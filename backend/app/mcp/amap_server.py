from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from app.config import (
    AMAP_API_KEY,
    AMAP_BASE_URL,
    AMAP_DEFAULT_CITY,
    AMAP_TIMEOUT_SECONDS,
    REDIS_MAP_TTL_SECONDS,
)
from app.services.cache_service import get_cached_json, set_cached_json


logger = logging.getLogger(__name__)
mcp = FastMCP("AmapMCP")


def _ensure_amap_api_key() -> None:
    if not AMAP_API_KEY:
        raise RuntimeError("当前环境未配置 AMAP_API_KEY，无法调用高德地图服务。")


def _build_client():
    import httpx
    return httpx.Client(timeout=AMAP_TIMEOUT_SECONDS)


def _request_amap(path: str, params: dict[str, Any]) -> dict[str, Any]:
    _ensure_amap_api_key()

    request_params = {
        "key": AMAP_API_KEY,
        **params,
    }

    with _build_client() as client:
        response = client.get(f"{AMAP_BASE_URL}{path}", params=request_params)
        response.raise_for_status()
        payload = response.json()

    if payload.get("status") != "1":
        info = payload.get("info", "未知错误")
        raise RuntimeError(f"高德地图接口调用失败：{info}")

    return payload


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_location(location: str | None) -> tuple[float | None, float | None]:
    if not location or "," not in location:
        return None, None
    longitude_text, latitude_text = location.split(",", 1)
    return _parse_float(latitude_text), _parse_float(longitude_text)


def _normalize_cache_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower()


@mcp.tool()
def geocode_address(address: str, city: str | None = None) -> dict[str, Any]:
    """根据地址获取经纬度信息

    Args:
        address: 要查询的地址
        city: 城市名称（可选）

    Returns:
        包含 latitude, longitude, formatted_address 等字段的字典
    """
    cache_key = (
        f"mcp:map:geocode:{_normalize_cache_text(address)}:{_normalize_cache_text(city or AMAP_DEFAULT_CITY)}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info("MCP geocode cache hit: address=%s", address)
        return cached_value

    payload = _request_amap(
        "/geocode/geo",
        {
            "address": address,
            "city": city or AMAP_DEFAULT_CITY,
        },
    )

    geocodes = payload.get("geocodes", [])
    if not geocodes:
        return {"error": "未找到该地址的坐标信息"}

    first = geocodes[0]
    latitude, longitude = _split_location(first.get("location"))
    result = {
        "formatted_address": first.get("formatted_address", address),
        "province": first.get("province"),
        "city": first.get("city"),
        "district": first.get("district"),
        "adcode": first.get("adcode"),
        "latitude": latitude,
        "longitude": longitude,
    }
    set_cached_json(cache_key, result, expire_seconds=REDIS_MAP_TTL_SECONDS)
    return result


@mcp.tool()
def search_places(
    keyword: str,
    city: str | None = None,
    page_size: int = 5,
) -> dict[str, Any]:
    """根据关键词搜索 POI 点位信息

    Args:
        keyword: 搜索关键词
        city: 城市名称（可选）
        page_size: 返回结果数量（默认5）

    Returns:
        包含 pois 列表的字典，每个 POI 包含 name, address, latitude, longitude 等字段
    """
    cache_key = (
        f"mcp:map:place:{_normalize_cache_text(keyword)}:{_normalize_cache_text(city or AMAP_DEFAULT_CITY)}:{page_size}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info("MCP place search cache hit: keyword=%s", keyword)
        return cached_value

    payload = _request_amap(
        "/place/text",
        {
            "keywords": keyword,
            "city": city or AMAP_DEFAULT_CITY,
            "offset": page_size,
            "page": 1,
            "extensions": "all",
        },
    )

    pois = payload.get("pois", [])
    results: list[dict[str, Any]] = []
    for poi in pois:
        latitude, longitude = _split_location(poi.get("location"))
        photos = poi.get("photos") if isinstance(poi.get("photos"), list) else []
        first_photo = photos[0] if photos and isinstance(photos[0], dict) else {}
        results.append(
            {
                "name": poi.get("name"),
                "address": poi.get("address"),
                "cityname": poi.get("cityname"),
                "adname": poi.get("adname"),
                "type": poi.get("type"),
                "poi_id": poi.get("id"),
                "image_url": first_photo.get("url"),
                "latitude": latitude,
                "longitude": longitude,
            }
        )

    result = {"count": len(results), "pois": results}
    set_cached_json(cache_key, result, expire_seconds=REDIS_MAP_TTL_SECONDS)
    return result


@mcp.tool()
def estimate_route(
    origin_address: str,
    destination_address: str,
    city: str | None = None,
) -> dict[str, Any]:
    """估算两个地点之间的驾车路线距离和耗时

    Args:
        origin_address: 出发地地址
        destination_address: 目的地地址
        city: 城市名称（可选）

    Returns:
        包含 distance_km, estimated_minutes 等字段的字典
    """
    origin_geocode = geocode_address(origin_address, city)
    dest_geocode = geocode_address(destination_address, city)

    if not origin_geocode.get("latitude") or not dest_geocode.get("latitude"):
        return {"error": "无法获取起点或终点的坐标信息"}

    origin_longitude = origin_geocode["longitude"]
    origin_latitude = origin_geocode["latitude"]
    dest_longitude = dest_geocode["longitude"]
    dest_latitude = dest_geocode["latitude"]

    cache_key = (
        "mcp:map:route:"
        f"{origin_longitude:.6f},{origin_latitude:.6f}:"
        f"{dest_longitude:.6f},{dest_latitude:.6f}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info("MCP route cache hit")
        return cached_value

    payload = _request_amap(
        "/direction/driving",
        {
            "origin": f"{origin_longitude},{origin_latitude}",
            "destination": f"{dest_longitude},{dest_latitude}",
            "strategy": 0,
        },
    )

    route = payload.get("route", {})
    paths = route.get("paths", [])
    if not paths:
        return {"error": "未找到路线信息"}

    first_path = paths[0]
    distance_meters = _parse_float(first_path.get("distance"))
    duration_seconds = _parse_float(first_path.get("duration"))

    result = {
        "origin": origin_address,
        "destination": destination_address,
        "distance_meters": distance_meters,
        "distance_km": round(distance_meters / 1000, 2) if distance_meters is not None else None,
        "duration_seconds": duration_seconds,
        "estimated_minutes": round(duration_seconds / 60) if duration_seconds is not None else None,
        "taxi_cost": _parse_float(route.get("taxi_cost")),
    }
    set_cached_json(cache_key, result, expire_seconds=REDIS_MAP_TTL_SECONDS)
    return result


@mcp.tool()
def get_place_detail(poi_id: str) -> dict[str, Any]:
    """根据 POI ID 获取详细信息

    Args:
        poi_id: POI 唯一标识符

    Returns:
        包含 POI 详细信息的字典
    """
    cache_key = f"mcp:map:poi_detail:{poi_id}"
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        return cached_value

    payload = _request_amap(
        "/place/detail",
        {
            "id": poi_id,
        },
    )

    pois = payload.get("pois", [])
    if not pois:
        return {"error": "未找到该 POI 的详细信息"}

    poi = pois[0]
    latitude, longitude = _split_location(poi.get("location"))
    result = {
        "name": poi.get("name"),
        "address": poi.get("address"),
        "location": {"latitude": latitude, "longitude": longitude},
        "tel": poi.get("tel"),
        "type": poi.get("type"),
        "typecode": poi.get("typecode"),
        "business_area": poi.get("business_area"),
        "citycode": poi.get("citycode"),
    }
    set_cached_json(cache_key, result, expire_seconds=REDIS_MAP_TTL_SECONDS)
    return result


@mcp.tool()
def batch_geocode(addresses: list[str], city: str | None = None) -> dict[str, Any]:
    """批量查询地址的经纬度信息

    Args:
        addresses: 地址列表
        city: 城市名称（可选）

    Returns:
        包含批量查询结果的字典
    """
    results = []
    for address in addresses:
        try:
            geocode = geocode_address(address, city)
            results.append({
                "address": address,
                "success": "error" not in geocode,
                "data": geocode
            })
        except Exception as e:
            results.append({
                "address": address,
                "success": False,
                "error": str(e)
            })

    return {
        "count": len(results),
        "success_count": sum(1 for r in results if r["success"]),
        "results": results
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")