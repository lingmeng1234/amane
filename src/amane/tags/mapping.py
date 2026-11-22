"""持久化的原始标签→中文标签映射。词典放在 Amane 数据目录，不随源码升级丢失。"""

import builtins
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

LanguageCode = Literal["ja", "en", "zh", "other"]


def detect_language(value: str) -> LanguageCode:
    if re.search(r"[\u3040-\u30ff]", value):
        return "ja"
    if re.search(r"[A-Za-z]", value):
        return "en"
    if re.search(r"[\u4e00-\u9fff]", value):
        # 纯汉字词条在日文/中文之间可能有歧义；仅凭字符无法可靠判断。
        # 只有包含常见简体字线索时才归为中文，其余放入“其他/未知”。
        simplified_hints = set(
            "这为与专业东丝两严丧个丰临丽举义乌乐习书买乱争云亚产亲亿仅从仓仪们价众优会伟传伤伦体余侠侣侥侦侧侨俭债倾偿儿党兰关兴养兽内冈册写军农冲决况冻净准凉减凤凭击刘则刚创删剂剑剧劝办务动励劳势区医华协单卖卫却厅历压厌县参双发变叙叠叶号叹吗听员呜响哑哗唤喷团园围国图圆场坏块坚坛坝坟垫墙声壳处备复头夹夺奋奖妆妇妈娇孙学宁宝实宠审宪宫宽宾对寻导寿将尔尘尝层岁岗岛岭峡币帅师帐带帮干并广庄庆库应废开异弃张弯弹强归当录忆忧怀总恋恶恼悦悬惊惧惨惯戏战户扑执扩扫扬扰抚抢护报担拟拢拣拥拦拨挠挡挣挤挥损捡换据掷揽搅携摄摆摇摊敌数斗断无旧时旷显晒晓暂术朴机杀杂权条来杨极构枪枫柜标栈栋栏树样桥档检楼欢欧残毁毕气汇汉汤沟没沪泪泷泸泻泼泽洁洒浇浊测济浑浓涛涝涟涡润涨涩渊渍渐渔湾湿溃溅滚滞满滤滥滨滩灭灯灵灾灿炉点炼烂烟烦烧热爱爷牵犹独狭狮狱猎猪猫献环现电画畅疗疯瘫皱盐监盖矿码砖础确碍祸离种积称稳穷窍竞笔筛筹签简篮类粮紧纠纤约级纪纯纱纲纳纵纷纸纹纽线练组细织终经绑绒结绕绘给络绝统绢绣继绩绪续绿缀缓编缘缝缠罗罚罢职联聪肃肠肤肾肿胀胆胜脏脑脚脱脸舰舱艰艳艺节药萝萧蓝虑虽虾蚀蚁蛮蝇补衬袜袭装裤见观规觅视览觉计订认讨让训议讯记讲论设访诀证评识诉诊词译试诗诚话诞询该详语误诱说请读课谁调谅谈谋谎谢谣贝负贡财责贤败账货质贩贪贫购贮贯贱贴贵贷贸费贺贼资赃赎赏赔赖赛赞赠赵赶趋跃践辉辑输辖辞辩边辽达迁过运还这进远违连选递遗邮邻郑钉针钓钙钝钞钟钢钥钦钧钩钮钱钳钻铁铃铅铜铝银铺链销锁锅锋锐错锡锚锤锦键锯镇镜长门闪闭问闯闲间闷闸闹闻阀阅队阳阴阵阶际陆陈险随隐难雾静顶项顺须顾顿颂预领频颗题颜额风飞饥饭饮饰饱饲饶饺饼饿馆馈马驭驮驯驰驱驳驴驶驻驼驾骂骄验骑骗骚骤鱼鲜鸟鸡鸣鸭鹅麦黄齐齿龙龟"
        )
        if any(char in simplified_hints for char in value):
            return "zh"
        return "other"
    return "other"


MappingKind = Literal["tag", "maker", "publisher", "series"]
MAPPING_KINDS: tuple[MappingKind, ...] = ("tag", "maker", "publisher", "series")


@dataclass
class TagEntry:
    original: str
    translation: str | None = None
    language: LanguageCode = "other"
    usage_count: int = 0
    sources: list[str] | None = None
    archived: bool = False
    type: MappingKind = "tag"


class TagMappingStore:
    """统一的原文→中文映射表; type 区分标签、制作商、发行商与系列."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "tag_mappings.json"
        self._lock = threading.RLock()
        self._entries: dict[tuple[MappingKind, str], TagEntry] = {}
        self._enabled = True
        self._last_seed: dict[MappingKind, float] = {}
        self._load()

    @staticmethod
    def _key(kind: MappingKind, original: str) -> tuple[MappingKind, str]:
        return kind, original

    @staticmethod
    def _valid_kind(value: object) -> bool:
        return value in MAPPING_KINDS

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._enabled = raw.get("enabled", True) is not False
            stored = raw.get("entries", {})
            if isinstance(stored, dict):
                # v1 词典只有标签; 旧记录全部按 tag 读取, 不改变既有映射.
                records = [(key, value, value.get("type", "tag")) for key, value in stored.items() if isinstance(value, dict)]
            elif isinstance(stored, list):
                records = [
                    (value.get("original"), value, value.get("type"))
                    for value in stored
                    if isinstance(value, dict)
                ]
            else:
                return
            for original, value, raw_kind in records:
                if not isinstance(original, str) or not original or not self._valid_kind(raw_kind):
                    continue
                kind = raw_kind
                self._entries[self._key(kind, original)] = TagEntry(
                    original=original,
                    translation=value.get("translation") or None,
                    language=value.get("language") or detect_language(original),
                    usage_count=max(0, int(value.get("usage_count", 0))),
                    sources=list(value.get("sources") or []),
                    archived=bool(value.get("archived", False)) and not bool(value.get("translation")),
                    type=kind,
                )
        except OSError, ValueError, TypeError:
            # 不覆盖损坏文件; 服务继续可用, 后续保存时使用当前可解析数据.
            self._entries = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "enabled": self._enabled,
            "entries": [
                asdict(entry)
                for _, entry in sorted(self._entries.items(), key=lambda item: (item[0][0], item[0][1]))
            ],
        }
        fd, name = tempfile.mkstemp(prefix="tag-mappings-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            Path(name).replace(self.path)
        finally:
            temp_path = Path(name)
            if temp_path.exists():
                temp_path.unlink()

    def needs_seed(self, kind: MappingKind = "tag") -> bool:
        return time.monotonic() - self._last_seed.get(kind, 0.0) > 60

    def _seed(self, kind: MappingKind, values: builtins.list[tuple[str, int]]) -> None:
        with self._lock:
            changed = False
            for original, count in values:
                if not original:
                    continue
                key = self._key(kind, original)
                entry = self._entries.get(key)
                if entry is None:
                    self._entries[key] = TagEntry(
                        original,
                        language=detect_language(original),
                        usage_count=max(0, count),
                        sources=[],
                        type=kind,
                    )
                    changed = True
                elif entry.usage_count != count:
                    entry.usage_count = max(0, count)
                    changed = True
            self._last_seed[kind] = time.monotonic()
            if changed:
                self._save()

    def seed(self, values: builtins.list[tuple[str, int]]) -> None:
        """从标签分类表同步标签与引用次数, 不覆盖已有人工作出的映射."""
        self._seed("tag", values)

    def seed_facets(self, kind: MappingKind, values: builtins.list[tuple[str, int]]) -> None:
        """同步制作商、发行商或系列分类; 标签仍由 seed() 处理."""
        if kind == "tag":
            raise ValueError("tag mappings must use seed()")
        self._seed(kind, values)

    def observe(self, tags: builtins.list[str], source: str | None = None) -> None:
        with self._lock:
            changed = False
            for tag in tags:
                name = tag.strip()
                if not name:
                    continue
                key = self._key("tag", name)
                entry = self._entries.get(key)
                if entry is None:
                    entry = TagEntry(name, language=detect_language(name), sources=[], type="tag")
                    self._entries[key] = entry
                entry.usage_count += 1
                if source and source not in (entry.sources or []):
                    entry.sources = [*(entry.sources or []), source]
                changed = True
            if changed:
                self._save()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        with self._lock:
            self._enabled = bool(enabled)
            self._save()
            return self._enabled

    def map_values(self, kind: MappingKind, values: builtins.list[str]) -> builtins.list[str]:
        """按归属类型映射并在映射后去重; UI、片库响应与 NFO 共用此映射词典, 未映射词条原样保留."""
        with self._lock:
            if not self._enabled:
                return list(dict.fromkeys(value for value in values if value))
            translated: builtins.list[str] = []
            for value in values:
                if not value:
                    continue
                entry = self._entries.get(self._key(kind, value))
                translated.append((entry.translation if entry else None) or value)
            return list(dict.fromkeys(translated))

    def map_tags(self, tags: builtins.list[str]) -> builtins.list[str]:
        return self.map_values("tag", tags)

    def display_name(self, original: str, kind: MappingKind = "tag") -> str:
        """返回指定类别原始名称对应的展示名称; 不修改原始值."""
        with self._lock:
            if not self._enabled:
                return original
            entry = self._entries.get(self._key(kind, original))
            return (entry.translation if entry else None) or original

    def map_id_map(self, values: dict[str, int], kind: MappingKind = "tag") -> dict[str, int]:
        """将分类名称映射到展示名称; 每个展示名称保留一个代表 ID."""
        mapped: dict[str, int] = {}
        with self._lock:
            for original, facet_id in values.items():
                entry = self._entries.get(self._key(kind, original)) if self._enabled else None
                display = (entry.translation if entry else None) or original
                mapped[display] = min(mapped.get(display, facet_id), facet_id)
        return mapped

    def list(
        self,
        *,
        kind: MappingKind = "tag",
        status: str = "all",
        language: str = "all",
        frequency: str = "all",
        search: str = "",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[TagEntry], int]:
        with self._lock:
            values = [entry for entry in self._entries.values() if entry.type == kind]
            if status == "pending":
                values = [v for v in values if not v.translation and not v.archived]
            elif status == "mapped":
                values = [v for v in values if bool(v.translation)]
            elif status == "archived":
                values = [v for v in values if v.archived]
            if language != "all":
                values = [v for v in values if v.language == language]
            if frequency == "high":
                values = [v for v in values if v.usage_count >= 5]
            if search:
                needle = search.casefold()
                values = [
                    v for v in values if needle in v.original.casefold() or needle in (v.translation or "").casefold()
                ]
            values.sort(key=lambda v: (-v.usage_count, v.original.casefold()))
            return values[offset : offset + limit], len(values)

    def counts(self, kind: MappingKind = "tag") -> dict[str, int]:
        with self._lock:
            values = [entry for entry in self._entries.values() if entry.type == kind]
            total = len(values)
            mapped = sum(1 for entry in values if entry.translation)
            archived = sum(1 for entry in values if entry.archived)
            pending = total - mapped - archived
            return {"all": total, "mapped": mapped, "pending": pending, "archived": archived}

    def upsert(self, original: str, translation: str | None, kind: MappingKind = "tag") -> TagEntry:
        original = original.strip()
        if not original:
            raise ValueError("原始名称不能为空")
        with self._lock:
            key = self._key(kind, original)
            entry = self._entries.get(key) or TagEntry(
                original, language=detect_language(original), sources=[], type=kind
            )
            entry.translation = translation.strip() if translation and translation.strip() else None
            entry.archived = False
            self._entries[key] = entry
            self._save()
            return entry

    def archive(self, original: str, kind: MappingKind = "tag") -> bool:
        with self._lock:
            entry = self._entries.get(self._key(kind, original))
            if entry is None or entry.translation:
                return False
            entry.archived = True
            self._save()
            return True

    def archive_many(self, originals: builtins.list[str], kind: MappingKind = "tag") -> tuple[int, int]:
        archived = skipped = 0
        with self._lock:
            for original in dict.fromkeys(originals):
                entry = self._entries.get(self._key(kind, original))
                if entry is None or entry.translation:
                    skipped += 1
                    continue
                if not entry.archived:
                    entry.archived = True
                archived += 1
            if archived:
                self._save()
        return archived, skipped

    def restore(self, original: str, kind: MappingKind = "tag") -> bool:
        with self._lock:
            entry = self._entries.get(self._key(kind, original))
            if entry is None or not entry.archived:
                return False
            entry.archived = False
            entry.translation = None
            self._save()
            return True

    def restore_many(self, originals: builtins.list[str], kind: MappingKind = "tag") -> int:
        restored = 0
        with self._lock:
            for original in dict.fromkeys(originals):
                entry = self._entries.get(self._key(kind, original))
                if entry is not None and entry.archived:
                    entry.archived = False
                    entry.translation = None
                    restored += 1
            if restored:
                self._save()
        return restored

    def export(self) -> dict:
        with self._lock:
            return {
                "version": 2,
                "entries": [
                    asdict(entry)
                    for _, entry in sorted(self._entries.items(), key=lambda item: (item[0][0], item[0][1]))
                    if entry.translation or entry.archived
                ],
            }

    def import_data(self, payload: dict) -> int:
        stored = payload.get("entries", {})
        if isinstance(stored, dict):
            # v1 导出只有标签; 允许继续导入, 归属明确解释为 tag.
            records = [
                {"original": original, **value, "type": value.get("type", "tag")}
                for original, value in stored.items()
                if isinstance(original, str) and isinstance(value, dict)
            ]
        elif isinstance(stored, list):
            records = stored
        else:
            raise ValueError("导入文件格式不正确")

        normalized: list[tuple[MappingKind, str, dict]] = []
        for value in records:
            if not isinstance(value, dict):
                raise ValueError("导入文件格式不正确")
            original = value.get("original")
            kind = value.get("type")
            if not isinstance(original, str) or not original.strip():
                raise ValueError("映射原始名称不能为空")
            if not self._valid_kind(kind):
                raise ValueError(f"无法识别的映射归属类型: {kind}")
            normalized.append((kind, original.strip(), value))

        count = 0
        with self._lock:
            for kind, original, value in normalized:
                key = self._key(kind, original)
                current = self._entries.get(key)
                if current is None:
                    current = TagEntry(
                        original, language=detect_language(original), sources=[], type=kind
                    )
                    self._entries[key] = current
                translation = value.get("translation")
                current.translation = (
                    translation.strip() if isinstance(translation, str) and translation.strip() else None
                )
                current.archived = bool(value.get("archived", False)) and not bool(current.translation)
                language = value.get("language")
                if language in {"ja", "en", "zh", "other"}:
                    current.language = language
                if isinstance(value.get("usage_count"), int):
                    current.usage_count = max(0, value["usage_count"])
                if isinstance(value.get("sources"), list):
                    current.sources = [str(source) for source in value["sources"]]
                count += 1
            self._save()
        return count
