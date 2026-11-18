"""Profile settings, device sessions and one-time password reset."""
from alembic import op

revision = "0009_profiles"
down_revision = "0008_consent_history"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""ALTER TABLE users ADD COLUMN preferences jsonb NOT NULL DEFAULT '{}',
        ADD COLUMN teacher_link_requested_at timestamptz, ADD COLUMN deletion_requested_at timestamptz""")
    op.execute("""ALTER TABLE refresh_sessions ADD COLUMN device_id varchar(64),
        ADD COLUMN created_at timestamptz NOT NULL DEFAULT now()""")
    op.execute("UPDATE refresh_sessions SET device_id = digest")
    op.execute("ALTER TABLE refresh_sessions ALTER COLUMN device_id SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX refresh_sessions_device ON refresh_sessions (device_id)")
    op.execute("""CREATE TABLE password_resets (user_id integer PRIMARY KEY REFERENCES users(id),
        digest varchar(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL)""")
    op.execute("ALTER TABLE rooms ADD COLUMN check_in_digest varchar(64)")
    op.execute("ALTER TABLE tickets ADD COLUMN reminder_sent_at timestamptz")


def downgrade():
    op.execute("ALTER TABLE tickets DROP COLUMN reminder_sent_at")
    op.execute("ALTER TABLE rooms DROP COLUMN check_in_digest")
    op.execute("DROP TABLE password_resets")
    op.execute("DROP INDEX refresh_sessions_device")
    op.execute("ALTER TABLE refresh_sessions DROP COLUMN device_id, DROP COLUMN created_at")
    op.execute("""ALTER TABLE users DROP COLUMN preferences, DROP COLUMN teacher_link_requested_at,
        DROP COLUMN deletion_requested_at""")
