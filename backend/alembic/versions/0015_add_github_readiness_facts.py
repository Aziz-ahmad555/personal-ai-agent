"""add github readiness facts

Revision ID: b7d2f9a13c64
Revises: a4c8e1f27b53
Create Date: 2026-09-22 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d2f9a13c64"
down_revision: str | None = "a4c8e1f27b53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "github_repos",
        sa.Column("tree_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("github_repos", sa.Column("notable_paths", sa.JSON(), nullable=True))
    op.add_column("github_repos", sa.Column("readme", sa.JSON(), nullable=True))
    op.add_column("github_connections", sa.Column("profile_facts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("github_connections", "profile_facts")
    op.drop_column("github_repos", "readme")
    op.drop_column("github_repos", "notable_paths")
    op.drop_column("github_repos", "tree_truncated")
