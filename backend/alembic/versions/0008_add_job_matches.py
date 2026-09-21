"""add job matches table

Revision ID: a91d6e2c7b40
Revises: c53a3b45eaea
Create Date: 2026-09-21 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a91d6e2c7b40'
down_revision: str | None = 'c53a3b45eaea'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('job_matches',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('job_posting_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('score_percent', sa.Integer(), nullable=True),
    sa.Column('assessed_weight', sa.Integer(), nullable=False),
    sa.Column('low_confidence', sa.Boolean(), nullable=False),
    sa.Column('components', sa.JSON(), nullable=False),
    sa.Column('uncertainties', sa.JSON(), nullable=False),
    sa.Column('requirements', sa.JSON(), nullable=True),
    sa.Column('deal_breaker_check', sa.String(length=20), nullable=False),
    sa.Column('deal_breaker_hits', sa.JSON(), nullable=False),
    sa.Column('profile_stamp', sa.String(length=64), nullable=True),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_posting_id'], ['job_postings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_posting_id')
    )


def downgrade() -> None:
    op.drop_table('job_matches')
