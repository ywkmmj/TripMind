"""
数据库初始化脚本
将配置文件中的规则填充到数据库中
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import engine, Base, SessionLocal
from app.models.db_models import (
    CitySpecificTip, WeatherTipTemplate, AttractionTypeTip,
    AttractionKeyword, TicketPriceRule, DemoSpotName,
    CityFilterKeyword, GenericTip, TechnicalTipKeyword
)
from app.rules.travel_tips import (
    CITY_SPECIFIC_TIPS, WEATHER_TIP_TEMPLATES, ATTRACTION_TYPE_TIPS,
    ATTRACTION_KEYWORDS, CITY_FILTER_KEYWORDS, GENERIC_TIPS,
    TECHNICAL_TIP_KEYWORDS, TICKET_PRICE_RULES, DEMO_SPOT_NAMES
)


def init_database():
    """初始化数据库表并填充数据"""
    print("正在创建数据库表...")
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成！")

    db = SessionLocal()
    try:
        print("\n正在填充城市特定提示...")
        for city, tips in CITY_SPECIFIC_TIPS.items():
            for idx, tip_text in enumerate(tips):
                existing = db.query(CitySpecificTip).filter(
                    CitySpecificTip.city_name == city,
                    CitySpecificTip.tip_text == tip_text
                ).first()
                if not existing:
                    db.add(CitySpecificTip(
                        city_name=city,
                        tip_text=tip_text,
                        priority=idx,
                        is_active=True
                    ))
        db.commit()
        print("城市特定提示填充完成！")

        print("\n正在填充天气提示模板...")
        for weather_keyword, templates in WEATHER_TIP_TEMPLATES.items():
            for idx, tip_text in enumerate(templates):
                existing = db.query(WeatherTipTemplate).filter(
                    WeatherTipTemplate.weather_keyword == weather_keyword,
                    WeatherTipTemplate.tip_text == tip_text
                ).first()
                if not existing:
                    db.add(WeatherTipTemplate(
                        weather_keyword=weather_keyword,
                        tip_text=tip_text,
                        priority=idx,
                        is_active=True
                    ))
        db.commit()
        print("天气提示模板填充完成！")

        print("\n正在填充景点类型提示...")
        for attraction_type, tips in ATTRACTION_TYPE_TIPS.items():
            for idx, tip_text in enumerate(tips):
                existing = db.query(AttractionTypeTip).filter(
                    AttractionTypeTip.attraction_type == attraction_type,
                    AttractionTypeTip.tip_text == tip_text
                ).first()
                if not existing:
                    db.add(AttractionTypeTip(
                        attraction_type=attraction_type,
                        tip_text=tip_text,
                        priority=idx,
                        is_active=True
                    ))
        db.commit()
        print("景点类型提示填充完成！")

        print("\n正在填充景点关键词...")
        for attraction_type, keywords in ATTRACTION_KEYWORDS.items():
            for keyword in keywords:
                existing = db.query(AttractionKeyword).filter(
                    AttractionKeyword.attraction_type == attraction_type,
                    AttractionKeyword.keyword == keyword
                ).first()
                if not existing:
                    db.add(AttractionKeyword(
                        attraction_type=attraction_type,
                        keyword=keyword,
                        is_active=True
                    ))
        db.commit()
        print("景点关键词填充完成！")

        print("\n正在填充门票价格规则...")
        for rule in TICKET_PRICE_RULES:
            existing = db.query(TicketPriceRule).filter(
                TicketPriceRule.category_name == rule["category"]
            ).first()
            if not existing:
                db.add(TicketPriceRule(
                    category_name=rule["category"],
                    keywords=",".join(rule["keywords"]),
                    base_price=rule["base_price"],
                    price_variance=rule["price_variance"],
                    is_active=True
                ))
        db.commit()
        print("门票价格规则填充完成！")

        print("\n正在填充演示景点名称...")
        for city, spots in DEMO_SPOT_NAMES.items():
            for idx, spot_name in enumerate(spots):
                existing = db.query(DemoSpotName).filter(
                    DemoSpotName.city_name == city,
                    DemoSpotName.spot_name == spot_name
                ).first()
                if not existing:
                    db.add(DemoSpotName(
                        city_name=city,
                        spot_name=spot_name,
                        priority=idx,
                        is_active=True
                    ))
        db.commit()
        print("演示景点名称填充完成！")

        print("\n正在填充城市过滤关键词...")
        for city, keywords in CITY_FILTER_KEYWORDS.items():
            for keyword in keywords:
                existing = db.query(CityFilterKeyword).filter(
                    CityFilterKeyword.city_name == city,
                    CityFilterKeyword.keyword == keyword
                ).first()
                if not existing:
                    db.add(CityFilterKeyword(
                        city_name=city,
                        keyword=keyword,
                        is_active=True
                    ))
        db.commit()
        print("城市过滤关键词填充完成！")

        print("\n正在填充通用提示...")
        for idx, tip_text in enumerate(GENERIC_TIPS):
            existing = db.query(GenericTip).filter(
                GenericTip.tip_text == tip_text
            ).first()
            if not existing:
                db.add(GenericTip(
                    tip_text=tip_text,
                    priority=idx,
                    is_active=True
                ))
        db.commit()
        print("通用提示填充完成！")

        print("\n正在填充技术提示关键词...")
        for keyword in TECHNICAL_TIP_KEYWORDS:
            existing = db.query(TechnicalTipKeyword).filter(
                TechnicalTipKeyword.keyword == keyword
            ).first()
            if not existing:
                db.add(TechnicalTipKeyword(
                    keyword=keyword,
                    is_active=True
                ))
        db.commit()
        print("技术提示关键词填充完成！")

        print("\n✅ 数据库初始化完成！")

    except Exception as e:
        print(f"\n❌ 初始化过程出错: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_database()
