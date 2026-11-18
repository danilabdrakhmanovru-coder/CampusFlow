"""Device-scoped Web Push. VAPID private key is a base64url PKCS8 DER key."""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
import re

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .activity_models import Outbox
from .auth import active_consent, booking_user, db_session
from .db import Base
from .models import RefreshSession, User

router = APIRouter(prefix="/push")
PROVIDERS = re.compile(r"https://(?:[a-z0-9-]+\.)*push\.apple\.com/|https://fcm\.googleapis\.com/|https://updates\.push\.services\.mozilla\.com/")
LIFETIME = {"watch_hold": 300, "booking_reminder": 900, "slot_freed": 86400, "cancelled_by_admin": 86400}


class Subscription(Base):
    __tablename__ = "push_subscriptions"
    device: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(2048), unique=True)
    keys: Mapped[dict] = mapped_column(JSONB)
    cursor: Mapped[int]


class Keys(BaseModel):
    p256dh: str = Field(pattern=r"^[A-Za-z0-9_-]{87}$")
    auth: str = Field(pattern=r"^[A-Za-z0-9_-]{22}$")


class Input(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: Keys


def decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def configured():
    return bool(os.getenv("CAMPUSFLOW_PUSH_KEY") and os.getenv("CAMPUSFLOW_PUSH_CONTACT"))


@router.get("")
def settings(user=Depends(booking_user), db=Depends(db_session)):
    key = None
    if configured():
        private = serialization.load_der_private_key(decode(os.environ["CAMPUSFLOW_PUSH_KEY"]), password=None)
        raw = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        key = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {"key": key, "enabled": db.get(Subscription, user.device) is not None}


@router.put("")
def subscribe(data: Input, user=Depends(booking_user), db=Depends(db_session)):
    if not configured():
        raise HTTPException(503, "Уведомления на устройстве пока не настроены")
    if not PROVIDERS.match(data.endpoint) or "\\" in data.endpoint:
        raise HTTPException(422, "Служба доставки этого браузера не поддерживается")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode(data.keys.p256dh))
    except ValueError:
        raise HTTPException(422, "Неверный ключ устройства")
    # Preserve progress for retries; a fresh sign-in starts with future events.
    sub = db.get(Subscription, user.device)
    if sub and sub.endpoint == data.endpoint and sub.keys == data.keys.model_dump():
        return {"enabled": True}
    db.execute(delete(Subscription).where((Subscription.device == user.device) | (Subscription.endpoint == data.endpoint)))
    cursor = db.scalar(select(func.max(Outbox.id)).where(Outbox.user_id == user.id)) or 0
    db.add(Subscription(device=user.device, user_id=user.id, endpoint=data.endpoint, keys=data.keys.model_dump(), cursor=cursor))
    db.commit()
    return {"enabled": True}


@router.delete("", status_code=204)
def unsubscribe(user=Depends(booking_user), db=Depends(db_session)):
    db.execute(delete(Subscription).where(Subscription.device == user.device))
    db.commit()


class ProviderSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def deliver(db):
    if not configured():
        return
    from pywebpush import WebPushException, webpush
    clock = datetime.now(timezone.utc)
    active = select(RefreshSession.device_id).where(RefreshSession.expires_at > clock, RefreshSession.consent_pending.is_(False))
    db.execute(delete(Subscription).where(Subscription.device.not_in(active)))
    db.commit()
    pending = select(Outbox.id).where(Outbox.user_id == Subscription.user_id, Outbox.id > Subscription.cursor).exists()
    devices = db.scalars(select(Subscription.device).where(pending)).all()
    for device in devices:
        sub = db.scalar(select(Subscription).where(Subscription.device == device).with_for_update(skip_locked=True))
        if not sub:
            db.rollback()
            continue
        owner = db.get(User, sub.user_id)
        if not owner.active or owner.role not in {"teacher", "admin"} or not active_consent(db, owner.id):
            db.delete(sub)
            db.commit()
            continue
        events = db.scalars(select(Outbox).where(Outbox.user_id == sub.user_id, Outbox.id > sub.cursor).order_by(Outbox.id).limit(20)).all()
        for event in events:
            expires = event.created_at + timedelta(seconds=LIFETIME.get(event.kind, 0))
            ttl = int((expires - datetime.now(timezone.utc)).total_seconds())
            if ttl > 0 and owner.preferences.get("notifications", {}).get(event.kind, True):
                try:
                    with ProviderSession() as transport:
                        webpush(requests_session=transport, subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
                            data=json.dumps({"kind": event.kind, "id": event.id, "until": expires.isoformat()}),
                            vapid_private_key=os.environ["CAMPUSFLOW_PUSH_KEY"],
                            vapid_claims={"sub": os.environ["CAMPUSFLOW_PUSH_CONTACT"]}, ttl=ttl, timeout=4)
                except WebPushException as exc:
                    if exc.response is not None and exc.response.status_code in {404, 410}:
                        db.delete(sub)
                    break
                except OSError:
                    break
            sub.cursor = event.id
        db.commit()
