from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastmcp import FastMCP

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent.parent

sys.path.insert(0, str(BACKEND_DIR))

from app.config import AMAP_API_KEY, AMAP_BASE_URL, AMAP_DEFAULT_CITY, AMAP_TIMEOUT_SECONDS, REDIS_MAP_TTL_SECONDS
from app.services.cache_service import get_cached_json, set_cached_json

logger = logging.getLogger(__name__)


def _ensure_amap_api_key():
    if not AMAP_API_KEY:
        raise RuntimeError("当前环境未配置 AMAP_API_KEY，无法调用高德地图服务。")


def _build_client():
    import httpx
    return httpx.Client(timeout=AMAP_TIMEOUT_SECONDS)


def _request_amap(path: str, params: dict):
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


mcp = FastMCP("AmapHTTPServer")


@mcp.tool()
def geocode_address(address: str, city: str | None = None):
    cache_key = (
        f"http:map:geocode:{_normalize_cache_text(address)}:{_normalize_cache_text(city or AMAP_DEFAULT_CITY)}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
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
def search_places(keyword: str, city: str | None = None, page_size: int = 5):
    cache_key = (
        f"http:map:place:{_normalize_cache_text(keyword)}:{_normalize_cache_text(city or AMAP_DEFAULT_CITY)}:{page_size}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
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
    results = []
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
def estimate_route(origin_address: str, destination_address: str, city: str | None = None):
    origin_geocode = geocode_address(origin_address, city)
    dest_geocode = geocode_address(destination_address, city)

    if not origin_geocode.get("latitude") or not dest_geocode.get("latitude"):
        return {"error": "无法获取起点或终点的坐标信息"}

    origin_longitude = origin_geocode["longitude"]
    origin_latitude = origin_geocode["latitude"]
    dest_longitude = dest_geocode["longitude"]
    dest_latitude = dest_geocode["latitude"]

    cache_key = (
        "http:map:route:"
        f"{origin_longitude:.6f},{origin_latitude:.6f}:"
        f"{dest_longitude:.6f},{dest_latitude:.6f}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
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


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("启动高德地图 MCP HTTP 服务...")

    mcp.run(transport="streamable-http", port=8001)
