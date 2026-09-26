"""add career verification tables

Revision ID: c53a3b45eaea
Revises: 4c788837eb35
Create Date: 2026-09-20 00:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c53a3b45eaea"
down_revision: str | None = "4c788837eb35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employer_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employer_key", sa.String(length=300), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("company_domain", sa.String(length=255), nullable=True),
        sa.Column("research_query_id", sa.Uuid(), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["research_query_id"], ["research_queries.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employer_key"),
    )
    op.create_index(
        op.f("ix_employer_verifications_employer_key"),
        "employer_verifications",
        ["employer_key"],
        unique=True,
    )

    op.create_table(
        "job_fraud_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_posting_id", sa.Uuid(), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("employer_verification_id", sa.Uuid(), nullable=True),
        sa.Column(
            "assessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employer_verification_id"], ["employer_verifications.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_posting_id"),
    )


def downgrade() -> None:
    op.drop_table("job_fraud_assessments")
    op.drop_index(
        op.f("ix_employer_verifications_employer_key"), table_name="employer_verifications"
    )
    op.drop_table("employer_verifications")
