from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB, TSTZRANGE
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.types import DateTime

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    preferences: Mapped[dict] = mapped_column(JSONB,default=dict,server_default="{}")
    teacher_link_requested_at = mapped_column(DateTime(timezone=True))
    deletion_requested_at = mapped_column(DateTime(timezone=True))
    auth_version: Mapped[int] = mapped_column(default=1, server_default="1")
    __table_args__ = (CheckConstraint("role IN ('student','teacher','dean','admin')", name="user_role"),)


class Identity(Base):
    __tablename__ = "auth_identities"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str]
    subject: Mapped[str]
    password_hash: Mapped[str | None]
    __table_args__ = (UniqueConstraint("provider", "subject"),)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    digest: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    device_id: Mapped[str]
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    consent_pending: Mapped[bool] = mapped_column(default=False, server_default="false")


class PasswordReset(Base):
    __tablename__ = "password_resets"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    digest: Mapped[str]
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    building: Mapped[str]
    code: Mapped[str]
    floor: Mapped[int | None]
    kind: Mapped[str | None]
    capacity: Mapped[int | None]
    equipment: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    accessible: Mapped[bool | None]
    check_in_digest: Mapped[str | None]
    plan_x: Mapped[float | None]
    plan_y: Mapped[float | None]
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    __table_args__ = (UniqueConstraint("building", "code"), CheckConstraint("capacity > 0", name="room_capacity"))


class Hold(Base):
    __tablename__ = "booking_holds"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(default="active")
    __table_args__ = (
        CheckConstraint("state IN ('active','expired','confirmed','released')", name="hold_state"),
        Index("ix_hold_room_state_expiry", "room_id", "state", "expires_at"),
    )


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    hold_id: Mapped[int] = mapped_column(ForeignKey("booking_holds.id"), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    period = mapped_column(TSTZRANGE, nullable=False)
    title: Mapped[str]
    cancelled_at = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Occupancy(Base):
    __tablename__ = "room_occupancy"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    period = mapped_column(TSTZRANGE, nullable=False)
    kind: Mapped[str]
    hold_id: Mapped[int | None] = mapped_column(ForeignKey("booking_holds.id"), unique=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), unique=True)
    lesson_key: Mapped[str | None]
    __table_args__ = (
        CheckConstraint("NOT isempty(period) AND NOT lower_inf(period) AND NOT upper_inf(period) AND lower_inc(period) AND NOT upper_inc(period)", name="occupancy_period"),
        CheckConstraint("""(kind = 'hold' AND hold_id IS NOT NULL AND booking_id IS NULL AND lesson_key IS NULL)
            OR (kind = 'booking' AND booking_id IS NOT NULL AND hold_id IS NULL AND lesson_key IS NULL)
            OR (kind = 'lesson' AND lesson_key IS NOT NULL AND hold_id IS NULL AND booking_id IS NULL)
            OR (kind = 'block' AND lesson_key IS NULL AND hold_id IS NULL AND booking_id IS NULL)""", name="occupancy_source"),
        ExcludeConstraint(("room_id", "="), ("period", "&&"), using="gist", name="no_room_overlap"),
    )


class Idempotency(Base):
    __tablename__ = "idempotency_keys"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    fingerprint: Mapped[str]
    result: Mapped[dict | None] = mapped_column(JSONB)


class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str]
    object_id: Mapped[int]
    at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Consent(Base):
    __tablename__ = "consent_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    version: Mapped[str]
    at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    withdrawn_at = mapped_column(DateTime(timezone=True), nullable=True)
