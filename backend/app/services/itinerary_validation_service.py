from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from datetime import time, datetime
from typing import Any, List, Dict, Optional, Tuple
from enum import Enum

from app.models.schemas import Itinerary, DayPlan, SpotItem, TripRequest


class ValidationStatus(Enum):
    """校验状态"""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class ValidationType(Enum):
    """校验类型"""
    BUDGET = "budget"
    DISTANCE = "distance"
    TRAVEL_TIME = "travel_time"
    OPENING_HOURS = "opening_hours"
    SCHEDULE = "schedule"


@dataclass
class ValidationIssue:
    """单个校验问题"""
    type: ValidationType
    status: ValidationStatus
    day_index: Optional[int] = None
    spot_name: Optional[str] = None
    message: str = ""
    suggestion: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """完整校验结果"""
    overall_status: ValidationStatus
    issues: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    def has_errors(self) -> bool:
        return any(issue.status == ValidationStatus.ERROR for issue in self.issues)
    
    def has_warnings(self) -> bool:
        return any(issue.status == ValidationStatus.WARNING for issue in self.issues)
    
    def get_issues_by_type(self, issue_type: ValidationType) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.type == issue_type]
    
    def get_warnings(self) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.status == ValidationStatus.WARNING]
    
    def get_errors(self) -> List[ValidationIssue]:
        return [issue for issue in self.issues if issue.status == ValidationStatus.ERROR]


class ItineraryValidationService:
    """行程合理性校验服务"""
    
    # 默认配置
    DEFAULT_CONFIG = {
        # 距离相关 (公里)
        "max_daily_distance_km": 150,  # 每日最大合理行驶距离
        "warning_distance_km": 80,  # 触发警告的距离
        "min_spot_spacing_km": 0.5,  # 景点间最小合理间距
        
        # 时间相关 (分钟)
        "max_daily_travel_time": 180,  # 每日最大交通时间
        "min_visit_duration": 60,  # 最小游览时间
        "max_spot_per_day": 5,  # 每日最大景点数
        
        # 预算相关
        "budget_tolerance_ratio": 0.2,  # 预算允许超出比例 (20%)
        "budget_warning_ratio": 0.1,  # 预算警告比例
        
        # 营业时间
        "default_opening_start": "08:00",
        "default_opening_end": "18:00",
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
    
    def validate_itinerary(
        self, 
        itinerary: Itinerary, 
        trip_request: Optional[TripRequest] = None
    ) -> ValidationResult:
        """
        完整校验行程
        
        Args:
            itinerary: 行程数据
            trip_request: 原始行程请求（包含预算等信息）
            
        Returns:
            完整校验结果
        """
        issues: List[ValidationIssue] = []
        
        # 1. 预算校验
        if trip_request:
            budget_issues = self._validate_budget(itinerary, trip_request)
            issues.extend(budget_issues)
        
        # 2. 逐日校验
        for day_plan in itinerary.days:
            day_issues = self._validate_day(day_plan)
            issues.extend(day_issues)
        
        # 3. 计算整体状态
        overall_status = self._calculate_overall_status(issues)
        
        # 4. 生成摘要
        summary = self._generate_summary(itinerary, issues, trip_request)
        
        return ValidationResult(
            overall_status=overall_status,
            issues=issues,
            summary=summary
        )
    
    def _validate_budget(self, itinerary: Itinerary, trip_request: TripRequest) -> List[ValidationIssue]:
        """校验预算"""
        issues: List[ValidationIssue] = []
        
        requested_budget = trip_request.budget
        estimated_budget = itinerary.estimated_budget
        travelers = trip_request.travelers
        
        if estimated_budget <= 0:
            return issues
        
        # 计算预算差异
        budget_diff = estimated_budget - requested_budget
        budget_ratio = budget_diff / requested_budget if requested_budget > 0 else 0
        
        details = {
            "requested_budget": requested_budget,
            "estimated_budget": estimated_budget,
            "budget_difference": budget_diff,
            "budget_ratio": budget_ratio,
            "travelers": travelers,
            # budget 现在是人均，不再需要除以travelers
            "per_person_budget": requested_budget,
            "per_person_estimated": estimated_budget,
            "total_group_budget": requested_budget * travelers,
            "total_group_estimated": estimated_budget * travelers,
            "budget_breakdown": itinerary.budget_breakdown.model_dump() if itinerary.budget_breakdown else None
        }
        
        tolerance = self.config["budget_tolerance_ratio"]
        warning_ratio = self.config["budget_warning_ratio"]
        
        if budget_ratio > tolerance:
            issues.append(ValidationIssue(
                type=ValidationType.BUDGET,
                status=ValidationStatus.ERROR,
                message=f"人均预算超出 {budget_ratio*100:.0f}%！预估 ¥{estimated_budget:.0f}/人，您设定 ¥{requested_budget:.0f}/人",
                suggestion=f"建议减少景点数量、降低住宿或餐饮标准，或增加人均预算至 ¥{estimated_budget:.0f}",
                details=details
            ))
        elif budget_ratio > warning_ratio:
            issues.append(ValidationIssue(
                type=ValidationType.BUDGET,
                status=ValidationStatus.WARNING,
                message=f"人均预算可能超出 {budget_ratio*100:.0f}%，预估 ¥{estimated_budget:.0f}/人",
                suggestion="注意控制额外支出",
                details=details
            ))
        
        return issues
    
    def _validate_day(self, day_plan: DayPlan) -> List[ValidationIssue]:
        """校验单日行程"""
        issues: List[ValidationIssue] = []
        
        # 1. 景点数量校验
        spot_count = len(day_plan.spots)
        if spot_count > self.config["max_spot_per_day"]:
            issues.append(ValidationIssue(
                type=ValidationType.SCHEDULE,
                status=ValidationStatus.WARNING,
                day_index=day_plan.day_index,
                message=f"当日安排了 {spot_count} 个景点，建议不超过 {self.config['max_spot_per_day']} 个",
                suggestion="减少当日景点数量或拆分到其他天"
            ))
        
        # 2. 距离和交通时间校验
        distance_issues = self._validate_distances(day_plan)
        issues.extend(distance_issues)
        
        # 3. 营业时间校验
        opening_issues = self._validate_opening_hours(day_plan)
        issues.extend(opening_issues)
        
        return issues
    
    def _validate_distances(self, day_plan: DayPlan) -> List[ValidationIssue]:
        """校验景点间距离和交通时间"""
        issues: List[ValidationIssue] = []
        
        spots = day_plan.spots
        if len(spots) < 2:
            return issues
        
        total_distance = 0.0
        total_travel_time = 0
        
        for i in range(len(spots) - 1):
            spot1 = spots[i]
            spot2 = spots[i + 1]
            
            # 计算距离
            distance = self._calculate_distance(spot1, spot2)
            
            if distance is not None:
                total_distance += distance
                
                # 单段距离校验
                if distance > self.config["warning_distance_km"]:
                    issues.append(ValidationIssue(
                        type=ValidationType.DISTANCE,
                        status=ValidationStatus.WARNING,
                        day_index=day_plan.day_index,
                        spot_name=f"{spot1.name} → {spot2.name}",
                        message=f"景点间距离较远：{distance:.1f} 公里",
                        suggestion="考虑调整顺序或增加交通时间",
                        details={"distance_km": distance}
                    ))
                
                # 估算交通时间
                travel_time = self._estimate_travel_time(distance)
                total_travel_time += travel_time
        
        # 总距离校验
        if total_distance > self.config["max_daily_distance_km"]:
            issues.append(ValidationIssue(
                type=ValidationType.DISTANCE,
                status=ValidationStatus.ERROR,
                day_index=day_plan.day_index,
                message=f"当日总行驶距离过长：{total_distance:.1f} 公里",
                suggestion="重新规划路线，减少跨区域移动",
                details={"total_distance_km": total_distance}
            ))
        
        # 总交通时间校验
        if total_travel_time > self.config["max_daily_travel_time"]:
            issues.append(ValidationIssue(
                type=ValidationType.TRAVEL_TIME,
                status=ValidationStatus.WARNING,
                day_index=day_plan.day_index,
                message=f"当日交通时间预计 {total_travel_time} 分钟，可能影响游览体验",
                suggestion="优化路线或减少景点",
                details={"total_travel_minutes": total_travel_time}
            ))
        
        return issues
    
    def _validate_opening_hours(self, day_plan: DayPlan) -> List[ValidationIssue]:
        """校验营业时间"""
        issues: List[ValidationIssue] = []
        
        for spot in day_plan.spots:
            if not spot.opening_hours:
                continue
            
            # 解析营业时间
            opening_info = self._parse_opening_hours(spot.opening_hours)
            
            if opening_info.get("is_closed", False):
                issues.append(ValidationIssue(
                    type=ValidationType.OPENING_HOURS,
                    status=ValidationStatus.ERROR,
                    day_index=day_plan.day_index,
                    spot_name=spot.name,
                    message=f"{spot.name} 可能不营业",
                    suggestion="更换其他景点或确认营业时间",
                    details=opening_info
                ))
            elif opening_info.get("limited_hours", False):
                issues.append(ValidationIssue(
                    type=ValidationType.OPENING_HOURS,
                    status=ValidationStatus.WARNING,
                    day_index=day_plan.day_index,
                    spot_name=spot.name,
                    message=f"{spot.name} 营业时间较短",
                    suggestion="安排在开放时段内游览",
                    details=opening_info
                ))
            
            # 如果有访问时间，校验是否在营业时间内
            if spot.start_time and spot.end_time:
                schedule_issue = self._validate_visit_schedule(spot, opening_info)
                if schedule_issue:
                    issues.append(schedule_issue)
        
        return issues
    
    def _validate_visit_schedule(self, spot: SpotItem, opening_info: Dict) -> Optional[ValidationIssue]:
        """校验访问时间是否在营业时间内"""
        try:
            visit_start = self._parse_time_str(spot.start_time)
            visit_end = self._parse_time_str(spot.end_time)
            
            if not visit_start or not visit_end:
                return None
            
            opening_start = opening_info.get("start_time")
            opening_end = opening_info.get("end_time")
            
            if opening_start and opening_end:
                open_time = self._parse_time_str(opening_start)
                close_time = self._parse_time_str(opening_end)
                
                if open_time and close_time:
                    if visit_start < open_time:
                        return ValidationIssue(
                            type=ValidationType.SCHEDULE,
                            status=ValidationStatus.WARNING,
                            spot_name=spot.name,
                            message=f"访问时间 {spot.start_time} 早于营业时间 {opening_start}",
                            suggestion="调整访问时间"
                        )
                    
                    if visit_end > close_time:
                        return ValidationIssue(
                            type=ValidationType.SCHEDULE,
                            status=ValidationStatus.WARNING,
                            spot_name=spot.name,
                            message=f"访问时间 {spot.end_time} 晚于营业时间 {opening_end}",
                            suggestion="调整访问时间"
                        )
        except Exception:
            pass
        
        return None
    
    def _calculate_distance(self, spot1: SpotItem, spot2: SpotItem) -> Optional[float]:
        """计算两个景点之间的距离（公里）"""
        if (spot1.latitude is None or spot1.longitude is None or
            spot2.latitude is None or spot2.longitude is None):
            return None
        
        # Haversine公式计算球面距离
        R = 6371  # 地球半径（公里）
        
        lat1 = math.radians(spot1.latitude)
        lon1 = math.radians(spot1.longitude)
        lat2 = math.radians(spot2.latitude)
        lon2 = math.radians(spot2.longitude)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def _estimate_travel_time(self, distance_km: float) -> int:
        """根据距离估算交通时间（分钟）"""
        # 假设平均时速 30-40 公里
        avg_speed_kmh = 35
        return int((distance_km / avg_speed_kmh) * 60)
    
    def _parse_opening_hours(self, opening_text: str) -> Dict[str, Any]:
        """解析营业时间文本"""
        result = {
            "raw": opening_text,
            "is_closed": False,
            "limited_hours": False,
            "start_time": None,
            "end_time": None
        }
        
        # 检测是否关闭
        closed_keywords = ["关闭", "不开放", "维修", "暂停", "停业"]
        if any(keyword in opening_text for keyword in closed_keywords):
            result["is_closed"] = True
            return result
        
        # 尝试提取时间
        time_pattern = r'(\d{1,2}):?(\d{2})?[-~至到](\d{1,2}):?(\d{2})?'
        match = re.search(time_pattern, opening_text)
        
        if match:
            start_hour = match.group(1)
            start_min = match.group(2) or "00"
            end_hour = match.group(3)
            end_min = match.group(4) or "00"
            
            result["start_time"] = f"{start_hour.zfill(2)}:{start_min}"
            result["end_time"] = f"{end_hour.zfill(2)}:{end_min}"
            
            # 检查是否营业时间短
            try:
                start_h = int(start_hour)
                end_h = int(end_hour)
                duration = end_h - start_h
                if duration < 4:
                    result["limited_hours"] = True
            except ValueError:
                pass
        
        return result
    
    def _parse_time_str(self, time_str: str) -> Optional[time]:
        """解析时间字符串"""
        try:
            # 处理 "HH:MM" 格式
            if ":" in time_str:
                parts = time_str.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                return time(hour=hour, minute=minute)
            
            # 处理 "HHMM" 格式
            if len(time_str) >= 3:
                hour = int(time_str[:2])
                minute = int(time_str[2:])
                return time(hour=hour, minute=minute)
        except (ValueError, IndexError):
            pass
        
        return None
    
    def _calculate_overall_status(self, issues: List[ValidationIssue]) -> ValidationStatus:
        """计算整体状态"""
        if any(issue.status == ValidationStatus.ERROR for issue in issues):
            return ValidationStatus.ERROR
        elif any(issue.status == ValidationStatus.WARNING for issue in issues):
            return ValidationStatus.WARNING
        return ValidationStatus.OK
    
    def _generate_summary(
        self, 
        itinerary: Itinerary, 
        issues: List[ValidationIssue],
        trip_request: Optional[TripRequest] = None
    ) -> Dict[str, Any]:
        """生成校验摘要"""
        summary = {
            "total_days": len(itinerary.days),
            "total_spots": sum(len(day.spots) for day in itinerary.days),
            "total_issues": len(issues),
            "error_count": sum(1 for i in issues if i.status == ValidationStatus.ERROR),
            "warning_count": sum(1 for i in issues if i.status == ValidationStatus.WARNING),
            "issues_by_type": {}
        }
        
        # 按类型统计
        for issue_type in ValidationType:
            type_issues = [i for i in issues if i.type == issue_type]
            summary["issues_by_type"][issue_type.value] = len(type_issues)
        
        # 预算信息
        if trip_request:
            summary["budget_info"] = {
                "requested": trip_request.budget,
                "estimated": itinerary.estimated_budget,
                "travelers": trip_request.travelers
            }
        
        return summary


# 全局服务实例
_validation_service: Optional[ItineraryValidationService] = None


def get_itinerary_validation_service(config: Optional[Dict[str, Any]] = None) -> ItineraryValidationService:
    """获取行程校验服务单例"""
    global _validation_service
    if _validation_service is None:
        _validation_service = ItineraryValidationService(config)
    return _validation_service
