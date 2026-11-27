from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, or_
from sqlmodel import col, select

from ..models import Metadata, UncollectedScene, UncollectedSceneActorBuild
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

    async def add_uncollected_scenes(
        self,
        scenes: list[dict[str, Any]],
        *,
        actor_name: str | None = None,
    ) -> tuple[int, int, int]:
        """批量幂等登记; 返回 (新增, 已在名单, 已在片库)."""
        normalized: dict[str, dict[str, Any]] = {}
        for scene in scenes:
            uuid = str(scene.get("theporndb_uuid") or "").strip().casefold()
            if uuid:
                normalized.setdefault(uuid, {**scene, "theporndb_uuid": uuid})
        if not normalized:
            return 0, 0, 0

        uuids = list(normalized)
        async with self._session() as session:
            await acquire_write_lock(session)
            collected_rows = await session.exec(
                select(func.lower(col(Metadata.theporndb_uuid))).where(
                    func.lower(col(Metadata.theporndb_uuid)).in_(uuids)
                )
            )
            collected = {str(value) for value in collected_rows.all() if value}
            existing_rows = await session.exec(
                select(func.lower(col(UncollectedScene.theporndb_uuid))).where(
                    func.lower(col(UncollectedScene.theporndb_uuid)).in_(uuids)
                )
            )
            existing = {str(value) for value in existing_rows.all() if value}

            added = 0
            already_listed = 0
            already_collected = 0
            for uuid, scene in normalized.items():
                if uuid in collected:
                    already_collected += 1
                elif uuid in existing:
                    already_listed += 1
                else:
                    session.add(
                        UncollectedScene(
                            theporndb_uuid=uuid,
                            title=str(scene.get("title") or ""),
                            date=str(scene.get("date") or ""),
                            studio=str(scene.get("studio") or ""),
                            performers=scene.get("performers") or [],
                            image_url=scene.get("image_url"),
                        )
                    )
                    added += 1
            if actor_name and actor_name.strip():
                actor_name = actor_name.strip()
                actor_record = (
                    await session.exec(
                        select(UncollectedSceneActorBuild).where(
                            col(UncollectedSceneActorBuild.actor_name) == actor_name
                        )
                    )
                ).first()
                if actor_record is None:
                    session.add(UncollectedSceneActorBuild(actor_name=actor_name))
            await session.commit()
            return added, already_listed, already_collected

    async def has_uncollected_scene_actor_build(self, actor_name: str) -> bool:
        normalized_name = actor_name.strip()
        if not normalized_name:
            return False
        async with self._session() as session:
            result = await session.exec(
                select(UncollectedSceneActorBuild.id)
                .where(col(UncollectedSceneActorBuild.actor_name) == normalized_name)
                .limit(1)
            )
            return result.first() is not None

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
        if studio:
            conditions.append(func.lower(col(UncollectedScene.studio)) == studio.strip().casefold())
        async with self._session() as session:
            stmt = select(UncollectedScene)
            if conditions:
                stmt = stmt.where(*conditions)
            stmt = stmt.order_by(col(UncollectedScene.created_at).desc(), col(UncollectedScene.id).asc())
            if performer:
                # JSON 演员字段在 SQLite/PostgreSQL 的存储表达不同; 在候选名单中按原始名称精确匹配.
                candidates = list((await session.exec(stmt)).all())
                matched = [
                    item
                    for item in candidates
                    if any(
                        isinstance(entry, dict)
                        and isinstance(entry.get("name"), str)
                        and entry["name"].casefold() == performer.strip().casefold()
                        for entry in (item.performers or [])
                    )
                ]
                return matched[offset : offset + limit], len(matched)

            count_stmt = select(func.count()).select_from(UncollectedScene)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = int((await session.exec(count_stmt)).one())
            items = list((await session.exec(stmt.offset(offset).limit(limit))).all())
            return items, total

    async def list_uncollected_scene_facets(self) -> tuple[list[str], list[str]]:
        """返回未收录名单中实际出现的演员展示名与制作商原名."""
        async with self._session() as session:
            rows = (await session.exec(select(UncollectedScene))).all()
        studios: dict[str, str] = {}
        performers: dict[str, str] = {}
        for item in rows:
            studio = item.studio
            entries = item.performers
            if isinstance(studio, str) and studio.strip():
                studios.setdefault(studio.casefold(), studio.strip())
            for entry in entries or []:
                if isinstance(entry, dict):
                    name = entry.get("name")
                    if isinstance(name, str) and name.strip():
                        performers.setdefault(name.casefold(), name.strip())
        return sorted(performers.values(), key=str.casefold), sorted(studios.values(), key=str.casefold)

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
