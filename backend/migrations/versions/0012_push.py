"""Persist device subscriptions and their outbox cursors."""
from alembic import op

revision = "0012_push"
down_revision = "0011_dean"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""CREATE TABLE push_subscriptions (
        device varchar(64) PRIMARY KEY, user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        endpoint varchar(2048) NOT NULL UNIQUE, keys jsonb NOT NULL, cursor integer NOT NULL
    )""")

def downgrade():
    op.drop_table("push_subscriptions")
