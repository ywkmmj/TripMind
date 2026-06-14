#!/usr/bin/env python3
"""
测试缓存效果的简单脚本
支持多级缓存测试（内存 + Redis）
"""
import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.rag.retriever import retrieve_travel_guide
import logging

# 设置日志级别
logging.basicConfig(level=logging.INFO)


def clear_memory_cache():
    """清空内存缓存（用于测试）"""
    from app.services.cache_service import _memory_cache
    _memory_cache.clear()
    print("[清空内存缓存]")


def clear_redis_cache():
    """清空 Redis 缓存（用于测试）"""
    from app.services.cache_service import _get_redis_client, _build_key
    client = _get_redis_client()
    if client:
        keys = client.keys(f"{_build_key('*')}")
        if keys:
            client.delete(*keys)
            print(f"[清空 Redis 缓存] 删除了 {len(keys)} 个键")
        else:
            print("[清空 Redis 缓存] 没有缓存键")


def test_multilevel_cache():
    """测试多级缓存效果"""
    print("=" * 70)
    print("开始测试多级缓存（内存 + Redis）效果...")
    print("=" * 70)
    
    # 测试查询
    test_query = "大理 自然风景 拍照"
    print(f"\n测试查询: '{test_query}'")
    
    # 先清空所有缓存
    print("\n--- 步骤 1：清空所有缓存 ---")
    clear_redis_cache()
    clear_memory_cache()
    
    # 第一次查询（都未命中）
    print("\n--- 第一次查询（完全未命中）---")
    start_time = time.time()
    result1 = retrieve_travel_guide(test_query, top_k=3)
    time1 = time.time() - start_time
    print(f"结果数量: {len(result1)}")
    print(f"耗时: {time1:.3f}秒")
    
    # 第二次查询（Redis 缓存命中）
    print("\n--- 第二次查询（Redis 缓存命中）---")
    start_time = time.time()
    result2 = retrieve_travel_guide(test_query, top_k=3)
    time2 = time.time() - start_time
    print(f"结果数量: {len(result2)}")
    print(f"耗时: {time2:.3f}秒")
    
    # 第三次查询（内存缓存命中）
    print("\n--- 第三次查询（内存缓存命中）---")
    start_time = time.time()
    result3 = retrieve_travel_guide(test_query, top_k=3)
    time3 = time.time() - start_time
    print(f"结果数量: {len(result3)}")
    print(f"耗时: {time3:.3f}秒")
    
    # 计算性能提升
    print("\n" + "-" * 70)
    print("性能对比:")
    print(f"  完全未命中:  {time1:.3f}秒 (基准)")
    print(f"  Redis 命中:  {time2:.3f}秒 ({(1-time2/time1)*100:.1f}% 降低)")
    print(f"  内存命中:    {time3:.3f}秒 ({(1-time3/time1)*100:.1f}% 降低)")
    
    if time2 > 0 and time3 > 0:
        print(f"\n  Redis 加速比:  {time1/time2:.2f}x")
        print(f"  内存加速比:   {time1/time3:.2f}x")
        print(f"  内存比 Redis 快:  {time2/time3:.2f}x")
    
    print("\n" + "=" * 70)
    print("多级缓存测试完成！")
    print("=" * 70)


if __name__ == "__main__":
    test_multilevel_cache()