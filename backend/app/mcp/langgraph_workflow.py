from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TypedDict

from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import create_react_agent
    from langchain_openai import ChatOpenAI
    LANGGRAPH_AVAILABLE = True
except ImportError:
    logger.warning("langgraph 未安装，工作流集成功能不可用")
    LANGGRAPH_AVAILABLE = False


class TripWorkflowState(TypedDict):
    destination: str
    days: int
    preferences: str | None
    weather_info: dict[str, Any]
    map_info: dict[str, Any]
    itinerary: dict[str, Any]
    final_plan: str
    error: str | None
    steps: list[str]


class TripWorkflow:
    """基于 LangGraph 的旅行规划工作流

    所有工具调用均通过 MCP Client 协议完成，不再直接导入服务端模块。
    支持通过环境变量 ``MCP_TRANSPORT`` 切换传输模式。
    """

    def __init__(self):
        self.workflow = None
        self.app = None
        self._initialized = False

    def _build_llm(self):
        """构建 LLM 实例"""
        if not LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY 未配置")

        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            temperature=0.7,
            max_retries=LLM_MAX_RETRIES,
            timeout=LLM_TIMEOUT_SECONDS,
        )

    async def _call_mcp_tool(self, tool_name: str, **kwargs) -> Any:
        """统一通过 MCP Client 调用工具（核心改造点）

        替代旧方式：
            from app.mcp.weather_server import get_weather_forecast
            weather = get_weather_forecast(city=...)

        新方式：
            weather = await self._call_mcp_tool("get_weather_forecast", city=...)
        """
        from app.mcp.client import get_mcp_client

        client = get_mcp_client()
        return await client.call_tool(tool_name, **kwargs)

    def _weather_node(self, state: TripWorkflowState) -> TripWorkflowState:
        """天气查询节点 - 通过 MCP Client 调用"""
        logger.info("执行天气查询节点（MCP Client 模式）...")

        try:
            import asyncio

            weather = asyncio.get_event_loop().run_until_complete(
                self._call_mcp_tool("get_weather_forecast", city=state["destination"])
            )
            state["weather_info"] = weather
            state["steps"].append(f"天气查询完成: {weather.get('city', '未知')}")
            logger.info(f"天气信息: {weather}")
        except Exception as e:
            state["error"] = f"天气查询失败: {str(e)}"
            state["steps"].append(f"天气查询失败: {str(e)}")
            logger.error(f"天气查询失败: {e}")

        return state

    def _map_node(self, state: TripWorkflowState) -> TripWorkflowState:
        """地图查询节点 - 通过 MCP Client 调用"""
        logger.info("执行地图查询节点（MCP Client 模式）...")

        try:
            import asyncio

            places = asyncio.get_event_loop().run_until_complete(
                self._call_mcp_tool(
                    "search_places",
                    keyword=state["destination"],
                    city=state["destination"],
                    page_size=10,
                )
            )

            geocode = asyncio.get_event_loop().run_until_complete(
                self._call_mcp_tool(
                    "geocode_address",
                    address=state["destination"],
                )
            )

            state["map_info"] = {
                "places": places,
                "location": geocode,
            }
            state["steps"].append(f"地图查询完成: {places.get('count', 0)} 个 POI")
            logger.info(f"地图信息: {places.get('count', 0)} 个 POI")
        except Exception as e:
            state["error"] = f"地图查询失败: {str(e)}"
            state["steps"].append(f"地图查询失败: {str(e)}")
            logger.error(f"地图查询失败: {e}")

        return state

    def _planner_node(self, state: TripWorkflowState) -> TripWorkflowState:
        """行程规划节点"""
        logger.info("执行行程规划节点...")

        try:
            llm = self._build_llm()

            weather_summary = self._summarize_weather(state["weather_info"])
            map_summary = self._summarize_map(state["map_info"])

            prompt = f"""你是一名专业的旅行规划师。请根据以下信息规划一次{state['days']}天的{state['destination']}旅行。

天气信息:
{weather_summary}

地点信息:
{map_summary}

用户偏好:
{state['preferences'] or '无特别要求'}

请生成一份详细的旅行计划，包括：
1. 每日行程安排
2. 推荐景点和活动
3. 交通建议
4. 餐饮推荐
5. 住宿建议
6. 注意事项

请用中文回答。"""

            response = llm.invoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, 'content') else str(response)

            state["final_plan"] = content
            state["steps"].append("行程规划完成")
            logger.info("行程规划完成")
        except Exception as e:
            state["error"] = f"行程规划失败: {str(e)}"
            state["steps"].append(f"行程规划失败: {str(e)}")
            logger.error(f"行程规划失败: {e}")

        return state

    def _should_continue(self, state: TripWorkflowState) -> str:
        """条件路由：根据状态决定下一步"""
        if state.get("error"):
            return "error"
        if not state.get("final_plan"):
            return "planner"
        return "end"

    def _summarize_weather(self, weather_info: dict) -> str:
        """生成天气摘要"""
        if not weather_info or "error" in weather_info:
            return "天气信息获取失败"

        days = weather_info.get("days", [])
        if not days:
            return "暂无天气预报"

        summary = []
        for day in days[:3]:
            summary.append(
                f"- {day.get('date', '')} ({day.get('week', '')}): "
                f"白天{day.get('day_weather', '')}, {day.get('day_temp', '')}°C"
            )

        return "\n".join(summary) if summary else "暂无天气预报"

    def _summarize_map(self, map_info: dict) -> str:
        """生成地图摘要"""
        if not map_info or "error" in map_info:
            return "地图信息获取失败"

        location = map_info.get("location", {})
        places = map_info.get("places", {}).get("pois", [])

        summary = [f"位置: {location.get('formatted_address', '未知')}"]

        if places:
            summary.append(f"\n推荐地点 (共{len(places)}个):")
            for i, place in enumerate(places[:5], 1):
                summary.append(
                    f"{i}. {place.get('name', '')} - "
                    f"{place.get('address', '地址未知')}"
                )

        return "\n".join(summary)

    def build_workflow(self) -> None:
        """构建工作流图"""
        if not LANGGRAPH_AVAILABLE:
            raise RuntimeError("langgraph 未安装，无法构建工作流")

        workflow = StateGraph(TripWorkflowState)

        workflow.add_node("weather", self._weather_node)
        workflow.add_node("map", self._map_node)
        workflow.add_node("planner", self._planner_node)

        workflow.set_entry_point("weather")

        workflow.add_edge("weather", "map")
        workflow.add_edge("map", "planner")
        workflow.add_edge("planner", END)

        workflow.add_conditional_edges(
            "weather",
            self._should_continue,
            {
                "error": END,
                "planner": "map",
                "end": END,
            },
        )

        self.workflow = workflow.compile()
        self._initialized = True
        logger.info("TripWorkflow 工作流构建完成（MCP Client 模式）")

    async def run(self, destination: str, days: int, preferences: str | None = None) -> dict[str, Any]:
        """运行工作流

        Args:
            destination: 目的地
            days: 天数
            preferences: 用户偏好

        Returns:
            工作流执行结果
        """
        # 启动前确保 MCP Client 已初始化
        from app.mcp.client import get_mcp_client

        mcp_client = get_mcp_client()
        if not mcp_client.is_initialized:
            await mcp_client.initialize()

        if not self._initialized:
            self.build_workflow()

        initial_state: TripWorkflowState = {
            "destination": destination,
            "days": days,
            "preferences": preferences,
            "weather_info": {},
            "map_info": {},
            "itinerary": {},
            "final_plan": "",
            "error": None,
            "steps": [],
        }

        logger.info(f"开始执行工作流: {destination}, {days}天 [transport={mcp_client.transport}]")

        result = await self.app.ainvoke(initial_state)

        logger.info(f"工作流执行完成，步骤: {result.get('steps', [])}")

        return {
            "destination": result["destination"],
            "days": result["days"],
            "weather": result["weather_info"],
            "map": result["map_info"],
            "plan": result["final_plan"],
            "steps": result["steps"],
            "error": result.get("error"),
        }

    def get_workflow_graph(self) -> Any:
        """获取工作流图结构"""
        if not self._initialized:
            self.build_workflow()
        return self.workflow


_workflow: TripWorkflow | None = None


def get_trip_workflow() -> TripWorkflow:
    """获取全局 TripWorkflow 实例"""
    global _workflow
    if _workflow is None:
        _workflow = TripWorkflow()
    return _workflow
