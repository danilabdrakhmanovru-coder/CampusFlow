"""Persistent, pseudonymous sign-in throttling."""
from alembic import op

revision = "0005_auth_throttle"
down_revision = "0004_pulse"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE login_throttle (
            key varchar(64) PRIMARY KEY,
            failures integer NOT NULL,
            blocked_until timestamptz NOT NULL,
            touched_at timestamptz NOT NULL
        )
    """)


def downgrade():
    op.drop_table("login_throttle")
