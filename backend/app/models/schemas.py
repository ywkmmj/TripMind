from __future__ import annotations

import re
from datetime import date as DateType, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# 基础模型，配置忽略未知字段
class BaseSchema(BaseModel):
    model_config = {
        "extra": "ignore"  # 忽略未知字段，兼容前端可能发送的额外字段
    }


class TripRequest(BaseSchema):
    """用于生成新行程的请求体。"""

    destination: str = Field(..., description="目的地，例如大理")
    start_date: DateType = Field(..., description="出行开始日期")
    end_date: DateType = Field(..., description="出行结束日期")
    travelers: int = Field(..., ge=1, description="出行人数")
    days: int = Field(default=3, ge=1, le=14, description="旅行天数，默认为3天")
    budget: float = Field(..., ge=0, description="人均预算（元）")
    preferences: list[str] = Field(default_factory=list, description="旅行偏好标签")
    pace: str | None = Field(default=None, description="旅行节奏，例如轻松、适中、紧凑")
    dietary_preferences: list[str] = Field(
        default_factory=list,
        description="饮食偏好或忌口",
    )
    hotel_level: str | None = Field(default=None, description="酒店档次偏好")
    special_notes: str | None = Field(default=None, description="额外要求")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_flexible_date(cls, v: Any) -> Any:
        """兼容前端传入的非零填充日期格式，如 '2026-6-6' → '2026-06-06'。"""
        if isinstance(v, DateType):
            return v
        if not isinstance(v, str):
            raise ValueError(f"日期类型应为字符串或 date 对象，实际为 {type(v).__name__}")
        v = v.strip()
        # 尝试直接解析（ISO 格式等标准格式）
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        # 兼容非零填充格式：用正则匹配 YYYY-M-D / YYYY-MMM-DD 等
        m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", v)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return DateType(year, month, day)
            except ValueError as e:
                raise ValueError(f"无效日期 '{v}'：{e}")
        raise ValueError(
            f"无法解析日期 '{v}'，请使用 YYYY-MM-DD 格式（如 2026-06-06）"
        )


class TripEditRequest(BaseSchema):
    """用于修改已有行程的请求体。"""

    trip_id: str = Field(..., description="需要编辑的行程 ID")
    current_itinerary: "Itinerary" = Field(..., description="当前完整 itinerary")
    user_instruction: str = Field(..., description="用户新的修改要求")
    edit_scope: str | None = Field(default=None, description="编辑范围")
    preserve_constraints: list[str] = Field(
        default_factory=list,
        description="需要尽量保留的条件",
    )


class TripSaveRequest(BaseSchema):
    """用于保存当前 itinerary 的请求体。"""

    trip_id: str = Field(..., description="需要保存的行程 ID")
    itinerary: "Itinerary" = Field(..., description="完整行程数据")
    user_id: str | None = Field(default=None, description="用户 ID，当前版本可留空")


class PhotoItem(BaseSchema):
    """图片项目。"""

    url: str = Field(..., description="图片地址")
    title: str | None = Field(default=None, description="图片标题")


class SpotItem(BaseSchema):
    """单个景点安排。"""

    name: str = Field(..., description="景点名称")
    start_time: str | None = Field(default=None, description="开始时间")
    end_time: str | None = Field(default=None, description="结束时间")
    description: str | None = Field(default=None, description="景点安排说明")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    location: str | None = Field(default=None, description="景点位置描述")
    image_url: str | None = Field(default=None, description="景点主图片地址")
    images: list[PhotoItem] = Field(default_factory=list, description="景点图片列表")
    address: str | None = Field(default=None, description="景点详细地址")
    latitude: float | None = Field(default=None, description="景点纬度")
    longitude: float | None = Field(default=None, description="景点经度")
    poi_id: str | None = Field(default=None, description="地图服务返回的 POI 标识")
    rating: float | None = Field(default=None, ge=0, le=5, description="评分，0-5分")
    price_level: str | None = Field(default=None, description="价格等级，例如：便宜、适中、较贵、昂贵")
    opening_hours: str | None = Field(default=None, description="营业时间")
    phone: str | None = Field(default=None, description="联系电话")
    website: str | None = Field(default=None, description="官方网站")
    tags: list[str] = Field(default_factory=list, description="标签/特色")
    cityname: str | None = Field(default=None, description="城市名称")
    adname: str | None = Field(default=None, description="区域名称")


class MealItem(BaseSchema):
    """单个餐饮安排。"""

    name: str = Field(..., description="餐厅或餐饮建议名称")
    meal_type: str = Field(..., description="早餐、午餐、晚餐等")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    price_per_person: float | None = Field(default=None, ge=0, description="人均消费")
    notes: str | None = Field(default=None, description="补充说明")
    image_url: str | None = Field(default=None, description="餐厅主图片")
    images: list[PhotoItem] = Field(default_factory=list, description="餐厅图片列表")
    address: str | None = Field(default=None, description="餐厅详细地址")
    latitude: float | None = Field(default=None, description="纬度")
    longitude: float | None = Field(default=None, description="经度")
    poi_id: str | None = Field(default=None, description="POI 标识")
    rating: float | None = Field(default=None, ge=0, le=5, description="评分，0-5分")
    opening_hours: str | None = Field(default=None, description="营业时间")
    phone: str | None = Field(default=None, description="联系电话")
    website: str | None = Field(default=None, description="官方网站")
    cuisine: list[str] = Field(default_factory=list, description="菜系类型")
    tags: list[str] = Field(default_factory=list, description="标签/特色")
    cityname: str | None = Field(default=None, description="城市名称")
    adname: str | None = Field(default=None, description="区域名称")


class HotelItem(BaseSchema):
    """单个住宿安排。"""

    name: str = Field(..., description="酒店名称")
    level: str | None = Field(default=None, description="酒店档次")
    star_rating: int | None = Field(default=None, ge=1, le=5, description="星级，1-5星")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    price_per_night: float | None = Field(default=None, ge=0, description="每晚价格")
    location: str | None = Field(default=None, description="酒店位置")
    image_url: str | None = Field(default=None, description="酒店主图片")
    images: list[PhotoItem] = Field(default_factory=list, description="酒店图片列表")
    address: str | None = Field(default=None, description="酒店详细地址")
    latitude: float | None = Field(default=None, description="酒店纬度")
    longitude: float | None = Field(default=None, description="酒店经度")
    poi_id: str | None = Field(default=None, description="POI 标识")
    rating: float | None = Field(default=None, ge=0, le=5, description="评分，0-5分")
    opening_hours: str | None = Field(default=None, description="前台营业时间")
    phone: str | None = Field(default=None, description="联系电话")
    website: str | None = Field(default=None, description="官方网站")
    facilities: list[str] = Field(default_factory=list, description="设施列表")
    tags: list[str] = Field(default_factory=list, description="标签/特色")
    cityname: str | None = Field(default=None, description="城市名称")
    adname: str | None = Field(default=None, description="区域名称")


class TransportItem(BaseSchema):
    """单段交通安排。"""

    mode: str = Field(..., description="交通方式，例如步行、打车、公交")
    from_place: str | None = Field(default=None, description="出发地")
    to_place: str | None = Field(default=None, description="目的地")
    estimated_cost: float = Field(default=0.0, ge=0, description="预估花费")
    duration: str | None = Field(default=None, description="预计耗时")
    distance_km: float | None = Field(default=None, ge=0, description="预计距离，单位公里")
    estimated_minutes: int | None = Field(default=None, ge=0, description="预计耗时，单位分钟")


class BudgetBreakdown(BaseSchema):
    """预算拆分（人均）。"""
    transport: float = Field(default=0.0, ge=0, description="交通预算(人均)")
    hotel: float = Field(default=0.0, ge=0, description="住宿预算(人均)")
    meals: float = Field(default=0.0, ge=0, description="餐饮预算(人均)")
    tickets: float = Field(default=0.0, ge=0, description="门票预算(人均)")
    insurance: float = Field(default=0.0, ge=0, description="旅行保险(人均)")
    contingency: float = Field(default=0.0, ge=0, description="应急备用金(人均)")
    shopping_misc: float = Field(default=0.0, ge=0, description="购物/杂项(人均)")
    total: float = Field(default=0.0, ge=0, description="预算总计(人均)")
    total_for_group: float = Field(default=0.0, ge=0, description="团队总预算")
    travelers: int = Field(default=1, ge=1, description="出行人数")
    budget_alert: str | None = Field(default=None, description="预算偏差提示信息")


class DayPlan(BaseSchema):
    """单日行程安排。"""

    day_index: int = Field(..., ge=1, description="第几天")
    date: DateType | None = Field(default=None, description="当天日期")
    theme: str | None = Field(default=None, description="当天主题")
    spots: list[SpotItem] = Field(default_factory=list, description="景点安排")
    meals: list[MealItem] = Field(default_factory=list, description="餐饮安排")
    hotel: HotelItem | None = Field(default=None, description="住宿安排")
    transport: list[TransportItem] = Field(default_factory=list, description="交通安排")
    notes: list[str] = Field(default_factory=list, description="补充说明")


class Itinerary(BaseSchema):
    """完整行程。"""

    trip_id: str = Field(..., description="行程唯一标识")
    destination: str = Field(..., description="目的地")
    summary: str = Field(..., description="整趟行程的概述")
    days: list[DayPlan] = Field(default_factory=list, description="逐日行程")
    estimated_budget: float = Field(default=0.0, ge=0, description="预算总计")
    budget_breakdown: BudgetBreakdown = Field(..., description="预算明细")
    tips: list[str] = Field(default_factory=list, description="旅行建议")
    source_notes: list[str] = Field(
        default_factory=list,
        description="RAG 或规则生成产生的补充说明",
    )


class TripDetailResponse(BaseSchema):
    """查询已保存行程时返回的响应体。"""

    trip_id: str = Field(..., description="行程 ID")
    itinerary: Itinerary = Field(..., description="已保存的完整行程")
    created_at: datetime | None = Field(default=None, description="创建时间")
    updated_at: datetime | None = Field(default=None, description="更新时间")


class TripSummaryItem(BaseSchema):
    """已保存行程的摘要信息。"""

    trip_id: str = Field(..., description="行程 ID")
    destination: str = Field(..., description="目的地")
    summary: str = Field(..., description="行程概述")
    created_at: datetime | None = Field(default=None, description="创建时间")
    updated_at: datetime | None = Field(default=None, description="更新时间")


class TripListResponse(BaseSchema):
    """行程列表接口的响应结构。"""

    total: int = Field(..., ge=0, description="列表总数")
    items: list[TripSummaryItem] = Field(default_factory=list, description="行程摘要列表")


class ChatRequest(BaseSchema):
    """统一聊天接口的请求体。"""

    message: str = Field(..., description="用户输入的消息")
    session_id: str | None = Field(default=None, description="会话ID，用于追踪")


class ChatResponse(BaseSchema):
    """统一聊天接口的响应体。"""

    status: str = Field(..., description="响应状态: success/error/need_more_info/need_clarification")
    intent: str = Field(..., description="识别到的用户意图")
    message: str | None = Field(default=None, description="响应消息")
    itinerary: dict | None = Field(default=None, description="行程数据（如果有）")
    weather: dict | None = Field(default=None, description="天气数据（如果有）")
    places: dict | None = Field(default=None, description="地点数据（如果有）")
    trips: dict | None = Field(default=None, description="行程列表（如果有）")
    params: dict = Field(default_factory=dict, description="提取到的参数")
    confidence: float = Field(default=0.0, description="意图识别置信度")


class AgentStep(BaseSchema):
    """ReAct Agent 的单步执行记录。"""

    step: int = Field(..., description="步骤序号")
    state: str | None = Field(default=None, description="步骤状态")
    thought: str | None = Field(default=None, description="思考内容")
    action: str | None = Field(default=None, description="调用的工具或动作")
    observation: str | None = Field(default=None, description="工具观察结果")
    tool_input: dict[str, Any] | str | None = Field(default=None, description="工具输入")


class ReactTripResponse(BaseSchema):
    """ReAct 增强行程生成响应。"""

    success: bool = Field(..., description="是否成功返回行程")
    mode: str = Field(default="react_agent", description="生成模式：react_agent 或 fallback")
    fallback_used: bool = Field(default=False, description="是否使用稳定主链路回退")
    itinerary: Itinerary | None = Field(default=None, description="生成的行程")
    react_answer: str | None = Field(default=None, description="Agent 最终回答")
    steps: list[AgentStep] = Field(default_factory=list, description="Agent 执行步骤")
    tool_calls: int = Field(default=0, ge=0, description="工具调用次数")
    error: str | None = Field(default=None, description="Agent 或回退错误")


# ==================== 可观测性与调试相关模型 ====================


class RAGContextItem(BaseSchema):
    """单个RAG检索上下文记录。"""
    
    content: str = Field(..., description="检索到的文本内容")
    score: float | None = Field(default=None, description="相似度评分")
    source: str | None = Field(default=None, description="来源（文件名或文档ID）")
    chunk_index: int | None = Field(default=None, description="分块索引")


class LLMCallRecord(BaseSchema):
    """LLM调用记录。"""
    
    model: str = Field(..., description="使用的模型名称")
    prompt: str = Field(..., description="发给LLM的完整prompt")
    response: str = Field(..., description="LLM的原始响应")
    temperature: float | None = Field(default=None, description="温度参数")
    max_tokens: int | None = Field(default=None, description="最大token数")
    tokens_used: int | None = Field(default=None, description="消耗的token数量")
    cost: float | None = Field(default=None, description="预估成本")
    duration_ms: int | None = Field(default=None, description="调用耗时（毫秒）")
    success: bool = Field(default=True, description="是否成功")
    error_message: str | None = Field(default=None, description="错误信息（如果失败）")


class AgentStepRecord(BaseSchema):
    """Agent执行步骤记录（用于ReAct Agent）。"""
    
    step_index: int = Field(..., description="步骤索引")
    state: str = Field(..., description="状态：thinking/acting/observing/finished/error")
    thought: str | None = Field(default=None, description="思考内容")
    action: str | None = Field(default=None, description="执行的动作/工具名称")
    tool_input: dict | None = Field(default=None, description="工具输入参数")
    observation: str | None = Field(default=None, description="观察结果")
    duration_ms: int | None = Field(default=None, description="本步骤耗时")


class TraceRecord(BaseSchema):
    """完整的追踪记录（贯穿整个请求链路）。"""
    
    trace_id: str = Field(..., description="唯一追踪ID")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    request_type: str = Field(..., description="请求类型：trip_generation/chat/weather等")
    
    # 输入层
    user_request: dict | None = Field(default=None, description="用户原始请求数据")
    destination: str | None = Field(default=None, description="目的地")
    
    # RAG检索
    rag_contexts: list[RAGContextItem] | None = Field(default=None, description="RAG检索结果")
    rag_duration_ms: int | None = Field(default=None, description="RAG检索耗时")
    cache_hit: bool | None = Field(default=None, description="是否命中缓存")
    
    # LLM调用
    llm_calls: list[LLMCallRecord] | None = Field(default=None, description="LLM调用记录列表")
    
    # Agent执行
    agent_steps: list[AgentStepRecord] | None = Field(default=None, description="Agent执行步骤")
    agent_type: str | None = Field(default=None, description="使用的Agent类型")
    
    # 输出层
    final_output: dict | None = Field(default=None, description="最终输出给用户的数据")
    success: bool = Field(default=True, description="整个请求是否成功")
    error_message: str | None = Field(default=None, description="错误信息（如果失败）")
    
    # 整体统计
    total_duration_ms: int | None = Field(default=None, description="总耗时")
    total_tokens_used: int | None = Field(default=None, description="总token使用量")
    total_cost: float | None = Field(default=None, description="预估总成本")


class ValidationIssueItem(BaseSchema):
    """单个校验问题"""
    type: str = Field(..., description="问题类型")
    status: str = Field(..., description="问题状态")
    day_index: int | None = Field(default=None, description="第几天")
    spot_name: str | None = Field(default=None, description="景点名称")
    message: str = Field(..., description="问题描述")
    suggestion: str | None = Field(default=None, description="改善建议")
    details: dict[str, Any] = Field(default_factory=dict, description="详细信息")


class ValidationSummary(BaseSchema):
    """校验摘要"""
    total_days: int = Field(..., description="总天数")
    total_spots: int = Field(..., description="总景点数")
    total_issues: int = Field(..., description="总问题数")
    error_count: int = Field(..., description="错误数")
    warning_count: int = Field(..., description="警告数")
    issues_by_type: dict[str, int] = Field(default_factory=dict, description="按类型统计")
    budget_info: dict[str, Any] | None = Field(default=None, description="预算信息")


class ItineraryValidationResponse(BaseSchema):
    """行程校验响应"""
    overall_status: str = Field(..., description="整体状态")
    issues: list[ValidationIssueItem] = Field(default_factory=list, description="问题列表")
    summary: ValidationSummary = Field(..., description="摘要信息")
    has_errors: bool = Field(..., description="是否有错误")
    has_warnings: bool = Field(..., description="是否有警告")


class PipelineStageResult(BaseSchema):
    """流水线单个阶段结果"""
    stage_type: str = Field(..., description="阶段类型")
    status: str = Field(..., description="状态")
    start_time: str | None = Field(default=None, description="开始时间")
    end_time: str | None = Field(default=None, description="结束时间")
    duration_ms: float | None = Field(default=None, description="耗时（毫秒）")
    error: str | None = Field(default=None, description="错误信息")
    warnings: list[str] = Field(default_factory=list, description="警告列表")
    metadata: dict[str, Any] = Field(default_factory=dict, description="阶段元数据")


class PipelineSummary(BaseSchema):
    """流水线摘要"""
    success: bool = Field(..., description="是否成功")
    total_stages: int = Field(..., description="总阶段数")
    completed_stages: int = Field(..., description="完成阶段数")
    failed_stages: int = Field(..., description="失败阶段数")
    total_warnings: int = Field(..., description="总警告数")
    total_duration_ms: float | None = Field(default=None, description="总耗时（毫秒）")
    stage_results: dict[str, Any] = Field(default_factory=dict, description="各阶段详细结果")


class PipelineResponse(BaseSchema):
    """流水线完整响应"""
    success: bool = Field(..., description="是否成功")
    itinerary: Itinerary | None = Field(default=None, description="生成的行程")
    summary: PipelineSummary = Field(..., description="执行摘要")
    final_error: str | None = Field(default=None, description="最终错误")


class TraceListResponse(BaseSchema):
    """追踪记录列表响应。"""
    
    total: int = Field(..., ge=0, description="总数")
    items: list[TraceRecord] = Field(default_factory=list, description="追踪记录列表")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")
