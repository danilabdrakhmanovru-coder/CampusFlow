"""Initial CampusFlow PostgreSQL schema."""
from alembic import op

revision = "0001_booking"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""CREATE EXTENSION IF NOT EXISTS btree_gist""")
    op.execute("""CREATE TABLE rooms (
	id SERIAL NOT NULL,
	building VARCHAR NOT NULL,
	code VARCHAR NOT NULL,
	floor INTEGER,
	kind VARCHAR,
	capacity INTEGER,
	equipment JSONB DEFAULT '{}' NOT NULL,
	accessible BOOLEAN,
	active BOOLEAN DEFAULT 'true' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (building, code),
	CONSTRAINT room_capacity CHECK (capacity > 0)
)""")
    op.execute("""CREATE TABLE users (
	id SERIAL NOT NULL,
	role VARCHAR NOT NULL,
	active BOOLEAN DEFAULT 'true' NOT NULL,
	auth_version INTEGER DEFAULT '1' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT user_role CHECK (role IN ('student','teacher','admin'))
)""")
    op.execute("""CREATE TABLE audit_log (
	id SERIAL NOT NULL,
	actor_id INTEGER NOT NULL,
	at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	action VARCHAR NOT NULL,
	object_id INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_id) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE auth_identities (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	provider VARCHAR NOT NULL,
	subject VARCHAR NOT NULL,
	password_hash VARCHAR,
	PRIMARY KEY (id),
	UNIQUE (provider, subject),
	FOREIGN KEY(user_id) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE booking_holds (
	id SERIAL NOT NULL,
	owner_id INTEGER NOT NULL,
	room_id INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	state VARCHAR NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT hold_state CHECK (state IN ('active','expired','confirmed','released')),
	FOREIGN KEY(owner_id) REFERENCES users (id),
	FOREIGN KEY(room_id) REFERENCES rooms (id)
)""")
    op.execute("""CREATE INDEX ix_hold_room_state_expiry ON booking_holds (room_id, state, expires_at)""")
    op.execute("""CREATE TABLE consent_events (
	user_id INTEGER NOT NULL,
	version VARCHAR NOT NULL,
	at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id, version),
	FOREIGN KEY(user_id) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE idempotency_keys (
	user_id INTEGER NOT NULL,
	operation VARCHAR NOT NULL,
	key VARCHAR NOT NULL,
	fingerprint VARCHAR NOT NULL,
	result JSONB,
	PRIMARY KEY (user_id, operation, key),
	FOREIGN KEY(user_id) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE refresh_sessions (
	digest VARCHAR NOT NULL,
	user_id INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (digest),
	FOREIGN KEY(user_id) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE bookings (
	id SERIAL NOT NULL,
	hold_id INTEGER NOT NULL,
	owner_id INTEGER NOT NULL,
	room_id INTEGER NOT NULL,
	period TSTZRANGE NOT NULL,
	cancelled_at TIMESTAMP WITH TIME ZONE,
	title VARCHAR NOT NULL,
	cancelled_by INTEGER,
	PRIMARY KEY (id),
	UNIQUE (hold_id),
	FOREIGN KEY(hold_id) REFERENCES booking_holds (id),
	FOREIGN KEY(owner_id) REFERENCES users (id),
	FOREIGN KEY(room_id) REFERENCES rooms (id),
	FOREIGN KEY(cancelled_by) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE room_occupancy (
	id SERIAL NOT NULL,
	room_id INTEGER NOT NULL,
	period TSTZRANGE NOT NULL,
	kind VARCHAR NOT NULL,
	hold_id INTEGER,
	booking_id INTEGER,
	lesson_key VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT occupancy_period CHECK (NOT isempty(period) AND NOT lower_inf(period) AND NOT upper_inf(period) AND lower_inc(period) AND NOT upper_inc(period)),
	CONSTRAINT occupancy_source CHECK ((kind = 'hold' AND hold_id IS NOT NULL AND booking_id IS NULL AND lesson_key IS NULL)
            OR (kind = 'booking' AND booking_id IS NOT NULL AND hold_id IS NULL AND lesson_key IS NULL)
            OR (kind = 'lesson' AND lesson_key IS NOT NULL AND hold_id IS NULL AND booking_id IS NULL)
            OR (kind = 'block' AND lesson_key IS NULL AND hold_id IS NULL AND booking_id IS NULL)),
	CONSTRAINT no_room_overlap EXCLUDE USING gist (room_id WITH =, period WITH &&),
	FOREIGN KEY(room_id) REFERENCES rooms (id),
	UNIQUE (hold_id),
	FOREIGN KEY(hold_id) REFERENCES booking_holds (id),
	UNIQUE (booking_id),
	FOREIGN KEY(booking_id) REFERENCES bookings (id)
)""")


def downgrade():
    op.execute("""DROP TABLE room_occupancy""")
    op.execute("""DROP TABLE bookings""")
    op.execute("""DROP TABLE refresh_sessions""")
    op.execute("""DROP TABLE idempotency_keys""")
    op.execute("""DROP TABLE consent_events""")
    op.execute("""DROP TABLE booking_holds""")
    op.execute("""DROP TABLE auth_identities""")
    op.execute("""DROP TABLE audit_log""")
    op.execute("""DROP TABLE users""")
    op.execute("""DROP TABLE rooms""")
