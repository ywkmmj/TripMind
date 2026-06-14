"""
网络景点信息获取服务
使用高德地图API搜索景点并获取详细信息
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import httpx

from app.config import AMAP_API_KEY, AMAP_WEB_SEARCH_API_URL

logger = logging.getLogger(__name__)

# 缓存：避免重复请求
_spots_cache: dict[str, dict] = {}
_cache_ttl_seconds = 3600  # 1小时缓存


class WebSpotInfo:
    """网络获取的景点信息"""
    def __init__(
        self,
        name: str,
        address: Optional[str] = None,
        location: Optional[str] = None,  # "经度,纬度"
        ticket_price: Optional[float] = None,
        open_time: Optional[str] = None,
        rating: Optional[float] = None,
        phone: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.name = name
        self.address = address
        self.location = location
        self.ticket_price = ticket_price
        self.open_time = open_time
        self.rating = rating
        self.phone = phone
        self.description = description


def _parse_amap_price(price_str: Optional[str]) -> Optional[float]:
    """解析高德地图返回的价格字符串"""
    if not price_str:
        return None
    
    try:
        # 尝试直接转换为数字
        return float(price_str)
    except ValueError:
        pass
    
    # 处理"免费"等文字
    if "免费" in price_str or "无" in price_str:
        return 0.0
    
    # 尝试提取数字
    import re
    numbers = re.findall(r'[\d.]+', price_str)
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            pass
    
    return None


def search_spot_on_amap(
    spot_name: str,
    city: Optional[str] = None,
    max_retries: int = 2,
    retry_delay: float = 0.5,
) -> Optional[WebSpotInfo]:
    """
    在高德地图上搜索景点信息
    
    Args:
        spot_name: 景点名称
        city: 城市名称（可选）
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
    
    Returns:
        WebSpotInfo对象，失败返回None
    """
    # 检查缓存
    cache_key = f"{city or ''}:{spot_name}"
    if cache_key in _spots_cache:
        cached = _spots_cache[cache_key]
        if time.time() - cached.get("_cached_at", 0) < _cache_ttl_seconds:
            logger.debug(f"使用缓存的景点信息: {spot_name}")
            return _cache_to_spot_info(cached)
    
    # 如果没有API Key，尝试使用Web搜索作为备选
    if not AMAP_API_KEY:
        logger.warning("高德地图API Key未配置，无法进行网络搜索")
        return None
    
    # 构建搜索关键词
    keywords = [spot_name]
    if city:
        keywords.append(city)
    keywords_str = "|".join(keywords)
    
    params = {
        "key": AMAP_API_KEY,
        "keywords": keywords_str,
        "types": "风景名胜|博物馆|公园|广场|寺庙|古镇|建筑",
        "city": city or "全国",
        "citylimit": "false",
        "offset": 1,
        "page": 1,
        "extensions": "all",
    }
    
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(AMAP_WEB_SEARCH_API_URL, params=params)
            
            if response.status_code != 200:
                logger.warning(f"高德地图API请求失败: {response.status_code}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
            
            data = response.json()
            
            # 检查API响应状态
            if data.get("status") != "1":
                logger.warning(f"高德地图API返回错误: {data.get('info', '未知错误')}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
            
            pois = data.get("pois", [])
            if not pois:
                logger.debug(f"高德地图未找到景点: {spot_name}")
                # 缓存空结果
                _spots_cache[cache_key] = {"_cached_at": time.time(), "name": spot_name}
                return None
            
            # 取第一个结果
            poi = pois[0]
            
            # 解析价格信息
            ticket_info = poi.get("ticket", "")
            ticket_price = _parse_amap_price(ticket_info)
            
            spot_info = WebSpotInfo(
                name=poi.get("name", spot_name),
                address=poi.get("address"),
                location=poi.get("location"),
                ticket_price=ticket_price,
                open_time=poi.get("opendata"),
                rating=float(poi.get("biz_r.ext.flags.b_002", 0)) if poi.get("biz_r.ext.flags.b_002") else None,
                phone=poi.get("tel"),
                description=poi.get("biz_ext", {}).get("intro") if poi.get("biz_ext") else None,
            )
            
            # 缓存结果
            result_dict = {
                "name": spot_info.name,
                "address": spot_info.address,
                "location": spot_info.location,
                "ticket_price": spot_info.ticket_price,
                "open_time": spot_info.open_time,
                "rating": spot_info.rating,
                "phone": spot_info.phone,
                "description": spot_info.description,
                "_cached_at": time.time(),
            }
            _spots_cache[cache_key] = result_dict
            
            logger.info(f"从高德地图获取景点信息成功: {spot_name}, 票价: {ticket_price}")
            return spot_info
            
        except httpx.TimeoutException:
            logger.warning(f"高德地图API请求超时: {spot_name}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
        except Exception as e:
            logger.error(f"高德地图API请求异常: {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
    
    return None


def _cache_to_spot_info(cache_dict: dict) -> Optional[WebSpotInfo]:
    """从缓存字典创建WebSpotInfo对象"""
    if "name" in cache_dict and len(cache_dict) == 1:
        return None
    
    return WebSpotInfo(
        name=cache_dict.get("name"),
        address=cache_dict.get("address"),
        location=cache_dict.get("location"),
        ticket_price=cache_dict.get("ticket_price"),
        open_time=cache_dict.get("open_time"),
        rating=cache_dict.get("rating"),
        phone=cache_dict.get("phone"),
        description=cache_dict.get("description"),
    )


def get_spot_ticket_price_from_web(
    spot_name: str,
    city: Optional[str] = None,
) -> Optional[float]:
    """
    从网络获取景点门票价格
    
    Args:
        spot_name: 景点名称
        city: 城市名称（可选）
    
    Returns:
        门票价格，失败返回None
    """
    spot_info = search_spot_on_amap(spot_name, city)
    if spot_info:
        return spot_info.ticket_price
    return None


def clear_spots_cache():
    """清除景点缓存"""
    global _spots_cache
    _spots_cache.clear()
    logger.info("景点缓存已清除")
