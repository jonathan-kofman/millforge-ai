"""add jobs, machines, and qc_results tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('stage', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('source', sa.String(30), nullable=False, server_default='manual'),
        sa.Column('material', sa.String(50), nullable=True),
        sa.Column('required_machine_type', sa.String(100), nullable=True),
        sa.Column('estimated_duration_minutes', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('cam_metadata', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_jobs_id'), 'jobs', ['id'], unique=False)

    op.create_table(
        'machines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('machine_type', sa.String(100), nullable=False),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_machines_id'), 'machines', ['id'], unique=False)

    op.create_table(
        'qc_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('defects_found_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('confidence_scores_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('image_path', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_qc_results_id'), 'qc_results', ['id'], unique=False)
    op.create_index(op.f('ix_qc_results_job_id'), 'qc_results', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_qc_results_job_id'), table_name='qc_results')
    op.drop_index(op.f('ix_qc_results_id'), table_name='qc_results')
    op.drop_table('qc_results')
    op.drop_index(op.f('ix_machines_id'), table_name='machines')
    op.drop_table('machines')
    op.drop_index(op.f('ix_jobs_id'), table_name='jobs')
    op.drop_table('jobs')
