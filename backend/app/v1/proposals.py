from collections import defaultdict
from datetime import date
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .analytics import BELL, moment
from .auth import schedule_staff, db_session
from .bookings import CAMPUS, Key, idem, lock_room, now
from .teaching_rules import days_off, teacher_gaps
from .models import Audit
from .ranking import Feedback
from .group_insights import LessonPin, pin_key
from .schedule import active_batches, materialize_lessons, rebuild_occupancy, room_map, row_period
from .schedule_models import ImportBatch, Lesson, Proposal

router = APIRouter(tags=["proposals"])


@router.get("/admin/proposals")
def proposals(db=Depends(db_session), _=Depends(schedule_staff)):
    return [{"id": p.id, "applied": p.applied, "decision": feedback.accepted if (feedback:=db.get(Feedback,p.id)) else None, **p.result} for p in db.scalars(
        select(Proposal).order_by(Proposal.id.desc()).limit(20)
    )]


class Apply(BaseModel):
    lesson_ids: list[int] = Field(min_length=1)


def overlaps(left, right):
    return left.lower < right.upper and right.lower < left.upper


@router.post("/admin/proposals/{proposal_id}/apply")
def apply(proposal_id: int, data: Apply, key: Key, db=Depends(db_session), admin=Depends(schedule_staff)):
    receipt = idem(db, admin, f"apply:{proposal_id}", key, data)
    if receipt.result is not None:
        return receipt.result
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    proposal = db.get(Proposal, proposal_id, with_for_update=True)
    if not proposal:
        raise HTTPException(404, "Предложение не найдено")
    batches = active_batches(db)
    feedback = db.get(Feedback, proposal_id)
    if feedback and not feedback.accepted:
        raise HTTPException(409, "Предложение уже отклонено")
    if proposal.applied is not None or sorted(b.id for b in batches) != proposal.source_versions:
        raise HTTPException(409, "Расписание изменилось. Пересчитайте предложение.")
    choices = {item["lesson_id"]: item for item in proposal.result["assignments"]}
    originals = {item["lesson_id"]: item for item in proposal.result["original"]}
    selected = set(data.lesson_ids)
    if not selected <= choices.keys():
        raise HTTPException(422, "Выберите занятия из предложения")
    selected = {i for i in selected if any(choices[i][k] != originals[i][k] for k in ("room_id", "date", "slot"))}
    if not selected:
        raise HTTPException(422, "В выбранных занятиях нет изменений")
    rooms = room_map(db)
    by_room = {value: key for key, value in rooms.items()}
    by_id = {b.id: b for b in batches}
    by_scope = {b.scope: b for b in batches}
    replacements = {b.id: list(b.rows) for b in batches}
    availability = days_off(db)
    before_gaps = teacher_gaps([
        {"teachers": row["teachers"], "period": row_period(row)}
        for batch in batches for row in batch.rows
    ], CAMPUS)
    # Rebuild acquires room locks in ascending order, including the affected rooms.
    catalog = {room_id: lock_room(db, room_id) for room_id in sorted(by_room)}
    changed, moving = set(), []
    for lesson_id in sorted(selected):
        lesson = db.get(Lesson, lesson_id)
        if lesson and db.get(LessonPin,pin_key(lesson)):
            raise HTTPException(409, "Это занятие закреплено")
        if lesson is None or lesson.batch_id not in by_id:
            raise HTTPException(409, "Исходное занятие изменилось")
        option = choices[lesson_id]
        location = by_room.get(option["room_id"])
        day = date.fromisoformat(option["date"])
        if any(day.weekday() in availability[teacher] for teacher in lesson.teachers):
            raise HTTPException(409, "У преподавателя день без занятий. Пересчитайте предложение.")
        room = catalog.get(option["room_id"])
        requirements = proposal.result["room_requirements"][str(lesson_id)]
        if not room or not room.active or room.kind != requirements["kind"] or (room.capacity or 0) < requirements["size"] or (
            requirements["accessible"] and not room.accessible
        ) or not all(room.equipment.get(item) for item in requirements["equipment"]):
            raise HTTPException(409, "Параметры аудитории изменились. Пересчитайте предложение.")
        if location is None:
            raise HTTPException(409, "Аудитория больше недоступна")
        coverage = by_scope.get(location[0])
        if not coverage or not coverage.complete or not coverage.date_from <= day <= coverage.date_to:
            raise HTTPException(409, "Расписание корпуса больше не покрывает выбранную дату")
        source = replacements[lesson.batch_id]
        matches = [r for r in source if (r["building"], r["room"], r["subject"]) ==
                   (lesson.building, lesson.room_code, lesson.subject) and
                   r["groups"] == lesson.groups and r["teachers"] == lesson.teachers and row_period(r) == lesson.period]
        if len(matches) != 1:
            raise HTTPException(409, "Не удалось однозначно найти исходную пару")
        original = matches[0]
        source.remove(original)
        start_time,end_time = (moment(day, minutes) for minutes in BELL[option["slot"] - 1])
        if proposal.result.get("suggestion") and min(start_time,lesson.period.lower)<=now(db):
            raise HTTPException(409,"Занятие уже началось. Пересчитайте предложение.")
        start,end = start_time.isoformat(),end_time.isoformat()
        target = coverage if by_id[lesson.batch_id].scope != "iimrt" else by_id[lesson.batch_id]
        if not target.date_from <= day <= target.date_to:
            raise HTTPException(409, "Занятие выйдет за период исходной выгрузки")
        row = {**original, "start":start, "end":end, "building":location[0], "room":location[1]}
        changed.update((lesson.batch_id, target.id))
        moving.append((target.id, row))

    resources = defaultdict(list)
    def labels(row):
        return [("room", row["building"], row["room"]),
                *(("group", g) for g in row["groups"]), *(("teacher", t) for t in row["teachers"])]
    for rows in replacements.values():
        for row in rows:
            for label in labels(row):
                resources[label].append(row_period(row))
    for batch_id, row in moving:
        period = row_period(row)
        for label in labels(row):
            if any(overlaps(period, busy) for busy in resources[label]):
                raise HTTPException(409, "Частичное применение создаёт пересечение. Выберите связанные переносы вместе.")
            resources[label].append(period)
        replacements[batch_id].append(row)

    after_gaps = teacher_gaps([
        {"teachers": row["teachers"], "period": row_period(row)}
        for rows in replacements.values() for row in rows
    ], CAMPUS)
    if any(minutes > before_gaps[teacher] for teacher, minutes in after_gaps.items()):
        raise HTTPException(409, "Перенос увеличивает перерывы преподавателя. Пересчитайте предложение.")
    updated = []
    for batch in batches:
        if batch.id not in changed:
            updated.append(batch)
            continue
        rows = replacements[batch.id]
        replacement = ImportBatch(
            actor_id=admin.id, scope=batch.scope, date_from=batch.date_from, date_to=batch.date_to,
            source_name="optimization", sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            state="active", rows=rows, mapping=batch.mapping, complete=batch.complete, previous_id=batch.id,
            report={**batch.report, "lessons": len(rows)},
        )
        batch.state = "archived"
        db.add(replacement)
        db.flush()
        if rows:
            materialize_lessons(db, replacement, rooms)
        updated.append(replacement)
    rebuild_occupancy(db, updated, rooms, {b.scope for b in batches if b.id in changed})
    proposal.applied = sorted(selected)
    if proposal.result.get("suggestion") and feedback is None:
        db.add(Feedback(proposal_id=proposal.id,accepted=True,reason="approved",features=proposal.result["features"],
                        gain=proposal.result["suggestion"]["gain"]))
    receipt.result = {"applied": sorted(selected)}
    db.add(Audit(actor_id=admin.id, action="proposal.applied", object_id=proposal.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23P01":
            raise HTTPException(409, "Занятость изменилась. Пересчитайте предложение.") from exc
        raise
    return receipt.result
