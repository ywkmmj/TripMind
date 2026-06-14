from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from functools import lru_cache
from datetime import datetime, timedelta

from pydantic import Field

from app.agents.tools.rag_tool import get_destination_guide_context
from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
    TRIP_PLANNER_FAST_MODEL,
)
from app.models.schemas import BaseSchema, DayPlan, TripEditRequest, TripRequest
from app.utils.llm_parser import (
    parse_llm_output,
    PLANNER_DRAFT_SCHEMA,
    DAY_EDIT_DRAFT_SCHEMA,
)

logger = logging.getLogger(__name__)


def _fetch_city_pois(city: str, max_attractions: int = 10, max_restaurants: int = 8) -> str:
    """当RAG为空时，从高德地图预取该城市的真实POI，格式化为LLM可用的候选列表。

    返回格式化的文本，包含景点和餐饮两个子列表。
    如果高德API不可用或无结果，返回兜底提示。
    """
    try:
        from app.services.map_service import search_attractions, search_restaurants
    except ImportError:
        return _fallback_poi_hint(city)

    parts = []

    # 1. 获取景点
    try:
        attractions = search_attractions(keyword=city, city=city, page_size=max_attractions)
        if attractions:
            lines = ["【景点列表】"]
            for i, p in enumerate(attractions, 1):
                name = p.get("name", "")
                addr = p.get("address", "") or ""
                typ = p.get("type", "") or ""
                desc_parts = [f"{i}. {name}"]
                if addr:
                    desc_parts.append(f"   地址：{addr}")
                if typ:
                    desc_parts.append(f"   类型：{typ}")
                lines.append("\n".join(desc_parts))
            parts.append("\n".join(lines))
        else:
            parts.append(f"【景点列表】未查询到「{city}」的景点数据。")
    except Exception as e:
        logger.warning(f"获取{city}景点POI失败: {e}")
        parts.append(f"【景点列表】获取失败，请根据「{city}」的实际情况推荐当地景点。")

    # 2. 获取餐饮
    try:
        restaurants = search_restaurants(keyword=city, city=city, page_size=max_restaurants)
        if restaurants:
            lines = ["\n【餐饮列表】"]
            for i, p in enumerate(restaurants, 1):
                name = p.get("name", "")
                addr = p.get("address", "") or ""
                typ = p.get("type", "") or ""
                desc_parts = [f"{i}. {name}"]
                if addr:
                    desc_parts.append(f"   地址：{addr}")
                if typ:
                    desc_parts.append(f"   类型：{typ}")
                lines.append("\n".join(desc_parts))
            parts.append("\n".join(lines))
        else:
            parts.append(f"\n【餐饮列表】未查询到「{city}」的餐饮数据。")
    except Exception as e:
        logger.warning(f"获取{city}餐饮POI失败: {e}")
        parts.append(f"\n【餐饮列表】获取失败，请推荐「{city}」当地的特色美食。")

    return "\n".join(parts)


def _fallback_poi_hint(city: str) -> str:
    """高德API不可用时的兜底提示。"""
    return (
        f"未能获取「{city}」的实时景点数据。\n"
        f"注意事项：\n"
        f"1. 必须只推荐位于「{city}」范围内的真实景点和地点。\n"
        f"2. 不要推荐同省其他城市（尤其是省会/大城市）的景点。\n"
        f"3. 如果该目的地是县级市或小县城，请推荐当地实际的景点（如当地公园、历史遗迹、特色街区等）。\n"
        f"4. 景点名称必须真实存在于「{city}」，不要使用其他城市的知名地标名称。"
    )

# LLM 行程草稿缓存
_planner_draft_cache: dict[str, tuple[PlannerDraft, datetime]] = {}
_CACHE_TTL_MINUTES = 60  # 缓存 60 分钟
_MAX_CACHE_ENTRIES = 100  # 最多缓存 100 条


def _generate_cache_key(
    destination: str,
    start_date: str,
    end_date: str,
    budget: float,
    travelers: int,
    preferences: list[str] | None,
    pace: str | None,
    dietary_preferences: list[str] | None,
    hotel_level: str | None,
    special_notes: str | None,
    day_count: int,
) -> str:
    """
    生成缓存键，用于查找相近请求。
    为了提高命中率，对一些参数进行标准化处理。
    """
    # 标准化参数
    norm_destination = destination.strip().lower()
    norm_preferences = sorted([p.strip().lower() for p in (preferences or [])])
    norm_dietary = sorted([p.strip().lower() for p in (dietary_preferences or [])])
    norm_pace = (pace or "适中").strip().lower()
    norm_hotel = (hotel_level or "舒适型").strip().lower()
    norm_notes = (special_notes or "").strip().lower()
    
    # 对预算进行粗略归类，提高命中率
    budget_category = int(budget // 500) * 500  # 每 500 元一档
    
    # 构建可哈希的字符串
    cache_str = (
        f"{norm_destination}:"
        f"{budget_category}:"
        f"{travelers}:"
        f"{norm_pace}:"
        f"{norm_hotel}:"
        f"{day_count}:"
        f"{','.join(norm_preferences)}:"
        f"{','.join(norm_dietary)}:"
        f"{norm_notes}"
    )
    
    return hashlib.md5(cache_str.encode("utf-8")).hexdigest()


def _get_from_cache(cache_key: str) -> PlannerDraft | None:
    """从缓存中获取草稿，检查过期时间"""
    if cache_key not in _planner_draft_cache:
        return None
    
    cached_draft, cached_time = _planner_draft_cache[cache_key]
    if datetime.now() - cached_time > timedelta(minutes=_CACHE_TTL_MINUTES):
        # 缓存过期
        del _planner_draft_cache[cache_key]
        return None
    
    logger.info(f"[LLM 缓存] 命中缓存: {cache_key[:8]}...")
    return cached_draft


def _save_to_cache(cache_key: str, draft: PlannerDraft):
    """保存草稿到缓存，清理旧条目"""
    # 如果缓存已满，删除最早的条目
    if len(_planner_draft_cache) >= _MAX_CACHE_ENTRIES:
        sorted_items = sorted(
            _planner_draft_cache.items(),
            key=lambda item: item[1][1]
        )
        oldest_key = sorted_items[0][0]
        del _planner_draft_cache[oldest_key]
        logger.info(f"[LLM 缓存] 清理旧缓存: {oldest_key[:8]}...")
    
    _planner_draft_cache[cache_key] = (draft, datetime.now())
    logger.info(f"[LLM 缓存] 保存到缓存: {cache_key[:8]}...")


class PlannerDayDraft(BaseSchema):
    """LLM 返回的单日最小行程草稿。"""

    day_index: int = Field(..., ge=1)
    theme: str = Field(..., description="当天的简短主题")
    spot_name: str = Field(..., description="当天主要景点名称")
    spot_description: str = Field(..., description="推荐该景点的简短理由")
    meal_name: str = Field(..., description="当天的餐饮或餐厅建议")
    meal_notes: str = Field(..., description="简短的用餐说明")
    daily_note: str = Field(..., description="当天的一条简短规划备注")


class PlannerDraft(BaseSchema):
    """提供给 trip_service.py 使用的结构化行程草稿。"""

    summary: str = Field(..., description="整趟旅行的简短概述")
    tips: list[str] = Field(default_factory=list, description="旅行提示")
    days: list[PlannerDayDraft] = Field(default_factory=list)


class DayEditDraft(BaseSchema):
    """LLM 返回的单日编辑草稿。"""

    theme: str = Field(..., description="编辑后的当天主题")
    spot_name: str = Field(..., description="编辑后的主要景点名称")
    spot_description: str = Field(..., description="编辑后的景点说明")
    meal_name: str = Field(..., description="编辑后的餐饮名称")
    meal_notes: str = Field(..., description="编辑后的餐饮说明")
    daily_note: str = Field(..., description="编辑后的当天备注")


def _normalize_day_edit_payload(payload: dict) -> dict:
    """兼容模型返回的两种单日编辑格式。"""
    if "spot_name" in payload and "meal_name" in payload and "daily_note" in payload:
        return payload

    normalized = dict(payload)

    spots = payload.get("spots")
    if isinstance(spots, list) and spots:
        first_spot = spots[0] or {}
        normalized.setdefault("spot_name", first_spot.get("name", ""))
        normalized.setdefault("spot_description", first_spot.get("description", ""))

    meals = payload.get("meals")
    if isinstance(meals, list) and meals:
        first_meal = meals[0] or {}
        normalized.setdefault("meal_name", first_meal.get("name", ""))
        normalized.setdefault("meal_notes", first_meal.get("notes", ""))

    notes = payload.get("notes")
    if isinstance(notes, list) and notes:
        normalized.setdefault("daily_note", notes[-1] or "")

    return normalized


def _extract_json_object(raw_text: str) -> str | None:
    """从模型原始文本中尽量提取 JSON 对象字符串。"""
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    start_index = text.find("{")
    end_index = text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index <= start_index:
        return None

    return text[start_index : end_index + 1]


def collect_trip_context(
    destination: str,
    preferences: list[str] | None = None,
    pace: str | None = None,
    special_notes: str | None = None,
    top_k: int = 5,
    use_llm_rewrite: bool = False,
) -> list[str]:
    """收集生成行程时需要参考的本地攻略片段。"""
    return get_destination_guide_context(
        destination=destination,
        preferences=preferences,
        pace=pace,
        special_notes=special_notes,
        top_k=top_k,
        use_llm=use_llm_rewrite,
    )


def _build_chat_llm(use_fast_model: bool = False):
    """创建通用 ChatOpenAI 实例。

    Args:
        use_fast_model: 是否使用快速模式专用模型（如 qwen-plus），
                        比 qwen-max 更快，适合 fast/async 模式。
    """
    if not LLM_API_KEY:
        return None

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    model = TRIP_PLANNER_FAST_MODEL if use_fast_model else LLM_MODEL

    logger.info(
        f"[_build_chat_llm] 使用模型: {model}"
        f"{' (快速模式)' if use_fast_model else ''}"
    )

    return ChatOpenAI(
        model=model,
        temperature=0.3,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL or None,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )


def generate_planner_draft(
    request: TripRequest,
    rag_contexts: list[str],
    day_count: int,
    use_fast_model: bool = False,
) -> PlannerDraft | None:
    """
    使用 LangChain 生成结构化行程草稿。

    如果当前环境还没有准备好模型调用条件，就返回 None，
    这样 service 层还能回退到规则版实现。

    此函数会先尝试从缓存中获取结果，命中则直接返回。

    Args:
        use_fast_model: 是否使用快速模式专用模型（如 qwen-plus），
                        比 qwen-max 更快，适合 fast/async 模式。
    """
    # 1. 尝试从缓存中获取
    cache_key = _generate_cache_key(
        destination=request.destination,
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        budget=request.budget,
        travelers=request.travelers,
        preferences=request.preferences,
        pace=request.pace,
        dietary_preferences=request.dietary_preferences,
        hotel_level=request.hotel_level,
        special_notes=request.special_notes,
        day_count=day_count,
    )
    
    cached_result = _get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # 2. 缓存未命中，调用 LLM
    llm = _build_chat_llm(use_fast_model=use_fast_model)
    if llm is None:
        return None

    if rag_contexts:
        guide_context = "\n\n".join(rag_contexts)
        has_local_guide = True
    else:
        has_local_guide = False
        # RAG为空时，从高德地图预取该城市的真实POI作为候选池，防止LLM编造其他城市的地标
        poi_list = _fetch_city_pois(request.destination)
        guide_context = (
            "【重要】当前没有该目的地的本地攻略数据。"
            f"请严格基于「{request.destination}」这个具体目的地来规划行程。\n\n"
            f"以下是从地图服务获取到的「{request.destination}」真实景点和餐饮列表，"
            "你**必须**且**只能**从以下列表中选择景点和餐饮进行推荐：\n\n"
            f"{poi_list}\n\n"
            "注意事项：\n"
            "1. 每天的主要景点(spot_name)必须从上面的「景点列表」中选择一个，不要使用列表以外的名称。\n"
            "2. 每天的餐饮建议(meal_name)必须从上面的「餐饮列表」中选择或参考，不要推荐其他城市的美食。\n"
            "3. 绝对不要推荐其他城市（尤其是省会/知名旅游城市）的景点地标，这是最高优先级约束。"
        )

    system_prompt = (
        "你是一名旅行规划助手。"
        "请用中文生成简洁的结构化旅行草稿。"
        "需要遵守用户给出的目的地、预算、节奏和本地攻略上下文。"
        "你必须只输出一个 JSON 对象，不要输出 Markdown，不要输出解释文字，不要输出代码块。"
        "输出内容必须严格符合给定的结构化字段要求。"
        "如果用户在额外备注里提出了明确诉求，例如看日落、不想早起、少辣、拍照等，你要优先把这些诉求落实到具体某一天的主要景点或当天安排里，而不是只写成泛泛的提示。"
        "如果用户明确提到想看日落，请优先把适合看日落的地点安排为某一天的主要景点，或至少让当天主景点与日落安排保持强关联。"
        "特别注意：根据用户的偏好调整推荐内容："
        "1. 如果用户偏好包含'美食'："
        "   - 优先选择当地美食丰富的地点作为主要景点（如美食街、夜市、特色餐厅集中区、老字号店铺等）"
        "   - 每天的餐饮建议要详细且有特色，推荐当地标志性美食和必吃榜单"
        "   - 可以安排多个美食相关的活动，如早市、夜市探店等"
        "2. 如果用户偏好包含'自然风景'："
        "   - 优先选择公园、山、湖、海滩、森林公园、湿地公园等自然风光景点"
        "   - 推荐户外活动，如徒步、骑行、野餐、观景等"
        "   - 特别注意天气条件，推荐适合的穿着和装备"
        "3. 如果用户偏好包含'拍照'："
        "   - 优先选择标志性建筑、夜景、风景优美的网红打卡点、艺术展览、特色街区"
        "   - 特别推荐适合拍照的时间段（如日出、日落、蓝调时刻）和最佳拍摄角度"
        "   - 安排足够的拍照时间，避免行程过于紧凑"
        "4. 如果用户偏好包含'古镇'："
        "   - 优先选择古城、古镇、历史街区、古村落等有历史文化氛围的景点"
        "   - 推荐当地传统手工艺品、特色建筑、民俗活动"
        "   - 安排慢节奏游览，留出时间感受历史文化"
        "5. 如果用户偏好包含'休闲'："
        "   - 优先选择温泉、SPA、咖啡馆、书店、公园散步等放松休闲场所"
        "   - 推荐慢节奏行程，避免早起赶景点，安排充足的休息时间"
        "   - 可以安排一些轻松的体验活动，如手工制作、品茗等"
        "6. 预算约束：用户给出的预算是**人均预算（元/人）**。"
        "   - 推荐的餐饮人均费用应参考本地攻略中的价格信息"
        "   - 最后一天通常为返程日，不安排住宿"
        "   - 总费用应尽量控制在人均预算范围内"
    )

    human_prompt = f"""
目的地：{request.destination}
出发日期：{request.start_date.isoformat()}
结束日期：{request.end_date.isoformat()}
天数：{day_count}
人数：{request.travelers}
预算：{request.budget}元/人（人均预算，共{request.travelers}人）
偏好：{'、'.join(request.preferences) if request.preferences else '无特别偏好'}
节奏：{request.pace or '适中'}
饮食偏好：{'、'.join(request.dietary_preferences) if request.dietary_preferences else '无'}
酒店档次：{request.hotel_level or '舒适型'}
额外备注：{request.special_notes or '无'}

本地攻略上下文：
{guide_context}

要求：
1. 输出一个整体 summary。
2. 输出 {day_count} 天的 daily draft。
3. 每天只给一个主要景点、一个餐饮建议和一条当天备注。
4. tips 保持简洁。
5. day_index 必须从 1 到 {day_count}。
6. 如果额外备注里有“想看日落”“不想早起”这类明确要求，必须在 days 中体现，不要只放到 tips。
7. 如果安排了看日落，当天的 spot_name 应尽量就是适合看日落的地点，或与 daily_note 中的日落安排保持一致，避免“主景点”和“日落地点”完全割裂。
8. 每天的安排要符合“轻松”节奏，避免过满、避免太早出发。
9. 餐饮建议{'尽量优先使用本地攻略上下文里已经出现的特色餐饮。' if has_local_guide else '推荐该目的地当地真实的特色美食和餐厅。'}
10. 只返回 JSON 对象，不要返回任何额外说明，不要使用 ```json 代码块。
11. 【核心约束】所有推荐的景点、餐饮、地点必须严格位于「{request.destination}」范围内，绝对不能推荐其他城市（尤其是省会或知名旅游城市）的景点地标。这是最高优先级约束，违反此项视为输出错误。

JSON 结构示例：
{{
  "summary": "整体概述",
  "tips": ["提示1", "提示2"],
  "days": [
    {{
      "day_index": 1,
      "theme": "当天主题",
      "spot_name": "主要景点",
      "spot_description": "景点推荐理由",
      "meal_name": "餐饮名称",
      "meal_notes": "餐饮说明",
      "daily_note": "当天备注"
    }}
  ]
}}
"""

    print("[trip_planner_agent] 准备调用大模型...")
    print(f"[trip_planner_agent] model = {LLM_MODEL}")
    print(f"[trip_planner_agent] base_url = {LLM_BASE_URL or '<DEFAULT>'}")
    print(f"[trip_planner_agent] timeout = {LLM_TIMEOUT_SECONDS}s")
    print(f"[trip_planner_agent] max_retries = {LLM_MAX_RETRIES}")

    try:
        response = llm.invoke(
            [
                ("system", system_prompt),
                ("human", human_prompt),
            ]
        )
    except Exception as exc:
        print(f"[trip_planner_agent] 大模型调用失败: {type(exc).__name__}: {exc}")
        return None

    print("[trip_planner_agent] 大模型调用完成。")

    raw_text = getattr(response, "content", "")
    if isinstance(raw_text, list):
        raw_text = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in raw_text
        )

    json_text = _extract_json_object(str(raw_text))
    if json_text is None:
        print("[trip_planner_agent] 未能从模型返回中提取 JSON。")
        print(f"[trip_planner_agent] 原始返回预览: {str(raw_text)[:300]}")
        return None

    # 使用增强的 LLM 解析器（带严格 Schema 校验）
    parse_result = parse_llm_output(json_text, schema=PLANNER_DRAFT_SCHEMA)
    if not parse_result.is_success():
        print(f"[trip_planner_agent] 解析失败: {parse_result.error_message}")
        if parse_result.validation_errors:
            print(f"[trip_planner_agent] Schema 校验错误: {parse_result.validation_errors}")
        print(f"[trip_planner_agent] 原始返回预览: {str(raw_text)[:300]}")
        logger.warning(
            f"LLM 解析失败 - status: {parse_result.status.value}, "
            f"error: {parse_result.error_message}, "
            f"validation_errors: {parse_result.validation_errors}, "
            f"duration: {parse_result.duration_ms}ms"
        )
        return None

    try:
        result = PlannerDraft.model_validate(parse_result.data)
    except Exception as exc:
        print(f"[trip_planner_agent] Pydantic 校验失败: {type(exc).__name__}: {exc}")
        print(f"[trip_planner_agent] 原始返回预览: {str(raw_text)[:300]}")
        logger.error(f"Pydantic 校验失败: {exc}", exc_info=True)
        return None

    if len(result.days) != day_count:
        print(
            "[trip_planner_agent] 结构化结果天数不匹配，"
            f"expected={day_count}, actual={len(result.days)}"
        )
        return None

    # 3. 保存结果到缓存
    _save_to_cache(cache_key, result)
    
    return result


def generate_day_edit_draft(
    request: TripEditRequest,
    target_day: DayPlan,
    use_fast_model: bool = False,
) -> DayEditDraft | None:
    """
    使用 LLM 生成单日编辑草稿，失败时返回 None。

    这个函数只负责产出目标那一天的编辑结果，
    最终如何合并回完整 itinerary 由 service 层处理。
    """
    llm = _build_chat_llm(use_fast_model=use_fast_model)
    if llm is None:
        return None

    current_day_payload = {
        "day_index": target_day.day_index,
        "date": target_day.date.isoformat() if target_day.date else None,
        "theme": target_day.theme,
        "spots": [spot.model_dump(mode="json") for spot in target_day.spots],
        "meals": [meal.model_dump(mode="json") for meal in target_day.meals],
        "notes": list(target_day.notes),
    }

    current_itinerary_payload = request.current_itinerary.model_dump(mode="json")

    system_prompt = (
        "你是一名旅行行程编辑助手。"
        "请根据用户编辑指令，只重写目标那一天的核心安排。"
        "你必须只输出一个 JSON 对象，不要输出 Markdown，不要输出解释文字，不要输出代码块。"
        "编辑结果要尽量保留原 itinerary 的整体风格、预算结构和轻松程度。"
    )

    human_prompt = f"""
当前完整 itinerary：
{json.dumps(current_itinerary_payload, ensure_ascii=False, indent=2)}

需要重点编辑的目标 day：
{json.dumps(current_day_payload, ensure_ascii=False, indent=2)}

用户编辑指令：{request.user_instruction}
编辑范围：{request.edit_scope or '未指定'}
需要尽量保留的约束：{', '.join(request.preserve_constraints) if request.preserve_constraints else '无'}

要求：
1. 只输出目标那一天编辑后的结果。
2. 如果用户要求“更轻松”“不要安排太满”，请减少固定景点压力，让备注更自然。
3. 尽量延续原 itinerary 的城市、风格、餐饮语气和预算结构。
4. 不要输出额外字段。
5. 只返回 JSON 对象。

JSON 结构示例：
{{
  "theme": "编辑后的当天主题",
  "spot_name": "编辑后的主要景点",
  "spot_description": "编辑后的景点说明",
  "meal_name": "编辑后的餐饮名称",
  "meal_notes": "编辑后的餐饮说明",
  "daily_note": "编辑后的当天备注"
}}
"""

    print("[trip_planner_agent] 准备调用大模型进行单日编辑...")
    print(f"[trip_planner_agent] model = {LLM_MODEL}")
    print(f"[trip_planner_agent] base_url = {LLM_BASE_URL or '<DEFAULT>'}")

    try:
        response = llm.invoke(
            [
                ("system", system_prompt),
                ("human", human_prompt),
            ]
        )
    except Exception as exc:
        print(f"[trip_planner_agent] 单日编辑调用失败: {type(exc).__name__}: {exc}")
        return None

    raw_text = getattr(response, "content", "")
    if isinstance(raw_text, list):
        raw_text = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in raw_text
        )

    json_text = _extract_json_object(str(raw_text))
    if json_text is None:
        print("[trip_planner_agent] 未能从单日编辑结果中提取 JSON。")
        print(f"[trip_planner_agent] 原始返回预览: {str(raw_text)[:300]}")
        return None

    # 使用增强的 LLM 解析器（带严格 Schema 校验）
    parse_result = parse_llm_output(json_text, schema=DAY_EDIT_DRAFT_SCHEMA)
    if not parse_result.is_success():
        print(f"[trip_planner_agent] 编辑解析失败: {parse_result.error_message}")
        if parse_result.validation_errors:
            print(f"[trip_planner_agent] Schema 校验错误: {parse_result.validation_errors}")
        print(f"[trip_planner_agent] 原始返回预览: {str(raw_text)[:300]}")
        logger.warning(
            f"单日编辑 LLM 解析失败 - status: {parse_result.status.value}, "
            f"error: {parse_result.error_message}, "
            f"validation_errors: {parse_result.validation_errors}, "
            f"duration: {parse_result.duration_ms}ms"
        )
        return None

    try:
        normalized_payload = _normalize_day_edit_payload(parse_result.data)
        return DayEditDraft.model_validate(normalized_payload)
    except Exception as exc:
        print(f"[trip_planner_agent] 单日编辑 Pydantic 校验失败: {type(exc).__name__}: {exc}")
        print(f"[trip_planner_agent] 原始返回预览: {str(raw_text)[:300]}")
        logger.error(f"单日编辑 Pydantic 校验失败: {exc}", exc_info=True)
        return None
