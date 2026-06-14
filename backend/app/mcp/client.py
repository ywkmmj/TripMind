from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    MCP_SDK_AVAILABLE = True
except ImportError:
    logger.warning("langchain-mcp-adapters 未安装，MCP 客户端功能不可用")
    MCP_SDK_AVAILABLE = False


BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# ── 传输模式配置 ──────────────────────────────────────────────
# "stdio"       : 子进程内嵌模式（默认，适合开发/单进程部署）
# "streamable-http": 远程 HTTP 模式（适合 MCP Server 独立进程部署）
MCP_TRANSPORT: Literal["stdio", "streamable-http"] = os.getenv(
    "MCP_TRANSPORT", "stdio"
)

# HTTP 模式下各服务的远程地址（仅 streamable-http 模式生效）
MCP_AMAP_URL = os.getenv("MCP_AMAP_URL", "http://localhost:8001/mcp")
MCP_WEATHER_URL = os.getenv("MCP_WEATHER_URL", "http://localhost:8002/mcp")


class MCPToolClient:
    """真正的 MCP Client 封装

    通过 MCP 协议与 Server 通信，支持两种传输模式：
    - **stdio**（默认）：以子进程方式启动 MCP Server，适合同进程部署
    - **streamable-http**：通过 HTTP 连接远程 MCP Server，适合独立进程部署

    切换方式：仅需修改环境变量 ``MCP_TRANSPORT=streamable-http`` 并启动对应的 HTTP Server，
    Agent 侧代码无需任何改动。
    """

    def __init__(self):
        self._client: MultiServerMCPClient | None = None
        self._tools: list[Any] = []
        self._initialized: bool = False

    # ── 服务器配置 ─────────────────────────────────────────────

    def _get_server_config(self) -> dict[str, Any]:
        """根据传输模式返回对应的服务器配置"""
        if MCP_TRANSPORT == "streamable-http":
            return {
                "amap": {
                    "transport": "streamable-http",
                    "url": MCP_AMAP_URL,
                },
                "weather": {
                    "transport": "streamable-http",
                    "url": MCP_WEATHER_URL,
                },
            }

        # 默认 stdio 模式：子进程启动 Python 脚本
        return {
            "amap": {
                "transport": "stdio",
                "command": "python",
                "args": [str(BACKEND_DIR / "app" / "mcp" / "amap_server.py")],
            },
            "weather": {
                "transport": "stdio",
                "command": "python",
                "args": [str(BACKEND_DIR / "app" / "mcp" / "weather_server.py")],
            },
        }

    # ── 生命周期管理 ───────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化 MCP Client，建立与所有 Server 的连接"""
        if not MCP_SDK_AVAILABLE:
            raise RuntimeError(
                "langchain-mcp-adapters 未安装，请先安装：pip install langchain-mcp-adapters"
            )

        if self._initialized:
            return

        logger.info(
            "初始化 MCP Client [transport=%s] ...", MCP_TRANSPORT
        )
        self._client = MultiServerMCPClient(self._get_server_config())
        self._tools = await self._client.get_tools()
        self._initialized = True
        logger.info(
            "MCP Client 初始化完成 [%s]，共加载 %d 个工具",
            MCP_TRANSPORT,
            len(self._tools),
        )

    async def close(self) -> None:
        """关闭 MCP Client，释放所有连接"""
        if self._client:
            await self._client.aclose()
            self._initialized = False
            logger.info("MCP Client 已关闭")

    # ── 工具操作 ───────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        """获取所有可用的 MCP 工具（LangChain Tool 格式）"""
        if not self._initialized:
            await self.initialize()
        return self._tools

    async def list_tools(self) -> list[dict[str, str]]:
        """列出所有可用工具的名称和描述"""
        if not self._initialized:
            await self.initialize()
        return [
            {"name": t.name, "description": t.description or ""}
            for t in self._tools
        ]

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """通过 MCP 协议调用指定工具

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在
        """
        if not self._initialized:
            await self.initialize()

        for tool in self._tools:
            if tool.name == tool_name:
                logger.info("MCP 调用工具: %s, 参数: %s", tool_name, kwargs)
                result = await tool.ainvoke(kwargs)
                logger.info("MCP 工具 %s 执行完成", tool_name)
                return result

        raise ValueError(f"未找到 MCP 工具: {tool_name}")

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    @property
    def transport(self) -> str:
        """当前使用的传输模式"""
        return MCP_TRANSPORT


# ── 全局单例 ───────────────────────────────────────────────────
_mcp_client_instance: MCPToolClient | None = None


def get_mcp_client() -> MCPToolClient:
    """获取全局 MCP Client 实例（单例模式）"""
    global _mcp_client_instance
    if _mcp_client_instance is None:
        _mcp_client_instance = MCPToolClient()
    return _mcp_client_instance


# ── 便捷函数（保持向后兼容）────────────────────────────────────

def get_amap_tools() -> list[str]:
    """高德地图工具名列表"""
    return [
        "geocode_address",
        "search_places",
        "estimate_route",
        "get_place_detail",
        "batch_geocode",
    ]


def get_weather_tools() -> list[str]:
    """天气工具名列表"""
    return [
        "get_weather_forecast",
        "get_current_weather",
        "get_weather_alert",
        "get_weather_suggestion",
    ]


async def call_amap_tool(tool_name: str, **kwargs) -> Any:
    """便捷函数：调用高德地图 MCP 工具"""
    if tool_name not in get_amap_tools():
        raise ValueError(f"无效的高德地图工具: {tool_name}")
    client = get_mcp_client()
    return await client.call_tool(tool_name, **kwargs)


async def call_weather_tool(tool_name: str, **kwargs) -> Any:
    """便捷函数：调用天气 MCP 工具"""
    if tool_name not in get_weather_tools():
        raise ValueError(f"无效的天气工具: {tool_name}")
    client = get_mcp_client()
    return await client.call_tool(tool_name, **kwargs)


async def call_any_tool(tool_name: str, **kwargs) -> Any:
    """便捷函数：调用任意 MCP 工具"""
    client = get_mcp_client()
    return await client.call_tool(tool_name, **kwargs)
