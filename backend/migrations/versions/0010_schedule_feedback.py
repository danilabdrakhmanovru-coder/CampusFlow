"""Feedback, versioned ranking models and lesson locks."""
from alembic import op

revision = "0010_schedule_feedback"
down_revision = "0009_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE proposal_feedback (
        proposal_id integer PRIMARY KEY REFERENCES proposals(id), accepted boolean NOT NULL,
        reason varchar(60) NOT NULL, features jsonb NOT NULL, gain integer NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""CREATE TABLE ranking_models (
        id serial PRIMARY KEY, trained_at timestamptz NOT NULL DEFAULT now(),
        sample_count integer NOT NULL UNIQUE, metrics jsonb NOT NULL,
        acceptance_model text NOT NULL, value_model text NOT NULL
    )""")
    op.execute("CREATE TABLE site_preferences (id integer PRIMARY KEY CHECK (id=1), data jsonb NOT NULL)")
    op.execute("CREATE TABLE lesson_pins (key varchar(64) PRIMARY KEY)")


def downgrade():
    op.drop_table("site_preferences")
    op.drop_table("lesson_pins")
    op.drop_table("ranking_models")
    op.drop_table("proposal_feedback")
