"""Preserve every acceptance and its withdrawal time."""
from alembic import op

revision = "0008_consent_history"
down_revision = "0007_proposals"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE refresh_sessions ADD COLUMN consent_pending boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE consent_events ADD COLUMN id serial, ADD COLUMN withdrawn_at timestamptz")
    op.execute("ALTER TABLE consent_events DROP CONSTRAINT consent_events_pkey, ADD PRIMARY KEY (id)")
    op.execute("""CREATE UNIQUE INDEX consent_events_active_version
        ON consent_events (user_id, version) WHERE withdrawn_at IS NULL""")
    op.execute("CREATE INDEX consent_events_user_history ON consent_events (user_id, at DESC)")


def downgrade():
    op.execute("DROP INDEX consent_events_active_version")
    op.execute("DROP INDEX consent_events_user_history")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM consent_events WHERE withdrawn_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Cannot downgrade consent history without losing withdrawal records';
        END IF;
    END $$""")
    op.execute("""ALTER TABLE consent_events DROP CONSTRAINT consent_events_pkey,
        DROP COLUMN id, DROP COLUMN withdrawn_at, ADD PRIMARY KEY (user_id, version)""")
    op.execute("DELETE FROM refresh_sessions WHERE consent_pending")
    op.execute("ALTER TABLE refresh_sessions DROP COLUMN consent_pending")
