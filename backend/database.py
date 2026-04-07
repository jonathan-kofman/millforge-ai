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
    from db_models import (  # noqa: F401
        User, OrderRecord, ScheduleRun, InspectionRecord, ContactSubmission,
        MachineStateLog, JobFeedbackRecord, InventoryStock, Supplier, Job,
        Machine, QCResult, ToolRecord, SensorReading,
        # Quality & Compliance modules
        MaterialCert, DrawingInspection, LogbookEntry, LogbookAISummary,
        AS9100Clause, AS9100ComplianceStatus, AS9100Procedure, AS9100AuditTrail,
        ToolingInsert, ToolPresetMeasurement,
    )
    from discovery.models import Interview, Insight, DiscoveryPattern  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _apply_column_migrations()


def _apply_column_migrations() -> None:
    """Add columns to existing tables that predate them. Safe to run repeatedly."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE shop_configs ADD COLUMN shifts_per_day INTEGER DEFAULT 2",
        "ALTER TABLE shop_configs ADD COLUMN hours_per_shift INTEGER DEFAULT 8",
        "ALTER TABLE suppliers ADD COLUMN lead_time_days INTEGER DEFAULT 7",
        # Tool presetter columns
        "ALTER TABLE tool_records ADD COLUMN measured_length_mm FLOAT",
        "ALTER TABLE tool_records ADD COLUMN measured_diameter_mm FLOAT",
        # Order customer tracking fields
        "ALTER TABLE orders ADD COLUMN customer_name VARCHAR(255)",
        "ALTER TABLE orders ADD COLUMN po_number VARCHAR(100)",
        "ALTER TABLE orders ADD COLUMN part_number VARCHAR(100)",
    ]
    for sql in migrations:
        # Use a fresh connection per migration — on Postgres, a failed DDL statement
        # poisons the current transaction and all subsequent executes on that connection
        # fail silently. Opening a new connection per statement avoids this.
        with engine.connect() as conn:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists
