from __future__ import annotations

import logging
import hashlib
import json
import math
from datetime import date as DateType, timedelta
from typing import Dict, Optional, Any

from app.agents.trip_planner_agent import (
    PlannerDraft,
    collect_trip_context,
    generate_day_edit_draft,
    generate_planner_draft,
)
from app.config import ENABLE_AMAP_ENRICHMENT, REDIS_LLM_DRAFT_TTL_SECONDS
from app.models.schemas import (
    BudgetBreakdown,
    DayPlan,
    HotelItem,
    Itinerary,
    MealItem,
    SpotItem,
    TransportItem,
    TripEditRequest,
    TripRequest,
)
from app.services.rule_service import get_rule_service
from app.services.cache_service import get_cached_json, set_cached_json
from app.services.map_service import enrich_itinerary_with_map_data
from app.services.ticket_service import extract_ticket_info, get_ticket_price
from app.services.weather_service import get_weather_forecast
from app.services.itinerary_validation_service import get_itinerary_validation_service
from app.services.tracing_service import TracingService

# Logger 初始化
logger = logging.getLogger(__name__)


def _generate_weather_tips(weather_data: dict, destination: str | None = None) -> list[str]:
    """根据天气数据生成天气相关的提示。"""
    rule_service = get_rule_service()
    weather_tips: list[str] = []
    
    if not weather_data or "days" not in weather_data or not weather_data["days"]:
        return weather_tips
    
    days = weather_data["days"]
    if not days:
        return weather_tips
    
    # 获取第一天或今天的天气
    today = days[0]
    day_weather = today.get("day_weather", "")
    night_weather = today.get("night_weather", "")
    day_temp = today.get("day_temp", "")
    night_temp = today.get("night_temp", "")
    
    # 根据天气关键词匹配模板
    matched_keywords = []
    all_weather_keywords = rule_service.get_all_weather_keywords()
    for keyword in all_weather_keywords:
        if keyword in day_weather or keyword in night_weather:
            matched_keywords.append(keyword)
            templates = rule_service.get_weather_tip_templates(keyword)
            if templates and len(weather_tips) < 2:
                weather_tips.append(templates[0])
    
    # 温度相关提示
    try:
        if day_temp and night_temp:
            day_temp_num = int(day_temp) if day_temp.isdigit() else 0
            night_temp_num = int(night_temp) if night_temp.isdigit() else 0
            
            if day_temp_num >= 30:
                weather_tips.append(f"白天气温较高（{day_temp}℃），注意防暑降温，多喝水。")
            elif day_temp_num <= 10:
                weather_tips.append(f"气温较低（{day_temp}℃），注意保暖。")
            
            if abs(day_temp_num - night_temp_num) >= 8:
                weather_tips.append(f"早晚温差较大（{abs(day_temp_num - night_temp_num)}℃），建议带一件薄外套。")
    except Exception:
        pass
    
    return weather_tips


def _identify_attraction_types(spot_name: str, spot_description: str | None = None) -> list[str]:
    """
    根据景点名称和描述识别景点类型

    Args:
        spot_name: 景点名称
        spot_description: 景点描述

    Returns:
        景点类型列表
    """
    rule_service = get_rule_service()
    types = set()
    combined_text = f"{spot_name} {spot_description or ''}"
    attraction_keywords = rule_service.get_attraction_keywords()

    for type_name, keywords in attraction_keywords.items():
        for keyword in keywords:
            if keyword in combined_text:
                types.add(type_name)
                break

    return list(types)


def _generate_attraction_tips(attraction_types: list[str]) -> list[str]:
    """
    根据景点类型生成相关提示

    Args:
        attraction_types: 景点类型列表

    Returns:
        相关提示列表
    """
    rule_service = get_rule_service()
    attraction_tips: list[str] = []

    for type_name in attraction_types:
        tips_for_type = rule_service.get_attraction_type_tips(type_name)
        if tips_for_type:
            attraction_tips.append(tips_for_type[0])

    return attraction_tips


def _generate_dynamic_tips(destination: str, weather_data: dict | None = None, rag_contexts: list[str] | None = None,
                           attraction_names: list[str] | None = None, attraction_descriptions: list[str] | None = None) -> list[str]:
    """
    综合生成动态旅行提示：
    1. 城市特定提示 + 天气相关提示 + 景点类型提示 + 通用提示

    Args:
        destination: 目的地城市
        weather_data: 天气数据（可选）
        rag_contexts: RAG 上下文（可选）
        attraction_names: 景点名称列表（可选）
        attraction_descriptions: 景点描述列表（可选）

    Returns:
        综合提示列表
    """
    rule_service = get_rule_service()
    all_tips: list[str] = []

    # 1. 首先添加城市特定提示
    city_tips = rule_service.get_city_specific_tips(destination)
    if city_tips:
        all_tips.extend(city_tips[:2])  # 取前2条城市特定提示

    # 2. 添加天气相关提示
    if weather_data:
        weather_tips = _generate_weather_tips(weather_data, destination)
        all_tips.extend(weather_tips)

    # 3. 添加景点类型相关提示
    if attraction_names:
        attraction_types = set()
        for i, name in enumerate(attraction_names):
            desc = attraction_descriptions[i] if attraction_descriptions and i < len(attraction_descriptions) else None
            types = _identify_attraction_types(name, desc)
            attraction_types.update(types)

        attraction_tips = _generate_attraction_tips(list(attraction_types))
        # 确保不重复添加
        for tip in attraction_tips:
            if tip not in all_tips:
                all_tips.append(tip)

    # 4. 如果有 RAG 上下文，添加相关提示
    if rag_contexts:
        dynamic_tip_config = rule_service.get_city_dynamic_tips(destination)
        if dynamic_tip_config:
            rag_keywords = dynamic_tip_config.get("rag_keywords", [])
            if any(any(kw in context for kw in rag_keywords) for context in rag_contexts):
                all_tips.append(dynamic_tip_config["tip"])

    # 5. 如果提示太少的话添加通用提示
    if len(all_tips) < 3:
        needed = 3 - len(all_tips)
        generic_tips = rule_service.get_generic_tips()
        all_tips.extend(generic_tips[:needed])

    return all_tips


def _clean_user_tips(tips: list[str], destination: str | None = None) -> list[str]:
    """过滤内部实现说明，只保留用户真正能用到的旅行建议。"""
    rule_service = get_rule_service()
    cleaned_tips: list[str] = []

    # 获取需要过滤的其他城市关键词
    keywords_to_filter = set()
    city_filter_keywords = rule_service.get_city_filter_keywords()
    for city, keywords in city_filter_keywords.items():
        if destination != city:
            keywords_to_filter.update(keywords)

    technical_keywords = rule_service.get_technical_tip_keywords()
    for tip in tips:
        normalized_tip = tip.strip()
        if not normalized_tip:
            continue
        if any(keyword in normalized_tip for keyword in technical_keywords):
            continue
        # 如果提示中包含其他城市的关键词，过滤掉
        if destination and any(keyword in normalized_tip for keyword in keywords_to_filter):
            continue
        if normalized_tip not in cleaned_tips:
            cleaned_tips.append(normalized_tip)

    if cleaned_tips:
        return cleaned_tips

    # 如果没有清理出有效的提示，使用城市特定提示或通用提示
    return _get_destination_specific_tips(destination)


def _get_destination_specific_tips(destination: str | None = None) -> list[str]:
    """根据目的地获取特定的旅行提示，如果没有匹配则返回通用提示。"""
    rule_service = get_rule_service()
    if destination:
        city_tips = rule_service.get_city_specific_tips(destination)
        if city_tips:
            return city_tips
    return rule_service.get_generic_tips()


def _build_demo_spot_names(destination: str, rag_contexts: list[str], day_count: int) -> list[str]:
    """从攻略片段里挑出更像样的演示景点名称。"""
    rule_service = get_rule_service()
    candidate_names: list[str] = []
    joined_context = "\n".join(rag_contexts)

    # 从规则中获取演示景点名称
    demo_spots = rule_service.get_demo_spot_names(destination)
    for spot in demo_spots:
        if spot in joined_context:
            candidate_names.append(spot)

    while len(candidate_names) < day_count:
        candidate_names.append(f"{destination} 推荐景点 {len(candidate_names) + 1}")

    return candidate_names[:day_count]


def _stable_bucket(text: str, modulo: int) -> int:
    """基于文本生成一个稳定桶值，用来做确定性的价格浮动。"""
    return sum(ord(char) for char in text) % modulo if modulo > 0 else 0


def _prorate_amounts(total: float, weights: list[float]) -> list[float]:
    """按权重拆分金额，同时保证拆分后的总和与原总额一致。"""
    if not weights:
        return []

    safe_weights = [max(weight, 0.01) for weight in weights]
    total_cents = max(int(round(total * 100)), 0)
    weight_sum = sum(safe_weights)
    raw_cents = [(total_cents * weight) / weight_sum for weight in safe_weights]
    base_cents = [int(value) for value in raw_cents]
    remainder = total_cents - sum(base_cents)

    ranked_indexes = sorted(
        range(len(raw_cents)),
        key=lambda index: (raw_cents[index] - base_cents[index], -index),
        reverse=True,
    )
    for index in ranked_indexes[:remainder]:
        base_cents[index] += 1

    return [round(value / 100, 2) for value in base_cents]


def _estimate_ticket_cost(spot_name: str, description: str | None = None, destination: str | None = None, ticket_map: Dict[str, float] | None = None) -> float:
    """根据景点关键词估算门票，优先从攻略文档中提取真实价格。"""
    rule_service = get_rule_service()
    # 如果提供了目的地，优先从攻略文档中获取真实门票价格
    if destination:
        try:
            price = get_ticket_price(spot_name, destination, ticket_map)
            return price
        except Exception as e:
            logger.debug(f"从攻略文档获取门票价格失败: {e}")
    
    # 回退到基于关键词的估算
    text = f"{spot_name} {description or ''}"
    bucket = _stable_bucket(text, 4)
    
    ticket_rules = rule_service.get_ticket_price_rules()
    for rule in ticket_rules:
        if any(keyword in text for keyword in rule["keywords"]):
            base_price = rule["base_price"]
            variance = rule["price_variance"]
            if variance == 0:
                return base_price
            return round(base_price + (bucket * variance / 3), 2)
    
    # 默认价格
    default_price = rule_service.get_default_ticket_price()
    return round(default_price["base_price"] + (bucket * default_price["price_variance"] / 3), 2)


def _build_hotel_weights(night_count: int, start_date: DateType) -> list[float]:
    """让住宿费用按周末、尾日、旺季等因素浮动。night_count = day_count - 1（最后一天不住宿）。"""
    weights: list[float] = []
    for index in range(night_count):
        current_date = start_date + timedelta(days=index)
        weight = 1.0
        # 周末溢价（周五、周六）
        if current_date.weekday() in (4, 5):
            weight += 0.18
        # 最后一晚离开日加成
        if index == night_count - 1:
            weight += 0.08
        # 隔天微调
        if index % 2 == 1:
            weight += 0.05
        # 旺季加成（国庆：10/1-10/7，春节：农历正月初一到初七）
        month, day = current_date.month, current_date.day
        if (month == 10 and 1 <= day <= 7) or (month == 2 and 8 <= day <= 14) or (month == 5 and 1 <= day <= 5):
            weight += 0.35
        elif (month == 7 or month == 8):  # 暑期
            weight += 0.15
        weights.append(weight)
    return weights


def _build_meal_weights(day_count: int, preferences: list[str]) -> list[float]:
    """让美食偏好的用户在部分天数获得更高餐饮预算。"""
    foodie_bonus = 0.12 if "美食" in preferences else 0.0
    return [
        1.0 + foodie_bonus + (0.08 if index == day_count // 2 else 0.0) + ((index % 3) * 0.04)
        for index in range(day_count)
    ]


def _build_transport_weights(day_count: int, pace: str | None) -> list[float]:
    """让交通预算随行程节奏和首尾日轻微浮动。"""
    pace_bonus = 0.12 if pace == "紧凑" else -0.04 if pace == "轻松" else 0.04
    return [
        1.0 + pace_bonus + (0.16 if index in (0, day_count - 1) else 0.0) + (index * 0.03)
        for index in range(day_count)
    ]


def _apply_route_based_transport_costs(itinerary: Itinerary) -> None:
    """在已有路线距离时，用路线信息修正交通花费和耗时。"""
    for day in itinerary.days:
        for transport in day.transport:
            if transport.estimated_minutes is not None:
                transport.duration = f"{transport.estimated_minutes} 分钟"

            if transport.distance_km is None:
                continue

            mode = transport.mode or ""
            if "公交" in mode:
                cost = max(2.0, 2.0 + (transport.distance_km * 0.25))
            elif "步行" in mode:
                cost = 0.0
            elif "包车" in mode:
                cost = 30.0 + (transport.distance_km * 3.8)
            else:
                cost = 10.0 + (transport.distance_km * 2.2)

            transport.estimated_cost = round(cost, 2)


def _haversine_distance(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """计算两点间的球面距离（单位：km）。使用 Haversine 公式。"""
    R = 6371.0  # 地球半径（km）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _select_smart_hotels(
    city: str,
    hotel_level: str,
    night_count: int,
    daily_hotel_costs: list[float],
    daily_spots: list[list[tuple[float, float]]],
    start_date: DateType,
) -> list[dict[str, Any]]:
    """
    基于预算和距离的智能酒店选择（V2：以距离为核心）。

    核心改进（相比V1）：
    - 距离权重提升至50%（从40%），连住奖励降至5%（从10%）
    - 每晚独立评分，优先选靠近当天景点的酒店
    - 连住阈值收紧至3km（从10km），超距必切
    - 新增"就近预筛"：按当天景点距离排序候选，取最近的前60%
    - 距离评分使用最大距离惩罚（最远景点>15km额外扣分）
    - 日志输出每家选中酒店的详细距离信息

    评分权重：距离55% + 预算/价格30% + 评分10% + 连住奖励5%

    V3修复：
    - 新增城市-景点一致性检查（景点距城市中心>50km时自动修正搜索城市）
    - 多区域采样搜索（市中心+多关键词，避免候选集中在单一偏远区域）
    - 候选距离上限保护（最近候选距景点>10km时发出警告）
    """
    logger.info(f"[smart_hotel] V3开始智能选址: city={city}, level={hotel_level}, nights={night_count}")

    # ---- 步骤0：参数校验与城市-景点一致性检查 ----
    # 主要城市中心点坐标(经度,纬度)，用于判断景点是否在目标城市范围内
    CITY_CENTER_COORDS: dict[str, tuple[float, float]] = {
        "长沙": (112.982279, 28.19477),
        "湘阴": (112.9009, 28.6812),
        "大理": (100.236, 25.6087),
        "成都": (104.065735, 30.659462),
        "西安": (108.948024, 34.263161),
        "厦门": (118.08939, 24.479836),
        "三亚": (109.5126, 18.2528),
        # 省会城市
        "武汉": (114.298572, 30.584355),
        "杭州": (120.15507, 30.274084),
        "南京": (118.767413, 32.041544),
        "北京": (116.407417, 39.904187),
        "上海": (121.473701, 31.230416),
        "广州": (113.264385, 23.129112),
        "深圳": (114.057868, 22.543099),
    }

    effective_city = city
    if daily_spots:
        all_spot_coords = [sc for spots in daily_spots for sc in spots]
        if all_spot_coords and city in CITY_CENTER_COORDS:
            center_lng, center_lat = CITY_CENTER_COORDS[city]
            avg_dist_to_center = sum(
                _haversine_distance(sc[0], sc[1], center_lng, center_lat)
                for sc in all_spot_coords
            ) / len(all_spot_coords)
            logger.info(f"[smart_hotel] 景点距{city}中心平均距离: {avg_dist_to_center:.1f}km")
            # 如果景点距离目标城市中心超过50km，说明可能city参数与实际景点不匹配
            if avg_dist_to_center > 50:
                logger.warning(
                    f"[smart_hotel] ⚠️ 景点距{city}中心{avg_dist_to_center:.1f}km，"
                    f"city参数可能与实际行程区域不一致！将尝试自动修正。"
                )
                # 尝试从已知城市中找到最近的一个作为有效搜索城市
                best_city = city
                best_dist = avg_dist_to_center
                for c_name, (c_lng, c_lat) in CITY_CENTER_COORDS.items():
                    d = sum(_haversine_distance(sc[0], sc[1], c_lng, c_lat) for sc in all_spot_coords) / len(all_spot_coords)
                    if d < best_dist:
                        best_dist = d
                        best_city = c_name
                if best_city != city:
                    effective_city = best_city
                    logger.warning(
                        f"[smart_hotel] 自动修正搜索城市: {city} → {effective_city} "
                        f"(距景点{best_dist:.1f}km)"
                    )

    for i, spots in enumerate(daily_spots):
        if spots:
            centroid_lng = sum(s[0] for s in spots) / len(spots)
            centroid_lat = sum(s[1] for s in spots) / len(spots)
            logger.info(f"[smart_hotel] D{i+1}: {len(spots)}个景点, 中心点=({centroid_lng:.4f}, {centroid_lat:.4f})")
        else:
            logger.info(f"[smart_hotel] D{i+1}: 无景点坐标")

    # ---- 步骤1：多区域采样搜索候选酒店 ----
    hotel_keywords = {
        "豪华": ["五星级酒店", "五星级 酒店"],
        "高档": ["四星级酒店 高端酒店 精品酒店", "高档酒店"],
        "舒适型": ["酒店 宾馆 舒适型酒店", "酒店"],
        "经济": ["快捷酒店 经济型酒店 旅馆", "宾馆"],
    }
    keywords = hotel_keywords.get(hotel_level, ["酒店 宾馆"])

    from app.services.map_service import search_hotels, _is_poi_in_city

    all_candidates: list[dict[str, Any]] = []
    seen_poi_ids: set[str | None] = set()

    for kw_idx, keyword in enumerate(keywords):
        try:
            page_size = max(night_count * 2, 8) if kw_idx > 0 else max(night_count * 3, 12)
            candidates = search_hotels(keyword, city=effective_city, page_size=page_size)
            for p in candidates:
                poi_id = p.get("poi_id")
                if poi_id in seen_poi_ids:
                    continue
                seen_poi_ids.add(poi_id)
                if _is_poi_in_city(p, effective_city):
                    all_candidates.append(p)
            logger.debug(
                f"[smart_hotel] 搜索关键词[{kw_idx}]'{keyword}': "
                f"返回{len(candidates)}家, 去重后累计{len(all_candidates)}家"
            )
        except Exception as e:
            logger.debug(f"[smart_hotel] 搜索关键词'{keyword}'失败: {e}")

    if not all_candidates:
        logger.warning("[smart_hotel] 无候选酒店，返回空列表")
        return []

    logger.info(f"[smart_hotel] 多关键词搜索共获取 {len(all_candidates)} 家候选酒店(已去重+城市过滤)")

    # ---- 步骤2：提取候选酒店的经纬度和价格信息 ----
    enriched_candidates: list[dict[str, Any]] = []
    for poi in all_candidates:
        lat = poi.get("latitude") or poi.get("lat")
        lng = poi.get("longitude") or poi.get("lng")
        if lat is None or lng is None:
            continue

        real_cost = None
        biz_ext = poi.get("biz_ext") or {}
        if isinstance(biz_ext, dict):
            cost_str = biz_ext.get("cost", "")
            if cost_str:
                try:
                    real_cost = float(cost_str)
                except (ValueError, TypeError):
                    pass

        enriched_candidates.append({
            **poi,
            "_lat": float(lat),
            "_lng": float(lng),
            "_real_cost": real_cost,
        })

    if not enriched_candidates:
        logger.warning("[smart_hotel] 所有候选酒店缺少坐标，返回空列表")
        return []

    # ---- 步骤3：档次基准价格 ----
    level_price_ranges = {
        "经济": (80, 150),
        "舒适型": (200, 400),
        "高档": (400, 700),
        "豪华": (700, 1500),
    }
    price_low, price_high = level_price_ranges.get(hotel_level, (200, 400))

    def _estimate_cost_for_candidate(poi: dict, budget: float) -> float:
        real_cost = poi.get("_real_cost")
        if real_cost and real_cost > 0:
            base = real_cost
        else:
            base = (price_low + price_high) / 2
        return min(base, budget * 1.3)

    def _get_spot_centroid(coords: list[tuple[float, float]]) -> tuple[float, float] | None:
        """计算一组景点坐标的中心点。"""
        if not coords:
            return None
        avg_lng = sum(c[0] for c in coords) / len(coords)
        avg_lat = sum(c[1] for c in coords) / len(coords)
        return (avg_lng, avg_lat)

    def _max_distance_to_spots(hotel_lng, hotel_lat, coords):
        """计算酒店到所有景点的最大距离。"""
        if not coords:
            return 0.0
        return max(_haversine_distance(hotel_lng, hotel_lat, sc[0], sc[1]) for sc in coords)

    def _avg_distance_to_spots(hotel_lng, hotel_lat, coords):
        """计算酒店到所有景点的平均距离。"""
        if not coords:
            return 30.0
        dists = [_haversine_distance(hotel_lng, hotel_lat, sc[0], sc[1]) for sc in coords]
        return sum(dists) / len(dists)

    # ---- 步骤4：逐晚分配酒店 ----
    result: list[dict[str, Any]] = []
    last_selected_poi: dict[str, Any] | None = None

    for night_idx in range(night_count):
        budget = daily_hotel_costs[night_idx] if night_idx < len(daily_hotel_costs) else daily_hotel_costs[-1]
        spot_coords = daily_spots[night_idx] if night_idx < len(daily_spots) else []

        # --- 阶段A：按当天景点位置就近预筛 ---
        centroid = _get_spot_centroid(spot_coords)

        if centroid and spot_coords:
            # 按到当天景点的平均距离排序，近的排前面
            candidates_by_dist = sorted(
                enriched_candidates,
                key=lambda p: _avg_distance_to_spots(p["_lng"], p["_lat"], spot_coords),
            )
            # 取最近的前60%，保证有足够选择余地
            nearby_count = max(len(enriched_candidates) // 2 + 1, night_count + 3)
            round_candidates = candidates_by_dist[:nearby_count]
            nearest_dist = _avg_distance_to_spots(
                round_candidates[0]["_lng"], round_candidates[0]["_lat"], spot_coords
            )
            logger.debug(
                f"[smart_hotel] 第{night_idx+1}晚就近预筛: "
                f"取最近{len(round_candidates)}家(最近{nearest_dist:.1f}km)"
            )
            # 距离上限保护：如果最近的候选都超过10km，发出警告
            if nearest_dist > 10:
                logger.warning(
                    f"[smart_hotel] ⚠️ 第{night_idx+1}晚: 最近候选酒店距景点{nearest_dist:.1f}km，"
                    f"可能搜索城市({effective_city})与实际景点区域不匹配！"
                )
        else:
            round_candidates = enriched_candidates[:]

        # --- 阶段B：预算过滤（放宽上下限，靠评分约束）---
        budget_max = budget * 1.8
        filtered = [
            p for p in round_candidates
            if _estimate_cost_for_candidate(p, budget) <= budget_max
        ]

        if not filtered:
            filtered = round_candidates[:]
            logger.debug(f"[smart_hotel] 第{night_idx+1}晚预算过滤无结果，使用全部{len(filtered)}家")

        # --- 阶段C：综合评分（距离优先55%，预算/价格次之30%，评分最后10%）---
        scored: list[tuple[dict, float]] = []
        for poi in filtered:
            score = 0.0

            # 【核心】距离评分（权重55%）— 平均距离+最远距离双重惩罚
            if spot_coords and poi.get("_lat") is not None:
                max_dist = _max_distance_to_spots(poi["_lng"], poi["_lat"], spot_coords)
                avg_dist = _avg_distance_to_spots(poi["_lng"], poi["_lat"], spot_coords)
                # 斜率更陡：5km→72.5分, 10km→45分, 15km→17.5分, 20km→0分
                dist_score = max(0, min(100, 100 - avg_dist * 5.5))
                # 最远景点>15km额外扣分（意味着需要长途往返某个景点）
                if max_dist > 15:
                    dist_score -= (max_dist - 15) * 3
                    dist_score = max(0, dist_score)
            elif centroid:
                d = _haversine_distance(poi["_lng"], poi["_lat"], centroid[0], centroid[1])
                dist_score = max(0, min(100, 100 - d * 5.5))
            else:
                dist_score = 50.0
            score += dist_score * 0.55

            # 预算/价格匹配度（权重30%）— 第二优先
            est_cost = _estimate_cost_for_candidate(poi, budget)
            if budget > 0:
                ratio = est_cost / budget
                if ratio <= 1.0:
                    budget_score = 100 - abs(ratio - 0.85) * 80
                else:
                    budget_score = max(0, 100 - (ratio - 1.0) * 120)
                budget_score = max(0, min(100, budget_score))
            else:
                budget_score = 70.0
            score += budget_score * 0.30

            # 评分（权重10%）— 最后考虑
            rating = poi.get("rating")
            if rating is not None and rating > 0:
                rating_score = min(100, (rating / 5.0) * 100)
            else:
                rating_score = 60.0
            score += rating_score * 0.10

            # 连住奖励（权重5%，仅当新旧差距<3km时生效）
            stay_bonus = 0.0
            if last_selected_poi is not None and spot_coords:
                prev_avg = _avg_distance_to_spots(
                    last_selected_poi["_lng"], last_selected_poi["_lat"], spot_coords
                )
                curr_avg = _avg_distance_to_spots(poi["_lng"], poi["_lat"], spot_coords)
                if abs(prev_avg - curr_avg) < 3:
                    if poi.get("poi_id") == last_selected_poi.get("poi_id"):
                        stay_bonus = 100.0
                    elif poi.get("name") == last_selected_poi.get("name"):
                        stay_bonus = 90.0
            score += stay_bonus * 0.05

            scored.append((poi, score))

        # 按得分降序排列
        scored.sort(key=lambda x: x[1], reverse=True)
        best_poi = scored[0][0] if scored else None

        if best_poi is None:
            logger.warning(f"[smart_hotel] 第{night_idx + 1}晚无可选酒店")
            break

        # --- 阶段D：连住决策（严格模式）---
        final_poi = best_poi
        if last_selected_poi is not None and spot_coords:
            prev_max = _max_distance_to_spots(
                last_selected_poi["_lng"], last_selected_poi["_lat"], spot_coords
            )
            curr_max = _max_distance_to_spots(
                best_poi["_lng"], best_poi["_lat"], spot_coords
            )
            prev_avg = _avg_distance_to_spots(
                last_selected_poi["_lng"], last_selected_poi["_lat"], spot_coords
            )
            curr_avg = _avg_distance_to_spots(
                best_poi["_lng"], best_poi["_lat"], spot_coords
            )

            # 严格规则：
            # a) 上一晚酒店到今天任意景点超过12km → 必须切换
            # b) 当前最佳比上一晚近超过3km → 切换
            # c) 否则 → 保持连住
            must_switch = prev_max > 12 or (curr_avg < prev_avg - 3)

            if not must_switch:
                logger.debug(
                    f"[smart_hotel] 第{night_idx+1}晚保持连住: "
                    f"{last_selected_poi.get('name')}(距景点{prev_avg:.1f}km) vs "
                    f"最佳{best_poi.get('name')}({curr_avg:.1f}km)"
                )
                final_poi = last_selected_poi
            else:
                logger.debug(
                    f"[smart_hotel] 第{night_idx+1}晚切换: "
                    f"{last_selected_poi.get('name')}({prev_avg:.1f}km) -> "
                    f"{best_poi.get('name')}({curr_avg:.1f}km)"
                )

        # 构建结果POI
        final_estimated_cost = round(_estimate_cost_for_candidate(final_poi, budget), 2)
        result_poi: dict[str, Any] = {
            "name": final_poi.get("name", f"{city} {hotel_level}住宿"),
            "address": final_poi.get("address"),
            "image_url": final_poi.get("image_url"),
            "latitude": final_poi.get("latitude") or final_poi.get("lat"),
            "longitude": final_poi.get("longitude") or final_poi.get("lng"),
            "poi_id": final_poi.get("poi_id"),
            "rating": final_poi.get("rating"),
            "phone": final_poi.get("phone"),
            "estimated_cost": final_estimated_cost,
        }

        result.append(result_poi)
        last_selected_poi = final_poi

        # 输出详细日志
        if spot_coords:
            avg_d = _avg_distance_to_spots(final_poi["_lng"], final_poi["_lat"], spot_coords)
            max_d = _max_distance_to_spots(final_poi["_lng"], final_poi["_lat"], spot_coords)
            logger.info(
                f"[smart_hotel] 第{night_idx+1}晚: {result_poi['name']}, "
                f"¥{final_estimated_cost:.0f}/晚, "
                f"距景点平均{avg_d:.1f}km(最远{max_d:.1f}km)"
            )

    logger.info(f"[smart_hotel] V2选址完成，共 {len(result)} 晚")
    return result


def _refresh_budget_breakdown(
    itinerary: Itinerary,
    request_budget: float | None = None,
    travelers: int = 1,
) -> Itinerary:
    """从具体条目回算预算汇总（人均），含分级压缩和偏差提示。

    优化点：
    - 超预算时分级压缩：门票不动 → 酒店降档 → 餐饮调整 → 交通压缩
    - 杂项拆分为保险/应急备用金/购物三项可见明细
    - 压缩比<0.7时生成budget_alert提示
    - 同时输出人均明细和团队总预算
    """
    _apply_route_based_transport_costs(itinerary)

    transport_total = round(
        sum(item.estimated_cost for day in itinerary.days for item in day.transport),
        2,
    )
    hotel_total = round(
        sum(day.hotel.estimated_cost for day in itinerary.days if day.hotel is not None),
        2,
    )
    meal_total = round(
        sum(item.estimated_cost for day in itinerary.days for item in day.meals),
        2,
    )
    ticket_total = round(
        sum(item.estimated_cost for day in itinerary.days for item in day.spots),
        2,
    )

    subtotal_per_person = transport_total + hotel_total + meal_total + ticket_total

    # 杂项拆分：保险(3%) + 应急备用金(3%) + 购物杂项(2%) = 总计~8%
    if request_budget is not None:
        insurance = round(request_budget * 0.03, 2)
        contingency = round(request_budget * 0.03, 2)
        shopping_misc = round(request_budget * 0.02, 2)
        misc_total = insurance + contingency + shopping_misc
    else:
        misc_ratio = subtotal_per_person * 0.06
        insurance = round(misc_ratio * 0.375, 2)
        contingency = round(misc_ratio * 0.375, 2)
        shopping_misc = round(misc_ratio * 0.25, 2)
        misc_total = insurance + contingency + shopping_misc

    total_per_person = round(subtotal_per_person + misc_total, 2)

    # === 分级超预算压缩（替代原来的等比例压缩）===
    budget_alert = None
    if request_budget is not None and total_per_person > request_budget:
        target_budget = request_budget * 0.95  # 控制在预算的95%以内

        # 计算需要压缩的金额
        excess = total_per_person - target_budget
        original_ticket_total = ticket_total  # 门票不压缩，记录原始值

        # 第1步：先压酒店（可调档次）
        hotel_compress = min(excess * 0.5, hotel_total * 0.35)  # 最多压掉酒店35%
        remaining_after_hotel = excess - hotel_compress

        # 第2步：再压餐饮（可调档次）
        meal_compress = min(remaining_after_hotel * 0.6, meal_total * 0.30)
        remaining_after_meal = remaining_after_hotel - meal_compress

        # 第3步：最后压交通
        transport_compress = min(remaining_after_meal, transport_total * 0.25)

        # 应用压缩
        hotel_total = round(max(hotel_total - hotel_compress, hotel_total * 0.50), 2)
        meal_total = round(max(meal_total - meal_compress, meal_total * 0.60), 2)
        transport_total = round(max(transport_total - transport_compress, transport_total * 0.65), 2)
        # 门票保持不变

        # 按比例回写到各明细项
        hotel_ratio = hotel_total / max(sum(day.hotel.estimated_cost for day in itinerary.days if day.hotel is not None), 1)
        meal_ratio = meal_total / max(sum(item.estimated_cost for day in itinerary.days for item in day.meals), 1)
        transport_ratio = transport_total / max(sum(item.estimated_cost for day in itinerary.days for item in day.transport), 1)

        for day in itinerary.days:
            if day.hotel is not None:
                day.hotel.estimated_cost = round(day.hotel.estimated_cost * hotel_ratio, 2)
            for item in day.meals:
                item.estimated_cost = round(item.estimated_cost * meal_ratio, 2)
            for item in day.transport:
                item.estimated_cost = round(item.estimated_cost * transport_ratio, 2)
            # 门票不修改

        # 重新计算总额
        subtotal_compressed = transport_total + hotel_total + meal_total + ticket_total
        total_per_person = round(subtotal_compressed + misc_total, 2)

        # 偏差提示
        compression_ratio = total_per_person / max(subtotal_per_person + misc_total - (excess if 'excess' in dir() else 0), 1)
        if compression_ratio < 0.70:
            suggested = round(request_budget / compression_ratio * 1.05, 0)
            budget_alert = (
                f"当前行程实际所需约{suggested:.0f}元/人，"
                f"超出您设定的人均预算{request_budget:.0f}元。"
                f"建议：①提高预算至{suggested:.0f}元/人；"
                f"②减少住宿天数；③选择经济型酒店或降低餐饮标准。"
                f"（门票价格已按原价保留未压缩）"
            )
        elif compression_ratio < 0.85:
            budget_alert = (
                f"行程费用已自动优化至人均{total_per_person:.0f}元，"
                f"接近您的预算上限{request_budget:.0f}元。"
                f"如需更宽松的体验，建议适当增加预算。"
            )

    # 团队总预算
    total_for_group = round(total_per_person * travelers, 2)

    itinerary.budget_breakdown = BudgetBreakdown(
        transport=transport_total,
        hotel=hotel_total,
        meals=meal_total,
        tickets=ticket_total,
        insurance=insurance,
        contingency=contingency,
        shopping_misc=shopping_misc,
        total=total_per_person,
        total_for_group=total_for_group,
        travelers=travelers,
        budget_alert=budget_alert,
    )
    itinerary.estimated_budget = total_per_person
    return itinerary


def _maybe_enrich_itinerary_with_map_data(
    itinerary: Itinerary,
    city: str | None = None,
    request_budget: float | None = None,
) -> Itinerary:
    """按开关补充地图信息，并在最后统一刷新预算。"""
    if ENABLE_AMAP_ENRICHMENT:
        try:
            itinerary = enrich_itinerary_with_map_data(itinerary, city=city)
        except Exception:
            pass

    return _refresh_budget_breakdown(itinerary, request_budget=request_budget, travelers=1)


# ==============================
# 新的拆分函数 - 用于 Pipeline
# ==============================

def collect_rag_contexts(request: TripRequest, trace_ctx = None, use_llm_rewrite: bool = False) -> list[str]:
    """阶段1：收集 RAG 上下文"""
    logger.info("[collect_rag_contexts] 收集 RAG 上下文...")

    rag_contexts = collect_trip_context(
        destination=request.destination,
        preferences=request.preferences,
        pace=request.pace,
        special_notes=request.special_notes,
        use_llm_rewrite=use_llm_rewrite,
    )

    if trace_ctx and rag_contexts:
        for ctx in rag_contexts:
            TracingService.add_rag_context(trace_ctx, context=ctx)

    logger.info(f"[collect_rag_contexts] 完成，共 {len(rag_contexts)} 条")
    return rag_contexts


def generate_llm_draft(request: TripRequest, rag_contexts: list[str], day_count: int):
    """阶段2：调用 LLM 生成行程草稿"""
    logger.info("[generate_llm_draft] 调用 LLM 生成行程草稿...")

    cache_payload = {
        "destination": request.destination,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "days": day_count,
        "travelers": request.travelers,
        "budget": request.budget,
        "preferences": request.preferences,
        "pace": request.pace,
        "dietary_preferences": request.dietary_preferences,
        "hotel_level": request.hotel_level,
        "special_notes": request.special_notes,
        "rag_contexts": rag_contexts,
    }
    cache_raw = json.dumps(cache_payload, ensure_ascii=False, sort_keys=True)
    cache_key = f"llm_draft:{hashlib.sha256(cache_raw.encode('utf-8')).hexdigest()}"
    cached = get_cached_json(cache_key)
    if cached is not None:
        try:
            logger.info("[generate_llm_draft] 命中缓存")
            return PlannerDraft.model_validate(cached)
        except Exception:
            logger.debug("[generate_llm_draft] 缓存解析失败，重新调用 LLM", exc_info=True)

    llm_draft = generate_planner_draft(request, rag_contexts, day_count)
    if llm_draft is not None:
        set_cached_json(
            cache_key,
            llm_draft.model_dump(mode="json"),
            expire_seconds=REDIS_LLM_DRAFT_TTL_SECONDS,
        )

    logger.info(f"[generate_llm_draft] 完成，{'成功' if llm_draft else '失败'}")
    return llm_draft


def build_raw_days_data_without_tickets(
    request: TripRequest,
    llm_draft,
    rag_contexts: list[str],
    day_count: int
) -> list[dict]:
    """阶段3：构建原始天数数据（不提取票价）"""
    logger.info("[build_raw_days_data_without_tickets] 构建原始天数数据...")
    
    fallback_spot_names = _build_demo_spot_names(request.destination, rag_contexts, day_count)
    raw_days: list[dict[str, object]] = []
    
    for index in range(day_count):
        day_number = index + 1
        current_date = request.start_date + timedelta(days=index)
        llm_day = None
        if llm_draft is not None:
            llm_day = next((item for item in llm_draft.days if item.day_index == day_number), None)

        spot_name = llm_day.spot_name if llm_day is not None else fallback_spot_names[index]
        theme = llm_day.theme if llm_day is not None else f"{request.destination} 第 {day_number} 天轻松游"
        spot_description = (
            llm_day.spot_description
            if llm_day is not None
            else "根据本地攻略和旅行偏好安排，适合用半天时间慢慢游览。"
        )
        meal_name = llm_day.meal_name if llm_day is not None else f"{request.destination} 特色餐饮 {day_number}"
        meal_note = (
            llm_day.meal_notes
            if llm_day is not None
            else "根据用户偏好和本地攻略预留的一条餐饮建议。"
        )
        daily_note = (
            llm_day.daily_note
            if llm_day is not None
            else "今天以轻松游览为主，建议根据体力和天气灵活调整停留时间。"
        )

        raw_days.append({
            "day_index": day_number,
            "date": current_date,
            "theme": theme,
            "spot_name": spot_name,
            "spot_description": spot_description,
            "meal_name": meal_name,
            "meal_note": meal_note,
            "daily_note": daily_note,
            "ticket_cost": 0.0,  # 先填默认值，后续由 TicketCheckStage 填充
        })
    
    logger.info(f"[build_raw_days_data_without_tickets] 完成，共 {len(raw_days)} 天")
    return raw_days


def calculate_budget_allocations_without_tickets(
    request: TripRequest,
    day_count: int
) -> tuple[list[float], list[float], list[float]]:
    """阶段4：计算预算分配（人均，不包含票价）。

    budget 现在是人均预算。交通和门票需要乘以人数，
    住宿和餐饮按人均计算。
    """
    logger.info("[calculate_budget_allocations_without_tickets] 计算预算分配（人均）...")

    travelers = max(request.travelers, 1)
    # 人均可分配预算 = 人均预算 × 节奏系数
    pace_factor = 0.78 if request.pace == "轻松" else 0.92 if request.pace == "紧凑" else 0.85
    target_total_per_person = request.budget * pace_factor

    # 多人折扣：2人以上部分项目有优惠
    group_discount = 1.0
    if travelers >= 3:
        group_discount = 0.90   # 3人及以上9折
    elif travelers >= 2:
        group_discount = 0.95   # 2人95折

    # 住宿晚数 = 天数 - 1（最后一天离开不住宿）
    night_count = max(day_count - 1, 1)

    # 杂项预算（保险+应急+购物），占比降低（原12%→8%）
    misc_budget_per_person = round(request.budget * (0.03 + min(day_count, 4) * 0.008), 2)
    allocatable_per_person = max(target_total_per_person - misc_budget_per_person, request.budget * 0.50)

    # 酒店档次决定住宿占比
    hotel_level = request.hotel_level or "舒适型"
    if "豪华" in hotel_level:
        hotel_ratio = 0.55
    elif "高档" in hotel_level or "高端" in hotel_level:
        hotel_ratio = 0.50
    elif "经济" in hotel_level:
        hotel_ratio = 0.35
    else:
        hotel_ratio = 0.42

    meal_ratio = 0.28 if "美食" in request.preferences else 0.22
    transport_ratio = max(0.15, 1 - hotel_ratio - meal_ratio)
    ratio_sum = hotel_ratio + meal_ratio + transport_ratio

    # 人均各项总额（应用多人折扣到酒店）
    hotel_total_per_person = allocatable_per_person * hotel_ratio / ratio_sum * group_discount
    meal_total_per_person = allocatable_per_person * meal_ratio / ratio_sum
    transport_total_per_person = allocatable_per_person * transport_ratio / ratio_sum

    # 按权重拆分到每天/每晚
    daily_hotel_costs = _prorate_amounts(
        hotel_total_per_person,
        _build_hotel_weights(night_count, request.start_date),
    )
    daily_meal_costs = _prorate_amounts(
        meal_total_per_person,
        _build_meal_weights(day_count, request.preferences),
    )
    daily_transport_costs = _prorate_amounts(
        transport_total_per_person,
        _build_transport_weights(day_count, request.pace),
    )

    logger.info("[calculate_budget_allocations_without_tickets] 完成"
                f" (人均={request.budget}, 人数={travelers}, 晚数={night_count})")
    return daily_hotel_costs, daily_meal_costs, daily_transport_costs


def build_day_plans(
    request: TripRequest,
    raw_days: list[dict],
    daily_hotel_costs: list[float],
    daily_meal_costs: list[float],
    daily_transport_costs: list[float]
) -> tuple[list[DayPlan], list[str], list[str]]:
    """阶段5：构建 DayPlan 对象。

    优化点：
    - 最后一天不分配酒店（day_count天只住night_count=day_count-1晚）
    - 尝试从高德API获取真实酒店/餐饮POI名称
    - 集成餐饮价格解析服务
    - 改善交通数据（from_place使用前一天景点或市区）
    """
    logger.info("[build_day_plans] 构建 DayPlan 对象...")

    days: list[DayPlan] = []
    attraction_names: list[str] = []
    attraction_descriptions: list[str] = []
    hotel_level = request.hotel_level or "舒适型"
    night_count = max(len(raw_days) - 1, 1)  # 晚数 = 天数 - 1

    # 尝试预取餐饮价格（用于填充estimated_cost）
    meal_price_map = None
    try:
        from app.services.meal_price_service import extract_meal_prices
        meal_price_map = extract_meal_prices(request.destination)
        if meal_price_map:
            logger.info(f"[build_day_plans] 从攻略提取到 {len(meal_price_map)} 条餐饮价格")
    except Exception as e:
        logger.debug(f"[build_day_plans] 餐饮价格提取失败: {e}")

    # === 智能酒店选址 ===
    smart_hotels: list[dict[str, Any]] = []
    try:
        # 收集每天的景点坐标（用于距离计算）
        # raw_days是list[dict]，需要从spot_name出发通过高德API获取真实坐标
        daily_spot_coords: list[list[tuple[float, float]]] = []

        from app.services.map_service import search_attractions, _is_poi_in_city

        for raw_day in raw_days:
            coords = []
            spot_name = str(raw_day.get("spot_name", ""))
            if spot_name and request.destination:
                try:
                    results = search_attractions(spot_name, city=request.destination, page_size=3)
                    for poi in results:
                        if _is_poi_in_city(poi, request.destination):
                            lat = poi.get("latitude") or poi.get("lat")
                            lng = poi.get("longitude") or poi.get("lng")
                            if lat is not None and lng is not None:
                                coords.append((float(lng), float(lat)))
                                logger.debug(
                                    f"[build_day_plans] 景点'{spot_name}'坐标: "
                                    f"({lng}, {lat}) from {poi.get('name')}"
                                )
                                break
                except Exception as e:
                    logger.debug(f"[build_day_plans] 获取景点'{spot_name}'坐标失败: {e}")
            if not coords:
                logger.warning(
                    f"[build_day_plans] ⚠️ 无法获取景点'{spot_name}'坐标，"
                    f"酒店选址将无法使用距离评分"
                )
            daily_spot_coords.append(coords)

        smart_hotels = _select_smart_hotels(
            city=request.destination,
            hotel_level=hotel_level,
            night_count=night_count,
            daily_hotel_costs=daily_hotel_costs,
            daily_spots=daily_spot_coords,  # 用于距离评分
            start_date=request.start_date,
        )
    except Exception as e:
        logger.warning(f"[build_day_plans] 智能酒店选址失败，回退到模板: {e}")

    for index, raw_day in enumerate(raw_days):
        spot_name = str(raw_day["spot_name"])
        spot_desc = str(raw_day["spot_description"])

        attraction_names.append(spot_name)
        attraction_descriptions.append(spot_desc)

        # --- 景点（不变）---
        spot_items = [
            SpotItem(
                name=spot_name,
                start_time="10:00",
                end_time="12:00",
                description=spot_desc,
                estimated_cost=float(raw_day["ticket_cost"]),
                location=request.destination,
            )
        ]

        # --- 餐饮：尝试用真实价格 ---
        meal_name = str(raw_day["meal_name"])
        meal_cost = daily_meal_costs[index]
        if meal_price_map:
            try:
                from app.services.meal_price_service import get_meal_price
                real_meal_price = get_meal_price(meal_name, request.destination, meal_price_map)
                if real_meal_price > 0:
                    meal_cost = real_meal_price
                    logger.debug(f"  餐饮'{meal_name}'使用真实价格: {real_meal_price}元")
            except Exception:
                pass

        meal_items = [
            MealItem(
                name=meal_name,
                meal_type="午餐",
                estimated_cost=meal_cost,
                notes=str(raw_day["meal_note"]),
            )
        ]

        # --- 酒店：最后一天为空，其他天使用智能选址结果 ---
        is_last_day = (index == len(raw_days) - 1)
        if is_last_day:
            hotel_item = None
        else:
            # 使用对应的酒店费用（按晚索引映射）
            hotel_cost_index = min(index, len(daily_hotel_costs) - 1)

            if index < len(smart_hotels):
                poi = smart_hotels[index]
                hotel_item = HotelItem(
                    name=poi["name"],
                    level=hotel_level,
                    estimated_cost=poi["estimated_cost"],
                    location=poi.get("address") or f"{request.destination} 市区",
                    address=poi.get("address"),
                    image_url=poi.get("image_url"),
                    latitude=poi.get("latitude"),
                    longitude=poi.get("longitude"),
                    poi_id=poi.get("poi_id"),
                    rating=poi.get("rating"),
                    phone=poi.get("phone"),
                )
            else:
                # 无智能选址结果时回退到模板名称
                hotel_item = HotelItem(
                    name=f"{request.destination} {hotel_level}住宿 {index + 1}",
                    level=hotel_level,
                    estimated_cost=daily_hotel_costs[hotel_cost_index],
                    location=f"{request.destination} 市区",
                )

        # --- 交通：改善出发地 ---
        transport_from = request.destination
        if index > 0 and index < len(attraction_names):
            # 从前一天的景点出发，而非固定的"出发点"
            prev_spot = attraction_names[index - 1]
            if prev_spot and prev_spot != f"{request.destination} 推荐景点":
                transport_from = prev_spot

        transport_items = [
            TransportItem(
                mode="打车",
                from_place=transport_from,
                to_place=spot_name,
                estimated_cost=daily_transport_costs[index],
                duration="待查询",  # 由地图补充阶段填充真实耗时
            )
        ]

        day_plan = DayPlan(
            day_index=int(raw_day["day_index"]),
            date=raw_day["date"],
            theme=str(raw_day["theme"]),
            spots=spot_items,
            meals=meal_items,
            hotel=hotel_item,
            transport=transport_items,
            notes=[
                f"当前旅行节奏：{request.pace or '适中'}",
                str(raw_day["daily_note"]),
            ],
        )
        days.append(day_plan)

    logger.info(f"[build_day_plans] 完成，共 {len(days)} 天（{night_count} 晚住宿）")
    return days, attraction_names, attraction_descriptions


def generate_tips_basic(
    request: TripRequest,
    llm_draft,
    rag_contexts: list[str],
    attraction_names: list[str],
    attraction_descriptions: list[str]
) -> list[str]:
    """阶段6：生成基础提示信息（不包含天气，天气由 WeatherCheckStage 处理）"""
    logger.info("[generate_tips_basic] 生成基础提示信息...")
    
    # 首先尝试获取 LLM 返回的提示
    if llm_draft is not None and llm_draft.tips:
        tips = llm_draft.tips
    else:
        # 如果 LLM 没有返回提示，使用动态提示（不包含天气）
        tips = _generate_dynamic_tips(
            destination=request.destination,
            weather_data=None,
            rag_contexts=rag_contexts,
            attraction_names=attraction_names,
            attraction_descriptions=attraction_descriptions
        )
    
    # 清理和过滤提示
    tips = _clean_user_tips(tips, request.destination)
    logger.info(f"[generate_tips_basic] 完成，共 {len(tips)} 条")
    return tips


def build_basic_itinerary(
    request: TripRequest,
    llm_draft,
    days: list[DayPlan],
    tips: list[str],
    rag_contexts: list[str],
    day_count: int
) -> Itinerary:
    """阶段7：构建基础 Itinerary 对象（不包含地图和校验，只包含基础信息）"""
    logger.info("[build_basic_itinerary] 构建基础 Itinerary 对象...")
    
    preference_text = "、".join(request.preferences) if request.preferences else "常规旅行体验"
    summary = (
        llm_draft.summary
        if llm_draft is not None
        else f"这是一份为 {request.destination} 生成的 {day_count} 日行程，偏好重点为：{preference_text}。"
    )
    
    source_notes = [
        "Itinerary is assembled by trip_service.py and can optionally use LangChain structured output.",
    ]
    source_notes.extend(rag_contexts[:2])
    
    itinerary = Itinerary(
        trip_id=f"trip_{request.destination}_{request.start_date.isoformat()}",
        destination=request.destination,
        summary=summary,
        days=days,
        estimated_budget=0.0,
        budget_breakdown=BudgetBreakdown(),
        tips=tips,
        source_notes=source_notes,
    )

    itinerary = _refresh_budget_breakdown(itinerary, request_budget=request.budget, travelers=request.travelers)
    logger.info("[build_basic_itinerary] 完成")
    return itinerary


def enrich_itinerary_data(itinerary: Itinerary, request: TripRequest) -> Itinerary:
    """地图补全阶段：只负责地图数据补充和预算刷新。"""
    return _maybe_enrich_itinerary_with_map_data(
        itinerary,
        city=request.destination,
        request_budget=request.budget,
    )


def apply_ticket_prices(itinerary: Itinerary, request: TripRequest) -> Itinerary:
    """票价阶段：从本地攻略提取票价并更新景点费用，避免主规划阶段重复 RAG。"""
    ticket_map = extract_ticket_info(request.destination)
    if not ticket_map:
        return _refresh_budget_breakdown(itinerary, request_budget=request.budget)

    for day in itinerary.days:
        for spot in day.spots:
            spot.estimated_cost = get_ticket_price(
                spot.name,
                request.destination,
                ticket_map=ticket_map,
            )

    return _refresh_budget_breakdown(itinerary, request_budget=request.budget)


def validate_itinerary(itinerary: Itinerary, request: TripRequest) -> Itinerary:
    """校验阶段：只追加用户可读的校验提示，不阻塞主流程。"""
    try:
        validation_service = get_itinerary_validation_service()
        validation_result = validation_service.validate_itinerary(itinerary, request)

        if validation_result.has_errors() or validation_result.has_warnings():
            validation_tips = [f"行程校验结果: {validation_result.overall_status.value}"]
            for issue in validation_result.issues[:3]:
                prefix = "错误" if issue.status.value == "error" else "提醒"
                tip_msg = f"{prefix}: {issue.message}"
                if issue.suggestion:
                    tip_msg += f" 建议: {issue.suggestion}"
                validation_tips.append(tip_msg)
            if len(validation_result.issues) > 3:
                validation_tips.append(
                    f"还有 {len(validation_result.issues) - 3} 个问题未显示，请查看详细校验报告。"
                )
            itinerary.tips.extend(tip for tip in validation_tips if tip not in itinerary.tips)
    except Exception as exc:
        logger.warning("行程校验执行失败: %s", exc)

    return itinerary


def _get_day_count(request: TripRequest) -> int:
    if request.days and request.days > 0:
        return request.days
    return max((request.end_date - request.start_date).days + 1, 1)


def generate_trip_itinerary(
    request: TripRequest,
    trace_ctx=None,
    *,
    use_llm_rewrite: bool = False,
    include_ticket_lookup: bool = True,
    include_map_enrichment: bool = True,
    include_validation: bool = True,
) -> Itinerary:
    """生成完整 itinerary；可按场景关闭慢阶段以支持快速首响。"""
    day_count = _get_day_count(request)

    rag_contexts = collect_rag_contexts(
        request,
        trace_ctx=trace_ctx,
        use_llm_rewrite=use_llm_rewrite,
    )
    llm_draft = generate_llm_draft(request, rag_contexts, day_count)
    raw_days = build_raw_days_data_without_tickets(request, llm_draft, rag_contexts, day_count)

    if include_ticket_lookup:
        ticket_map = extract_ticket_info(request.destination)
        for raw_day in raw_days:
            raw_day["ticket_cost"] = _estimate_ticket_cost(
                str(raw_day["spot_name"]),
                str(raw_day["spot_description"]),
                request.destination,
                ticket_map,
            )

    daily_hotel_costs, daily_meal_costs, daily_transport_costs = calculate_budget_allocations_without_tickets(
        request,
        day_count,
    )
    days, attraction_names, attraction_descriptions = build_day_plans(
        request,
        raw_days,
        daily_hotel_costs,
        daily_meal_costs,
        daily_transport_costs,
    )
    tips = generate_tips_basic(
        request,
        llm_draft,
        rag_contexts,
        attraction_names,
        attraction_descriptions,
    )
    itinerary = build_basic_itinerary(request, llm_draft, days, tips, rag_contexts, day_count)

    if include_map_enrichment:
        itinerary = enrich_itinerary_data(itinerary, request)
    if include_validation:
        itinerary = validate_itinerary(itinerary, request)

    return itinerary


def edit_trip_itinerary(request: TripEditRequest) -> Itinerary:
    """根据用户编辑指令返回更新后的 itinerary，LLM 失败时使用轻量规则回退。"""
    updated_itinerary = request.current_itinerary.model_copy(deep=True)

    target_day = updated_itinerary.days[0] if updated_itinerary.days else None
    if request.edit_scope and request.edit_scope.startswith("day_"):
        try:
            target_day_index = int(request.edit_scope.split("_")[1])
            target_day = next(
                (day for day in updated_itinerary.days if day.day_index == target_day_index),
                target_day,
            )
        except (IndexError, ValueError):
            pass

    if target_day is None:
        updated_itinerary.tips = _clean_user_tips(
            updated_itinerary.tips,
            updated_itinerary.destination,
        )
        return updated_itinerary

    llm_day = None
    try:
        llm_day = generate_day_edit_draft(request, target_day)
    except Exception as exc:
        logger.warning("LLM 编辑失败，使用规则回退: %s", exc)

    if llm_day is not None:
        target_day.theme = llm_day.theme
        if target_day.spots:
            target_day.spots[0].name = llm_day.spot_name
            target_day.spots[0].description = llm_day.spot_description
        if target_day.meals:
            target_day.meals[0].name = llm_day.meal_name
            target_day.meals[0].notes = llm_day.meal_notes
        target_day.notes = [llm_day.daily_note]
    else:
        instruction = request.user_instruction.strip()
        if "轻松" in instruction and target_day.theme:
            if not target_day.theme.endswith("（已调整为更轻松）"):
                target_day.theme = f"{target_day.theme}（已调整为更轻松）"
        target_day.notes.append(f"已根据你的要求调整：{instruction}")

    updated_itinerary.source_notes.append(
        f"已根据用户编辑指令更新行程：{request.user_instruction}"
    )
    updated_itinerary.tips = _clean_user_tips(
        updated_itinerary.tips,
        updated_itinerary.destination,
    )
    if "已根据你的修改要求更新目标日期，出发前建议再确认当天交通、天气和景点开放情况。" not in updated_itinerary.tips:
        updated_itinerary.tips.append("已根据你的修改要求更新目标日期，出发前建议再确认当天交通、天气和景点开放情况。")

    return _refresh_budget_breakdown(
        updated_itinerary,
        request_budget=updated_itinerary.estimated_budget or None,
    )


def parse_ticket_prices_from_rag(
    rag_contexts: list[str],
    destination: str
) -> dict[str, float]:
    """从本地攻略中解析票价，避免重复 RAG 查询"""
    logger.info("[parse_ticket_prices_from_rag] 从本地攻略提取票价")
    return extract_ticket_info(destination)


def update_itinerary_with_tickets(
    itinerary: Itinerary,
    ticket_map: dict[str, float],
    request: TripRequest
) -> Itinerary:
    """使用票价信息更新 itinerary"""
    logger.info("[update_itinerary_with_tickets] 更新景点票价")
    for day in itinerary.days:
        for spot in day.spots:
            spot.estimated_cost = _estimate_ticket_cost(
                spot.name,
                spot.description,
                request.destination,
                ticket_map
            )
    return refresh_budget_final(itinerary, request)


def add_weather_tips_to_itinerary(
    itinerary: Itinerary,
    weather_data: dict
) -> Itinerary:
    """添加天气提示"""
    logger.info("[add_weather_tips_to_itinerary] 添加天气提示")
    weather_tips = _generate_weather_tips(weather_data, itinerary.destination)
    if weather_tips:
        for tip in weather_tips:
            if tip not in itinerary.tips:
                itinerary.tips.append(tip)
    return itinerary


def enrich_map_data_only(
    itinerary: Itinerary,
    request: TripRequest
) -> Itinerary:
    """只补充地图数据，不刷新预算"""
    logger.info("[enrich_map_data_only] 补充地图数据")
    if ENABLE_AMAP_ENRICHMENT:
        try:
            itinerary = enrich_itinerary_with_map_data(itinerary, city=request.destination)
        except Exception as e:
            logger.warning(f"补充地图数据失败: {e}")
    return itinerary


def refresh_budget_final(
    itinerary: Itinerary,
    request: TripRequest
) -> Itinerary:
    """最终刷新预算"""
    logger.info("[refresh_budget_final] 刷新最终预算")
    return _refresh_budget_breakdown(itinerary, request_budget=request.budget)


def validate_itinerary_only(
    itinerary: Itinerary,
    request: TripRequest
) -> Itinerary:
    """只进行校验，不做其他操作"""
    logger.info("[validate_itinerary_only] 执行行程校验")
    try:
        validation_service = get_itinerary_validation_service()
        validation_result = validation_service.validate_itinerary(itinerary, request)
        
        if validation_result.has_errors() or validation_result.has_warnings():
            validation_tips = []
            validation_tips.append(f"📊 行程校验结果: {validation_result.overall_status.value}")
            
            for issue in validation_result.issues[:3]:
                status_emoji = "❌" if issue.status.value == "error" else "⚠️"
                tip_msg = f"{status_emoji} {issue.message}"
                if issue.suggestion:
                    tip_msg += f" 建议: {issue.suggestion}"
                validation_tips.append(tip_msg)
            
            if len(validation_result.issues) > 3:
                validation_tips.append(f"还有 {len(validation_result.issues) - 3} 个问题未显示，请查看详细校验报告。")
            
            # 去重添加
            for tip in validation_tips:
                if tip not in itinerary.tips:
                    itinerary.tips.append(tip)
    except Exception as e:
        logger.warning(f"行程校验执行失败: {e}")
    
    return itinerary
