
"""
测试 Qwen3-VL-Flash 多模态模型图片解析测试脚本
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.knowledge_base.parsers.multimodal_parser import MultimodalParser


async def main():
    print("=" * 60)
    print("Qwen3-VL-Flash 多模态模型测试")
    print("=" * 60)

    # 测试图片路径
    image_path = r"D:\Downloads\xiaohongshu\5月长沙已回。。。说点难听的大实话_2_丝狮公举_来自小红书网页版.jpg"

    # 检查图片是否存在
    if not os.path.exists(image_path):
        print(f"错误：图片文件不存在：{image_path}")
        return

    print(f"图片路径：{image_path}")
    print()

    # 初始化解析器
    parser = MultimodalParser()
    print(f"使用模型：{parser.multimodal_model}")
    print(f"API Key 配置：{'已配置' if parser.api_key else '未配置'}")
    print()

    if not parser.api_key:
        print("错误：未配置 LLM_API_KEY")
        return

    try:
        print("正在分析图片...")
        posts = await parser.parse_file(image_path)
        
        print()
        print("=" * 60)
        print("解析结果：")
        print("=" * 60)
        
        for i, post in enumerate(posts, 1):
            print(f"\n帖子 {i}：")
            print(f"  标题：{post.title}")
            print(f"  目的地：{post.destination}")
            print(f"  内容：{post.content}")
            
            if post.images:
                print(f"\n  图片洞察：")
                for img in post.images:
                    print(f"    描述：{img.description}")
                    print(f"    识别景点：{img.recognized_spots}")
                    print(f"    活动：{img.activities}")
                    print(f"    季节特征：{img.season_hints}")
                    print(f"    人流：{img.crowd_level}")
            
            if post.key_attractions:
                print(f"\n  关键景点：")
                for attr in post.key_attractions:
                    print(f"    - {attr}")
            
            if post.food_recommendations:
                print(f"\n  美食推荐：")
                for food in post.food_recommendations:
                    print(f"    - {food}")
            
            if post.experience_tips:
                print(f"\n  经验提示：")
                for tip in post.experience_tips:
                    print(f"    - {tip}")

        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n错误：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 加载环境变量
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"已加载环境变量：{env_path}")

    asyncio.run(main())
