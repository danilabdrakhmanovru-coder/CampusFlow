from collections import defaultdict

from sqlalchemy import select

from .schedule_models import TeacherNumber


def building_key(building):
    return building or "unknown"


def register_numbers(db, rows):
    """Called under the import advisory lock."""
    known = defaultdict(dict)
    for row in db.scalars(select(TeacherNumber)):
        known[row.building][row.teacher_key] = row.number
    incoming = defaultdict(set)
    for row in rows:
        incoming[building_key(row["building"])].update(row["teachers"])
    for building, keys in incoming.items():
        numbers = known[building]
        first = max(numbers.values(), default=0) + 1
        for number, key in enumerate(sorted(keys - numbers.keys()), first):
            db.add(TeacherNumber(building=building, teacher_key=key, number=number))


def directory(db):
    return {(r.building, r.teacher_key): r.number for r in db.scalars(select(TeacherNumber))}


def teacher_view(building, number, key=None):
    from .demo_examples import is_demo, TEACHER_NAMES
    if is_demo() and key in TEACHER_NAMES:
        return {"building":building,"number":number,"label":TEACHER_NAMES[key]}
    return {"building": building, "number": number, "label": f"Преподаватель №{number}"}
