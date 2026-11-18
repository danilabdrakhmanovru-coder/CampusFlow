from os import environ

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from .bookings import CAMPUS, standalone_booking
from .optimizer import BELL
from .site_config import site_preferences
from .auth import db_session
from .models import Audit
from .schedule_models import ImportBatch

router = APIRouter()
PUBLICATION_ACTIONS = ("schedule.publish", "schedule.rollback", "proposal.applied")


@router.get("/site")
def site(db=Depends(db_session)):
    batches = db.execute(select(ImportBatch.id, ImportBatch.scope, ImportBatch.created_at).where(
        ImportBatch.state == "active",
    )).all()
    published = db.scalar(select(func.max(Audit.at)).where(
        Audit.action.in_(PUBLICATION_ACTIONS),
    ))
    changed = max((row.created_at for row in batches), default=None)
    if batches and published and (changed is None or published > changed):
        changed = published
    config=site_preferences(db)
    return {
        "booking_mode": "standalone" if standalone_booking() else "schedule",
        "timezone": CAMPUS.key,
        "bell": BELL,
        "name": environ.get("CAMPUSFLOW_SITE_NAME", "CampusFlow"),
        "description": environ.get("CAMPUSFLOW_SITE_DESCRIPTION", "Бронирование аудиторий"),
        "campus": environ.get("CAMPUSFLOW_SITE_CAMPUS", "Учебный кампус"),
        "support_email": config["support_email"],
        "support_hours": config["support_hours"],
        "schedule_source": environ.get("CAMPUSFLOW_SCHEDULE_SOURCE", "Опубликованные выгрузки"),
        "schedule_updated_at": changed,
        "schedule_scopes": sorted({row.scope for row in batches}),
    }
