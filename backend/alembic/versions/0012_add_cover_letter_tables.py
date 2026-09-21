"""add cover letter tables

Revision ID: e6a1c9d47b28
Revises: d3f5b8a92e17
Create Date: 2026-09-21 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e6a1c9d47b28'
down_revision: str | None = 'd3f5b8a92e17'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('cover_letters',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('job_posting_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('base', sa.JSON(), nullable=True),
    sa.Column('requirements', sa.JSON(), nullable=False),
    sa.Column('gaps', sa.JSON(), nullable=False),
    sa.Column('dropped', sa.JSON(), nullable=False),
    sa.Column('profile_stamp', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_posting_id'], ['job_postings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_posting_id')
    )
    op.create_index(op.f('ix_cover_letters_user_id'), 'cover_letters', ['user_id'], unique=False)

    op.create_table('cover_letter_paragraphs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('letter_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('sentences', sa.JSON(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('edited_text', sa.Text(), nullable=True),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['letter_id'], ['cover_letters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cover_letter_paragraphs_letter_id'), 'cover_letter_paragraphs', ['letter_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cover_letter_paragraphs_letter_id'), table_name='cover_letter_paragraphs')
    op.drop_table('cover_letter_paragraphs')
    op.drop_index(op.f('ix_cover_letters_user_id'), table_name='cover_letters')
    op.drop_table('cover_letters')
