"""Group-only analytics and automatically generated proposals."""
from collections import defaultdict
from datetime import date, timedelta
from hashlib import sha256
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from .analytics import BELL, OptimizationRequest, Requirements, covered, fits_bell_slot, lessons, moment, optimize_day, periods
from .auth import admin_user, schedule_staff, db_session
from .bookings import CAMPUS
from .catalog import GroupSize, WalkingTime
from .db import Base
from .models import Audit, Room
from .ollama import GapExplanation, analyze_gaps, anonymized_metrics
from .ranking import Feedback, model_status, scores, train, trained_model
from .schedule import display_subject
from .schedule_models import Lesson, Proposal, TeacherLink
from .teachers import building_key, directory, teacher_view
from .teaching_rules import teacher_gaps

router = APIRouter(tags=["group-insights"])
KINDS = {"lecture":0,"computer":1,"laboratory":2,"seminar":3}
REASONS = {"approved", "pedagogy", "coordination", "room", "other"}


class LessonPin(Base):
    __tablename__ = "lesson_pins"
    key: Mapped[str] = mapped_column(primary_key=True)


def pin_key(row):
    return sha256(json.dumps([row.building,row.room_code,row.subject,sorted(row.groups),
                              sorted(row.teachers),row.period.lower.isoformat(),row.period.upper.isoformat()],
                             ensure_ascii=False).encode()).hexdigest()


def visible_groups(db, user, rows):
    if user.role in {"dean", "admin"}:
        return {group for row in rows for group in row.groups}
    link = db.get(TeacherLink,user.id)
    return {group for row in rows if link and link.teacher_key in row.teachers for group in row.groups}


def course_for(group):
    # Use an explicit course marker only; admission year is not a course number.
    match = re.search(r"(?:курс|курс-)[ -]*([1-6])\b", group, re.I)
    return int(match[1]) if match else None


def group_metrics(group, rows, lengths, routes, minimum=40):
    ordered = sorted(rows,key=lambda r:(r.period.lower,r.period.upper,r.id))
    windows, days, transitions = [], set(), 0
    prior = None
    prior_day = None
    for row in ordered:
        day = row.period.lower.astimezone(CAMPUS).date()
        if prior_day != day:
            prior = None
            prior_day = day
        if prior and prior.period.upper.astimezone(CAMPUS).date()==day:
            if row.period.lower >= prior.period.upper:
                minutes = int((row.period.lower-prior.period.upper).total_seconds()//60)
                change = bool(prior.building and row.building and prior.building != row.building)
                walk = routes.get((prior.room_id,row.room_id)) if change else 0
                transitions += int(change)
                available = max(0,minutes-(walk or 0))
                if available >= minimum and fits_bell_slot(day,prior.period.upper,row.period.lower):
                    days.add(day)
                    windows.append({"day":day,"minutes":available,"break_minutes":minutes,"walking_minutes":walk,
                                    "from_id":prior.id,"to_id":row.id,"before":display_subject(prior.subject),"after":display_subject(row.subject),
                                    "start":prior.period.upper,"end":row.period.lower,
                                    "building":row.building,"transfer":change})
        if not prior or row.period.upper>prior.period.upper:
            prior=row
    total = sum(w["minutes"] for w in windows)
    largest = max((w["minutes"] for w in windows),default=0)
    size = lengths.get(group)
    teaching_days = {row.period.lower.astimezone(CAMPUS).date() for row in ordered}
    compact_days = len(teaching_days-days)
    penalty = min(100, round(total/12+largest/12+len(windows)*2+transitions*4))
    summary = {"group":group,"course":course_for(group),"size":size,"status":"unknown_size" if size is None else "small" if size<5 else "ready",
               "total":total,"count":len(windows),"largest":largest,"days":len(days),"transitions":transitions,
               "score":penalty, "quality":100-penalty, "lesson_count":len(ordered),
               "teaching_days":len(teaching_days), "compact_days":compact_days}
    if size is not None and size<5:
        return {**summary, **dict.fromkeys(["total","count","largest","days","transitions","score","quality","lesson_count","teaching_days","compact_days"])}, []
    return summary, windows


def load(db, user, start, end):
    if not 0 <= (end-start).days <= 200:
        raise HTTPException(422,"Укажите период до 201 дня")
    rows=lessons(db,periods(start,end))
    authorized=visible_groups(db,user,rows)
    lengths={r.group_code:r.size for r in db.scalars(select(GroupSize))}
    routes={(r.from_room_id,r.to_room_id):r.minutes for r in db.scalars(select(WalkingTime))}
    return rows,authorized,lengths,routes


@router.get("/analytics/groups/windows")
def groups_windows(start:date,end:date,building:str|None=None,course:int|None=None,minimum:int=Query(40,ge=1,le=480),
                   db=Depends(db_session),user=Depends(schedule_staff)):
    rows,allowed,lengths,routes=load(db,user,start,end)
    grouped=defaultdict(list)
    for row in rows:
        for group in set(row.groups)&allowed:
            grouped[group].append(row)
    result=[group_metrics(group,items,lengths,routes,minimum)[0] for group,items in grouped.items()
            if (not building or any(row.building==building for row in items)) and (not course or course_for(group)==course)]
    return {"items":sorted(result,key=lambda r:(-(r["score"] or 0),r["group"])),
            "missing_sizes":sum(r["size"] is None for r in result),
            "formula":"Качество = 100 − штраф. Штраф = минуты окон ÷ 12 + самое длинное окно ÷ 12 + число окон × 2 + смены корпуса × 4, округлённый и ограниченный 100. Чем выше качество, тем удобнее расписание. Дни без окон показаны отдельно. Это стартовые веса прототипа."}


def group_detail(db,user,group,start,end,minimum=40):
    rows,allowed,lengths,routes=load(db,user,start,end)
    if group not in allowed:
        raise HTTPException(404, "Группа недоступна за выбранный период")
    selected=[row for row in rows if group in row.groups]
    summary,windows=group_metrics(group,selected,lengths,routes,minimum)
    return selected,summary,windows


@router.get("/analytics/groups/{group}/windows")
def windows_for_group(group:str,start:date,end:date,minimum:int=Query(40,ge=1,le=480),
                      db=Depends(db_session),user=Depends(schedule_staff)):
    selected,summary,windows=group_detail(db,user,group,start,end,minimum)
    numbers=directory(db)
    pins=set(db.scalars(select(LessonPin.key)))
    return {"summary":summary,"windows":windows,"lessons":[] if summary["status"]=="small" else [
        {"id":r.id,"start":r.period.lower,"end":r.period.upper,"subject":display_subject(r.subject),"building":r.building,
         "room":r.room_code,"pinned":pin_key(r) in pins,
         "teachers":[teacher_view(b,numbers[b,key],key) for key in r.teachers
                     if (b:=building_key(r.building),key) in numbers]}
        for r in selected]}


class GapAnalysis(BaseModel):
    start: date
    end: date
    minimum: int = Field(default=40, ge=1, le=480)


@router.post("/analytics/groups/{group}/analysis", response_model=GapExplanation)
def analyze_group(group: str, data: GapAnalysis, db=Depends(db_session), user=Depends(schedule_staff)):
    _, summary, windows = group_detail(db,user,group,data.start,data.end,data.minimum)
    if summary["status"] != "ready":
        raise HTTPException(422, "Для ИИ-анализа нужен подтверждённый размер группы от пяти человек")
    if not windows:
        raise HTTPException(422, "За выбранный период нет окон для анализа")
    metrics = anonymized_metrics(summary,windows,data.start,data.end,data.minimum)
    db.rollback()
    return analyze_gaps(metrics)


class Search(BaseModel):
    start:date
    end:date
    lesson_id:int|None=None


@router.post("/analytics/groups/{group}/suggestions")
def suggestions(group:str,data:Search,db=Depends(db_session),user=Depends(schedule_staff)):
    if not 0 <= (data.end-data.start).days <= 6:
        raise HTTPException(422,"Выберите неделю или меньший период")
    selected,summary,windows=group_detail(db,user,group,data.start,data.end)
    if summary["status"]!="ready":
        return {"items":[],"status":"missing_group_size" if summary["size"] is None else "small_group"}
    by_id={row.id:row for row in selected}
    lengths={r.group_code:r.size for r in db.scalars(select(GroupSize))}
    routes={(r.from_room_id,r.to_room_id):r.minutes for r in db.scalars(select(WalkingTime))}
    rooms={row.id:row for row in db.scalars(select(Room))}
    pins=set(db.scalars(select(LessonPin.key)))
    seen=set()
    model=trained_model(db)
    expected=[]
    link=db.get(TeacherLink,user.id) if user.role=="teacher" else None
    all_rows = lessons(db, periods(data.start, data.end))
    before_teachers = teacher_gaps([
        {"teachers": r.teachers, "period": r.period} for r in all_rows
    ], CAMPUS)
    for window in sorted(windows,key=lambda w:-w["minutes"]):
        for key in (window["from_id"],window["to_id"]):
            if key in seen or (data.lesson_id and key!=data.lesson_id):
                continue
            seen.add(key)
            if len(seen)>6:
                break
            row=by_id[key]
            if link and link.teacher_key not in row.teachers:
                continue
            origin=rooms.get(row.room_id)
            local=row.period.lower.astimezone(CAMPUS)
            day=local.date()
            if not origin or not origin.kind or not row.teachers or pin_key(row) in pins or not all(group in lengths for group in row.groups):
                continue
            if row.building not in covered(db,day):
                continue
            try:
                plan=optimize_day(OptimizationRequest(day=data.start,end_day=data.end,future_only=True,requirements={
                    row.id:Requirements(kind=origin.kind,people=sum(lengths[g] for g in row.groups),
                                        equipment=[k for k,v in origin.equipment.items() if v],accessible=bool(origin.accessible)),
                }),db,user)
            except HTTPException as error:
                if error.status_code not in {409,422}:
                    raise
                db.rollback()
                continue
            if not plan.get("id") or not plan.get("assignments"):
                continue
            target=plan["assignments"][0]
            dest=rooms[target["room_id"]]
            target_day=target["date"]
            a,b=BELL[target["slot"]-1]
            from types import SimpleNamespace
            from sqlalchemy.dialects.postgresql import Range
            moved=SimpleNamespace(id=row.id,period=Range(moment(target_day,a),moment(target_day,b),bounds="[)"),
                                  building=dest.building,room_id=dest.id,subject=row.subject)
            revised,_=group_metrics(group,[r for r in selected if r.id!=row.id]+[moved],lengths,routes)
            gain=summary["total"]-revised["total"]
            proposal=db.get(Proposal,plan["id"])
            after_teachers = teacher_gaps([
                {"teachers": r.teachers, "period": moved.period if r.id==row.id else r.period}
                for r in all_rows
            ], CAMPUS)
            if gain<=0 or any(after_teachers[t] > before_teachers[t] for t in row.teachers):
                db.delete(proposal);db.commit();continue
            features=[window["minutes"],day.weekday(),plan["original"][0]["slot"],int(dest.building!=row.building),
                      KINDS[origin.kind],summary["size"],len(row.groups),len(row.teachers)]
            chance,value=scores(model,features)
            item={"id":plan["id"],"group":group,"subject":display_subject(row.subject),"lesson_id":row.id,
                  "original":{"start":row.period.lower.isoformat(),"end":row.period.upper.isoformat(),"room":origin.code,"building":origin.building},
                  "target":{"start":moved.period.lower.isoformat(),"end":moved.period.upper.isoformat(),"room":dest.code,"building":dest.building},
                  "gain":gain,"before":summary["total"],"after":revised["total"],"transitions_before":summary["transitions"],
                  "transitions_after":revised["transitions"],"groups":len(row.groups),"teachers":len(row.teachers),
                  "acceptance":chance,"expected_value":value}
            item["teacher_breaks_before"] = sum(before_teachers[t] for t in row.teachers)
            item["teacher_breaks_after"] = sum(after_teachers[t] for t in row.teachers)
            proposal.result={**proposal.result,"suggestion":item,"features":features}
            db.commit()
            expected.append(item)
            if len(expected)>=5:
                break
        if len(expected)>=5 or len(seen)>6:
            break
    return {"status":"ready","items":sorted(expected,key=lambda item:-(item["expected_value"] if item["expected_value"] is not None else item["gain"]))}


class Decision(BaseModel):
    accepted:bool
    reason:str=Field(max_length=60)


@router.post("/suggestions/{proposal_id}/decision")
def decide(proposal_id:int,data:Decision,db=Depends(db_session),admin=Depends(schedule_staff)):
    proposal=db.get(Proposal,proposal_id,with_for_update=True)
    if not proposal or not proposal.result.get("suggestion"):
        raise HTTPException(404,"Предложение не найдено")
    if data.reason not in REASONS or data.accepted!=(data.reason=="approved"):
        raise HTTPException(422,"Укажите причину решения")
    if data.accepted and proposal.applied is None:
        raise HTTPException(409,"Сначала примените перенос и проверьте отсутствие конфликтов")
    if not data.accepted and proposal.applied is not None:
        raise HTTPException(409,"Предложение уже применено")
    previous=db.get(Feedback,proposal_id)
    if previous:
        if previous.accepted==data.accepted and previous.reason==data.reason:
            return {"saved":True}
        raise HTTPException(409,"Решение уже зарегистрировано")
    db.add(Feedback(proposal_id=proposal_id,accepted=data.accepted,reason=data.reason,features=proposal.result["features"],
                    gain=proposal.result["suggestion"]["gain"]))
    db.add(Audit(actor_id=admin.id,action="proposal.decided",object_id=proposal_id))
    db.commit()
    return {"saved":True}


@router.get("/analytics/model")
def model(db=Depends(db_session),_=Depends(admin_user)):
    return model_status(db)


@router.post("/analytics/model/train")
def retrain(db=Depends(db_session),_=Depends(admin_user)):
    return train(db)


@router.put("/admin/lessons/{lesson_id}/pin")
def pin(lesson_id:int,pinned:bool,db=Depends(db_session),admin=Depends(schedule_staff)):
    from sqlalchemy import text
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    row=db.get(Lesson,lesson_id)
    if not row:
        raise HTTPException(404,"Занятие не найдено")
    key=pin_key(row)
    existing=db.get(LessonPin,key)
    if pinned and not existing:
        db.add(LessonPin(key=key))
    elif not pinned and existing:
        db.delete(existing)
    db.add(Audit(actor_id=admin.id,action="lesson.pinned" if pinned else "lesson.unpinned",object_id=lesson_id))
    db.commit()
    return {"pinned":pinned}
