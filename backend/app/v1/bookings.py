import hashlib
import json
from secrets import token_urlsafe
from datetime import datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo
from os import environ

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.exc import IntegrityError

from .auth import admin_user, booking_user, current_user, db_session
from .models import Audit, Booking, Hold, Idempotency, Occupancy, Room, User

from .schedule_models import ImportBatch
from .activity_models import Outbox, Ticket

router = APIRouter()
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
CAMPUS = ZoneInfo(environ.get("CAMPUSFLOW_TIMEZONE", "Asia/Yekaterinburg"))


class Interval(BaseModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def validate_interval(self):
        self.start = self.start.astimezone(timezone.utc)
        self.end = self.end.astimezone(timezone.utc)
        if not timedelta(0) < self.end - self.start <= timedelta(hours=8):
            raise ValueError("Интервал должен длиться больше нуля и не более 8 часов")
        start, end = self.start.astimezone(CAMPUS), self.end.astimezone(CAMPUS)
        if start.date() != end.date() or start.hour < 8 or end > end.replace(hour=23, minute=0, second=0, microsecond=0):
            raise ValueError("Выберите интервал в пределах одного дня с 08:00 до 23:00")
        return self


class HoldInput(Interval):
    room_id: int = Field(gt=0)


class ConfirmInput(BaseModel):
    repeats: int = Field(default=1, ge=1, le=12)
    hold_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")


def now(db):
    return db.scalar(select(func.clock_timestamp()))


def lock_room(db, room_id):
    room = db.scalar(select(Room).where(Room.id == room_id).with_for_update())
    if room is None:
        raise HTTPException(404, "Аудитория не найдена")
    return room


def expire_room(db, room_id, clock):
    expired = db.execute(update(Hold).where(
        Hold.room_id == room_id, Hold.state == "active", Hold.expires_at <= clock,
    ).values(state="expired").returning(Hold.id)).scalars().all()
    if expired:
        db.execute(delete(Occupancy).where(Occupancy.hold_id.in_(expired)))


def idem(db, user, operation, key, data):
    account = db.scalar(select(User).where(User.id == user.id).with_for_update(read=True))
    if not account or not account.active or account.auth_version != user.auth_version:
        raise HTTPException(401, "Войдите в CampusFlow")
    fingerprint = hashlib.sha256(json.dumps(
        data.model_dump(mode="json"), sort_keys=True,
    ).encode()).hexdigest()
    pk = (user.id, operation, key)
    db.execute(insert(Idempotency).values(
        user_id=user.id, operation=operation, key=key, fingerprint=fingerprint,
    ).on_conflict_do_nothing())
    record = db.get(Idempotency, pk, with_for_update=True)
    if record.fingerprint != fingerprint:
        raise HTTPException(409, {"code": "key_reused", "message": "Ключ уже использован с другими параметрами"})
    return record


def view(booking):
    return {
        "id": booking.id, "room_id": booking.room_id, "owner_id": booking.owner_id,
        "start": booking.period.lower.isoformat(), "end": booking.period.upper.isoformat(),
        "title": booking.title, "cancelled_at": booking.cancelled_at,
    }


def has_coverage(db, building, start, end):
    if standalone_booking():
        return True
    first = start.astimezone(CAMPUS).date()
    last = (end - timedelta(microseconds=1)).astimezone(CAMPUS).date()
    return db.scalar(select(ImportBatch.id).where(
        ImportBatch.scope == building, ImportBatch.state == "active", ImportBatch.complete,
        ImportBatch.date_from <= first, ImportBatch.date_to >= last,
    ).limit(1)) is not None


def standalone_booking():
    from os import environ
    return environ.get("CAMPUSFLOW_BOOKING_MODE", "schedule") == "standalone"


def require_coverage(db, building, start, end):
    if not has_coverage(db, building, start, end):
        raise HTTPException(409, {"code": "no_coverage", "message":
            "На эту дату нет полного расписания корпуса. Бронирование недоступно.",
            "alternatives": []})


def effective_start(start, end, clock):
    if start >= clock:
        return start
    if end - clock < timedelta(minutes=15):
        raise HTTPException(422, "До конца начавшегося слота должно оставаться не менее 15 минут")
    return clock


def alternatives(db, data):
    room = db.get(Room, data.room_id)
    if room is None or not room.active:
        return []
    duration = data.end - data.start
    limit = min(data.end.astimezone(CAMPUS).replace(hour=23, minute=0, second=0, microsecond=0),
                data.start + timedelta(hours=4))
    occupied = db.scalars(select(Occupancy.period).outerjoin(Hold, Occupancy.hold_id == Hold.id).where(
        Occupancy.room_id == data.room_id,
        Occupancy.period.op("&&")(Range(data.start, limit, bounds="[)")),
        (Occupancy.hold_id.is_(None) | (Hold.expires_at > func.clock_timestamp())),
    ).order_by(func.lower(Occupancy.period))).all()
    candidate = max(data.start, now(db))
    options = []
    for busy in [*occupied, Range(limit, limit + timedelta(seconds=1), bounds="[)")]:
        while candidate + duration <= min(busy.lower, limit):
            options.append({"room_id": room.id, "start": candidate.isoformat(),
                            "end": (candidate + duration).isoformat(), "coverage": "building_import"})
            if len(options) == 3:
                return options
            candidate += timedelta(minutes=15)
        candidate = max(candidate, busy.upper)
    return options


@router.post("/booking-holds", status_code=201)
def create_hold(data: HoldInput, key: Key, db=Depends(db_session), user=Depends(booking_user)):
    try:
        record = idem(db, user, "hold", key, data)
        if record.result is not None:
            hold = db.get(Hold, record.result["id"])
            if hold is None or hold.expires_at <= now(db) or hold.state == "expired":
                raise HTTPException(409, {"code": "hold_expired", "message": "Удержание истекло. Выберите слот повторно."})
            if hold.state != "active":
                raise HTTPException(409, {"code": "hold_unavailable", "message": "Удержание больше недоступно."})
            return record.result
        room = lock_room(db, data.room_id)
        clock = now(db)
        if not room.active:
            raise HTTPException(409, {"code": "room_inactive", "message": "Аудитория недоступна"})
        require_coverage(db, room.building, data.start, data.end)
        start = effective_start(data.start, data.end, clock)
        expire_room(db, room.id, clock)
        hold = Hold(owner_id=user.id, room_id=room.id, expires_at=clock + timedelta(minutes=5), state="active")
        db.add(hold)
        db.flush()
        db.add(Occupancy(room_id=room.id, period=Range(start, data.end, bounds="[)"), kind="hold", hold_id=hold.id))
        record.result = {"id": hold.id, "room_id": room.id, "expires_at": hold.expires_at.isoformat(), "start": start.isoformat(), "end": data.end.isoformat()}
        db.commit()
        return record.result
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23P01":
            raise
        raise HTTPException(409, {"code": "room_busy", "message": "Интервал уже занят",
                                  "alternatives": alternatives(db, data)}) from exc


def get_hold(db, hold_id, user):
    hold = db.get(Hold, hold_id)
    if hold is None or hold.owner_id != user.id:
        raise HTTPException(404, "Удержание не найдено")
    room = lock_room(db, hold.room_id)
    db.refresh(hold, with_for_update=True)
    return hold, room


@router.post("/bookings", status_code=201)
def confirm(data: ConfirmInput, key: Key, db=Depends(db_session), user=Depends(booking_user)):
    record = idem(db, user, "confirm", key, data)
    if record.result is not None:
        return record.result
    hold, room = get_hold(db, data.hold_id, user)
    clock = now(db)
    if hold.state != "active" or hold.expires_at <= clock or not room.active:
        raise HTTPException(409, {"code": "hold_unavailable", "message": "Выберите интервал заново"})
    occupancy = db.scalar(select(Occupancy).where(Occupancy.hold_id == hold.id))
    if occupancy is None:
        raise HTTPException(409, {"code": "hold_unavailable", "message": "Выберите интервал заново"})
    require_coverage(db, room.building, occupancy.period.lower, occupancy.period.upper)
    start = effective_start(occupancy.period.lower, occupancy.period.upper, clock)
    occupancy.period = Range(start, occupancy.period.upper, bounds="[)")
    booking = Booking(hold_id=hold.id, owner_id=user.id, room_id=room.id,
                      period=occupancy.period, title=data.title.strip())
    db.add(booking)
    db.flush()
    db.add(Ticket(booking_id=booking.id, token=token_urlsafe(32),
                  auto_release_at=min(start + timedelta(minutes=15), booking.period.upper)))
    hold.state = "confirmed"
    occupancy.kind, occupancy.hold_id, occupancy.booking_id = "booking", None, booking.id
    db.add(Audit(actor_id=user.id, action="booking.created", object_id=booking.id))
    series = []
    for index in range(1, data.repeats):
        shift = timedelta(weeks=index)
        lower = occupancy.period.lower.astimezone(CAMPUS) + shift
        upper = occupancy.period.upper.astimezone(CAMPUS) + shift
        require_coverage(db, room.building, lower, upper)
        period = Range(lower, upper, bounds="[)")
        expire_room(db, room.id, clock)
        conflict = db.scalar(select(Occupancy.id).where(Occupancy.room_id == room.id,
                             Occupancy.period.op("&&")(period)).limit(1))
        if conflict:
            raise HTTPException(409, {"code": "series_conflict",
                "message": f"Один из повторов занят ({lower:%d.%m.%Y}). Серия не создана."})
        occurrence = Hold(owner_id=user.id, room_id=room.id, expires_at=clock, state="confirmed")
        db.add(occurrence)
        db.flush()
        item = Booking(hold_id=occurrence.id, owner_id=user.id, room_id=room.id, period=period, title=booking.title)
        db.add(item)
        db.flush()
        db.add(Occupancy(room_id=room.id, period=period, kind="booking", booking_id=item.id))
        db.add(Ticket(booking_id=item.id, token=token_urlsafe(32),
                      auto_release_at=min(lower+timedelta(minutes=15), upper)))
        db.add(Audit(actor_id=user.id, action="booking.created", object_id=item.id))
        series.append(item.id)
    record.result = {**view(booking), "repeated_ids": series} if series else view(booking)
    db.commit()
    return record.result


@router.delete("/booking-holds/{hold_id}", status_code=204)
def release(hold_id: int, db=Depends(db_session), user=Depends(booking_user)):
    hold, _ = get_hold(db, hold_id, user)
    if hold.state == "active":
        hold.state = "released"
        db.execute(delete(Occupancy).where(Occupancy.hold_id == hold.id))
        db.commit()


@router.post("/bookings/{booking_id}/cancel", status_code=204)
def cancel(booking_id: int, db=Depends(db_session), user=Depends(booking_user)):
    booking = db.get(Booking, booking_id)
    if booking is None or (booking.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Бронь не найдена")
    lock_room(db, booking.room_id)
    db.refresh(booking, with_for_update=True)
    if booking.cancelled_at is None:
        booking.cancelled_at, booking.cancelled_by = now(db), user.id
        db.execute(delete(Occupancy).where(Occupancy.booking_id == booking.id))
        db.add(Audit(actor_id=user.id, action="booking.cancelled", object_id=booking.id))
        db.add(Outbox(user_id=booking.owner_id, kind="cancelled_by_admin" if user.id != booking.owner_id else "slot_freed", payload={"booking_id": booking.id}))
        db.commit()


@router.get("/bookings/mine")
def mine(offset: int = 0, include_cancelled: bool = False, upcoming: bool = False, db=Depends(db_session), user=Depends(booking_user)):
    conditions = [Booking.owner_id == user.id]
    if upcoming:
        conditions.append(func.upper(Booking.period) > func.now())
    if not include_cancelled:
        conditions.append(Booking.cancelled_at.is_(None))
    return list_bookings(db, offset, *conditions)


@router.get("/admin/bookings")
def all_bookings(offset: int = 0, db=Depends(db_session), _=Depends(admin_user)):
    return list_bookings(db, offset)


def list_bookings(db, offset, *conditions):
    return [view(row) for row in db.scalars(
        select(Booking).where(*conditions).order_by((func.upper(Booking.period) <= func.now()), func.lower(Booking.period), Booking.id).offset(max(0, offset)).limit(100)
    )]


@router.get("/rooms")
def rooms(offset: int = 0, db=Depends(db_session), _=Depends(current_user)):
    query = select(Room).where(Room.active).order_by(Room.id).offset(max(0, offset)).limit(100)
    return [{"id": r.id, "building": r.building, "code": r.code, "capacity": r.capacity,
             "kind": r.kind, "floor": r.floor, "equipment": r.equipment, "accessible": r.accessible,
             "plan_x":r.plan_x,"plan_y":r.plan_y}
            for r in db.scalars(query)]


@router.get("/rooms/{room_id}/timeline")
@router.get("/rooms/{room_id}/occupancy")
def room_occupancy(room_id: int, start: AwareDatetime, end: AwareDatetime,
                   db=Depends(db_session), _=Depends(current_user)):
    if not timedelta(0) < end - start <= timedelta(days=7):
        raise HTTPException(422, "Укажите интервал до семи дней")
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(404, "Аудитория не найдена")
    rows = db.execute(select(Occupancy.period, Occupancy.kind).outerjoin(Hold, Occupancy.hold_id == Hold.id).where(
        Occupancy.room_id == room_id, Occupancy.period.op("&&")(Range(start, end, bounds="[)")),
        (Occupancy.hold_id.is_(None) | (Hold.expires_at > func.clock_timestamp())),
    ).order_by(func.lower(Occupancy.period))).all()
    covered = has_coverage(db, room.building, start, end)
    return {"coverage": "building_import" if covered else "unknown",
            "busy": [{"start": r.lower, "end": r.upper, "kind": kind} for r, kind in rows]}

class BookingTitle(BaseModel):
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")


@router.patch("/bookings/{booking_id}")
def rename_booking(booking_id: int, data: BookingTitle, db=Depends(db_session), user=Depends(booking_user)):
    booking = db.get(Booking, booking_id, with_for_update=True)
    if not booking or booking.owner_id != user.id and user.role != "admin":
        raise HTTPException(404, "Бронь не найдена")
    if booking.cancelled_at:
        raise HTTPException(409, "Бронь уже отменена")
    booking.title = data.title.strip()
    db.add(Audit(actor_id=user.id, action="booking.renamed", object_id=booking.id))
    db.commit()
    return view(booking)
