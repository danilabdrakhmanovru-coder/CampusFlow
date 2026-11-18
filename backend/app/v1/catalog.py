from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class GroupSize(Base):
    __tablename__ = "group_sizes"
    group_code: Mapped[str] = mapped_column(String(160), primary_key=True)
    size: Mapped[int]


class WalkingTime(Base):
    __tablename__ = "walking_matrix"
    from_room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    to_room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    minutes: Mapped[int]
