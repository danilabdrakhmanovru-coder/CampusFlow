"""Idempotent synthetic seed for the local Compose demo."""
from datetime import datetime, timedelta
from os import environ

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from .catalog import GroupSize

from ..security import password_hash
from .bookings import CAMPUS
from .db import session_factory
from .models import Hold, Identity, Occupancy, Room, User
from .optimizer import BELL
from .schedule import activate
from .group_insights import LessonPin, pin_key
from .schedule_models import ImportBatch, Lesson, TeacherLink, TeacherNumber

ACCOUNTS = (
    ("student", "StudyFlow26!"),
    ("teacher", "TeachFlow26!"),
    ("dean", "DeanFlow26!"),
    ("admin", "AdminFlow26!"),
)


DEMO_SUBJECTS = (
    ("практическая", ("Дискретная математика","Алгоритмы и структуры данных","Математический анализ","Теория вероятностей")),
    ("практическая", ("Программирование на Python","Базы данных","Сетевые технологии","Разработка веб-приложений")),
    ("лабораторная", ("Основы робототехники","Цифровая схемотехника","Микроконтроллеры","Архитектура вычислительных систем")),
    ("лекция", ("Линейная алгебра","Информатика","Операционные системы","Методы машинного обучения")),
)


def demo_subject(room_code,start):
    index = int(room_code.rsplit("-",1)[1])-1
    kind, subjects = DEMO_SUBJECTS[index]
    local = start.astimezone(CAMPUS)
    minute = local.hour*60+local.minute
    slot = next((i for i,(a,_) in enumerate(BELL) if a==minute),0)
    return f"{subjects[(local.weekday()+slot)%len(subjects)]} ({kind})"


def refresh_demo_labels(db,batch):
    if batch.state!="active" or not any(row["subject"].startswith("Учебный пример") for row in batch.rows):
        return
    rows = []
    for row in batch.rows:
        if row["subject"].startswith("Учебный пример"):
            row = {**row,"subject":demo_subject(row["room"],datetime.fromisoformat(row["start"]))}
        rows.append(row)
    batch.rows = rows
    for lesson in db.scalars(select(Lesson).where(Lesson.batch_id==batch.id,Lesson.subject.startswith("Учебный пример"))):
        old_pin=db.get(LessonPin,pin_key(lesson))
        lesson.subject=demo_subject(lesson.room_code,lesson.period.lower)
        if old_pin:
            db.delete(old_pin)
            db.execute(insert(LessonPin).values(key=pin_key(lesson)).on_conflict_do_nothing())


DEMO_DAYS = ((0,1,3), (1,2), (2,3,4), (0,2,3), (1,2,3), (0,1))


def rows_for_day(day, prototype):
    index = int(prototype["room"].rsplit("-",1)[1])-1
    midnight = datetime.combine(day,datetime.min.time(),CAMPUS)
    for first in DEMO_DAYS[day.weekday()]:
        a,b = BELL[first + index%3]
        start,end = (midnight+timedelta(minutes=minute) for minute in (a,b))
        yield {**prototype,"start":start.isoformat(),"end":end.isoformat(),
               "subject":demo_subject(prototype["room"],start)}


def refresh_demo_layout(db,batch):
    clock = datetime.now(CAMPUS)
    active_busy = list(db.execute(select(Room.code,Occupancy.period).join(Room).outerjoin(Hold).where(
        Room.building==batch.scope, Occupancy.kind!="lesson", func.upper(Occupancy.period)>clock,
        Occupancy.hold_id.is_(None) | (Hold.expires_at>clock),
    )))
    pins = set(db.scalars(select(LessonPin.key)))
    protected_days = {(lesson.room_code,lesson.period.lower.astimezone(CAMPUS).date())
                      for lesson in db.scalars(select(Lesson).where(Lesson.batch_id==batch.id))
                      if pin_key(lesson) in pins} if pins else set()
    by_day = {}
    for row in batch.rows:
        day = datetime.fromisoformat(row["start"]).astimezone(CAMPUS).date()
        by_day.setdefault((row["room"],day),[]).append(row)
    revised = []
    for (room,day), rows in by_day.items():
        start_of_day = datetime.combine(day,datetime.min.time(),CAMPUS)
        end_of_day = start_of_day+timedelta(days=1)
        if (start_of_day+timedelta(minutes=BELL[0][0])<=clock or (room,day) in protected_days
                or any(code==room and period.lower<end_of_day and period.upper>start_of_day for code,period in active_busy)):
            revised.extend(rows)
        else:
            revised.extend(rows_for_day(day,rows[0]))
    replacement = ImportBatch(actor_id=batch.actor_id,scope=batch.scope,date_from=batch.date_from,date_to=batch.date_to,
                              source_name="synthetic-demo",sha256=batch.sha256,state="staged",rows=revised,
                              mapping=batch.mapping,complete=batch.complete,
                              report={**batch.report,"input_rows":len(revised),"lessons":len(revised),"demo_layout":2})
    db.add(replacement)
    db.flush()
    try:
        activate(db,replacement,batch,db.get(User,batch.actor_id),"publish")
    except HTTPException as exc:
        db.rollback()
        if exc.status_code!=409:
            raise


def seed():
    if environ.get("CAMPUSFLOW_DEMO") != "1":
        return
    if environ.get("CAMPUSFLOW_LOCAL_HTTP") != "1":
        raise RuntimeError("Synthetic demo accounts require local HTTP mode")
    sessions = session_factory()
    for scope in ("6", "7"):
        with sessions() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
            db.execute(insert(GroupSize).on_conflict_do_nothing(),[
                {"group_code":f"ДЕМО-{scope}{index}", "size":12+3*index} for index in range(1,5)
            ])
            existing = db.scalars(select(ImportBatch).where(ImportBatch.source_name=="synthetic-demo",ImportBatch.scope==scope)).all()
            if existing:
                active = next((batch for batch in existing if batch.state=="active"),None)
                if active:
                    refresh_demo_labels(db,active)
                    if not any(batch.report.get("demo_layout")==2 for batch in existing):
                        refresh_demo_layout(db,active)
                db.commit()
                continue
            if db.scalar(select(ImportBatch.id).where(ImportBatch.scope == scope)) is not None:
                raise RuntimeError("Use a separate database for the synthetic demo")
            for role, password in ACCOUNTS:
                identity = db.scalar(select(Identity).where(Identity.provider == "local", Identity.subject == role))
                if identity is None:
                    user = User(role=role)
                    db.add(user)
                    db.flush()
                    db.add(Identity(user_id=user.id, provider="local", subject=role,
                                    password_hash=password_hash(password)))
                else:
                    user = db.get(User, identity.user_id)
            rooms = [
                Room(building=scope, code=f"DEMO-{index:02}", floor=1+index%2,
                     kind=kind, capacity=capacity, accessible=index%2==0,
                     equipment={"projector":1,"pc":capacity} if kind=="computer" else {"projector":1})
                for index, (kind, capacity) in enumerate((
                    ("seminar",24),("computer",30),("laboratory",20),("lecture",80),
                ),1)
            ]
            db.add_all(rooms)
            db.flush()
            today = datetime.now(CAMPUS).date()
            first, last = today-timedelta(days=56), today+timedelta(days=28)
            rows = []
            for offset in range((last-first).days+1):
                day = first+timedelta(days=offset)
                if day.weekday() == 6:
                    continue
                for index,room in enumerate(rooms,1):
                    rows.extend(rows_for_day(day,dict(building=scope,room=room.code,
                        groups=[f"ДЕМО-{scope}{index}"],teachers=[f"demo-{scope}-{index}"])))
            batch = ImportBatch(actor_id=user.id, scope=scope, date_from=first, date_to=last,
                                source_name="synthetic-demo", sha256="0"*64, state="staged",
                                rows=rows, mapping={}, complete=True,
                                report=dict(input_rows=len(rows), lessons=len(rows), errors=0,
                                            unknown_room_lessons=0, overlapping_room_rows=0,
                                            booking_conflicts=[], issues=[], demo_layout=2))
            db.add(batch)
            db.flush()
            activate(db,batch,None,user,"publish")

    with sessions() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(61206701)"))
        scope = "Практикум"
        existing = db.scalar(select(ImportBatch.id).where(ImportBatch.scope == scope).limit(1))
        if existing is None:
            today = datetime.now(CAMPUS).date()
            first, last = today-timedelta(days=14), today+timedelta(days=98)
            rows = []
            for index in range(16):
                kind = ("seminar","computer","laboratory","lecture")[index%4]
                size = (20,24,16,60)[index%4]
                room = Room(building=scope,code=str(101+index%8+100*(index//8)),floor=1+index//8,
                            kind=kind,capacity=size+4,accessible=index%3!=0,
                            equipment={"projector":1,**({"pc":size+4} if kind=="computer" else {})})
                db.add(room)
                group = ("ИВТ","ПИ","РТ","ПМ")[index%4]+"-"+str(21+index//4)
                db.execute(insert(GroupSize).values(group_code=group,size=size).on_conflict_do_nothing())
                for offset in range((last-first).days+1):
                    day=first+timedelta(days=offset)
                    if day.weekday()>=5 or day.weekday()==index%5:
                        continue
                    midnight=datetime.combine(day,datetime.min.time(),CAMPUS)
                    for slot in ((0,1,2),(1,2,4),(0,3,5),(2,3,4))[index%4]:
                        a,b=BELL[slot]
                        rows.append(dict(building=scope,room=room.code,groups=[group],teachers=[f"practice-{index}"],
                            subject=DEMO_SUBJECTS[index%4][1][(slot+day.weekday())%4],
                            start=(midnight+timedelta(minutes=a)).isoformat(),end=(midnight+timedelta(minutes=b)).isoformat()))
            actor=db.scalar(select(User).join(Identity).where(Identity.subject=="admin",Identity.provider=="local"))
            batch=ImportBatch(actor_id=actor.id,scope=scope,date_from=first,date_to=last,source_name="synthetic-practice",
                sha256="1"*64,state="staged",rows=rows,mapping={},complete=True,
                report=dict(input_rows=len(rows),lessons=len(rows),errors=0,unknown_room_lessons=0,
                            overlapping_room_rows=0,booking_conflicts=[],issues=[]))
            db.add(batch)
            db.flush()
            activate(db,batch,None,actor,"publish")

    with sessions.begin() as db:
        if not db.scalar(select(Identity.id).where(Identity.subject=="dean",Identity.provider=="local")):
            dean = User(role="dean")
            db.add(dean)
            db.flush()
            db.add(Identity(user_id=dean.id,provider="local",subject="dean",password_hash=password_hash(dict(ACCOUNTS)["dean"])))
        student = db.scalar(select(User).join(Identity).where(
            Identity.provider=="local", Identity.subject=="student", User.role=="student", User.active,
        ))
        if student and not student.preferences.get("group"):
            student.preferences={**student.preferences,"group":"ДЕМО-61"}
        teacher = db.scalar(select(User).join(Identity).where(
            Identity.provider=="local", Identity.subject=="teacher", User.role=="teacher", User.active,
        ))
        if teacher and not db.get(TeacherLink,teacher.id):
            key = db.scalar(select(TeacherNumber.teacher_key).where(
                TeacherNumber.teacher_key=="demo-6-1", TeacherNumber.building=="6",
            ))
            if key:
                db.execute(insert(TeacherLink).values(user_id=teacher.id,teacher_key=key).on_conflict_do_nothing())


if __name__ == "__main__":
    seed()
