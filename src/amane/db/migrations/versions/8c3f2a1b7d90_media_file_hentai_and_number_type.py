"""persist independent hentai and number-derived file type

Revision ID: 8c3f2a1b7d90
Revises: f28a0c1d9e31
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from amane.parsing import parse_file_info

revision: str = "8c3f2a1b7d90"
down_revision: str | Sequence[str] | None = "f28a0c1d9e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_files",
        sa.Column(
            "number_content_type",
            sa.Enum(
                "CENSORED",
                "UNCENSORED",
                "CHINESE",
                "WESTERN",
                "FC2",
                "AMATEUR",
                "HENTAI",
                name="contenttype",
            ),
            nullable=False,
            server_default="WESTERN",
        ),
    )
    op.add_column(
        "media_files",
        sa.Column("hentai", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_media_files_number_content_type", "media_files", ["number_content_type"])
    op.create_index("ix_media_files_hentai", "media_files", ["hentai"])

    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, path FROM media_files")).all()
    for row_id, path in rows:
        info = parse_file_info(path)
        conn.execute(
            text(
                "UPDATE media_files SET mosaic = :mosaic, number_content_type = :number_content_type, "
                "hentai = :hentai, has_subtitle_in_name = :has_subtitle, definition = :definition, "
                "has_external_subtitle = 0 WHERE id = :id"
            ),
            {
                "mosaic": info.mosaic.name if info.mosaic is not None else None,
                "number_content_type": info.number_content_type.name,
                "hentai": info.hentai,
                "has_subtitle": info.has_subtitle_in_name,
                "definition": info.definition,
                "id": row_id,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_media_files_hentai", table_name="media_files")
    op.drop_index("ix_media_files_number_content_type", table_name="media_files")
    op.drop_column("media_files", "hentai")
    op.drop_column("media_files", "number_content_type")
