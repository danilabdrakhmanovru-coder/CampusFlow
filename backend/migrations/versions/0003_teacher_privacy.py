"""Building-scoped teacher directory and account links."""
from alembic import op

revision = "0003_teacher_privacy"
down_revision = "0002_schedule"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE teacher_numbers (
            building varchar(120) NOT NULL,
            teacher_key varchar(100) NOT NULL,
            number integer NOT NULL CHECK (number > 0),
            PRIMARY KEY (building, teacher_key),
            UNIQUE (building, number)
        )
    """)
    op.execute("""
        INSERT INTO teacher_numbers (building, teacher_key, number)
        SELECT building, teacher_key, row_number() OVER (PARTITION BY building ORDER BY teacher_key)
        FROM (
            SELECT DISTINCT coalesce(nullif(building, ''), 'unknown') AS building, teacher_key
            FROM scheduled_lessons CROSS JOIN LATERAL jsonb_array_elements_text(teachers) AS t(teacher_key)
        ) AS pairs
    """)
    op.execute("""
        CREATE TABLE teacher_links (
            user_id integer PRIMARY KEY REFERENCES users(id),
            teacher_key varchar(100) NOT NULL UNIQUE
        )
    """)


def downgrade():
    op.drop_table("teacher_links")
    op.drop_table("teacher_numbers")
