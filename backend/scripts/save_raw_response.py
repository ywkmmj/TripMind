
"""
保存 API 原始响应到文件
"""

import asyncio
import os
import sys
import base64
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def save_raw_response():
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    api_key = os.getenv("LLM_API_KEY", "")
    image_path = r"D:\Downloads\xiaohongshu\5月长沙已回。。。说点难听的大实话_2_丝狮公举_来自小红书网页版.jpg"

    print("=" * 60)
    print("保存 API 原始响应到文件")
    print("=" * 60)

    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode()

    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    prompt = """请分析这张旅行图片，提取以下信息：
1. 图片描述（详细描述图片中的内容）
2. 识别出的景点或地标
3. 可能的活动类型（如拍照、徒步、用餐等）
4. 季节特征（如有）
5. 人流估计（低/中/高）

请以 JSON 格式返回，包含这些字段：
{
    "description": "图片描述文本",
    "spots": ["景点1", "景点2"],
    "activities": ["活动1", "活动2"],
    "season_hints": ["季节特征1"],
    "crowd_level": "低/中/高"
}

请确保返回有效的 JSON，不要包含其他内容。
"""
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

    output_path = Path(__file__).parent.parent / "api_response.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"响应已保存到：{output_path}")


if __name__ == "__main__":
    asyncio.run(save_raw_response())
