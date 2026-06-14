from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastmcp import FastMCP

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent.parent

sys.path.insert(0, str(BACKEND_DIR))

from app.config import AMAP_API_KEY, AMAP_BASE_URL, AMAP_TIMEOUT_SECONDS, REDIS_WEATHER_TTL_SECONDS
from app.services.cache_service import get_cached_json, set_cached_json

logger = logging.getLogger(__name__)


def _ensure_amap_api_key():
    if not AMAP_API_KEY:
        raise RuntimeError("当前环境未配置 AMAP_API_KEY，无法调用天气服务。")


def _build_client():
    import httpx
    return httpx.Client(timeout=AMAP_TIMEOUT_SECONDS)


def _request_amap_weather(path: str, params: dict):
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
        raise RuntimeError(f"高德天气接口调用失败：{info}")

    return payload


def _normalize_cache_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower()


def _get_city_adcode(city: str):
    try:
        from app.mcp.amap_http_server import geocode_address
        geocode = geocode_address(city, city=city)
        return geocode.get("adcode")
    except Exception:
        return None


mcp = FastMCP("WeatherHTTPServer")


@mcp.tool()
def get_weather_forecast(city: str):
    cache_key = f"http:weather:forecast:{_normalize_cache_text(city)}"
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        return cached_value

    city_code = _get_city_adcode(city)
    if not city_code:
        return {"error": f"无法获取城市 {city} 的行政区划代码"}

    payload = _request_amap_weather(
        "/weather/weatherInfo",
        {
            "city": city_code,
            "extensions": "all",
        },
    )

    forecasts = payload.get("forecasts", [])
    if not forecasts:
        return {"error": "未获取到天气预报结果"}

    first = forecasts[0]
    casts = first.get("casts", [])

    days = [
        {
            "date": cast.get("date"),
            "week": cast.get("week"),
            "day_weather": cast.get("dayweather"),
            "night_weather": cast.get("nightweather"),
            "day_temp": cast.get("daytemp"),
            "night_temp": cast.get("nighttemp"),
            "day_wind": cast.get("daywind"),
            "night_wind": cast.get("nightwind"),
        }
        for cast in casts
    ]

    result = {
        "city": first.get("city") or city,
        "province": first.get("province"),
        "adcode": first.get("adcode"),
        "report_time": first.get("reporttime"),
        "days": days,
    }
    set_cached_json(cache_key, result, expire_seconds=REDIS_WEATHER_TTL_SECONDS)
    return result


@mcp.tool()
def get_current_weather(city: str):
    cache_key = f"http:weather:current:{_normalize_cache_text(city)}"
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        return cached_value

    city_code = _get_city_adcode(city)
    if not city_code:
        return {"error": f"无法获取城市 {city} 的行政区划代码"}

    payload = _request_amap_weather(
        "/weather/weatherInfo",
        {
            "city": city_code,
            "extensions": "base",
        },
    )

    lives = payload.get("lives", [])
    if not lives:
        return {"error": "未获取到实时天气结果"}

    live = lives[0]
    result = {
        "city": live.get("city"),
        "weather": live.get("weather"),
        "temperature": live.get("temperature"),
        "wind_direction": live.get("winddirection"),
        "wind_power": live.get("windpower"),
        "humidity": live.get("humidity"),
        "report_time": live.get("reporttime"),
    }
    set_cached_json(cache_key, result, expire_seconds=900)
    return result


@mcp.tool()
def get_weather_alert(city: str):
    cache_key = f"http:weather:alert:{_normalize_cache_text(city)}"
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        return cached_value

    city_code = _get_city_adcode(city)
    if not city_code:
        return {"error": f"无法获取城市 {city} 的行政区划代码"}

    payload = _request_amap_weather(
        "/warning",
        {
            "city": city_code,
        },
    )

    alerts = payload.get("data", [])
    if not alerts:
        return {
            "city": city,
            "has_alert": False,
            "alerts": []
        }

    result = {
        "city": city,
        "has_alert": True,
        "count": len(alerts),
        "alerts": [
            {
                "province": alert.get("province"),
                "city": alert.get("city"),
                "alert_type": alert.get("alertType"),
                "alert_level": alert.get("alert_level"),
                "alert_name": alert.get("alert_name"),
                "content": alert.get("content"),
                "publish_time": alert.get("publish_time"),
            }
            for alert in alerts
        ]
    }
    set_cached_json(cache_key, result, expire_seconds=1800)
    return result


@mcp.tool()
def get_weather_suggestion(city: str):
    cache_key = f"http:weather:suggestion:{_normalize_cache_text(city)}"
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        return cached_value

    city_code = _get_city_adcode(city)
    if not city_code:
        return {"error": f"无法获取城市 {city} 的行政区划代码"}

    payload = _request_amap_weather(
        "/weather/weatherInfo",
        {
            "city": city_code,
            "extensions": "all",
        },
    )

    forecasts = payload.get("forecasts", [])
    if not forecasts:
        return {"error": "未获取到天气数据"}

    casts = forecasts[0].get("casts", [])
    if not casts:
        return {"error": "未获取到天气预报"}

    today = casts[0]
    result = {
        "city": city,
        "date": today.get("date"),
        "week": today.get("week"),
        "day_weather": today.get("dayweather"),
        "night_weather": today.get("nightweather"),
        "day_temp": today.get("daytemp"),
        "night_temp": today.get("nighttemp"),
        "suggestions": _generate_suggestions(today),
    }
    set_cached_json(cache_key, result, expire_seconds=1800)
    return result


def _generate_suggestions(weather_data: dict) -> dict:
    suggestions = {}

    day_weather = weather_data.get("dayweather", "")
    day_temp = weather_data.get("daytemp", "")

    if "雨" in day_weather or "雪" in day_weather:
        suggestions["出行"] = "今天有降水，请带好雨具"
    elif "阴" in day_weather:
        suggestions["出行"] = "今天天气阴沉，建议携带外套"
    else:
        suggestions["出行"] = "今天天气良好，适合外出"

    if day_temp:
        try:
            temp = int(day_temp)
            if temp < 10:
                suggestions["穿着"] = "气温较低，建议穿厚外套"
            elif temp < 20:
                suggestions["穿着"] = "气温适宜，建议穿长袖"
            else:
                suggestions["穿着"] = "气温较高，注意防晒"
        except (ValueError, TypeError):
            pass

    if "晴" in day_weather:
        suggestions["紫外线"] = "紫外线较强，建议涂抹防晒霜"
    else:
        suggestions["紫外线"] = "紫外线较弱，可以不涂防晒"

    return suggestions


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("启动天气 MCP HTTP 服务...")

    mcp.run(transport="streamable-http", port=8002)
