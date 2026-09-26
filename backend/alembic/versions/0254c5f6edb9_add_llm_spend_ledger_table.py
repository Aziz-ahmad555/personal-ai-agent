"""add llm spend ledger table

Revision ID: 0254c5f6edb9
Revises: 8a2141377984
Create Date: 2026-09-26 17:06:49.220075

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0254c5f6edb9'
down_revision: str | None = '8a2141377984'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Note: autogenerate also proposed dropping employer_verifications'
    # employer_key unique constraint — pre-existing drift unrelated to this migration
    # (not something this change touches), deliberately left out here.
    op.create_table('llm_spend_ledger',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('tokens_in', sa.Integer(), nullable=False),
    sa.Column('tokens_out', sa.Integer(), nullable=False),
    sa.Column('estimated_cost_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_spend_ledger_created_at'), 'llm_spend_ledger', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_llm_spend_ledger_created_at'), table_name='llm_spend_ledger')
    op.drop_table('llm_spend_ledger')
