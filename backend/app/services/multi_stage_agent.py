from __future__ import annotations

import logging
import threading
import asyncio
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from app.models.schemas import TripRequest, Itinerary
from app.services.tracing_service import TracingService, TraceContext


logger = logging.getLogger(__name__)

# 异步任务存储
_async_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()


class StageStatus(Enum):
    """阶段状态"""
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()


class PipelineMode(Enum):
    """流水线执行模式"""
    FAST = "fast"  # 快速模式：仅行程规划
    FULL = "full"  # 完整模式：所有阶段
    ASYNC = "async"  # 异步模式：行程规划+异步补充其他数据


class StageType(Enum):
    """阶段类型"""
    TRIP_PLANNING = "trip_planning"
    MAP_ENRICHMENT = "map_enrichment"
    WEATHER_CHECK = "weather_check"
    TICKET_CHECK = "ticket_check"
    CONSISTENCY_VALIDATION = "consistency_validation"


@dataclass
class StageResult:
    """单个阶段的执行结果"""
    stage_type: StageType
    status: StageStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    output: Any = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_type": self.stage_type.value,
            "status": self.status.name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "warnings": self.warnings,
            "metadata": self.metadata
        }


@dataclass
class PipelineContext:
    """流水线上下文，在各阶段间传递数据"""
    trip_request: TripRequest
    itinerary: Optional[Itinerary] = None
    rag_contexts: List[str] = field(default_factory=list)
    weather_data: Optional[Dict[str, Any]] = None
    ticket_data: Optional[Dict[str, float]] = None
    validation_result: Optional[Any] = None
    custom_data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    trace_ctx: Optional[TraceContext] = None

    def get_stage_data(self, stage_type: StageType, key: str, default: Any = None) -> Any:
        """获取特定阶段的数据"""
        return self.custom_data.get(f"{stage_type.value}_{key}", default)

    def set_stage_data(self, stage_type: StageType, key: str, value: Any) -> None:
        """设置特定阶段的数据"""
        self.custom_data[f"{stage_type.value}_{key}"] = value


@dataclass
class PipelineResult:
    """完整流水线执行结果"""
    success: bool
    context: PipelineContext
    stage_results: Dict[StageType, StageResult] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_duration_ms: Optional[float] = None
    final_error: Optional[str] = None

    def get_summary(self) -> Dict[str, Any]:
        completed = sum(1 for r in self.stage_results.values() 
                       if r.status == StageStatus.COMPLETED)
        failed = sum(1 for r in self.stage_results.values() 
                    if r.status == StageStatus.FAILED)
        warnings = []
        for result in self.stage_results.values():
            warnings.extend(result.warnings)
        warnings.extend(self.context.warnings)

        return {
            "success": self.success,
            "total_stages": len(self.stage_results),
            "completed_stages": completed,
            "failed_stages": failed,
            "total_warnings": len(warnings),
            "total_duration_ms": self.total_duration_ms,
            "stage_results": {
                st.value: res.to_dict()
                for st, res in self.stage_results.items()
            }
        }


class StageProcessor:
    """单个阶段的处理器基类"""

    def __init__(self, stage_type: StageType, name: str):
        self.stage_type = stage_type
        self.name = name

    def can_process(self, context: PipelineContext) -> bool:
        """检查是否可以处理当前阶段（依赖检查）"""
        return True

    def execute(self, context: PipelineContext) -> StageResult:
        """执行阶段逻辑（子类实现）"""
        raise NotImplementedError

    def __call__(self, context: PipelineContext) -> StageResult:
        """调用执行，添加时间测量和错误处理"""
        result = StageResult(stage_type=self.stage_type, status=StageStatus.RUNNING)
        result.start_time = datetime.now()

        try:
            logger.info(f"🚀 执行阶段: {self.name}")

            if not self.can_process(context):
                result.status = StageStatus.SKIPPED
                result.warnings.append("跳过此阶段，依赖条件未满足")
            else:
                stage_output = self.execute(context)
                result.output = stage_output
                result.status = StageStatus.COMPLETED

        except Exception as e:
            logger.exception(f"❌ 阶段执行失败: {self.name}")
            result.status = StageStatus.FAILED
            result.error = str(e)

        result.end_time = datetime.now()
        if result.start_time and result.end_time:
            delta = result.end_time - result.start_time
            result.duration_ms = delta.total_seconds() * 1000

        logger.info(f"✅ 阶段完成: {self.name}, 状态: {result.status.name}, 耗时: {result.duration_ms:.1f}ms")
        return result


class TripPlanningStage(StageProcessor):
    """第一阶段：行程规划生成（仅 RAG + LLM + 基础 itinerary）"""

    def __init__(self, use_high_quality_mode: bool = False):
        super().__init__(StageType.TRIP_PLANNING, "行程规划")
        self.use_high_quality_mode = use_high_quality_mode

    def execute(self, context: PipelineContext) -> Any:
        from app.services.trip_service import (
            collect_rag_contexts,
            generate_llm_draft,
            build_raw_days_data_without_tickets,
            calculate_budget_allocations_without_tickets,
            build_day_plans,
            generate_tips_basic,
            build_basic_itinerary,
        )

        logger.info("📝 生成行程规划...")

        request = context.trip_request
        if request.days and request.days > 0:
            day_count = request.days
        else:
            day_count = (request.end_date - request.start_date).days + 1
            day_count = max(day_count, 1)

        # 子阶段1: 收集 RAG 上下文（默认不使用 LLM rewrite）
        rag_contexts = collect_rag_contexts(request, context.trace_ctx, use_llm_rewrite=self.use_high_quality_mode)
        context.rag_contexts = rag_contexts

        # 子阶段2: 调用 LLM 生成草稿
        llm_draft = generate_llm_draft(request, rag_contexts, day_count)

        # 子阶段3: 构建原始天数数据（不提取票价）
        raw_days = build_raw_days_data_without_tickets(request, llm_draft, rag_contexts, day_count)

        # 子阶段4: 计算预算分配（不包含票价）
        daily_hotel_costs, daily_meal_costs, daily_transport_costs = calculate_budget_allocations_without_tickets(
            request, day_count
        )

        # 子阶段5: 构建 DayPlan 对象
        days, attraction_names, attraction_descriptions = build_day_plans(
            request, raw_days, daily_hotel_costs, daily_meal_costs, daily_transport_costs
        )

        # 子阶段6: 生成基础提示信息（不包含天气）
        tips = generate_tips_basic(request, llm_draft, rag_contexts, attraction_names, attraction_descriptions)

        # 子阶段7: 构建基础 Itinerary 对象（不包含地图和校验）
        itinerary = build_basic_itinerary(request, llm_draft, days, tips, rag_contexts, day_count)
        context.itinerary = itinerary

        logger.info(f"✅ 行程规划生成完成，共 {len(itinerary.days)} 天")
        return {"days": len(itinerary.days), "destination": itinerary.destination}


class MapEnrichmentStage(StageProcessor):
    """第二阶段：地图数据补充"""

    def __init__(self):
        super().__init__(StageType.MAP_ENRICHMENT, "地图数据补充")

    def can_process(self, context: PipelineContext) -> bool:
        return context.itinerary is not None

    def execute(self, context: PipelineContext) -> Any:
        from app.services.trip_service import enrich_map_data_only

        logger.info("🗺️ 补充地图数据...")

        try:
            enriched = enrich_map_data_only(
                context.itinerary,
                context.trip_request
            )
            context.itinerary = enriched

            # 计算距离数据
            spots_with_coords = 0
            for day in context.itinerary.days:
                for spot in day.spots:
                    if spot.latitude is not None and spot.longitude is not None:
                        spots_with_coords += 1

            logger.info(f"✅ 地图数据补充完成，{spots_with_coords} 个景点有坐标")
            context.set_stage_data(self.stage_type, "spots_with_coords", spots_with_coords)

            return {"spots_with_coords": spots_with_coords}

        except Exception as e:
            logger.warning(f"地图数据补充失败: {e}")
            context.warnings.append(f"地图数据补充失败: {e}")
            return {"spots_with_coords": 0}


class WeatherCheckStage(StageProcessor):
    """第三阶段：天气数据检查"""

    def __init__(self):
        super().__init__(StageType.WEATHER_CHECK, "天气检查")

    def can_process(self, context: PipelineContext) -> bool:
        return context.itinerary is not None

    def execute(self, context: PipelineContext) -> Any:
        from app.services.weather_service import get_weather_forecast
        from app.services.trip_service import add_weather_tips_to_itinerary
        
        logger.info("🌤️ 获取天气数据...")
        
        try:
            weather = get_weather_forecast(context.trip_request.destination)
            context.weather_data = weather
            
            # 向 itinerary 中添加天气提示
            updated_itinerary = add_weather_tips_to_itinerary(context.itinerary, weather)
            context.itinerary = updated_itinerary
            
            days_available = len(weather.get("days", []))
            logger.info(f"✅ 天气数据获取完成，共 {days_available} 天预报")
            
            return {"days_available": days_available}
            
        except Exception as e:
            logger.warning(f"天气数据获取失败: {e}")
            context.warnings.append(f"天气数据获取失败: {e}")
            return {"days_available": 0}


class TicketCheckStage(StageProcessor):
    """第四阶段：票价数据检查"""

    def __init__(self):
        super().__init__(StageType.TICKET_CHECK, "票价检查")

    def can_process(self, context: PipelineContext) -> bool:
        return context.itinerary is not None

    def execute(self, context: PipelineContext) -> Any:
        from app.services.trip_service import parse_ticket_prices_from_rag, update_itinerary_with_tickets
        
        logger.info("🎫 提取票价数据...")
        
        # 从已经获取的 RAG 上下文中解析票价，避免重复查询
        ticket_map = parse_ticket_prices_from_rag(
            context.rag_contexts,
            context.trip_request.destination
        )
        context.ticket_data = ticket_map
        
        tickets_available = len(ticket_map) if ticket_map else 0
        logger.info(f"✅ 票价数据提取完成，共 {tickets_available} 个景点有票价")
        
        # 更新 itinerary 中的票价信息
        validated_count = 0
        if context.itinerary and ticket_map:
            updated_itinerary = update_itinerary_with_tickets(
                context.itinerary,
                ticket_map,
                context.trip_request
            )
            context.itinerary = updated_itinerary
            validated_count = sum(1 for day in context.itinerary.days 
                                 for spot in day.spots 
                                 if spot.name in ticket_map)
        
        return {"tickets_available": tickets_available, "validated_count": validated_count}


class ConsistencyValidationStage(StageProcessor):
    """第五阶段：一致性校验（最终检查）"""

    def __init__(self):
        super().__init__(StageType.CONSISTENCY_VALIDATION, "一致性校验")

    def can_process(self, context: PipelineContext) -> bool:
        return context.itinerary is not None

    def execute(self, context: PipelineContext) -> Any:
        from app.services.trip_service import validate_itinerary_only, refresh_budget_final

        logger.info("🔍 执行行程一致性校验...")

        # 先最终刷新预算
        itinerary_with_budget = refresh_budget_final(context.itinerary, context.trip_request)
        context.itinerary = itinerary_with_budget

        # 只进行校验
        validated = validate_itinerary_only(
            context.itinerary,
            context.trip_request
        )
        context.itinerary = validated

        # 统计提示中的校验信息
        error_count = 0
        warning_count = 0
        for tip in validated.tips:
            if "❌" in tip:
                error_count += 1
            elif "⚠️" in tip:
                warning_count += 1

        logger.info(f"✅ 校验完成")
        if error_count > 0:
            logger.warning(f"⚠️ 发现 {error_count} 个错误提示")
        if warning_count > 0:
            logger.info(f"📋 发现 {warning_count} 个警告提示")

        return {
            "has_errors": error_count > 0,
            "has_warnings": warning_count > 0,
            "error_count": error_count,
            "warning_count": warning_count,
            "overall_status": "completed"
        }


class MultiStagePipeline:
    """多阶段 Agent 流水线"""

    def __init__(self, use_high_quality_mode: bool = False):
        self.use_high_quality_mode = use_high_quality_mode
        self.full_stages: List[StageProcessor] = [
            TripPlanningStage(use_high_quality_mode=use_high_quality_mode),
            MapEnrichmentStage(),
            WeatherCheckStage(),
            TicketCheckStage(),
            ConsistencyValidationStage(),
        ]
        self.fast_stages: List[StageProcessor] = [
            TripPlanningStage(use_high_quality_mode=use_high_quality_mode),
        ]
        self.async_stages: List[StageProcessor] = [
            MapEnrichmentStage(),
            WeatherCheckStage(),
            TicketCheckStage(),
            ConsistencyValidationStage(),
        ]

    def add_stage(self, processor: StageProcessor, position: Optional[int] = None, mode: PipelineMode = PipelineMode.FULL) -> None:
        """添加阶段"""
        stages_list = None
        if mode == PipelineMode.FULL:
            stages_list = self.full_stages
        elif mode == PipelineMode.ASYNC:
            stages_list = self.async_stages
        
        if stages_list is not None:
            if position is not None:
                stages_list.insert(position, processor)
            else:
                stages_list.append(processor)

    def execute(self, trip_request: TripRequest, trace_ctx: Optional[TraceContext] = None, mode: PipelineMode = PipelineMode.FULL) -> PipelineResult:
        """执行流水线"""
        mode_name = mode.value
        logger.info("=" * 80)
        logger.info(f"🚀 启动多阶段 Agent 流水线 [模式: {mode_name}]")
        logger.info("=" * 80)

        context = PipelineContext(
            trip_request=trip_request,
            trace_ctx=trace_ctx
        )
        result = PipelineResult(
            success=True,
            context=context,
            start_time=datetime.now()
        )

        # 根据模式选择要执行的阶段
        stages = self._get_stages_for_mode(mode)
        logger.info(f"📋 执行阶段列表: {[s.name for s in stages]}")

        try:
            for idx, processor in enumerate(stages):
                stage_start = datetime.now()
                logger.info(f"⏱️  阶段 {idx+1}/{len(stages)} 开始: {processor.name}")
                
                stage_result = processor(context)
                result.stage_results[processor.stage_type] = stage_result

                stage_end = datetime.now()
                stage_duration = (stage_end - stage_start).total_seconds() * 1000
                logger.info(f"⏱️  阶段 {idx+1}/{len(stages)} 完成: {processor.name}, 耗时: {stage_duration:.1f}ms")

                if stage_result.status == StageStatus.FAILED:
                    result.success = False
                    result.final_error = stage_result.error

                # 记录到追踪
                if trace_ctx:
                    TracingService.add_agent_step(
                        trace_ctx,
                        step_index=list(result.stage_results.keys()).index(processor.stage_type),
                        state=stage_result.status.name,
                        thought=f"执行阶段: {processor.name}",
                        action=processor.stage_type.value
                    )

        except Exception as e:
            logger.exception("❌ 流水线执行异常")
            result.success = False
            result.final_error = str(e)

        result.end_time = datetime.now()
        if result.start_time and result.end_time:
            delta = result.end_time - result.start_time
            result.total_duration_ms = delta.total_seconds() * 1000

        logger.info("=" * 80)
        logger.info(f"✅ 流水线执行完成: {'成功' if result.success else '失败'}, 模式: {mode_name}, 总耗时: {result.total_duration_ms:.1f}ms")
        self._log_stage_breakdown(result)
        logger.info("=" * 80)

        return result

    def _get_stages_for_mode(self, mode: PipelineMode) -> List[StageProcessor]:
        """根据模式获取阶段列表"""
        if mode == PipelineMode.FAST:
            return self.fast_stages
        elif mode == PipelineMode.ASYNC:
            return self.fast_stages  # 异步模式也是先快速返回，再后台补充
        else:
            return self.full_stages

    def _log_stage_breakdown(self, result: PipelineResult) -> None:
        """记录各阶段耗时明细"""
        logger.info("📊 阶段耗时明细:")
        for stage_type, stage_result in result.stage_results.items():
            duration = stage_result.duration_ms or 0
            status_icon = "✅" if stage_result.status == StageStatus.COMPLETED else \
                         "⚠️" if stage_result.status == StageStatus.SKIPPED else "❌"
            logger.info(f"   {status_icon} {stage_type.value}: {duration:.1f}ms")
        
        if result.total_duration_ms:
            total = result.total_duration_ms
            logger.info(f"📈 总耗时: {total:.1f}ms ({total/1000:.2f}s)")

    def execute_async(self, trip_request: TripRequest, trace_ctx: Optional[TraceContext] = None, trip_id: Optional[str] = None) -> PipelineResult:
        """异步执行模式：快速返回行程，后台异步补充数据"""
        logger.info("=" * 80)
        logger.info("🚀 启动异步多阶段 Agent 流水线")
        logger.info("=" * 80)

        # 先快速执行行程规划
        fast_result = self.execute(trip_request, trace_ctx, PipelineMode.FAST)
        
        if fast_result.success and fast_result.context.itinerary:
            # 创建异步任务，后台补充其他数据
            if trip_id is None:
                trip_id = fast_result.context.itinerary.trip_id
            
            self._launch_async_enrichment(trip_id, fast_result.context)

        return fast_result

    def _launch_async_enrichment(self, task_id: str, context: PipelineContext) -> None:
        """启动后台异步数据补充任务"""
        def background_task():
            try:
                logger.info(f"🔄 后台异步任务开始: {task_id}")
                task_start = datetime.now()
                
                # 更新任务状态
                with _tasks_lock:
                    _async_tasks[task_id] = {
                        "status": "running",
                        "start_time": task_start.isoformat(),
                        "trip_id": task_id,
                        "stages_completed": []
                    }

                # 异步执行补充阶段
                stages_completed = []
                for processor in self.async_stages:
                    try:
                        stage_start = datetime.now()
                        logger.info(f"🔄 异步阶段开始: {processor.name}")
                        
                        stage_result = processor(context)
                        
                        stage_end = datetime.now()
                        stage_duration = (stage_end - stage_start).total_seconds() * 1000
                        logger.info(f"🔄 异步阶段完成: {processor.name}, 耗时: {stage_duration:.1f}ms")
                        
                        stages_completed.append(processor.stage_type.value)
                        
                        # 更新任务状态
                        with _tasks_lock:
                            if task_id in _async_tasks:
                                _async_tasks[task_id]["stages_completed"] = stages_completed
                        
                    except Exception as e:
                        logger.warning(f"⚠️ 异步阶段执行失败: {processor.name}, 错误: {e}")
                
                task_end = datetime.now()
                total_duration = (task_end - task_start).total_seconds() * 1000
                logger.info(f"🔄 后台异步任务完成: {task_id}, 总耗时: {total_duration:.1f}ms")
                
                # 完成任务状态
                with _tasks_lock:
                    if task_id in _async_tasks:
                        _async_tasks[task_id].update({
                            "status": "completed",
                            "end_time": task_end.isoformat(),
                            "duration_ms": total_duration
                        })
                        
            except Exception as e:
                logger.exception(f"❌ 后台异步任务异常: {task_id}")
                with _tasks_lock:
                    if task_id in _async_tasks:
                        _async_tasks[task_id].update({
                            "status": "failed",
                            "error": str(e)
                        })

        # 在新线程中执行后台任务
        thread = threading.Thread(target=background_task, daemon=True)
        thread.start()
        logger.info(f"🚀 后台异步任务已启动: {task_id}")


# 全局流水线实例
_pipeline_instance: Optional[MultiStagePipeline] = None


def get_pipeline() -> MultiStagePipeline:
    """获取多阶段流水线实例"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = MultiStagePipeline()
    return _pipeline_instance


def get_async_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """获取异步任务状态"""
    with _tasks_lock:
        return _async_tasks.get(task_id)


def list_async_tasks() -> List[Dict[str, Any]]:
    """列出所有异步任务"""
    with _tasks_lock:
        return list(_async_tasks.values())


def clear_async_tasks() -> int:
    """清理已完成的异步任务，返回清理的数量"""
    with _tasks_lock:
        completed_tasks = [
            tid for tid, task in _async_tasks.items()
            if task.get("status") in ("completed", "failed")
        ]
        for tid in completed_tasks:
            del _async_tasks[tid]
        return len(completed_tasks)
