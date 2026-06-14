from __future__ import annotations

import logging
import re
from typing import Dict, Optional

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


def _parse_meal_price(text: str) -> Optional[float]:
    """从文本中提取餐饮人均价格"""
    text = text.strip()

    # 匹配带 ** 标记的价格区间，如 "**60-80元**" 或 "**120元**"
    # 优先匹配"人均预算约 **XX元**"、"人均预算 **XX-YY元**" 等格式
    patterns = [
        # 人均预算约 **120元** / 人均预算 **60-80元**
        r'人均预算[约\s]*\*{2}\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*\*{2}\s*元',
        r'人均预算[约\s]*\*{2}\s*(\d+(?:\.\d+)?)\s*\*{2}\s*元',
        # 人均预算约80-150元 / 人均预算约80元（无星号）
        r'人均预算[约\s]*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*元',
        r'人均预算[约\s]*(\d+(?:\.\d+)?)\s*元',
        # 独立的 **5-8元** / **15-20元**
        r'\*{2}\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*\*{2}\s*元',
        r'\*{2}\s*(\d+(?:\.\d+)?)\s*\*{2}\s*元',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                if match.lastindex is not None and match.lastindex >= 2 and match.group(2) is not None:
                    # 区间价格，取中间值
                    low = float(match.group(1))
                    high = float(match.group(2))
                    return round((low + high) / 2, 1)
                else:
                    # 单一价格
                    return float(match.group(1))
            except (ValueError, IndexError):
                continue

    return None


def _find_meal_section(text: str, spot_name: str) -> Optional[str]:
    """查找景点标题后面的美食相关段落"""
    lines = text.split('\n')
    start_idx = None

    for i, line in enumerate(lines):
        if spot_name in line:
            start_idx = i
            break

    if start_idx is None:
        return None

    # 提取从标题之后到下一个 ### X.X 段落结束的内容
    section_lines = []
    for i in range(start_idx + 1, min(start_idx + 15, len(lines))):
        line = lines[i]
        if re.match(r'###\s*\d+\.\d+', line):
            break
        section_lines.append(line)

    return '\n'.join(section_lines)


def _extract_from_local_file(destination: str) -> Dict[str, float]:
    """直接从本地攻略文件中提取餐饮人均价格"""
    meal_map: Dict[str, float] = {}

    filename = CITY_FILE_MAP.get(destination)
    if not filename:
        return meal_map

    file_path = f"{DATA_DIR}/{filename}"

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 匹配所有景点/段落标题：### X.X 标题名
        section_pattern = r'###\s*\d+\.\d+\s+([^\n]+)'
        sections = re.findall(section_pattern, content)

        for section_name in sections:
            section_text = _find_meal_section(content, section_name)
            if not section_text:
                continue

            # 在段落中查找包含"人均预算"或价格标记的美食行
            for line in section_text.split('\n'):
                line = line.strip()
                if not line or not re.search(r'人均预算|[\d]+.*元', line):
                    continue

                price = _parse_meal_price(line)
                if price is not None:
                    # 尝试从行首提取餐饮名称（取第一个非空格非*字符到冒号或价格前）
                    meal_name = _extract_meal_name(line)
                    if meal_name:
                        meal_map[meal_name] = price
                        logger.debug(f"从本地文件提取餐饮价格: {meal_name} = {price}元")

    except Exception as e:
        logger.debug(f"从本地文件提取餐饮价格失败: {e}")

    return meal_map


def _extract_meal_name(line: str) -> Optional[str]:
    """从包含价格的文本行中提取餐饮名称"""
    # 移除 Markdown 加粗标记
    cleaned = re.sub(r'\*{2}', '', line).strip()

    # 匹配类似 "美食名称：人均预算..." 或 "美食名称 人均预算..."
    name_match = re.match(r'^([^：:\n\d]+?)(?:[：:]\s*)?(?:人均预算|$)', cleaned)
    if name_match:
        name = name_match.group(1).strip()
        # 过滤掉过短或无意义的名称
        if len(name) >= 2 and name not in ('', '-', '—'):
            return name

    return None


def extract_meal_prices(destination: str) -> Dict[str, float]:
    """从攻略文档中提取指定目的地的所有餐饮人均价格信息

    Args:
        destination: 目的地城市名称

    Returns:
        餐饮名称到人均价格的映射字典 {餐饮名称: 人均价格}
    """
    meal_map: Dict[str, float] = {}

    # 从本地文件读取
    meal_map = _extract_from_local_file(destination)

    logger.info(f"从攻略文档提取餐饮价格完成，共 {len(meal_map)} 条记录，目的地: {destination}")
    return meal_map


def get_meal_price(meal_name: str, destination: str, meal_price_map: Optional[Dict[str, float]] = None) -> float:
    """
    获取单个餐饮的人均价格

    优先级：
    1. 从已有的meal_price_map中精确匹配
    2. 从meal_price_map中模糊匹配（子串包含）
    3. 回退到基于关键词的估算

    Args:
        meal_name: 餐饮名称
        destination: 目的地城市
        meal_price_map: 已有的餐饮价格映射（可选）

    Returns:
        人均价格（元）
    """
    if meal_price_map is None:
        meal_price_map = extract_meal_prices(destination)

    # 1. 精确匹配
    if meal_name in meal_price_map:
        return meal_price_map[meal_name]

    # 2. 模糊匹配
    normalized = meal_name.strip()
    for name, price in meal_price_map.items():
        if normalized in name or name in normalized:
            logger.debug(f"餐饮价格模糊匹配: '{meal_name}' → '{name}' = {price}元")
            return price

    # 3. 回退估算
    fallback = _fallback_estimate_meal_price(meal_name)
    logger.debug(f"餐饮价格回退估算: {meal_name} ≈ {fallback}元")
    return fallback


def _fallback_estimate_meal_price(meal_name: str) -> float:
    """基于关键词的餐饮人均价格估算（作为最后的回退）"""
    text = meal_name

    # 街头小吃 / 特色小吃类
    if any(keyword in text for keyword in (
        "街头小吃", "特色小吃", "粑粑", "米粉", "米线", "面条", "豆花",
        "凉皮", "抄手", "馄饨", "包子", "馒头", "烧饼", "烤串", "煎饼",
        "臭豆腐", "糖油粑粑", "凉粉", "酸辣粉", "小面"
    )):
        import random
        return round(random.uniform(5, 20), 1)

    # 正餐 / 火锅 / 炒菜类
    if any(keyword in text for keyword in (
        "火锅", "炒菜", "鱼头", "小龙虾", "海鲜", "川菜", "湘菜",
        "粤菜", "本帮菜", "农家乐", "土菜", "私房菜", "烧烤", "烤鱼"
    )):
        import random
        return round(random.uniform(60, 150), 1)

    # 高端料理类
    if any(keyword in text for keyword in (
        "烤鸭", "高端料理", "米其林", "法餐", "日料", "怀石料理"
    )):
        import random
        return round(random.uniform(150, 300), 1)

    # 默认估算
    return 40.0
