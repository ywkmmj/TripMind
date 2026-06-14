from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, TypedDict

from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

try:
    from langchain_openai import ChatOpenAI
    LLM_AVAILABLE = True
except ImportError:
    logger.warning("LangChain LLM 未安装，意图识别功能不可用")
    LLM_AVAILABLE = False


class UserIntent(Enum):
    """用户意图枚举"""
    TRIP_PLANNING = "trip_planning"
    TRIP_EDITING = "trip_editing"
    WEATHER_QUERY = "weather_query"
    PLACE_INFO = "place_info"
    EXPORT_DOC = "export_doc"
    HISTORY_QUERY = "history_query"
    GENERAL_CHAT = "general_chat"
    UNKNOWN = "unknown"


class IntentRecognitionResult(TypedDict):
    """意图识别结果"""
    intent: str
    confidence: float
    extracted_params: Dict[str, Any]
    reasoning: str


class IntentRouter:
    """基于 LLM 的意图路由器"""

    def __init__(self):
        self._llm = None
        self._initialized = False

    def _build_llm(self):
        """构建 LLM 实例"""
        if not LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY 未配置")

        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            temperature=0.0,
            max_retries=LLM_MAX_RETRIES,
            timeout=LLM_TIMEOUT_SECONDS,
        )

    def _initialize(self):
        """初始化路由器"""
        if self._initialized:
            return

        if not LLM_AVAILABLE:
            raise RuntimeError("LLM 未安装，无法初始化意图路由器")

        self._llm = self._build_llm()
        self._initialized = True
        logger.info("IntentRouter 初始化完成")

    def _build_intent_prompt(self, user_input: str) -> str:
        """构建意图识别提示词"""
        return f"""你是一个专业的意图识别助手。请分析用户的请求，判断其意图类型，并提取关键参数。

可能的意图类型:
- trip_planning: 用户想要生成新的旅行计划（包含目的地、天数等相关信息）
- trip_editing: 用户想要修改或编辑已有的行程
- weather_query: 用户单纯查询天气信息
- place_info: 用户查询地点、景点、路线等信息
- export_doc: 用户要求导出文档（Markdown/PDF）
- history_query: 用户查询或查看历史行程
- general_chat: 一般性闲聊、问候等
- unknown: 无法识别的意图

用户请求: {user_input}

请按以下 JSON 格式返回，不要返回其他内容:
{{
    "intent": "意图类型名称",
    "confidence": 0.0-1.0之间的置信度,
    "extracted_params": {{
        "destination": "目的地（如果有）",
        "days": 天数（如果有）,
        "preferences": "用户偏好（如果有）",
        "trip_id": "行程ID（如果有）",
        "export_format": "导出格式（markdown/pdf）（如果有）"
    }},
    "reasoning": "简短的推理说明"
}}"""

    async def recognize_intent(self, user_input: str) -> IntentRecognitionResult:
        """
        识别用户意图

        Args:
            user_input: 用户输入

        Returns:
            意图识别结果
        """
        self._initialize()

        prompt = self._build_intent_prompt(user_input)

        try:
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 解析 LLM 返回的 JSON
            import json
            result = json.loads(content)
            
            # 验证结果
            if "intent" not in result:
                result["intent"] = UserIntent.UNKNOWN.value
            
            if "confidence" not in result:
                result["confidence"] = 0.5
            
            if "extracted_params" not in result:
                result["extracted_params"] = {}
            
            if "reasoning" not in result:
                result["reasoning"] = "无"
            
            logger.info(f"意图识别: {result['intent']}, 置信度: {result['confidence']}")
            return result

        except Exception as e:
            logger.error(f"意图识别失败: {e}")
            return {
                "intent": UserIntent.UNKNOWN.value,
                "confidence": 0.0,
                "extracted_params": {},
                "reasoning": f"识别失败: {str(e)}"
            }

    async def route(self, user_input: str, **kwargs) -> Dict[str, Any]:
        """
        根据用户意图路由到对应处理流程

        Args:
            user_input: 用户输入
            **kwargs: 其他参数

        Returns:
            处理结果
        """
        self._initialize()

        recognition_result = await self.recognize_intent(user_input)
        intent_str = recognition_result["intent"]
        params = recognition_result["extracted_params"]

        # 合并外部参数
        params.update(kwargs)

        logger.info(f"路由到意图: {intent_str}")

        # 根据意图分发
        if intent_str == UserIntent.TRIP_PLANNING.value:
            return await self._handle_trip_planning(user_input, params)
        elif intent_str == UserIntent.TRIP_EDITING.value:
            return await self._handle_trip_editing(user_input, params)
        elif intent_str == UserIntent.WEATHER_QUERY.value:
            return await self._handle_weather_query(user_input, params)
        elif intent_str == UserIntent.PLACE_INFO.value:
            return await self._handle_place_info(user_input, params)
        elif intent_str == UserIntent.EXPORT_DOC.value:
            return await self._handle_export_doc(user_input, params)
        elif intent_str == UserIntent.HISTORY_QUERY.value:
            return await self._handle_history_query(user_input, params)
        elif intent_str == UserIntent.GENERAL_CHAT.value:
            return await self._handle_general_chat(user_input, params)
        else:
            return await self._handle_unknown(user_input, params)

    async def _handle_trip_planning(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理行程规划意图"""
        destination = params.get("destination", "")
        days = params.get("days", 3)
        preferences = params.get("preferences", "")

        if not destination:
            return {
                "status": "need_more_info",
                "intent": "trip_planning",
                "message": "请问你想要去哪个地方旅行？",
                "params": params
            }

        # 调用现有的行程规划服务
        try:
            from app.services.trip_service import generate_trip_itinerary
            from app.models.schemas import TripRequest
            from datetime import date, timedelta

            # 为缺失的字段提供默认值
            today = date.today()
            start_date = params.get("start_date", today)
            if isinstance(start_date, str):
                from datetime import datetime
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            
            end_date = params.get("end_date", start_date + timedelta(days=days - 1))
            if isinstance(end_date, str):
                from datetime import datetime
                end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            
            travelers = params.get("travelers", params.get("people", 2))
            budget = params.get("budget", 3000.0)
            if isinstance(budget, str):
                budget = float(budget)
            
            # 处理 preferences - 可能是字符串需要转为列表
            preference_list = []
            if preferences:
                if isinstance(preferences, str):
                    preference_list = [preferences]
                elif isinstance(preferences, list):
                    preference_list = preferences
            
            request = TripRequest(
                destination=destination,
                start_date=start_date,
                end_date=end_date,
                travelers=travelers,
                days=days,
                budget=budget,
                preferences=preference_list,
                pace=params.get("pace"),
                dietary_preferences=params.get("dietary_preferences", []),
                hotel_level=params.get("hotel_level"),
                special_notes=params.get("special_notes")
            )

            itinerary = generate_trip_itinerary(request)

            return {
                "status": "success",
                "intent": "trip_planning",
                "message": f"已成功规划 {days} 天的 {destination} 旅行行程！",
                "itinerary": itinerary.dict(),
                "params": params
            }

        except Exception as e:
            logger.error(f"行程规划失败: {e}")
            return {
                "status": "error",
                "intent": "trip_planning",
                "message": f"行程规划失败: {str(e)}",
                "params": params
            }

    async def _handle_trip_editing(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理行程编辑意图"""
        trip_id = params.get("trip_id", "")
        edit_instruction = user_input

        if not trip_id:
            return {
                "status": "need_more_info",
                "intent": "trip_editing",
                "message": "请问你想要编辑哪个行程？请提供 trip_id。",
                "params": params
            }

        try:
            from app.services.trip_service import edit_trip_itinerary
            from app.models.schemas import TripEditRequest

            request = TripEditRequest(
                trip_id=trip_id,
                edit_instruction=edit_instruction
            )

            itinerary = edit_trip_itinerary(request)

            return {
                "status": "success",
                "intent": "trip_editing",
                "itinerary": itinerary.dict(),
                "params": params
            }

        except Exception as e:
            logger.error(f"行程编辑失败: {e}")
            return {
                "status": "error",
                "intent": "trip_editing",
                "message": f"行程编辑失败: {str(e)}",
                "params": params
            }

    async def _handle_weather_query(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理天气查询意图"""
        destination = params.get("destination", "")

        if not destination:
            return {
                "status": "need_more_info",
                "intent": "weather_query",
                "message": "请问你想要查询哪个城市的天气？",
                "params": params
            }

        try:
            from app.services.weather_service import get_weather_forecast

            weather = get_weather_forecast(city=destination)

            return {
                "status": "success",
                "intent": "weather_query",
                "message": f"已查询到 {destination} 的天气信息",
                "weather": weather,
                "params": params
            }

        except Exception as e:
            logger.error(f"天气查询失败: {e}")
            return {
                "status": "error",
                "intent": "weather_query",
                "message": f"天气查询失败: {str(e)}",
                "params": params
            }

    async def _handle_place_info(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理地点信息查询意图 - 通过 MCP Client 调用地图工具"""
        destination = params.get("destination", "")

        if not destination:
            return {
                "status": "need_more_info",
                "intent": "place_info",
                "message": "请问你想要查询哪个地方的信息？",
                "params": params
            }

        try:
            # 通过 MCP Client 调用地图工具（替代直接 import）
            from app.mcp.client import get_mcp_client

            mcp_client = get_mcp_client()
            places = await mcp_client.call_tool(
                "search_places",
                keyword=destination,
                city=destination,
                page_size=10,
            )

            return {
                "status": "success",
                "intent": "place_info",
                "places": places,
                "params": params
            }

        except Exception as e:
            logger.error(f"地点信息查询失败: {e}")
            return {
                "status": "error",
                "intent": "place_info",
                "message": f"地点信息查询失败: {str(e)}",
                "params": params
            }

    async def _handle_export_doc(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理文档导出意图"""
        trip_id = params.get("trip_id", "")
        export_format = params.get("export_format", "markdown")

        if not trip_id:
            return {
                "status": "need_more_info",
                "intent": "export_doc",
                "message": "请问你想要导出哪个行程？请提供 trip_id。",
                "params": params
            }

        return {
            "status": "success",
            "intent": "export_doc",
            "message": f"准备导出行程 {trip_id} 为 {export_format} 格式",
            "params": params
        }

    async def _handle_history_query(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理历史查询意图"""
        try:
            from app.services.storage_service import list_saved_itineraries

            trips = list_saved_itineraries()

            return {
                "status": "success",
                "intent": "history_query",
                "trips": trips.dict(),
                "params": params
            }

        except Exception as e:
            logger.error(f"历史查询失败: {e}")
            return {
                "status": "error",
                "intent": "history_query",
                "message": f"历史查询失败: {str(e)}",
                "params": params
            }

    async def _handle_general_chat(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理一般性闲聊意图"""
        # 简单的问候回复
        greetings = ["你好", "您好", "hello", "hi", "嗨"]
        if any(greet in user_input.lower() for greet in greetings):
            return {
                "status": "success",
                "intent": "general_chat",
                "message": "你好！我是你的旅行规划助手。我可以帮你：\n1. 规划旅行行程\n2. 查询天气信息\n3. 查询景点信息\n4. 查看历史行程\n\n你需要什么帮助？",
                "params": params
            }

        return {
            "status": "success",
            "intent": "general_chat",
            "message": "我是旅行规划助手。如果你需要规划旅行、查询天气或景点，请告诉我！",
            "params": params
        }

    async def _handle_unknown(self, user_input: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理无法识别的意图"""
        return {
            "status": "need_clarification",
            "intent": "unknown",
            "message": "抱歉，我不太理解你的请求。你可以：\n1. 告诉我想要去哪个地方旅行\n2. 查询某个城市的天气\n3. 查询某个地点的信息\n\n请具体描述你的需求。",
            "params": params
        }


_router: IntentRouter | None = None


def get_intent_router() -> IntentRouter:
    """获取全局 IntentRouter 实例（单例模式）"""
    global _router
    if _router is None:
        _router = IntentRouter()
    return _router
