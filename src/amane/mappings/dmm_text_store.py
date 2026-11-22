"""Persistent DMM text-harmony correction mappings."""

from __future__ import annotations

import builtins
import json
import os
import re
import tempfile
import threading
from itertools import pairwise
from pathlib import Path
from typing import Any


class DmmTextMappingStore:
    """Map an exact censored phrase to its corrected text.

    The source phrase is unique; corrected text may be shared by any number of
    source phrases. Reads are intentionally refreshed from disk so a running
    DMM crawler sees edits made in the management UI without being recreated.
    """

    def __init__(self, data_dir: Path) -> None:
        self.directory = data_dir / "mappings"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / "dmm_text_map.json"
        self.exceptions_file = self.directory / "dmm_text_map_exceptions.json"
        self._lock = threading.RLock()
        if not self.file.exists():
            self._atomic_write(self.file, {})
        if not self.exceptions_file.exists():
            self._atomic_write(self.exceptions_file, [])

    @staticmethod
    def _atomic_write(path: Path, data: Any) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _validate(source: str, target: Any) -> str:
        source = source.strip()
        if not source:
            raise ValueError("原和谐词不能为空")
        if len(source) > 200:
            raise ValueError("原和谐词不能超过 200 个字符")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"{source}: 修正后文字不能为空")
        target = target.strip()
        if len(target) > 500:
            raise ValueError(f"{source}: 修正后文字不能超过 500 个字符")
        return target

    def list(self, search: str = "") -> dict[str, str]:
        with self._lock:
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"DMM和谐映射文件读取失败：{exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("DMM和谐映射文件必须是 JSON 对象")
            normalized: dict[str, str] = {}
            for raw_source, target in data.items():
                source = str(raw_source).strip()
                if source in normalized:
                    raise ValueError(f"原和谐词重复：{source}")
                normalized[source] = self._validate(source, target)
            needle = search.strip()
            if not needle:
                return normalized
            # Exact match on either side. Do not use substring/fuzzy matching.
            return {source: target for source, target in normalized.items() if source == needle or target == needle}

    def save(self, source: str, target: str, original_source: str | None = None) -> None:
        target = self._validate(source, target)
        source = source.strip()
        with self._lock:
            data = self.list()
            if original_source is not None:
                original_source = original_source.strip()
                if original_source not in data:
                    raise ValueError(f"待编辑的原和谐词不存在：{original_source}")
            if source in data and source != original_source:
                raise ValueError(f"原和谐词已存在：{source}")
            if original_source and original_source != source:
                data.pop(original_source, None)
            data[source] = target
            self._atomic_write(self.file, dict(sorted(data.items())))

    def delete(self, source: str) -> bool:
        with self._lock:
            data = self.list()
            if source not in data:
                return False
            data.pop(source)
            self._atomic_write(self.file, dict(sorted(data.items())))
            return True

    def delete_many(self, sources: builtins.list[str]) -> int:
        with self._lock:
            data = self.list()
            count = 0
            for source in dict.fromkeys(sources):
                if source in data:
                    data.pop(source)
                    count += 1
            if count:
                self._atomic_write(self.file, dict(sorted(data.items())))
            return count

    def list_conflicts(self) -> builtins.list[dict[str, Any]]:
        with self._lock:
            try:
                items = json.loads(self.exceptions_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"DMM和谐映射冲突文件读取失败：{exc}") from exc
            if not isinstance(items, list):
                raise ValueError("DMM和谐映射冲突文件必须是 JSON 数组")
            return items

    def _write_conflicts(self, items: builtins.list[dict[str, Any]]) -> None:
        normalized = []
        for index, item in enumerate(items, 1):
            row = dict(item)
            row["group_id"] = index
            normalized.append(row)
        self._atomic_write(self.exceptions_file, normalized)

    def add_conflicts(self, items: builtins.list[dict[str, Any]]) -> builtins.list[dict[str, Any]]:
        with self._lock:
            current = self.list_conflicts()
            current.extend(items)
            self._write_conflicts(current)
            return self.list_conflicts()

    def update_conflict(self, group_id: int, side: str, entry: dict[str, str] | None) -> builtins.list[dict[str, Any]]:
        if side not in {"old", "new"}:
            raise ValueError("冲突记录侧别无效")
        with self._lock:
            items = self.list_conflicts()
            if group_id < 1 or group_id > len(items):
                raise ValueError("冲突组不存在")
            if entry is None:
                items[group_id - 1].pop(side, None)
                if not items[group_id - 1].get("old") and not items[group_id - 1].get("new"):
                    items.pop(group_id - 1)
            else:
                source = str(entry.get("source", ""))
                target = self._validate(source, entry.get("target"))
                items[group_id - 1][side] = {"source": source.strip(), "target": target}
            self._write_conflicts(items)
            return self.list_conflicts()

    def save_conflict_entry(self, group_id: int, side: str, source: str, target: str) -> builtins.list[dict[str, Any]]:
        if side not in {"old", "new"}:
            raise ValueError("冲突记录侧别无效")
        with self._lock:
            items = self.list_conflicts()
            if group_id < 1 or group_id > len(items):
                raise ValueError("冲突组不存在")
            self.save(source, target)
            return self.update_conflict(group_id, side, None)

    def clear_conflicts(self) -> None:
        with self._lock:
            self._write_conflicts([])

    def import_merge(self, incoming: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(incoming, dict):
            raise ValueError("导入内容必须是以原和谐词为键的 JSON 对象")
        return self.import_merge_rows(list(incoming.items()))

    def import_merge_rows(self, rows: builtins.list[tuple[Any, Any]]) -> dict[str, Any]:
        grouped: dict[str, builtins.list[str]] = {}
        for raw_source, raw_target in rows:
            source = str(raw_source).strip()
            target = self._validate(source, raw_target)
            grouped.setdefault(source, []).append(target)
        with self._lock:
            current = self.list()
            added: builtins.list[str] = []
            unchanged: builtins.list[str] = []
            conflicts: builtins.list[dict[str, Any]] = []
            for source, targets in grouped.items():
                distinct_targets = list(dict.fromkeys(targets))
                existing_target = current.get(source)
                values = list(
                    dict.fromkeys(([existing_target] if existing_target is not None else []) + distinct_targets)
                )
                if len(values) == 1:
                    if existing_target is None:
                        current[source] = values[0]
                        added.append(source)
                    else:
                        unchanged.append(source)
                    continue
                current.pop(source, None)
                for old_target, new_target in pairwise(values):
                    conflicts.append(
                        {
                            "reason": "source",
                            "old": {"source": source, "target": old_target},
                            "new": {"source": source, "target": new_target},
                        }
                    )
            self._atomic_write(self.file, dict(sorted(current.items())))
            if conflicts:
                self.add_conflicts(conflicts)
            return {"added": added, "unchanged": unchanged, "conflicts": conflicts}

    def replace(self, incoming: dict[str, Any]) -> int:
        if not isinstance(incoming, dict):
            raise ValueError("导入内容必须是以原和谐词为键的 JSON 对象")
        return self.replace_rows(list(incoming.items()))

    def replace_rows(self, rows: builtins.list[tuple[Any, Any]]) -> int:
        normalized: dict[str, str] = {}
        for raw_source, target in rows:
            source = str(raw_source).strip()
            if source in normalized:
                raise ValueError(f"原和谐词重复：{source}")
            normalized[source] = self._validate(source, target)
        with self._lock:
            self._atomic_write(self.file, dict(sorted(normalized.items())))
        return len(normalized)

    def export_data(self) -> dict[str, str]:
        return dict(sorted(self.list().items()))

    @staticmethod
    def _apply(value: str | None, mappings: dict[str, str]) -> str | None:
        if not value or not mappings:
            return value
        # One-pass replacement prevents a replacement result from being fed into
        # another rule. Longer source phrases win when rules overlap.
        sources = sorted(mappings, key=lambda item: (-len(item), item))
        pattern = re.compile("|".join(re.escape(source) for source in sources))
        return pattern.sub(lambda match: mappings[match.group(0)], value)

    def apply_text(self, value: str | None) -> str | None:
        return self._apply(value, self.list())

    def apply_metadata(self, metadata: Any) -> None:
        mappings = self.list()
        metadata.title = self._apply(metadata.title, mappings)
        metadata.plot = self._apply(metadata.plot, mappings)
        metadata.series = self._apply(metadata.series, mappings)
