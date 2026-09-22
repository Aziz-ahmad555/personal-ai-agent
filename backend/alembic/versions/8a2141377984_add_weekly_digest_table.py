"""add weekly digest table

Revision ID: 8a2141377984
Revises: 01009e17179d
Create Date: 2026-09-22 23:10:51.967655

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '8a2141377984'
down_revision: str | None = '01009e17179d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('weekly_digests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_weekly_digests_user_id'), 'weekly_digests', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_weekly_digests_user_id'), table_name='weekly_digests')
    op.drop_table('weekly_digests')
