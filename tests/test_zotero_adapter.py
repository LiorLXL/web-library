from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import pytest

from zotero_web_library import app_store
from zotero_web_library.metadata_import import ImportedCreator, ImportedItem
from zotero_web_library.sources import SourceError, create_local_copy, create_read_only_source
from zotero_web_library.sync import mark_conflicts_for_changed_keys, prepare_sync_payloads
from zotero_web_library import web
from zotero_web_library.web import create_app
from zotero_web_library.zotero_adapter import ZoteroRepository


def test_adapter_reads_items_collections_tags_and_attachments(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    repo = ZoteroRepository(library)
    state = repo.state()
    item = next(item for item in state["items"] if item["key"] == "ITEM0001")
    assert state["collections"][0]["name"] == "VLA"
    assert item["title"] == "OpenVLA"
    assert item["semantic"]["rating"] == ["★★★★★"]
    assert "#有代码" in item["semantic"]["nested"]
    assert "/done" in item["semantic"]["reading_status"]
    assert item["attachments"][0]["resolved_path"].endswith("storage\\ATTACH01\\paper.pdf") or item["attachments"][0]["resolved_path"].endswith("storage/ATTACH01/paper.pdf")
    assert item["attachments"][0]["kind"] == "pdf"
    assert item["attachments"][0]["status"] == "openable"
    assert any(attachment["status"] == "missing" for attachment in item["attachments"])
    assert any(badge["label"] == "PDF" for badge in item["attachment_badges"])
    assert any(badge["label"] == "Note" for badge in item["attachment_badges"])
    assert {item["type"] for item in state["items"]} >= {
        "journalArticle",
        "conferencePaper",
        "preprint",
        "standard",
        "webpage",
        "computerProgram",
        "magazineArticle",
        "newspaperArticle",
    }


def test_read_only_blocks_edits(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    with pytest.raises(SourceError):
        ZoteroRepository(library).create_collection("New")


def test_local_copy_allows_collection_and_field_edits(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    repo.create_collection("New")
    repo.update_item_field("ITEM0001", "title", "Changed")
    repo.add_tag("ITEM0001", "New/Tag")
    repo.set_rating("ITEM0001", 2)
    repo.set_reading_status("ITEM0001", "reading")
    state = repo.state()
    assert any(collection["name"] == "New" for collection in state["collections"])
    item = next(item for item in state["items"] if item["key"] == "ITEM0001")
    assert item["title"] == "Changed"
    assert "#New/Tag" in item["semantic"]["nested"]
    assert item["semantic"]["rating"] == ["⭐⭐"]
    assert item["semantic"]["reading_status"] == ["/reading"]
    repo.set_reading_status("ITEM0001", "unread")
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert item["semantic"]["reading_status"] == []


def test_state_exposes_structured_fields_from_extra_and_abstract_note(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    item = next(item for item in ZoteroRepository(library).state()["items"] if item["key"] == "ITEM0001")
    assert item["structured"] == {
        "remark": "李飞飞团队",
        "title_zh": "开放词汇机器人",
        "abstract_zh": "中文摘要",
    }


def test_update_structured_field_preserves_other_blocks_and_legacy_text(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    repo.update_structured_field("ITEM0001", "remark", "新备注")
    repo.update_structured_field("ITEM0001", "abstract_zh", "新的中文摘要")

    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert item["structured"]["remark"] == "新备注"
    assert item["structured"]["title_zh"] == "开放词汇机器人"
    assert item["structured"]["abstract_zh"] == "新的中文摘要"
    assert "legacy: keep" in item["fields"]["extra"]
    assert "[title_zh]开放词汇机器人[title_zhend]" in item["fields"]["extra"]
    assert item["fields"]["abstractNote"].startswith("English abstract")


def test_update_structured_field_appends_missing_block_without_overwriting_field(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    repo.update_item_field("ITEM0001", "extra", "legacy only")
    repo.update_structured_field("ITEM0001", "title_zh", "追加标题")

    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert item["structured"]["title_zh"] == "追加标题"
    assert item["fields"]["extra"] == "legacy only\n[title_zh]追加标题[title_zhend]"


def test_update_item_field_rejects_unknown_native_field_name(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    with pytest.raises(ValueError, match="Zotero 原生字段不存在"):
        repo.update_item_field("ITEM0001", "title_zh", "不允许新增")


def test_local_copy_reparents_collection_and_prepares_sync_payloads(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    repo.create_collection("Parent")
    state = repo.state()
    parent = next(collection for collection in state["collections"] if collection["name"] == "Parent")
    repo.reparent_collection("COLL0001", parent["key"])
    repo.set_collection_membership("ITEM0001", "COLL0001", False)
    payloads = prepare_sync_payloads(library["library_id"])
    assert any(payload["operation"] == "reparent_collection" for payload in payloads)
    assert any(payload["operation"] == "set_collection_membership" for payload in payloads)
    conflicted = mark_conflicts_for_changed_keys(library["library_id"], {"COLL0001"})
    assert conflicted


def test_deleting_shortcut_does_not_remove_item_tag(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    repo.add_tag("ITEM0001", "多提示词")
    app_store.upsert_tag_shortcut(library["library_id"], "#多提示词", "#2563eb")
    app_store.mark_tag_shortcuts_initialized(library["library_id"])
    app_store.delete_tag_shortcut(library["library_id"], "#多提示词")
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert "#多提示词" in item["semantic"]["nested"]
    shortcut_tags = {item["tag"] for item in app_store.list_tag_shortcuts(library["library_id"])}
    assert "#多提示词" not in shortcut_tags


def test_tag_shortcuts_seed_from_existing_nested_tags(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    shortcuts = ZoteroRepository(library).state()["tag_shortcuts"]
    shortcut_tags = {item["tag"] for item in shortcuts}
    assert {"#VLA/端到端", "#有代码"}.issubset(shortcut_tags)
    assert app_store.tag_shortcuts_initialized(library["library_id"]) is True


def test_deleted_shortcut_does_not_reseed_after_reload(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    repo.state()
    app_store.delete_tag_shortcut(library["library_id"], "#有代码")
    reloaded = repo.state()
    assert "#有代码" not in {item["tag"] for item in reloaded["tag_shortcuts"]}


def test_tag_writes_use_zotero_tag_name_with_hash_prefix(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    repo.add_tag("ITEM0001", "多提示词")
    repo.set_reading_status("ITEM0001", "reading")
    repo.set_rating("ITEM0001", 2)

    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert "#多提示词" in item["semantic"]["nested"]
    assert item["semantic"]["reading_status"] == ["/reading"]
    assert item["semantic"]["rating"] == ["⭐⭐"]

    with sqlite3.connect(Path(library["data_path"]) / "zotero.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        assert "type" not in {row["name"] for row in conn.execute("PRAGMA table_info(tags)").fetchall()}
        assert "type" in {row["name"] for row in conn.execute("PRAGMA table_info(itemTags)").fetchall()}
        row = conn.execute(
            """
            SELECT t.name
            FROM itemTags it
            JOIN tags t ON t.tagID = it.tagID
            JOIN items i ON i.itemID = it.itemID
            WHERE i.key = ? AND t.name = ?
            """,
            ("ITEM0001", "#多提示词"),
        ).fetchone()
        assert row is not None


def test_semantic_tag_parse_and_write_boundaries_match_current_product_scope(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    repo.add_tag("ITEM0001", "多提示词")
    repo.set_rating("ITEM0001", 4)
    repo.set_reading_status("ITEM0001", "read")

    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert "#多提示词" in item["semantic"]["nested"]
    assert item["semantic"]["rating"] == ["⭐⭐⭐⭐"]
    assert item["semantic"]["reading_status"] == ["/done"]
    assert item["semantic"]["venue_rank"] == ["CCF-A"]

    with sqlite3.connect(Path(library["data_path"]) / "zotero.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        names = {
            row["name"]
            for row in conn.execute(
                """
                SELECT t.name
                FROM itemTags it
                JOIN tags t ON t.tagID = it.tagID
                JOIN items i ON i.itemID = it.itemID
                WHERE i.key = ?
                """,
                ("ITEM0001",),
            ).fetchall()
        }
    assert "#多提示词" in names
    assert "⭐⭐⭐⭐" in names
    assert "/done" in names
    assert "CCF-A" in names


def test_structured_field_api_updates_supported_keys_only(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    client = create_app().test_client()

    response = client.patch(
        f"/api/library/{library['library_id']}/items/ITEM0001/structured-field",
        json={"field": "remark", "value": "接口备注"},
    )
    assert response.status_code == 200

    invalid = client.patch(
        f"/api/library/{library['library_id']}/items/ITEM0001/structured-field",
        json={"field": "venue_rank", "value": "不允许"},
    )
    assert invalid.status_code == 400

    item = next(item for item in ZoteroRepository(library).state()["items"] if item["key"] == "ITEM0001")
    assert item["structured"]["remark"] == "接口备注"


def test_import_metadata_creates_native_item_and_adds_to_collection(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    summary = repo.import_metadata_items(
        [
            ImportedItem(
                item_type="journalArticle",
                fields={"title": "Imported Paper", "DOI": "10.9999/imported", "publicationTitle": "Demo Journal", "date": "2026"},
                creators=[ImportedCreator(first_name="Ada", last_name="Lovelace")],
                identifiers={"doi": "10.9999/imported"},
                source="test",
            )
        ],
        "COLL0001",
    )

    assert summary["created_count"] == 1
    item = next(item for item in repo.state()["items"] if item["key"] == summary["results"][0]["item_key"])
    assert item["title"] == "Imported Paper"
    assert item["fields"]["DOI"] == "10.9999/imported"
    assert item["creators_display"] == "Ada Lovelace"
    assert any(collection["key"] == "COLL0001" for collection in item["collections"])


def test_import_metadata_reuses_existing_strong_identifier_without_creating_duplicate(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    before = len(repo.state()["items"])
    summary = repo.import_metadata_items(
        [
            ImportedItem(
                item_type="journalArticle",
                fields={"title": "Should Not Create", "DOI": "https://doi.org/10.48550/ARXIV.2406.09246"},
                identifiers={"doi": "10.48550/arXiv.2406.09246"},
                source="test",
            )
        ],
        "COLL0001",
    )

    assert summary["existing_count"] == 1
    assert summary["results"][0]["item_key"] == "ITEM0001"
    assert len(repo.state()["items"]) == before
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert any(collection["key"] == "COLL0001" for collection in item["collections"])
    assert item["title"] == "OpenVLA"


def test_import_metadata_reports_conflict_when_multiple_existing_items_match(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    db_path = Path(library["data_path"]) / "zotero.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (99, 1, "2026-01-01", "2026-01-01", 1, "DUP0001", 0, 1))
        conn.execute("INSERT INTO itemData VALUES (?, ?, ?)", (99, 4, 4))
        conn.commit()

    summary = ZoteroRepository(library).import_metadata_items(
        [
            ImportedItem(
                item_type="journalArticle",
                fields={"title": "Conflict", "DOI": "10.48550/arXiv.2406.09246"},
                identifiers={"doi": "10.48550/arXiv.2406.09246"},
                source="test",
            )
        ]
    )

    assert summary["conflict_count"] == 1
    assert {candidate["key"] for candidate in summary["results"][0]["candidates"]} == {"ITEM0001", "DUP0001"}


def test_import_metadata_blocked_in_read_only_mode(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    with pytest.raises(SourceError):
        ZoteroRepository(library).import_metadata_items([ImportedItem(item_type="journalArticle", fields={"title": "Nope"})])


def test_import_apis_use_shared_metadata_import_flow(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    monkeypatch.setattr(
        web,
        "resolve_identifier",
        lambda value: ImportedItem(
            item_type="journalArticle",
            fields={"title": f"Resolved {value}", "DOI": "10.1212/api"},
            identifiers={"doi": "10.1212/api"},
            source="mock",
        ),
    )
    monkeypatch.setattr(
        web,
        "parse_import_text",
        lambda text, fmt: [
            ImportedItem(
                item_type="book",
                fields={"title": "Text Import", "ISBN": "9780306406157"},
                identifiers={"isbn": "9780306406157"},
                source=fmt,
            )
        ],
    )
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/items/import-identifier",
        json={"identifier": "10.1212/api", "collection_key": "COLL0001"},
    )
    assert response.status_code == 200
    assert response.get_json()["created_count"] == 1

    duplicate = client.post(
        f"/api/library/{library['library_id']}/items/import-identifier",
        json={"identifier": "10.1212/api", "collection_key": "COLL0001"},
    )
    assert duplicate.status_code == 200
    assert duplicate.get_json()["existing_count"] == 1

    text_response = client.post(
        f"/api/library/{library['library_id']}/items/import-text",
        json={"text": "@book{}", "format": "bibtex"},
    )
    assert text_response.status_code == 200
    assert text_response.get_json()["created_count"] == 1


def test_delete_items_to_trash_marks_deleted_without_removing_item(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    result = repo.delete_items(["ITEM0001"], "trash")

    assert result["deleted_count"] == 1
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert item["deleted"] is True
    assert (Path(library["data_path"]) / "storage" / "ATTACH01").exists()


def test_permanent_delete_items_removes_records_and_attachment_storage(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    storage_dir = Path(library["data_path"]) / "storage" / "ATTACH01"
    assert storage_dir.exists()

    result = repo.delete_items(["ITEM0001"], "permanent")

    assert result["deleted_count"] == 1
    assert result["removed_storage_dirs"] >= 1
    assert not storage_dir.exists()
    assert "ITEM0001" not in {item["key"] for item in repo.state()["items"]}
    db_path = Path(library["data_path"]) / "zotero.sqlite"
    with sqlite3.connect(db_path) as conn:
      conn.row_factory = sqlite3.Row
      for table in ["items", "itemData", "itemTags", "itemCreators", "collectionItems", "deletedItems", "itemAttachments", "itemNotes"]:
          row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE itemID IN (1, 2, 3, 4, 5, 6)").fetchone()
          assert row["count"] == 0
      assert conn.execute("SELECT COUNT(*) AS count FROM itemAnnotations WHERE itemID = 14 OR parentItemID = 2").fetchone()["count"] == 0


def test_move_items_replaces_existing_collection_memberships(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    result = repo.move_items(["ITEM0001"], "COLL0001")

    assert result["moved_count"] == 1
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert [collection["key"] for collection in item["collections"]] == ["COLL0001"]


def test_delete_collection_removes_tree_and_memberships_but_keeps_items(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    result = repo.delete_collection("COLL0001")

    assert result["deleted_count"] == 2
    state = repo.state()
    assert not state["collections"]
    item = next(item for item in state["items"] if item["key"] == "ITEM0001")
    assert item["collections"] == []


def test_item_and_collection_management_blocked_in_read_only_mode(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    repo = ZoteroRepository(library)

    with pytest.raises(SourceError):
        repo.delete_items(["ITEM0001"], "trash")
    with pytest.raises(SourceError):
        repo.move_items(["ITEM0001"], "COLL0001")
    with pytest.raises(SourceError):
        repo.delete_collection("COLL0001")


def test_item_management_apis(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    client = create_app().test_client()

    move_response = client.post(
        f"/api/library/{library['library_id']}/items/move",
        json={"item_keys": ["ITEM0001"], "target_collection_key": "COLL0001"},
    )
    assert move_response.status_code == 200
    assert move_response.get_json()["moved_count"] == 1

    delete_response = client.post(
        f"/api/library/{library['library_id']}/items/delete",
        json={"item_keys": ["ITEM0001"], "mode": "trash"},
    )
    assert delete_response.status_code == 200
    assert delete_response.get_json()["mode"] == "trash"

    collection_response = client.delete(f"/api/library/{library['library_id']}/collections/COLL0002")
    assert collection_response.status_code == 200
    assert collection_response.get_json()["deleted_count"] == 1


def test_file_attachment_add_rename_and_delete_updates_storage(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    source_file = tmp_path / "demo.pdf"
    source_file.write_bytes(b"%PDF-1.4\n%%EOF\n")

    added = repo.add_file_attachment("ITEM0001", source_file, "demo.pdf", "application/pdf")
    attachment_key = added["attachment_key"]
    storage_dir = Path(library["data_path"]) / "storage" / attachment_key
    assert (storage_dir / "demo.pdf").exists()

    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    attachment = next(value for value in item["attachments"] if value["key"] == attachment_key)
    assert attachment["display_label"] == "demo.pdf"
    assert attachment["kind"] == "pdf"

    renamed = repo.rename_attachment(attachment_key, "renamed")
    assert renamed["title"] == "renamed.pdf"
    assert not (storage_dir / "demo.pdf").exists()
    assert (storage_dir / "renamed.pdf").exists()
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    attachment = next(value for value in item["attachments"] if value["key"] == attachment_key)
    assert attachment["path"] == "storage:renamed.pdf"
    assert attachment["display_label"] == "renamed.pdf"

    deleted = repo.delete_attachments([attachment_key])
    assert deleted["deleted_count"] == 1
    assert deleted["removed_storage_dirs"] == 1
    assert not storage_dir.exists()
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    assert attachment_key not in {attachment["key"] for attachment in item["attachments"]}


def test_pdf_annotation_read_and_create_use_zotero_native_table(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    existing = repo.annotations_for_attachment("ATTACH01")
    assert existing[0]["key"] == "ANNOT001"
    assert existing[0]["type"] == "highlight"
    assert existing[0]["position"]["rects"] == [[10, 20, 30, 40]]

    highlight = repo.create_pdf_annotation(
        "ATTACH01",
        {"type": "highlight", "text": "new highlight", "color": "#ffd400", "page_index": 0, "page_label": "1", "rects": [[1, 2, 3, 4]]},
    )
    underline = repo.create_pdf_annotation(
        "ATTACH01",
        {"type": "underline", "text": "new underline", "color": "#2ea8e5", "page_index": 0, "page_label": "1", "rects": [[5, 6, 7, 8]]},
    )
    positioned = repo.create_pdf_annotation(
        "ATTACH01",
        {
            "type": "highlight",
            "text": "position object",
            "color": "#ffd400",
            "position": {"pageIndex": 1, "rects": [[9.11119, 10.22229, 11.33339, 12.44449]]},
        },
    )

    assert highlight["type_id"] == 1
    assert underline["type_id"] == 5
    assert positioned["position"] == {"pageIndex": 1, "rects": [[9.111, 10.222, 11.333, 12.444]]}
    with sqlite3.connect(Path(library["data_path"]) / "zotero.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT ia.type, ia.text, ia.position
            FROM itemAnnotations ia
            JOIN items i ON i.itemID = ia.itemID
            WHERE i.key IN (?, ?)
            ORDER BY ia.type
            """,
            (highlight["key"], underline["key"]),
        ).fetchall()
    assert [row["type"] for row in rows] == [1, 5]
    assert rows[0]["text"] == "new highlight"
    assert '"pageIndex":0' in rows[0]["position"]


def test_pdf_annotation_rejects_non_pdf_and_read_only(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    local_library = create_local_copy(zotero_fixture)
    with pytest.raises(ValueError, match="仅支持 PDF"):
        ZoteroRepository(local_library).create_pdf_annotation(
            "HTML01",
            {"type": "highlight", "page_index": 0, "rects": [[1, 2, 3, 4]]},
        )

    readonly_library = create_read_only_source(zotero_fixture)
    with pytest.raises(SourceError):
        ZoteroRepository(readonly_library).create_pdf_annotation(
            "ATTACH01",
            {"type": "highlight", "page_index": 0, "rects": [[1, 2, 3, 4]]},
        )


def test_clear_pdf_annotations_deletes_intersecting_saved_styles_only(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)
    matching = repo.create_pdf_annotation(
        "ATTACH01",
        {"type": "highlight", "text": "delete me", "page_index": 0, "rects": [[1, 2, 5, 6]]},
    )
    same_page_other_area = repo.create_pdf_annotation(
        "ATTACH01",
        {"type": "underline", "text": "keep me", "page_index": 0, "rects": [[50, 60, 70, 80]]},
    )
    other_page = repo.create_pdf_annotation(
        "ATTACH01",
        {"type": "highlight", "text": "keep page", "position": {"pageIndex": 1, "rects": [[1, 2, 5, 6]]}},
    )

    result = repo.clear_pdf_annotations("ATTACH01", {"position": {"pageIndex": 0, "rects": [[4, 5, 7, 8]]}})

    assert result["deleted_count"] == 1
    assert result["annotation_keys"] == [matching["key"]]
    remaining_keys = {annotation["key"] for annotation in repo.annotations_for_attachment("ATTACH01")}
    assert matching["key"] not in remaining_keys
    assert same_page_other_area["key"] in remaining_keys
    assert other_page["key"] in remaining_keys


def test_clear_pdf_annotations_rejects_read_only_source(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    readonly_library = create_read_only_source(zotero_fixture)
    with pytest.raises(SourceError):
        ZoteroRepository(readonly_library).clear_pdf_annotations(
            "ATTACH01",
            {"position": {"pageIndex": 0, "rects": [[1, 2, 3, 4]]}},
        )


def test_deleting_attachment_removes_child_annotations(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    result = repo.delete_attachments(["ATTACH01"])

    assert result["deleted_count"] == 1
    with sqlite3.connect(Path(library["data_path"]) / "zotero.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT COUNT(*) AS count FROM items WHERE key = 'ANNOT001'").fetchone()["count"] == 0
        assert conn.execute("SELECT COUNT(*) AS count FROM itemAnnotations WHERE itemID = 14 OR parentItemID = 2").fetchone()["count"] == 0


def test_url_attachment_add_and_rename_does_not_create_storage(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    repo = ZoteroRepository(library)

    added = repo.add_url_attachment("ITEM0001", "https://example.com/paper", "项目主页")
    attachment_key = added["attachment_key"]

    assert not (Path(library["data_path"]) / "storage" / attachment_key).exists()
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    attachment = next(value for value in item["attachments"] if value["key"] == attachment_key)
    assert attachment["kind"] == "link"
    assert attachment["display_label"] == "项目主页"
    assert attachment["path"] == "https://example.com/paper"

    repo.rename_attachment(attachment_key, "新标题")
    item = next(item for item in repo.state()["items"] if item["key"] == "ITEM0001")
    attachment = next(value for value in item["attachments"] if value["key"] == attachment_key)
    assert attachment["display_label"] == "新标题"
    assert attachment["path"] == "https://example.com/paper"


def test_attachment_edits_blocked_in_read_only_mode(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    repo = ZoteroRepository(library)
    source_file = tmp_path / "demo.pdf"
    source_file.write_bytes(b"%PDF-1.4\n%%EOF\n")

    with pytest.raises(SourceError):
        repo.add_file_attachment("ITEM0001", source_file, "demo.pdf", "application/pdf")
    with pytest.raises(SourceError):
        repo.add_url_attachment("ITEM0001", "https://example.com", "Example")
    with pytest.raises(SourceError):
        repo.rename_attachment("ATTACH01", "New")
    with pytest.raises(SourceError):
        repo.delete_attachments(["ATTACH01"])


def test_attachment_management_apis(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    client = create_app().test_client()

    upload_response = client.post(
        f"/api/library/{library['library_id']}/items/ITEM0001/attachments/file",
        data={"file": (BytesIO(b"%PDF-1.4\n%%EOF\n"), "api.pdf")},
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 200
    uploaded_key = upload_response.get_json()["attachment_key"]

    url_response = client.post(
        f"/api/library/{library['library_id']}/items/ITEM0001/attachments/url",
        json={"url": "https://example.com/api", "title": "API 链接"},
    )
    assert url_response.status_code == 200

    rename_response = client.patch(
        f"/api/library/{library['library_id']}/attachments/{uploaded_key}",
        json={"title": "api-renamed"},
    )
    assert rename_response.status_code == 200
    assert rename_response.get_json()["title"] == "api-renamed.pdf"

    delete_response = client.delete(
        f"/api/library/{library['library_id']}/attachments/{uploaded_key}",
        json={"attachment_keys": [uploaded_key]},
    )
    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted_count"] == 1
