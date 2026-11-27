"""track actors who explicitly initiated uncollected scene building

Revision ID: 8a7d3c2e1f90
Revises: 7c2e9a1b4d60
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a7d3c2e1f90"
down_revision: str | None = "7c2e9a1b4d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uncollected_scene_actor_builds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_name", name="uq_uncollected_scene_actor_builds_actor_name"),
    )
    op.create_index(
        "ix_uncollected_scene_actor_builds_actor_name",
        "uncollected_scene_actor_builds",
        ["actor_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_uncollected_scene_actor_builds_actor_name", table_name="uncollected_scene_actor_builds")
    op.drop_table("uncollected_scene_actor_builds")
