from __future__ import annotations

import json
import uuid
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.models.schemas import (
    TraceRecord,
    LLMCallRecord,
    RAGContextItem,
    AgentStepRecord,
    TraceListResponse,
)

logger = logging.getLogger(__name__)


@dataclass
class TraceContext:
    """追踪上下文，用于在请求处理过程中记录信息。"""
    trace_id: str
    start_time: float = field(default_factory=time.time)
    trace_record: TraceRecord = field(init=False)
    llm_calls: List[LLMCallRecord] = field(default_factory=list)
    agent_steps: List[AgentStepRecord] = field(default_factory=list)
    rag_contexts: List[RAGContextItem] = field(default_factory=list)
    
    def __post_init__(self):
        self.trace_record = TraceRecord(
            trace_id=self.trace_id,
            request_type="unknown",
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return self.trace_record.model_dump()


# 全局追踪存储（生产环境应该用数据库）
_trace_storage: List[TraceRecord] = []
_max_storage_size = 100  # 最多保留100条记录


class TracingService:
    """可观测性追踪服务。"""
    
    @staticmethod
    def create_trace(request_type: str, user_request: Optional[Dict[str, Any]] = None, 
                    destination: Optional[str] = None) -> TraceContext:
        """创建一个新的追踪上下文。"""
        trace_id = str(uuid.uuid4())
        ctx = TraceContext(trace_id=trace_id)
        ctx.trace_record.request_type = request_type
        ctx.trace_record.user_request = user_request
        ctx.trace_record.destination = destination
        logger.info(f"[Tracing] Created trace: {trace_id} for {request_type}")
        return ctx
    
    @staticmethod
    def add_rag_context(ctx: TraceContext, context: str, 
                       score: Optional[float] = None,
                       source: Optional[str] = None,
                       chunk_index: Optional[int] = None):
        """添加RAG检索上下文。"""
        ctx.rag_contexts.append(RAGContextItem(
            content=context,
            score=score,
            source=source,
            chunk_index=chunk_index,
        ))
        ctx.trace_record.rag_contexts = ctx.rag_contexts
    
    @staticmethod
    @contextmanager
    def record_rag_call(ctx: TraceContext):
        """记录RAG调用的上下文管理器。"""
        start_time = time.time()
        try:
            yield
        finally:
            duration = int((time.time() - start_time) * 1000)
            ctx.trace_record.rag_duration_ms = duration
    
    @staticmethod
    def record_llm_call(ctx: TraceContext, model: str, prompt: str, response: str,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       tokens_used: Optional[int] = None,
                       duration_ms: Optional[int] = None,
                       success: bool = True,
                       error_message: Optional[str] = None):
        """记录LLM调用。"""
        llm_call = LLMCallRecord(
            model=model,
            prompt=prompt,
            response=response,
            temperature=temperature,
            max_tokens=max_tokens,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        )
        ctx.llm_calls.append(llm_call)
        ctx.trace_record.llm_calls = ctx.llm_calls
        
        # 更新token和成本统计
        if tokens_used:
            current_tokens = ctx.trace_record.total_tokens_used or 0
            ctx.trace_record.total_tokens_used = current_tokens + tokens_used
            
        # 简单成本估算（示例）
        if tokens_used:
            cost_per_1k = 0.01  # 假设1k token $0.01
            current_cost = ctx.trace_record.total_cost or 0
            ctx.trace_record.total_cost = current_cost + (tokens_used / 1000 * cost_per_1k)
    
    @staticmethod
    @contextmanager
    def llm_call_context(ctx: TraceContext, model: str, 
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None):
        """LLM调用的上下文管理器，自动记录耗时。"""
        start_time = time.time()
        prompt = ""
        response = ""
        
        class LLMContext:
            prompt = ""
            response = ""
            error_message: Optional[str] = None
            tokens_used: Optional[int] = None
        
        llm_ctx = LLMContext()
        
        try:
            yield llm_ctx
            duration = int((time.time() - start_time) * 1000)
            TracingService.record_llm_call(
                ctx, model, llm_ctx.prompt, llm_ctx.response,
                temperature, max_tokens, llm_ctx.tokens_used,
                duration, success=True
            )
        except Exception as e:
            duration = int((time.time() - start_time) * 1000)
            TracingService.record_llm_call(
                ctx, model, llm_ctx.prompt, llm_ctx.response,
                temperature, max_tokens, llm_ctx.tokens_used,
                duration, success=False, error_message=str(e)
            )
            raise
    
    @staticmethod
    def add_agent_step(ctx: TraceContext, step_index: int, state: str,
                      thought: Optional[str] = None,
                      action: Optional[str] = None,
                      tool_input: Optional[Dict] = None,
                      observation: Optional[str] = None,
                      duration_ms: Optional[int] = None):
        """添加Agent执行步骤。"""
        step = AgentStepRecord(
            step_index=step_index,
            state=state,
            thought=thought,
            action=action,
            tool_input=tool_input,
            observation=observation,
            duration_ms=duration_ms,
        )
        ctx.agent_steps.append(step)
        ctx.trace_record.agent_steps = ctx.agent_steps
    
    @staticmethod
    def set_agent_type(ctx: TraceContext, agent_type: str):
        """设置使用的Agent类型。"""
        ctx.trace_record.agent_type = agent_type
    
    @staticmethod
    def set_cache_hit(ctx: TraceContext, cache_hit: bool):
        """设置缓存命中状态。"""
        ctx.trace_record.cache_hit = cache_hit
    
    @staticmethod
    def finish_trace(ctx: TraceContext, success: bool = True,
                    final_output: Optional[Dict] = None,
                    error_message: Optional[str] = None):
        """完成追踪，保存记录。"""
        total_duration = int((time.time() - ctx.start_time) * 1000)
        ctx.trace_record.total_duration_ms = total_duration
        ctx.trace_record.success = success
        ctx.trace_record.final_output = final_output
        ctx.trace_record.error_message = error_message
        
        # 保存记录
        _trace_storage.append(ctx.trace_record)
        
        # 限制存储大小
        if len(_trace_storage) > _max_storage_size:
            _trace_storage.pop(0)
        
        logger.info(f"[Tracing] Finished trace: {ctx.trace_id}, duration: {total_duration}ms")
        return ctx.trace_record
    
    @staticmethod
    def get_trace(trace_id: str) -> Optional[TraceRecord]:
        """根据trace_id获取记录。"""
        for record in _trace_storage:
            if record.trace_id == trace_id:
                return record
        return None
    
    @staticmethod
    def list_traces(page: int = 1, page_size: int = 20,
                   request_type: Optional[str] = None,
                   destination: Optional[str] = None,
                   success_only: bool = False) -> TraceListResponse:
        """列出追踪记录，支持分页和过滤。"""
        filtered = _trace_storage.copy()
        
        # 过滤
        if request_type:
            filtered = [r for r in filtered if r.request_type == request_type]
        if destination:
            filtered = [r for r in filtered if r.destination == destination]
        if success_only:
            filtered = [r for r in filtered if r.success]
        
        # 按时间倒序
        filtered.sort(key=lambda x: x.created_at, reverse=True)
        
        total = len(filtered)
        
        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]
        
        return TraceListResponse(
            total=total,
            items=items,
            page=page,
            page_size=page_size,
        )
    
    @staticmethod
    def clear_traces():
        """清空所有追踪记录。"""
        _trace_storage.clear()
        logger.info("[Tracing] Cleared all trace records")


# 全局服务实例
_tracing_service = TracingService()


def get_tracing_service() -> TracingService:
    """获取追踪服务实例。"""
    return _tracing_service
