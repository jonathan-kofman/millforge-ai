"""work center schema: generalized manufacturing abstraction layer

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-11

Adds:
  - work_centers   — universal machine/station abstraction (31 categories)
  - operators      — shop floor operators with PIN tablet login
  - shop_quotes    — DB-persisted quotes with full cost breakdown
  - routing_templates + routing_steps — reusable operation sequences
  - operations     — process-agnostic work instances with actual vs estimated times
  - shop_floor_events — append-only event log (the data moat)
  - non_conformance_reports — quality failure tracking
  - first_article_inspections — dimensional measurement records

  Views:
  - v_work_center_utilization
  - v_job_progress
  - v_estimation_accuracy

  Trigger:
  - trg_operations_status_change — auto-logs to shop_floor_events on status change
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_centers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("hourly_rate", sa.Float(), nullable=True),
        sa.Column("setup_time_default_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("available_hours_json", sa.Text(), nullable=True),
        sa.Column("capabilities_json", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_centers_id", "work_centers", ["id"])
    op.create_index("ix_work_centers_user_id", "work_centers", ["user_id"])
    op.create_index("ix_work_centers_category", "work_centers", ["category"])
    op.create_index("ix_work_centers_status", "work_centers", ["status"])

    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("initials", sa.String(6), nullable=False),
        sa.Column("pin_code_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("qualifications_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operators_id", "operators", ["id"])
    op.create_index("ix_operators_user_id", "operators", ["user_id"])

    op.create_table(
        "routing_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_routing_templates_id", "routing_templates", ["id"])

    op.create_table(
        "routing_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("routing_templates.id"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("operation_name", sa.String(255), nullable=False),
        sa.Column("work_center_category", sa.String(50), nullable=False),
        sa.Column("estimated_setup_min", sa.Float(), nullable=False, server_default="30"),
        sa.Column("estimated_run_min_per_part", sa.Float(), nullable=False, server_default="5"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_routing_steps_template_id", "routing_steps", ["template_id"])

    op.create_table(
        "shop_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("quote_number", sa.String(20), nullable=False, unique=True),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("part_name", sa.String(255), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("revision", sa.String(20), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("material", sa.String(100), nullable=True),
        sa.Column("routing_template_id", sa.Integer(), sa.ForeignKey("routing_templates.id"), nullable=True),
        sa.Column("material_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("labor_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overhead_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("subcontract_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("markup_pct", sa.Float(), nullable=False, server_default="0.15"),
        sa.Column("total_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_per_part", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shop_quotes_id", "shop_quotes", ["id"])
    op.create_index("ix_shop_quotes_quote_number", "shop_quotes", ["quote_number"], unique=True)
    op.create_index("ix_shop_quotes_status", "shop_quotes", ["status"])

    op.create_table(
        "operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_ref", sa.String(50), nullable=True),
        sa.Column("shop_quote_id", sa.Integer(), sa.ForeignKey("shop_quotes.id"), nullable=True),
        sa.Column("work_center_id", sa.Integer(), sa.ForeignKey("work_centers.id"), nullable=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id"), nullable=True),
        sa.Column("depends_on_id", sa.Integer(), sa.ForeignKey("operations.id"), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("operation_name", sa.String(255), nullable=False),
        sa.Column("work_center_category", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("estimated_setup_min", sa.Float(), nullable=False, server_default="30"),
        sa.Column("estimated_run_min", sa.Float(), nullable=False, server_default="60"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("actual_setup_min", sa.Float(), nullable=True),
        sa.Column("actual_run_min", sa.Float(), nullable=True),
        sa.Column("quantity_complete", sa.Integer(), nullable=True),
        sa.Column("quantity_scrapped", sa.Integer(), nullable=True),
        sa.Column("scrap_reason", sa.Text(), nullable=True),
        sa.Column("setup_started_at", sa.DateTime(), nullable=True),
        sa.Column("run_started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operations_id", "operations", ["id"])
    op.create_index("ix_operations_user_id", "operations", ["user_id"])
    op.create_index("ix_operations_order_ref", "operations", ["order_ref"])
    op.create_index("ix_operations_work_center_id", "operations", ["work_center_id"])
    op.create_index("ix_operations_status", "operations", ["status"])
    op.create_index("ix_operations_work_center_category", "operations", ["work_center_category"])

    op.create_table(
        "shop_floor_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("operations.id"), nullable=True),
        sa.Column("work_center_id", sa.Integer(), sa.ForeignKey("work_centers.id"), nullable=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id"), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shop_floor_events_id", "shop_floor_events", ["id"])
    op.create_index("ix_shop_floor_events_operation_id", "shop_floor_events", ["operation_id"])
    op.create_index("ix_shop_floor_events_work_center_id", "shop_floor_events", ["work_center_id"])
    op.create_index("ix_shop_floor_events_event_type", "shop_floor_events", ["event_type"])
    op.create_index("ix_shop_floor_events_occurred_at", "shop_floor_events", ["occurred_at"])

    op.create_table(
        "non_conformance_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("operations.id"), nullable=True),
        sa.Column("order_ref", sa.String(50), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="minor"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ncr_id", "non_conformance_reports", ["id"])
    op.create_index("ix_ncr_status", "non_conformance_reports", ["status"])

    op.create_table(
        "first_article_inspections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_ref", sa.String(50), nullable=True),
        sa.Column("part_name", sa.String(255), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("revision", sa.String(20), nullable=True),
        sa.Column("inspector", sa.String(255), nullable=True),
        sa.Column("result", sa.String(20), nullable=False, server_default="pass"),
        sa.Column("measurements_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fai_id", "first_article_inspections", ["id"])
    op.create_index("ix_fai_order_ref", "first_article_inspections", ["order_ref"])

    # -------------------------------------------------------------------------
    # Views
    # -------------------------------------------------------------------------
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE VIEW IF NOT EXISTS v_work_center_utilization AS
        SELECT
            wc.id                               AS work_center_id,
            wc.name                             AS work_center_name,
            wc.category,
            wc.status,
            COUNT(CASE WHEN o.status = 'in_progress' THEN 1 END) AS active_operations,
            COUNT(CASE WHEN o.status IN ('pending','queued') THEN 1 END) AS queued_operations,
            SUM(CASE WHEN o.status = 'complete' THEN COALESCE(o.actual_run_min, o.estimated_run_min) ELSE 0 END)
                AS total_run_min_completed,
            SUM(CASE WHEN o.status = 'complete' THEN o.estimated_run_min ELSE 0 END)
                AS total_est_min_completed,
            wc.hourly_rate
        FROM work_centers wc
        LEFT JOIN operations o ON o.work_center_id = wc.id
        GROUP BY wc.id, wc.name, wc.category, wc.status, wc.hourly_rate
    """))

    conn.execute(sa.text("""
        CREATE VIEW IF NOT EXISTS v_job_progress AS
        SELECT
            COALESCE(o.order_ref, CAST(sq.id AS TEXT))  AS job_ref,
            sq.customer_name,
            sq.part_name,
            COUNT(o.id)                                 AS total_operations,
            COUNT(CASE WHEN o.status = 'complete' THEN 1 END) AS completed_operations,
            COUNT(CASE WHEN o.status = 'in_progress' THEN 1 END) AS active_operations,
            COUNT(CASE WHEN o.status IN ('pending','queued') THEN 1 END) AS pending_operations,
            SUM(o.estimated_run_min)                    AS total_est_run_min,
            SUM(COALESCE(o.actual_run_min, 0))          AS total_actual_run_min,
            MIN(o.created_at)                           AS started_at,
            MAX(o.completed_at)                         AS last_completed_at
        FROM operations o
        LEFT JOIN shop_quotes sq ON sq.id = o.shop_quote_id
        GROUP BY COALESCE(o.order_ref, CAST(sq.id AS TEXT)), sq.customer_name, sq.part_name
    """))

    conn.execute(sa.text("""
        CREATE VIEW IF NOT EXISTS v_estimation_accuracy AS
        SELECT
            o.work_center_category,
            o.operation_name,
            COUNT(*)                                    AS sample_count,
            AVG(o.estimated_setup_min)                  AS avg_est_setup_min,
            AVG(o.actual_setup_min)                     AS avg_actual_setup_min,
            AVG(o.estimated_run_min)                    AS avg_est_run_min,
            AVG(o.actual_run_min)                       AS avg_actual_run_min,
            AVG(o.actual_setup_min - o.estimated_setup_min)  AS setup_bias_min,
            AVG(o.actual_run_min   - o.estimated_run_min)    AS run_bias_min,
            -- positive = underestimating (actual > estimate), negative = overestimating
            CASE
                WHEN AVG(o.estimated_run_min) > 0
                THEN ROUND((AVG(o.actual_run_min) - AVG(o.estimated_run_min))
                           / AVG(o.estimated_run_min) * 100, 1)
                ELSE NULL
            END AS run_bias_pct
        FROM operations o
        WHERE o.status = 'complete'
          AND o.actual_setup_min IS NOT NULL
          AND o.actual_run_min IS NOT NULL
        GROUP BY o.work_center_category, o.operation_name
        HAVING COUNT(*) >= 3
    """))

    # -------------------------------------------------------------------------
    # Trigger: auto-log status changes to shop_floor_events
    # SQLite syntax; Postgres would use a PL/pgSQL function + CREATE TRIGGER
    # -------------------------------------------------------------------------
    conn.execute(sa.text("""
        CREATE TRIGGER IF NOT EXISTS trg_operations_status_change
        AFTER UPDATE OF status ON operations
        WHEN OLD.status != NEW.status
        BEGIN
            INSERT INTO shop_floor_events
                (user_id, operation_id, work_center_id, event_type, payload_json, occurred_at)
            VALUES (
                NEW.user_id,
                NEW.id,
                NEW.work_center_id,
                'status_change',
                json_object(
                    'from', OLD.status,
                    'to',   NEW.status,
                    'operation_name', NEW.operation_name
                ),
                datetime('now')
            );
        END
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TRIGGER IF EXISTS trg_operations_status_change"))
    conn.execute(sa.text("DROP VIEW IF EXISTS v_estimation_accuracy"))
    conn.execute(sa.text("DROP VIEW IF EXISTS v_job_progress"))
    conn.execute(sa.text("DROP VIEW IF EXISTS v_work_center_utilization"))

    op.drop_table("first_article_inspections")
    op.drop_table("non_conformance_reports")
    op.drop_table("shop_floor_events")
    op.drop_table("operations")
    op.drop_table("shop_quotes")
    op.drop_table("routing_steps")
    op.drop_table("routing_templates")
    op.drop_table("operators")
    op.drop_table("work_centers")
