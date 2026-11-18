from getpass import getpass
import argparse
import re

from sqlalchemy import select

from ..security import password_hash
from .bookings import expire_room, lock_room, now
from .db import session_factory
from .models import Hold, Identity, Room, User
from .retention import cleanup


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    user = commands.add_parser("user")
    user.add_argument("login")
    user.add_argument("role", choices=["student", "teacher", "admin"])
    room = commands.add_parser("room")
    room.add_argument("building", choices=["6", "7"])
    room.add_argument("code")
    room.add_argument("capacity", type=int)
    room.add_argument("kind", choices=["lecture", "computer", "laboratory", "seminar"])
    commands.add_parser("expire-holds")
    commands.add_parser("cleanup-data")
    args = parser.parse_args()
    with session_factory().begin() as db:
        if args.command == "user":
            login = args.login.casefold()
            if not re.fullmatch(r"[a-z0-9._-]{1,100}", login):
                parser.error("Use a local pseudonymous login")
            if db.scalar(select(Identity).where(Identity.provider == "local", Identity.subject == login)):
                parser.error("Login already exists")
            password = getpass("Password: ")
            if not 12 <= len(password) <= 128 or password != getpass("Repeat password: "):
                parser.error("Passwords must match and contain 12 to 128 characters")
            account = User(role=args.role)
            db.add(account)
            db.flush()
            db.add(Identity(user_id=account.id, provider="local", subject=login, password_hash=password_hash(password)))
        elif args.command == "cleanup-data":
            print(cleanup(db))
        elif args.command == "expire-holds":
            clock = now(db)
            ids = db.scalars(select(Hold.room_id).where(
                Hold.state == "active", Hold.expires_at <= clock,
            ).distinct().order_by(Hold.room_id)).all()
            for room_id in ids:
                lock_room(db, room_id)
                expire_room(db, room_id, clock)
        else:
            if args.capacity < 1 or not args.code.strip():
                parser.error("Room code and positive capacity required")
            db.add(Room(building=args.building, code=args.code.strip(), capacity=args.capacity, kind=args.kind))


if __name__ == "__main__":
    main()
