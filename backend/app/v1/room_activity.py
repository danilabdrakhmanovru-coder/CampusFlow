"""Live occupancy, booking tickets and waiting lists."""
import asyncio
from datetime import date, datetime, time, timedelta
import json
from hashlib import sha256
from secrets import compare_digest, token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import Range
from starlette.concurrency import run_in_threadpool

from .site import PUBLICATION_ACTIONS
from .catalog import WalkingTime
from .auth import admin_user, digest, active_consent, booking_user, current_user, db_session
from .bookings import CAMPUS, HoldInput, Key, get_hold, has_coverage, idem, lock_room, now, require_coverage
from .models import Audit, Booking, Hold, Occupancy, RefreshSession, Room, User
from .activity_models import Outbox, Ticket, Watch

router = APIRouter(tags=["room-activity"])


@router.get("/free-now")
def free_now(building: str, from_room_id: int | None = None, db=Depends(db_session), _=Depends(current_user)):
    if not db.scalar(select(Room.id).where(Room.building == building, Room.active).limit(1)):
        raise HTTPException(422, "Выберите корпус из каталога")
    clock = now(db)
    day_end = clock.astimezone(CAMPUS).replace(hour=23, minute=0, second=0, microsecond=0)
    covered = clock < day_end and has_coverage(db, building, clock, day_end)
    if not covered or clock.astimezone(CAMPUS).hour < 8:
        return {"covered": covered, "rooms": [], "at": clock}
    candidates = db.scalars(select(Room).where(
        Room.building == building, Room.active,
    ).order_by(Room.code)).all()
    busy = db.execute(select(Occupancy.room_id, Occupancy.period).join(Room).outerjoin(Hold).where(
        Room.building == building, Occupancy.period.op("&&")(Range(clock, day_end, bounds="[)")),
        Occupancy.hold_id.is_(None) | (Hold.expires_at > clock),
    )).all()
    next_starts = {}
    for room_id, period in busy:
        next_starts[room_id] = min(next_starts.get(room_id, day_end), period.lower)
    routes = {r.to_room_id:r.minutes for r in db.scalars(select(WalkingTime).where(WalkingTime.from_room_id == from_room_id))} if from_room_id else {}
    return {"covered": True, "at": clock, "rooms": [{
        "id": r.id, "code": r.code, "building": building, "floor": r.floor, "kind": r.kind,
        "capacity": r.capacity, "equipment": r.equipment, "accessible": r.accessible, "walk_minutes": 0 if from_room_id == r.id else routes.get(r.id), "free_until": next_starts.get(r.id, day_end),
    } for r in candidates if next_starts.get(r.id, day_end) > clock]}


@router.get("/tickets/{booking_id}")
def ticket(booking_id: int, db=Depends(db_session), user=Depends(booking_user)):
    b = db.get(Booking, booking_id)
    t = db.get(Ticket, booking_id) if b and (b.owner_id == user.id or user.role == "admin") else None
    if t is None:
        raise HTTPException(404, "Талон не найден")
    return {"id": booking_id, "token": t.token, "checked_in_at": t.check_in_at,
            "auto_release_at": t.auto_release_at, "cancelled": b.cancelled_at is not None}


class CheckIn(BaseModel):
    token: str | None = Field(default=None, min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    code: str | None = Field(default=None, min_length=6, max_length=100)


@router.post("/tickets/{booking_id}/check-in")
def check_in(booking_id: int, data: CheckIn, db=Depends(db_session), user=Depends(booking_user)):
    b = db.get(Booking, booking_id)
    if b is None or (b.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Талон не найден")
    room = lock_room(db, b.room_id)
    db.refresh(b)
    t = db.get(Ticket, booking_id)
    if t is None or b.cancelled_at:
        raise HTTPException(404, "Талон недействителен")
    if not ((user.role == "admin" and data.token and compare_digest(t.token, data.token)) or
            (room.check_in_digest and data.code and compare_digest(room.check_in_digest, digest(data.code.strip())))):
        raise HTTPException(403, "Введите код у двери аудитории или обратитесь к диспетчеру")
    if t.check_in_at is None:
        clock = now(db)
        if not b.period.lower <= clock < t.auto_release_at:
            raise HTTPException(409, {"code": "check_in_closed", "message": "Отметиться можно в первые 15 минут брони"})
        t.check_in_at = clock
        db.commit()
    return {"checked_in_at": t.check_in_at}


@router.post("/watches", status_code=201)
def watch(data: HoldInput, key: Key, db=Depends(db_session), user=Depends(booking_user)):
    record = idem(db, user, "watch", key, data)
    if record.result is not None:
        return record.result
    room = lock_room(db, data.room_id)
    require_coverage(db, room.building, data.start, data.end)
    if not room.active or data.end - now(db) < timedelta(minutes=15):
        raise HTTPException(422, "Интервал недоступен для подписки")
    period = Range(data.start, data.end, bounds="[)")
    item = db.scalar(select(Watch).where(Watch.user_id == user.id, Watch.room_id == room.id,
                                        Watch.period == period, Watch.state == "waiting"))
    if item is None:
        item = Watch(user_id=user.id, room_id=room.id, period=period, state="waiting")
        db.add(item)
        db.flush()
    record.result = {"id": item.id}
    db.commit()
    return record.result


@router.get("/watches")
def watches(db=Depends(db_session), user=Depends(booking_user)):
    rows = db.execute(select(Watch, Hold, Occupancy.period).select_from(Watch).outerjoin(Hold, Watch.hold_id == Hold.id).outerjoin(
        Occupancy, Occupancy.hold_id == Hold.id,
    ).where(Watch.user_id == user.id).order_by(Watch.id.desc()).limit(100)).all()
    clock = now(db)
    return [{
        "id": row.id, "room_id": row.room_id, "state": row.state,
        "start": row.period.lower, "end": row.period.upper,
        "offer": {"id": hold.id, "expires_at": hold.expires_at, "start": period.lower, "end": period.upper}
        if hold and period and hold.state == "active" and hold.expires_at > clock else None,
    } for row, hold, period in rows]


@router.delete("/watches/{watch_id}", status_code=204)
def stop_watch(watch_id: int, db=Depends(db_session), user=Depends(booking_user)):
    row = db.get(Watch, watch_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Подписка не найдена")
    lock_room(db, row.room_id)
    db.refresh(row, with_for_update=True)
    if row.hold_id:
        hold, _ = get_hold(db, row.hold_id, user)
        if hold.state == "active":
            hold.state = "released"
    if row.hold_id:
        db.execute(delete(Occupancy).where(Occupancy.hold_id == row.hold_id))
    row.state = "cancelled"
    db.commit()


@router.get("/events")
def events(request: Request, user=Depends(current_user)):
    factory = request.app.state.sessions

    def snapshot():
        with factory() as db:
            account = db.get(User, user.id)
            if not account or not account.active or account.auth_version != user.auth_version or active_consent(db, user.id) is None:
                return None
            if not db.scalar(select(RefreshSession.device_id).where(RefreshSession.device_id == user.device, RefreshSession.expires_at > func.now())):
                return None
            values = db.execute(select(Occupancy.id, Occupancy.period, Occupancy.kind).outerjoin(Hold).where(
                func.upper(Occupancy.period) > func.clock_timestamp(),
                Occupancy.hold_id.is_(None) | (Hold.expires_at > func.clock_timestamp()),
            ).order_by(Occupancy.id))
            digest = sha256()
            for value in values:
                digest.update(str(value).encode())
            notice = db.scalar(select(func.max(Outbox.id)).where(Outbox.user_id == user.id))
            publication = db.scalar(select(func.max(Audit.id)).where(Audit.action.in_(PUBLICATION_ACTIONS)))
            return {"revision": digest.hexdigest(), "notification": notice, "publication": publication}

    async def stream():
        last = None
        # Reconnect periodically so the next request revalidates the access token.
        for _ in range(12):
            if await request.is_disconnected():
                break
            state = await run_in_threadpool(snapshot)
            if state is None:
                break
            if state != last:
                yield "event: occupancy\ndata: " + json.dumps(state) + "\n\n"
                last = state
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/notifications")
def notifications(db=Depends(db_session), user=Depends(booking_user)):
    prefs = user.preferences.get("notifications", {})
    disabled = [key for key, value in prefs.items() if not value]
    return [{"id": row.id, "kind": row.kind, "payload": row.payload, "created_at": row.created_at}
            for row in db.scalars(select(Outbox).where(Outbox.user_id == user.id, Outbox.kind.not_in(disabled))
                                  .order_by(Outbox.id.desc()).limit(10))]


@router.post("/booking-holds/{hold_id}/renew")
def renew_hold(hold_id: int, key: Key, db=Depends(db_session), user=Depends(booking_user)):
    record = idem(db, user, f"renew:{hold_id}", key, BaseModel())
    hold, room = get_hold(db, hold_id, user)
    clock = now(db)
    if hold.state != "active" or hold.expires_at <= clock:
        raise HTTPException(409, {"code": "hold_expired", "message": "Удержание истекло"})
    period = db.scalar(select(Occupancy.period).where(Occupancy.hold_id == hold_id))
    if period is None or period.upper - clock < timedelta(minutes=15):
        raise HTTPException(409, {"code": "hold_unavailable", "message": "До конца слота осталось меньше 15 минут"})
    require_coverage(db, room.building, period.lower, period.upper)
    if record.result is not None:
        return record.result
    if db.scalar(select(Audit.id).where(Audit.action == "hold.renewed", Audit.object_id == hold_id).limit(1)):
        raise HTTPException(409, {"code": "already_renewed", "message": "Удержание можно продлить один раз"})
    hold.expires_at = clock + timedelta(minutes=5)
    db.add(Audit(actor_id=user.id, action="hold.renewed", object_id=hold_id))
    record.result = {"id": hold_id, "expires_at": hold.expires_at.isoformat(),
                     "start": period.lower.isoformat(), "end": period.upper.isoformat()}
    db.commit()
    return record.result


@router.get("/buildings/{building}/pulse-curve")
def occupancy_curve(building: str, day: date | None = None, db=Depends(db_session), _=Depends(current_user)):
    """Count distinct active rooms occupied during each quarter-hour."""
    clock = now(db)
    day = day or clock.astimezone(CAMPUS).date()
    start = datetime.combine(day, time(8), CAMPUS)
    last = datetime.combine(day, time(22), CAMPUS)
    step = timedelta(minutes=15)
    end = last + step
    if not has_coverage(db, building, start, end):
        return {"covered": False, "step_minutes": 15, "points": []}

    rooms = select(Room.id).where(Room.building == building, Room.active)
    total = db.scalar(select(func.count()).select_from(rooms.subquery()))
    intervals = db.execute(
        select(Occupancy.room_id, Occupancy.period)
        .outerjoin(Hold, Occupancy.hold_id == Hold.id)
        .where(
            Occupancy.room_id.in_(rooms),
            Occupancy.period.op("&&")(Range(start, end, bounds="[)")),
            Occupancy.hold_id.is_(None) | (Hold.expires_at > clock),
        )
    ).all()

    points = []
    at = start
    while at <= last:
        busy = {room_id for room_id, interval in intervals if interval.lower < at + step and interval.upper > at}
        points.append({"at": at, "busy": len(busy), "total": total})
        at += step
    return {"covered": True, "step_minutes": 15, "points": points}

@router.post("/admin/rooms/{room_id}/check-in-code")
def room_code(room_id: int, db=Depends(db_session), admin=Depends(admin_user)):
    room = lock_room(db, room_id)
    code = token_urlsafe(9)
    room.check_in_digest = digest(code)
    db.add(Audit(actor_id=admin.id, action="room.check_in_code_changed", object_id=room.id))
    db.commit()
    return {"code": code}


@router.get("/rooms/free")
def free_at(start: datetime, end: datetime, building: str | None = None, from_room_id: int | None = None,
            db=Depends(db_session), _=Depends(current_user)):
    if start.tzinfo is None or end.tzinfo is None or not timedelta(0) < end-start <= timedelta(hours=24):
        raise HTTPException(422, "Укажите интервал до суток с часовым поясом")
    clock = now(db)
    start = max(start, clock)
    if end <= start:
        return {"covered_buildings": [], "rooms": [], "ended": True}
    query = select(Room).where(Room.active)
    if building:
        query = query.where(Room.building == building)
    catalog = list(db.scalars(query.order_by(Room.building, Room.code)))
    covered = {key for key in {r.building for r in catalog} if has_coverage(db, key, start, end)}
    busy = set(db.scalars(select(Occupancy.room_id).outerjoin(Hold).where(
        Occupancy.period.op("&&")(Range(start, end, bounds="[)")),
        Occupancy.hold_id.is_(None) | (Hold.expires_at > clock),
    )))
    routes = {r.to_room_id:r.minutes for r in db.scalars(select(WalkingTime).where(WalkingTime.from_room_id == from_room_id))} if from_room_id else {}
    return {"covered_buildings": sorted(covered), "rooms": [
        {"id": r.id, "code": r.code, "building": r.building, "floor": r.floor, "kind": r.kind, "capacity": r.capacity,
         "equipment": r.equipment, "accessible": r.accessible, "free_until": end,
         "walk_minutes": 0 if from_room_id == r.id else routes.get(r.id)}
        for r in catalog if r.building in covered and r.id not in busy]}
