from __future__ import annotations

import json
from pathlib import Path

from zotero_web_library.rag import chunk_read, index_library, keyword_search, metadata_search, retrieve
from zotero_web_library.rag.store import create_knowledge_base
from zotero_web_library.rag.store import rag_db_path
from zotero_web_library.sources import create_local_copy
from zotero_web_library.web import create_app


def write_mineru_fixture(library: dict[str, str]) -> None:
    root = Path(library["data_path"]) / "mineru-results"
    root.mkdir(parents=True, exist_ok=True)
    stem = "20260703010101-ATTACH01"
    payload = {
        "schema": "web-library.mineru-parse-result/v1",
        "library_id": library["library_id"],
        "item_key": "ITEM0001",
        "attachment": {"key": "ATTACH01", "title": "paper.pdf"},
        "parsed_at": "2026-07-03T01:01:01Z",
        "result": {"data": {"markdown": "# Abstract\nRobot catalyst planning improves embodied control.\n\n# Method\nAction chunking is used for robust manipulation."}},
    }
    (root / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (root / f"{stem}.md").write_text(
        "# Abstract\nRobot catalyst planning improves embodied control.\n\n# Method\nAction chunking is used for robust manipulation.",
        encoding="utf-8",
    )
    image_dir = root / stem / "images"
    image_dir.mkdir(parents=True)
    (image_dir / "figure-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")


def test_rag_indexes_metadata_notes_and_mineru_results(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)

    status = index_library(library)

    assert Path(status["rag_db_path"]).exists()
    assert Path(status["rag_db_path"]) == rag_db_path(library)
    assert status["total_chunks"] >= 4
    assert {item["source_type"] for item in status["sources"]} >= {"zotero_metadata", "note", "mineru_markdown"}

    metadata = metadata_search(library, "OpenVLA")
    assert metadata["results"]
    assert metadata["results"][0]["source"]["item_key"] == "ITEM0001"

    result = keyword_search(library, "Action chunking")
    assert result["results"]
    first = result["results"][0]
    assert first["source"]["source_type"] == "mineru_markdown"
    assert first["source"]["title"] == "OpenVLA"

    context = chunk_read(library, first["chunk_id"], window_size=1)
    assert context["chunks"]
    assert any("Action chunking" in chunk["content"] for chunk in context["chunks"])


def test_rag_api_minimal_flow(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    client = create_app().test_client()

    index_response = client.post(f"/api/library/{library['library_id']}/rag/index")
    assert index_response.status_code == 200
    index_payload = index_response.get_json()
    assert index_payload["ok"] is True
    assert index_payload["status"]["total_chunks"] >= 4

    search_response = client.post(
        f"/api/library/{library['library_id']}/rag/tools/keyword_search",
        json={"query": "Robot catalyst", "top_k": 5},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["ok"] is True
    assert search_payload["results"]
    chunk_id = search_payload["results"][0]["chunk_id"]

    read_response = client.post(
        f"/api/library/{library['library_id']}/rag/tools/chunk_read",
        json={"chunk_id": chunk_id, "window_size": 1},
    )
    assert read_response.status_code == 200
    read_payload = read_response.get_json()
    assert read_payload["ok"] is True
    assert read_payload["chunks"]
    assert read_payload["source"]["item_key"] == "ITEM0001"

    retrieve_response = client.post(
        f"/api/library/{library['library_id']}/rag/tools/retrieve",
        json={"query": "Action chunking", "top_k": 3},
    )
    assert retrieve_response.status_code == 200
    retrieve_payload = retrieve_response.get_json()
    assert retrieve_payload["ok"] is True
    assert retrieve_payload["results"]
    assert retrieve_payload["results"][0]["citation"].startswith("[ITEM0001:")

    bad_retrieve_response = client.post(
        f"/api/library/{library['library_id']}/rag/tools/retrieve",
        json={"query": "Action chunking", "item_keys": "ITEM0001"},
    )
    assert bad_retrieve_response.status_code == 400


def test_knowledge_base_scopes_keyword_search(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    index_library(library)

    unrelated = create_knowledge_base(library, name="Unrelated", item_keys=["ITEM0002"])
    assert unrelated["item_count"] == 1
    assert keyword_search(library, "Action chunking", knowledge_base_id=unrelated["knowledge_base_id"])["results"] == []

    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    result = keyword_search(library, "Action chunking", knowledge_base_id=scoped["knowledge_base_id"])

    assert result["results"]
    assert {item["item_key"] for item in result["results"]} == {"ITEM0001"}

    bypass_attempt = keyword_search(
        library,
        "Action chunking",
        knowledge_base_id=unrelated["knowledge_base_id"],
        item_keys=["ITEM0001"],
    )
    assert bypass_attempt["results"] == []


def test_retrieve_builds_evidence_pack(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    index_library(library)

    pack = retrieve(library, "Action chunking", top_k=5)

    assert pack["query"] == "Action chunking"
    assert pack["mode"] == "auto"
    assert {call["tool"] for call in pack["tool_calls"]} == {"metadata_search", "keyword_search"}
    assert pack["results"]
    first = pack["results"][0]
    assert first["evidence_id"] == "ev-1"
    assert first["source_type"] == "chunk"
    assert first["item_key"] == "ITEM0001"
    assert first["citation"].startswith("[ITEM0001:chunk-")
    assert "Action chunking" in first["text"]


def test_retrieve_respects_knowledge_base_scope(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    index_library(library)
    unrelated = create_knowledge_base(library, name="Unrelated", item_keys=["ITEM0002"])

    pack = retrieve(
        library,
        "Action chunking",
        knowledge_base_id=unrelated["knowledge_base_id"],
        item_keys=["ITEM0001"],
    )

    assert pack["results"] == []
    assert "no_evidence_found" in pack["warnings"]


def test_retrieve_falls_back_to_scoped_context_for_natural_language_question(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    index_library(library)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])

    pack = retrieve(library, "这篇文章的方法是什么？", knowledge_base_id=scoped["knowledge_base_id"], top_k=5)

    assert pack["results"]
    assert len(pack["results"]) <= 4
    assert {item["item_key"] for item in pack["results"]} == {"ITEM0001"}
    assert "keyword_no_match_used_scope_context" in pack["warnings"]
    assert any(call["tool"] == "scope_context_read" for call in pack["tool_calls"])
    assert all(item["retrieval_type"] == "scope_context" for item in pack["results"])
    assert any("Action chunking" in item["text"] for item in pack["results"])


def test_retrieve_semantic_mode_is_explicitly_not_configured(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    index_library(library)

    pack = retrieve(library, "robot planning", mode="semantic")

    assert pack["results"] == []
    assert "semantic_search_not_configured" in pack["warnings"]
    assert pack["tool_calls"] == [
        {
            "tool": "semantic_search",
            "query": "robot planning",
            "result_count": 0,
            "status": "not_configured",
        }
    ]


def test_knowledge_base_api_crud_and_scoped_search(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    client = create_app().test_client()

    assert client.post(f"/api/library/{library['library_id']}/rag/index").status_code == 200

    create_response = client.post(
        f"/api/library/{library['library_id']}/rag/knowledge-bases",
        json={"name": "VLA 核心论文", "item_keys": ["ITEM0002"]},
    )
    assert create_response.status_code == 200
    kb = create_response.get_json()["knowledge_base"]
    assert kb["item_count"] == 1

    empty_search = client.post(
        f"/api/library/{library['library_id']}/rag/tools/keyword_search",
        json={"query": "Action chunking", "knowledge_base_id": kb["knowledge_base_id"]},
    ).get_json()
    assert empty_search["ok"] is True
    assert empty_search["results"] == []

    add_response = client.post(
        f"/api/library/{library['library_id']}/rag/knowledge-bases/{kb['knowledge_base_id']}/items",
        json={"item_keys": ["ITEM0001"]},
    )
    assert add_response.status_code == 200
    assert add_response.get_json()["knowledge_base"]["item_count"] == 2

    scoped_search = client.post(
        f"/api/library/{library['library_id']}/rag/tools/keyword_search",
        json={"query": "Action chunking", "knowledge_base_id": kb["knowledge_base_id"]},
    ).get_json()
    assert scoped_search["ok"] is True
    assert scoped_search["results"]
    assert {item["item_key"] for item in scoped_search["results"]} == {"ITEM0001"}

    bad_filter_response = client.post(
        f"/api/library/{library['library_id']}/rag/tools/keyword_search",
        json={"query": "Action chunking", "item_keys": "ITEM0001"},
    )
    assert bad_filter_response.status_code == 400

    remove_response = client.delete(
        f"/api/library/{library['library_id']}/rag/knowledge-bases/{kb['knowledge_base_id']}/items",
        json={"item_keys": ["ITEM0001"]},
    )
    assert remove_response.status_code == 200
    assert remove_response.get_json()["knowledge_base"]["item_count"] == 1

    delete_response = client.delete(f"/api/library/{library['library_id']}/rag/knowledge-bases/{kb['knowledge_base_id']}")
    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted"] is True

    list_response = client.get(f"/api/library/{library['library_id']}/rag/knowledge-bases")
    assert list_response.status_code == 200
    assert all(
        item["knowledge_base_id"] != kb["knowledge_base_id"]
        for item in list_response.get_json()["knowledge_bases"]
    )

    missing_response = client.get(f"/api/library/{library['library_id']}/rag/knowledge-bases/{kb['knowledge_base_id']}")
    assert missing_response.status_code == 400
