"""add career tables

Revision ID: 4c788837eb35
Revises: 5ddf66a149ec
Create Date: 2026-09-20 00:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '4c788837eb35'
down_revision: str | None = '5ddf66a149ec'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('job_postings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('source_channel', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('source_url', sa.String(length=2048), nullable=True),
    sa.Column('company_name', sa.String(length=255), nullable=True),
    sa.Column('company_domain', sa.String(length=255), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('location', sa.String(length=255), nullable=True),
    sa.Column('remote_type', sa.String(length=20), nullable=False),
    sa.Column('salary_min', sa.Integer(), nullable=True),
    sa.Column('salary_max', sa.Integer(), nullable=True),
    sa.Column('salary_currency', sa.String(length=10), nullable=True),
    sa.Column('description_text', sa.Text(), nullable=True),
    sa.Column('description_hash', sa.String(length=64), nullable=True),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('research_source_id', sa.Uuid(), nullable=True),
    sa.Column('raw_payload', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['research_source_id'], ['research_sources.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'source_channel', 'external_id', name='uq_job_postings_user_channel_external'),
    sa.UniqueConstraint('user_id', 'source_url', name='uq_job_postings_user_source_url')
    )
    op.create_index(op.f('ix_job_postings_description_hash'), 'job_postings', ['description_hash'], unique=False)
    op.create_index(op.f('ix_job_postings_user_id'), 'job_postings', ['user_id'], unique=False)

    op.create_table('job_board_feeds',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('board', sa.String(length=20), nullable=False),
    sa.Column('company_slug', sa.String(length=200), nullable=True),
    sa.Column('keyword', sa.String(length=200), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_poll_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'board', 'company_slug', 'keyword', name='uq_job_board_feed_user')
    )
    op.create_index(op.f('ix_job_board_feeds_user_id'), 'job_board_feeds', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_job_board_feeds_user_id'), table_name='job_board_feeds')
    op.drop_table('job_board_feeds')
    op.drop_index(op.f('ix_job_postings_user_id'), table_name='job_postings')
    op.drop_index(op.f('ix_job_postings_description_hash'), table_name='job_postings')
    op.drop_table('job_postings')
