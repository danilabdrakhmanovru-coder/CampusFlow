from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(16))
    date_from: Mapped[date]
    date_to: Mapped[date]
    source_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    rows: Mapped[list] = mapped_column(JSONB)
    mapping: Mapped[dict] = mapped_column(JSONB)
    report: Mapped[dict] = mapped_column(JSONB)
    complete: Mapped[bool]
    previous_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Lesson(Base):
    __tablename__ = "scheduled_lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"))
    building: Mapped[str | None] = mapped_column(String(120))
    room_code: Mapped[str | None] = mapped_column(String(100))
    period = mapped_column(TSTZRANGE, nullable=False)
    subject: Mapped[str]
    groups: Mapped[list] = mapped_column(JSONB)
    teachers: Mapped[list] = mapped_column(JSONB)

class TeacherNumber(Base):
    __tablename__ = "teacher_numbers"
    building: Mapped[str] = mapped_column(String(120), primary_key=True)
    teacher_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    number: Mapped[int]


class TeacherLink(Base):
    __tablename__ = "teacher_links"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    teacher_key: Mapped[str] = mapped_column(String(100), unique=True)

class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    result: Mapped[dict] = mapped_column(JSONB)
    source_versions: Mapped[list] = mapped_column(JSONB)
    applied: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
