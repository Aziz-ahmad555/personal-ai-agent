"""add practice session tables

Revision ID: 01009e17179d
Revises: d9f4a2c86e17
Create Date: 2026-09-22 22:04:01.467107

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "01009e17179d"
down_revision: str | None = "d9f4a2c86e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_posting_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("profile_stamp", sa.String(length=64), nullable=True),
        sa.Column("dropped", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_practice_sessions_job_posting_id"),
        "practice_sessions",
        ["job_posting_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_practice_sessions_user_id"), "practice_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "practice_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("ref_type", sa.String(length=20), nullable=False),
        sa.Column("ref_name", sa.String(length=255), nullable=False),
        sa.Column("ref_excerpt", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verdict", sa.String(length=20), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["practice_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_practice_questions_session_id"), "practice_questions", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_practice_questions_session_id"), table_name="practice_questions")
    op.drop_table("practice_questions")
    op.drop_index(op.f("ix_practice_sessions_user_id"), table_name="practice_sessions")
    op.drop_index(op.f("ix_practice_sessions_job_posting_id"), table_name="practice_sessions")
    op.drop_table("practice_sessions")
