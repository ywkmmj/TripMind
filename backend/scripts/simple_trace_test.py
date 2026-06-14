#!/usr/bin/env python3
"""
简单的追踪功能测试
"""

import sys
import os
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.tracing_service import TracingService, TraceContext

def test_simple_trace():
    """简单的追踪测试"""
    print("=" * 80)
    print("简单追踪功能测试")
    print("=" * 80)
    
    try:
        print("\n1. 清空之前的追踪记录...")
        TracingService.clear_traces()
        print("   [OK] 已清空")
        
        print("\n2. 创建第一个追踪记录...")
        ctx1 = TracingService.create_trace(
            request_type="trip_generation",
            user_request={"destination": "大理", "days": 3},
            destination="大理"
        )
        
        # 添加一些数据
        TracingService.add_rag_context(
            ctx1,
            context="大理古城是一个历史悠久的地方...",
            source="大理攻略.md",
            chunk_index=1
        )
        
        TracingService.add_rag_context(
            ctx1,
            context="苍山洱海是必去的景点...",
            source="大理攻略.md",
            chunk_index=2
        )
        
        TracingService.add_agent_step(
            ctx1,
            step_index=1,
            state="thinking",
            thought="我需要为用户规划一个大理3天的旅行计划..."
        )
        
        TracingService.add_agent_step(
            ctx1,
            step_index=2,
            state="acting",
            action="search_destination_guide",
            tool_input={"destination": "大理", "top_k": 3}
        )
        
        TracingService.finish_trace(
            ctx1,
            success=True,
            final_output={"trip_id": "trip_dali_001", "destination": "大理"}
        )
        print(f"   [OK] 第一个追踪创建成功，trace_id: {ctx1.trace_id}")
        
        print("\n3. 创建第二个追踪记录...")
        ctx2 = TracingService.create_trace(
            request_type="trip_generation",
            user_request={"destination": "丽江", "days": 2},
            destination="丽江"
        )
        
        TracingService.add_agent_step(
            ctx2,
            step_index=1,
            state="thinking",
            thought="我需要为用户规划一个丽江2天的旅行计划..."
        )
        
        TracingService.finish_trace(
            ctx2,
            success=True,
            final_output={"trip_id": "trip_lijiang_001", "destination": "丽江"}
        )
        print(f"   [OK] 第二个追踪创建成功，trace_id: {ctx2.trace_id}")
        
        print("\n4. 列出所有追踪记录...")
        list_result = TracingService.list_traces(page=1, page_size=20)
        print(f"   总记录数: {list_result.total}")
        print(f"   当前页记录数: {len(list_result.items)}")
        
        print("\n   追踪列表:")
        for i, trace in enumerate(list_result.items, 1):
            print(f"   {i}. Trace ID: {trace.trace_id}")
            print(f"      目的地: {trace.destination}")
            print(f"      成功: {trace.success}")
            print(f"      创建时间: {trace.created_at}")
            
            if trace.agent_steps:
                print(f"      步骤数: {len(trace.agent_steps)}")
                print()
        
        print("\n5. 获取第一个追踪的详细信息...")
        if list_result.items:
            trace_id = list_result.items[0].trace_id
            single_trace = TracingService.get_trace(trace_id)
            
            if single_trace:
                print(f"   [OK] 获取详情成功！")
                print(f"   Trace ID: {single_trace.trace_id}")
                print(f"   目的地: {single_trace.destination}")
                print(f"   总耗时: {single_trace.total_duration_ms} ms")
                print(f"   成功: {single_trace.success}")
                
                if single_trace.agent_steps:
                    print(f"\n   Agent 执行步骤:")
                    for step in single_trace.agent_steps:
                        print(f"   步骤 {step.step_index}: {step.state}")
                        if step.thought:
                            print(f"      思考: {step.thought}")
                        if step.action:
                            print(f"      动作: {step.action}")
        
        print("\n" + "=" * 80)
        print("[OK] 测试完成！追踪功能正常工作！")
        print("=" * 80)
        print("\n[提示] 你可以通过 API 访问这些追踪记录:")
        print("   GET http://127.0.0.1:8000/monitor/traces")
        print("\n[提示] 或者在浏览器中打开 Swagger UI:")
        print("   http://127.0.0.1:8000/docs")
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_simple_trace()
    sys.exit(0 if success else 1)
