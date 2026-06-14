#!/usr/bin/env python3
"""
调试地图信息填充功能
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.schemas import TripRequest
from app.services.trip_service import generate_trip_itinerary
from app.services.map_service import enrich_itinerary_with_map_data


def main():
    print("=== 调试地图信息填充 ===\n")
    
    # 1. 创建测试请求
    request = TripRequest(
        destination="长沙",
        start_date=date(2024, 5, 27),
        end_date=date(2024, 5, 30),
        days=4,
        travelers=2,
        budget=5000,
        preferences=["美食", "自然风景"],
        pace="适中",
        dietary_preferences=[],
        hotel_level="舒适型",
        special_notes=None
    )
    
    print("1. 生成基础行程...")
    try:
        itinerary = generate_trip_itinerary(request)
        print("   行程生成成功！")
    except Exception as e:
        print(f"   行程生成失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print(f"\n2. 检查填充前的景点数据...")
    for day in itinerary.days:
        for spot in day.spots:
            print(f"\n   第 {day.day_index} 天 - {spot.name}:")
            print(f"     - 地址: {spot.address}")
            print(f"     - 经纬度: {spot.latitude}, {spot.longitude}")
            print(f"     - 图片: {spot.image_url}")
            print(f"     - 评分: {spot.rating}")
    
    print(f"\n3. 手动调用地图数据填充...")
    try:
        itinerary = enrich_itinerary_with_map_data(itinerary, city="长沙")
        print("   地图数据填充成功！")
    except Exception as e:
        print(f"   地图数据填充失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print(f"\n4. 检查填充后的景点数据...")
    for day in itinerary.days:
        for spot in day.spots:
            print(f"\n   第 {day.day_index} 天 - {spot.name}:")
            print(f"     - 地址: {spot.address}")
            print(f"     - 经纬度: {spot.latitude}, {spot.longitude}")
            print(f"     - 图片: {spot.image_url}")
            print(f"     - 图片数量: {len(spot.images) if hasattr(spot, 'images') else 'N/A'}")
            print(f"     - 评分: {spot.rating}")
            print(f"     - 营业时间: {spot.opening_hours if hasattr(spot, 'opening_hours') else 'N/A'}")
            print(f"     - 电话: {spot.phone if hasattr(spot, 'phone') else 'N/A'}")
            print(f"     - 标签: {spot.tags if hasattr(spot, 'tags') else 'N/A'}")
    
    print(f"\n5. 检查餐饮数据...")
    for day in itinerary.days:
        for meal in day.meals:
            print(f"\n   第 {day.day_index} 天 - {meal.name}:")
            print(f"     - 地址: {meal.address if hasattr(meal, 'address') else 'N/A'}")
            print(f"     - 图片: {meal.image_url if hasattr(meal, 'image_url') else 'N/A'}")
            print(f"     - 评分: {meal.rating if hasattr(meal, 'rating') else 'N/A'}")
    
    print(f"\n6. 检查酒店数据...")
    for day in itinerary.days:
        if day.hotel:
            print(f"\n   第 {day.day_index} 天 - {day.hotel.name}:")
            print(f"     - 地址: {day.hotel.address}")
            print(f"     - 图片: {day.hotel.image_url if hasattr(day.hotel, 'image_url') else 'N/A'}")
            print(f"     - 评分: {day.hotel.rating if hasattr(day.hotel, 'rating') else 'N/A'}")
    
    print("\n=== 调试结束 ===")


if __name__ == "__main__":
    main()
