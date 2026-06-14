from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.mcp.intent_router import get_intent_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    """
    统一聊天入口 - 支持 LLM 意图识别路由

    支持的意图:
    - trip_planning: 行程规划
    - trip_editing: 行程编辑
    - weather_query: 天气查询
    - place_info: 地点信息查询
    - export_doc: 文档导出
    - history_query: 历史查询
    - general_chat: 闲聊
    """
    try:
        router_instance = get_intent_router()

        result = await router_instance.route(
            user_input=request.message,
            session_id=request.session_id
        )

        # 构建响应
        response = ChatResponse(
            status=result.get("status", "success"),
            intent=result.get("intent", "unknown"),
            message=result.get("message"),
            itinerary=result.get("itinerary"),
            weather=result.get("weather"),
            places=result.get("places"),
            trips=result.get("trips"),
            params=result.get("params", {}),
            confidence=result.get("confidence", 0.0)
        )

        return response

    except Exception as e:
        logger.error(f"聊天接口异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"服务异常: {str(e)}"
        )


@router.post("/intent", response_model=dict)
async def intent_recognition_endpoint(request: ChatRequest) -> dict:
    """
    仅做意图识别，不执行实际业务逻辑
    """
    try:
        router_instance = get_intent_router()
        result = await router_instance.recognize_intent(request.message)

        return {
            "intent": result["intent"],
            "confidence": result["confidence"],
            "extracted_params": result["extracted_params"],
            "reasoning": result["reasoning"]
        }

    except Exception as e:
        logger.error(f"意图识别接口异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"服务异常: {str(e)}"
        )
