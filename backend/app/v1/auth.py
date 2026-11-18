import hashlib
from os import environ
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import delete, select, update

from ..security import password_hash, verify_password
from .models import Audit, Consent, Identity, PasswordReset, RefreshSession, User
from .privacy import policy_version
from .login_throttle import bucket_key, buckets, lock_buckets, record_failure

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "cf_refresh"

ISSUER = "campusflow"
bearer = HTTPBearer(auto_error=False)
dummy = password_hash(secrets.token_urlsafe())


def secret():
    value = environ["CAMPUSFLOW_JWT_SECRET"]
    if len(value.encode()) < 32:
        raise RuntimeError("CAMPUSFLOW_JWT_SECRET must contain at least 32 bytes")
    return value


async def db_session(request: Request):
    with request.app.state.sessions() as db:
        yield db


def unauthorized():
    return HTTPException(401, "Войдите в CampusFlow", headers={"WWW-Authenticate": "Bearer"})


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(db_session)):
    if credentials is None:
        raise unauthorized()
    try:
        claims = jwt.decode(credentials.credentials, secret(), algorithms=["HS256"], issuer=ISSUER,
                            audience="campusflow-api", options={"require": ["sub", "exp", "iat", "ver", "role", "policy", "device"]})
        user = db.get(User, int(claims["sub"]))
        consent = active_consent(db, user.id) if user else None
        device = db.scalar(select(RefreshSession.device_id).where(
            RefreshSession.device_id == claims["device"], RefreshSession.user_id == user.id,
            RefreshSession.expires_at > datetime.now(timezone.utc), RefreshSession.consent_pending.is_(False),
        )) if user else None
        if user:
            user.device = device
        version = policy_version(db)
        if user:
            db.expunge(user)
        db.rollback()
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized()
    if not user or not user.active or user.auth_version != claims["ver"] or user.role != claims["role"] or claims["policy"] != version or consent is None or device is None:
        raise unauthorized()
    return user


def booking_user(user=Depends(current_user)):
    if user.role not in {"teacher", "admin"}:
        raise HTTPException(403, "Бронирование доступно преподавателю и администратору")
    return user


def schedule_staff(user=Depends(current_user)):
    if user.role not in {"dean", "admin"}:
        raise HTTPException(403, "Доступно сотрудникам деканата")
    return user


def admin_user(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Доступно администратору")
    return user


class Login(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


class ConsentInput(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    policy_accepted: StrictBool
    consent_accepted: StrictBool


def active_consent(db, user_id):
    return db.scalar(select(Consent.id).where(
        Consent.user_id == user_id, Consent.version == policy_version(db), Consent.withdrawn_at.is_(None),
    ))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def same_origin(request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Недопустимый источник запроса")


def profile(user):
    return {"id": user.id, "role": user.role}


def issue(db, user, response, *, needs_consent=False, device_id=None, created_at=None):
    now = datetime.now(timezone.utc)
    device_id = device_id or secrets.token_hex(16)
    body = {"status": "consent_required", "version": policy_version(db)}
    lifetime = timedelta(minutes=15) if needs_consent else timedelta(days=7)
    if not needs_consent:
        access = jwt.encode({
            "iss": ISSUER, "aud": "campusflow-api", "sub": str(user.id), "role": user.role,
            "iat": now, "exp": now + timedelta(minutes=10), "ver": user.auth_version, "policy": policy_version(db), "device": device_id,
        }, secret(), algorithm="HS256")
        body = {"status": "authenticated", "access_token": access, "token_type": "bearer", **profile(user)}
    refresh = secrets.token_urlsafe(32)
    db.add(RefreshSession(digest=digest(refresh), user_id=user.id, expires_at=now + lifetime,
                          consent_pending=needs_consent, device_id=device_id, created_at=created_at or now))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(COOKIE, refresh, httponly=True, secure=environ.get("CAMPUSFLOW_LOCAL_HTTP") != "1",
                        samesite="strict", path="/api/v1/auth", max_age=int(lifetime.total_seconds()))
    return body


def cookie_account(request, db):
    token = request.cookies.get(COOKIE)
    if not token:
        raise unauthorized()
    match = (RefreshSession.digest == digest(token),
             RefreshSession.expires_at > datetime.now(timezone.utc))
    session = db.execute(select(RefreshSession.user_id, RefreshSession.consent_pending, RefreshSession.device_id, RefreshSession.created_at).where(*match)).one_or_none()
    if session is None:
        raise unauthorized()
    user = db.scalar(select(User).where(User.id == session.user_id).with_for_update())
    if not user or not user.active:
        raise unauthorized()
    return user, match, session


@router.post("/login")
def login(data: Login, request: Request, response: Response, db=Depends(db_session)):
    same_origin(request)
    login_name = data.login.strip().casefold()
    ip = request.client.host if request.client else "unknown"
    rows, clock = lock_buckets(db, login_name, ip, secret())
    retry = max(row.blocked_until for row in rows) - clock
    if retry.total_seconds() > 0:
        seconds = max(1, int(retry.total_seconds()) + 1)
        raise HTTPException(429, "Слишком много попыток входа. Повторите позже.",
                            headers={"Retry-After": str(seconds)})
    identity = db.scalar(select(Identity).where(Identity.provider == "local", Identity.subject == login_name))
    valid = verify_password(data.password, (identity.password_hash if identity else None) or dummy)
    if not identity or not identity.password_hash or not valid:
        delay = record_failure(db, rows, clock)
        if delay and identity:
            db.add(Audit(actor_id=identity.user_id, action="login.throttled", object_id=identity.user_id))
        db.commit()
        raise unauthorized()
    user = db.scalar(select(User).where(User.id == identity.user_id).with_for_update())
    if not user or not user.active:
        raise unauthorized()
    login_key = bucket_key("login:" + login_name, secret())
    db.execute(update(buckets).where(buckets.c.key == login_key).values(
        failures=0, blocked_until=clock, touched_at=clock))
    previous = request.cookies.get(COOKIE)
    if previous:
        db.execute(delete(RefreshSession).where(RefreshSession.digest == digest(previous)))
    return issue(db, user, response, needs_consent=active_consent(db, user.id) is None)


@router.post("/demo")
def enter_demo(role: Literal["student", "teacher", "dean", "admin"], request: Request, response: Response, db=Depends(db_session)):
    if environ.get("CAMPUSFLOW_DEMO") != "1" or environ.get("CAMPUSFLOW_LOCAL_HTTP") != "1":
        raise HTTPException(404, "Демонстрационный вход недоступен")
    from .demo import ACCOUNTS
    return login(Login(login=role,password=dict(ACCOUNTS)[role]),request,response,db)


@router.post("/refresh")
def refresh(request: Request, response: Response, db=Depends(db_session)):
    same_origin(request)
    user, match, session = cookie_account(request, db)
    needs_consent = active_consent(db, user.id) is None
    if session.consent_pending and needs_consent:
        response.headers["Cache-Control"] = "no-store"
        return {"status": "consent_required", "version": policy_version(db)}
    if db.execute(delete(RefreshSession).where(*match)).rowcount != 1:
        raise unauthorized()
    return issue(db, user, response, needs_consent=needs_consent, device_id=session.device_id, created_at=session.created_at)


@router.post("/consent")
def accept_consent(data: ConsentInput, request: Request, response: Response, db=Depends(db_session)):
    same_origin(request)
    version = policy_version(db)
    if data.version != version:
        raise HTTPException(409, {"code": "consent_version_changed", "message": "Документы обновились. Прочитайте новую редакцию."})
    if not data.policy_accepted or not data.consent_accepted:
        raise HTTPException(422, "Отметьте ознакомление с политикой и согласие на обработку данных")
    user, match, session = cookie_account(request, db)
    if db.execute(delete(RefreshSession).where(*match)).rowcount != 1:
        raise unauthorized()
    if active_consent(db, user.id) is None:
        db.add(Consent(user_id=user.id, version=version))
        db.add(Audit(actor_id=user.id, action="consent.accepted", object_id=user.id))
    return issue(db, user, response, device_id=session.device_id, created_at=session.created_at)


@router.get("/consents")
def consent_history(response: Response, db=Depends(db_session), user=Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.at.desc(), Consent.id.desc()))
    return [{"id": row.id, "version": row.version, "accepted_at": row.at, "withdrawn_at": row.withdrawn_at}
            for row in rows]


@router.post("/consent/withdraw", status_code=204)
def withdraw_consent(request: Request, response: Response, db=Depends(db_session), user=Depends(current_user)):
    same_origin(request)
    account = db.get(User, user.id, with_for_update=True)
    consent_id = active_consent(db, user.id)
    if not account or not account.active or account.auth_version != user.auth_version or consent_id is None:
        raise unauthorized()
    db.execute(update(Consent).where(
        Consent.user_id == user.id, Consent.withdrawn_at.is_(None),
    ).values(withdrawn_at=datetime.now(timezone.utc)))
    account.auth_version += 1
    db.execute(delete(RefreshSession).where(RefreshSession.user_id == user.id))
    db.add(Audit(actor_id=user.id, action="consent.withdrawn", object_id=user.id))
    db.commit()
    response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db=Depends(db_session)):
    same_origin(request)
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(RefreshSession).where(RefreshSession.digest == digest(token)))
        db.commit()
    response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.get("/me")
def me(user=Depends(current_user)):
    return profile(user)

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/password", status_code=204)
def change_password(data: PasswordChange, response: Response, db=Depends(db_session), user=Depends(current_user)):
    account = db.get(User,user.id,with_for_update=True)
    if not account or not account.active or account.auth_version != user.auth_version:
        raise unauthorized()
    identity = db.scalar(select(Identity).where(Identity.user_id == user.id, Identity.provider == "local").limit(1))
    if identity is None or not identity.password_hash or not verify_password(data.current_password, identity.password_hash):
        raise HTTPException(403, "Текущий пароль неверен")
    new = data.new_password
    if new == data.current_password or not any(ch.isalpha() for ch in new) or not any(ch.isdigit() for ch in new):
        raise HTTPException(422, "Задайте новый пароль из 12 или более знаков, с буквами и цифрами")
    identity.password_hash = password_hash(new)
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    account.auth_version += 1
    db.execute(delete(RefreshSession).where(RefreshSession.user_id == user.id))
    db.add(Audit(actor_id=user.id, action="user.password_changed", object_id=user.id))
    db.commit()
    response.delete_cookie(COOKIE,path="/api/v1/auth")
