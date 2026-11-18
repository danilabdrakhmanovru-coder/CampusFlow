"""Retention and administrative deletion for the CampusFlow database."""
from datetime import timedelta
from os import environ

from sqlalchemy import delete, func, select, update

from .models import Audit, Booking, Consent, Hold, Idempotency, Identity, Occupancy, PasswordReset, RefreshSession
from .schedule_models import TeacherLink
from .activity_models import Outbox, Watch
from .login_throttle import buckets
from .site_config import site_preferences


def remove_reservations(db, hold_ids, booking_ids):
    if booking_ids:
        db.execute(delete(Occupancy).where(Occupancy.booking_id.in_(booking_ids)))
        db.execute(delete(Idempotency).where(
            Idempotency.operation == "confirm", Idempotency.result["id"].astext.in_([str(i) for i in booking_ids]),
        ))
        db.execute(delete(Booking).where(Booking.id.in_(booking_ids)))
    if hold_ids:
        db.execute(delete(Occupancy).where(Occupancy.hold_id.in_(hold_ids)))
        db.execute(delete(Idempotency).where(
            Idempotency.operation == "hold", Idempotency.result["id"].astext.in_([str(i) for i in hold_ids]),
        ))
        db.execute(delete(Hold).where(Hold.id.in_(hold_ids)))


def retention_days(key, default):
    value = int(environ.get(f"CAMPUSFLOW_{key}_DAYS", default))
    if value < 1:
        raise ValueError(f"CAMPUSFLOW_{key}_DAYS must be a positive integer")
    return value


def cleanup(db):
    clock = db.scalar(select(func.clock_timestamp()))
    config=site_preferences(db)
    booking_cutoff = clock - timedelta(days=int(config["booking_days"] or retention_days("BOOKING_RETENTION", 365)))
    audit_cutoff = clock - timedelta(days=int(config["audit_days"] or retention_days("AUDIT_RETENTION", 365)))
    session_cutoff = clock - timedelta(days=int(config["session_days"] or retention_days("EXPIRED_SESSION_RETENTION", 1)))
    # Remove confirmed bookings before the holds they reference.
    booking_ids = db.scalars(select(Booking.id).where(
        func.upper(Booking.period) < booking_cutoff,
        (Booking.cancelled_at.is_(None) | (Booking.cancelled_at < booking_cutoff)),
    ).order_by(Booking.id).limit(1000).with_for_update(skip_locked=True)).all()
    hold_ids = db.scalars(select(Hold.id).where(
        Hold.expires_at < booking_cutoff,
        ~select(Booking.id).where(Booking.hold_id == Hold.id, Booking.id.not_in(booking_ids)).exists(),
    ).order_by(Hold.id).limit(1000).with_for_update(skip_locked=True)).all()
    remove_reservations(db, hold_ids, booking_ids)
    audit = db.execute(delete(Audit).where(Audit.at < audit_cutoff)).rowcount
    db.execute(delete(PasswordReset).where(PasswordReset.expires_at < clock))
    sessions = db.execute(delete(RefreshSession).where(RefreshSession.expires_at < session_cutoff)).rowcount
    db.execute(delete(buckets).where(buckets.c.touched_at < clock - timedelta(days=1)))
    db.execute(delete(Outbox).where(Outbox.created_at < audit_cutoff))
    db.execute(delete(Watch).where(func.upper(Watch.period) < booking_cutoff))
    return {"bookings": len(booking_ids), "holds": len(hold_ids), "audit": audit, "sessions": sessions}


def erase_account(db, user):
    user.active = False
    user.auth_version += 1
    db.flush()
    bookings = db.scalars(select(Booking.id).where(Booking.owner_id == user.id)).all()
    holds = db.scalars(select(Hold.id).where(Hold.owner_id == user.id)).all()
    remove_reservations(db, holds, bookings)
    user.preferences = {}
    user.teacher_link_requested_at = user.deletion_requested_at = None
    for model in (Identity, Consent, PasswordReset, RefreshSession, Idempotency, TeacherLink, Watch, Outbox):
        db.execute(delete(model).where(model.user_id == user.id))
    db.execute(delete(Audit).where(
        (Audit.actor_id == user.id) | (Audit.action.like("user.%") & (Audit.object_id == user.id)),
    ))
    db.execute(update(Booking).where(Booking.cancelled_by == user.id).values(cancelled_by=None))
