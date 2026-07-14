from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from zotero_web_library.rag import index_library
from zotero_web_library.rag.agent.evidence import EvidenceAccumulator
from zotero_web_library.rag.agent.loop import run_agentic_chat
from zotero_web_library.rag.agent.memory import load_history
from zotero_web_library.rag.agent.tools import ScopeContext, execute_tool
from zotero_web_library.rag.store import (
    connect,
    create_knowledge_base,
    delete_knowledge_base,
    remove_knowledge_base_items,
)
from zotero_web_library.rag.tools import keyword_search
from zotero_web_library.sources import create_local_copy


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


def assistant_response(*, content: str = "", tool_calls: list[Any] | None = None, total_tokens: int = 10) -> Any:
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls or [])
    usage = SimpleNamespace(prompt_tokens=total_tokens, completion_tokens=0, total_tokens=total_tokens)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def tool_call(name: str, args: dict[str, Any], *, call_id: str = "call-1") -> Any:
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeCompletions:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("fake client response script exhausted")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def indexed_library(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    write_mineru_fixture(library)
    index_library(library)
    return library


def test_evidence_accumulator_deduplicates_and_reuses_ids() -> None:
    accumulator = EvidenceAccumulator()
    first = accumulator.register(
        [
            {
                "item_key": "ITEM0001",
                "chunk_id": "chunk-a",
                "title": "Paper",
                "excerpt": "first",
                "citation": "[ITEM0001:chunk-a]",
            }
        ]
    )
    second = accumulator.register(
        [
            {
                "item_key": "ITEM0001",
                "chunk_id": "chunk-a",
                "title": "Paper",
                "excerpt": "second",
                "citation": "[ITEM0001:chunk-a]",
            },
            {
                "item_key": "ITEM0001",
                "source_type": "metadata",
                "title": "Paper",
            },
        ]
    )

    assert first[0]["evidence_id"] == "ev-1"
    assert second[0]["evidence_id"] == "ev-1"
    assert second[1]["evidence_id"] == "ev-2"
    assert [item["evidence_id"] for item in accumulator.all_sources()] == ["ev-1", "ev-2"]


def test_agent_tools_inject_scope_and_guard_chunk_reads(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    accumulator = EvidenceAccumulator()
    scope = ScopeContext(scoped["knowledge_base_id"], ["ITEM0001"])

    result, trace = execute_tool(
        tool_call("search_evidence", {"query": "Action chunking", "mode": "hybrid", "top_k": 5}),
        library,
        scope,
        accumulator,
    )

    assert trace["ok"] is True
    assert result["results"]
    assert "text" not in result["results"][0]
    chunk_id = result["results"][0]["chunk_id"]

    read_result, read_trace = execute_tool(
        tool_call("read_chunk_context", {"chunk_id": chunk_id, "window_size": 1}),
        library,
        scope,
        accumulator,
    )

    assert read_trace["ok"] is True
    assert read_result["chunks"]
    assert "text" in read_result["chunks"][0]
    assert any(source["chunk_id"] == chunk_id for source in accumulator.all_sources())

    blocked_result, blocked_trace = execute_tool(
        tool_call("read_chunk_context", {"chunk_id": chunk_id, "window_size": 1}),
        library,
        ScopeContext(scoped["knowledge_base_id"], ["ITEM0002"]),
        EvidenceAccumulator(),
    )

    assert blocked_trace["ok"] is False
    assert blocked_result["error"] == "chunk_out_of_scope"


def test_run_agentic_chat_normal_flow_persists_pruned_history(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    fake_client = FakeClient(
        [
            assistant_response(tool_calls=[tool_call("search_evidence", {"query": "Action chunking", "mode": "hybrid"})]),
            assistant_response(content="Action chunking 可增强长时程操作鲁棒性 [ITEM0001:chunk-test]。"),
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="Action chunking 有什么作用？",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert result["ok"] is True
    assert result["conversation_id"].startswith("conv-")
    assert result["tool_trace"][0]["tool"] == "search_evidence"
    assert fake_client.completions.calls[0]["tool_choice"] == "auto"
    assert fake_client.completions.calls[0]["messages"][0]["role"] == "system"

    history = load_history(library, result["conversation_id"])
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert "Action chunking" in history[1]["content"]


def test_run_agentic_chat_forces_final_iteration_and_ignores_tool_calls(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    fake_client = FakeClient(
        [
            assistant_response(tool_calls=[tool_call("list_scope_documents", {}, call_id=f"call-{index}")])
            for index in range(5)
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="列出范围",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert len(fake_client.completions.calls) == 5
    assert fake_client.completions.calls[-1]["tool_choice"] == "none"
    assert len(result["tool_trace"]) == 4
    assert "final_tool_calls_ignored" in result["warnings"]


def test_run_agentic_chat_token_budget_forces_one_final_call(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    fake_client = FakeClient(
        [
            assistant_response(tool_calls=[tool_call("list_scope_documents", {})], total_tokens=60_000),
            assistant_response(content="基于已有证据，当前范围包含 OpenVLA。", total_tokens=10),
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="这个库有什么？",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert len(fake_client.completions.calls) == 2
    assert fake_client.completions.calls[-1]["tool_choice"] == "none"
    assert "token_budget_exceeded" in result["warnings"]


def test_session_scope_is_snapshotted_and_deleted_with_knowledge_base(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    unrelated = create_knowledge_base(library, name="Other", item_keys=["ITEM0002"])
    first_client = FakeClient([assistant_response(content="第一轮回答。")])
    first = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="第一轮",
        knowledge_base_id=scoped["knowledge_base_id"],
        item_keys=["ITEM0001", "ITEM0002"],
        client=first_client,
    )

    remove_knowledge_base_items(library, scoped["knowledge_base_id"], ["ITEM0001"])
    second_client = FakeClient(
        [
            assistant_response(tool_calls=[tool_call("search_evidence", {"query": "Action chunking", "mode": "keyword"})]),
            assistant_response(content="second answer"),
        ]
    )
    second = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        conversation_id=first["conversation_id"],
        question="第二轮",
        knowledge_base_id=unrelated["knowledge_base_id"],
        item_keys=["ITEM0002"],
        client=second_client,
    )

    assert second["conversation_id"] == first["conversation_id"]
    assert second["tool_trace"][0]["result_count"] > 0
    assert {source["item_key"] for source in second["sources"]} == {"ITEM0001"}
    with connect(library) as conn:
        session = conn.execute("SELECT * FROM rag_chat_sessions WHERE conversation_id = ?", (first["conversation_id"],)).fetchone()
        assert json.loads(session["item_keys_json"]) == ["ITEM0001"]

    delete_knowledge_base(library, scoped["knowledge_base_id"])
    with connect(library) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rag_chat_sessions WHERE conversation_id = ?", (first["conversation_id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM rag_chat_messages WHERE conversation_id = ?", (first["conversation_id"],)).fetchone()[0] == 0


def test_tool_error_is_returned_for_invalid_arguments(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    result, trace = execute_tool(
        SimpleNamespace(id="bad", function=SimpleNamespace(name="search_evidence", arguments="[]")),
        library,
        ScopeContext("kb-test", ["ITEM0001"]),
        EvidenceAccumulator(),
    )

    assert result["error"] == "invalid_tool_arguments"
    assert trace["ok"] is False


def test_keyword_fixture_still_indexes_expected_chunk(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    result = keyword_search(library, "Action chunking")
    assert result["results"]
