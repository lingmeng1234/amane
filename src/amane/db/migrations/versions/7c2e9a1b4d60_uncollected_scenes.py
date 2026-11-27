"""persist manually collected ThePornDB scenes

Revision ID: 7c2e9a1b4d60
Revises: f28a0c1d9e31
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c2e9a1b4d60"
down_revision: str | None = "f28a0c1d9e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uncollected_scenes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theporndb_uuid", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("studio", sa.String(), nullable=False),
        sa.Column("performers", sa.JSON(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("theporndb_uuid", name="uq_uncollected_scenes_theporndb_uuid"),
    )
    op.create_index("ix_uncollected_scenes_theporndb_uuid", "uncollected_scenes", ["theporndb_uuid"])
    op.create_index("ix_uncollected_scenes_date", "uncollected_scenes", ["date"])
    op.create_index("ix_uncollected_scenes_studio", "uncollected_scenes", ["studio"])


def downgrade() -> None:
    op.drop_index("ix_uncollected_scenes_studio", table_name="uncollected_scenes")
    op.drop_index("ix_uncollected_scenes_date", table_name="uncollected_scenes")
    op.drop_index("ix_uncollected_scenes_theporndb_uuid", table_name="uncollected_scenes")
    op.drop_table("uncollected_scenes")
