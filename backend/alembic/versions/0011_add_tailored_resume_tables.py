"""add tailored resume tables

Revision ID: d3f5b8a92e17
Revises: c8d4a1f7e236
Create Date: 2026-09-21 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3f5b8a92e17"
down_revision: str | None = "c8d4a1f7e236"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tailored_resumes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_posting_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("base", sa.JSON(), nullable=True),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("dropped", sa.JSON(), nullable=False),
        sa.Column("profile_stamp", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_posting_id"),
    )
    op.create_index(
        op.f("ix_tailored_resumes_user_id"), "tailored_resumes", ["user_id"], unique=False
    )

    op.create_table(
        "resume_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("change_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("target_label", sa.String(length=255), nullable=False),
        sa.Column("before_text", sa.Text(), nullable=False),
        sa.Column("after_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("addresses", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["tailored_resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resume_changes_resume_id"), "resume_changes", ["resume_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_resume_changes_resume_id"), table_name="resume_changes")
    op.drop_table("resume_changes")
    op.drop_index(op.f("ix_tailored_resumes_user_id"), table_name="tailored_resumes")
    op.drop_table("tailored_resumes")
