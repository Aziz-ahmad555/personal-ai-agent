"""add calendar sync tables

Revision ID: d9f4a2c86e17
Revises: c8e3f6a29d51
Create Date: 2026-09-22 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'd9f4a2c86e17'
down_revision: str | None = 'c8e3f6a29d51'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('calendar_connections', sa.Column('sync_token', sa.Text(), nullable=True))
    op.add_column('calendar_connections', sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('calendar_sync_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('connection_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('events_seen', sa.Integer(), nullable=False),
    sa.Column('events_stored', sa.Integer(), nullable=False),
    sa.Column('warnings', sa.JSON(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['connection_id'], ['calendar_connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calendar_sync_runs_connection_id'), 'calendar_sync_runs', ['connection_id'], unique=False)

    op.create_table('calendar_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('connection_id', sa.Uuid(), nullable=False),
    sa.Column('google_event_id', sa.String(length=200), nullable=False),
    sa.Column('html_link', sa.String(length=500), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_all_day', sa.Boolean(), nullable=False),
    sa.Column('organizer_email', sa.String(length=255), nullable=True),
    sa.Column('attendees', sa.JSON(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('match_reason', sa.Text(), nullable=True),
    sa.Column('user_confirmed', sa.Boolean(), nullable=False),
    sa.Column('application_id', sa.Uuid(), nullable=True),
    sa.Column('application_match_reason', sa.Text(), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['calendar_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('connection_id', 'google_event_id', name='uq_calendar_event')
    )
    op.create_index(op.f('ix_calendar_events_connection_id'), 'calendar_events', ['connection_id'], unique=False)


def downgrade() -> None:
    op.drop_table('calendar_events')
    op.drop_table('calendar_sync_runs')
    op.drop_column('calendar_connections', 'last_synced_at')
    op.drop_column('calendar_connections', 'sync_token')
