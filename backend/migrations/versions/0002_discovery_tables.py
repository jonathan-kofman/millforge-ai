"""add customer discovery tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discovery_interviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_name', sa.String(255), nullable=False),
        sa.Column('shop_name', sa.String(255), nullable=False),
        sa.Column('shop_size', sa.String(20), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('date', sa.String(20), nullable=False),
        sa.Column('raw_transcript', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_discovery_interviews_id'), 'discovery_interviews', ['id'], unique=False)

    op.create_table(
        'discovery_insights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interview_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('severity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('quote', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['interview_id'], ['discovery_interviews.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_discovery_insights_id'), 'discovery_insights', ['id'], unique=False)
    op.create_index(op.f('ix_discovery_insights_interview_id'), 'discovery_insights', ['interview_id'], unique=False)

    op.create_table(
        'discovery_patterns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('insight_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('frequency', sa.Float(), nullable=False),
        sa.Column('evidence_quotes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('feature_tag', sa.String(50), nullable=False, server_default='other'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_discovery_patterns_id'), 'discovery_patterns', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_discovery_patterns_id'), table_name='discovery_patterns')
    op.drop_table('discovery_patterns')
    op.drop_index(op.f('ix_discovery_insights_interview_id'), table_name='discovery_insights')
    op.drop_index(op.f('ix_discovery_insights_id'), table_name='discovery_insights')
    op.drop_table('discovery_insights')
    op.drop_index(op.f('ix_discovery_interviews_id'), table_name='discovery_interviews')
    op.drop_table('discovery_interviews')
