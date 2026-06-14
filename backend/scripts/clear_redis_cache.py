#!/usr/bin/env python3
"""
清空 Redis 缓存中的地图相关数据
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import REDIS_ENABLED, REDIS_URL, REDIS_KEY_PREFIX

try:
    import redis
except ImportError:
    redis = None


def main():
    print("=== 清空 Redis 缓存 ===\n")
    
    if not REDIS_ENABLED:
        print("Redis 未启用，无需清理！")
        return
    
    if redis is None:
        print("Redis 依赖未安装！")
        return
    
    try:
        # 连接 Redis
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        print("连接到 Redis 成功！\n")
        
        # 构建带前缀的搜索模式
        prefix = REDIS_KEY_PREFIX + ":"
        map_pattern = prefix + "map:*"
        weather_pattern = prefix + "weather:*"
        trip_pattern = prefix + "trip:*"
        
        # 清空所有与地图相关的缓存
        print("正在搜索地图相关的缓存键...")
        map_keys = list(client.keys(map_pattern))
        weather_keys = list(client.keys(weather_pattern))
        trip_keys = list(client.keys(trip_pattern))
        
        print(f"\n找到以下缓存键：")
        print(f"  - map:*     : {len(map_keys)} 个")
        print(f"  - weather:* : {len(weather_keys)} 个")
        print(f"  - trip:*    : {len(trip_keys)} 个")
        
        all_keys = map_keys + weather_keys + trip_keys
        
        if all_keys:
            print(f"\n正在删除 {len(all_keys)} 个缓存键...")
            for i, key in enumerate(all_keys, 1):
                print(f"  [{i}/{len(all_keys)}] 删除: {key}")
                client.delete(key)
            
            print(f"\n成功删除 {len(all_keys)} 个缓存键！")
        else:
            print("\n没有找到相关缓存键！")
        
        print("\n缓存清理完成！")
        print("\n下次生成行程时，将重新从高德地图获取最新数据！")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
