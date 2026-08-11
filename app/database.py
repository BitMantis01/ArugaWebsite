import os
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import BASE_DIR

logger = logging.getLogger(__name__)

raw_db_url = os.getenv("DATABASE_URL")

if raw_db_url:
    if raw_db_url.startswith("postgres://"):
        DATABASE_URL = raw_db_url.replace("postgres://", "postgresql://", 1)
    elif raw_db_url.startswith("sqlite:///"):
        db_filename = raw_db_url.replace("sqlite:///", "", 1)
        db_path = (BASE_DIR / db_filename).resolve() if not os.isabs(db_filename) else Path(db_filename).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        DATABASE_URL = f"sqlite:///{db_path.as_posix()}"
    else:
        DATABASE_URL = raw_db_url
else:
    db_path = (BASE_DIR / "aruga.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{db_path.as_posix()}"

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning(f"Database table initialization warning: {e}")

    with engine.connect() as conn:
        from sqlalchemy import text
        if DATABASE_URL.startswith("sqlite"):
            try:
                columns = [row[1] for row in conn.execute(text("PRAGMA table_info(medicines)")).fetchall()]
                if "slot_number" not in columns:
                    conn.execute(text("ALTER TABLE medicines ADD COLUMN slot_number INTEGER DEFAULT 1"))
                if "scheduled_datetime" not in columns:
                    conn.execute(text("ALTER TABLE medicines ADD COLUMN scheduled_datetime DATETIME"))
                if "is_dispensed" not in columns:
                    conn.execute(text("ALTER TABLE medicines ADD COLUMN is_dispensed BOOLEAN DEFAULT 0"))

                user_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
                if "enable_sms_alerts" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN enable_sms_alerts BOOLEAN DEFAULT 1"))
                if "last_sms_alert_no" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_sms_alert_no INTEGER DEFAULT 0"))
                if "last_sms_alert_time" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_sms_alert_time DATETIME"))
                if "last_sms_alert_vital_id" not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_sms_alert_vital_id INTEGER"))
                conn.execute(text("UPDATE users SET enable_sms_alerts = 1 WHERE enable_sms_alerts IS NULL"))
                conn.commit()
            except Exception as e:
                logger.warning(f"SQLite migration step warning: {e}")
        else:
            # PostgreSQL / Production database migration
            try:
                conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS slot_number INTEGER DEFAULT 1"))
                conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS scheduled_datetime TIMESTAMP"))
                conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS is_dispensed BOOLEAN DEFAULT FALSE"))

                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS enable_sms_alerts BOOLEAN DEFAULT TRUE"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_sms_alert_no INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_sms_alert_time TIMESTAMP"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_sms_alert_vital_id INTEGER"))
                conn.execute(text("UPDATE users SET enable_sms_alerts = TRUE WHERE enable_sms_alerts IS NULL"))
                conn.commit()
            except Exception as e:
                logger.warning(f"PostgreSQL migration step warning: {e}")


def init_db():
    migrate_db()


