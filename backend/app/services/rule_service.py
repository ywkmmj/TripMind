"""
规则加载服务
支持从配置文件和数据库读取规则
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import SessionLocal
from app.models.db_models import (
    CitySpecificTip, WeatherTipTemplate, AttractionTypeTip,
    AttractionKeyword, TicketPriceRule, DemoSpotName,
    CityFilterKeyword, GenericTip, TechnicalTipKeyword
)
from app.rules.travel_tips import (
    CITY_SPECIFIC_TIPS, WEATHER_TIP_TEMPLATES, ATTRACTION_TYPE_TIPS,
    ATTRACTION_KEYWORDS, CITY_FILTER_KEYWORDS, GENERIC_TIPS,
    TECHNICAL_TIP_KEYWORDS, TICKET_PRICE_RULES, DEFAULT_TICKET_PRICE,
    DEMO_SPOT_NAMES, CITY_DYNAMIC_TIPS
)

logger = logging.getLogger(__name__)


class RuleService:
    """规则服务类，提供统一的规则访问接口"""

    def __init__(self, use_database: bool = False):
        self.use_database = use_database
        self._db: Optional[Session] = None

    def _get_db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def close(self):
        if self._db:
            self._db.close()
            self._db = None

    # 城市特定提示
    def get_city_specific_tips(self, city_name: str) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                tips = db.query(CitySpecificTip).filter(
                    CitySpecificTip.city_name == city_name,
                    CitySpecificTip.is_active == True
                ).order_by(CitySpecificTip.priority).all()
                return [tip.tip_text for tip in tips]
            except Exception as e:
                logger.warning(f"从数据库读取城市提示失败: {e}, 回退到配置文件")
        return CITY_SPECIFIC_TIPS.get(city_name, [])

    # 天气提示模板
    def get_weather_tip_templates(self, weather_keyword: str) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                templates = db.query(WeatherTipTemplate).filter(
                    WeatherTipTemplate.weather_keyword == weather_keyword,
                    WeatherTipTemplate.is_active == True
                ).order_by(WeatherTipTemplate.priority).all()
                return [template.tip_text for template in templates]
            except Exception as e:
                logger.warning(f"从数据库读取天气模板失败: {e}, 回退到配置文件")
        return WEATHER_TIP_TEMPLATES.get(weather_keyword, [])

    # 获取所有天气关键词
    def get_all_weather_keywords(self) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                keywords = db.query(WeatherTipTemplate.weather_keyword).filter(
                    WeatherTipTemplate.is_active == True
                ).distinct().all()
                return [kw[0] for kw in keywords]
            except Exception as e:
                logger.warning(f"从数据库读取天气关键词失败: {e}, 回退到配置文件")
        return list(WEATHER_TIP_TEMPLATES.keys())

    # 景点类型提示
    def get_attraction_type_tips(self, attraction_type: str) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                tips = db.query(AttractionTypeTip).filter(
                    AttractionTypeTip.attraction_type == attraction_type,
                    AttractionTypeTip.is_active == True
                ).order_by(AttractionTypeTip.priority).all()
                return [tip.tip_text for tip in tips]
            except Exception as e:
                logger.warning(f"从数据库读取景点类型提示失败: {e}, 回退到配置文件")
        return ATTRACTION_TYPE_TIPS.get(attraction_type, [])

    # 景点关键词映射
    def get_attraction_keywords(self) -> Dict[str, List[str]]:
        if self.use_database:
            try:
                db = self._get_db()
                keywords = db.query(AttractionKeyword).filter(
                    AttractionKeyword.is_active == True
                ).all()
                result: Dict[str, List[str]] = {}
                for kw in keywords:
                    if kw.attraction_type not in result:
                        result[kw.attraction_type] = []
                    result[kw.attraction_type].append(kw.keyword)
                return result
            except Exception as e:
                logger.warning(f"从数据库读取景点关键词失败: {e}, 回退到配置文件")
        return ATTRACTION_KEYWORDS

    # 门票价格规则
    def get_ticket_price_rules(self) -> List[Dict]:
        if self.use_database:
            try:
                db = self._get_db()
                rules = db.query(TicketPriceRule).filter(
                    TicketPriceRule.is_active == True
                ).all()
                return [
                    {
                        "category": rule.category_name,
                        "keywords": rule.keywords.split(","),
                        "base_price": rule.base_price,
                        "price_variance": rule.price_variance
                    }
                    for rule in rules
                ]
            except Exception as e:
                logger.warning(f"从数据库读取门票价格规则失败: {e}, 回退到配置文件")
        return TICKET_PRICE_RULES

    # 默认门票价格
    def get_default_ticket_price(self) -> Dict:
        return DEFAULT_TICKET_PRICE

    # 演示景点名称
    def get_demo_spot_names(self, city_name: str) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                spots = db.query(DemoSpotName).filter(
                    DemoSpotName.city_name == city_name,
                    DemoSpotName.is_active == True
                ).order_by(DemoSpotName.priority).all()
                return [spot.spot_name for spot in spots]
            except Exception as e:
                logger.warning(f"从数据库读取演示景点名称失败: {e}, 回退到配置文件")
        return DEMO_SPOT_NAMES.get(city_name, [])

    # 城市过滤关键词
    def get_city_filter_keywords(self) -> Dict[str, List[str]]:
        if self.use_database:
            try:
                db = self._get_db()
                keywords = db.query(CityFilterKeyword).filter(
                    CityFilterKeyword.is_active == True
                ).all()
                result: Dict[str, List[str]] = {}
                for kw in keywords:
                    if kw.city_name not in result:
                        result[kw.city_name] = []
                    result[kw.city_name].append(kw.keyword)
                return result
            except Exception as e:
                logger.warning(f"从数据库读取城市过滤关键词失败: {e}, 回退到配置文件")
        return CITY_FILTER_KEYWORDS

    # 通用提示
    def get_generic_tips(self) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                tips = db.query(GenericTip).filter(
                    GenericTip.is_active == True
                ).order_by(GenericTip.priority).all()
                return [tip.tip_text for tip in tips]
            except Exception as e:
                logger.warning(f"从数据库读取通用提示失败: {e}, 回退到配置文件")
        return GENERIC_TIPS

    # 技术提示关键词
    def get_technical_tip_keywords(self) -> List[str]:
        if self.use_database:
            try:
                db = self._get_db()
                keywords = db.query(TechnicalTipKeyword).filter(
                    TechnicalTipKeyword.is_active == True
                ).all()
                return [kw.keyword for kw in keywords]
            except Exception as e:
                logger.warning(f"从数据库读取技术提示关键词失败: {e}, 回退到配置文件")
        return list(TECHNICAL_TIP_KEYWORDS)

    # 城市动态提示
    def get_city_dynamic_tips(self, city_name: str) -> Optional[Dict]:
        return CITY_DYNAMIC_TIPS.get(city_name)


# 全局规则服务实例（默认使用配置文件）
_rule_service_instance: Optional[RuleService] = None


def get_rule_service(use_database: bool = False) -> RuleService:
    """获取规则服务单例"""
    global _rule_service_instance
    if _rule_service_instance is None or _rule_service_instance.use_database != use_database:
        if _rule_service_instance:
            _rule_service_instance.close()
        _rule_service_instance = RuleService(use_database=use_database)
    return _rule_service_instance
