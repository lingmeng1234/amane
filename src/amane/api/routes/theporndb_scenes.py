import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from httpx2 import AsyncClient, Timeout
from pydantic import BaseModel, Field

from ...enums import ActorGender, SiteName
from ..deps import RepoDep, RuntimeDep

router = APIRouter(prefix="/theporndb-scenes", tags=["theporndb-scenes"])


class SceneSearchRequest(BaseModel):
    query: str = Field(default="", max_length=200)
    date: str = Field(default="", max_length=40)


class SceneSearchFilterRequest(BaseModel):
    query: str = Field(default="", max_length=200)
    date: str = Field(default="", max_length=40)
    studio: str = Field(default="", max_length=200)
    performer: str = Field(default="", max_length=200)
    tag: str = Field(default="", max_length=200)
    record_actor_name: str = Field(default="", max_length=200)


_PERFORMER_GENDER: dict[str, str] = {
    "FEMALE": "female",
    "INTERSEX": "intersex",
    "MALE": "male",
    "NON BINARY": "non_binary",
    "TRANSGENDER FEMALE": "transgender_female",
    "TRANSGENDER MALE": "transgender_male",
    "UNKNOWN": "unknown",
}


def _official_gender(performer: dict[str, Any]) -> str | None:
    """返回官方明确提供的性别; None 仅表示官方没有提供该字段."""
    extras = performer.get("extras")
    value = extras.get("gender") if isinstance(extras, dict) else None
    if not isinstance(value, str) or not value.strip():
        value = performer.get("gender")
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().upper().replace("_", " ")
    return _PERFORMER_GENDER.get(normalized, "unknown")


def _performer_entries(scene: dict[str, Any]) -> list[dict[str, Any]]:
    raw = scene.get("performers")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        performer = item.get("performer")
        if not isinstance(performer, dict):
            performer = item
        name = performer.get("name") or item.get("as")
        if not isinstance(name, str) or not name.strip():
            continue
        official_gender = _official_gender(performer)
        if official_gender is None and performer is not item:
            # ThePornDB 不同响应形态可能把性别放在外层关联对象.
            official_gender = _official_gender(item)
        result.append({"name": name.strip(), "official_gender": official_gender})
    return result


def _tag_names(scene: dict[str, Any]) -> list[str]:
    raw = scene.get("tags")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return list(dict.fromkeys(names))


def _image_url(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("url", "large", "full", "medium", "small", "image"):
            result = _image_url(value.get(key))
            if result:
                return result
    return None


def _scene_cover_image(scene: dict[str, Any]) -> str | None:
    """优先选择横向正面图/背景图, 竖版 poster 仅在没有横图时兜底."""
    for key in ("image", "background", "back_image", "images", "poster_image", "poster"):
        value = scene.get(key)
        if isinstance(value, list):
            for item in value:
                result = _image_url(item)
                if result:
                    return result
        else:
            result = _image_url(value)
            if result:
                return result
    return None


async def _resolve_exact_tag(client: AsyncClient, token: str, name: str) -> dict[str, str] | None:
    response = await client.get(
        "https://api.theporndb.net/tags",
        params={"q": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise HTTPException(502, detail="ThePornDB TAG 搜索返回了无效响应")
    matches = [item for item in data if isinstance(item, dict) and item.get("name") == name]
    unique: dict[str, dict[str, Any]] = {}
    for item in matches:
        identifier = str(item.get("_id") or item.get("id") or item.get("uuid") or "")
        if identifier:
            unique[identifier] = item
    if not unique:
        return None
    if len(unique) > 1:
        raise HTTPException(422, detail=f"ThePornDB 中存在多个完全匹配的 TAG：{name}")
    identifier = next(iter(unique))
    return {identifier: name}


async def _resolve_exact_site(client: AsyncClient, token: str, name: str) -> int | None:
    response = await client.get(
        "https://api.theporndb.net/sites",
        params={"q": name, "per_page": 100, "page": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise HTTPException(502, detail="ThePornDB 制作商搜索返回了无效响应")
    matches = [
        item for item in data if isinstance(item, dict) and item.get("name") == name and item.get("id") is not None
    ]
    unique = {int(item["id"]) for item in matches}
    if not unique:
        return None
    if len(unique) > 1:
        raise HTTPException(422, detail=f"ThePornDB 中存在多个完全匹配的制作商：{name}")
    return next(iter(unique))


async def _fetch_scene_pages(
    client: AsyncClient,
    params: dict[str, Any],
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    """读取 ThePornDB 场景搜索的全部分页, 不把首屏 50 条误当成完整结果."""
    per_page = 50
    page = 1
    scenes: list[dict[str, Any]] = []
    while True:
        response = await client.get(
            "https://api.theporndb.net/scenes",
            params={**params, "per_page": per_page, "page": page},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise HTTPException(502, detail="ThePornDB 返回了无效响应")
        batch = [item for item in payload["data"] if isinstance(item, dict)]
        scenes.extend(batch)

        meta = payload.get("meta")
        pagination = meta.get("pagination") if isinstance(meta, dict) else None
        last_page = meta.get("last_page") if isinstance(meta, dict) else None
        if not isinstance(last_page, int) and isinstance(pagination, dict):
            last_page = pagination.get("total_pages") or pagination.get("last_page")
        if isinstance(last_page, int) and last_page > 0:
            if page >= last_page:
                break
        elif len(batch) < per_page:
            break
        page += 1
    return scenes


async def _search_scenes(
    req: SceneSearchFilterRequest,
    runtime: RuntimeDep,
    repo: RepoDep,
) -> dict[str, list[dict[str, Any]]]:
    query = req.query.strip()
    date = req.date.strip()
    studio = req.studio.strip()
    performer = req.performer.strip()
    tag = req.tag.strip()
    if not any((query, date, studio, performer, tag)):
        raise HTTPException(422, detail="标题、日期、制作商、演员或 TAG 至少填写一项")

    cfg = runtime.config.hot.scraping.site_config.get(str(SiteName.THEPORNDB))
    token = cfg.api_token if cfg else None
    if not token:
        raise HTTPException(503, detail="未配置 ThePornDB API Token")

    normalized_date = date.replace(".", "-").replace("/", "-") if date else ""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with AsyncClient(
            proxy=runtime.config.hot.network.proxy,
            timeout=Timeout(30),
            follow_redirects=True,
        ) as client:
            tag_filter, site_filter = await asyncio.gather(
                _resolve_exact_tag(client, token, tag) if tag else _empty_filter(),
                _resolve_exact_site(client, token, studio) if studio else _empty_filter(),
            )
            if tag and tag_filter is None:
                return {"items": []}
            if studio and site_filter is None:
                return {"items": []}

            searches: list[dict[str, Any]] = []
            if performer:
                # 直接把演员展示名作为 ThePornDB 自由检索词; 不查询演员映射或 ID.
                searches.append({"q": performer, "per_page": 50, "page": 1, "orderBy": "most_relevant"})
            elif query:
                searches.extend(
                    (
                        {"title": query, "per_page": 50, "page": 1, "orderBy": "most_relevant"},
                        {"site": query, "per_page": 50, "page": 1, "orderBy": "most_relevant"},
                    )
                )
            else:
                searches.append({"per_page": 50, "page": 1, "orderBy": "recently_released"})
            for params in searches:
                if normalized_date:
                    params["date"] = normalized_date
                if site_filter is not None:
                    params["site_id"] = site_filter
                if tag_filter:
                    tag_id, tag_name = next(iter(tag_filter.items()))
                    params["tags[" + tag_id + "]"] = tag_name
                    params["tag_and"] = "true"

            search_pages = await asyncio.gather(*(_fetch_scene_pages(client, params, headers) for params in searches))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"ThePornDB 搜索请求失败：{exc}") from exc

    scenes_by_id: dict[str, dict[str, Any]] = {}
    for batch in search_pages:
        for scene in batch:
            if scene.get("id"):
                scenes_by_id.setdefault(str(scene["id"]), scene)

    # 演员性别以本地档案为准; 尚未建档的演员显示未知性别.
    performer_names = list(
        dict.fromkeys(performer["name"] for scene in scenes_by_id.values() for performer in _performer_entries(scene))
    )
    local_gender_by_name = await repo.get_actor_genders_by_names_or_aliases(performer_names) if performer_names else {}

    result: list[dict[str, Any]] = []
    for scene in scenes_by_id.values():
        site = scene.get("site")
        studio_value = scene.get("studio")
        image = _scene_cover_image(scene)

        performers: list[dict[str, Any]] = []
        for item in _performer_entries(scene):
            gender = local_gender_by_name.get(item["name"], ActorGender.UNKNOWN).value
            performers.append(
                {
                    "name": item["name"],
                    "gender": gender,
                    "official_gender": item.get("official_gender"),
                }
            )

        result.append(
            {
                "id": str(scene["id"]),
                "title": scene.get("title") or "",
                "date": scene.get("date") or "",
                "duration": scene.get("duration"),
                "studio": (
                    site.get("name", "")
                    if isinstance(site, dict)
                    else studio_value.get("name", "")
                    if isinstance(studio_value, dict)
                    else site
                    if isinstance(site, str)
                    else ""
                ),
                "performers": performers,
                "tags": _tag_names(scene),
                "image": image,
            }
        )
    return {"items": result}


@router.post("/search")
async def search_scenes(
    req: SceneSearchRequest,
    runtime: RuntimeDep,
    repo: RepoDep,
) -> dict[str, list[dict[str, Any]]]:
    return await _search_scenes(
        SceneSearchFilterRequest(query=req.query, date=req.date),
        runtime,
        repo,
    )


@router.post("/search-filtered", include_in_schema=False)
async def search_scenes_filtered(
    req: SceneSearchFilterRequest,
    runtime: RuntimeDep,
    repo: RepoDep,
) -> dict[str, list[dict[str, Any]]]:
    return await _search_scenes(req, runtime, repo)


@router.post("/build-uncollected", include_in_schema=False)
async def build_uncollected_scenes(
    req: SceneSearchFilterRequest,
    runtime: RuntimeDep,
    repo: RepoDep,
) -> dict[str, int]:
    """按检索条件搜索全部分页并一次性幂等写入未收录名单."""
    result = await _search_scenes(req, runtime, repo)
    scenes = [
        {
            "theporndb_uuid": scene["id"],
            "title": scene["title"],
            "date": scene["date"],
            "studio": scene["studio"],
            "performers": [
                {
                    "name": performer["name"],
                    "official_gender": performer.get("official_gender"),
                }
                for performer in scene["performers"]
            ],
            "image_url": scene["image"],
        }
        for scene in result["items"]
    ]
    added, already_listed, already_collected = await repo.add_uncollected_scenes(
        scenes,
        actor_name=req.record_actor_name or None,
    )
    return {
        "matched": len(scenes),
        "added": added,
        "already_in_list": already_listed,
        "already_collected": already_collected,
    }


async def _empty_filter() -> None:
    return None
