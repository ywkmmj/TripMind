
"""
查看 API 原始响应
"""

import asyncio
import os
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def check_raw_response():
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    api_key = os.getenv("LLM_API_KEY", "")
    image_path = r"D:\Downloads\xiaohongshu\5月长沙已回。。。说点难听的大实话_2_丝狮公举_来自小红书网页版.jpg"

    print("=" * 60)
    print("检查 API 原始响应")
    print("=" * 60)

    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode()

    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    prompt = "请描述这张图片"
    data = {
        "model": "qwen3-vl-flash",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/jpeg;base64,{image_base64}"},
                        {"text": prompt}
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
        result = response.json()

    print(f"完整响应：")
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(check_raw_response())
