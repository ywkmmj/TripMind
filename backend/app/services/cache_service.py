from __future__ import annotations

import json
import logging
import time
import sys
from typing import Any
from collections import OrderedDict

from app.config import (
    REDIS_DEFAULT_TTL_SECONDS,
    REDIS_ENABLED,
    REDIS_KEY_PREFIX,
    REDIS_URL,
    REDIS_CACHE_VERSION,
)

try:
    import redis
except ImportError:  # pragma: no cover - 依赖未安装时优雅降级
    redis = None


logger = logging.getLogger(__name__)
_redis_client: Any | None = None
_redis_unavailable_logged = False

# 内存缓存实现（LRU 策略 + 多层安全保护）
_memory_cache: OrderedDict = OrderedDict()  # (key: (value, expire_timestamp, size_bytes))
_MEMORY_CACHE_MAX_SIZE = 1000  # 最多 1000 条
_MEMORY_CACHE_TTL_SECONDS = 60  # 内存缓存 1 分钟
_MEMORY_CACHE_MAX_ITEM_SIZE = 10 * 1024 * 1024  # 单条最大 10MB
_MEMORY_CACHE_TOTAL_SIZE = 500 * 1024 * 1024  # 总内存最大 500MB
_memory_cache_current_size = 0  # 当前内存缓存总大小（字节）
_USE_MEMORY_CACHE_FALLBACK = True  # 即使 Redis 启用，也优先使用内存缓存


def _get_cache_size(value: Any) -> int:
    """估算缓存值的内存大小（字节）"""
    try:
        serialized = json.dumps(value, ensure_ascii=False)
        return sys.getsizeof(serialized)
    except Exception:
        # 如果序列化失败，返回默认值
        return 1024  # 默认 1KB


def _cleanup_expired_cache() -> int:
    """清理过期的缓存，释放内存，返回清理的条数"""
    now = int(time.time())
    expired_keys = []
    cleaned_size = 0
    
    # 先找出所有过期的 key
    for key, (value, expire_at, size) in _memory_cache.items():
        if now >= expire_at:
            expired_keys.append(key)
            cleaned_size += size
    
    # 删除过期的 key
    for key in expired_keys:
        del _memory_cache[key]
    
    global _memory_cache_current_size
    _memory_cache_current_size -= cleaned_size
    
    if expired_keys:
        logger.debug(f"清理过期缓存: {len(expired_keys)} 条, 释放 {cleaned_size / 1024 / 1024:.2f}MB")
    
    return len(expired_keys)


def _enforce_size_limits() -> None:
    """确保内存缓存不超过大小限制"""
    global _memory_cache_current_size
    
    # 先清理过期的缓存
    _cleanup_expired_cache()
    
    # 如果超过条数限制，删除最旧的
    while len(_memory_cache) > _MEMORY_CACHE_MAX_SIZE:
        oldest_key, (_, _, size) = _memory_cache.popitem(last=False)
        _memory_cache_current_size -= size
        logger.debug(f"LRU 淘汰缓存: {oldest_key}, 释放 {size / 1024:.2f}KB")
    
    # 如果超过总大小限制，持续删除直到满足
    while _memory_cache_current_size > _MEMORY_CACHE_TOTAL_SIZE and _memory_cache:
        oldest_key, (_, _, size) = _memory_cache.popitem(last=False)
        _memory_cache_current_size -= size
        logger.debug(f"内存超限淘汰: {oldest_key}, 释放 {size / 1024:.2f}KB, "
                    f"当前总大小: {_memory_cache_current_size / 1024 / 1024:.2f}MB")


def _build_key(key: str) -> str:
    """为缓存 key 添加统一前缀和版本号，避免不同项目/版本之间冲突。"""
    return f"{REDIS_KEY_PREFIX}:{REDIS_CACHE_VERSION}:{key}"


def _get_redis_client():
    """懒加载 Redis 客户端；不可用时返回 None。"""
    global _redis_client
    global _redis_unavailable_logged

    if not REDIS_ENABLED:
        return None
    if redis is None:
        if not _redis_unavailable_logged:
            logger.warning("Redis 已启用，但当前环境未安装 redis 依赖，缓存功能将被跳过。")
            _redis_unavailable_logged = True
        return None
    if _redis_client is not None:
        return _redis_client

    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:  # pragma: no cover - 连接问题时优雅降级
        if not _redis_unavailable_logged:
            logger.warning("Redis 连接失败，缓存功能将被跳过：%s", exc)
            _redis_unavailable_logged = True
        return None


def get_cached_json(key: str) -> Any | None:
    """读取 JSON 缓存；多级缓存策略：内存 -> Redis。"""
    now = int(time.time())
    
    # 先查内存缓存
    if _USE_MEMORY_CACHE_FALLBACK:
        if key in _memory_cache:
            value, expire_at, _ = _memory_cache[key]
            if now < expire_at:
                # 访问到了，移到末尾（LRU）
                _memory_cache.move_to_end(key)
                logger.debug("memory cache hit: %s", key)
                return value
            else:
                # 过期了，删除
                del _memory_cache[key]
    
    # 再查 Redis
    client = _get_redis_client()
    if client is None:
        return None

    try:
        raw_value = client.get(_build_key(key))
        if raw_value is None:
            return None
        value = json.loads(raw_value)
        
        # 写入内存缓存
        if _USE_MEMORY_CACHE_FALLBACK:
            _set_memory_cache(key, value)
        
        return value
    except Exception as exc:  # pragma: no cover - 缓存失败不影响主流程
        logger.debug("读取 Redis 缓存失败：%s", exc)
        return None


def _set_memory_cache(key: str, value: Any, expire_seconds: int = None) -> bool:
    """写入内存缓存，返回是否成功（失败是因为超过大小限制）"""
    # 先检查单条大小
    item_size = _get_cache_size(value)
    if item_size > _MEMORY_CACHE_MAX_ITEM_SIZE:
        logger.warning(f"缓存过大，跳过写入: {key}, 大小: {item_size / 1024 / 1024:.2f}MB, "
                      f"限制: {_MEMORY_CACHE_MAX_ITEM_SIZE / 1024 / 1024:.2f}MB")
        return False
    
    ttl = expire_seconds or _MEMORY_CACHE_TTL_SECONDS
    expire_at = int(time.time()) + ttl
    
    # 如果 key 已存在，先删除旧的
    if key in _memory_cache:
        _, _, old_size = _memory_cache.pop(key)
        global _memory_cache_current_size
        _memory_cache_current_size -= old_size
    
    # 写入新缓存
    _memory_cache[key] = (value, expire_at, item_size)
    _memory_cache_current_size += item_size
    
    # 强制检查大小限制
    _enforce_size_limits()
    
    logger.debug(f"写入内存缓存: {key}, 大小: {item_size / 1024:.2f}KB, "
                f"总大小: {_memory_cache_current_size / 1024 / 1024:.2f}MB, "
                f"条数: {len(_memory_cache)}")
    
    return True


def set_cached_json(
    key: str,
    value: Any,
    expire_seconds: int | None = None,
) -> None:
    """写入 JSON 缓存；多级缓存策略：先写内存，再写 Redis。"""
    # 先写内存缓存
    if _USE_MEMORY_CACHE_FALLBACK:
        _set_memory_cache(key, value, expire_seconds)
    
    # 再写 Redis
    client = _get_redis_client()
    if client is None:
        return

    ttl = expire_seconds or REDIS_DEFAULT_TTL_SECONDS
    try:
        client.set(_build_key(key), json.dumps(value, ensure_ascii=False), ex=ttl)
    except Exception as exc:  # pragma: no cover - 缓存失败不影响主流程
        logger.debug("写入 Redis 缓存失败：%s", exc)


def get_cache_stats() -> dict:
    """获取内存缓存统计信息（用于监控）"""
    _cleanup_expired_cache()  # 先清理过期的
    
    stats = {
        "total_items": len(_memory_cache),
        "total_size_mb": _memory_cache_current_size / 1024 / 1024,
        "max_items": _MEMORY_CACHE_MAX_SIZE,
        "max_size_mb": _MEMORY_CACHE_TOTAL_SIZE / 1024 / 1024,
        "usage_percent": (_memory_cache_current_size / _MEMORY_CACHE_TOTAL_SIZE) * 100,
        "items": []
    }
    
    # 添加前 10 个最大的缓存项
    items = list(_memory_cache.items())
    items.sort(key=lambda x: x[1][2], reverse=True)
    for key, (_, _, size) in items[:10]:
        stats["items"].append({
            "key": key,
            "size_kb": size / 1024
        })
    
    return stats

