from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...mappings.dmm_text_store import DmmTextMappingStore
from ..deps import RuntimeDep

router = APIRouter(prefix="/dmm-mappings", tags=["dmm-mappings"])


class EntryUpdate(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=500)
    original_source: str | None = Field(default=None, max_length=200)


class JSONObjectPairs(list):
    """Preserve duplicate JSON object keys so merge import can quarantine them."""


class BatchDeleteRequest(BaseModel):
    sources: list[str]


class ExceptionUpdate(BaseModel):
    group_id: int
    side: Literal["old", "new"]
    entry: dict | None = None


def store(runtime) -> DmmTextMappingStore:
    return runtime.dmm_text_mappings


@router.get("")
async def list_dmm_mappings(runtime: RuntimeDep, search: str = "", limit: int = 30, offset: int = 0):
    try:
        data = store(runtime).list(search)
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc
    entries = list(data.items())
    page = entries[max(0, offset) : max(0, offset) + max(1, min(limit, 200))]
    return {"items": [{"source": source, "target": target} for source, target in page], "total": len(entries)}


@router.put("")
async def save_dmm_mapping(req: EntryUpdate, runtime: RuntimeDep):
    try:
        store(runtime).save(req.source, req.target, req.original_source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"source": req.source.strip(), "target": req.target.strip()}


@router.delete("/item", status_code=204)
async def delete_dmm_mapping(runtime: RuntimeDep, source: str):
    if not store(runtime).delete(source):
        raise HTTPException(404, "DMM和谐映射不存在")


@router.post("/batch-delete")
async def batch_delete_dmm_mappings(req: BatchDeleteRequest, runtime: RuntimeDep):
    return {"deleted": store(runtime).delete_many(req.sources)}


@router.get("/exceptions")
async def list_dmm_mapping_exceptions(runtime: RuntimeDep):
    return store(runtime).list_conflicts()


@router.put("/exceptions")
async def update_dmm_mapping_exception(req: ExceptionUpdate, runtime: RuntimeDep):
    try:
        return store(runtime).update_conflict(req.group_id, req.side, req.entry)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/exceptions/save")
async def save_dmm_mapping_exception(req: ExceptionUpdate, runtime: RuntimeDep):
    if req.entry is None:
        raise HTTPException(400, "冲突记录不能为空")

    source = req.entry.get("source")
    target = req.entry.get("target")

    if not isinstance(source, str) or not isinstance(target, str):
        raise HTTPException(400, "冲突记录的原文字和修正文字必须是字符串")

    try:
        return store(runtime).save_conflict_entry(req.group_id, req.side, source, target)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/exceptions/clear")
async def clear_dmm_mapping_exceptions(runtime: RuntimeDep):
    store(runtime).clear_conflicts()
    return {"cleared": True}


@router.get("/export")
async def export_dmm_mappings(runtime: RuntimeDep):
    return JSONResponse(
        store(runtime).export_data(),
        headers={"Content-Disposition": 'attachment; filename="dmm_text_map.json"'},
    )


@router.post("/import")
async def import_dmm_mappings(request: Request, runtime: RuntimeDep, mode: Literal["merge", "replace"] = "merge"):
    try:
        raw = await request.body()
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=JSONObjectPairs)
        if not isinstance(data, JSONObjectPairs):
            raise ValueError("JSON 内容必须是以原和谐词为键、修正后文字为值的对象")
        rows = list(data)
        if mode == "replace":
            return {"replaced": store(runtime).replace_rows(rows)}
        return store(runtime).import_merge_rows(rows)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(400, f"JSON 导入失败：{exc}") from exc
