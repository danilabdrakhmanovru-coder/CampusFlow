from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert

from ..security import password_hash
from .auth import admin_user, db_session
from .catalog import GroupSize, WalkingTime
from .models import Audit, Identity, Room, User
from .schedule_models import ImportBatch, TeacherLink, TeacherNumber
from .retention import erase_account
from .teachers import teacher_view
from .schedule import batch_view

router = APIRouter(tags=["workspace"])


@router.get("/admin/imports")
def imports(db=Depends(db_session), _=Depends(admin_user)):
    return [{key: value for key, value in batch_view(row).items() if key != "preview"}
            for row in db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(100))]


class RoomData(BaseModel):
    building: str = Field(min_length=1,max_length=16,pattern=r"^[0-9A-Za-zА-Яа-я_-]+$")
    code: str = Field(min_length=1, max_length=100, pattern=r"\S")
    floor: int | None = Field(default=None, ge=-5, le=50)
    kind: Literal["lecture", "computer", "laboratory", "seminar"]
    capacity: int = Field(gt=0, le=10000)
    equipment: dict[str, int] = Field(default_factory=dict)
    accessible: bool | None = None
    plan_x: float | None = Field(default=None, ge=0, le=100)
    plan_y: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_coordinates(self):
        if (self.plan_x is None) != (self.plan_y is None):
            raise ValueError("Укажите обе координаты плана")
        return self


def save_room(db, admin, room, data):
    for field, value in data.model_dump().items():
        setattr(room, field, value.strip() if isinstance(value, str) else value)
    db.add(room)
    try:
        db.flush()
        db.add(Audit(actor_id=admin.id, action="room.saved", object_id=room.id))
        db.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "Такой номер уже существует в этом корпусе") from exc
    return {"id": room.id}


@router.post("/admin/rooms", status_code=201)
def create_room(data: RoomData, db=Depends(db_session), admin=Depends(admin_user)):
    return save_room(db, admin, Room(), data)


@router.put("/admin/rooms/{room_id}")
def update_room(room_id: int, data: RoomData, db=Depends(db_session), admin=Depends(admin_user)):
    room = db.get(Room, room_id, with_for_update=True)
    if room is None:
        raise HTTPException(404, "Аудитория не найдена")
    if (data.building, data.code.strip()) != (room.building, room.code):
        raise HTTPException(422, "Корпус и номер существующей аудитории менять нельзя")
    return save_room(db, admin, room, data)


class UserData(BaseModel):
    login: str = Field(pattern=r"^[a-z0-9._-]{1,100}$")
    password: str = Field(min_length=12, max_length=128)
    role: Literal["student", "teacher", "dean", "admin"]


@router.get("/admin/users")
def users(offset: int = Query(0, ge=0), q: str = Query("",max_length=100), db=Depends(db_session), _=Depends(admin_user)):
    rows = db.execute(select(User, Identity.subject).join(Identity).where(
        Identity.provider == "local", Identity.subject.contains(q,autoescape=True)).order_by(User.id).offset(offset).limit(100))
    from .demo_examples import is_demo, PEOPLE
    return [{"id": user.id, "role": user.role, "active": user.active, "login": login,
             "display_name": PEOPLE.get(login) if is_demo() else None,
             "teaching_days_off": user.preferences.get("teaching_days_off", []) if user.role=="teacher" else [],
             "teacher_link_requested_at": user.teacher_link_requested_at,
             "deletion_requested_at": user.deletion_requested_at} for user, login in rows]


@router.post("/admin/users", status_code=201)
def create_user(data: UserData, db=Depends(db_session), admin=Depends(admin_user)):
    user = User(role=data.role)
    db.add(user)
    db.flush()
    db.add(Identity(user_id=user.id, provider="local", subject=data.login,
                    password_hash=password_hash(data.password)))
    db.add(Audit(actor_id=admin.id, action="user.created", object_id=user.id))
    try:
        db.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "Логин уже занят") from exc
    return {"id": user.id}


class UserUpdate(BaseModel):
    role: Literal["student", "teacher", "dean", "admin"]
    active: bool


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, db=Depends(db_session), admin=Depends(admin_user)):
    if user_id == admin.id:
        raise HTTPException(422, "Для изменения своей роли или статуса нужен другой администратор")
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    if data.role != "teacher":
        link = db.get(TeacherLink, user_id)
        if link:
            db.delete(link)
    user.role, user.active = data.role, data.active
    user.auth_version += 1
    db.add(Audit(actor_id=admin.id, action="user.updated", object_id=user.id))
    db.commit()
    return {"id": user.id}


class LinkData(BaseModel):
    building: str = Field(min_length=1, max_length=120)
    number: int = Field(gt=0)


@router.put("/admin/users/{user_id}/teacher-link")
def link_teacher(user_id: int, data: LinkData, db=Depends(db_session), admin=Depends(admin_user)):
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    user = db.get(User, user_id, with_for_update=True)
    if user is None or not user.active or user.role != "teacher":
        raise HTTPException(422, "Выберите активный аккаунт преподавателя")
    teacher = db.scalar(select(TeacherNumber).where(
        TeacherNumber.building == data.building, TeacherNumber.number == data.number,
    ))
    if teacher is None:
        raise HTTPException(404, "Преподаватель не найден")
    linked = db.get(TeacherLink, user_id)
    if linked:
        linked.teacher_key = teacher.teacher_key
    else:
        db.add(TeacherLink(user_id=user_id, teacher_key=teacher.teacher_key))
    user.teacher_link_requested_at = None
    db.add(Audit(actor_id=admin.id, action="user.teacher_linked", object_id=user_id))
    try:
        db.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "Этот преподаватель уже привязан к другому аккаунту") from exc
    return teacher_view(teacher.building, teacher.number)


@router.delete("/admin/users/{user_id}/teacher-link", status_code=204)
def unlink_teacher(user_id: int, db=Depends(db_session), admin=Depends(admin_user)):
    db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
    db.get(User, user_id, with_for_update=True)
    link = db.get(TeacherLink, user_id)
    if link:
        db.delete(link)
        db.add(Audit(actor_id=admin.id, action="user.teacher_unlinked", object_id=user_id))
        db.commit()


@router.delete("/admin/users/{user_id}/data", status_code=204)
def delete_user_data(user_id: int, db=Depends(db_session), admin=Depends(admin_user)):
    if user_id == admin.id:
        raise HTTPException(422, "Для удаления своего аккаунта обратитесь к другому администратору")
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    erase_account(db, user)
    db.add(Audit(actor_id=admin.id, action="user.erased", object_id=user_id))
    db.commit()

class GroupSizes(BaseModel):
    sizes: dict[str, Annotated[int, Field(ge=1, le=10000)]] = Field(min_length=1, max_length=2000)


@router.get("/admin/group-sizes")
def group_sizes(db=Depends(db_session), _=Depends(admin_user)):
    return {row.group_code: row.size for row in db.scalars(select(GroupSize).order_by(GroupSize.group_code))}


@router.put("/admin/group-sizes")
def save_group_sizes(data: GroupSizes, db=Depends(db_session), _=Depends(admin_user)):
    if any(not key or key != key.strip() or len(key) > 160 for key in data.sizes):
        raise HTTPException(422, "Коды групп должны быть непустыми, до 160 знаков")
    stmt = insert(GroupSize)
    db.execute(stmt.on_conflict_do_update(index_elements=[GroupSize.group_code],
                                          set_={"size": stmt.excluded.size}),
               [{"group_code": code, "size": size} for code, size in data.sizes.items()])
    db.commit()
    return {"updated": len(data.sizes)}


class WalkData(BaseModel):
    from_room_id: int = Field(gt=0)
    to_room_id: int = Field(gt=0)
    minutes: int = Field(ge=1, le=90)


@router.put("/admin/walking-times")
def save_walking_time(data: WalkData, db=Depends(db_session), _=Depends(admin_user)):
    a, b = data.from_room_id, data.to_room_id
    if a == b or not db.get(Room, a) or not db.get(Room, b):
        raise HTTPException(422, "Укажите две разные аудитории")
    stmt = insert(WalkingTime).values(**data.model_dump())
    db.execute(stmt.on_conflict_do_update(index_elements=[WalkingTime.from_room_id, WalkingTime.to_room_id],
                                          set_={"minutes": data.minutes}))
    db.commit()
    return {"saved": True}


@router.get("/admin/audit")
def audit_log(offset: int = Query(0, ge=0), action:str="", start:date|None=None, end:date|None=None, db=Depends(db_session), _=Depends(admin_user)):
    from sqlalchemy import func
    from .bookings import CAMPUS
    query=select(Audit)
    if action:
        query=query.where(Audit.action.contains(action,autoescape=True))
    if start:
        query=query.where(func.date(func.timezone(CAMPUS.key,Audit.at))>=start)
    if end:
        query=query.where(func.date(func.timezone(CAMPUS.key,Audit.at))<=end)
    return [{"id": row.id, "action": row.action, "actor_id": row.actor_id, "object_id": row.object_id,
             "at": row.at} for row in db.scalars(query.order_by(Audit.id.desc()).offset(offset).limit(100))]
