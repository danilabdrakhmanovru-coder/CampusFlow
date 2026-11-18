"""Coverage-aware analytics and recommendations."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range

from .auth import admin_user, booking_user, current_user, db_session
from .bookings import CAMPUS, now, standalone_booking
from .teaching_rules import days_off
from .catalog import GroupSize, WalkingTime
from .forecast import building_feature, train_booking_demand, train_load
from .models import Booking, Hold, Occupancy, Room
from .optimizer import BELL, LessonChoices, Option, measure, optimize
from .schedule_models import ImportBatch, Lesson, Proposal
from .teachers import building_key, directory, teacher_view

router = APIRouter()


def moment(day, minute):
    return datetime.combine(day, time(minute // 60, minute % 60), CAMPUS)


def fits_bell_slot(day, start, end):
    return any(start <= moment(day,a) and moment(day,b) <= end for a,b in BELL)


def periods(day, end):
    if not 0 <= (end - day).days <= 200:
        raise HTTPException(422, "Укажите период до 201 дня")
    return Range(moment(day, 0), moment(end + timedelta(days=1), 0), bounds="[)")


def lessons(db, span):
    return db.scalars(select(Lesson).join(ImportBatch).where(
        ImportBatch.state == "active", Lesson.period.op("&&")(span),
    )).all()


def people(row):
    return tuple([f"g:{group}" for group in row.groups] + [f"t:{teacher}" for teacher in row.teachers])


def busy_rows(db, span):
    return db.scalars(select(Occupancy).outerjoin(Hold, Occupancy.hold_id == Hold.id).where(
        Occupancy.period.op("&&")(span),
        Occupancy.hold_id.is_(None) | (Hold.expires_at > func.clock_timestamp()),
    )).all()


def covered(db, day):
    if standalone_booking():
        return set(db.scalars(select(Room.building).where(Room.active).distinct()))
    return set(db.scalars(select(ImportBatch.scope).where(
        ImportBatch.state == "active", ImportBatch.complete, ImportBatch.date_from <= day, ImportBatch.date_to >= day,
    )))


def overlaps(period, start, end):
    return period.lower < end and period.upper > start


def ranked_rooms(db, buildings, kind, count, equipment=()):
    return [room for room in db.scalars(select(Room).where(
        Room.active, Room.building.in_(buildings), Room.kind == kind, Room.capacity >= count,
    )) if all(room.equipment.get(item) for item in equipment)]


ROOM_KIND_LABELS = {
    "lecture": "лекционная", "computer": "компьютерный класс",
    "laboratory": "лаборатория", "seminar": "семинарская",
}
MISSING_EQUIPMENT = {
    "pc": "Нет компьютеров", "projector": "Нет проектора", "board": "Нет доски",
    "microphone": "Нет микрофона", "screen": "Нет экрана",
}


def room_requirements(room, kind, count, equipment):
    reasons = []
    if room.kind != kind:
        reason = f"Другой тип: {ROOM_KIND_LABELS.get(room.kind, 'не указан')}"
        reasons.append(reason if room.kind else "Тип аудитории не указан")
    if room.capacity is None:
        reasons.append("Вместимость не указана")
    elif room.capacity < count:
        reasons.append(f"Мало мест: {room.capacity}, нужно {count}")
    for item in equipment:
        if item == "accessible":
            if room.accessible is not True:
                reasons.append("Доступная среда не подтверждена" if room.accessible is None
                               else "Аудитория недоступна для маломобильных")
        elif not room.equipment.get(item):
            reasons.append(MISSING_EQUIPMENT.get(item, f"Нет оборудования: {item}"))
    return reasons


def walking_minutes(room_id, routes, previous, following, start, end):
    walk = 0
    if previous:
        minutes = routes.get((previous.room_id, room_id), 0)
        if timedelta(minutes=minutes) > start - previous.period.upper:
            return None
        walk += minutes
    if following:
        minutes = routes.get((room_id, following.room_id), 0)
        if timedelta(minutes=minutes) > following.period.lower - end:
            return None
        walk += minutes
    return walk


def other_rooms_for(catalog, coverage, busy, requirements, slots, routes, exact, count, requested):
    result = []
    for room in catalog:
        reasons = list(requirements[room.id])
        available = None
        selectable = False
        if room.building not in coverage:
            status = "unknown"
            reasons.append("Расписание корпуса на эту дату не подтверждено. Занятость неизвестна")
        elif not slots:
            status = "no_time"
            reasons.append("Выбранный интервал уже начался или выходит за пределы времени бронирования"
                           if exact else "На эту дату больше нет интервалов нужной длительности")
        else:
            free = [(start, end, group_busy, previous, following)
                    for start, end, group_busy, previous, following, _ in slots
                    if not any(overlaps(period, start, end) for period in busy[room.id])]
            if not free:
                status = "busy"
                reasons.append("Аудитория занята в выбранное время" if exact
                               else "Нет свободного интервала нужной длительности")
            else:
                status = "free"
                suitable = next((slot for slot in free if not slot[2] and
                                 walking_minutes(room.id, routes, slot[3], slot[4], slot[0], slot[1]) is not None), None)
                start, end, *_ = suitable or free[0]
                available = {"start": start, "end": end}
                selectable = bool(suitable and room.capacity is not None and room.capacity >= count
                                  and ("accessible" not in requested or room.accessible))
                if not suitable:
                    reasons.append("У группы занятия в свободное для аудитории время" if all(slot[2] for slot in free)
                                   else "Группа не успеет перейти между аудиториями")
        order = {"free": 0, "busy": 1, "unknown": 2, "no_time": 3}
        result.append(((order[status], len(reasons), room.building, room.code, room.id),
                       {"room_id": room.id, "room": room.code, "building": room.building,
                        "capacity": room.capacity, "status": status, "available": available, "selectable": selectable, "reasons": reasons}))
    return [item for _, item in sorted(result)][:12]


@router.get("/slots/recommendations")
def recommend(day: date, kind: str, count: int | None = Query(default=None, ge=1), group: str | None = None,
              equipment: str = "", duration: int = Query(90, ge=15, le=480), start_minute: int | None = Query(None, ge=0, le=1380),
              building: str | None = None,
              db=Depends(db_session), _=Depends(booking_user)):
    span = periods(day, day)
    coverage = covered(db, day) - {"iimrt"}
    if building:
        coverage &= {building}
    if count is None:
        size = db.get(GroupSize, group) if group else None
        if size is None:
            raise HTTPException(422, "Укажите число участников или группу с известным размером")
        count = size.size
    requested = tuple(dict.fromkeys(item.strip() for item in equipment.split(",") if item.strip()))
    catalog_query = select(Room).where(Room.active)
    if building:
        catalog_query = catalog_query.where(Room.building == building)
    catalog = db.scalars(catalog_query.order_by(Room.building, Room.code)).all()
    requirements = {room.id: room_requirements(room, kind, count, requested) for room in catalog}
    rooms = [room for room in catalog if room.building in coverage and not requirements[room.id]]
    busy = defaultdict(list)
    fixed = defaultdict(list)
    for occupancy in busy_rows(db, span):
        if occupancy.kind in {"lesson","block"}:
            fixed[occupancy.room_id].append(occupancy.period)
        busy[occupancy.room_id].append(occupancy.period)
    group_rows = [r for r in lessons(db, span) if group in r.groups] if group else []
    routes = {(r.from_room_id, r.to_room_id): r.minutes for r in db.scalars(select(WalkingTime))} if group_rows else {}
    clock = now(db)
    slots = []
    starts = [start_minute] if start_minute is not None else range(480, 1380 - duration + 1, 15)
    for a in starts:
        if a + duration > 1380:
            continue
        start, end = moment(day, a), moment(day, a + duration)
        if start < clock:
            continue
        group_busy = any(overlaps(row.period, start, end) for row in group_rows)
        prior = [row for row in group_rows if row.period.upper <= start]
        later = [row for row in group_rows if row.period.lower >= end]
        previous = max((row for row in prior if row.room_id), key=lambda r:r.period.upper, default=None)
        following = min((row for row in later if row.room_id), key=lambda r:r.period.lower, default=None)
        gap = int((min(r.period.lower for r in later) - max(r.period.upper for r in prior)).total_seconds() // 60) if prior and later else 0
        slots.append((start, end, group_busy, previous, following, gap))

    options, wait_options = [], []
    usage = {room.id: sum((period.upper - period.lower).total_seconds() for period in busy[room.id])/3600
             for room in rooms}
    for start, end, group_busy, previous, following, gap in slots:
        if group_busy:
            continue
        for room in rooms:
            if any(overlaps(period, start, end) for period in busy[room.id]):
                if start_minute is not None and not any(overlaps(p,start,end) for p in fixed[room.id]):
                    wait_options.append(dict(room_id=room.id, room=room.code, building=room.building, start=start, end=end))
                continue
            walk = walking_minutes(room.id, routes, previous, following, start, end)
            if walk is None:
                continue
            reasons = [f"Аудитория подходит по типу. Мест: {room.capacity}, нужно: {count}."]
            if gap:
                reasons.append(f"Интервал попадает в перерыв группы между парами ({gap} мин).")
            if walk:
                reasons.append(f"Измеренное время переходов: {walk} мин.")
            score = (room.capacity-count) + 3*walk + usage[room.id] - min(gap, 180)/6
            options.append(((score, start, room.id), dict(
                room_id=room.id, room=room.code, building=room.building,
                start=start, end=end, explanation=" ".join(reasons), reasons=reasons,
            )))
    others = [] if options else other_rooms_for(catalog, coverage, busy, requirements, slots, routes, start_minute is not None, count, requested)
    return {"covered_buildings": sorted(coverage), "options": [v for _, v in sorted(options)[:3]],
            "waiting": wait_options[:3], "other_rooms": others}


@router.get("/analytics/windows")
def windows(start: date, end: date, db=Depends(db_session), _=Depends(admin_user)):
    schedules = defaultdict(set)
    teacher_buildings = defaultdict(set)
    eligible_groups = set(db.scalars(select(GroupSize.group_code).where(GroupSize.size >= 5)))
    numbers = directory(db)
    for row in lessons(db, periods(start, end)):
        lower, upper = row.period.lower.astimezone(CAMPUS), row.period.upper.astimezone(CAMPUS)
        for label in people(row):
            if label.startswith("g:") and label[2:] not in eligible_groups:
                continue
            schedules[label, lower.date()].add((lower, upper))
            if label.startswith("t:"):
                teacher_buildings[label, lower.date()].add(building_key(row.building))
    result = []
    for (label, day), intervals in schedules.items():
        last = None
        for lower, upper in sorted(intervals):
            if last is not None:
                free_slots = sum(last <= moment(day, a) and moment(day, b) <= lower for a, b in BELL)
                if free_slots:
                    public_label = label
                    if label.startswith("t:"):
                        aliases = [f"Преподаватель №{numbers[b, label[2:]]} — {b if b != 'unknown' else 'без корпуса'}"
                                   for b in sorted(teacher_buildings[label, day]) if (b, label[2:]) in numbers]
                        public_label = " / ".join(aliases) or "Преподаватель"
                    result.append(dict(entity=public_label, day=day, start=last, end=lower, free_slots=free_slots,
                                       minutes=int((lower-last).total_seconds() // 60)))
            last = max(last, upper) if last is not None else upper
    result.sort(key=lambda row: (-row["minutes"], row["day"], row["entity"], row["start"]))
    return {"total": len(result), "windows": result[:100], "coverage": "published_schedule"}


def load_data(db, start, end):
    span = periods(start, end)
    imports = db.scalars(select(ImportBatch).where(ImportBatch.state == "active", ImportBatch.complete)).all()
    rooms = {room.id: room for room in db.scalars(select(Room).where(Room.active))}
    counts = {b: sum(r.building == b for r in rooms.values()) for b in {room.building for room in rooms.values()}}
    occupied = defaultdict(set)
    for row in db.scalars(select(Occupancy).where(Occupancy.kind == "lesson", Occupancy.period.op("&&")(span))):
        room = rooms.get(row.room_id)
        if room is None:
            continue
        day = row.period.lower.astimezone(CAMPUS).date()
        for slot, (a, b) in enumerate(BELL):
            if overlaps(row.period, moment(day, a), moment(day, b)):
                occupied[day, room.building, slot].add(room.id)
    values = {}
    for batch in imports:
        if not counts.get(batch.scope):
            continue
        day = max(start, batch.date_from)
        while day <= min(end, batch.date_to):
            for slot in range(len(BELL)):
                values[day, batch.scope, slot] = len(occupied[day, batch.scope, slot])
            day += timedelta(days=1)
    return values, counts


@router.get("/analytics/occupancy")
def occupancy(start: date, end: date, db=Depends(db_session), _=Depends(booking_user)):
    values, counts = load_data(db, start, end)
    return {"cells": [dict(day=day, building=b, slot=i+1, occupied=n, total=counts[b])
                      for (day,b,i), n in sorted(values.items())]}


@router.get("/analytics/forecasts")
def forecasts(start: date, end: date, target: date, db=Depends(db_session), _=Depends(booking_user)):
    if target <= end:
        raise HTTPException(422, "Дата прогноза должна быть позже периода обучения")
    values, counts = load_data(db, start, end)
    trained = train_load(values, counts)
    history = defaultdict(int)
    end_date = min(end, now(db).astimezone(CAMPUS).date() - timedelta(days=1))
    if end_date >= start:
        for building, period in db.execute(select(Room.building, Booking.period).join(Room).where(
            Booking.period.op("&&")(periods(start, end_date)), Room.active,
        )):
            day = period.lower.astimezone(CAMPUS).date()
            if start <= day <= end_date:
                history[day, building] += 1
    buildings = sorted({b for _, b in history})
    demand = train_booking_demand(history, buildings)
    data = {"demand": {"status": "insufficient_data"}, "load": {"status": "insufficient_data"}}
    if demand:
        model, metrics = demand
        data["demand"] = {
            "status": "trained", "source": "booking_history", "metrics": metrics,
            "rooms": [{"building": b, "count": max(0., float(model.predict([[target.weekday(), building_feature(b)]])[0]))}
                      for b in buildings],
        }
    if trained:
        model, metrics = trained
        cells = []
        for building in sorted({b for _, b, _ in values}):
            inputs = [(target.weekday(), building_feature(building), i) for i in range(len(BELL))]
            predicted = model.predict(inputs)
            cells.extend(dict(building=building, slot=i+1, ratio=max(0., min(1., float(p))))
                         for i,p in enumerate(predicted))
        data["load"] = {"status": "trained", "source": "published_building_schedule", "date": target,
                        "metrics": metrics, "cells": cells}
    return data


@router.get("/schedule/entities")
def entities(db=Depends(db_session), user=Depends(current_user)):
    rows = db.execute(select(Lesson.groups, Lesson.building, Lesson.teachers).join(ImportBatch).where(
        ImportBatch.state == "active",
    ))
    groups, teacher_keys = set(), set()
    for group_codes, building, teachers in rows:
        groups.update(group_codes)
        if user.role == "admin":
            teacher_keys.update((building_key(building), key) for key in teachers)
    result = {"groups": sorted(groups)}
    if user.role != "student":
        result["rooms"] = [
            {"id": room.id, "building": room.building, "code": room.code}
            for room in db.scalars(select(Room).where(Room.active).order_by(Room.building, Room.code))
        ]
    if user.role == "admin":
        numbers = directory(db)
        result["teachers"] = [
            teacher_view(b, n) for b, n in sorted((b, numbers[b, key]) for b, key in teacher_keys if (b, key) in numbers)
        ]
    return result


class Requirements(BaseModel):
    kind: Literal["lecture", "computer", "laboratory", "seminar"] | None = None
    people: int | None = Field(default=None, gt=0)
    equipment: list[str] = Field(default_factory=list)
    accessible: bool = False
    unavailable_slots: list[Annotated[int, Field(ge=1, le=9)]] = Field(default_factory=list)


class OptimizationRequest(BaseModel):
    future_only: bool = False
    day: date
    end_day: date | None = None
    requirements: dict[int, Requirements]


@router.post("/admin/optimization-runs")
def optimize_day(data: OptimizationRequest, db=Depends(db_session), _=Depends(admin_user)):
    versions = sorted(db.scalars(select(ImportBatch.id).where(ImportBatch.state == "active")))
    day = data.day
    end_day = data.end_day or day
    count = (end_day-day).days+1
    if not 1 <= count <= 7 or not data.requirements:
        raise HTTPException(422, "Выберите занятия за период от одного до семи дней")
    span = periods(day, end_day)
    rows = lessons(db, span)
    by_id = {r.id: r for r in rows}
    if not set(data.requirements) <= by_id.keys():
        raise HTTPException(422, "Некоторые занятия отсутствуют в активном расписании на эту дату")
    days = [day+timedelta(days=i) for i in range(count)]
    coverage_by_day = {d: covered(db,d) for d in days}
    coverage = set().union(*coverage_by_day.values())
    if not coverage:
        return {"status": "insufficient_coverage", "assignments": []}
    slots = [(moment(d, a), moment(d, b)) for d in days for a, b in BELL]
    moving = {key: by_id[key] for key in data.requirements}
    clock = now(db) if data.future_only else None
    if clock and any(row.period.lower <= clock for row in moving.values()):
        raise HTTPException(422, "Начавшиеся занятия закреплены")
    for row in moving.values():
        if not row.room_id or not row.groups or not row.teachers or row.building not in coverage_by_day[row.period.lower.astimezone(CAMPUS).date()]:
            raise HTTPException(422, "Для подвижной пары нужны аудитория с покрытием, группа и преподаватель")
        duplicates = [r for r in rows if r.id != row.id and r.building == row.building
                      and r.room_code == row.room_code and overlaps(r.period, row.period.lower, row.period.upper)]
        if duplicates:
            raise HTTPException(409, "В источниках есть пересекающиеся записи этой пары. Сначала устраните неоднозначность.")
    fixed = set()
    for row in rows:
        if row.id not in moving:
            for i, (start, end) in enumerate(slots):
                if overlaps(row.period, start, end):
                    for label in people(row):
                        fixed.add((label, i, row.building or ""))
                    if row.room_id:
                        fixed.add((f"r:{row.room_id}", i, row.building or ""))
    fixed_busy = defaultdict(list)
    for occupied in busy_rows(db, span):
        if occupied.kind == "lesson" and any(
            r.room_id == occupied.room_id and r.period == occupied.period for r in moving.values()
        ):
            continue
        fixed_busy[occupied.room_id].append(occupied.period)
    rooms_by_id = {room.id: room for room in db.scalars(select(Room))}
    teacher_days_off = days_off(db)
    sizes = {r.group_code:r.size for r in db.scalars(select(GroupSize))}
    items = []
    room_requirements = {}
    for key, row in moving.items():
        rule = data.requirements[key]
        original_slot = next((i for i, (a, b) in enumerate(slots) if row.period.lower == a and row.period.upper == b), None)
        if original_slot is None:
            raise HTTPException(422, "Оптимизатор принимает занятия целиком на одном слоте сетки звонков")
        origin = rooms_by_id[row.room_id]
        kind = rule.kind or origin.kind
        size = rule.people or (sum(sizes[group] for group in row.groups) if all(group in sizes for group in row.groups) else None)
        if not kind or not size:
            raise HTTPException(422, f"Укажите тип и число участников для занятия №{key}")
        room_requirements[str(key)] = {"kind":kind,"size":size,"equipment":rule.equipment,"accessible":rule.accessible}
        rooms = ranked_rooms(db, coverage, kind, size, rule.equipment)
        options = tuple(
            Option(room.id, room.building, i, room.capacity-size)
            for room in rooms if not rule.accessible or room.accessible
            for i, (a, b) in enumerate(slots)
            if all(a.weekday() not in teacher_days_off[teacher] for teacher in row.teachers)
            if (clock is None or a>clock) and room.building in coverage_by_day[days[i//len(BELL)]] and i%len(BELL)+1 not in rule.unavailable_slots and not any(overlaps(p, a, b) for p in fixed_busy[room.id])
        )
        original_capacity = rooms_by_id[row.room_id].capacity
        original = Option(row.room_id, row.building, original_slot, max(0, original_capacity - size) if original_capacity else 0)
        items.append(LessonChoices(key, people(row), original, options))
    result = optimize(items, sorted(fixed), days=count, seconds=12 if count>1 else 8)
    result["before"] = measure([(row.people, row.original) for row in items], sorted(fixed))
    if result["assignments"]:
        assigned = {item["lesson_id"]: item for item in result["assignments"]}
        result["after"] = measure([
            (row.people, next(option for option in row.choices
                              if option.room == assigned[row.id]["room_id"] and option.slot + 1 == assigned[row.id]["slot"]))
            for row in items
        ], sorted(fixed))
    for assignment in result["assignments"]:
        index = assignment["slot"] - 1
        assignment.update(date=days[index//len(BELL)], slot=index%len(BELL)+1)
    proposal_result = {**result, "room_requirements": room_requirements, "day": day, "end_day": end_day, "covered_buildings": sorted(coverage),
            "original": [{"lesson_id": row.id, "room_id": row.original.room,
                          "date": days[row.original.slot//len(BELL)],
                          "slot": row.original.slot%len(BELL)+1} for row in items]}

    if result["assignments"]:
        proposal = Proposal(result=jsonable_encoder(proposal_result), source_versions=versions)
        db.add(proposal)
        db.commit()
        proposal_result["id"] = proposal.id
    return proposal_result

@router.get("/me/windows")
def personal_windows(day: date, group: str | None = None, db=Depends(db_session), user=Depends(current_user)):
    from .schedule_models import TeacherLink

    rows = lessons(db, periods(day, day))
    if user.role == "teacher" and not group:
        link = db.get(TeacherLink, user.id)
        if link is None:
            raise HTTPException(404, "Ваш аккаунт ещё не привязан к расписанию")
        items = [row.period for row in rows if link.teacher_key in row.teachers]
    elif group:
        if user.role == "student" and user.preferences.get("group") != group:
            raise HTTPException(403, "Выберите свою группу в личном кабинете")
        if user.role == "teacher":
            link = db.get(TeacherLink,user.id)
            if not link or not any(group in row.groups and link.teacher_key in row.teachers for row in rows):
                raise HTTPException(403, "Это расписание другой группы")
        items = [row.period for row in rows if group in row.groups]
    else:
        return {"items": []}
    result = []
    last = None
    for item in sorted(items, key=lambda p: (p.lower, p.upper)):
        if last is not None and fits_bell_slot(day,last,item.lower):
            result.append({"start": last, "end": item.lower,
                           "minutes": int((item.lower-last).total_seconds()//60)})
        last = max(last,item.upper) if last else item.upper
    return {"items": result}
