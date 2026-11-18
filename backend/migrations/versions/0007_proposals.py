"""Persist optimization proposals and their applied subset."""
from alembic import op

revision = "0007_proposals"
down_revision = "0006_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE proposals (
            id serial PRIMARY KEY,
            result jsonb NOT NULL,
            source_versions jsonb NOT NULL,
            applied jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    op.drop_table("proposals")
