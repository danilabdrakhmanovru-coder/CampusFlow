"""Booking tickets, waiting list and in-app notifications."""
from alembic import op

revision = "0004_pulse"
down_revision = "0003_teacher_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE tickets (
            booking_id integer PRIMARY KEY REFERENCES bookings(id) ON DELETE CASCADE,
            token varchar(100) NOT NULL UNIQUE,
            check_in_at timestamptz,
            auto_release_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_ticket_release ON tickets (auto_release_at) WHERE check_in_at IS NULL")
    op.execute("""
        CREATE TABLE watches (
            id serial PRIMARY KEY,
            user_id integer NOT NULL REFERENCES users(id),
            room_id integer NOT NULL REFERENCES rooms(id),
            period tstzrange NOT NULL,
            state varchar(16) NOT NULL,
            hold_id integer REFERENCES booking_holds(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX ix_watch_queue ON watches (room_id, id) WHERE state = 'waiting'")
    op.execute("""
        CREATE TABLE outbox_events (
            id serial PRIMARY KEY,
            user_id integer NOT NULL REFERENCES users(id),
            kind varchar(40) NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    op.drop_table("outbox_events")
    op.drop_table("watches")
    op.drop_table("tickets")
