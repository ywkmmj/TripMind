"""
外部服务调用增强模块 - 提供超时、重试、降级和错误码包装
"""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Type, Union
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """错误码枚举"""
    SUCCESS = 0
    TIMEOUT = 1001
    NETWORK_ERROR = 1002
    RATE_LIMITED = 1003
    INVALID_RESPONSE = 1004
    SERVICE_UNAVAILABLE = 1005
    UNKNOWN_ERROR = 9999


class ServiceError(Exception):
    """服务错误基类"""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        original_error: Optional[Exception] = None,
        retryable: bool = True,
    ):
        self.message = message
        self.error_code = error_code
        self.original_error = original_error
        self.retryable = retryable
        super().__init__(message)


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[tuple[Type[Exception], ...] = (Exception,),
    on_failure: Optional[Callable[[Exception, int], None] = None,
):
    """
    重试装饰器
    
    Args:
        max_attempts: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 延迟倍数（指数退避
        max_delay: 最大延迟
        retryable_exceptions: 可重试的异常类型
        on_failure: 失败回调函数 (exception, attempt_count)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt}/{max_attempts} 次执行失败: {e}"
                    )

                    if on_failure and callable(on_failure):
                        on_failure(e, attempt)

                    if attempt < max_attempts:
                        sleep_time = min(current_delay, max_delay)
                        logger.info(f"等待 {sleep_time:.1f} 秒后重试...")
                        time.sleep(sleep_time)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"函数 {func.__name__} 已达最大重试次数 {max_attempts}，放弃重试失败"
                        )

            raise ServiceError(
                f"函数执行失败，已重试 {max_attempts} 次",
                error_code=ErrorCode.NETWORK_ERROR,
                original_error=last_exception,
            )

        return wrapper
    return decorator


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    fallback_function: Optional[Callable] = None,
):
    """
    熔断器装饰器 - 实现熔断模式，避免级联故障保护
    
    Args:
        failure_threshold: 连续失败次数阈值
        recovery_timeout: 恢复等待时间（秒）
        fallback_function: 熔断时的降级函数
    """
    def decorator(func: Callable) -> Callable:
        failure_count = 0
        last_failure_time = 0.0
        circuit_open = False

        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal failure_count, last_failure_time, circuit_open

            now = time.time()

            # 检查熔断器状态
            if circuit_open:
                if now - last_failure_time >= recovery_timeout:
                    # 进入半开状态，尝试一次
                    circuit_open = False
                    logger.info("熔断器进入半开状态，尝试恢复...")
                else:
                    logger.warning(f"熔断器处于打开状态，直接降级")
                    if fallback_function and callable(fallback_function):
                        return fallback_function(*args, **kwargs)
                    raise ServiceError(
                        "服务不可用，熔断器已打开",
                        error_code=ErrorCode.SERVICE_UNAVAILABLE,
                        retryable=False,
                    )

            try:
                result = func(*args, **kwargs)
                # 成功，重置计数器
                failure_count = 0
                return result
            except Exception as e:
                failure_count += 1
                last_failure_time = now
                logger.error(
                    f"函数 {func.__name__} 执行失败，失败次数: {failure_count}/{failure_threshold}"
                )

                if failure_count >= failure_threshold:
                    circuit_open = True
                    logger.critical(f"连续失败次数达到阈值，熔断器已打开！")

                if fallback_function and callable(fallback_function):
                    return fallback_function(*args, **kwargs)
                raise

        return wrapper
    return decorator


def timeout(seconds: float):
    """
    超时装饰器（使用信号量实现超时，Windows 兼容性处理）
    
    Args:
        seconds: 超时时间（秒）
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except concurrent.futures.TimeoutError:
                    logger.error(f"函数 {func.__name__} 执行超时 ({seconds}秒")
                    raise ServiceError(
                        f"请求超时",
                        error_code=ErrorCode.TIMEOUT,
                        retryable=True,
                    )
        return wrapper
    return decorator


class ServiceResponse:
    """服务响应包装类"""
    def __init__(
        self,
        success: bool,
        data: Any = None,
        error_code: ErrorCode = ErrorCode.SUCCESS,
        error_message: str = "",
        duration_ms: float = 0.0,
        from_cache: bool = False,
    ):
        self.success = success
        self.data = data
        self.error_code = error_code
        self.error_message = error_message
        self.duration_ms = duration_ms
        self.from_cache = from_cache

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error_code": self.error_code.value if isinstance(self.error_code, ErrorCode) else self.error_code,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "from_cache": self.from_cache,
        }


def wrap_service_call(
    func: Callable,
    *args,
    timeout_seconds: Optional[float] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    fallback: Optional[Callable] = None,
    **kwargs,
) -> ServiceResponse:
    """
    包装服务调用，统一处理超时、重试、降级
    
    Args:
        func: 要调用的函数
        timeout_seconds: 超时时间（秒）
        max_retries: 最大重试次数
        retry_delay: 重试延迟
        fallback: 降级函数
        *args, **kwargs: 传递给函数的参数
    
    Returns:
        ServiceResponse 包装对象
    """
    start_time = time.time()
    
    try:
        # 应用超时装饰器（如果有指定）
        if timeout_seconds is not None:
            @timeout(timeout_seconds)
            def wrapped_func():
                return func(*args, **kwargs)
            result = wrapped_func()
        else:
            result = func(*args, **kwargs)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.debug(f"服务调用成功，耗时: {duration_ms:.2f}ms")
        
        return ServiceResponse(
            success=True,
            data=result,
            duration_ms=duration_ms,
        )
        
    except ServiceError as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"服务调用失败: {e}, 耗时: {duration_ms:.2f}ms")
        
        if fallback:
            logger.info("使用降级函数...")
            fallback_result = fallback(*args, **kwargs)
            return ServiceResponse(
                success=True,
                data=fallback_result,
                error_code=e.error_code,
                error_message=str(e),
                duration_ms=duration_ms,
                from_cache=False,
            )
        
        return ServiceResponse(
            success=False,
            error_code=e.error_code,
            error_message=str(e),
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"服务调用异常: {e}, 耗时: {duration_ms:.2f}ms")
        
        if fallback:
            logger.info("使用降级函数...")
            fallback_result = fallback(*args, **kwargs)
            return ServiceResponse(
                success=True,
                data=fallback_result,
                error_code=ErrorCode.UNKNOWN_ERROR,
                error_message=str(e),
                duration_ms=duration_ms,
                from_cache=False,
            )
        
        return ServiceResponse(
            success=False,
            error_code=ErrorCode.UNKNOWN_ERROR,
            error_message=str(e),
            duration_ms=duration_ms,
        )

