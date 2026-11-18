from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Ticket(Base):
    __tablename__ = "tickets"
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True)
    token: Mapped[str] = mapped_column(String(100), unique=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at = mapped_column(DateTime(timezone=True))
    auto_release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Watch(Base):
    __tablename__ = "watches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    period = mapped_column(TSTZRANGE, nullable=False)
    state: Mapped[str] = mapped_column(String(16))
    hold_id: Mapped[int | None] = mapped_column(ForeignKey("booking_holds.id", ondelete="SET NULL"))


class Outbox(Base):
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
