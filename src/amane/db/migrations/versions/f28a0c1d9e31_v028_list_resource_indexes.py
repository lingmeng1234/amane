"""v0.28.0 list and resource indexes

Revision ID: f28a0c1d9e31
Revises: d4e8f1a2b6c0, 4b8d2e7c1a90, 56fe451426ef, b8c4d2e19a70, d2e6a8c91f30, f2a3b4c5d6e7
Create Date: 2026-11-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f28a0c1d9e31"
down_revision: str | Sequence[str] | None = (
    "d4e8f1a2b6c0",
    "4b8d2e7c1a90",
    "56fe451426ef",
    "b8c4d2e19a70",
    "d2e6a8c91f30",
    "f2a3b4c5d6e7",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 关联表复合主键以 metadata_id 开头, 增加反向索引以支持按分类筛选和删除.
    op.create_index("ix_actor_user_tags_user_tag_id", "actor_user_tags", ["user_tag_id", "actor_id"])
    op.create_index("ix_metadata_actors_actor_id", "metadata_actors", ["actor_id", "metadata_id"])
    op.create_index("ix_metadata_directors_director_id", "metadata_directors", ["director_id", "metadata_id"])
    op.create_index("ix_metadata_tags_tag_id", "metadata_tags", ["tag_id", "metadata_id"])
    op.create_index("ix_metadata_user_tags_user_tag_id", "metadata_user_tags", ["user_tag_id", "metadata_id"])
    # 表达式 / 带方向的索引: SQLite autogenerate 无法可靠反射, 手工创建.
    op.execute(sa.text("CREATE INDEX ix_metadata_updated_at_id ON metadata (updated_at DESC, id)"))
    op.execute(
        sa.text(
            "CREATE INDEX ix_feed_items_state_list_order ON feed_items "
            "(ignored_at, coalesce(published_at, created_at), id)"
        )
    )
    op.create_index("ix_resources_file_path", "resources", ["file_path"])


def downgrade() -> None:
    op.drop_index("ix_resources_file_path", table_name="resources")
    op.drop_index("ix_feed_items_state_list_order", table_name="feed_items")
    op.drop_index("ix_metadata_updated_at_id", table_name="metadata")
    op.drop_index("ix_metadata_user_tags_user_tag_id", table_name="metadata_user_tags")
    op.drop_index("ix_metadata_tags_tag_id", table_name="metadata_tags")
    op.drop_index("ix_metadata_directors_director_id", table_name="metadata_directors")
    op.drop_index("ix_metadata_actors_actor_id", table_name="metadata_actors")
    op.drop_index("ix_actor_user_tags_user_tag_id", table_name="actor_user_tags")
