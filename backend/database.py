"""
MillForge database setup — SQLAlchemy 2.0 with SQLite for development.

Swap DATABASE_URL in .env to point at Postgres for production.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./millforge.db")

# SQLite needs `check_same_thread=False` in multi-threaded environments
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a database session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called at app startup."""
    # Import here so all models are registered on Base.metadata
    from db_models import User, OrderRecord, ScheduleRun, InspectionRecord, ContactSubmission, MachineStateLog, JobFeedbackRecord  # noqa: F401
    Base.metadata.create_all(bind=engine)
