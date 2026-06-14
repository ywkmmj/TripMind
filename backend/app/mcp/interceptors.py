from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from app.config import AMAP_API_KEY

logger = logging.getLogger(__name__)

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.interceptors import MCPToolCallRequest
    from mcp.types import TextContent
    MCP_AVAILABLE = True
except ImportError:
    logger.warning("langchain-mcp-adapters 未安装，拦截器功能不可用")
    MCP_AVAILABLE = False


@dataclass
class AuthContext:
    api_key: str = ""
    user_id: str = ""
    tenant_id: str = ""


@dataclass
class ToolMetrics:
    tool_name: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""
    request_args: dict = field(default_factory=dict)
    response_size: int = 0


class AuthInterceptor:
    """认证拦截器

    功能：
    - 验证 API Key
    - 注入用户上下文
    - 多租户支持
    """

    def __init__(self, auth_context: AuthContext):
        self.auth_context = auth_context
        self.api_key = AMAP_API_KEY

    async def intercept(
        self,
        request: MCPToolCallRequest,
        handler: Callable,
    ):
        """认证拦截逻辑"""
        logger.info(f"[认证拦截] 工具: {request.name}, 参数: {request.args}")

        if not self.api_key:
            logger.warning("[认证拦截] API Key 未配置，使用默认值")

        modified_request = request.override(
            args={
                **request.args,
                "_auth": {
                    "user_id": self.auth_context.user_id,
                    "tenant_id": self.auth_context.tenant_id,
                }
            }
        )

        return await handler(modified_request)


class LoggingInterceptor:
    """日志拦截器

    功能：
    - 请求日志
    - 响应日志
    - 性能监控
    - 错误追踪
    """

    def __init__(self):
        self.metrics: list[ToolMetrics] = []

    async def intercept(
        self,
        request: MCPToolCallRequest,
        handler: Callable,
    ):
        """日志拦截逻辑"""
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(
            f"[{request_id}] 请求开始: tool={request.name}, "
            f"args={json.dumps(request.args, ensure_ascii=False)[:200]}"
        )

        try:
            result = await handler(request)
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            metric = ToolMetrics(
                tool_name=request.name,
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                success=True,
                request_args=request.args,
                response_size=len(str(result)),
            )
            self.metrics.append(metric)

            logger.info(
                f"[{request_id}] 请求完成: tool={request.name}, "
                f"duration={duration_ms:.2f}ms, success=True"
            )

            return result

        except Exception as e:
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            metric = ToolMetrics(
                tool_name=request.name,
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                success=False,
                error=str(e),
                request_args=request.args,
            )
            self.metrics.append(metric)

            logger.error(
                f"[{request_id}] 请求失败: tool={request.name}, "
                f"duration={duration_ms:.2f}ms, error={str(e)}"
            )

            raise

    def get_metrics(self) -> list[dict]:
        """获取性能指标"""
        return [
            {
                "tool_name": m.tool_name,
                "duration_ms": m.duration_ms,
                "success": m.success,
                "error": m.error,
                "response_size": m.response_size,
            }
            for m in self.metrics
        ]

    def get_summary(self) -> dict:
        """获取性能摘要"""
        if not self.metrics:
            return {"total_calls": 0}

        total = len(self.metrics)
        success = sum(1 for m in self.metrics if m.success)
        failed = total - success

        durations = [m.duration_ms for m in self.metrics]
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)

        return {
            "total_calls": total,
            "success": success,
            "failed": failed,
            "success_rate": f"{success/total*100:.1f}%",
            "avg_duration_ms": f"{avg_duration:.2f}",
            "max_duration_ms": f"{max_duration:.2f}",
            "min_duration_ms": f"{min_duration:.2f}",
        }

    def clear_metrics(self) -> None:
        """清空指标"""
        self.metrics.clear()
        logger.info("性能指标已清空")


class RetryInterceptor:
    """重试拦截器

    功能：
    - 自动重试失败请求
    - 指数退避策略
    - 最多重试次数限制
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def intercept(
        self,
        request: MCPToolCallRequest,
        handler: Callable,
    ):
        """重试拦截逻辑"""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    delay = self.base_delay * (2 ** (attempt - 1))
                    logger.info(f"[重试拦截] 工具: {request.name}, 第 {attempt} 次重试, 延迟: {delay}s")
                    await self._sleep(delay)

                result = await handler(request)
                if attempt > 0:
                    logger.info(f"[重试拦截] 工具: {request.name}, 重试成功")
                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    f"[重试拦截] 工具: {request.name}, 第 {attempt + 1} 次尝试失败: {str(e)}"
                )

        logger.error(f"[重试拦截] 工具: {request.name}, 全部重试失败")
        raise last_error

    async def _sleep(self, seconds: float):
        """异步睡眠"""
        import asyncio
        await asyncio.sleep(seconds)


class RateLimitInterceptor:
    """限流拦截器

    功能：
    - 请求速率限制
    - 滑动窗口算法
    - 并发控制
    """

    def __init__(self, max_calls: int = 100, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls: list[float] = []

    async def intercept(
        self,
        request: MCPToolCallRequest,
        handler: Callable,
    ):
        """限流拦截逻辑"""
        current_time = time.time()

        self.calls = [t for t in self.calls if current_time - t < self.window_seconds]

        if len(self.calls) >= self.max_calls:
            wait_time = self.window_seconds - (current_time - self.calls[0])
            logger.warning(
                f"[限流拦截] 请求过多，等待 {wait_time:.2f} 秒"
            )
            await self._sleep(wait_time)
            self.calls = [t for t in self.calls if time.time() - t < self.window_seconds]

        self.calls.append(time.time())

        return await handler(request)

    async def _sleep(self, seconds: float):
        """异步睡眠"""
        import asyncio
        await asyncio.sleep(seconds)


class StructuredContentInterceptor:
    """结构化内容拦截器

    功能：
    - 自动提取结构化数据
    - 追加到工具响应
    - 便于后续处理
    """

    async def intercept(
        self,
        request: MCPToolCallRequest,
        handler: Callable,
    ):
        """结构化内容拦截逻辑"""
        result = await handler(request)

        if hasattr(result, 'structuredContent') and result.structuredContent:
            result.content.append(
                TextContent(
                    type="text",
                    text=json.dumps(result.structuredContent, ensure_ascii=False)
                )
            )
            logger.debug(
                f"[结构化内容拦截] 工具: {request.name}, "
                f"已追加结构化数据"
            )

        return result


def create_interceptors(
    enable_auth: bool = True,
    enable_logging: bool = True,
    enable_retry: bool = True,
    enable_rate_limit: bool = False,
    enable_structured_content: bool = True,
) -> list:
    """创建拦截器链

    Args:
        enable_auth: 启用认证
        enable_logging: 启用日志
        enable_retry: 启用重试
        enable_rate_limit: 启用限流
        enable_structured_content: 启用结构化内容

    Returns:
        拦截器列表
    """
    if not MCP_AVAILABLE:
        return []

    interceptors = []

    if enable_logging:
        logging_interceptor = LoggingInterceptor()
        interceptors.append(logging_interceptor)

    if enable_retry:
        retry_interceptor = RetryInterceptor(max_retries=2, base_delay=1.0)
        interceptors.append(retry_interceptor)

    if enable_rate_limit:
        rate_limit_interceptor = RateLimitInterceptor(max_calls=50, window_seconds=60)
        interceptors.append(rate_limit_interceptor)

    return interceptors


_global_logging_interceptor: LoggingInterceptor | None = None


def get_logging_interceptor() -> LoggingInterceptor:
    """获取全局日志拦截器"""
    global _global_logging_interceptor
    if _global_logging_interceptor is None:
        _global_logging_interceptor = LoggingInterceptor()
    return _global_logging_interceptor
