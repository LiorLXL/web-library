from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zotero_web_library import app_store
from zotero_web_library.codex_agent import build_config_overrides, build_runtime_config
from zotero_web_library.rag import index_library
from zotero_web_library.sources import create_local_copy
from zotero_web_library.web import API_CONFIG_PREFERENCE_KEY, create_app


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
        "result": {"data": {"markdown": "# Method\nAction chunking is used for robust manipulation."}},
    }
    (root / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (root / f"{stem}.md").write_text("# Method\nAction chunking is used for robust manipulation.", encoding="utf-8")


def test_codex_runtime_config_uses_library_settings() -> None:
    library = {"library_id": "lib-123"}
    runtime = build_runtime_config(
        library,
        {
            "model": "gpt-5.4",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "reasoning_effort_default": "high",
        },
    )

    assert runtime["api_key"] == "sk-test"
    assert runtime["base_url"] == "https://api.openai.com/v1/"
    assert runtime["model"] == "gpt-5.4"
    assert runtime["model_provider"] == "web_library_lib_123"
    assert runtime["reasoning_effort"] == "high"

    overrides = build_config_overrides(runtime)
    assert 'model="gpt-5.4"' in overrides
    assert 'model_provider="web_library_lib_123"' in overrides
    assert 'model_providers.web_library_lib_123.wire_api="responses"' in overrides


def test_codex_agent_check_reports_missing_config(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/rag/agent/check")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["configured"] is False
    assert payload["missing"] == ["model", "api_key"]


def test_rag_agent_check_uses_saved_model_config(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    app_store.set_preference(
        library["library_id"],
        API_CONFIG_PREFERENCE_KEY,
        {
            "model": {
                "model": "gpt-5.4",
                "base_url": "https://api.openai.com/v1/chat/completions",
                "api_key": "sk-test",
            }
        },
    )
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/rag/agent/check")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["configured"] is True
    assert payload["model"] == "gpt-5.4"
    assert payload["base_url"] == "https://api.openai.com/v1"
    assert payload["missing"] == []


def test_rag_chat_uses_agentic_runner_and_model_config(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    index_library(library)
    app_store.set_preference(
        library["library_id"],
        API_CONFIG_PREFERENCE_KEY,
        {
            "model": {
                "model": "gpt-5.4",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            }
        },
    )
    captured: dict[str, Any] = {}

    def fake_runner(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "ok": True,
            "conversation_id": "conv-test",
            "answer": "Action chunking 用于增强长时程操作鲁棒性 [ITEM0001:chunk-test]。",
            "sources": [{"citation": "[ITEM0001:chunk-test]"}],
            "tool_trace": [{"tool": "search_evidence", "ok": True, "result_count": 1}],
            "usage": {"input_tokens": 10},
            "iterations": 2,
            "warnings": [],
        }

    monkeypatch.setattr("zotero_web_library.web.rag_run_agentic_chat", fake_runner)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/rag/chat",
        json={"question": "Action chunking", "knowledge_base_id": "kb-test"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "Action chunking" in payload["answer"]
    assert payload["sources"]
    assert payload["tool_trace"]
    assert captured["model_config"]["api_key"] == "sk-test"
    assert captured["knowledge_base_id"] == "kb-test"


def test_rag_chat_requires_model_config(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/rag/chat",
        json={"question": "不存在的证据问题", "knowledge_base_id": "kb-test"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "模型 API 配置不完整" in payload["error"]
