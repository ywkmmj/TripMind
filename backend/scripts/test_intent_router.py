#!/usr/bin/env python3
"""
测试意图识别路由功能
"""
import sys
import os
import asyncio

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.mcp.intent_router import get_intent_router

# 测试用例
test_cases = [
    {
        "name": "行程规划 - 大理",
        "input": "帮我规划一个3天的大理旅行"
    },
    {
        "name": "行程规划 - 西安",
        "input": "我想去西安玩5天，预算5000元"
    },
    {
        "name": "天气查询",
        "input": "查询一下大理的天气"
    },
    {
        "name": "景点查询",
        "input": "大理有什么好玩的地方？"
    },
    {
        "name": "历史查询",
        "input": "查看我的历史行程"
    },
    {
        "name": "闲聊问候",
        "input": "你好"
    },
    {
        "name": "未知意图",
        "input": "今天是星期几？"
    }
]


async def test_intent_recognition():
    """测试意图识别功能"""
    print("=" * 70)
    print("测试意图识别功能")
    print("=" * 70)

    router = get_intent_router()

    for idx, test_case in enumerate(test_cases, 1):
        print(f"\n测试 {idx}/{len(test_cases)}: {test_case['name']}")
        print(f"输入: {test_case['input']}")

        try:
            result = await router.recognize_intent(test_case['input'])
            print(f"意图: {result['intent']}")
            print(f"置信度: {result['confidence']}")
            print(f"参数: {result['extracted_params']}")
            print(f"推理: {result['reasoning']}")
        except Exception as e:
            print(f"识别失败: {e}")

        print("-" * 50)


async def test_full_routing():
    """测试完整路由功能"""
    print("\n" + "=" * 70)
    print("测试完整路由功能")
    print("=" * 70)

    router = get_intent_router()

    # 只测试几个核心用例
    quick_tests = [
        "你好",
        "大理的天气怎么样？",
        "帮我规划去大理玩3天"
    ]

    for idx, test_input in enumerate(quick_tests, 1):
        print(f"\n测试 {idx}/{len(quick_tests)}: {test_input}")

        try:
            result = await router.route(test_input)
            print(f"状态: {result.get('status')}")
            print(f"意图: {result.get('intent')}")
            print(f"消息: {result.get('message')}")
        except Exception as e:
            print(f"处理失败: {e}")

        print("-" * 50)


async def main():
    """主函数"""
    try:
        await test_intent_recognition()
        await test_full_routing()

        print("\n" + "=" * 70)
        print("所有测试完成！")
        print("=" * 70)
    except Exception as e:
        print(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
