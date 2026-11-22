from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ...config import HotSettings, MediaServerConfig
from ...events import Event, EventType
from ...media_server import MediaServerClient, MediaServerError
from ...parsing import file_phase_from_path
from ..deps import ConfigDep, PluginManagerDep, RepoDep, RuntimeDep

logger = structlog.get_logger()

router = APIRouter(prefix="/config", tags=["config"])


def _masked_settings(settings: HotSettings) -> HotSettings:
    media_server = settings.media_server.model_copy(
        update={"api_key": "**********" if settings.media_server.api_key else None}
    )
    return settings.model_copy(update={"media_server": media_server})


@router.post("/media-server/test")
async def test_media_server_connection(config: MediaServerConfig, current: ConfigDep) -> dict[str, object]:
    """测试 Emby/Jellyfin 连接与 API Key, 不写入配置; 掩码值复用已保存密钥."""
    if config.api_key == "**********":
        config = config.model_copy(update={"api_key": current.hot.media_server.api_key})
    if not config.enabled:
        raise HTTPException(status_code=400, detail="请先填写服务器地址和 API Key")
    try:
        async with MediaServerClient(config) as client:
            persons = await client.list_persons()
    except MediaServerError as exc:
        raise HTTPException(status_code=502, detail=f"媒体服务器连接失败: {exc}") from exc
    return {"success": True, "kind": config.kind, "people_count": len(persons)}


@router.get("")
async def get_config(config: ConfigDep) -> HotSettings:
    # 不把媒体服务器 API Key 明文返回浏览器; 未修改时前端回传掩码会被 update_config 忽略.
    return _masked_settings(config.hot)


@router.patch("")
async def update_config(req: dict[str, Any], config: ConfigDep, repo: RepoDep, runtime: RuntimeDep) -> HotSettings:
    """先用当前会话的插件目录校验新路由和插件配置, 再持久化."""
    changed_sections = list(req.keys())
    logger.info("config update requested", sections=changed_sections)

    try:
        previous_rules = config.hot.scraping.mosaic_rules.model_dump()
        preview = config.preview(req)
        if runtime.plugin_manager is not None:
            runtime.plugin_manager.validate_hot_settings(preview, require_available=False)
        config.update(req)
        next_rules = preview.scraping.mosaic_rules.model_dump()
        if previous_rules != next_rules:
            repo.set_mosaic_rules(next_rules)
            media_files = await repo.list_media_files(limit=None)
            phase_updates = [
                (media.id, file_phase_from_path(media.path, mosaic_rules=next_rules))
                for media in media_files
                if media.id is not None
            ]
            updated_count = await repo.update_media_file_phases(phase_updates)
            logger.info("media file attributes reprojected after mosaic rule change", count=updated_count)
    except (KeyError, ValidationError, ValueError) as e:
        logger.warning("config update rejected", error=str(e), sections=changed_sections)
        raise HTTPException(status_code=422, detail=str(e)) from e

    await runtime.apply_rebuild()
    logger.info("runtime rebuilt after config update", sections=changed_sections)

    await runtime.event_bus.broadcast(Event(type=EventType.LOG, data={"type": "config.updated"}))

    return _masked_settings(config.hot)


@router.get("/schema")
async def get_config_schema(plugin_manager: PluginManagerDep) -> dict:
    return plugin_manager.augment_config_schema(HotSettings.model_json_schema())
