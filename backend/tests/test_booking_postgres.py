"""Integration checks. Use a dedicated migrated PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from app.security import password_hash
from app.v1.main import app
from app.v1.privacy import POLICY
from app.v1.schedule_models import ImportBatch
from app.v1.models import Hold, Identity, Occupancy, Room, User


@pytest.fixture
def pilot(monkeypatch):
    if not os.getenv("CAMPUSFLOW_TEST_DATABASE_URL"):
        pytest.skip("Set CAMPUSFLOW_TEST_DATABASE_URL to a dedicated migrated PostgreSQL database")
    monkeypatch.setenv("CAMPUSFLOW_DATABASE_URL", os.environ["CAMPUSFLOW_TEST_DATABASE_URL"])
    monkeypatch.setenv("CAMPUSFLOW_JWT_SECRET", "integration-tests-only-32-bytes-minimum")
    monkeypatch.setenv("CAMPUSFLOW_LOCAL_HTTP", "1")
    monkeypatch.setenv("CAMPUSFLOW_SCHEDULE_SECRET", "integration-schedule-secret-32-byte-minimum")
    with TestClient(app) as client:
        tokens = {}
        with app.state.sessions.begin() as db:
            room = Room(building="6", code=f"test-{uuid4().hex}", capacity=40)
            db.add(room)
            for role in ("student", "teacher", "admin"):
                user = User(role=role)
                db.add(user)
                db.flush()
                login = uuid4().hex
                db.add(Identity(provider="local", subject=login, user_id=user.id,
                                password_hash=password_hash("Integration-only!")))
                tokens[role] = login
        for role, login in tokens.items():
            client.cookies.clear()
            response = client.post("/api/v1/auth/login", json={
                "login": login, "password": "Integration-only!",
            })
            assert response.json()["status"] == "consent_required", response.text
            response = client.post("/api/v1/auth/consent", json={
                "version": response.json()["version"], "policy_accepted": True, "consent_accepted": True,
            })
            assert response.status_code == 200, response.text
            tokens[role] = {"Authorization": "Bearer " + response.json()["access_token"]}
        start = (datetime.now(ZoneInfo("Asia/Yekaterinburg")) + timedelta(days=1)).replace(
            hour=11, minute=0, second=0, microsecond=0)
        with app.state.sessions.begin() as db:
            admin_id = client.get("/api/v1/auth/me", headers=tokens["admin"]).json()["id"]
            db.execute(update(ImportBatch).where(ImportBatch.state == "active").values(state="archived"))
            spare = start+timedelta(hours=8)
            baseline = dict(start=spare.isoformat(),end=(spare+timedelta(hours=1)).isoformat(),
                            building="6",room=room.code,subject="Baseline",groups=[],teachers=[])
            db.add(ImportBatch(scope="6", date_from=start.date(), date_to=start.date(), state="active",
                               source_name="synthetic-test", sha256="0"*64, actor_id=admin_id,
                               rows=[baseline], mapping={}, report={"errors":0,"overlapping_room_rows":0}, complete=True))
        yield client, tokens, room.id, start


def hold(client, headers, room, start, key=None):
    return client.post("/api/v1/booking-holds", headers={**headers, "Idempotency-Key": key or uuid4().hex},
                       json={"room_id": room, "start": start.isoformat(),
                             "end": (start + timedelta(hours=1)).isoformat()})


def confirm(client, headers, hold_id, key):
    return client.post("/api/v1/bookings", headers={**headers, "Idempotency-Key": key},
                       json={"hold_id": hold_id, "title": "Проверка"})


def test_100_parallel_requests(pilot):
    client, tokens, room, start = pilot
    with ThreadPoolExecutor(max_workers=100) as pool:
        responses = list(pool.map(lambda _: hold(client, tokens["teacher"], room, start), range(100)))
    successes = [response for response in responses if response.status_code == 201]
    assert len(successes) == 1
    assert sum(response.status_code == 409 for response in responses) == 99
    assert all(response.json()["detail"]["alternatives"] for response in responses if response.status_code == 409)
    hold_id = successes[0].json()["id"]
    key = uuid4().hex
    booking = confirm(client, tokens["teacher"], hold_id, key)
    assert booking.status_code == 201, booking.text
    assert confirm(client, tokens["teacher"], hold_id, key).json() == booking.json()
    assert hold(client, tokens["teacher"], room, start).status_code == 409


def test_roles_expiry_adjacency_and_lessons(pilot):
    client, tokens, room, start = pilot
    assert hold(client, {}, room, start).status_code == 401
    assert hold(client, tokens["student"], room, start).status_code == 403
    assert client.get("/api/v1/admin/bookings", headers=tokens["teacher"]).status_code == 403
    assert client.get("/api/v1/admin/bookings", headers=tokens["admin"]).status_code == 200
    with app.state.sessions.begin() as db:
        data = Range(start, start + timedelta(hours=1), bounds="[)")
        db.add(Occupancy(room_id=room, period=data, kind="lesson", lesson_key="synthetic"))
    with pytest.raises(IntegrityError) as exc:
        with app.state.sessions.begin() as db:
            db.add(Occupancy(room_id=room, period=data, kind="block"))
    assert exc.value.orig.sqlstate == "23P01"
    assert hold(client, tokens["teacher"], room, start).status_code == 409
    next_start = start + timedelta(hours=1)
    key = uuid4().hex
    response = hold(client, tokens["teacher"], room, next_start, key)
    assert response.status_code == 201, response.text
    assert hold(client, tokens["teacher"], room, next_start, key).json() == response.json()
    assert hold(client, tokens["teacher"], room, next_start + timedelta(hours=1), key).status_code == 409
    hold_id = response.json()["id"]
    with app.state.sessions.begin() as db:
        db.get(Hold, hold_id).expires_at = start - timedelta(days=2)
    assert confirm(client, tokens["teacher"], hold_id, uuid4().hex).status_code == 409
    replacement = hold(client, tokens["teacher"], room, next_start)
    assert replacement.status_code == 201, replacement.text
    booking = confirm(client, tokens["teacher"], replacement.json()["id"], uuid4().hex)
    assert booking.status_code == 201
    endpoint = f"/api/v1/bookings/{booking.json()['id']}/cancel"
    assert client.post(endpoint, headers=tokens["student"]).status_code == 403
    assert client.post(endpoint, headers=tokens["admin"]).status_code == 204
    assert hold(client, tokens["teacher"], room, next_start).status_code == 201



def test_database_rejects_competing_writes(pilot):
    _, _, room, start = pilot
    period = Range(start, start + timedelta(hours=1), bounds="[)")

    def attempt(_):
        try:
            with app.state.sessions.begin() as db:
                db.add(Occupancy(room_id=room, period=period, kind="block"))
            return True
        except IntegrityError as exc:
            assert exc.orig.sqlstate == "23P01"
            return False

    with ThreadPoolExecutor(max_workers=100) as pool:
        assert sum(pool.map(attempt, range(100))) == 1

def test_import_preview_publish_and_rollback(pilot):
    client, tokens, room, start = pilot
    admin = tokens["admin"]
    with app.state.sessions() as db:
        code = db.get(Room, room).code
    end = start + timedelta(hours=1)
    date = start.date().isoformat()
    row = f"start,end,building,room,subject,groups,teachers\n{start.isoformat()},{end.isoformat()},6,{code},Example,{code},Private Name\n"
    def upload(headers):
        return client.post("/api/v1/admin/imports", headers=headers,
                           data=dict(scope="6", date_from=date, date_to=date, complete="true"),
                           files={"file": ("schedule.csv", row.encode())})
    assert upload(tokens["student"]).status_code == 403
    response = upload(admin)
    assert response.status_code == 201, response.text
    assert "Private Name" not in response.text
    batch = response.json()["id"]
    path = f"/api/v1/admin/imports/{batch}"
    occupied = hold(client, tokens["teacher"], room, start)
    assert occupied.status_code == 201
    response = client.post(path + "/publish", headers=admin)
    assert response.status_code == 409, response.text
    assert client.delete(f"/api/v1/booking-holds/{occupied.json()['id']}", headers=tokens["teacher"]).status_code == 204
    response = client.post(path + "/publish", headers=admin)
    assert response.status_code == 200, response.text
    assert hold(client, tokens["teacher"], room, start).status_code == 409
    response = client.get("/api/v1/schedule", params={"scope":"group","entity_id":code,"from":date,"to":date},
                          headers=tokens["student"])
    assert len(response.json()["items"]) == 1 and "Private Name" not in response.text
    response = client.get(f"/api/v1/rooms/{room}/occupancy", params={"start":start.isoformat(),"end":end.isoformat()},
                          headers=tokens["student"])
    assert response.json()["coverage"] == "building_import"
    response = client.post(path + "/rollback", headers=admin)
    assert response.status_code == 200, response.text
    # The room in this fixture has no independent lesson or booking after rollback.
    assert hold(client, tokens["teacher"], room, start).status_code == 201



def test_teacher_directory_link_and_erasure(pilot):
    from app.v1.import_files import teacher_id
    from app.v1.schedule_models import ImportBatch
    from sqlalchemy import func

    client, tokens, room, start = pilot
    admin = tokens["admin"]
    teacher = tokens["teacher"]
    teacher_user = client.get("/api/v1/auth/me", headers=teacher).json()["id"]
    with app.state.sessions() as db:
        code = db.get(Room, room).code
    date = start.date().isoformat()
    csv = f"start,end,building,room,subject,groups,teachers\n{start.isoformat()},{(start+timedelta(hours=1)).isoformat()},6,{code},Example,{code},Synthetic Lecturer\n"
    path = "/api/v1/admin/imports"
    batch = client.post(path, headers=admin, data=dict(scope="6", date_from=date, date_to=date, complete="true"),
                        files={"file": ("schedule.csv", csv.encode())})
    teacher_key = teacher_id("Synthetic Lecturer")
    assert teacher_key not in batch.text, batch.text
    batch_id = batch.json()["id"]
    assert client.post(f"{path}/{batch_id}/publish", headers=admin).status_code == 200
    entities = "/api/v1/schedule/entities"
    assert set(client.get(entities, headers=tokens["student"]).json()) == {"groups"}
    assert set(client.get(entities, headers=teacher).json()) == {"groups", "rooms"}
    data = client.get(entities, headers=admin).json()
    alias = next(alias for alias in data["teachers"] if alias["building"] == "6")
    assert teacher_key not in str(data) and alias["label"].startswith("Преподаватель №")
    query = {"scope": "mine", "from": date, "to": date}
    assert client.get("/api/v1/schedule", params=query, headers=tokens["student"]).status_code == 403
    assert client.get("/api/v1/schedule", params=query, headers=teacher).status_code == 404
    link = f"/api/v1/admin/users/{teacher_user}/teacher-link"
    assert client.put(link, headers=teacher, json=alias).status_code == 403
    assert client.put(link, headers=admin, json=alias).status_code == 200
    mine = client.get("/api/v1/schedule", params=query, headers=teacher)
    assert len(mine.json()["items"]) == 1 and teacher_key not in mine.text
    assert client.get("/api/v1/schedule", headers=teacher, params={
        **query, "scope":"teacher", "building":"6", "entity_id":str(alias["number"]),
    }).status_code == 403
    next_slot = start + timedelta(hours=1)
    h = hold(client, teacher, room, next_slot)
    assert h.status_code == 201, h.text
    b = confirm(client, teacher, h.json()["id"], uuid4().hex)
    assert b.status_code == 201, b.text
    assert client.delete(f"/api/v1/admin/users/{teacher_user}/data", headers=admin).status_code == 204
    assert client.get("/api/v1/auth/me", headers=teacher).status_code == 401
    assert hold(client, admin, room, next_slot).status_code == 201
    with app.state.sessions() as db:
        for model in (Identity,):
            assert db.scalar(select(func.count()).select_from(model).where(model.user_id == teacher_user)) == 0
        assert db.get(ImportBatch,batch_id).state == "active"
    assert client.post(f"{path}/{batch_id}/rollback", headers=admin).status_code == 200


def test_retention_removes_old_records(pilot, monkeypatch):
    from datetime import datetime, timezone
    from app.v1.models import Audit, Booking, RefreshSession
    from app.v1.retention import cleanup

    client, tokens, room, start = pilot
    teacher = tokens["teacher"]
    user = client.get("/api/v1/auth/me", headers=teacher).json()["id"]
    created = hold(client, teacher, room, start)
    assert created.status_code == 201
    hold_id = created.json()["id"]
    b = confirm(client, teacher, hold_id, uuid4().hex)
    assert b.status_code == 201
    old = datetime.now(timezone.utc) - timedelta(days=10)
    for key in ("BOOKING_RETENTION", "AUDIT_RETENTION", "EXPIRED_SESSION_RETENTION"):
        monkeypatch.setenv(f"CAMPUSFLOW_{key}_DAYS", "2")
    with app.state.sessions.begin() as db:
        db.get(Hold, hold_id).expires_at = old
        db.get(Booking, b.json()["id"]).period = Range(old, old + timedelta(hours=1), bounds="[)")
        db.add(RefreshSession(digest="test-retention", device_id="test-retention", user_id=user, expires_at=old))
        audit = Audit(actor_id=user, action="test.old", object_id=0, at=old)
        db.add(audit)
        db.flush()
        audit_id = audit.id
        report = cleanup(db)
        assert all(report[key] >= 1 for key in ("bookings", "holds", "sessions", "audit"))
    with app.state.sessions() as db:
        assert db.get(Booking, b.json()["id"]) is None
        assert db.get(Hold, hold_id) is None
        assert db.get(Audit, audit_id) is None
        assert db.get(RefreshSession, "test-retention") is None
    assert hold(client, teacher, room, start).status_code == 201


def test_activity_auto_release_and_watch(pilot):
    from app.v1.activity_job import process_room_activity
    from app.v1.activity_models import Outbox, Ticket
    from datetime import timezone

    client, tokens, room, start = pilot
    teacher, admin = tokens["teacher"], tokens["admin"]
    first = hold(client, teacher, room, start)
    booked = confirm(client, teacher, first.json()["id"], uuid4().hex)
    assert booked.status_code == 201, booked.text
    booking_id = booked.json()["id"]
    assert client.get(f"/api/v1/tickets/{booking_id}", headers=tokens["student"]).status_code == 403
    ticket = client.get(f"/api/v1/tickets/{booking_id}", headers=teacher).json()
    assert len(ticket["token"]) >= 20 and ticket["checked_in_at"] is None
    assert client.post(f"/api/v1/tickets/{booking_id}/check-in", headers=teacher,
                       json={"token":ticket["token"]}).status_code == 403
    door = client.post(f"/api/v1/admin/rooms/{room}/check-in-code", headers=admin).json()["code"]
    assert client.post(f"/api/v1/tickets/{booking_id}/check-in", headers=teacher, json={"code":door}).status_code == 409
    timeline = client.get(f"/api/v1/rooms/{room}/timeline", headers=tokens["student"],
                          params={"start": start.isoformat(),"end":(start+timedelta(hours=1)).isoformat()})
    assert timeline.json()["busy"][0]["kind"] == "booking"
    watched = client.post("/api/v1/watches", headers={**admin,"Idempotency-Key":uuid4().hex},
                          json={"room_id":room,"start":start.isoformat(),"end":(start+timedelta(hours=1)).isoformat()})
    assert watched.status_code == 201, watched.text
    with app.state.sessions.begin() as db:
        db.get(Ticket, booking_id).auto_release_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    with app.state.sessions() as db:
        process_room_activity(db)
        assert db.scalar(select(Outbox.id).where(Outbox.kind == "watch_hold"))
    assert client.get("/api/v1/bookings/mine",headers=teacher).json() == []
    assert len(client.get("/api/v1/bookings/mine?include_cancelled=true",headers=teacher).json()) == 1
    watches = client.get("/api/v1/watches",headers=admin)
    assert watches.json()[0]["offer"] is not None, watches.text
    first_key = uuid4().hex
    second = hold(client, teacher, room, start+timedelta(hours=1), first_key)
    assert second.status_code == 201, second.text
    with app.state.sessions.begin() as db:
        db.get(Hold, second.json()["id"]).expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    assert hold(client, teacher, room, start+timedelta(hours=1), first_key).json()["detail"]["code"] == "hold_expired"
    assert hold(client, teacher, room, start+timedelta(days=10)).json()["detail"]["code"] == "no_coverage"


def test_signin_throttle(pilot):
    client, _, _, _ = pilot
    body = {"login":"synthetic-missing-account","password":"Incorrect-pass-42"}
    for _ in range(5):
        assert client.post("/api/v1/auth/login",json=body).status_code == 401
    blocked = client.post("/api/v1/auth/login",json=body)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1
    # Avoid sharing failed-attempt buckets with subsequent independent tests.
    from app.v1.login_throttle import buckets
    with app.state.sessions.begin() as db:
        db.execute(buckets.delete())


def test_import_conflict_cancellation_notifies_owner(pilot):
    client, tokens, room, start = pilot
    teacher, admin = tokens["teacher"], tokens["admin"]
    reservation = hold(client, teacher, room, start)
    booking = confirm(client, teacher, reservation.json()["id"], uuid4().hex)
    assert booking.status_code == 201
    booking_id = booking.json()["id"]
    with app.state.sessions() as db:
        code = db.get(Room,room).code
    end = start+timedelta(hours=1)
    csv = f"start,end,building,room,subject\n{start.isoformat()},{end.isoformat()},6,{code},Synthetic\n"
    stage = client.post("/api/v1/admin/imports",headers=admin,
                        data=dict(scope="6",date_from=start.date().isoformat(),date_to=start.date().isoformat(),complete="true"),
                        files={"file":("test.csv",csv.encode())})
    assert stage.status_code == 201, stage.text
    prefix = f"/api/v1/admin/imports/{stage.json()['id']}"
    assert client.get(prefix+"/conflicts",headers=admin).json()["items"][0]["booking_id"] == booking_id
    assert client.post(prefix+"/publish",headers=admin).status_code == 409
    result = client.post(prefix+"/conflicts",headers={**admin,"Idempotency-Key":uuid4().hex},
                         json={"action":"cancel_booking","booking_id":booking_id,"reason":"Учебная пара"})
    assert result.status_code == 200, result.text
    assert client.get("/api/v1/notifications",headers=teacher).json()[0]["payload"]["reason"] == "Учебная пара"
    assert client.post(prefix+"/publish",headers=admin).status_code == 200
    assert client.post(prefix+"/rollback",headers=admin).status_code == 200


def test_weekly_proposal_partial_apply(pilot):
    from app.v1.optimizer import BELL
    from app.v1.analytics import moment

    client, tokens, room, start = pilot
    admin = tokens["admin"]
    day = start.date()
    other_day = day + timedelta(days=1)
    a,b = BELL[0]
    begin, end = moment(day,a), moment(day,b)
    second_start, second_end = moment(other_day,a), moment(other_day,b)
    with app.state.sessions.begin() as db:
        item = db.get(Room,room)
        item.kind = "seminar"
        code = item.code
    data = ("start,end,building,room,subject,groups,teachers\n"
            f"{begin.isoformat()},{end.isoformat()},6,{code},First,A Group,First Synthetic Teacher {code}\n"
            f"{second_start.isoformat()},{second_end.isoformat()},6,{code},Second,B Group,Second Synthetic Teacher {code}\n")
    upload = client.post("/api/v1/admin/imports",headers=admin,
                         data=dict(scope="6",date_from=day.isoformat(),date_to=other_day.isoformat(),complete="true"),
                         files={"file":("schedule.csv",data.encode())})
    assert upload.status_code == 201, upload.text
    assert client.post(f"/api/v1/admin/imports/{upload.json()['id']}/publish",headers=admin).status_code == 200
    params = {"scope":"building","entity_id":"6","from":day.isoformat(),"to":other_day.isoformat()}
    rows = client.get("/api/v1/schedule",headers=admin,params=params).json()["items"]
    sizes = client.put("/api/v1/admin/group-sizes",headers=admin,json={"sizes":{"A Group":20,"B Group":22}})
    assert sizes.status_code == 200, sizes.text
    result = client.post("/api/v1/admin/optimization-runs",headers=admin,json={
        "day":day.isoformat(),"end_day":other_day.isoformat(),
        "requirements":{str(row["id"]):{"unavailable_slots":[1]} for row in rows},
    })
    assert result.status_code == 200, result.text
    proposal = result.json()
    assert proposal["status"] in {"optimal","feasible"} and len(proposal["assignments"]) == 2
    first = rows[0]["id"]
    chosen = next(o for o in proposal["assignments"] if o["lesson_id"] == first)
    assert chosen["slot"] != 1
    url = f"/api/v1/admin/proposals/{proposal['id']}/apply"
    from app.v1.schedule_models import Lesson, TeacherLink
    teacher_id = client.get("/api/v1/auth/me", headers=tokens["teacher"]).json()["id"]
    with app.state.sessions.begin() as db:
        lesson = db.get(Lesson, first)
        db.add(TeacherLink(user_id=teacher_id, teacher_key=lesson.teachers[0]))
    day_off = datetime.fromisoformat(chosen["date"]).weekday()
    prefs = client.get("/api/v1/me/preferences", headers=tokens["teacher"]).json()
    assert client.put("/api/v1/me/preferences", headers=tokens["teacher"],
                      json={**prefs,"teaching_days_off":[day_off]}).status_code == 200
    blocked = client.post(url,headers={**admin,"Idempotency-Key":uuid4().hex},json={"lesson_ids":[first]})
    assert blocked.status_code == 409 and "день без занятий" in blocked.text
    assert client.put("/api/v1/me/preferences", headers=tokens["teacher"],
                      json={**prefs,"teaching_days_off":list(range(7))}).status_code == 200
    impossible = client.post("/api/v1/admin/optimization-runs",headers=admin,json={
        "day":day.isoformat(),"end_day":other_day.isoformat(),"requirements":{str(first):{}},
    })
    assert impossible.status_code == 200 and impossible.json()["assignments"] == []
    assert client.put("/api/v1/me/preferences", headers=tokens["teacher"],
                      json={**prefs,"teaching_days_off":[]}).status_code == 200
    selected = client.post(url,headers={**admin,"Idempotency-Key":uuid4().hex},json={"lesson_ids":[first]})
    assert selected.status_code == 200, selected.text
    fresh = {r["subject"]:r for r in client.get("/api/v1/schedule",headers=admin,params=params).json()["items"]}
    assert datetime.fromisoformat(fresh["First"]["start"]) != begin
    assert datetime.fromisoformat(fresh["Second"]["start"]) == second_start


def test_activity_curve_student_coverage_and_expired_holds(pilot):
    from datetime import timezone

    client, tokens, room, start = pilot
    path = "/api/v1/buildings/6/pulse-curve"
    params = {"day": start.date().isoformat()}
    assert client.get(path, params=params).status_code == 401
    before = client.get(path, headers=tokens["student"], params=params).json()
    baseline = {datetime.fromisoformat(row["at"]): row["busy"] for row in before["points"]}
    active = hold(client, tokens["teacher"], room, start)
    assert active.status_code == 201, active.text
    expired_start = start + timedelta(hours=2)
    expired = hold(client, tokens["teacher"], room, expired_start)
    assert expired.status_code == 201, expired.text
    with app.state.sessions.begin() as db:
        db.get(Hold, expired.json()["id"]).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    result = client.get(path, headers=tokens["student"], params=params)
    assert result.status_code == 200, result.text
    data = result.json()
    assert set(data) == {"covered", "step_minutes", "points"}
    assert data["covered"] and data["step_minutes"] == 15 and len(data["points"]) == 57
    assert all(set(point) == {"at", "busy", "total"} for point in data["points"])
    by_time = {datetime.fromisoformat(row["at"]): row for row in data["points"]}
    assert by_time[start]["busy"] == baseline[start] + 1
    assert by_time[start - timedelta(minutes=15)]["busy"] == baseline[start - timedelta(minutes=15)]
    assert by_time[start + timedelta(hours=1)]["busy"] == baseline[start + timedelta(hours=1)]
    assert by_time[expired_start]["busy"] == baseline[expired_start]
    assert min(by_time).hour == 8 and max(by_time).hour == 22
    assert client.get("/api/v1/buildings/7/pulse-curve", headers=tokens["student"], params=params).json() == {
        "covered": False, "step_minutes": 15, "points": [],
    }

def test_public_site_metadata_contains_no_personal_data(pilot, monkeypatch):
    client, _, _, _ = pilot
    monkeypatch.setenv("CAMPUSFLOW_SUPPORT_EMAIL", "dispatcher@example.invalid")
    response = client.get("/api/v1/site")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "name", "description", "campus", "support_email", "support_hours",
        "schedule_source", "schedule_updated_at", "schedule_scopes", "timezone", "bell", "booking_mode",
    }
    assert data["support_email"] == "dispatcher@example.invalid"
    assert data["schedule_scopes"] == ["6"]
    assert datetime.fromisoformat(data["schedule_updated_at"]).tzinfo is not None

def test_consent_lifecycle_and_session_revocation(pilot, monkeypatch):
    from app.v1.models import Consent

    client, tokens, _, _ = pilot
    login_name = uuid4().hex
    credentials = {"login": login_name, "password": "Test-privacy-only-42"}
    with app.state.sessions.begin() as db:
        student = User(role="student")
        db.add(student)
        db.flush()
        student_id = student.id
        db.add(Identity(provider="local", subject=login_name, user_id=student_id,
                        password_hash=password_hash(credentials["password"])))

    assert not client.post("/api/v1/auth/logout").content
    assert client.post("/api/v1/auth/consent", json={
        "version": POLICY, "policy_accepted": True, "consent_accepted": True,
    }).status_code == 401
    # Old request fields must not bypass the separate consent screen.
    response = client.post("/api/v1/auth/login", json={
        **credentials, "policy_version": POLICY, "policy_accepted": True, "consent_accepted": True,
    })
    assert response.json() == {"status": "consent_required", "version": POLICY}
    assert "Max-Age=900" in response.headers["set-cookie"]
    pending_refresh = client.post("/api/v1/auth/refresh")
    assert pending_refresh.json() == response.json()
    assert "set-cookie" not in pending_refresh.headers
    assert client.get("/api/v1/rooms").status_code == 401
    with app.state.sessions() as db:
        assert not db.scalars(select(Consent).where(Consent.user_id == student_id)).all()

    form = {"version": POLICY, "policy_accepted": True, "consent_accepted": True}
    assert client.post("/api/v1/auth/consent", json={**form, "version": "old"}).status_code == 409
    assert client.post("/api/v1/auth/consent", json={**form, "consent_accepted": False}).status_code == 422
    assert client.post("/api/v1/auth/consent", json=form, headers={"Origin": "https://other.invalid"}).status_code == 403
    accepted = client.post("/api/v1/auth/consent", json=form).json()
    assert accepted["status"] == "authenticated"
    original = {"Authorization": "Bearer " + accepted["access_token"]}
    assert client.get("/api/v1/rooms", headers=original).status_code == 200
    assert client.get("/api/v1/auth/consents", headers=tokens["teacher"]).json()[0]["id"] != client.get(
        "/api/v1/auth/consents", headers=original,
    ).json()[0]["id"]
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/login", json=credentials).json()["status"] == "authenticated"

    monkeypatch.setenv("CAMPUSFLOW_PRIVACY_VERSION", "test-new-policy")
    assert client.get("/api/v1/rooms", headers=original).status_code == 401
    assert client.post("/api/v1/auth/refresh").json() == {"status": "consent_required", "version": "test-new-policy"}
    updated_form = {**form, "version": "test-new-policy"}
    current = client.post("/api/v1/auth/consent", json=updated_form).json()
    headers = {"Authorization": "Bearer " + current["access_token"]}
    assert len(client.get("/api/v1/auth/consents", headers=headers).json()) == 2
    assert client.get("/api/v1/rooms", headers=original).status_code == 401
    other_cookie = client.cookies.get("cf_refresh")
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json=credentials).json()["status"] == "authenticated"
    assert client.post("/api/v1/auth/consent/withdraw", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/refresh", headers={"Cookie": f"cf_refresh={other_cookie}"}).status_code == 401
    assert client.get("/api/v1/rooms", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert client.post("/api/v1/auth/login", json=credentials).json()["status"] == "consent_required"
    again = client.post("/api/v1/auth/consent", json=updated_form).json()
    history = client.get("/api/v1/auth/consents", headers={"Authorization": "Bearer " + again["access_token"]}).json()
    assert [item["version"] for item in history] == ["test-new-policy", "test-new-policy", POLICY]
    assert history[1]["withdrawn_at"] and history[0]["withdrawn_at"] is None
    assert history[2]["withdrawn_at"]
    monkeypatch.setenv("CAMPUSFLOW_PRIVACY_VERSION", POLICY)
    assert client.post("/api/v1/auth/refresh").json() == {"status": "consent_required", "version": POLICY}


def test_public_privacy_documents_and_pdf(pilot, monkeypatch):
    client, _, _, _ = pilot
    monkeypatch.setenv("CAMPUSFLOW_PRIVACY_OPERATOR", "Синтетический оператор")
    assert client.post("/api/v1/auth/logout").status_code == 204
    result = client.get("/api/v1/privacy/policy")
    assert result.headers["cache-control"] == "no-store"
    data = result.json()
    assert data["operator"]["operator"] == "Синтетический оператор"
    assert "operator" not in data["missing"]
    assert set(data["documents"]) == {"consent", "cookies", "privacy"}
    for kind in data["documents"]:
        pdf = client.get(f"/api/v1/privacy/documents/{kind}.pdf")
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")
    assert client.get("/api/v1/privacy/documents/missing.pdf").status_code == 404

def test_profile_preferences_export_and_session_revocation(pilot):
    client, tokens, _, _ = pilot
    student, teacher, admin = (tokens[k] for k in ("student","teacher","admin"))
    assert client.get("/api/v1/me").status_code == 401
    profile = client.get("/api/v1/me", headers=student).json()
    assert profile["role"] == "student" and "preferences" in profile
    assert client.get("/api/v1/catalog/groups", headers=student).status_code == 200
    assert client.put("/api/v1/me/preferences", headers=student, json={"group":"unknown_group"}).status_code == 422
    saved = client.put("/api/v1/me/preferences", headers=student, json={"theme":"dark","density":"compact","building":"6"})
    assert saved.status_code == 200 and saved.json()["theme"] == "dark"
    assert client.get("/api/v1/me/preferences", headers=teacher).json()["theme"] == "system"
    assert client.post("/api/v1/me/teacher-link-request", headers=student).status_code == 403
    assert client.post("/api/v1/me/teacher-link-request", headers=teacher).status_code == 204
    assert client.post("/api/v1/me/deletion-request", headers=student).status_code == 204
    exported = client.get("/api/v1/me/export", headers=student)
    assert "attachment" in exported.headers["content-disposition"]
    assert exported.json()["profile"]["deletion_requested_at"]
    assert "password" not in exported.text
    sessions = client.get("/api/v1/me/sessions", headers=student).json()
    assert len(sessions) == 1 and sessions[0]["current"]
    assert client.delete("/api/v1/me/sessions/"+sessions[0]["id"], headers=teacher).status_code == 204
    assert client.get("/api/v1/me", headers=student).status_code == 200
    assert client.delete("/api/v1/me/sessions/"+sessions[0]["id"], headers=student).status_code == 204
    assert client.get("/api/v1/me", headers=student).status_code == 401
    assert client.get("/api/v1/admin/overview",headers=teacher).status_code == 403
    assert client.get("/api/v1/admin/overview",headers=admin).status_code == 200


def test_weekly_booking_series_is_atomic(pilot):
    client,tokens,room,start=pilot
    teacher=tokens["teacher"]
    with app.state.sessions.begin() as db:
        db.execute(update(ImportBatch).where(ImportBatch.state=="active").values(date_to=start.date()+timedelta(days=14)))
    future = hold(client, teacher, room, start+timedelta(days=7))
    assert future.status_code==201
    occupied=confirm(client,teacher,future.json()["id"],uuid4().hex)
    assert occupied.status_code==201
    first=hold(client,teacher,room,start)
    key={"Idempotency-Key":uuid4().hex,**teacher}
    data={"hold_id":first.json()["id"],"title":"Синтетическая серия","repeats":2}
    assert client.post("/api/v1/bookings",headers=key,json=data).json()["code"]=="series_conflict"
    assert client.post(f'/api/v1/bookings/{occupied.json()["id"]}/cancel',headers=teacher).status_code==204
    result=client.post("/api/v1/bookings",headers=key,json=data)
    assert result.status_code==201,result.text
    assert len(result.json()["repeated_ids"])==1
    assert client.post("/api/v1/bookings",headers=key,json=data).json()==result.json()
    assert client.patch(f'/api/v1/bookings/{result.json()["id"]}',headers=tokens["student"],json={"title":"change"}).status_code==403
    updated=client.patch(f'/api/v1/bookings/{result.json()["id"]}',headers=teacher,json={"title":"Новое название"})
    assert updated.json()["title"]=="Новое название"


def test_group_access_and_ranker_training(pilot):
    from app.v1.ranking import Feedback, scores, train, trained_model
    from app.v1.schedule_models import Proposal
    client,tokens,_,start=pilot
    arguments={"start":start.date().isoformat(),"end":start.date().isoformat()}
    url="/api/v1/analytics/groups/windows"
    assert client.get(url,headers=tokens["student"],params=arguments).status_code==403
    assert client.get(url,headers=tokens["teacher"],params=arguments).status_code==403
    assert client.get(url,headers=tokens["admin"],params=arguments).status_code==200
    assert client.get("/api/v1/analytics/windows",headers=tokens["teacher"],params=arguments).status_code==403
    assert client.get("/api/v1/analytics/model",headers=tokens["admin"]).json()["status"]=="insufficient_data"
    with app.state.sessions() as db:
        for i in range(32):
            proposal=Proposal(result={},source_versions=[])
            db.add(proposal);db.flush()
            db.add(Feedback(proposal_id=proposal.id,accepted=bool(i%2),reason="fixture",
                features=[40+i,i%6,i%9+1,i%2,2,20+i,1,1],gain=i+10))
        db.commit()
        try:
            result=train(db)
            assert result["status"]=="trained" and result["metrics"]["holdout_rows"]>0
            chance,minutes=scores(trained_model(db),[50,2,3,0,2,22,1,1])
            assert 0<=chance<=1 and minutes>=0
        finally:
            from sqlalchemy import delete
            from app.v1.ranking import RankingModel
            db.execute(delete(RankingModel))
            db.execute(delete(Feedback))
            db.commit()

def test_issued_password_reset_is_single_use(pilot):
    client,tokens,_,_=pilot
    teacher=tokens["teacher"]
    admin=tokens["admin"]
    teacher_profile=client.get("/api/v1/me",headers=teacher).json()
    path=f'/api/v1/admin/users/{teacher_profile["id"]}/password-reset'
    assert client.post(path,headers=teacher).status_code==403
    issued=client.post(path,headers=admin)
    token=issued.json()["path"].split("#",1)[1]
    response=client.post("/api/v1/password-reset",json={"token":token,"password":"NewPass-391Test"})
    assert response.status_code==204,response.text
    assert client.post("/api/v1/password-reset",json={"token":token,"password":"NewPass-391Test"}).status_code==404
    assert client.get("/api/v1/me",headers=teacher).status_code==401
    client.cookies.clear()
    assert client.post("/api/v1/auth/login",json={"login":teacher_profile["login"],"password":"NewPass-391Test"}).json()["status"]=="authenticated"

def test_recommendations_allow_no_group_and_explain_other_rooms(pilot):
    client, tokens, _, start = pilot
    teacher = tokens["teacher"]
    scope = "F" + uuid4().hex[:8]
    unchecked = "U" + uuid4().hex[:8]
    admin_id = client.get("/api/v1/auth/me", headers=tokens["admin"]).json()["id"]
    with app.state.sessions.begin() as db:
        projectors_missing = Room(building=scope, code="F-101", kind="lecture", capacity=40, equipment={})
        occupied = Room(building=scope, code="F-102", kind="lecture", capacity=40, equipment={"pc":30,"projector":1})
        small = Room(building=scope, code="F-103", kind="seminar", capacity=10, equipment={"pc":10})
        unknown = Room(building=unchecked, code="U-101", kind="lecture", capacity=40, equipment={"pc":30,"projector":1})
        db.add_all([projectors_missing, occupied, small, unknown])
        db.flush()
        occupied_id = occupied.id
        db.add(ImportBatch(scope=scope, date_from=start.date(), date_to=start.date(), state="active",
                           source_name="synthetic-recommendations", sha256="0"*64, actor_id=admin_id,
                           rows=[], mapping={}, report={}, complete=True))
    assert hold(client, teacher, occupied_id, start).status_code == 201
    params = {"day":start.date().isoformat(), "kind":"lecture", "count":25,
              "start_minute":start.hour*60+start.minute, "duration":30, "building":scope}
    path = "/api/v1/slots/recommendations"
    exact = client.get(path, params=params, headers=teacher)
    assert exact.status_code == 200
    assert exact.json()["options"][0]["room"] == "F-101"
    assert exact.json()["other_rooms"] == []
    response = client.get(path, params={**params, "equipment":"pc,projector"}, headers=teacher).json()
    assert response["options"] == []
    assert [item["room"] for item in response["waiting"]] == ["F-102"]
    alternatives = {item["room"]:item for item in response["other_rooms"]}
    missing = alternatives["F-101"]
    assert missing["status"] == "free" and missing["available"]["start"]
    assert missing["selectable"] is True
    assert not alternatives["F-103"]["selectable"]
    assert not alternatives["F-102"]["selectable"]
    assert missing["reasons"] == ["Нет компьютеров", "Нет проектора"]
    assert alternatives["F-102"]["status"] == "busy"
    assert "Мало мест: 10, нужно 25" in alternatives["F-103"]["reasons"]
    unconfirmed = client.get(path, params={**params, "building":unchecked}, headers=teacher).json()
    assert unconfirmed["options"] == [] and unconfirmed["covered_buildings"] == []
    assert unconfirmed["other_rooms"][0]["status"] == "unknown"
    assert unconfirmed["other_rooms"][0]["available"] is None

def test_demo_login_is_disabled_outside_demonstration(pilot, monkeypatch):
    client,_,_,_=pilot
    monkeypatch.setenv("CAMPUSFLOW_DEMO","1")
    monkeypatch.setenv("CAMPUSFLOW_LOCAL_HTTP","0")
    assert client.post("/api/v1/auth/demo",params={"role":"admin"}).status_code==404
    monkeypatch.setenv("CAMPUSFLOW_DEMO","0")
    monkeypatch.setenv("CAMPUSFLOW_LOCAL_HTTP","1")
    assert client.post("/api/v1/auth/demo",params={"role":"admin"}).status_code==404

def test_schedule_downloads_pdf_and_editable_word(pilot):
    from io import BytesIO
    from docx import Document
    from app.v1.schedule_models import Lesson

    client, tokens, room_id, start = pilot
    group = "ДЕМО-ЭКСПОРТ"
    with app.state.sessions.begin() as db:
        batch = db.scalar(select(ImportBatch).where(ImportBatch.state=="active",ImportBatch.scope=="6"))
        room = db.get(Room,room_id)
        db.add(Lesson(batch_id=batch.id,room_id=room_id,building="6",room_code=room.code,
                      period=Range(start,start+timedelta(minutes=80),bounds="[)"),
                      subject="Дискретная математика (лекция)",groups=[group],teachers=[]))
    day = start.date().isoformat()
    query = {"scope":"group","entity_id":group,"from":day,"to":day}
    route = "/api/v1/schedule/export/"
    assert client.get(route+"docx",params=query).status_code==401
    headers=tokens["student"]
    pdf=client.get(route+"pdf",params=query,headers=headers)
    assert pdf.status_code==200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-disposition"].endswith('.pdf"')
    word=client.get(route+"docx",params=query,headers=headers)
    assert word.status_code==200 and word.headers["content-disposition"].endswith('.docx"')
    document=Document(BytesIO(word.content))
    assert document.paragraphs[0].text=="Расписание занятий"
    assert document.tables[0].cell(1,1).text=="Дискретная математика (лекция)"
    assert document.tables[0].cell(1,3).text==group
    assert client.get(route+"pdf",params={**query,"scope":"teacher","building":"6","entity_id":"1"},
                      headers=headers).status_code==403

def test_standalone_booking_without_schedule(pilot, monkeypatch):
    client, tokens, room_id, start = pilot
    monkeypatch.setenv('CAMPUSFLOW_BOOKING_MODE', 'standalone')
    with app.state.sessions.begin() as db:
        room = db.get(Room, room_id)
        room.building = 'independent-campus'
        room.kind = 'seminar'
    assert hold(client, tokens['student'], room_id, start).status_code == 403
    assert hold(client, tokens['teacher'], room_id, start).status_code == 201
    assert hold(client, tokens['admin'], room_id, start).status_code == 409
    query = dict(day=start.date().isoformat(), kind='seminar', count=10,
                 duration=30, building='independent-campus', start_minute=15*60)
    response = client.get('/api/v1/slots/recommendations', params=query, headers=tokens['teacher'])
    assert response.status_code == 200 and response.json()['options']
    monkeypatch.setenv('CAMPUSFLOW_BOOKING_MODE', 'schedule')
    response = hold(client, tokens['teacher'], room_id, start+timedelta(hours=3))
    assert response.status_code == 409 and response.json()['detail']['code'] == 'no_coverage'

def test_apply_rejects_more_teacher_breaks(pilot):
    from app.v1.optimizer import BELL
    from app.v1.analytics import moment
    client, tokens, room_id, start = pilot
    admin = tokens['admin']
    day = start.date()
    with app.state.sessions.begin() as db:
        room = db.get(Room, room_id)
        room.kind = 'seminar'
        code = room.code
    lines = ['start,end,building,room,subject,groups,teachers']
    for index in (0,1):
        a,b = BELL[index]
        lines.append(f'{moment(day,a).isoformat()},{moment(day,b).isoformat()},6,{code},Synthetic {index},G{index},One synthetic teacher')
    upload = client.post('/api/v1/admin/imports', headers=admin,
        data=dict(scope='6',date_from=day.isoformat(),date_to=day.isoformat(),complete='true'),
        files={'file':('schedule.csv','\n'.join(lines).encode())})
    assert upload.status_code == 201, upload.text
    assert client.post(f"/api/v1/admin/imports/{upload.json()['id']}/publish", headers=admin).status_code == 200
    assert client.put('/api/v1/admin/group-sizes',headers=admin,json={'sizes':{'G0':20,'G1':20}}).status_code == 200
    rows = client.get('/api/v1/schedule',headers=admin,params={'scope':'group','entity_id':'G0','from':str(day),'to':str(day)}).json()['items']
    lesson_id = rows[0]['id']
    plan = client.post('/api/v1/admin/optimization-runs',headers=admin,json={
        'day':str(day),'requirements':{str(lesson_id):{'unavailable_slots':[1,2,3,4]}}})
    assert plan.status_code == 200 and plan.json()['assignments'], plan.text
    response = client.post(f"/api/v1/admin/proposals/{plan.json()['id']}/apply",headers={**admin,'Idempotency-Key':uuid4().hex},json={'lesson_ids':[lesson_id]})
    assert response.status_code == 409 and 'перерывы преподавателя' in response.text
