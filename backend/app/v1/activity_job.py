from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from .auth import active_consent
from .bookings import expire_room, has_coverage, lock_room, now
from .models import Audit, Booking, Hold, Occupancy, User
from .activity_models import Outbox, Ticket, Watch


def process_room_activity(db):
    clock = now(db)
    reminders = db.execute(select(Ticket, Booking).join(Booking).where(
        Booking.cancelled_at.is_(None), Ticket.reminder_sent_at.is_(None),
        func.lower(Booking.period) > clock, func.lower(Booking.period) <= clock+timedelta(minutes=15),
    ).limit(200).with_for_update(of=Ticket, skip_locked=True)).all()
    for ticket, booking in reminders:
        ticket.reminder_sent_at = clock
        db.add(Outbox(user_id=booking.owner_id, kind="booking_reminder", payload={"booking_id":booking.id}))
    db.commit()
    due = db.execute(select(Booking.id, Booking.room_id).join(Ticket).where(
        Booking.cancelled_at.is_(None), Ticket.check_in_at.is_(None), Ticket.auto_release_at <= clock,
    ).order_by(Booking.room_id, Booking.id).limit(200)).all()
    locked = set()
    for booking_id, room_id in due:
        if room_id not in locked:
            lock_room(db, room_id)
            locked.add(room_id)
        booking = db.get(Booking, booking_id, populate_existing=True)
        ticket = db.get(Ticket, booking_id, populate_existing=True)
        if not booking or not ticket or booking.cancelled_at or ticket.check_in_at:
            continue
        booking.cancelled_at = clock
        db.execute(delete(Occupancy).where(Occupancy.booking_id == booking_id))
        db.add(Audit(actor_id=booking.owner_id, action="booking.auto_released", object_id=booking_id))
        db.add(Outbox(user_id=booking.owner_id, kind="slot_freed", payload={"booking_id": booking_id}))
    # Release room locks before processing the independent waiting queue.
    db.commit()

    db.execute(update(Watch).where(Watch.state == "waiting",
        func.upper(Watch.period) <= clock,
    ).values(state="expired"))
    db.commit()
    queued = db.scalars(select(Watch.id).where(Watch.state == "waiting").order_by(Watch.id)).all()
    db.commit()
    for key in queued:
        candidate = db.get(Watch, key)
        if candidate is None:
            db.rollback()
            continue
        user = db.scalar(select(User).where(User.id == candidate.user_id).with_for_update(read=True))
        if user is None or not user.active or user.role not in {"teacher", "admin"} or not active_consent(db,user.id):
            db.rollback()
            continue
        room = lock_room(db, candidate.room_id)
        db.refresh(candidate, with_for_update=True)
        if candidate.state != "waiting":
            db.rollback()
            continue
        clock = now(db)
        start, end = max(clock, candidate.period.lower), candidate.period.upper
        if end-start < timedelta(minutes=15):
            candidate.state = "expired"
            db.commit()
            continue
        if not room.active or not has_coverage(db, room.building, start, end):
            db.rollback()
            continue
        expire_room(db, room.id, clock)
        period = Range(start, end, bounds="[)")
        if db.scalar(select(Occupancy.id).where(
            Occupancy.room_id == room.id, Occupancy.period.op("&&")(period),
        ).limit(1)):
            db.commit()
            continue
        try:
            hold = Hold(owner_id=candidate.user_id, room_id=room.id,
                        expires_at=clock+timedelta(minutes=5), state="active")
            db.add(hold)
            db.flush()
            db.add(Occupancy(room_id=room.id, period=period, kind="hold", hold_id=hold.id))
            candidate.hold_id, candidate.state = hold.id, "offered"
            db.add(Outbox(user_id=user.id, kind="watch_hold", payload={"watch_id": key, "hold_id": hold.id}))
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if getattr(exc.orig, "sqlstate", None) != "23P01":
                raise
