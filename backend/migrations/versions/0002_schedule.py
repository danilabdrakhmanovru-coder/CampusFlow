"""Versioned schedule staging and normalized lesson storage."""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE
from alembic import op

revision = "0002_schedule"
down_revision = "0001_booking"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_batches",
        Column("id", Integer, primary_key=True),
        Column("actor_id", Integer, ForeignKey("users.id"), nullable=False),
        Column("scope", String(16), nullable=False),
        Column("date_from", Date, nullable=False),
        Column("date_to", Date, nullable=False),
        Column("source_name", String(255), nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("state", String(16), nullable=False),
        Column("rows", JSONB, nullable=False),
        Column("mapping", JSONB, nullable=False),
        Column("report", JSONB, nullable=False),
        Column("complete", Boolean, nullable=False),
        Column("previous_id", Integer, ForeignKey("import_batches.id")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    op.create_index("ix_import_scope_state", "import_batches", ["scope", "state"])
    op.create_table(
        "scheduled_lessons",
        Column("id", Integer, primary_key=True),
        Column("batch_id", Integer, ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        Column("room_id", Integer, ForeignKey("rooms.id")),
        Column("building", String(120)),
        Column("room_code", String(100)),
        Column("period", TSTZRANGE, nullable=False),
        Column("subject", Text, nullable=False),
        Column("groups", JSONB, nullable=False),
        Column("teachers", JSONB, nullable=False),
    )
    op.create_index("ix_lesson_batch", "scheduled_lessons", ["batch_id"])
    op.create_index("ix_lesson_period", "scheduled_lessons", ["period"], postgresql_using="gist")


def downgrade():
    op.drop_table("scheduled_lessons")
    op.drop_table("import_batches")
