from pathlib import Path

import pytest

from amane.mappings.dmm_text_store import DmmTextMappingStore


def test_save_exact_search_and_duplicate_source(tmp_path: Path) -> None:
    store = DmmTextMappingStore(tmp_path)
    store.save("催O", "催眠")
    store.save("催0", "催眠")

    assert store.list("催O") == {"催O": "催眠"}
    assert store.list("催眠") == {"催O": "催眠", "催0": "催眠"}
    assert store.list("O") == {}

    with pytest.raises(ValueError, match="原和谐词已存在"):
        store.save("催O", "催眠術")


def test_edit_and_batch_delete(tmp_path: Path) -> None:
    store = DmmTextMappingStore(tmp_path)
    store.save("女子JO", "女子JK")
    store.save("女子J0", "女子JK")
    store.save("女子JO", "女子JK", original_source="女子JO")
    store.save("女子JK", "女子高生", original_source="女子JO")

    assert store.list() == {"女子J0": "女子JK", "女子JK": "女子高生"}
    assert store.delete_many(["女子J0", "女子J0", "missing"]) == 1
    assert store.list() == {"女子JK": "女子高生"}


def test_merge_quarantines_only_conflicting_source_and_replace_allows_duplicate_targets(tmp_path: Path) -> None:
    store = DmmTextMappingStore(tmp_path)
    store.save("催O", "催眠")
    store.save("女子JO", "女子JK")

    result = store.import_merge({"催O": "催眠術", "女子JO": "女子JK", "女子J0": "女子JK"})

    assert result["added"] == ["女子J0"]
    assert result["unchanged"] == ["女子JO"]
    assert len(result["conflicts"]) == 1
    assert store.list() == {"女子J0": "女子JK", "女子JO": "女子JK"}
    conflicts = store.list_conflicts()
    assert conflicts[0]["old"] == {"source": "催O", "target": "催眠"}
    assert conflicts[0]["new"] == {"source": "催O", "target": "催眠術"}

    assert store.replace({"催O": "催眠", "催0": "催眠"}) == 2
    assert store.list() == {"催0": "催眠", "催O": "催眠"}


def test_replace_text_is_one_pass_and_applies_to_title_and_plot(tmp_path: Path) -> None:
    store = DmmTextMappingStore(tmp_path)
    store.save("催O", "催眠")
    store.save("催眠", "催眠術")

    class Metadata:
        title = "催O女子JO"
        plot = "催Oの物語"
        series = ""

    store.save("女子JO", "女子JK")
    metadata = Metadata()
    store.apply_metadata(metadata)

    assert metadata.title == "催眠女子JK"
    assert metadata.plot == "催眠の物語"


def test_merge_import_quarantines_duplicate_source_keys_but_imports_unique_rows(tmp_path: Path) -> None:
    store = DmmTextMappingStore(tmp_path)

    result = store.import_merge_rows(
        [
            ("重复词", "修正甲"),
            ("重复词", "修正乙"),
            ("独立词", "修正丙"),
        ]
    )

    assert result["added"] == ["独立词"]
    assert len(result["conflicts"]) == 1
    assert store.list() == {"独立词": "修正丙"}
    assert store.list_conflicts()[0]["old"] == {"source": "重复词", "target": "修正甲"}
    assert store.list_conflicts()[0]["new"] == {"source": "重复词", "target": "修正乙"}
