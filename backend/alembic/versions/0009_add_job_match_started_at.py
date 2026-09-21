"""add started_at to job matches

Revision ID: b27e9f41c8d3
Revises: a91d6e2c7b40
Create Date: 2026-09-21 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b27e9f41c8d3'
down_revision: str | None = 'a91d6e2c7b40'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('job_matches', sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))


def downgrade() -> None:
    op.drop_column('job_matches', 'started_at')
