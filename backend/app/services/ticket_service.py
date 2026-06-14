from __future__ import annotations

import logging
import re
from typing import Dict, Optional

from app.rag.retriever import retrieve_travel_guide_chunks

logger = logging.getLogger(__name__)

# 城市名称到文件名的映射
CITY_FILE_MAP = {
    "长沙": "changsha_guide.md",
    "成都": "chengdu_guide.md",
    "杭州": "hangzhou_guide.md",
    "重庆": "chongqing_guide.md",
    "北京": "beijing_guide.md",
    "大理": "dali_guide.md",
    "三亚": "sanya_guide.md",
    "厦门": "xiamen_guide.md",
    "西安": "xian_guide.md",
}

DATA_DIR = "E:/github-project-001/zhilv-yuntu-main/backend/data"


class TicketInfo:
    """景点门票信息"""
    def __init__(self, spot_name: str, price: float, description: str = ""):
        self.spot_name = spot_name
        self.price = price
        self.description = description


def _parse_ticket_price(text: str) -> Optional[float]:
    """从文本中提取门票价格"""
    text = text.strip()
    
    # 优先检查免费情况（包括"* **门票**：免费"、"免费（需预约）"等格式）
    free_patterns = [
        r'门票[^：:]*[：:]\s*免费',  # 匹配"门票**：免费"这种格式
        r'门票\s*免费',
        r'免费\s*\（',  # 免费（需预约）
        r'免费\s*\(',   # 免费(需预约)
        r'^免费$',
        r'不收门票',
        r'门票免费',
        r'免费参观',
    ]
    
    for pattern in free_patterns:
        if re.search(pattern, text):
            return 0.0
    
    # 匹配 "门票：XX元/人" 格式
    patterns = [
        r'门票[^：:]*[：:]\s*([\d]+(?:\.[\d]+)?)\s*元',  # 匹配"门票**：XX元"格式
        r'门票\s*[：:]?\s*([\d]+(?:\.[\d]+)?)\s*元',
        r'门票\s*[：:]?\s*([\d]+(?:\.[\d]+)?)\s*元/人',
        r'([\d]+(?:\.[\d]+)?)\s*元/人',
        r'([\d]+(?:\.[\d]+)?)\s*元/位',
        r'([\d]+(?:\.[\d]+)?)\s*元起',
        r'([\d]+(?:\.[\d]+)?)\s*元',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    
    return None


def _extract_spot_info_from_chunk(chunk: dict) -> list[TicketInfo]:
    """从单个攻略片段中提取景点信息"""
    results = []
    text = chunk.get("text", "")
    title = chunk.get("title", "")
    
    # 匹配景点标题格式：### 2.1 景点名称
    spot_pattern = r'###\s*\d+\.\d+\s+([^\n]+)'
    spots = re.findall(spot_pattern, text)
    
    for spot_name in spots:
        # 查找该景点对应的门票信息
        spot_section = _find_spot_section(text, spot_name)
        if spot_section:
            price = _parse_ticket_price(spot_section)
            if price is not None:
                results.append(TicketInfo(
                    spot_name=spot_name.strip(),
                    price=price,
                    description=spot_section[:200]
                ))
    
    # 如果标题看起来像景点名称，也尝试提取
    if not spots and "门票" in text:
        price = _parse_ticket_price(text)
        if price is not None:
            results.append(TicketInfo(
                spot_name=title.strip(),
                price=price,
                description=text[:200]
            ))
    
    return results


def _find_spot_section(text: str, spot_name: str) -> Optional[str]:
    """查找景点对应的详细信息段落"""
    lines = text.split('\n')
    start_idx = None
    
    for i, line in enumerate(lines):
        if spot_name in line:
            start_idx = i
            break
    
    if start_idx is None:
        return None
    
    # 提取从景点名称之后到下一个景点或段落结束的内容
    section_lines = []
    # 从 start_idx + 1 开始，跳过标题行
    for i in range(start_idx + 1, min(start_idx + 10, len(lines))):
        line = lines[i]
        # 检查是否是下一个景点标题
        if re.match(r'###\s*\d+\.\d+', line):
            break
        section_lines.append(line)
    
    return '\n'.join(section_lines)


def _extract_from_local_file(destination: str) -> Dict[str, float]:
    """直接从本地攻略文件中提取门票信息"""
    ticket_map: Dict[str, float] = {}
    
    # 获取对应城市的文件名
    filename = CITY_FILE_MAP.get(destination)
    if not filename:
        return ticket_map
    
    file_path = f"{DATA_DIR}/{filename}"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 匹配所有景点标题：### 2.X 景点名称
        spot_pattern = r'###\s*\d+\.\d+\s+([^\n]+)'
        spots = re.findall(spot_pattern, content)
        
        for spot_name in spots:
            # 查找该景点对应的门票信息
            spot_section = _find_spot_section(content, spot_name)
            if spot_section:
                price = _parse_ticket_price(spot_section)
                if price is not None:
                    ticket_map[spot_name.strip()] = price
                    logger.debug(f"从本地文件提取: {spot_name.strip()} = {price}元")
    
    except Exception as e:
        logger.debug(f"从本地文件提取门票信息失败: {e}")
    
    return ticket_map


def extract_ticket_info(destination: str) -> Dict[str, float]:
    """从攻略文档中提取指定目的地的所有景点门票信息"""
    ticket_map: Dict[str, float] = {}
    
    # 首先尝试直接从本地文件读取（更可靠）
    ticket_map = _extract_from_local_file(destination)
    
    # 如果本地文件没有找到，再尝试RAG检索
    if not ticket_map:
        try:
            chunks = retrieve_travel_guide_chunks(
                query=f"{destination} 景点 门票",
                top_k=10,
                destination=destination
            )
            
            for chunk in chunks:
                spot_infos = _extract_spot_info_from_chunk(chunk)
                for info in spot_infos:
                    # 使用规范化的景点名称作为key
                    normalized_name = info.spot_name.strip()
                    ticket_map[normalized_name] = info.price
                    logger.debug(f"提取门票信息: {normalized_name} = {info.price}元")
        except Exception as e:
            logger.error(f"从RAG检索提取门票信息失败: {e}")
    
    return ticket_map


def get_ticket_price(spot_name: str, destination: str, ticket_map: Optional[Dict[str, float]] = None) -> float:
    """
    获取景点的门票价格
    
    优先级：
    1. 从已有的ticket_map中查找（精确匹配）
    2. 从攻略文档中实时检索（模糊匹配）
    3. 从网络获取（高德地图API）
    4. 回退到基于关键词的估算
    
    Args:
        spot_name: 景点名称
        destination: 目的地城市
        ticket_map: 已有的门票映射（可选）
    
    Returns:
        门票价格（元）
    """
    # 如果没有提供ticket_map，先尝试检索
    if ticket_map is None:
        ticket_map = extract_ticket_info(destination)
    
    # 1. 精确匹配
    if spot_name in ticket_map:
        return ticket_map[spot_name]
    
    # 2. 模糊匹配（景点名称可能有不同表述）
    normalized_spot = spot_name.strip()
    for name, price in ticket_map.items():
        if normalized_spot in name or name in normalized_spot:
            return price
    
    # 3. 尝试从网络获取（高德地图API）
    try:
        from app.services.web_spot_service import get_spot_ticket_price_from_web
        web_price = get_spot_ticket_price_from_web(spot_name, destination)
        if web_price is not None:
            logger.info(f"从网络获取门票价格成功: {spot_name} = {web_price}元")
            return web_price
    except Exception as e:
        logger.debug(f"从网络获取门票价格失败: {e}")
    
    # 4. 回退到关键词估算（保持兼容性）
    return _fallback_estimate_price(spot_name)


def _fallback_estimate_price(spot_name: str) -> float:
    """基于关键词的门票估算（作为最后的回退）"""
    text = spot_name
    
    if any(keyword in text for keyword in ("古城", "古镇", "公园", "廊道", "村", "湿地", "街区", "广场", "洲", "街", "步行街")):
        # 免费或低价景点
        return 0.0
    
    if any(keyword in text for keyword in ("寺", "三塔", "博物馆", "遗址", "山庄", "故居")):
        # 中等价格景点
        return 50.0
    
    if any(keyword in text for keyword in ("索道", "缆车", "游船", "演出", "雪山")):
        # 高价景点或活动
        return 120.0
    
    # 默认估算
    return 35.0
