"""Separate scheduling staff from system administrators."""
from alembic import op

revision = "0011_dean"
down_revision = "0010_schedule_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("user_role", "users", type_="check")
    op.create_check_constraint("user_role", "users", "role IN ('student','teacher','dean','admin')")


def downgrade():
    op.drop_constraint("user_role", "users", type_="check")
    op.execute("UPDATE users SET role='student' WHERE role='dean'")
    op.create_check_constraint("user_role", "users", "role IN ('student','teacher','admin')")
