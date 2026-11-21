from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from tests.helpers import alembic_config


@pytest.fixture
def alembic_cfg(tmp_path: Path) -> Config:
    return alembic_config(tmp_path / "v028-indexes.db")


def test_v028_list_resource_indexes_are_created(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    assert url is not None
    engine = create_engine(url)
    expected = {
        "actor_user_tags": {"ix_actor_user_tags_user_tag_id"},
        "metadata_actors": {"ix_metadata_actors_actor_id"},
        "metadata_directors": {"ix_metadata_directors_director_id"},
        "metadata_tags": {"ix_metadata_tags_tag_id"},
        "metadata_user_tags": {"ix_metadata_user_tags_user_tag_id"},
        "metadata": {"ix_metadata_updated_at_id"},
        "resources": {"ix_resources_file_path"},
    }
    with engine.connect() as connection:
        inspector = inspect(connection)
        for table, indexes in expected.items():
            actual = {item["name"] for item in inspector.get_indexes(table)}
            assert indexes <= actual
        metadata_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_metadata_updated_at_id'")
        ).scalar_one()
        assert "updated_at DESC" in metadata_sql
        # SQLite Inspector 无法可靠反射表达式索引, 直接从 sqlite_master 核验.
        expression_indexes = {
            "ix_metadata_western_theporndb_uuid": "lower(theporndb_uuid)",
            "ix_feed_items_list_order": "coalesce(published_at, created_at)",
            "ix_feed_items_state_list_order": "coalesce(published_at, created_at)",
        }
        for name, expression in expression_indexes.items():
            index_sql = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"), {"name": name}
            ).scalar_one()
            assert expression in index_sql
    engine.dispose()
