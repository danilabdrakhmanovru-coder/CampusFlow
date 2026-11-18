"""Editable public deployment settings stored in one row."""
from os import environ

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class SitePreferences(Base):
    __tablename__ = "site_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB)


ENV_FIELDS = {
    "operator": "CAMPUSFLOW_PRIVACY_OPERATOR", "responsible": "CAMPUSFLOW_PRIVACY_RESPONSIBLE",
    "contact": "CAMPUSFLOW_PRIVACY_CONTACT", "effective_date": "CAMPUSFLOW_PRIVACY_EFFECTIVE_DATE",
    "version": "CAMPUSFLOW_PRIVACY_VERSION", "support_email": "CAMPUSFLOW_SUPPORT_EMAIL",
    "support_hours": "CAMPUSFLOW_SUPPORT_HOURS",
    "booking_days":"CAMPUSFLOW_BOOKING_RETENTION_DAYS", "audit_days":"CAMPUSFLOW_AUDIT_RETENTION_DAYS",
    "session_days":"CAMPUSFLOW_EXPIRED_SESSION_RETENTION_DAYS",
}


def site_preferences(db=None):
    record=db.get(SitePreferences,1) if db is not None else None
    return {key:environ.get(value,"").strip() or None for key,value in ENV_FIELDS.items()} | (record.data if record else {})
