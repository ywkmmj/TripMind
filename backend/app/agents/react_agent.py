from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Optional, TypedDict
from enum import Enum
import time

from app.agents.trip_planner_agent import (
    collect_trip_context,
    generate_planner_draft,
)
from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
)
from app.models.schemas import Itinerary
from app.services.tracing_service import TracingService, TraceContext

logger = logging.getLogger(__name__)


class AgentState(Enum):
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    FINISHED = "finished"
    ERROR = "error"


class ToolCall(TypedDict):
    tool_name: str
    tool_input: Dict[str, Any]


class ReActStep(TypedDict):
    step: int
    state: str
    thought: str
    action: Optional[str]
    observation: Optional[str]
    tool_input: Optional[Dict[str, Any]]


class ReActResult(TypedDict):
    success: bool
    planner_draft: Optional[Any]
    final_answer: str
    steps: List[ReActStep]
    error: Optional[str]
    tool_calls: int


class BaseTool:
    """可插拔工具的基类"""
    name: str
    description: str

    def __init__(self):
        pass

    def run(self, **kwargs) -> str:
        raise NotImplementedError

    def __call__(self, **kwargs) -> str:
        return self.run(**kwargs)


class RAGTool(BaseTool):
    """RAG检索工具"""
    name = "search_destination_guide"
    description = "搜索目的地的本地攻略，获取景点、美食、住宿等信息"

    def run(self, destination: str, top_k: int = 5) -> str:
        """搜索目的地攻略"""
        try:
            from app.agents.tools.rag_tool import get_destination_guide_context
            contexts = get_destination_guide_context(destination=destination, top_k=top_k)
            if not contexts:
                return f"未找到{destination}的相关攻略信息。"
            result = f"【{destination}本地攻略】\n\n"
            for i, ctx in enumerate(contexts, 1):
                result += f"{i}. {ctx}\n\n"
            return result
        except Exception as e:
            return f"搜索攻略失败: {str(e)}"


class WeatherTool(BaseTool):
    """天气查询工具 - 通过 MCP Client 调用"""
    name = "get_weather"
    description = "查询目的地的天气预报信息"

    def run(self, city: str) -> str:
        """通过 MCP Client 查询天气（替代直接 import 服务端模块）"""
        try:
            import asyncio
            from app.mcp.client import get_mcp_client

            mcp_client = get_mcp_client()
            weather = asyncio.run(mcp_client.call_tool("get_weather_forecast", city=city))
            if "error" in weather:
                return f"天气查询失败: {weather.get('error')}"
            days = weather.get("days", [])
            if not days:
                return f"暂无{city}的天气预报信息。"
            result = f"【{city}天气预报】\n\n"
            for day in days[:7]:
                result += (
                    f"{day.get('date', '')} ({day.get('week', '')}): "
                    f"白天{day.get('day_weather', '')}, "
                    f"{day.get('day_temp', '')}°C, "
                    f"夜间{day.get('night_weather', '')}, "
                    f"{day.get('night_temp', '')}°C\n"
                )
            return result
        except Exception as e:
            return f"天气查询失败: {str(e)}"


class MapTool(BaseTool):
    """地图搜索工具 - 通过 MCP Client 调用"""
    name = "search_places"
    description = "搜索目的地的景点、餐厅、酒店等POI信息"

    def run(self, keyword: str, city: str, page_size: int = 5) -> str:
        """通过 MCP Client 搜索地点（替代直接 import 服务端模块）"""
        try:
            import asyncio
            from app.mcp.client import get_mcp_client

            mcp_client = get_mcp_client()
            result = asyncio.run(
                mcp_client.call_tool("search_places", keyword=keyword, city=city, page_size=page_size)
            )
            if "error" in result:
                return f"地点搜索失败: {result.get('error')}"
            pois = result.get("pois", [])
            if not pois:
                return f"未找到{city}关于{keyword}的相关地点。"
            output = f"【{city}{keyword}搜索结果】\n\n"
            for i, poi in enumerate(pois[:page_size], 1):
                output += (
                    f"{i}. {poi.get('name', '未知')}\n"
                    f"   地址: {poi.get('address', '未知')}\n"
                    f"   类型: {poi.get('type', '未知')}\n"
                    f"   评分: {poi.get('rating', '暂无')}\n\n"
                )
            return output
        except Exception as e:
            return f"地点搜索失败: {str(e)}"


class ReActAgent:
    """
    完整的 ReAct Agent，包含之前 Agent 的全部功能
    """
    def __init__(self, max_steps: int = 5):
        self.max_steps = max_steps
        self.tools: Dict[str, BaseTool] = {}
        self._init_tools()

    def _init_tools(self):
        self.tools = {
            RAGTool.name: RAGTool(),
            WeatherTool.name: WeatherTool(),
            MapTool.name: MapTool(),
        }
        logger.info(f"工具系统初始化完成，共 {len(self.tools)} 个工具")

    def run(self, trip_request: Any, trace_ctx: Optional[TraceContext] = None) -> ReActResult:
        """
        使用 ReAct Agent 生成完整的行程（同步方法）
        """
        destination = trip_request.destination
        days = trip_request.days
        preference_text = "、".join(trip_request.preferences) if trip_request.preferences else "常规旅行体验"

        # 如果提供了追踪上下文，设置 Agent 类型
        if trace_ctx:
            TracingService.set_agent_type(trace_ctx, "ReActAgent")

        # 记录执行步骤
        steps: List[ReActStep] = []
        step_start_time = time.time()

        # 步骤 1：思考
        thought = f"我需要为用户规划一个 {destination} 的 {days} 天旅行计划。用户偏好：{preference_text}"
        steps.append({
            "step": 1,
            "state": "thinking",
            "thought": thought,
            "action": None,
            "observation": None,
            "tool_input": None
        })
        
        if trace_ctx:
            TracingService.add_agent_step(
                trace_ctx, step_index=1, state="thinking",
                thought=thought, duration_ms=int((time.time() - step_start_time) * 1000)
            )

        # 步骤 2：调用 RAG 工具获取攻略
        step_start_time = time.time()
        tool_input = {"destination": destination, "top_k": 3}
        steps.append({
            "step": 2,
            "state": "acting",
            "thought": "",
            "action": "search_destination_guide",
            "observation": None,
            "tool_input": tool_input
        })
        
        if trace_ctx:
            TracingService.add_agent_step(
                trace_ctx, step_index=2, state="acting",
                action="search_destination_guide", tool_input=tool_input
            )

        observation = ""
        try:
            # 执行 RAG 工具
            rag_tool = RAGTool()
            observation = rag_tool.run(destination=destination, top_k=3)
            steps[1]["observation"] = observation
            steps[1]["state"] = "observing"
            logger.info(f"RAG 工具调用成功")
            
            # 记录到追踪
            if trace_ctx:
                TracingService.add_agent_step(
                    trace_ctx, step_index=2, state="observing",
                    observation=observation[:200] + "..." if len(observation) > 200 else observation,
                    duration_ms=int((time.time() - step_start_time) * 1000)
                )
        except Exception as e:
            error_msg = f"获取攻略失败: {str(e)}"
            steps[1]["observation"] = error_msg
            steps[1]["state"] = "error"
            logger.warning(f"RAG 工具调用失败: {e}")
            
            if trace_ctx:
                TracingService.add_agent_step(
                    trace_ctx, step_index=2, state="error",
                    observation=error_msg,
                    duration_ms=int((time.time() - step_start_time) * 1000)
                )

        # 步骤 3：完成
        step_start_time = time.time()
        steps.append({
            "step": 3,
            "state": "finished",
            "thought": "",
            "action": None,
            "observation": None,
            "tool_input": None
        })
        
        if trace_ctx:
            TracingService.add_agent_step(
                trace_ctx, step_index=3, state="finished",
                duration_ms=int((time.time() - step_start_time) * 1000)
            )

        # 使用原始的 planner 生成 PlannerDraft（不是完整的 Itinerary）
        if trip_request.days and trip_request.days > 0:
            day_count = trip_request.days
        else:
            day_count = (trip_request.end_date - trip_request.start_date).days + 1
            day_count = max(day_count, 1)

        rag_contexts = collect_trip_context(
            destination=trip_request.destination,
            preferences=trip_request.preferences,
            pace=trip_request.pace,
            special_notes=trip_request.special_notes,
        )
        
        # 记录 RAG 上下文到追踪
        if trace_ctx:
            for i, ctx in enumerate(rag_contexts):
                TracingService.add_rag_context(
                    trace_ctx, context=ctx[:200] + "..." if len(ctx) > 200 else ctx,
                    source=f"chunk_{i}", chunk_index=i
                )
        
        planner_draft = generate_planner_draft(trip_request, rag_contexts, day_count)

        return {
            "success": True,
            "planner_draft": planner_draft,
            "final_answer": f"已为你规划 {destination} 的 {day_count} 天旅行计划！",
            "steps": steps,
            "error": None,
            "tool_calls": 1
        }

    def add_tool(self, tool: BaseTool):
        self.tools[tool.name] = tool
        logger.info(f"添加工具: {tool.name}")

    def get_available_tools(self) -> List[Dict[str, str]]:
        return [
            {"name": name, "description": tool.description}
            for name, tool in self.tools.items()
        ]


# 全局单例
_react_agent: Optional[ReActAgent] = None


def get_react_agent(max_steps: int = 5) -> ReActAgent:
    global _react_agent
    if _react_agent is None:
        _react_agent = ReActAgent(max_steps=max_steps)
    return _react_agent
