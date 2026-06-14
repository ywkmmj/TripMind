import json

from app.config import SessionLocal, engine
from app.models.db_models import TripRecord
from app.models.schemas import Itinerary, TripDetailResponse, TripListResponse, TripSummaryItem


def init_db() -> None:
    """初始化数据库表结构。"""
    from app.config import Base

    Base.metadata.create_all(bind=engine)


def save_itinerary(itinerary: Itinerary) -> str:
    """保存或更新完整 itinerary，并返回 trip_id。"""
    init_db()

    session = SessionLocal()
    try:
        itinerary_json = json.dumps(
            itinerary.model_dump(mode="json"),
            ensure_ascii=False,
        )

        existing_record = (
            session.query(TripRecord)
            .filter(TripRecord.trip_id == itinerary.trip_id)
            .first()
        )

        if existing_record is None:
            record = TripRecord(
                trip_id=itinerary.trip_id,
                destination=itinerary.destination,
                summary=itinerary.summary,
                itinerary_json=itinerary_json,
            )
            session.add(record)
        else:
            existing_record.destination = itinerary.destination
            existing_record.summary = itinerary.summary
            existing_record.itinerary_json = itinerary_json

        session.commit()
        return itinerary.trip_id
    finally:
        session.close()


def get_itinerary_by_trip_id(trip_id: str) -> TripDetailResponse | None:
    """根据 trip_id 读取已保存 itinerary，找不到时返回 None。"""
    init_db()

    session = SessionLocal()
    try:
        record = session.query(TripRecord).filter(TripRecord.trip_id == trip_id).first()
        if record is None:
            return None

        itinerary_data = json.loads(record.itinerary_json)
        itinerary = Itinerary(**itinerary_data)

        return TripDetailResponse(
            trip_id=record.trip_id,
            itinerary=itinerary,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    finally:
        session.close()


def list_saved_itineraries() -> TripListResponse:
    """返回已保存行程的摘要列表。"""
    init_db()

    session = SessionLocal()
    try:
        records = (
            session.query(TripRecord)
            .order_by(TripRecord.updated_at.desc(), TripRecord.id.desc())
            .all()
        )

        items = [
            TripSummaryItem(
                trip_id=record.trip_id,
                destination=record.destination,
                summary=record.summary,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]
        return TripListResponse(total=len(items), items=items)
    finally:
        session.close()


def delete_itinerary_by_trip_id(trip_id: str) -> bool:
    """根据 trip_id 删除已保存行程，删除成功返回 True。"""
    init_db()

    session = SessionLocal()
    try:
        record = session.query(TripRecord).filter(TripRecord.trip_id == trip_id).first()
        if record is None:
            return False

        session.delete(record)
        session.commit()
        return True
    finally:
        session.close()
