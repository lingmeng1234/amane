import json
from typing import Annotated, Literal

from aiolimiter import AsyncLimiter
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from httpx2 import AsyncClient, Timeout
from pydantic import BaseModel, Field, StrictBool
from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart

from ...db.models import FacetKind, FacetSortField, SortOrder
from ...llm.model import build_model
from ...tags.mapping import MappingKind
from ..deps import RepoDep, RuntimeDep

router = APIRouter(prefix="/tag-mappings", tags=["tag-mappings"])


class MappingUpdate(BaseModel):
    original: str = Field(min_length=1, max_length=300)
    translation: str | None = Field(default=None, max_length=300)
    type: MappingKind = "tag"


@router.get("")
async def list_mappings(
    runtime: RuntimeDep,
    repo: RepoDep,
    status: Literal["all", "pending", "mapped", "archived"] = "pending",
    language: Literal["all", "ja", "en", "zh", "other"] = "all",
    frequency: Literal["all", "high"] = "all",
    search: str = "",
    mapping_type: Annotated[MappingKind, Query(alias="type")] = "tag",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    # 四类词条统一进入同一映射表; 各自从对应分类实体同步原始名称与影片引用数.
    if runtime.tag_mappings.needs_seed(mapping_type):
        facet_kind = {
            "tag": FacetKind.TAG,
            "maker": FacetKind.STUDIO,
            "publisher": FacetKind.PUBLISHER,
            "series": FacetKind.SERIES,
        }[mapping_type]
        offset_seed = 0
        seeded: list[tuple[str, int]] = []
        while True:
            facets, total_facets = await repo.list_facets(
                facet_kind,
                offset=offset_seed,
                limit=1000,
                sort_by=FacetSortField.NAME,
                order=SortOrder.ASC,
            )
            seeded.extend((item.name, item.count) for item in facets)
            offset_seed += len(facets)
            if not facets or offset_seed >= total_facets:
                break
        if mapping_type == "tag":
            runtime.tag_mappings.seed(seeded)
        else:
            runtime.tag_mappings.seed_facets(mapping_type, seeded)
    items, total = runtime.tag_mappings.list(
        kind=mapping_type,
        status=status,
        language=language,
        frequency=frequency,
        search=search,
        offset=offset,
        limit=limit,
    )
    return {
        "items": [item.__dict__ for item in items],
        "total": total,
        "stats": runtime.tag_mappings.counts(mapping_type),
    }


@router.get("/state")
async def get_mapping_state(runtime: RuntimeDep):
    return {"enabled": runtime.tag_mappings.enabled}


class MappingStateUpdate(BaseModel):
    enabled: StrictBool


@router.put("/state")
async def update_mapping_state(req: MappingStateUpdate, runtime: RuntimeDep):
    return {"enabled": runtime.tag_mappings.set_enabled(req.enabled)}


@router.put("")
async def save_mapping(req: MappingUpdate, runtime: RuntimeDep):
    try:
        item = runtime.tag_mappings.upsert(req.original, req.translation, req.type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return item.__dict__


class MappingSelection(BaseModel):
    originals: list[str] = Field(min_length=1, max_length=200)
    type: MappingKind = "tag"


@router.put("/{original:path}/archive")
async def archive_mapping(
    original: str,
    runtime: RuntimeDep,
    mapping_type: Annotated[MappingKind, Query(alias="type")] = "tag",
):
    if not runtime.tag_mappings.archive(original, mapping_type):
        raise HTTPException(409, "词条不存在或已有中文译名，不能归档")
    return {"archived": True}


@router.put("/{original:path}/restore")
async def restore_mapping(
    original: str,
    runtime: RuntimeDep,
    mapping_type: Annotated[MappingKind, Query(alias="type")] = "tag",
):
    if not runtime.tag_mappings.restore(original, mapping_type):
        raise HTTPException(404, "归档词条不存在")
    return {"archived": False}


@router.post("/archive")
async def archive_mappings(req: MappingSelection, runtime: RuntimeDep):
    archived, skipped = runtime.tag_mappings.archive_many(req.originals, req.type)
    return {"archived": archived, "skipped": skipped}


@router.post("/restore")
async def restore_mappings(req: MappingSelection, runtime: RuntimeDep):
    return {"restored": runtime.tag_mappings.restore_many(req.originals, req.type)}


@router.get("/export")
async def export_mappings(runtime: RuntimeDep):
    return JSONResponse(
        runtime.tag_mappings.export(),
        headers={"Content-Disposition": 'attachment; filename="chinese_mappings.json"'},
    )


@router.post("/import")
async def import_mappings(payload: dict, runtime: RuntimeDep):
    try:
        count = runtime.tag_mappings.import_data(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"imported": count}


class SuggestRequest(BaseModel):
    originals: list[str] = Field(min_length=1, max_length=30)
    type: MappingKind = "tag"


@router.post("/suggest")
async def suggest_mappings(req: SuggestRequest, runtime: RuntimeDep):
    """只返回候选译名，不写入词典；人工确认仍由 PUT 接口完成."""
    llm = runtime.config.hot.llm
    if not llm.api_key or not llm.model:
        raise HTTPException(503, "请先在现有 LLM 设置中配置 API Key 和模型")
    originals = list(dict.fromkeys(value.strip() for value in req.originals if value.strip()))
    if not originals:
        raise HTTPException(400, "没有有效的原始名称")
    subject = {"tag": "影片标签", "maker": "制作商", "publisher": "发行商", "series": "系列"}[req.type]
    prompt = (
        f"将以下{subject}逐条翻译为简体中文。保留原有含义，不要合并，不要解释。"
        "只返回 JSON 对象，键为原文，值为中文译名。\n"
        + json.dumps(originals, ensure_ascii=False)
    )
    try:
        # 复用现有 LLM 的 API 类型、地址、密钥、模型、代理和速率配置；不依赖标题/剧情翻译开关.
        async with AsyncClient(
            proxy=runtime.config.hot.network.proxy, timeout=Timeout(45), follow_redirects=True
        ) as http_client:
            model = build_model(
                llm.api_type, base_url=llm.base_url, api_key=llm.api_key, model=llm.model, http_client=http_client
            )
            async with AsyncLimiter(llm.rate_limit, time_period=1):
                result = await model_request(
                    model,
                    [
                        ModelRequest(
                            parts=[
                                SystemPromptPart(content="你是影视中文映射助手。输出必须是合法 JSON 对象。"),
                                UserPromptPart(content=prompt),
                            ]
                        )
                    ],
                )
        data = json.loads(result.text or "{}")
        if not isinstance(data, dict):
            raise ValueError("模型返回格式不是 JSON 对象")
    except Exception as exc:
        raise HTTPException(502, f"LLM 建议生成失败：{exc}") from exc
    return {
        "suggestions": {
            key: str(value).strip() for key, value in data.items() if key in originals and str(value).strip()
        }
    }
