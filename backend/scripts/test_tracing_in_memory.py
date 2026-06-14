#!/usr/bin/env python3
"""测试追踪服务在内存中的工作情况"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.tracing_service import TracingService
from app.models.schemas import TripRequest
from app.services.trip_service import generate_trip_itinerary


def main():
    print("测试追踪服务...")
    print("=" * 80)
    
    # 1. 清空旧数据
    print("\n1. 清空旧数据...")
    TracingService.clear_traces()
    
    # 2. 创建一个追踪上下文
    print("\n2. 创建测试追踪...")
    
    # 创建测试请求
    today = datetime.now().date()
    trip_request = TripRequest(
        destination="大理",
        start_date=today,
        end_date=today + timedelta(days=2),
        travelers=2,
        days=3,
        budget=5000,
        preferences=["美食", "自然风景"],
        pace="轻松",
        dietary_preferences=[],
        hotel_level=None,
        special_notes=None
    )
    
    # 创建追踪
    trace_ctx = TracingService.create_trace(
        request_type="trip_generation",
        user_request=trip_request.model_dump(),
        destination=trip_request.destination
    )
    print(f"[OK] 追踪创建成功，trace_id: {trace_ctx.trace_id}")
    
    # 3. 调用 generate_trip_itinerary 并传入 trace_ctx
    print("\n3. 生成行程并测试追踪...")
    itinerary = generate_trip_itinerary(trip_request, trace_ctx)
    
    # 4. 完成追踪
    print("\n4. 完成追踪...")
    TracingService.finish_trace(
        trace_ctx,
        success=True,
        final_output=itinerary.model_dump()
    )
    
    # 5. 查看所有追踪
    print("\n5. 查看所有追踪记录...")
    traces = TracingService.list_traces()
    print(f"[OK] 总记录数: {traces.total}")
    
    if traces.items:
        trace = traces.items[0]
        print(f"  Trace ID: {trace.trace_id}")
        print(f"  目的地: {trace.destination}")
        print(f"  成功: {trace.success}")
        
        if trace.rag_contexts:
            print(f"  RAG 上下文: {len(trace.rag_contexts)} 条")
        
        print("\n" + "=" * 80)
        print("[OK] 追踪功能在内存中工作正常！")
    else:
        print("\n[ERROR] 没有找到追踪记录！")


if __name__ == "__main__":
    main()
