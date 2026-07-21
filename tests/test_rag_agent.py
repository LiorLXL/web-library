from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from zotero_web_library.rag import index_library
from zotero_web_library.rag.agent.evidence import EvidenceAccumulator
from zotero_web_library.rag.agent.controller import AgentController
from zotero_web_library.rag.agent.jobs import cancel_agent_chat_job, restart_agent_chat_job, start_agentic_chat_job
from zotero_web_library.rag.agent.loop import prepare_agentic_chat_run, run_agentic_chat
from zotero_web_library.rag.agent.memory import complete_turn, load_conversation, load_history
from zotero_web_library.rag.agent.models import EvidenceState, TaskPlan
from zotero_web_library.rag.agent.runtime import load_agent_run, reconcile_interrupted_runs
from zotero_web_library.rag.agent.tools import ScopeContext, execute_tool
from zotero_web_library.rag.agent.verifier import parse_answer_envelope, verify_answer
from zotero_web_library.rag.store import (
    connect,
    create_knowledge_base,
    delete_knowledge_base,
    remove_knowledge_base_items,
)
from zotero_web_library.rag.tools import keyword_search
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


def action_citation(library: dict[str, Any]) -> str:
    results = keyword_search(library, "Action chunking", top_k=5).get("results") or []
    assert results
    result = results[0]
    return f"[{result['item_key']}:{result['chunk_id']}]"


def structured_answer(citation: str, claim: str = "Action chunking is used for robust manipulation.") -> str:
    return json.dumps(
        {
            "answer_markdown": f"{claim} {citation}",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": claim,
                    "citations": [citation],
                    "factual": True,
                }
            ],
            "citations": [citation],
        }
    )


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


def test_phase2_task_plan_and_evidence_state_contract() -> None:
    plan = TaskPlan.initial(
        "比较 Paper A 与 Paper B 的方法差异",
        task_type="comparative",
        scope_item_keys=["ITEM0001", "ITEM0002"],
        planned_queries=[
            {"text": "Paper A", "reason": "task_decomposition"},
            {"text": "Paper B", "reason": "task_decomposition"},
        ],
    )
    assert plan.task_type == "comparative"
    assert plan.completion_conditions["minimum_item_coverage"] == 2
    assert plan.budget.max_tool_calls > plan.budget.max_search_calls
    assert [item.question for item in plan.subquestions] == [
        "比较 Paper A 与 Paper B 的方法差异",
        "Paper A",
        "Paper B",
    ]

    evidence_state = EvidenceState.for_plan(plan)
    evidence_state.observe_tool_result(
        "search_evidence",
        {
            "results": [
                {
                    "evidence_id": "ev-1",
                    "citation": "[ITEM0001:chunk-a]",
                    "source_type": "chunk",
                    "item_key": "ITEM0001",
                    "chunk_id": "chunk-a",
                    "title": "Paper A",
                }
            ],
            "warnings": ["reranker_failed"],
        },
    )
    evidence_state.observe_tool_result(
        "read_chunk_context",
        {
            "chunks": [
                {
                    "evidence_id": "ev-1",
                    "citation": "[ITEM0001:chunk-a]",
                    "source_type": "chunk",
                    "item_key": "ITEM0001",
                    "chunk_id": "chunk-a",
                    "title": "Paper A",
                }
            ]
        },
    )
    evidence_state.mark_answer_usage("Paper A 使用方法 A [ITEM0001:chunk-a]。")

    snapshot = evidence_state.to_dict()
    assert snapshot["coverage"]["sq-1"]["status"] == "evidence_found"
    assert snapshot["evidence"][0]["status"] == "used"
    assert snapshot["used_evidence_ids"] == ["ev-1"]
    assert snapshot["warnings"] == ["reranker_failed"]


def test_knowledge_base_relationship_plan_requires_content_from_all_explicit_papers() -> None:
    plan = TaskPlan.initial(
        "这个知识库里的三篇论文是什么关系",
        task_type="comparative",
        scope_item_keys=["ITEM0001", "ITEM0002", "ITEM0003"],
    )
    state = EvidenceState.for_plan(plan)
    state.observe_tool_result(
        "list_scope_documents",
        {
            "documents": [
                {
                    "evidence_id": f"ev-{index}",
                    "citation": f"[ITEM000{index}:metadata]",
                    "source_type": "metadata",
                    "item_key": f"ITEM000{index}",
                }
                for index in range(1, 4)
            ]
        },
    )

    assert plan.completion_conditions["minimum_item_coverage"] == 3
    metadata_gap = AgentController(plan.budget).completion_gap(plan, state)
    assert metadata_gap["gap_type"] == "content_evidence_required"

    state.observe_tool_result(
        "search_evidence",
        {
            "results": [
                {
                    "evidence_id": "ev-content-1",
                    "citation": "[ITEM0001:chunk-a]",
                    "source_type": "chunk",
                    "item_key": "ITEM0001",
                    "chunk_id": "chunk-a",
                }
            ]
        },
    )
    coverage_gap = AgentController(plan.budget).completion_gap(plan, state)
    assert coverage_gap["gap_type"] == "minimum_item_coverage_not_met"
    assert coverage_gap["observed"] == 1
    assert coverage_gap["required"] == 3


def test_answer_verifier_enforces_content_registry_scope_and_comparison_coverage() -> None:
    evidence = [
        {
            "evidence_id": "ev-1",
            "citation": "[ITEM0001:chunk-a]",
            "source_type": "chunk",
            "item_key": "ITEM0001",
            "support_text": "Action chunking is used for robust manipulation.",
        }
    ]
    factual_plan = TaskPlan.initial(
        "What is action chunking used for?",
        task_type="factual",
        scope_item_keys=["ITEM0001"],
    )
    verified = verify_answer(
        parse_answer_envelope(structured_answer("[ITEM0001:chunk-a]")),
        task_plan=factual_plan,
        evidence=evidence,
        scope_item_keys=["ITEM0001"],
    )
    assert verified["status"] == "verified"
    assert verified["verified_evidence_ids"] == ["ev-1"]

    unknown = verify_answer(
        parse_answer_envelope(structured_answer("[ITEM0001:unknown]")),
        task_plan=factual_plan,
        evidence=evidence,
        scope_item_keys=["ITEM0001"],
    )
    assert unknown["hard_gate_passed"] is False
    assert "citation_not_in_registry" in {issue["code"] for issue in unknown["issues"]}

    metadata_only = verify_answer(
        parse_answer_envelope(structured_answer("[ITEM0001:metadata]")),
        task_plan=factual_plan,
        evidence=[{**evidence[0], "citation": "[ITEM0001:metadata]", "source_type": "metadata"}],
        scope_item_keys=["ITEM0001"],
    )
    assert metadata_only["hard_gate_passed"] is False
    assert "content_evidence_required" in {issue["code"] for issue in metadata_only["issues"]}

    comparative_plan = TaskPlan.initial(
        "Compare the two methods",
        task_type="comparative",
        scope_item_keys=["ITEM0001", "ITEM0002"],
    )
    incomplete_comparison = verify_answer(
        parse_answer_envelope(structured_answer("[ITEM0001:chunk-a]")),
        task_plan=comparative_plan,
        evidence=evidence,
        scope_item_keys=["ITEM0001", "ITEM0002"],
    )
    assert incomplete_comparison["hard_gate_passed"] is False
    assert "minimum_item_coverage_not_met" in {
        issue["code"] for issue in incomplete_comparison["issues"]
    }


def test_semantic_judge_cannot_bypass_hard_gate_but_can_resolve_text_support() -> None:
    plan = TaskPlan.initial(
        "What is the benefit?",
        task_type="factual",
        scope_item_keys=["ITEM0001"],
    )
    citation = "[ITEM0001:chunk-a]"
    envelope = parse_answer_envelope(
        structured_answer(citation, "It makes long-horizon tasks substantially more reliable.")
    )
    evidence = [
        {
            "evidence_id": "ev-1",
            "citation": citation,
            "source_type": "chunk",
            "item_key": "ITEM0001",
            "support_text": "Action chunking is used for robust manipulation.",
        }
    ]
    pending = verify_answer(
        envelope,
        task_plan=plan,
        evidence=evidence,
        scope_item_keys=["ITEM0001"],
    )
    assert pending["status"] == "pending_semantic"
    resolved = verify_answer(
        envelope,
        task_plan=plan,
        evidence=evidence,
        scope_item_keys=["ITEM0001"],
        semantic_decisions={"claim-1": {"supported": True, "reason": "direct paraphrase"}},
    )
    assert resolved["status"] == "verified"

    out_of_scope = verify_answer(
        envelope,
        task_plan=plan,
        evidence=evidence,
        scope_item_keys=["ITEM0002"],
        semantic_decisions={"claim-1": {"supported": True, "reason": "must not override scope"}},
    )
    assert out_of_scope["hard_gate_passed"] is False
    assert out_of_scope["status"] == "failed"


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
    assert read_result["parent_context"]
    assert read_result["parent_context"]["section_path"] == "Method"
    assert "Action chunking" in read_result["parent_context"]["text"]
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


def test_scope_document_tool_returns_citable_knowledge_base_context(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    accumulator = EvidenceAccumulator()

    result, trace = execute_tool(
        tool_call("list_scope_documents", {"limit": 10}),
        library,
        ScopeContext(scoped["knowledge_base_id"], ["ITEM0001"]),
        accumulator,
    )

    assert trace["ok"] is True
    assert result["knowledge_base"]["name"] == "Core"
    assert result["knowledge_base"]["item_count"] == 1
    assert result["knowledge_base"]["full_text_count"] == 1
    assert "Knowledge base: Core" in result["documents"][0]["excerpt"]
    assert "Full text parsed: yes" in result["documents"][0]["excerpt"]
    assert "Knowledge base: Core" in accumulator.verification_evidence()[0]["support_text"]


def test_run_agentic_chat_normal_flow_persists_pruned_history(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    citation = action_citation(library)
    fake_client = FakeClient(
        [
            assistant_response(tool_calls=[tool_call("search_evidence", {"query": "Action chunking", "mode": "hybrid"})]),
            assistant_response(content=structured_answer(citation)),
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
    assert result["run_id"].startswith("run-")
    assert result["stop_reason"] == "completed"
    assert result["agent_state"]["task_plan"]["task_type"] == "factual"
    assert [event["sequence"] for event in result["agent_trace"]] == list(
        range(1, len(result["agent_trace"]) + 1)
    )
    assert any(event["event_type"] == "plan.created" for event in result["agent_trace"])
    assert any(event["event_type"] == "state.entered" for event in result["agent_trace"])
    assert result["tool_trace"][0]["tool"] == "search_evidence"
    assert result["verification"]["status"] == "verified"
    assert result["claims"][0]["claim_id"] == "claim-1"
    assert [source["citation"] for source in result["sources"]] == [citation]
    assert fake_client.completions.calls[0]["tool_choice"] == "auto"
    assert fake_client.completions.calls[0]["messages"][0]["role"] == "system"
    assert "Injected Agentic RAG Skill Bundle" in fake_client.completions.calls[0]["messages"][0]["content"]
    assert "parent_context" in fake_client.completions.calls[0]["messages"][0]["content"]

    history = load_history(library, result["conversation_id"])
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert "Action chunking" in history[1]["content"]

    restored = load_conversation(library, knowledge_base_id=scoped["knowledge_base_id"])
    assert restored["conversation_id"] == result["conversation_id"]
    assert [item["role"] for item in restored["messages"]] == ["user", "assistant"]
    assert restored["messages"][1]["sources"]
    assert restored["messages"][1]["tool_trace"][0]["tool"] == "search_evidence"
    assert restored["messages"][1]["run_id"] == result["run_id"]

    persisted_run = load_agent_run(library, result["run_id"])
    assert persisted_run["status"] == "completed"
    assert persisted_run["stop_reason"] == "completed"
    assert persisted_run["evidence_state"]["coverage"]["sq-1"]["evidence_ids"]

    index_library(library)
    assert load_agent_run(library, result["run_id"])["status"] == "completed"

    response = create_app().test_client().get(
        f"/api/library/{library['library_id']}/rag/chat/runs/{result['run_id']}",
        query_string={"after_sequence": 1},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["run_id"] == result["run_id"]
    assert payload["events"]
    assert all(event["sequence"] > 1 for event in payload["events"])


def test_answer_verification_repairs_once_and_only_returns_verified_sources(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    citation = action_citation(library)
    fake_client = FakeClient(
        [
            assistant_response(
                tool_calls=[tool_call("search_evidence", {"query": "Action chunking", "mode": "hybrid"})]
            ),
            assistant_response(content="Action chunking is useful, but this draft forgot its citation."),
            assistant_response(content=structured_answer(citation)),
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="What is action chunking used for?",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert result["stop_reason"] == "completed"
    assert result["verification"]["status"] == "verified"
    assert result["agent_state"]["controller"]["repair_calls"] == 1
    assert len(fake_client.completions.calls) == 3
    assert [source["citation"] for source in result["sources"]] == [citation]
    assert any(event["event_type"] == "verification.repair_started" for event in result["agent_trace"])


def test_answer_verification_abstains_after_single_failed_repair(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    fake_client = FakeClient(
        [
            assistant_response(
                tool_calls=[tool_call("search_evidence", {"query": "Action chunking", "mode": "hybrid"})]
            ),
            assistant_response(content="Unsupported draft without a citation."),
            assistant_response(content="Still unsupported and still uncited."),
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="What is action chunking used for?",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert result["stop_reason"] == "insufficient_evidence"
    assert result["agent_state"]["status"] == "abstained"
    assert result["agent_state"]["controller"]["repair_calls"] == 1
    assert len(fake_client.completions.calls) == 3
    assert result["sources"] == []
    assert "answer_verification_failed" in result["warnings"]


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


def test_agent_controller_skips_duplicate_tool_invocations(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    repeated_args = {"query": "Action chunking", "mode": "hybrid"}
    fake_client = FakeClient(
        [
            assistant_response(tool_calls=[tool_call("search_evidence", repeated_args, call_id="call-1")]),
            assistant_response(tool_calls=[tool_call("search_evidence", repeated_args, call_id="call-2")]),
            assistant_response(content="已有证据足以回答。"),
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="Action chunking 有什么作用？",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert result["tool_trace"][0]["ok"] is True
    assert result["tool_trace"][1]["error"] == "duplicate_invocation"
    assert result["agent_state"]["controller"]["tool_calls"] == 1
    assert result["agent_state"]["controller"]["duplicate_calls"] == 1
    assert any(event["event_type"] == "tool.skipped" for event in result["agent_trace"])


def test_comparative_controller_replans_until_coverage_or_abstains(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Compare", item_keys=["ITEM0001", "ITEM0002"])
    fake_client = FakeClient(
        [
            assistant_response(content="过早作答。"),
            assistant_response(
                tool_calls=[tool_call("search_evidence", {"query": "Action chunking", "mode": "hybrid"}, call_id="call-1")]
            ),
            assistant_response(content="仍然只覆盖一篇。"),
            assistant_response(
                tool_calls=[tool_call("search_evidence", {"query": "baseline method", "mode": "keyword"}, call_id="call-2")]
            ),
            assistant_response(content="最后仍试图作答。"),
        ]
    )

    result = run_agentic_chat(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="比较 Action chunking 与 baseline 的方法差异",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=fake_client,
    )

    assert result["agent_state"]["task_plan"]["task_type"] == "comparative"
    assert len(result["agent_state"]["task_plan"]["subquestions"]) >= 2
    assert result["stop_reason"] == "insufficient_evidence"
    assert "minimum_item_coverage_not_met" in result["warnings"]
    assert sum(event["event_type"] == "plan.revised" for event in result["agent_trace"]) == 2
    assert "TaskPlan:" in fake_client.completions.calls[0]["messages"][1]["content"]


def test_async_agent_job_persists_progress_and_can_be_cancelled(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    entered = threading.Event()
    release = threading.Event()

    class BlockingCompletions:
        def create(self, **kwargs: Any) -> Any:
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("test did not release the fake model call")
            return assistant_response(content="这条回答会被取消状态替代。")

    client = SimpleNamespace(chat=SimpleNamespace(completions=BlockingCompletions()))
    accepted = start_agentic_chat_job(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="请分析 Action chunking",
        knowledge_base_id=scoped["knowledge_base_id"],
        client=client,
    )
    assert accepted["accepted"] is True
    assert entered.wait(timeout=1)

    running_history = load_conversation(library, conversation_id=accepted["conversation_id"])
    assert [message["role"] for message in running_history["messages"]] == ["user"]
    assert running_history["active_run"]["run_id"] == accepted["run_id"]
    assert running_history["active_run"]["status"] == "running"

    cancelled = cancel_agent_chat_job(library, accepted["run_id"])
    assert cancelled["cancel_requested"] is True
    release.set()
    deadline = time.monotonic() + 3
    run = load_agent_run(library, accepted["run_id"])
    while run.get("status") == "running" and time.monotonic() < deadline:
        threading.Event().wait(0.01)
        run = load_agent_run(library, accepted["run_id"])

    assert run["status"] == "cancelled"
    assert run["stop_reason"] == "cancelled"
    assert any(event["event_type"] == "run.cancel_requested" for event in run["events"])
    assert any(event["event_type"] == "run.cancelled" for event in run["events"])
    restored = load_conversation(library, conversation_id=accepted["conversation_id"])
    assert [message["role"] for message in restored["messages"]] == ["user", "assistant"]
    assert restored["messages"][1]["run_status"] == "cancelled"
    assert restored["messages"][1]["agent_trace"]


def test_run_checkpoint_redacts_sensitive_values_and_reconciles_missing_local_job(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    prepared = prepare_agentic_chat_run(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="What is action chunking used for?",
        knowledge_base_id=scoped["knowledge_base_id"],
    )
    prepared.recorder.event(
        "diagnostic.test",
        summary="Sensitive values are filtered.",
        payload={"api_key": "sk-secret", "nested": {"authorization": "Bearer secret", "safe": "kept"}},
        visibility="diagnostic",
    )
    checkpoint = prepared.recorder.checkpoint(
        {"token": "secret-token", "safe_counter": 2}
    )
    assert checkpoint["runtime"]["token"] == "[redacted]"
    assert checkpoint["runtime"]["safe_counter"] == 2
    diagnostic = prepared.recorder.trace(include_internal=True)[-1]
    assert diagnostic["payload"]["api_key"] == "[redacted]"
    assert diagnostic["payload"]["nested"]["authorization"] == "[redacted]"
    assert diagnostic["payload"]["nested"]["safe"] == "kept"

    assert reconcile_interrupted_runs(library, active_run_ids=set()) == [prepared.recorder.run_id]
    run = load_agent_run(library, prepared.recorder.run_id)
    assert run["status"] == "interrupted"
    assert run["stop_reason"] == "interrupted"
    assert run["checkpoint"]["restart_allowed"] is True
    assert run["checkpoint"]["resume_policy"] == "restart_from_user_turn"
    assert any(event["event_type"] == "run.interrupted" for event in run["events"])
    restored = load_conversation(library, conversation_id=prepared.session.conversation_id)
    assert [message["role"] for message in restored["messages"]] == ["user", "assistant"]
    assert restored["messages"][1]["run_status"] == "interrupted"


def test_interrupted_run_can_explicitly_restart_from_original_user_turn(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    prepared = prepare_agentic_chat_run(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="What is action chunking used for?",
        knowledge_base_id=scoped["knowledge_base_id"],
    )
    reconcile_interrupted_runs(library, active_run_ids=set())

    restarted = restart_agent_chat_job(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        run_id=prepared.recorder.run_id,
        client=FakeClient([assistant_response(content="Insufficient evidence.")]),
    )
    assert restarted["run_id"] != prepared.recorder.run_id
    assert restarted["conversation_id"] == prepared.session.conversation_id
    deadline = time.monotonic() + 3
    run = load_agent_run(library, restarted["run_id"])
    while run.get("status") == "running" and time.monotonic() < deadline:
        threading.Event().wait(0.01)
        run = load_agent_run(library, restarted["run_id"])
    assert run["status"] == "abstained"
    restarted_event = next(event for event in run["events"] if event["event_type"] == "run.restarted")
    assert restarted_event["payload"]["previous_run_id"] == prepared.recorder.run_id


def test_reconcile_does_not_interrupt_live_run_owned_by_another_worker(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    prepared = prepare_agentic_chat_run(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="What is action chunking used for?",
        knowledge_base_id=scoped["knowledge_base_id"],
    )

    monkeypatch.setattr(
        "zotero_web_library.rag.agent.runtime.PROCESS_WORKER_ID",
        "worker-other-process",
    )

    assert reconcile_interrupted_runs(library) == []
    run = load_agent_run(library, prepared.recorder.run_id)
    assert run["status"] == "running"
    assert not any(event["event_type"] == "run.interrupted" for event in run["events"])


def test_complete_turn_overwrites_interruption_placeholder(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    prepared = prepare_agentic_chat_run(
        library=library,
        model_config={"model": "gpt-test", "api_key": "sk-test"},
        question="What is action chunking used for?",
        knowledge_base_id=scoped["knowledge_base_id"],
    )
    assert reconcile_interrupted_runs(library, active_run_ids=set()) == [prepared.recorder.run_id]

    complete_turn(
        library,
        prepared.session,
        turn_index=prepared.turn_index,
        answer="Final answer from surviving worker.",
        sources=[{"citation": "[ITEM0001:chunk-1]"}],
        tool_trace=[{"tool": "search_evidence"}],
        run_id=prepared.recorder.run_id,
    )

    with connect(library) as conn:
        row = conn.execute(
            """
            SELECT content, sources_json, tool_trace_json
            FROM rag_chat_messages
            WHERE conversation_id = ? AND turn_index = ? AND role = 'assistant'
            """,
            (prepared.session.conversation_id, prepared.turn_index),
        ).fetchone()

    assert row is not None
    assert row["content"] == "Final answer from surviving worker."
    assert json.loads(row["sources_json"]) == [{"citation": "[ITEM0001:chunk-1]"}]
    assert json.loads(row["tool_trace_json"]) == [{"tool": "search_evidence"}]


def test_session_scope_is_snapshotted_and_deleted_with_knowledge_base(
    zotero_fixture: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])
    unrelated = create_knowledge_base(library, name="Other", item_keys=["ITEM0002"])
    citation = action_citation(library)
    first_client = FakeClient([assistant_response(content="当前证据不足，无法回答。")])
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
            assistant_response(content=structured_answer(citation)),
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
        assert conn.execute("SELECT COUNT(*) FROM rag_agent_runs WHERE conversation_id = ?", (first["conversation_id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM rag_agent_events WHERE run_id = ?", (first["run_id"],)).fetchone()[0] == 0


def test_model_failure_finishes_agent_run(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    library = indexed_library(zotero_fixture, monkeypatch, tmp_path)
    scoped = create_knowledge_base(library, name="Core", item_keys=["ITEM0001"])

    class FailingCompletions:
        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("provider offline")

    client = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    try:
        run_agentic_chat(
            library=library,
            model_config={"model": "gpt-test", "api_key": "sk-test"},
            question="Action chunking 有什么作用？",
            knowledge_base_id=scoped["knowledge_base_id"],
            client=client,
        )
    except RuntimeError as exc:
        assert "provider offline" in str(exc)
    else:
        raise AssertionError("provider failure should propagate")

    with connect(library) as conn:
        row = conn.execute("SELECT * FROM rag_agent_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row["status"] == "failed"
    assert row["stop_reason"] == "provider_unavailable"
    assert row["current_state"] == "abstain"


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
