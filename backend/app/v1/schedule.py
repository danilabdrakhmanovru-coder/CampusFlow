from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from .auth import admin_user, current_user, db_session
from .bookings import CAMPUS, Key, expire_room, idem, lock_room, now
from .import_files import COLUMNS, identities, parse_datetime, parse_ics, parse_snapshot, parse_table
from .models import Audit, Booking, Hold, Occupancy, Room
from .activity_models import Outbox
from .schedule_export import DOCX_TYPE, as_docx, as_pdf, export_rows
from .schedule_models import ImportBatch, Lesson, TeacherLink, TeacherNumber
from .teachers import building_key, directory, register_numbers, teacher_view

router = APIRouter(tags=["schedule"])
MAX_FILE = 20_000_000


def display_subject(subject):
    return subject.replace(" · ", " — ").replace("·", "—")



def report_for(rows, rooms, mapping, scope, date_from, date_to):
    lessons = {}
    issues = []
    errors = 0
    unknown = 0
    for index, row in enumerate(rows, 1):
        fields = {field: row.get(mapping.get(field, field), "").strip() for field in COLUMNS}
        try:
            start, end = [parse_datetime(fields[key]).astimezone(timezone.utc) for key in ("start", "end")]
            local_start = start.astimezone(CAMPUS)
            local_end = end.astimezone(CAMPUS)
            if not start < end or not date_from <= local_start.date() <= date_to or local_end.date() != local_start.date():
                raise ValueError("Интервал вне заявленного периода или учебного дня")
            if not fields["subject"]:
                raise ValueError("Не указана дисциплина")
            building = fields["building"]
            if building.casefold().startswith("корпус "):
                building = building[7:].strip()
            code = fields["room"]
            if scope != "iimrt" and (building != scope or not code):
                raise ValueError("Укажите аудиторию выбранного корпуса")
            if len(building) > 120 or len(code) > 100:
                raise ValueError("Слишком длинное обозначение аудитории")
        except (TypeError, ValueError):
            errors += 1
            if len(issues) < 100:
                issues.append(dict(row=index, code="invalid_row", message="Проверьте дату, время, дисциплину и аудиторию"))
            continue
        teacher_keys = identities(fields["teachers"])
        subject = display_subject(fields["subject"])
        category = fields["lesson_type"].casefold()
        for prefixes, label in ((("lab","лаб"),"лабораторная"),(("lecture","лек"),"лекция"),
                                (("practice","seminar","практи","семинар"),"практическая")):
            if category.startswith(prefixes) and label not in subject.casefold():
                subject += " ("+label+")"
                break
        key = (start, end, building, code, subject, tuple(teacher_keys))
        lesson = lessons.setdefault(key, dict(
            start=start.isoformat(), end=end.isoformat(), building=building or None, room=code or None,
            subject=subject, groups=[], teachers=teacher_keys,
        ))
        groups = {group.strip() for group in fields["groups"].split(";") if group.strip()}
        lesson["groups"] = sorted(groups.union(lesson["groups"]))
    room_rows = {}
    room_overlaps = 0
    for lesson in sorted(lessons.values(), key=lambda row: row["start"]):
        location = lesson["building"], lesson["room"]
        if all(location) and lesson["room"].casefold() != "уточняется":
            previous_end = room_rows.get(location, "")
            room_overlaps += lesson["start"] < previous_end
            room_rows[location] = max(previous_end, lesson["end"])
        if (lesson["building"], lesson["room"]) not in rooms and all(location):
            unknown += 1
    return list(lessons.values()), dict(
        input_rows=len(rows), lessons=len(lessons), errors=errors, unknown_room_lessons=unknown, overlapping_room_rows=room_overlaps, issues=issues,
    )


def room_map(db):
    return {(r.building, r.code): r.id for r in db.scalars(select(Room))}


def row_period(row):
    return Range(datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"]), bounds="[)")


def desired_intervals(batches, rooms):
    by_room = defaultdict(list)
    for batch in batches:
        for row in batch.rows:
            room_id = rooms.get((row["building"], row["room"]))
            if not room_id:
                continue
            period = row_period(row)
            by_room[room_id].append(period)
    merged = {}
    for room_id, periods in by_room.items():
        spans = []
        for lower, upper in sorted({(p.lower, p.upper) for p in periods}):
            if spans and lower < spans[-1][1]:
                spans[-1] = (spans[-1][0], max(upper, spans[-1][1]))
            else:
                spans.append((lower, upper))
        merged[room_id] = spans
    return merged


def conflicts(db, spans):
    blocked = defaultdict(list)
    for row in db.scalars(select(Occupancy).where(Occupancy.kind != "lesson")):
        blocked[row.room_id].append(row.period)
    found = []
    for room, intervals in spans.items():
        for start, end in intervals:
            if any(period.lower < end and period.upper > start for period in blocked[room]):
                found.append(dict(room_id=room, start=start.isoformat(), end=end.isoformat()))
                if len(found) >= 100:
                    return found
    return found


def batch_view(batch):
    return dict(id=batch.id, scope=batch.scope, date_from=batch.date_from, date_to=batch.date_to,
                state=batch.state, complete=batch.complete, previous_id=batch.previous_id,
                report=batch.report, preview=[{key: value for key, value in row.items() if key != "teachers"} for row in batch.rows[:20]])


def require_batch(db, batch_id):
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "Импорт не найден")
    return batch


def active_batches(db):
    return db.scalars(select(ImportBatch).where(ImportBatch.state == "active")).all()


@router.post("/admin/imports", status_code=201)
def upload(
    date_from: date = Form(), date_to: date = Form(), scope: str = Form(),
    mapping_json: str = Form("{}"), complete: bool = Form(False),
    file: UploadFile = File(), db=Depends(db_session), user=Depends(admin_user),
):
    if (scope != "iimrt" and not db.scalar(select(Room.id).where(Room.building==scope,Room.active).limit(1))) or not 0 <= (date_to - date_from).days <= 200:
        raise HTTPException(422, "Укажите ИИМРТ, корпус 6 или 7 и период до 201 дня")
    data = file.file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(413, "Файл превышает 20 МБ")
    extension = Path(file.filename or "").suffix.lower()
    try:
        mapping = json.loads(mapping_json)
        if not isinstance(mapping, dict) or any(key not in COLUMNS or not isinstance(value, str) for key, value in mapping.items()):
            raise ValueError("mapping_json должен сопоставлять стандартные поля с заголовками файла")
        if extension in (".csv", ".xlsx"):
            rows = parse_table(data, extension)
        elif extension == ".json" and scope == "iimrt":
            rows = list(parse_snapshot(data, date_from, date_to))
        elif extension == ".ics":
            rows = parse_ics(data, date_from, date_to, scope)
        else:
            raise ValueError("Поддерживаются CSV, XLSX, ICS и JSON выгрузки ИИМРТ")
    except Exception as exc:
        raise HTTPException(422, "Не удалось прочитать файл. Проверьте формат, даты и сопоставление колонок") from exc
    if len(rows) > 100_000:
        raise HTTPException(422, "Слишком много строк")
    if not rows:
        raise HTTPException(422, "В выбранном периоде файл не содержит занятий")
    required = ("start", "end", "subject") + (("building", "room") if scope != "iimrt" else ())
    columns = set().union(*(row.keys() for row in rows))
    missing = [key for key in required if mapping.get(key, key) not in columns]
    if missing:
        return {"state": "mapping_required", "columns": sorted(columns), "missing": missing}
    rooms = room_map(db)
    normalized, report = report_for(rows, rooms, mapping, scope, date_from, date_to)
    batch = ImportBatch(actor_id=user.id, scope=scope, date_from=date_from, date_to=date_to,
                        source_name=extension, sha256=hashlib.sha256(data).hexdigest(), state="staged",
                        rows=normalized, mapping=mapping, report=report, complete=complete and scope != "iimrt")
    others = [b for b in active_batches(db) if b.scope != scope]
    batch.report = {**report, "booking_conflicts": conflicts(db, desired_intervals([*others, batch], rooms))}
    db.add(batch)
    db.flush()
    db.add(Audit(actor_id=user.id, action="schedule.staged", object_id=batch.id))
    db.commit()
    return batch_view(batch)


@router.get("/admin/imports/{batch_id}")
def inspect(batch_id: int, db=Depends(db_session), _=Depends(admin_user)):
    return batch_view(require_batch(db, batch_id))


def rebuild_occupancy(db, batches, rooms, scopes):
    spans = desired_intervals(batches, rooms)
    prior_rooms = db.scalars(select(Occupancy.room_id).where(Occupancy.kind == "lesson").distinct()).all()
    affected = {room_id for (building, _), room_id in rooms.items() if building in scopes}
    for room_id in sorted(set(prior_rooms) | set(spans) | affected):
        lock_room(db, room_id)
        expire_room(db, room_id, now(db))
    blocked = conflicts(db, spans)
    if blocked:
        raise HTTPException(409, {"code": "import_conflict", "conflicts": blocked})
    db.execute(delete(Occupancy).where(Occupancy.kind == "lesson"))
    db.add_all(Occupancy(room_id=room_id, period=Range(start, end, bounds="[)"), kind="lesson",
                         lesson_key=f"import:{room_id}:{start.isoformat()}")
               for room_id, intervals in spans.items() for start, end in intervals)


def materialize_lessons(db, batch, rooms):
    db.execute(delete(Lesson).where(Lesson.batch_id == batch.id))
    db.execute(Lesson.__table__.insert(), [
        dict(batch_id=batch.id, room_id=rooms.get((r["building"], r["room"])), building=r["building"],
             room_code=r["room"], period=row_period(r), subject=r["subject"], groups=r["groups"],
             teachers=r["teachers"]) for r in batch.rows
    ])


def activate(db, batch, replaces, actor, action):
    rooms = room_map(db)
    if batch and (batch.report["errors"] or not batch.rows):
        raise HTTPException(422, "Исправьте ошибки импорта перед публикацией")
    if batch and batch.scope != "iimrt" and batch.report["overlapping_room_rows"]:
        raise HTTPException(409, "Исправьте пересечения занятий в выгрузке корпуса")
    if batch and batch.complete and any((r["building"], r["room"]) not in rooms for r in batch.rows):
        raise HTTPException(422, "Добавьте все аудитории корпуса в каталог")
    next_batches = [b for b in active_batches(db) if replaces is None or b.id != replaces.id]
    if batch:
        next_batches.append(batch)
    rebuild_occupancy(db, next_batches, rooms, {item.scope for item in (batch, replaces) if item})
    if replaces:
        replaces.state = "archived"
    if batch:
        if action == "publish":
            batch.previous_id = replaces.id if replaces else None
        batch.state = "active"
        register_numbers(db, batch.rows)
        materialize_lessons(db, batch, rooms)
    db.add(Audit(actor_id=actor.id, action=f"schedule.{action}", object_id=(batch or replaces).id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23P01":
            raise HTTPException(409, "Занятость изменилась во время публикации") from exc
        raise


@router.post("/admin/imports/{batch_id}/publish")
def publish(batch_id: int, db=Depends(db_session), user=Depends(admin_user)):
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    batch = require_batch(db, batch_id)
    if batch.state == "active":
        return batch_view(batch)
    if batch.state != "staged":
        raise HTTPException(409, "Опубликовать можно только черновик")
    previous = next((b for b in active_batches(db) if b.scope == batch.scope), None)
    activate(db, batch, previous, user, "publish")
    return batch_view(batch)


@router.post("/admin/imports/{batch_id}/rollback")
def rollback(batch_id: int, db=Depends(db_session), user=Depends(admin_user)):
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    batch = require_batch(db, batch_id)
    if batch.state != "active":
        raise HTTPException(409, "Откатить можно только действующий импорт")
    previous = db.get(ImportBatch, batch.previous_id) if batch.previous_id else None
    activate(db, previous, batch, user, "rollback")
    return {"active_id": previous.id if previous else None}


@router.get("/schedule")
def schedule(
    scope: str, date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
    entity_id: str = "", building: str = "", offset: int = Query(0, ge=0),
    db=Depends(db_session), user=Depends(current_user),
):
    if scope not in {"group", "teacher", "mine", "room", "building"} or not 0 <= (date_to - date_from).days <= 31:
        raise HTTPException(422, "Укажите режим просмотра и период до 32 дней")
    start = datetime.combine(date_from, datetime.min.time(), CAMPUS)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), CAMPUS)
    filters = {
        "group": Lesson.groups.contains([entity_id]),
        "building": Lesson.building == entity_id,
    }
    if scope == "teacher":
        if user.role != "admin":
            raise HTTPException(403, "Поиск по преподавателю доступен диспетчеру")
        if not entity_id.isascii() or not entity_id.isdecimal() or len(entity_id) > 9 or not building:
            raise HTTPException(422, "Укажите корпус и номер преподавателя")
        teacher = db.scalar(select(TeacherNumber).where(
            TeacherNumber.building == building, TeacherNumber.number == int(entity_id),
        ))
        if teacher is None:
            raise HTTPException(404, "Преподаватель не найден")
        condition = Lesson.teachers.contains([teacher.teacher_key]) & (
            func.coalesce(func.nullif(Lesson.building, ""), "unknown") == building
        )
    elif scope == "mine":
        if user.role != "teacher":
            raise HTTPException(403, "Своё расписание доступно преподавателю")
        link = db.get(TeacherLink, user.id)
        if link is None:
            raise HTTPException(404, "Диспетчер ещё не привязал ваш аккаунт к расписанию")
        condition = Lesson.teachers.contains([link.teacher_key])
    elif scope == "room":
        if not entity_id.isascii() or not entity_id.isdecimal() or len(entity_id) > 9:
            raise HTTPException(422, "Укажите числовой идентификатор аудитории")
        condition = Lesson.room_id == int(entity_id)
    else:
        condition = filters[scope]
    rows = db.scalars(select(Lesson).join(ImportBatch).where(
        ImportBatch.state == "active", condition, Lesson.period.op("&&")(Range(start, end, bounds="[)")),
    ).order_by(func.lower(Lesson.period), Lesson.id).offset(offset).limit(501)).all()
    numbers = directory(db) if user.role == "admin" or scope == "mine" else {}
    items = [dict(id=r.id, start=r.period.lower, end=r.period.upper, subject=display_subject(r.subject),
                  groups=r.groups, teachers=[
                      teacher_view(b, numbers[b, key], key) for key in r.teachers
                      if (b := building_key(r.building), key) in numbers
                  ], building=r.building, room=r.room_code) for r in rows[:500]]
    return {"items": items, "next_offset": offset + 500 if len(rows) > 500 else None,
            "coverage": [dict(scope=b.scope, date_from=b.date_from, date_to=b.date_to, complete=b.complete)
                         for b in active_batches(db)]}


class ConflictAction(BaseModel):
    action: Literal["cancel_booking", "skip_lesson"]
    booking_id: int | None = None
    row_key: str | None = None
    reason: str = Field(min_length=3, max_length=300, pattern=r"\S")


def conflict_row_key(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def detailed_conflicts(db, batch):
    rooms = room_map(db)
    occupied = defaultdict(list)
    current = now(db)
    for interval, booking in db.execute(select(Occupancy, Booking).outerjoin(
        Booking, Occupancy.booking_id == Booking.id,
    ).outerjoin(Hold, Occupancy.hold_id == Hold.id).where(
        Occupancy.kind != "lesson", Occupancy.hold_id.is_(None) | (Hold.expires_at > current),
    )):
        occupied[interval.room_id].append((interval, booking))
    result = []
    for row in batch.rows:
        room_id = rooms.get((row["building"], row["room"]))
        period = row_period(row)
        for interval, booking in occupied.get(room_id, []):
            if interval.period.lower < period.upper and interval.period.upper > period.lower:
                result.append({"row_key": conflict_row_key(row), "room_id": room_id, "start": row["start"], "end": row["end"],
                               "subject": display_subject(row["subject"]), "kind": interval.kind,
                               "booking_id": booking.id if booking else None})
    return result


@router.get("/admin/imports/{batch_id}/conflicts")
def import_conflicts(batch_id: int, db=Depends(db_session), _=Depends(admin_user)):
    return {"items": detailed_conflicts(db, require_batch(db, batch_id))}


@router.post("/admin/imports/{batch_id}/conflicts")
def resolve_conflict(batch_id: int, data: ConflictAction, key: Key, db=Depends(db_session), admin=Depends(admin_user)):
    record = idem(db, admin, f"import_conflict:{batch_id}", key, data)
    if record.result is not None:
        return record.result
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    batch = require_batch(db, batch_id)
    if batch.state != "staged":
        raise HTTPException(409, "Конфликты решаются до публикации")
    rows = detailed_conflicts(db, batch)
    if data.action == "cancel_booking":
        if not data.booking_id or not any(item["booking_id"] == data.booking_id for item in rows):
            raise HTTPException(409, "Эта бронь больше не конфликтует")
        booking = db.get(Booking, data.booking_id)
        lock_room(db, booking.room_id)
        db.refresh(booking, with_for_update=True)
        if booking.cancelled_at is not None:
            raise HTTPException(409, "Бронь уже отменена")
        booking.cancelled_at, booking.cancelled_by = now(db), admin.id
        db.execute(delete(Occupancy).where(Occupancy.booking_id == booking.id))
        db.add(Outbox(user_id=booking.owner_id, kind="cancelled_by_admin",
                      payload={"booking_id": booking.id, "reason": data.reason.strip()}))
        db.add(Audit(actor_id=admin.id, action="booking.cancelled_for_import", object_id=booking.id))
    else:
        if not data.row_key or not any(item["row_key"] == data.row_key for item in rows) or len(batch.rows) < 2:
            raise HTTPException(409, "Нельзя исключить эту пару")
        batch.rows = [row for row in batch.rows if conflict_row_key(row) != data.row_key]
        # A partial import cannot assert complete coverage.
        batch.complete = False
        batch.report = {**batch.report, "lessons": len(batch.rows),
                        "skipped_lessons": batch.report.get("skipped_lessons", 0) + 1}
        db.add(Audit(actor_id=admin.id, action="schedule.lesson_skipped", object_id=batch.id))
    record.result = {"resolved": True}
    db.commit()
    return record.result

@router.get("/schedule/export/{format_name}")
def export_schedule(format_name: Literal["pdf","docx"], scope: str,
                    date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
                    entity_id: str = "", building: str = "", db=Depends(db_session), user=Depends(current_user)):
    if not 0 <= (date_to-date_from).days <= 6:
        raise HTTPException(422, "Выберите период до семи дней")
    items, offset = [], 0
    while offset is not None:
        page = schedule(scope,date_from,date_to,entity_id,building,offset,db,user)
        items.extend(page["items"])
        offset = page["next_offset"]
    filters = {
        "mine":"Моё расписание", "group":f"Группа {entity_id}", "teacher":f"Преподаватель №{entity_id}",
        "room":"Выбранная аудитория", "building":f"Корпус {entity_id}",
    }
    subtitle = f"{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y} | {filters[scope]}"
    days = export_rows(items,date_from,date_to)
    render, media = (as_pdf,"application/pdf") if format_name=="pdf" else (as_docx,DOCX_TYPE)
    return Response(render(subtitle,days),media_type=media,headers={
        "Content-Disposition": f'attachment; filename="campusflow-schedule.{format_name}"',
        "Cache-Control":"no-store",
    })
