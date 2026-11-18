from os import environ

from .auth import secret


def schedule_secret():
    value = environ.get("CAMPUSFLOW_SCHEDULE_SECRET", "")
    if len(value.encode()) < 32 or value == secret():
        raise RuntimeError("Set a separate CAMPUSFLOW_SCHEDULE_SECRET of at least 32 bytes")
    return value
