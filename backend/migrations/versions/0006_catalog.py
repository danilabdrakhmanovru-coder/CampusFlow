"""Room plan coordinates, walking times and group sizes."""
from alembic import op
from sqlalchemy import Column, Float

revision = "0006_catalog"
down_revision = "0005_auth_throttle"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rooms", Column("plan_x", Float))
    op.add_column("rooms", Column("plan_y", Float))
    op.execute("""
        ALTER TABLE rooms ADD CONSTRAINT room_coordinates CHECK (
            (plan_x IS NULL AND plan_y IS NULL) OR
            (plan_x BETWEEN 0 AND 100 AND plan_y BETWEEN 0 AND 100
                AND plan_x IS NOT NULL AND plan_y IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE TABLE group_sizes (
            group_code varchar(160) PRIMARY KEY,
            size integer NOT NULL CHECK (size BETWEEN 1 AND 10000)
        )
    """)
    op.execute("""
        CREATE TABLE walking_matrix (
            from_room_id integer REFERENCES rooms(id),
            to_room_id integer REFERENCES rooms(id),
            minutes integer NOT NULL CHECK (minutes BETWEEN 1 AND 90),
            PRIMARY KEY (from_room_id, to_room_id),
            CHECK (from_room_id <> to_room_id)
        )
    """)


def downgrade():
    op.drop_table("walking_matrix")
    op.drop_table("group_sizes")
    op.drop_constraint("room_coordinates", "rooms")
    op.drop_column("rooms", "plan_y")
    op.drop_column("rooms", "plan_x")
