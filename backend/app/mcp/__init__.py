from __future__ import annotations

"""
MCP 模块 - 智旅云图 MCP 服务封装

提供地图、天气等外部服务的 MCP 工具封装，便于 LangChain Agent 调用
"""

from app.mcp.amap_server import mcp as amap_mcp
from app.mcp.weather_server import mcp as weather_mcp

from app.mcp.amap_server import (
    geocode_address,
    search_places,
    estimate_route,
    get_place_detail,
    batch_geocode,
)

from app.mcp.weather_server import (
    get_weather_forecast,
    get_current_weather,
    get_weather_alert,
    get_weather_suggestion,
)

from app.mcp.client import (
    MCPToolClient,
    get_mcp_client,
    call_amap_tool,
    call_weather_tool,
    call_any_tool,
    MCP_TRANSPORT,
    MCP_AMAP_URL,
    MCP_WEATHER_URL,
)

try:
    from app.mcp.langchain_agent import (
        TripPlannerAgent,
        get_trip_planner_agent,
    )
    LANGCHAIN_AGENT_AVAILABLE = True
except ImportError:
    LANGCHAIN_AGENT_AVAILABLE = False

try:
    from app.mcp.langgraph_workflow import (
        TripWorkflow,
        TripWorkflowState,
        get_trip_workflow,
    )
    LANGGRAPH_WORKFLOW_AVAILABLE = True
except ImportError:
    LANGGRAPH_WORKFLOW_AVAILABLE = False

from app.mcp.interceptors import (
    AuthInterceptor,
    AuthContext,
    LoggingInterceptor,
    RetryInterceptor,
    RateLimitInterceptor,
    StructuredContentInterceptor,
    create_interceptors,
    get_logging_interceptor,
)

__all__ = [
    "amap_mcp",
    "weather_mcp",
    "geocode_address",
    "search_places",
    "estimate_route",
    "get_place_detail",
    "batch_geocode",
    "get_weather_forecast",
    "get_current_weather",
    "get_weather_alert",
    "get_weather_suggestion",
    "MCPToolClient",
    "get_mcp_client",
    "call_amap_tool",
    "call_weather_tool",
    "call_any_tool",
    "MCP_TRANSPORT",
    "MCP_AMAP_URL",
    "MCP_WEATHER_URL",
    "AuthInterceptor",
    "AuthContext",
    "LoggingInterceptor",
    "RetryInterceptor",
    "RateLimitInterceptor",
    "StructuredContentInterceptor",
    "create_interceptors",
    "get_logging_interceptor",
]

if LANGCHAIN_AGENT_AVAILABLE:
    __all__.extend([
        "TripPlannerAgent",
        "get_trip_planner_agent",
    ])

if LANGGRAPH_WORKFLOW_AVAILABLE:
    __all__.extend([
        "TripWorkflow",
        "TripWorkflowState",
        "get_trip_workflow",
    ])
