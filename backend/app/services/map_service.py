from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import (
    AMAP_API_KEY,
    AMAP_BASE_URL,
    AMAP_DEFAULT_CITY,
    AMAP_TIMEOUT_SECONDS,
    REDIS_MAP_TTL_SECONDS,
)
from app.models.schemas import HotelItem, Itinerary, MealItem, PhotoItem, SpotItem, TransportItem
from app.services.cache_service import get_cached_json, set_cached_json


logger = logging.getLogger(__name__)


def _ensure_amap_api_key() -> None:
    """确保当前环境已经配置高德地图 Key。"""
    if not AMAP_API_KEY:
        raise RuntimeError("当前环境未配置 AMAP_API_KEY，无法调用高德地图服务。")


def _build_client() -> httpx.Client:
    """创建访问高德 HTTP API 的客户端。"""
    return httpx.Client(timeout=AMAP_TIMEOUT_SECONDS)


def _request_amap(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """调用高德地图 API 并返回 JSON 结果。"""
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
    """把字符串安全转换成浮点数。"""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_location(location: str | None) -> tuple[float | None, float | None]:
    """把高德返回的 '经度,纬度' 文本拆成两个浮点数。"""
    if not location or "," not in location:
        return None, None

    longitude_text, latitude_text = location.split(",", 1)
    return _parse_float(latitude_text), _parse_float(longitude_text)


def _normalize_cache_text(value: str | None) -> str:
    """把缓存 key 里用到的文本做简单标准化。"""
    if value is None:
        return ""
    return value.strip().lower()


def geocode_address(address: str, city: str | None = None) -> dict[str, Any] | None:
    """根据地址获取经纬度信息。"""
    cache_key = (
        f"map:geocode:{_normalize_cache_text(address)}:{_normalize_cache_text(city or AMAP_DEFAULT_CITY)}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info("map geocode cache hit: address=%s city=%s", address, city or AMAP_DEFAULT_CITY)
        return cached_value
    logger.info("map geocode cache miss: address=%s city=%s", address, city or AMAP_DEFAULT_CITY)

    payload = _request_amap(
        "/geocode/geo",
        {
            "address": address,
            "city": city or AMAP_DEFAULT_CITY,
        },
    )

    geocodes = payload.get("geocodes", [])
    if not geocodes:
        return None

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


def _parse_photos(photos: Any) -> list[PhotoItem]:
    """解析高德返回的照片列表"""
    result: list[PhotoItem] = []
    if not photos or not isinstance(photos, list):
        return result
    for photo in photos:
        if isinstance(photo, dict) and photo.get("url"):
            # 处理 title 可能是列表的情况
            title_val = photo.get("title")
            if isinstance(title_val, list) and title_val:
                title_val = str(title_val[0])
            elif title_val is not None and not isinstance(title_val, str):
                title_val = str(title_val)
            result.append(PhotoItem(url=photo["url"], title=title_val))
    return result


def _parse_tags(type_str: str | None) -> list[str]:
    """从类型字符串解析标签。"""
    if not type_str:
        return []
    tags = [t.strip() for t in type_str.split("|") if t.strip()]
    return tags


def search_places(
    keyword: str,
    city: str | None = None,
    page_size: int = 5,
    types: str | None = None,
) -> list[dict[str, Any]]:
    """根据关键词搜索 POI。"""
    cache_key = (
        f"map:place:{_normalize_cache_text(keyword)}:{_normalize_cache_text(city or AMAP_DEFAULT_CITY)}:"
        f"{_normalize_cache_text(types)}:{page_size}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info("map place cache hit: keyword=%s city=%s types=%s", keyword, city or AMAP_DEFAULT_CITY, types)
        return cached_value
    logger.info("map place cache miss: keyword=%s city=%s types=%s", keyword, city or AMAP_DEFAULT_CITY, types)

    params = {
        "keywords": keyword,
        "city": city or AMAP_DEFAULT_CITY,
        "offset": page_size,
        "page": 1,
        "extensions": "all",
    }
    if types:
        params["types"] = types

    payload = _request_amap("/place/text", params)

    pois = payload.get("pois", [])
    results: list[dict[str, Any]] = []
    for poi in pois:
        latitude, longitude = _split_location(poi.get("location"))
        photos = _parse_photos(poi.get("photos"))
        first_photo_url = photos[0].url if photos else None
        
        # 提取评分
        rating = None
        biz_ext = poi.get("biz_ext") or {}
        if isinstance(biz_ext, dict):
            rating_str = biz_ext.get("rating")
            if rating_str:
                try:
                    rating = float(rating_str)
                except (ValueError, TypeError):
                    pass
        
        # 处理营业时间
        opening_hours = None
        if isinstance(biz_ext, dict):
            opening_hours = biz_ext.get("time")
            if isinstance(opening_hours, list) and opening_hours:
                opening_hours = str(opening_hours[0])
            elif opening_hours is not None and not isinstance(opening_hours, str):
                opening_hours = str(opening_hours)
        
        # 处理电话
        phone = poi.get("tel")
        if isinstance(phone, list) and phone:
            phone = str(phone[0])
        elif phone is not None and not isinstance(phone, str):
            phone = str(phone)
        
        # 处理网站
        website = poi.get("website")
        if isinstance(website, list) and website:
            website = str(website[0])
        elif website is not None and not isinstance(website, str):
            website = str(website)

        results.append(
            {
                "name": poi.get("name"),
                "address": poi.get("address"),
                "cityname": poi.get("cityname"),
                "adname": poi.get("adname"),
                "type": poi.get("type"),
                "poi_id": poi.get("id"),
                "image_url": first_photo_url,
                "images": [p.model_dump() for p in photos],
                "latitude": latitude,
                "longitude": longitude,
                "rating": rating,
                "opening_hours": opening_hours,
                "phone": phone,
                "website": website,
                "tags": _parse_tags(poi.get("type")),
            }
        )

    set_cached_json(cache_key, results, expire_seconds=REDIS_MAP_TTL_SECONDS)
    return results


def search_restaurants(
    keyword: str,
    city: str | None = None,
    page_size: int = 5,
) -> list[dict[str, Any]]:
    """搜索餐厅。"""
    return search_places(keyword, city, page_size, types="050000|050100|050200|050300")


def search_hotels(
    keyword: str,
    city: str | None = None,
    page_size: int = 5,
) -> list[dict[str, Any]]:
    """搜索酒店/民宿。"""
    return search_places(keyword, city, page_size, types="100000|100100|100200")


def search_attractions(
    keyword: str,
    city: str | None = None,
    page_size: int = 5,
) -> list[dict[str, Any]]:
    """搜索景点。"""
    return search_places(keyword, city, page_size, types="110000|110100|110200|110300")


def estimate_route(
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
) -> dict[str, Any] | None:
    """估算两点之间的驾车距离和耗时。"""
    cache_key = (
        "map:route:"
        f"{origin_longitude:.6f},{origin_latitude:.6f}:"
        f"{destination_longitude:.6f},{destination_latitude:.6f}"
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info(
            "map route cache hit: origin=%s,%s destination=%s,%s",
            origin_longitude,
            origin_latitude,
            destination_longitude,
            destination_latitude,
        )
        return cached_value
    logger.info(
        "map route cache miss: origin=%s,%s destination=%s,%s",
        origin_longitude,
        origin_latitude,
        destination_longitude,
        destination_latitude,
    )

    payload = _request_amap(
        "/direction/driving",
        {
            "origin": f"{origin_longitude},{origin_latitude}",
            "destination": f"{destination_longitude},{destination_latitude}",
            "strategy": 0,
        },
    )

    route = payload.get("route", {})
    paths = route.get("paths", [])
    if not paths:
        return None

    first_path = paths[0]
    distance_meters = _parse_float(first_path.get("distance"))
    duration_seconds = _parse_float(first_path.get("duration"))

    result = {
        "distance_meters": distance_meters,
        "distance_km": round(distance_meters / 1000, 2) if distance_meters is not None else None,
        "duration_seconds": duration_seconds,
        "estimated_minutes": round(duration_seconds / 60) if duration_seconds is not None else None,
        "taxi_cost": _parse_float(route.get("taxi_cost")),
    }
    set_cached_json(cache_key, result, expire_seconds=REDIS_MAP_TTL_SECONDS)
    return result


def _pick_best_place(keyword: str, city: str | None = None) -> dict[str, Any] | None:
    """优先从 POI 搜索里选取第一条结果（需通过城市名校验）。"""
    results = search_places(keyword=keyword, city=city, page_size=1)
    for r in results:
        if _is_poi_in_city(r, city):
            return r
    return None


def _is_poi_in_city(place: dict[str, Any] | None, city: str | None) -> bool:
    """校验 POI 搜索结果是否属于目标城市，防止跨城市错误匹配。"""
    if not place or not city:
        return True  # 无 city 参数时不限制
    city = city.strip()
    poi_city = (place.get("cityname") or "").strip()
    poi_adname = (place.get("adname") or "").strip()
    # 目标城市名或其所属行政区名出现在 POI 的城市/区县字段中
    if city in poi_city or city in poi_adname or poi_city in city or poi_adname in city:
        return True
    return False


def _enrich_spot(spot: SpotItem, city: str | None = None) -> bool:
    """补全单个景点的地址、经纬度和 POI 信息。"""
    places = search_attractions(spot.name, city=city, page_size=1)
    place = places[0] if places else None
    # 城市名校验：确保搜索结果属于目标城市
    if place and not _is_poi_in_city(place, city):
        logger.debug(
            f"景点'{spot.name}'搜索结果城市不匹配: "
            f"期望={city}, 实际cityname={place.get('cityname')}, adname={place.get('adname')}"
        )
        place = None
    if place is None and spot.location:
        places = search_attractions(spot.location, city=city, page_size=1)
        place = places[0] if places else None
        if place and not _is_poi_in_city(place, city):
            place = None
    if place is None:
        places = search_places(spot.name, city=city, page_size=1)
        place = places[0] if places else None
        if place and not _is_poi_in_city(place, city):
            place = None

    if place is None:
        query_address = spot.address or spot.location or spot.name
        geocode = geocode_address(query_address, city=city)
        if geocode is None:
            return False
        # 地理编码结果也需要校验地址是否包含目标城市
        formatted_addr = (geocode.get("formatted_address") or "").strip()
        if city and city.strip() not in formatted_addr:
            logger.debug(
                f"景点'{spot.name}'地理编码地址不包含目标城市: "
                f"期望={city}, 地址={formatted_addr}"
            )
            return False
        spot.address = geocode.get("formatted_address") or spot.address
        spot.latitude = geocode.get("latitude")
        spot.longitude = geocode.get("longitude")
        return True

    spot.address = place.get("address") or spot.address
    spot.image_url = place.get("image_url") or spot.image_url
    spot.latitude = place.get("latitude")
    spot.longitude = place.get("longitude")
    spot.poi_id = place.get("poi_id") or spot.poi_id
    spot.rating = place.get("rating")
    spot.opening_hours = place.get("opening_hours")
    spot.phone = place.get("phone")
    spot.website = place.get("website")
    spot.tags = place.get("tags", [])
    spot.cityname = place.get("cityname")
    spot.adname = place.get("adname")
    # 解析图片列表
    images_data = place.get("images", [])
    spot.images = [PhotoItem(**img) for img in images_data]
    return True


def _enrich_meal(meal: MealItem, city: str | None = None) -> bool:
    """补全单个餐饮的地址、经纬度和 POI 信息。"""
    places = search_restaurants(meal.name, city=city, page_size=1)
    place = places[0] if places else None
    if place and not _is_poi_in_city(place, city):
        place = None
    if place is None:
        places = search_places(meal.name, city=city, page_size=1)
        place = places[0] if places else None
        if place and not _is_poi_in_city(place, city):
            place = None

    if place is None:
        return False

    meal.address = place.get("address")
    meal.image_url = place.get("image_url")
    meal.latitude = place.get("latitude")
    meal.longitude = place.get("longitude")
    meal.poi_id = place.get("poi_id")
    meal.rating = place.get("rating")
    meal.opening_hours = place.get("opening_hours")
    meal.phone = place.get("phone")
    meal.website = place.get("website")
    meal.tags = place.get("tags", [])
    meal.cityname = place.get("cityname")
    meal.adname = place.get("adname")
    # 解析图片列表
    images_data = place.get("images", [])
    meal.images = [PhotoItem(**img) for img in images_data]
    # 从标签中提取菜系
    meal.cuisine = [t for t in meal.tags if "菜" in t or "料理" in t or "火锅" in t]
    return True


def _enrich_hotel(hotel: HotelItem, city: str | None = None) -> bool:
    """补全单个酒店的地址和经纬度。"""
    # 搜索策略1：用酒店名称精确搜索
    places = search_hotels(hotel.name, city=city, page_size=1)
    place = places[0] if places else None
    if place and not _is_poi_in_city(place, city):
        place = None

    # 搜索策略2：如果名称是模板名（含"住宿"），用城市+档次关键词搜索
    if place is None and hotel.name and "住宿" in hotel.name:
        level_keywords = {
            "豪华": "五星级酒店",
            "高档": "四星级酒店 精品酒店",
            "舒适型": "酒店 宾馆",
            "经济": "快捷酒店 经济型",
        }
        level = hotel.level or "舒适型"
        keyword = level_keywords.get(level, "酒店 宾馆")
        places = search_hotels(keyword, city=city, page_size=3)
        # 取第一个通过城市校验的结果
        for p in places:
            if _is_poi_in_city(p, city):
                place = p
                break

    # 搜索策略3：用位置文本搜索
    if place is None and hotel.location:
        places = search_hotels(hotel.location, city=city, page_size=1)
        place = places[0] if places else None
        if place and not _is_poi_in_city(place, city):
            place = None

    # 搜索策略4：通用地点搜索
    if place is None:
        places = search_places(hotel.name, city=city, page_size=1)
        place = places[0] if places else None
        if place and not _is_poi_in_city(place, city):
            place = None

    if place is None:
        query_address = hotel.address or hotel.location or hotel.name
        geocode = geocode_address(query_address, city=city)
        if geocode is None:
            return False
        formatted_addr = (geocode.get("formatted_address") or "").strip()
        if city and city.strip() not in formatted_addr:
            return False
        hotel.address = geocode.get("formatted_address") or hotel.address
        hotel.latitude = geocode.get("latitude")
        hotel.longitude = geocode.get("longitude")
        return True

    # 用真实POI数据覆盖模板字段（包括名称）
    if place.get("name") and (not hotel.name or "住宿" in hotel.name):
        # 只有当当前名称为空或是模板名称时才替换（含"住宿"的视为模板）
        hotel.name = place.get("name")
    hotel.address = place.get("address") or hotel.address
    hotel.image_url = place.get("image_url")
    hotel.latitude = place.get("latitude")
    hotel.longitude = place.get("longitude")
    hotel.poi_id = place.get("poi_id")
    hotel.rating = place.get("rating")
    hotel.opening_hours = place.get("opening_hours")
    hotel.phone = place.get("phone")
    hotel.website = place.get("website")
    hotel.tags = place.get("tags", [])
    hotel.cityname = place.get("cityname")
    hotel.adname = place.get("adname")
    # 解析图片列表
    images_data = place.get("images", [])
    hotel.images = [PhotoItem(**img) for img in images_data]
    # 从标签中提取设施
    hotel.facilities = [t for t in hotel.tags if "wifi" in t.lower() or "停车场" in t or "早餐" in t]
    return True


def _geocode_place_text(place_text: str | None, city: str | None = None) -> dict[str, Any] | None:
    """把文本地点尽量解析成带经纬度的结果。"""
    if not place_text:
        return None

    place = _pick_best_place(place_text, city=city)
    if place is not None:
        return {
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "address": place.get("address"),
        }

    geocode = geocode_address(place_text, city=city)
    if geocode is not None:
        return {
            "latitude": geocode.get("latitude"),
            "longitude": geocode.get("longitude"),
            "address": geocode.get("formatted_address"),
        }
    return None


def _enrich_transport(transport: TransportItem, city: str | None = None) -> bool:
    """补全单段交通的距离和耗时信息。"""
    origin = _geocode_place_text(transport.from_place, city=city)
    destination = _geocode_place_text(transport.to_place, city=city)
    if not origin or not destination:
        return False

    if origin.get("latitude") is None or origin.get("longitude") is None:
        return False
    if destination.get("latitude") is None or destination.get("longitude") is None:
        return False

    route = estimate_route(
        origin_longitude=origin["longitude"],
        origin_latitude=origin["latitude"],
        destination_longitude=destination["longitude"],
        destination_latitude=destination["latitude"],
    )
    if route is None:
        return False

    transport.distance_km = route.get("distance_km")
    transport.estimated_minutes = route.get("estimated_minutes")
    if route.get("estimated_minutes") is not None and not transport.duration:
        transport.duration = f"{route['estimated_minutes']} 分钟"
    return True


def enrich_itinerary_with_map_data(itinerary: Itinerary, city: str | None = None) -> Itinerary:
    """使用高德服务补全 itinerary 里的地图字段。"""
    enriched_count = 0

    for day in itinerary.days:
        for spot in day.spots:
            try:
                if _enrich_spot(spot, city=city or itinerary.destination):
                    enriched_count += 1
            except Exception:
                continue

        for meal in day.meals:
            try:
                if _enrich_meal(meal, city=city or itinerary.destination):
                    enriched_count += 1
            except Exception:
                continue

        if day.hotel is not None:
            try:
                if _enrich_hotel(day.hotel, city=city or itinerary.destination):
                    enriched_count += 1
            except Exception:
                pass

        for transport in day.transport:
            try:
                if _enrich_transport(transport, city=city or itinerary.destination):
                    enriched_count += 1
            except Exception:
                continue

    if enriched_count > 0:
        note = "已补充高德地图地址、坐标、商户信息或路线估算信息。"
        if note not in itinerary.source_notes:
            itinerary.source_notes.append(note)

    return itinerary
