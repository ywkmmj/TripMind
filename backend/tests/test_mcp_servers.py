from __future__ import annotations

import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent

sys.path.insert(0, str(BACKEND_DIR))


def main():
    print("=== MCP 服务测试 ===")
    print()

    print("1. 导入高德地图 MCP 工具...")
    from app.mcp.amap_server import (
        geocode_address,
        search_places,
        estimate_route,
        get_place_detail,
        batch_geocode,
    )
    print("   高德地图 MCP 工具导入成功")
    print()

    print("2. 导入天气 MCP 工具...")
    from app.mcp.weather_server import (
        get_weather_forecast,
        get_current_weather,
        get_weather_alert,
        get_weather_suggestion,
    )
    print("   天气 MCP 工具导入成功")
    print()

    print("3. 测试 geocode_address")
    try:
        result = geocode_address(address="大理古城")
        print(f"   结果: {result}")
    except Exception as e:
        print(f"   错误: {e}")
    print()

    print("4. 测试 search_places")
    try:
        result = search_places(keyword="洱海", city="大理")
        print(f"   结果数量: {result.get('count', 0)}")
        if result.get("pois"):
            print(f"   第一个: {result['pois'][0].get('name')}")
    except Exception as e:
        print(f"   错误: {e}")
    print()

    print("5. 测试 get_weather_forecast")
    try:
        result = get_weather_forecast(city="大理")
        print(f"   城市: {result.get('city')}")
        if result.get("days"):
            print(f"   预报天数: {len(result['days'])}")
    except Exception as e:
        print(f"   错误: {e}")
    print()

    print("6. 测试 FastMCP 服务...")
    from app.mcp.amap_server import mcp as amap_mcp
    from app.mcp.weather_server import mcp as weather_mcp
    print(f"   AmapMCP 服务名: {amap_mcp.name}")
    print(f"   WeatherMCP 服务名: {weather_mcp.name}")
    print()

    print("=== 测试完成 ===")


if __name__ == "__main__":
    main()