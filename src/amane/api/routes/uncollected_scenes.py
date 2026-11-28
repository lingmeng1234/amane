from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...enums import ActorGender
from ..deps import RepoDep

router = APIRouter(prefix="/uncollected-scenes", tags=["uncollected-scenes"])

SceneGender = Literal[
    "female",
    "intersex",
    "male",
    "non_binary",
    "transgender_female",
    "transgender_male",
    "unknown",
]


class ScenePerformerInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    official_gender: SceneGender | None = None


class UncollectedSceneCreateRequest(BaseModel):
    theporndb_uuid: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=1000)
    date: str = Field(default="", max_length=40)
    studio: str = Field(default="", max_length=200)
    performers: list[ScenePerformerInput] = Field(default_factory=list, max_length=100)
    image_url: str | None = Field(default=None, max_length=2000)


class UncollectedScenePerformerResponse(BaseModel):
    name: str
    gender: SceneGender
    actor_id: int | None = None


class UncollectedSceneResponse(BaseModel):
    id: int
    theporndb_uuid: str
    title: str
    date: str
    studio: str
    performers: list[UncollectedScenePerformerResponse]
    image_url: str | None
    created_at: str


class UncollectedSceneListResponse(BaseModel):
    items: list[UncollectedSceneResponse]
    total: int
    page: int
    per_page: int


class UncollectedSceneAddResponse(BaseModel):
    added: bool
    already_collected: bool
    theporndb_uuid: str


class UncollectedSceneRefreshResponse(BaseModel):
    deleted: int


@router.get("/facets", include_in_schema=False)
def _female_performer_facets(
    names: list[str],
    local_actor_by_name: dict[str, tuple[int, ActorGender]],
) -> list[str]:
    """筛选项只展示本地档案确认为女性或跨性别女性的演员."""
    return sorted(
        {
            name
            for name in names
            if (profile := local_actor_by_name.get(name)) is not None
            and profile[1] in {ActorGender.FEMALE, ActorGender.TRANSGENDER_FEMALE}
        },
        key=str.casefold,
    )


@router.get("/facets", include_in_schema=False)
async def uncollected_scene_facets(repo: RepoDep) -> dict[str, list[str]]:
    performers, studios = await repo.list_uncollected_scene_facets()
    local_actor_by_name = await repo.get_actor_profiles_by_names_or_aliases(performers) if performers else {}
    return {"performers": _female_performer_facets(performers, local_actor_by_name), "studios": studios}


@router.get("/status", include_in_schema=False)
async def uncollected_scene_status(
    repo: RepoDep,
    actor_name: Annotated[str, Query(min_length=1, max_length=200)],
) -> dict[str, bool]:
    return {"exists": await repo.has_uncollected_scene_actor_build(actor_name)}


def _gender(value: object) -> SceneGender:
    if isinstance(value, str) and value in {
        "female",
        "intersex",
        "male",
        "non_binary",
        "transgender_female",
        "transgender_male",
        "unknown",
    }:
        return value  # type: ignore[return-value]
    return "unknown"


async def _scene_response(
    item: Any,
    local_actor_by_name: dict[str, tuple[int, ActorGender]],
) -> UncollectedSceneResponse:
    assert item.id is not None
    performers: list[UncollectedScenePerformerResponse] = []
    for performer in item.performers or []:
        if not isinstance(performer, dict):
            continue
        name = performer.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        profile = local_actor_by_name.get(name)
        # 本地演员档案是性别显示的唯一依据; 未建档时显示未知性别.
        gender = _gender(profile[1].value if profile is not None else ActorGender.UNKNOWN.value)
        performers.append(
            UncollectedScenePerformerResponse(
                name=name,
                gender=gender,
                actor_id=profile[0] if profile is not None else None,
            )
        )
    return UncollectedSceneResponse(
        id=item.id,
        theporndb_uuid=item.theporndb_uuid,
        title=item.title,
        date=item.date,
        studio=item.studio,
        performers=performers,
        image_url=item.image_url,
        created_at=item.created_at.isoformat(),
    )


@router.get("", include_in_schema=False)
async def list_uncollected_scenes(
    repo: RepoDep,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 30,
    query: Annotated[str | None, Query(max_length=200)] = None,
    performer: Annotated[str | None, Query(max_length=200)] = None,
    studio: Annotated[str | None, Query(max_length=200)] = None,
) -> UncollectedSceneListResponse:
    items, total = await repo.list_uncollected_scenes(
        offset=(page - 1) * per_page,
        limit=per_page,
        query=query,
        performer=performer,
        studio=studio,
    )
    # 每次请求都按当前演员展示名/别名重新解析档案; 不把 actor_id 固化到未收录记录.
    names = list(
        dict.fromkeys(
            performer["name"]
            for item in items
            for performer in (item.performers or [])
            if isinstance(performer, dict)
            and isinstance(performer.get("name"), str)
            and performer.get("name", "").strip()
        )
    )
    local_actor_by_name = await repo.get_actor_profiles_by_names_or_aliases(names) if names else {}
    responses = [await _scene_response(item, local_actor_by_name) for item in items]
    return UncollectedSceneListResponse(
        items=responses,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("", include_in_schema=False)
async def add_uncollected_scene(
    req: UncollectedSceneCreateRequest,
    repo: RepoDep,
) -> UncollectedSceneAddResponse:
    uuid = req.theporndb_uuid.strip()
    if not uuid:
        raise HTTPException(422, detail="ThePornDB UUID 不能为空")
    performers = [
        {
            "name": item.name.strip(),
            "official_gender": item.official_gender,
        }
        for item in req.performers
        if item.name.strip()
    ]
    item, added = await repo.add_uncollected_scene(
        theporndb_uuid=uuid,
        title=req.title.strip(),
        date=req.date.strip(),
        studio=req.studio.strip(),
        performers=performers,
        image_url=req.image_url,
    )
    already_collected = item is None
    return UncollectedSceneAddResponse(
        added=added,
        already_collected=already_collected,
        theporndb_uuid=uuid.casefold(),
    )


@router.delete("/{theporndb_uuid}", include_in_schema=False)
async def delete_uncollected_scene(theporndb_uuid: str, repo: RepoDep) -> dict[str, bool]:
    deleted = await repo.delete_uncollected_scene(theporndb_uuid)
    return {"deleted": deleted}


@router.post("/refresh", include_in_schema=False)
async def refresh_uncollected_scenes(repo: RepoDep) -> UncollectedSceneRefreshResponse:
    deleted = await repo.prune_collected_uncollected_scenes()
    return UncollectedSceneRefreshResponse(deleted=deleted)
