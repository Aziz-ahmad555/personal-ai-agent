"""add github sync tables

Revision ID: a4c8e1f27b53
Revises: f2b7d5c18a39
Create Date: 2026-09-22 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c8e1f27b53"
down_revision: str | None = "f2b7d5c18a39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_repos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("full_name", sa.String(length=300), nullable=False),
        sa.Column("html_url", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_fork", sa.Boolean(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("primary_language", sa.String(length=100), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("forks", sa.Integer(), nullable=False),
        sa.Column("license_spdx", sa.String(length=100), nullable=True),
        sa.Column("homepage", sa.String(length=500), nullable=True),
        sa.Column("default_branch", sa.String(length=200), nullable=True),
        sa.Column("created_at_gh", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details_fetched", sa.Boolean(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("root_files", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("authored_commits", sa.Integer(), nullable=True),
        sa.Column("first_commit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_commit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["github_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "github_repo_id", name="uq_github_repo"),
    )
    op.create_index(
        op.f("ix_github_repos_connection_id"), "github_repos", ["connection_id"], unique=False
    )

    op.create_table(
        "github_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("repos_seen", sa.Integer(), nullable=False),
        sa.Column("repos_detailed", sa.Integer(), nullable=False),
        sa.Column("requests_made", sa.Integer(), nullable=False),
        sa.Column("activity", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("skipped", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["github_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_github_sync_runs_connection_id"),
        "github_sync_runs",
        ["connection_id"],
        unique=False,
    )

    op.create_table(
        "github_skill_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("contributions", sa.JSON(), nullable=False),
        sa.Column("attribution", sa.String(length=20), nullable=False),
        sa.Column("existing_skill_name", sa.String(length=120), nullable=True),
        sa.Column("existing_level", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skill_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["github_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_version_id"], ["skill_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "skill_name", "fingerprint", name="uq_github_proposal"
        ),
    )
    op.create_index(
        op.f("ix_github_skill_proposals_connection_id"),
        "github_skill_proposals",
        ["connection_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("github_skill_proposals")
    op.drop_table("github_sync_runs")
    op.drop_table("github_repos")
