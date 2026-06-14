
"""
调试 DashScope 多模态 API 调用
"""

import asyncio
import os
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def debug_dashscope_api():
    """测试 DashScope 多模态 API 的不同调用方式"""

    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    api_key = os.getenv("LLM_API_KEY", "")
    image_path = r"D:\Downloads\xiaohongshu\5月长沙已回。。。说点难听的大实话_2_丝狮公举_来自小红书网页版.jpg"

    print("=" * 60)
    print("DashScope 多模态 API 调试")
    print("=" * 60)
    print(f"API Key: {api_key[:10]}...")
    print(f"图片: {image_path}")
    print()

    if not os.path.exists(image_path):
        print(f"图片不存在")
        return

    # 读取图片
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode()

    import httpx

    # 测试方式1: 使用 use_raw_prompt (当前代码的方式)
    print("=" * 60)
    print("测试方式 1: use_raw_prompt")
    print("=" * 60)
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        prompt = "请描述这张图片"
        data = {
            "model": "qwen3-vl-flash",
            "input": {
                "prompt": prompt,
                "image": f"data:image/jpeg;base64,{image_base64}",
            },
            "parameters": {
                "max_tokens": 1024,
                "use_raw_prompt": True,
            },
        }
        api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(api_url, headers=headers, json=data)
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text[:500]}")
    except Exception as e:
        print(f"错误: {e}")

    print()
    print("=" * 60)
    print("测试方式 2: 不使用 use_raw_prompt")
    print("=" * 60)
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "qwen3-vl-flash",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                            {"type": "text", "text": "请描述这张图片"}
                        ]
                    }
                ]
            },
            "parameters": {
                "max_tokens": 1024,
            },
        }
        api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(api_url, headers=headers, json=data)
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text[:500]}")
    except Exception as e:
        print(f"错误: {e}")

    print()
    print("=" * 60)
    print("测试方式 3: messages 格式的 multimodal API")
    print("=" * 60)
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "qwen3-vl-flash",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": f"data:image/jpeg;base64,{image_base64}"},
                            {"text": "请描述这张图片"}
                        ]
                    }
                ]
            },
            "parameters": {
                "max_tokens": 1024,
            },
        }
        api_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(api_url, headers=headers, json=data)
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text[:1000]}")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    asyncio.run(debug_dashscope_api())
