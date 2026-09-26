"""drop redundant employer_verifications unique constraint

Revision ID: 2820bed632e0
Revises: 0254c5f6edb9
Create Date: 2026-09-26 23:21:56.698446

The original migration (0007) created both a table-level UniqueConstraint on
employer_key AND a separate unique index — the model only ever wanted one
(unique=True + index=True on the column renders as a single unique index).
The constraint was pure redundancy: same guarantee, one extra catalog object,
and the reason `alembic check` reported drift against a freshly-migrated
database. ix_employer_verifications_employer_key (kept) still enforces
uniqueness on its own.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2820bed632e0"
down_revision: str | None = "0254c5f6edb9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("employer_verifications_employer_key_key"), "employer_verifications", type_="unique"
    )


def downgrade() -> None:
    op.create_unique_constraint(
        op.f("employer_verifications_employer_key_key"), "employer_verifications", ["employer_key"]
    )
