from __future__ import annotations

from sqlalchemy import String, cast, delete, func, or_
from sqlmodel import col, select

from ..models import Metadata, UncollectedScene
from .base import RepositoryMixinBase, acquire_write_lock


class UncollectedScenesRepoMixin(RepositoryMixinBase):
    async def add_uncollected_scene(
        self,
        *,
        theporndb_uuid: str,
        title: str,
        date: str,
        studio: str,
        performers: list[dict[str, str | None]],
        image_url: str | None,
    ) -> tuple[UncollectedScene | None, bool]:
        """按 UUID 幂等登记; 已存在时保留原记录."""
        normalized_uuid = theporndb_uuid.strip().casefold()
        async with self._session() as session:
            await acquire_write_lock(session)
            collected = (
                await session.exec(
                    select(Metadata.id).where(func.lower(col(Metadata.theporndb_uuid)) == normalized_uuid).limit(1)
                )
            ).first()
            if collected is not None:
                await session.commit()
                return None, False
            existing = (
                await session.exec(
                    select(UncollectedScene).where(func.lower(col(UncollectedScene.theporndb_uuid)) == normalized_uuid)
                )
            ).first()
            if existing is not None:
                await session.commit()
                return existing, False
            item = UncollectedScene(
                theporndb_uuid=normalized_uuid,
                title=title,
                date=date,
                studio=studio,
                performers=performers,
                image_url=image_url,
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item, True

    async def list_uncollected_scenes(
        self,
        *,
        offset: int,
        limit: int,
        query: str | None = None,
        performer: str | None = None,
        studio: str | None = None,
    ) -> tuple[list[UncollectedScene], int]:
        conditions = []
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    col(UncollectedScene.title).ilike(pattern),
                    col(UncollectedScene.theporndb_uuid).ilike(pattern),
                )
            )
        if performer:
            conditions.append(cast(col(UncollectedScene.performers), String).ilike(f"%{performer.strip()}%"))
        if studio:
            conditions.append(col(UncollectedScene.studio).ilike(f"%{studio.strip()}%"))
        async with self._session() as session:
            count_stmt = select(func.count()).select_from(UncollectedScene)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = int((await session.exec(count_stmt)).one())
            stmt = select(UncollectedScene)
            if conditions:
                stmt = stmt.where(*conditions)
            stmt = (
                stmt.order_by(col(UncollectedScene.created_at).desc(), col(UncollectedScene.id).asc())
                .offset(offset)
                .limit(limit)
            )
            items = list((await session.exec(stmt)).all())
            return items, total

    async def delete_uncollected_scene(self, theporndb_uuid: str) -> bool:
        normalized_uuid = theporndb_uuid.strip().casefold()
        async with self._session() as session:
            item = (
                await session.exec(
                    select(UncollectedScene).where(func.lower(col(UncollectedScene.theporndb_uuid)) == normalized_uuid)
                )
            ).first()
            if item is None:
                return False
            await session.delete(item)
            await session.commit()
            return True

    async def prune_collected_uncollected_scenes(self) -> int:
        """只清理名单记录; 绝不修改 Metadata 或片库文件."""
        async with self._session() as session:
            await acquire_write_lock(session)
            collected_uuids = select(func.lower(col(Metadata.theporndb_uuid))).where(
                col(Metadata.theporndb_uuid).is_not(None)
            )
            statement = delete(UncollectedScene).where(
                func.lower(col(UncollectedScene.theporndb_uuid)).in_(collected_uuids)
            )
            result = await session.exec(statement)
            await session.commit()
            return int(result.rowcount or 0)
