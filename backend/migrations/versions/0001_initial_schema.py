"""initial schema: users, orders, inspections, suppliers, inventory, and more

Revision ID: 0001
Revises:
Create Date: 2026-03-24 22:22:06.441849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('company', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # Create orders table
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.String(50), nullable=False),
        sa.Column('material', sa.String(50), nullable=False),
        sa.Column('dimensions', sa.String(100), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('complexity', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('due_date', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_orders_order_id'), 'orders', ['order_id'], unique=True)
    op.create_index(op.f('ix_orders_id'), 'orders', ['id'], unique=False)

    # Create inspection_results table
    op.create_table(
        'inspection_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_record_id', sa.Integer(), nullable=True),
        sa.Column('order_id_str', sa.String(50), nullable=True),
        sa.Column('image_url', sa.String(2048), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('defects_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('recommendation', sa.Text(), nullable=False),
        sa.Column('inspector_version', sa.String(50), nullable=False, server_default='mock-v0.1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_record_id'], ['orders.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inspection_results_id'), 'inspection_results', ['id'], unique=False)

    # Create schedule_runs table
    op.create_table(
        'schedule_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('algorithm', sa.String(20), nullable=False),
        sa.Column('order_ids_json', sa.Text(), nullable=False),
        sa.Column('summary_json', sa.Text(), nullable=False),
        sa.Column('on_time_rate', sa.Float(), nullable=False),
        sa.Column('makespan_hours', sa.Float(), nullable=False),
        sa.Column('schedule_json', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_schedule_runs_id'), 'schedule_runs', ['id'], unique=False)

    # Create shop_configs table
    op.create_table(
        'shop_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('shop_name', sa.String(255), nullable=True),
        sa.Column('machine_count', sa.Integer(), nullable=True),
        sa.Column('materials_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('setup_times_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('baseline_otd', sa.Float(), nullable=True),
        sa.Column('scheduling_method', sa.String(50), nullable=True),
        sa.Column('weekly_order_volume', sa.Integer(), nullable=True),
        sa.Column('wizard_step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_shop_configs_user_id'), 'shop_configs', ['user_id'], unique=True)

    # Create contact_submissions table
    op.create_table(
        'contact_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('company', sa.String(255), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('pilot_interest', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create machine_state_logs table
    op.create_table(
        'machine_state_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('machine_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.String(100), nullable=True),
        sa.Column('from_state', sa.String(20), nullable=False),
        sa.Column('to_state', sa.String(20), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_machine_state_logs_machine_id'), 'machine_state_logs', ['machine_id'], unique=False)

    # Create job_feedback table
    op.create_table(
        'job_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical_id', sa.String(200), nullable=False),
        sa.Column('order_id', sa.String(50), nullable=False),
        sa.Column('material', sa.String(50), nullable=False),
        sa.Column('machine_id', sa.Integer(), nullable=False),
        sa.Column('predicted_setup_minutes', sa.Float(), nullable=False),
        sa.Column('actual_setup_minutes', sa.Float(), nullable=False),
        sa.Column('predicted_processing_minutes', sa.Float(), nullable=False),
        sa.Column('actual_processing_minutes', sa.Float(), nullable=False),
        sa.Column('data_provenance', sa.String(30), nullable=False, server_default='operator_logged'),
        sa.Column('logged_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_id')
    )
    op.create_index(op.f('ix_job_feedback_canonical_id'), 'job_feedback', ['canonical_id'], unique=True)
    op.create_index(op.f('ix_job_feedback_order_id'), 'job_feedback', ['order_id'], unique=False)

    # Create suppliers table
    op.create_table(
        'suppliers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('city', sa.String(100), nullable=False),
        sa.Column('state', sa.String(50), nullable=False),
        sa.Column('country', sa.String(50), nullable=False, server_default='US'),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lng', sa.Float(), nullable=True),
        sa.Column('materials', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('categories', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('website', sa.String(500), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('data_source', sa.String(50), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_suppliers_id'), 'suppliers', ['id'], unique=False)

    # Create inventory_stock table
    op.create_table(
        'inventory_stock',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('material', sa.String(50), nullable=False),
        sa.Column('quantity_kg', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('material')
    )
    op.create_index(op.f('ix_inventory_stock_material'), 'inventory_stock', ['material'], unique=True)


def downgrade() -> None:
    # Drop all tables in reverse order of dependencies
    op.drop_index(op.f('ix_inventory_stock_material'), table_name='inventory_stock')
    op.drop_table('inventory_stock')
    op.drop_index(op.f('ix_suppliers_id'), table_name='suppliers')
    op.drop_table('suppliers')
    op.drop_index(op.f('ix_job_feedback_order_id'), table_name='job_feedback')
    op.drop_index(op.f('ix_job_feedback_canonical_id'), table_name='job_feedback')
    op.drop_table('job_feedback')
    op.drop_index(op.f('ix_machine_state_logs_machine_id'), table_name='machine_state_logs')
    op.drop_table('machine_state_logs')
    op.drop_table('contact_submissions')
    op.drop_index(op.f('ix_shop_configs_user_id'), table_name='shop_configs')
    op.drop_table('shop_configs')
    op.drop_index(op.f('ix_schedule_runs_id'), table_name='schedule_runs')
    op.drop_table('schedule_runs')
    op.drop_index(op.f('ix_inspection_results_id'), table_name='inspection_results')
    op.drop_table('inspection_results')
    op.drop_index(op.f('ix_orders_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_order_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
