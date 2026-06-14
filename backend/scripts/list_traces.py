#!/usr/bin/env python3
"""简单查看追踪记录的脚本"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import httpx

BASE_URL = "http://127.0.0.1:8000"


def main():
    print("当前追踪记录:")
    print("=" * 80)
    
    try:
        response = httpx.get(f"{BASE_URL}/monitor/traces", timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print(f"总记录数: {data['total']}")
            print()
            
            if data['items']:
                for i, item in enumerate(data['items'], 1):
                    print(f"{i}. Trace ID: {item['trace_id']}")
                    print(f"   目的地: {item['destination']}")
                    print(f"   成功: {item['success']}")
                    print(f"   创建时间: {item['created_at']}")
                    print()
            else:
                print("暂无追踪记录")
        else:
            print(f"请求失败，状态码: {response.status_code}")
            
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
