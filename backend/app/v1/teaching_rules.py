"""Recurring teacher availability and protection of existing teaching days."""
from collections import defaultdict

from sqlalchemy import select

from .models import User
from .schedule_models import TeacherLink


def days_off(db):
    rules = defaultdict(set)
    for key, preferences in db.execute(select(TeacherLink.teacher_key, User.preferences).join(
        User, User.id == TeacherLink.user_id,
    )):
        rules[key].update(preferences.get("teaching_days_off", []))
    return rules


def teacher_gaps(rows, timezone):
    by_day = defaultdict(list)
    for row in rows:
        for teacher in row["teachers"]:
            period = row["period"]
            by_day[teacher, period.lower.astimezone(timezone).date()].append(period)
    totals = defaultdict(int)
    for (teacher, _), periods in by_day.items():
        previous = None
        for period in sorted(periods, key=lambda p: (p.lower, p.upper)):
            if previous is not None:
                totals[teacher] += max(0, int((period.lower-previous).total_seconds()//60))
            previous = max(previous, period.upper) if previous else period.upper
    return totals
