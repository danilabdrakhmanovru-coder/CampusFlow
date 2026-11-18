"""Operational summary and settings exposed only to dispatchers."""
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from .activity_models import Ticket
from .analytics import covered, lessons, periods
from .auth import admin_user, db_session
from .bookings import CAMPUS, now
from .catalog import GroupSize, WalkingTime
from .models import Audit, Booking, Room, User
from .privacy import policy_version
from .schedule import detailed_conflicts
from .schedule_models import ImportBatch
from .site_config import SitePreferences, site_preferences

router=APIRouter(tags=["dispatch"])


@router.get("/admin/overview")
def overview(day:date|None=None,db=Depends(db_session),_=Depends(admin_user)):
    clock=now(db)
    day=day or clock.astimezone(CAMPUS).date()
    buildings=set(db.scalars(select(Room.building).where(Room.active).distinct()))
    incomplete=sorted(buildings-covered(db,day))
    staged=list(db.scalars(select(ImportBatch).where(ImportBatch.state=="staged").order_by(ImportBatch.id.desc()).limit(20)))
    pending=sum(len(detailed_conflicts(db,batch)) for batch in staged)
    groups={key for row in lessons(db,periods(day,day+timedelta(days=6))) for key in row.groups}
    known=set(db.scalars(select(GroupSize.group_code)))
    active=db.scalar(select(func.count()).select_from(Booking).where(Booking.cancelled_at.is_(None),Booking.period.op("&&")(periods(day,day))))
    due=db.execute(select(Ticket.booking_id,Ticket.auto_release_at).join(Booking).where(
        Booking.cancelled_at.is_(None),Ticket.check_in_at.is_(None),Ticket.auto_release_at>clock,
        Ticket.auto_release_at<clock+timedelta(hours=4),
    ).order_by(Ticket.auto_release_at).limit(12)).all()
    recent=db.scalars(select(Audit).order_by(Audit.id.desc()).limit(8))
    requests=db.scalar(select(func.count()).select_from(User).where(User.active,User.deletion_requested_at.is_not(None)|User.teacher_link_requested_at.is_not(None)))
    return {"day":day,"uncovered_buildings":incomplete,"conflicts":pending,"checked_staged_imports":len(staged),
            "missing_group_sizes":sorted(groups-known),"bookings_today":active,"requests":requests,
            "auto_releases":[{"booking_id":row.booking_id,"at":row.auto_release_at} for row in due],
            "actions":[{"id":row.id,"action":row.action,"at":row.at} for row in recent]}


class Settings(BaseModel):
    operator: str | None = Field(default=None,max_length=250)
    responsible: str | None = Field(default=None,max_length=250)
    contact: str | None = Field(default=None,max_length=160)
    effective_date: date | None = None
    version: str = Field(min_length=1,max_length=80,pattern=r"^\S+$")
    support_email: str | None = Field(default=None,max_length=160,pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    support_hours: str | None = Field(default=None,max_length=200)
    booking_days: int = Field(ge=1,le=3650)
    audit_days: int = Field(ge=1,le=3650)
    session_days: int = Field(ge=1,le=3650)


@router.get("/admin/settings")
def settings(db=Depends(db_session),_=Depends(admin_user)):
    info=site_preferences(db)
    return {**info,"version":policy_version(db),
            "booking_days":int(info["booking_days"] or 365),"audit_days":int(info["audit_days"] or 365),"session_days":int(info["session_days"] or 1)}


@router.put("/admin/settings")
def save_settings(data:Settings,db=Depends(db_session),admin=Depends(admin_user)):
    db.execute(text("SELECT pg_advisory_xact_lock(61206704)"))
    previous=settings(db,admin)
    changes=data.model_dump(mode="json")
    public_keys=set(changes)-{"support_email","support_hours","version"}
    if any(previous[k]!=changes[k] for k in public_keys) and data.version==previous["version"]:
        raise HTTPException(422,"Укажите новую версию документов после изменения реквизитов или сроков")
    if data.version!=previous["version"]:
        from .models import Consent
        if db.scalar(select(Consent.id).where(Consent.version==data.version).limit(1)):
            raise HTTPException(422,"Эта редакция уже использовалась. Укажите новый номер.")
    record=db.get(SitePreferences,1)
    if record is None:
        db.add(SitePreferences(id=1,data=changes))
    else:
        record.data=changes
    db.add(Audit(actor_id=admin.id, action="site.settings_changed",object_id=1))
    db.commit()
    return {"version":data.version}


@router.get("/admin/walking-times")
def walking(db=Depends(db_session),_=Depends(admin_user)):
    rooms={room.id:room for room in db.scalars(select(Room))}
    return [{"from":rooms[row.from_room_id].building+" — "+rooms[row.from_room_id].code,
             "to":rooms[row.to_room_id].building+" — "+rooms[row.to_room_id].code,"minutes":row.minutes}
            for row in db.scalars(select(WalkingTime).order_by(WalkingTime.from_room_id,WalkingTime.to_room_id).limit(1000))]
