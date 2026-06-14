from __future__ import annotations

import logging
from typing import Any, Callable

from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

try:
    from langchain.tools import tool
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import StructuredTool
    LANGCHAIN_AVAILABLE = True
except ImportError as e:
    logger.warning(f"LangChain Agent 导入失败: {str(e)}")
    LANGCHAIN_AVAILABLE = False


class AgentConfig(TypedDict):
    model: str
    temperature: float
    max_tokens: int | None
    tools: list[Any]


class TripPlannerAgent:
    """基于 LangChain 的旅行规划 Agent

    通过 MCP Client 协议加载工具（地图、天气），不再直接依赖服务端模块。
    切换 MCP Server 部署模式（stdio / streamable-http）时无需修改本文件。
    """

    def __init__(self):
        self.agent = None
        self._initialized = False
        self._tools: list[Any] = []
        self._mcp_client = None

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

    async def _load_tools(self) -> list[Any]:
        """通过 MCP Client 加载工具（核心改造点）

        旧方式：直接 ``from app.mcp.amap_server import geocode_address``
        新方式：通过 MCP Client 协议获取工具列表，实现真正的 C/S 解耦
        """
        from app.mcp.client import get_mcp_client

        mcp_client = get_mcp_client()
        await mcp_client.initialize()

        tools = await mcp_client.get_tools()

        logger.info(
            "通过 MCP Client [%s] 加载工具完成，共 %d 个",
            mcp_client.transport,
            len(tools),
        )
        for t in tools:
            logger.info("  - %s: %s", t.name, (t.description or "")[:50])

        return tools

    async def initialize(self) -> None:
        """初始化 Agent

        通过 MCP Client 加载 MCP 工具并创建 Agent
        """
        if not LANGCHAIN_AVAILABLE:
            raise RuntimeError("langchain 未安装，请先安装相关依赖")

        if self._initialized:
            return

        logger.info("初始化 TripPlannerAgent（MCP Client 模式）...")

        self._tools = await self._load_tools()
        logger.info(f"MCP 工具加载完成，共 {len(self._tools)} 个工具")

        llm = self._build_llm()
        logger.info(f"LLM 配置: model={LLM_MODEL}")

        self.agent = create_agent(llm, self._tools)

        self._initialized = True
        logger.info("TripPlannerAgent 初始化完成")

    async def chat(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        """与 Agent 对话

        Args:
            message: 用户消息
            session_id: 会话 ID（用于追踪）

        Returns:
            Agent 响应结果
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"[Session: {session_id}] 用户消息: {message}")

        result = await self.agent.ainvoke(
            {"messages": [HumanMessage(content=message)]}
        )

        logger.info(f"[Session: {session_id}] Agent 响应完成")

        return {
            "session_id": session_id,
            "message": message,
            "response": result,
            "tool_count": len(self._tools),
        }

    async def plan_trip(
        self,
        destination: str,
        days: int,
        preferences: str | None = None,
    ) -> dict[str, Any]:
        """规划旅行

        Args:
            destination: 目的地
            days: 天数
            preferences: 用户偏好

        Returns:
            旅行规划结果
        """
        prompt = f"""请帮我规划一次{days}天的{destination}旅行。

偏好要求: {preferences or '无特别要求'}

请考虑以下因素：
1. 当地天气情况
2. 主要景点和活动
3. 交通路线安排
4. 餐饮推荐
5. 住宿建议

请提供详细的旅行计划。"""

        return await self.chat(prompt, session_id=f"trip_{destination}")

    async def get_destination_info(
        self,
        destination: str,
        info_type: str = "all",
    ) -> dict[str, Any]:
        """获取目的地信息

        Args:
            destination: 目的地
            info_type: 信息类型（weather/map/all）

        Returns:
            目的地相关信息
        """
        prompts = {
            "weather": f"请查询{destination}的天气预报",
            "map": f"请查询{destination}的主要景点和位置信息",
            "all": f"请帮我查询{destination}的天气、主要景点、交通路线等信息",
        }

        prompt = prompts.get(info_type, prompts["all"])
        return await self.chat(prompt, session_id=f"info_{destination}")

    def get_available_tools(self) -> list[dict[str, str]]:
        """获取可用的 MCP 工具列表"""
        if not self._initialized:
            return []

        result = []
        for tool_item in self._tools:
            result.append({
                "name": getattr(tool_item, 'name', str(tool_item)),
                "description": getattr(tool_item, 'description', 'No description'),
            })
        return result

    async def close(self) -> None:
        """关闭 Agent 及其 MCP Client 连接"""
        from app.mcp.client import get_mcp_client

        self._initialized = False

        mcp_client = get_mcp_client()
        if mcp_client.is_initialized:
            await mcp_client.close()

        logger.info("TripPlannerAgent 已关闭")


_agent: TripPlannerAgent | None = None


def get_trip_planner_agent() -> TripPlannerAgent:
    """获取全局 TripPlannerAgent 实例（单例模式）"""
    global _agent
    if _agent is None:
        _agent = TripPlannerAgent()
    return _agent
