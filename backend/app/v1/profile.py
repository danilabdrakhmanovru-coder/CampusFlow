"""Self-service profile and administrative password recovery."""
from datetime import datetime, timedelta, timezone
from os import environ
from secrets import token_urlsafe
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from ..security import password_hash
from .auth import admin_user, current_user, db_session, digest, same_origin, COOKIE
from .catalog import GroupSize
from .models import Audit, Booking, Consent, Identity, PasswordReset, RefreshSession, Room, User
from .schedule_models import ImportBatch, Lesson, TeacherLink, TeacherNumber
from .teachers import teacher_view

router = APIRouter(tags=["profile"])

NOTICE_DEFAULTS = {"watch_hold": True, "cancelled_by_admin": True, "booking_reminder": True, "slot_freed": True}


class Preferences(BaseModel):
    teaching_days_off: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=list, max_length=7)
    group: str | None = Field(default=None, max_length=160)
    building: str | None = Field(default=None, max_length=120)
    theme: Literal["light", "dark", "system"] = "system"
    density: Literal["comfortable", "compact"] = "comfortable"
    notifications: dict[Literal["watch_hold", "cancelled_by_admin", "booking_reminder", "slot_freed"], bool] = Field(default_factory=dict)


def settings(user):
    return Preferences.model_validate(user.preferences or {})


def profile_data(db, user):
    identity = db.scalar(select(Identity.subject).where(Identity.user_id == user.id, Identity.provider == "local"))
    link = db.get(TeacherLink, user.id) if user.role == "teacher" else None
    teacher = db.scalar(select(TeacherNumber).where(TeacherNumber.teacher_key == link.teacher_key)
                        .order_by(TeacherNumber.building).limit(1)) if link else None
    prefs = settings(user).model_dump()
    if user.role == "student":
        prefs["notifications"] = {}
    else:
        prefs["notifications"] = NOTICE_DEFAULTS | prefs["notifications"]
    from .demo_examples import is_demo, PEOPLE
    return {"display_name":PEOPLE.get(identity) if is_demo() else None,"id": user.id, "role": user.role, "login": identity, "institute": environ.get("CAMPUSFLOW_INSTITUTE", "ИИМРТ"),
            "teacher": teacher_view(teacher.building, teacher.number, teacher.teacher_key) if teacher else None,
            "teacher_link_requested_at": user.teacher_link_requested_at if user.role == "teacher" and not link else None,
            "deletion_requested_at": user.deletion_requested_at, "preferences": prefs}


@router.get("/me")
def get_profile(response: Response, db=Depends(db_session), user=Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return profile_data(db, user)


@router.get("/me/preferences")
def get_preferences(db=Depends(db_session), user=Depends(current_user)):
    return profile_data(db, user)["preferences"]


@router.put("/me/preferences")
def save_preferences(data: Preferences, db=Depends(db_session), user=Depends(current_user)):
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    account = db.get(User, user.id, with_for_update=True)
    if user.role != "teacher":
        data.teaching_days_off = []
    elif "teaching_days_off" not in data.model_fields_set:
        data.teaching_days_off = account.preferences.get("teaching_days_off", [])
    else:
        data.teaching_days_off = sorted(set(data.teaching_days_off))
        if data.teaching_days_off != account.preferences.get("teaching_days_off", []):
            db.add(Audit(actor_id=user.id, action="teacher.availability_changed", object_id=user.id))
    if data.group:
        known = db.get(GroupSize, data.group) or db.scalar(select(Lesson.id).join(ImportBatch).where(
            ImportBatch.state == "active", Lesson.groups.contains([data.group]),
        ).limit(1))
        if not known:
            raise HTTPException(422, "Выберите группу из списка")
    if data.building and not db.scalar(select(Room.id).where(Room.building == data.building, Room.active).limit(1)):
        raise HTTPException(422, "Выберите корпус из каталога")
    if user.role == "student":
        data.notifications = {}
    account.preferences = data.model_dump()
    db.commit()
    return profile_data(db, account)["preferences"]


@router.get("/me/sessions")
def sessions(db=Depends(db_session), user=Depends(current_user)):
    rows = db.scalars(select(RefreshSession).where(
        RefreshSession.user_id == user.id, RefreshSession.expires_at > func.now(), RefreshSession.consent_pending.is_(False),
    ).order_by(RefreshSession.created_at.desc()))
    return [{"id": row.device_id, "created_at": row.created_at, "expires_at": row.expires_at,
             "current": row.device_id == user.device} for row in rows]


@router.delete("/me/sessions", status_code=204)
def revoke_sessions(request: Request, response: Response, db=Depends(db_session), user=Depends(current_user)):
    same_origin(request)
    account = db.get(User, user.id, with_for_update=True)
    account.auth_version += 1
    db.execute(delete(RefreshSession).where(RefreshSession.user_id == user.id))
    db.add(Audit(actor_id=user.id, action="user.sessions_revoked", object_id=user.id))
    db.commit()
    response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.delete("/me/sessions/{device_id}", status_code=204)
def revoke_session(device_id: str, request: Request, response: Response, db=Depends(db_session), user=Depends(current_user)):
    same_origin(request)
    db.get(User, user.id, with_for_update=True)
    db.execute(delete(RefreshSession).where(RefreshSession.user_id == user.id, RefreshSession.device_id == device_id))
    db.commit()
    if device_id == user.device:
        response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.post("/me/teacher-link-request", status_code=204)
def request_link(db=Depends(db_session), user=Depends(current_user)):
    account = db.get(User, user.id, with_for_update=True)
    if account.role != "teacher":
        raise HTTPException(403, "Привязка доступна преподавателям")
    if db.get(TeacherLink, user.id):
        raise HTTPException(409, "Аккаунт уже привязан к расписанию")
    if account.teacher_link_requested_at is None:
        account.teacher_link_requested_at = datetime.now(timezone.utc)
        db.add(Audit(actor_id=user.id, action="user.teacher_link_requested", object_id=user.id))
        db.commit()


@router.post("/me/deletion-request", status_code=204)
def request_deletion(db=Depends(db_session), user=Depends(current_user)):
    account = db.get(User, user.id, with_for_update=True)
    if account.deletion_requested_at is None:
        account.deletion_requested_at = datetime.now(timezone.utc)
        db.add(Audit(actor_id=user.id, action="user.deletion_requested", object_id=user.id))
        db.commit()


@router.get("/me/export")
def export(response: Response, db=Depends(db_session), user=Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="campusflow-my-data.json"'
    return {
        "profile": profile_data(db, user),
        "consents": [{"version": row.version, "accepted_at": row.at, "withdrawn_at": row.withdrawn_at}
                     for row in db.scalars(select(Consent).where(Consent.user_id == user.id))],
        "bookings": [{"room_id": row.room_id, "title": row.title, "start": row.period.lower,
                      "end": row.period.upper, "cancelled_at": row.cancelled_at}
                     for row in db.scalars(select(Booking).where(Booking.owner_id == user.id))],
    }


@router.post("/admin/users/{user_id}/password-reset")
def create_reset(user_id: int, response: Response, db=Depends(db_session), admin=Depends(admin_user)):
    account = db.get(User, user_id, with_for_update=True)
    if not account or not account.active:
        raise HTTPException(404, "Активный аккаунт не найден")
    token = token_urlsafe(32)
    values = {"digest": digest(token), "expires_at": datetime.now(timezone.utc)+timedelta(minutes=30)}
    stmt = insert(PasswordReset).values(user_id=user_id, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[PasswordReset.user_id], set_=values))
    db.add(Audit(actor_id=admin.id, action="user.password_reset_issued", object_id=user_id))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"path": "/reset-password#"+token, "expires_at": values["expires_at"]}


class ResetPassword(BaseModel):
    token: str = Field(min_length=32, max_length=100)
    password: str = Field(min_length=12,max_length=128)


@router.post("/password-reset", status_code=204)
def reset_password(data: ResetPassword, request: Request, db=Depends(db_session)):
    same_origin(request)
    if not any(c.isalpha() for c in data.password) or not any(c.isdigit() for c in data.password):
        raise HTTPException(422, "Пароль должен содержать буквы и цифры")
    match = (PasswordReset.digest == digest(data.token), PasswordReset.expires_at > func.now())
    user_id = db.scalar(select(PasswordReset.user_id).where(*match))
    account = db.get(User, user_id, with_for_update=True) if user_id is not None else None
    if not account or not account.active or db.execute(delete(PasswordReset).where(*match)).rowcount != 1:
        raise HTTPException(404, "Ссылка устарела. Запросите новую у диспетчера")
    identity = db.scalar(select(Identity).where(Identity.user_id == user_id, Identity.provider == "local"))
    if not identity:
        raise HTTPException(404, "Аккаунт для восстановления не найден")
    identity.password_hash = password_hash(data.password)
    account.auth_version += 1
    db.execute(delete(RefreshSession).where(RefreshSession.user_id == user_id))
    db.add(Audit(actor_id=user_id, action="user.password_reset", object_id=user_id))
    db.commit()


@router.get("/catalog/groups")
def groups(db=Depends(db_session), user=Depends(current_user)):
    sizes = {r.group_code:r.size for r in db.scalars(select(GroupSize))}
    codes = set(db.scalars(select(func.jsonb_array_elements_text(Lesson.groups)).select_from(Lesson).join(ImportBatch)
                            .where(ImportBatch.state == "active").distinct()))
    return [{"code": code, "size": sizes.get(code)} for code in sorted(codes | sizes.keys())]
