"""add blood type to actor profiles

Revision ID: a74d8c2e1f60
Revises: 8c3f2a1b7d90
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a74d8c2e1f60"
down_revision: str | Sequence[str] | None = "8c3f2a1b7d90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("actors", sa.Column("blood_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("actors", "blood_type")
