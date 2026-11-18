"""Lock and update the account/IP sign-in buckets in one transaction."""
import hashlib
import hmac
from datetime import timedelta

from sqlalchemy import Column, DateTime, Integer, String, Table, func, select, update
from sqlalchemy.dialects.postgresql import insert

from .db import Base

buckets = Table("login_throttle", Base.metadata, Column("key", String(64), primary_key=True),
                Column("failures", Integer, nullable=False), Column("blocked_until", DateTime(timezone=True), nullable=False),
                Column("touched_at", DateTime(timezone=True), nullable=False))


def bucket_key(value, secret):
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def lock_buckets(db, login, ip, secret):
    keys = sorted(bucket_key(value, secret)
                  for value in ("login:" + login, "ip:" + ip))
    clock = db.scalar(select(func.clock_timestamp()))
    rows = []
    for key in keys:
        db.execute(insert(buckets).values(key=key, failures=0, blocked_until=clock,
                                          touched_at=clock).on_conflict_do_nothing())
        rows.append(db.execute(select(buckets).where(buckets.c.key == key).with_for_update()).one())
    now = db.scalar(select(func.clock_timestamp()))
    return rows, now


def record_failure(db, rows, now):
    pause = 0
    for row in rows:
        previous = row.failures if now - row.touched_at < timedelta(minutes=30) else 0
        failures = previous + 1
        delay = min(900, 2 ** min(10, failures - 4)) if failures >= 5 else 0
        pause = max(pause, delay)
        db.execute(update(buckets).where(buckets.c.key == row.key).values(
            failures=failures, blocked_until=now+timedelta(seconds=delay), touched_at=now,
        ))
    return pause
