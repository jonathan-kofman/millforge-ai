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
        # Work center schema (0004)
        WorkCenter, Operator, ShopQuote, RoutingTemplate, RoutingStep,
        Operation, ShopFloorEvent, NonConformanceReport, FirstArticleInspection,
        ProductEvent,
    )
    from discovery.models import Interview, Insight, DiscoveryPattern  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _apply_column_migrations()


def _apply_views_and_triggers() -> None:
    """Create SQLite views and triggers idempotently. No-op on Postgres (views created via Alembic)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import text as _text
    ddl = [
        """CREATE VIEW IF NOT EXISTS v_work_center_utilization AS
        SELECT wc.id AS work_center_id, wc.name AS work_center_name, wc.category, wc.status,
               COUNT(CASE WHEN o.status = 'in_progress' THEN 1 END) AS active_operations,
               COUNT(CASE WHEN o.status IN ('pending','queued') THEN 1 END) AS queued_operations,
               SUM(CASE WHEN o.status = 'complete' THEN COALESCE(o.actual_run_min, o.estimated_run_min) ELSE 0 END) AS total_run_min_completed,
               SUM(CASE WHEN o.status = 'complete' THEN o.estimated_run_min ELSE 0 END) AS total_est_min_completed,
               wc.hourly_rate
        FROM work_centers wc LEFT JOIN operations o ON o.work_center_id = wc.id
        GROUP BY wc.id, wc.name, wc.category, wc.status, wc.hourly_rate""",

        """CREATE VIEW IF NOT EXISTS v_job_progress AS
        SELECT COALESCE(o.order_ref, CAST(sq.id AS TEXT)) AS job_ref, sq.customer_name, sq.part_name,
               COUNT(o.id) AS total_operations,
               COUNT(CASE WHEN o.status = 'complete' THEN 1 END) AS completed_operations,
               COUNT(CASE WHEN o.status = 'in_progress' THEN 1 END) AS active_operations,
               SUM(o.estimated_run_min) AS total_est_run_min,
               SUM(COALESCE(o.actual_run_min, 0)) AS total_actual_run_min,
               MIN(o.created_at) AS started_at, MAX(o.completed_at) AS last_completed_at
        FROM operations o LEFT JOIN shop_quotes sq ON sq.id = o.shop_quote_id
        GROUP BY COALESCE(o.order_ref, CAST(sq.id AS TEXT)), sq.customer_name, sq.part_name""",

        """CREATE VIEW IF NOT EXISTS v_estimation_accuracy AS
        SELECT o.work_center_category, o.operation_name, COUNT(*) AS sample_count,
               AVG(o.estimated_setup_min) AS avg_est_setup_min,
               AVG(o.actual_setup_min) AS avg_actual_setup_min,
               AVG(o.estimated_run_min) AS avg_est_run_min,
               AVG(o.actual_run_min) AS avg_actual_run_min,
               AVG(o.actual_setup_min - o.estimated_setup_min) AS setup_bias_min,
               AVG(o.actual_run_min - o.estimated_run_min) AS run_bias_min,
               CASE WHEN AVG(o.estimated_run_min) > 0
                    THEN ROUND((AVG(o.actual_run_min)-AVG(o.estimated_run_min))/AVG(o.estimated_run_min)*100,1)
                    ELSE NULL END AS run_bias_pct
        FROM operations o WHERE o.status = 'complete'
          AND o.actual_setup_min IS NOT NULL AND o.actual_run_min IS NOT NULL
        GROUP BY o.work_center_category, o.operation_name HAVING COUNT(*) >= 3""",

        """CREATE TRIGGER IF NOT EXISTS trg_operations_status_change
        AFTER UPDATE OF status ON operations WHEN OLD.status != NEW.status
        BEGIN
            INSERT INTO shop_floor_events (user_id, operation_id, work_center_id, event_type, payload_json, occurred_at)
            VALUES (NEW.user_id, NEW.id, NEW.work_center_id, 'status_change',
                    json_object('from', OLD.status, 'to', NEW.status, 'operation_name', NEW.operation_name),
                    datetime('now'));
        END""",
    ]
    for sql in ddl:
        with engine.connect() as conn:
            try:
                conn.execute(_text(sql))
                conn.commit()
            except Exception:
                pass


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
        # Adaptive learning — ARIA simulation metadata on feedback records
        "ALTER TABLE job_feedback ADD COLUMN simulation_confidence FLOAT",
        "ALTER TABLE job_feedback ADD COLUMN tolerance_class VARCHAR(50)",
        # Stripe billing
        "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(32)",
        "ALTER TABLE users ADD COLUMN subscription_status VARCHAR(32)",
        # ARIA bridge V2 — multi-process operations (migration 0005)
        "ALTER TABLE operations ADD COLUMN job_id INTEGER REFERENCES jobs(id)",
        "ALTER TABLE operations ADD COLUMN inspection_required INTEGER DEFAULT 0",
        "ALTER TABLE operations ADD COLUMN is_subcontracted INTEGER DEFAULT 0",
        "ALTER TABLE operations ADD COLUMN subcontractor_name VARCHAR(255)",
        "ALTER TABLE operations ADD COLUMN subcontractor_lead_days INTEGER",
        "ALTER TABLE operations ADD COLUMN ai_confidence FLOAT",
        "ALTER TABLE operations ADD COLUMN detected_features_json TEXT",
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

    # ------------------------------------------------------------------
    # Views — idempotent CREATE ... IF NOT EXISTS
    # Only runs on SQLite (Postgres uses CREATE OR REPLACE VIEW syntax)
    # ------------------------------------------------------------------
    _apply_views_and_triggers()
