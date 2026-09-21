"""add application tracker tables

Revision ID: c8d4a1f7e236
Revises: b27e9f41c8d3
Create Date: 2026-09-21 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c8d4a1f7e236'
down_revision: str | None = 'b27e9f41c8d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('applications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_posting_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('applied_on', sa.Date(), nullable=True),
    sa.Column('next_action_text', sa.String(length=255), nullable=True),
    sa.Column('next_action_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_posting_id'], ['job_postings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_posting_id')
    )
    op.create_index(op.f('ix_applications_user_id'), 'applications', ['user_id'], unique=False)

    op.create_table('application_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=20), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=True),
    sa.Column('occurred_on', sa.Date(), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_application_events_application_id'), 'application_events', ['application_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_application_events_application_id'), table_name='application_events')
    op.drop_table('application_events')
    op.drop_index(op.f('ix_applications_user_id'), table_name='applications')
    op.drop_table('applications')
