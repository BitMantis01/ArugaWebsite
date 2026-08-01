import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import BASE_DIR

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
    engine = create_engine(DATABASE_URL)

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
    Base.metadata.create_all(bind=engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            from sqlalchemy import text
            try:
                columns = [row[1] for row in conn.execute(text("PRAGMA table_info(medicines)")).fetchall()]
                if "slot_number" not in columns:
                    conn.execute(text("ALTER TABLE medicines ADD COLUMN slot_number INTEGER DEFAULT 1"))
                if "scheduled_datetime" not in columns:
                    conn.execute(text("ALTER TABLE medicines ADD COLUMN scheduled_datetime DATETIME"))
                if "is_dispensed" not in columns:
                    conn.execute(text("ALTER TABLE medicines ADD COLUMN is_dispensed BOOLEAN DEFAULT 0"))
                conn.commit()
            except Exception as e:
                pass


def init_db():
    migrate_db()

