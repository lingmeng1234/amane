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
        result.append({"name": name.strip(), "official_gender": _official_gender(performer)})
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


async def _resolve_exact_performer(client: AsyncClient, token: str, name: str) -> dict[str, str] | None:
    response = await client.get(
        "https://api.theporndb.net/performers",
        params={"q": name, "per_page": 100, "page": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise HTTPException(502, detail="ThePornDB 演员搜索返回了无效响应")
    matches: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        aliases = item.get("aliases")
        exact_names = [item.get("name")]
        if isinstance(aliases, list):
            exact_names.extend(aliases)
        if name in exact_names:
            matches.append(item)
    # 同一官方演员可能同时以展示名和别名命中, 按官方 ID 去重.
    unique: dict[str, dict[str, Any]] = {}
    for item in matches:
        identifier = str(item.get("_id") or item.get("id") or "")
        if identifier:
            unique[identifier] = item
    if not unique:
        return None
    if len(unique) > 1:
        raise HTTPException(422, detail=f"ThePornDB 中存在多个完全匹配的演员：{name}")
    item = next(iter(unique.values()))
    identifier = str(item.get("_id") or item.get("id") or "")
    canonical_name = item.get("name")
    if not identifier or not isinstance(canonical_name, str) or not canonical_name:
        raise HTTPException(502, detail="ThePornDB 演员结果缺少必要身份字段")
    return {identifier: canonical_name}


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
        raise HTTPException(502, detail="ThePornDB 厂牌搜索返回了无效响应")
    matches = [
        item for item in data if isinstance(item, dict) and item.get("name") == name and item.get("id") is not None
    ]
    unique = {int(item["id"]) for item in matches}
    if not unique:
        return None
    if len(unique) > 1:
        raise HTTPException(422, detail=f"ThePornDB 中存在多个完全匹配的厂牌：{name}")
    return next(iter(unique))


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
        raise HTTPException(422, detail="标题、日期、厂牌、演员或 TAG 至少填写一项")

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
            performer_filter, tag_filter, site_filter = await asyncio.gather(
                _resolve_exact_performer(client, token, performer) if performer else _empty_filter(),
                _resolve_exact_tag(client, token, tag) if tag else _empty_filter(),
                _resolve_exact_site(client, token, studio) if studio else _empty_filter(),
            )
            if performer and performer_filter is None:
                return {"items": []}
            if tag and tag_filter is None:
                return {"items": []}
            if studio and site_filter is None:
                return {"items": []}

            searches: list[dict[str, Any]] = []
            if query:
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
                if performer_filter:
                    performer_id, performer_name = next(iter(performer_filter.items()))
                    params["performers[" + performer_id + "]"] = performer_name
                    params["performer_and"] = "true"
                if tag_filter:
                    tag_id, tag_name = next(iter(tag_filter.items()))
                    params["tags[" + tag_id + "]"] = tag_name
                    params["tag_and"] = "true"

            responses = await asyncio.gather(
                *(
                    client.get(
                        "https://api.theporndb.net/scenes",
                        params=params,
                        headers=headers,
                    )
                    for params in searches
                )
            )
            payloads = []
            for response in responses:
                response.raise_for_status()
                payloads.append(response.json())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, detail=f"ThePornDB 搜索请求失败：{exc}") from exc

    scenes_by_id: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise HTTPException(502, detail="ThePornDB 返回了无效响应")
        for scene in payload["data"]:
            if isinstance(scene, dict) and scene.get("id"):
                scenes_by_id.setdefault(str(scene["id"]), scene)

    # 官方明确提供的性别优先; 只有官方缺失时才查询本地演员档案.
    performer_names = list(
        dict.fromkeys(performer["name"] for scene in scenes_by_id.values() for performer in _performer_entries(scene))
    )
    local_gender_by_name = await repo.get_actor_genders_by_names_or_aliases(performer_names) if performer_names else {}

    result: list[dict[str, Any]] = []
    for scene in scenes_by_id.values():
        site = scene.get("site")
        studio_value = scene.get("studio")
        image: Any = scene.get("poster") or scene.get("image")
        if isinstance(image, dict):
            image = image.get("url") or image.get("large")
        background = scene.get("background")
        images = scene.get("images")
        if not image and isinstance(background, dict):
            image = background.get("large") or background.get("url")
        if not image and isinstance(images, list):
            for candidate in images:
                if isinstance(candidate, str) and candidate.strip():
                    image = candidate
                    break
                if isinstance(candidate, dict):
                    image = candidate.get("url") or candidate.get("large") or candidate.get("image")
                    if isinstance(image, dict):
                        image = image.get("url") or image.get("large")
                    if image:
                        break
        if not isinstance(image, str) or not image.strip():
            image = None

        performers: list[dict[str, Any]] = []
        for item in _performer_entries(scene):
            official = item["official_gender"]
            gender = (
                official if official is not None else local_gender_by_name.get(item["name"], ActorGender.UNKNOWN).value
            )
            performers.append(
                {
                    "name": item["name"],
                    "gender": gender,
                    "official_gender": official,
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


async def _empty_filter() -> None:
    return None
