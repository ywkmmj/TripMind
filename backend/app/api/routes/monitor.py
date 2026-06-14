from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from app.services.cache_service import get_cache_stats
from app.services.tracing_service import TracingService, TraceListResponse
from app.models.schemas import TraceRecord


class CacheItemStats(BaseModel):
    """单个缓存项统计。"""
    key: str = Field(..., description="缓存键")
    size_kb: float = Field(..., description="缓存大小（KB）")


class CacheStatsResponse(BaseModel):
    """缓存统计响应。"""
    total_items: int = Field(..., description="缓存总条数")
    total_size_mb: float = Field(..., description="缓存总大小（MB）")
    max_items: int = Field(..., description="最大缓存条数")
    max_size_mb: float = Field(..., description="最大缓存大小（MB）")
    usage_percent: float = Field(..., description="使用率（%）")
    items: list[CacheItemStats] = Field(default_factory=list, description="前10个最大的缓存项")


router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/cache", response_model=CacheStatsResponse)
def get_cache_stats_endpoint() -> CacheStatsResponse:
    """获取内存缓存统计信息。"""
    stats = get_cache_stats()
    return CacheStatsResponse(**stats)


@router.get("/traces", response_model=TraceListResponse)
def list_traces(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    request_type: str | None = Query(None, description="按请求类型过滤"),
    destination: str | None = Query(None, description="按目的地过滤"),
    success_only: bool = Query(False, description="仅显示成功的请求")
) -> TraceListResponse:
    """列出追踪记录，支持分页和过滤。"""
    return TracingService.list_traces(
        page=page,
        page_size=page_size,
        request_type=request_type,
        destination=destination,
        success_only=success_only
    )


@router.get("/traces/{trace_id}", response_model=TraceRecord)
def get_trace(trace_id: str) -> TraceRecord:
    """根据 trace_id 获取单个追踪记录。"""
    trace = TracingService.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"未找到 trace_id 为 {trace_id} 的追踪记录")
    return trace


@router.delete("/traces")
def clear_traces() -> dict[str, str]:
    """清空所有追踪记录。"""
    TracingService.clear_traces()
    return {"message": "所有追踪记录已清空"}
