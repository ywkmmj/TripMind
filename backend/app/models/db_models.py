from datetime import datetime

from sqlalchemy import DateTime, String, Text, Float, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.config import Base


class TripRecord(Base):
    """当前版本使用的最小行程表。"""

    __tablename__ = "trip_records"

    # 数据库内部主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 业务侧使用的 itinerary 标识
    trip_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    destination: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    # 完整 itinerary 的 JSON 字符串
    itinerary_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class CitySpecificTip(Base):
    """城市特定提示规则表。"""

    __tablename__ = "city_specific_tips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_name: Mapped[str] = mapped_column(String(100), index=True)
    tip_text: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WeatherTipTemplate(Base):
    """天气提示模板规则表。"""

    __tablename__ = "weather_tip_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    weather_keyword: Mapped[str] = mapped_column(String(50), index=True)
    tip_text: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AttractionTypeTip(Base):
    """景点类型提示规则表。"""

    __tablename__ = "attraction_type_tips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attraction_type: Mapped[str] = mapped_column(String(50), index=True)
    tip_text: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AttractionKeyword(Base):
    """景点关键词规则表。"""

    __tablename__ = "attraction_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attraction_type: Mapped[str] = mapped_column(String(50), index=True)
    keyword: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TicketPriceRule(Base):
    """门票价格估算规则表。"""

    __tablename__ = "ticket_price_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category_name: Mapped[str] = mapped_column(String(100), index=True)
    keywords: Mapped[str] = mapped_column(Text)  # 逗号分隔的关键词
    base_price: Mapped[float] = mapped_column(Float)
    price_variance: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DemoSpotName(Base):
    """演示景点名称规则表。"""

    __tablename__ = "demo_spot_names"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_name: Mapped[str] = mapped_column(String(100), index=True)
    spot_name: Mapped[str] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CityFilterKeyword(Base):
    """城市过滤关键词规则表。"""

    __tablename__ = "city_filter_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    city_name: Mapped[str] = mapped_column(String(100), index=True)
    keyword: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GenericTip(Base):
    """通用提示规则表。"""

    __tablename__ = "generic_tips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tip_text: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TechnicalTipKeyword(Base):
    """技术提示关键词规则表。"""

    __tablename__ = "technical_tip_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
