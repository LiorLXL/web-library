from __future__ import annotations

import json
from pathlib import Path

import pytest

from zotero_web_library.rag import build_query_plan, chunk_read, index_library, keyword_search, retrieve
from zotero_web_library.rag.chunking import chunk_markdown
from zotero_web_library.rag.reranker import rerank_results
from zotero_web_library.rag.retriever import _rank_rrf, _select_diverse_results
from zotero_web_library.rag.store import CHUNK_CONTENT_VERSION, connect, create_knowledge_base
from zotero_web_library.sources import create_local_copy


def _write_structured_mineru_fixture(library: dict[str, str]) -> None:
    root = Path(library["data_path"]) / "mineru-results"
    root.mkdir(parents=True, exist_ok=True)
    stem = "20260714010101-ATTACH01"
    markdown = """# Paper
## Abstract
Robot catalyst planning improves embodied control.

## Method
Action chunking is used for robust manipulation.

### Experiments and Results
The approach improves success rate on Benchmark-X.

| Model | Score |
|---|---|
| OpenVLA | 91 |

Figure 1: Success rate by task.

## References
[1] Example reference.
"""
    payload = {
        "schema": "web-library.mineru-parse-result/v1",
        "library_id": library["library_id"],
        "item_key": "ITEM0001",
        "attachment": {"key": "ATTACH01", "title": "paper.pdf"},
        "parsed_at": "2026-07-14T01:01:01Z",
    }
    (root / f"{stem}.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / f"{stem}.md").write_text(markdown, encoding="utf-8")


def test_structured_markdown_chunks_preserve_hierarchy_and_types() -> None:
    chunks = chunk_markdown(
        """# Paper
## Abstract
An abstract.
## Method
A method.
### Experimental Results
| Model | Score |
|---|---|
Figure 1: Results.
## References
[1] Source.
"""
    )

    abstract = next(chunk for chunk in chunks if chunk.content == "An abstract.")
    method = next(chunk for chunk in chunks if chunk.content == "A method.")
    table = next(chunk for chunk in chunks if "| Model | Score |" in chunk.content)
    figure = next(chunk for chunk in chunks if chunk.content.startswith("Figure 1"))
    reference = next(chunk for chunk in chunks if chunk.content == "[1] Source.")

    assert (abstract.chunk_type, abstract.section_path) == ("abstract", "Paper > Abstract")
    assert (method.chunk_type, method.section_path) == ("method", "Paper > Method")
    assert table.chunk_type == "table"
    assert table.section_path == "Paper > Method > Experimental Results"
    assert figure.chunk_type == "figure_caption"
    assert reference.chunk_type == "references"


def test_index_builds_parent_context_and_versions_chunks(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    _write_structured_mineru_fixture(library)

    status = index_library(library)
    result = keyword_search(library, "Action chunking")
    hit = result["results"][0]
    context = chunk_read(library, hit["chunk_id"], window_size=0)

    assert hit["parent_chunk_id"].startswith("parent-")
    assert hit["section_path"] == "Paper > Method"
    assert context["parent"]["parent_chunk_id"] == hit["parent_chunk_id"]
    assert "Action chunking" in context["parent"]["content"]
    assert context["parent"]["section_path"] == "Paper > Method"
    assert status["content_version"] == CHUNK_CONTENT_VERSION
    assert status["requires_reindex"] is False
    with connect(library) as conn:
        types = {str(row[0]) for row in conn.execute("SELECT DISTINCT chunk_type FROM rag_chunks")}
    assert {"abstract", "method", "results", "table", "figure_caption", "references"} <= types


def test_query_plan_classifies_and_decomposes_comparative_query() -> None:
    plan = build_query_plan("请问比较 AlphaNet 和 BetaNet 的方法与实验结果是什么？")

    assert plan["task_type"] == "comparative"
    assert plan["normalized_query"].startswith("比较 AlphaNet")
    assert len(plan["queries"]) >= 3
    assert [item["query_id"] for item in plan["queries"]] == [f"q{index}" for index in range(len(plan["queries"]))]
    assert all(item["lexical_query"] for item in plan["queries"])
    assert any(item["reason"] == "task_decomposition" for item in plan["queries"])


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("总结这些论文的主要贡献", "summary"),
        ("生成文献矩阵字段", "matrix"),
        ("写一段相关工作综述", "writing"),
        ("列出知识库有哪些文献", "scope"),
        ("这是一个什么知识库", "scope"),
        ("这个知识库里的三篇论文是什么关系", "comparative"),
        ("这是一个什么知识库，它里面的三篇论文有什么关系", "comparative"),
        ("OpenVLA 的作者是谁", "factual"),
    ],
)
def test_query_plan_recognizes_supported_task_types(query: str, expected: str) -> None:
    assert build_query_plan(query)["task_type"] == expected


def test_rrf_uses_standard_rank_contributions_and_keeps_lineage() -> None:
    ranked = _rank_rrf(
        [
            {"chunk_id": "a", "item_key": "A", "retrieval_type": "keyword", "retriever_rank": 1, "query_id": "q0", "query_text": "alpha"},
            {"chunk_id": "b", "item_key": "B", "retrieval_type": "keyword", "retriever_rank": 2, "query_id": "q0", "query_text": "alpha"},
            {"chunk_id": "a", "item_key": "A", "retrieval_type": "semantic", "retriever_rank": 1, "query_id": "q1", "query_text": "method"},
        ]
    )

    assert [item["chunk_id"] for item in ranked] == ["a", "b"]
    assert ranked[0]["scores"]["rrf_score"] == pytest.approx(2 / 61)
    assert ranked[1]["scores"]["rrf_score"] == pytest.approx(1 / 62)
    assert {entry["retriever"] for entry in ranked[0]["query_lineage"]} == {"keyword", "semantic"}


def test_comparative_selection_covers_multiple_items() -> None:
    ranked = [
        {"chunk_id": "a1", "item_key": "A", "doc_id": "A", "chunk_index": 1, "score": 1.0, "snippet": "same method"},
        {"chunk_id": "a2", "item_key": "A", "doc_id": "A", "chunk_index": 2, "score": 0.9, "snippet": "same method details"},
        {"chunk_id": "b1", "item_key": "B", "doc_id": "B", "chunk_index": 1, "score": 0.8, "snippet": "different baseline"},
    ]

    selected = _select_diverse_results(ranked, top_k=2, task_type="comparative")

    assert {item["item_key"] for item in selected} == {"A", "B"}
    assert all(item["selection_reason"] == "comparative_item_coverage" for item in selected)


def test_optional_reranker_reorders_and_degrades_without_losing_results() -> None:
    class WorkingReranker:
        provider_name = "test"
        model = "cross-encoder-test"

        def rerank(self, query: str, documents: list[str]) -> list[float]:
            assert query == "robot"
            return [0.1, 0.9]

    class FailingReranker(WorkingReranker):
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            raise RuntimeError("reranker unavailable")

    original = [
        {"chunk_id": "a", "score": 1.0, "snippet": "first", "scores": {"rrf_score": 0.3}},
        {"chunk_id": "b", "score": 0.5, "snippet": "second", "scores": {"rrf_score": 0.2}},
    ]
    reordered, trace, warning = rerank_results("robot", original, reranker=WorkingReranker())
    degraded, failed_trace, failed_warning = rerank_results("robot", original, reranker=FailingReranker())

    assert [item["chunk_id"] for item in reordered] == ["b", "a"]
    assert trace["status"] == "ok" and warning == ""
    assert degraded == original
    assert failed_trace["status"] == "failed"
    assert failed_warning == "reranker_failed"


def test_metadata_filters_are_intersected_with_search_scope(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    index_library(library)

    matched = keyword_search(
        library,
        "OpenVLA",
        filters={"year_from": 2024, "year_to": 2024, "authors": ["Kim"], "venues": ["arXiv"], "chunk_types": ["metadata"]},
    )
    excluded_by_year = keyword_search(library, "OpenVLA", filters={"year_from": 2025})
    excluded_by_item = keyword_search(library, "OpenVLA", item_keys=["ITEM0001"], filters={"item_keys": ["ITEM0002"]})
    unrelated = create_knowledge_base(library, name="Unrelated", item_keys=["ITEM0002"])
    excluded_by_kb = keyword_search(
        library,
        "OpenVLA",
        knowledge_base_id=unrelated["knowledge_base_id"],
        filters={"item_keys": ["ITEM0001"]},
    )

    assert matched["results"]
    assert {item["item_key"] for item in matched["results"]} == {"ITEM0001"}
    assert excluded_by_year["results"] == []
    assert excluded_by_item["results"] == []
    assert excluded_by_kb["results"] == []


def test_retrieve_exposes_query_lineage_rrf_and_parent_answer_context(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    _write_structured_mineru_fixture(library)
    index_library(library)

    pack = retrieve(library, "Action chunking method", mode="keyword", top_k=3)

    assert pack["task_type"] == "factual"
    assert pack["query_plan"]["queries"]
    assert any(stage["stage"] == "rrf" for stage in pack["ranking_stages"])
    assert pack["results"]
    result = pack["results"][0]
    assert result["scores"]["rrf_score"] > 0
    assert result["query_lineage"]
    assert result["parent_chunk_id"].startswith("parent-")
    assert "Action chunking" in result["text"]


def test_retrieve_keeps_local_results_when_optional_reranker_fails(zotero_fixture: Path, monkeypatch, tmp_path: Path) -> None:
    class FailingReranker:
        provider_name = "test"
        model = "cross-encoder-test"

        def rerank(self, query: str, documents: list[str]) -> list[float]:
            raise RuntimeError("temporary reranker outage")

    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    _write_structured_mineru_fixture(library)
    index_library(library)

    pack = retrieve(library, "Action chunking", mode="keyword", top_k=3, reranker=FailingReranker())

    assert pack["results"]
    assert "reranker_failed" in pack["warnings"]
    trace = next(stage for stage in pack["ranking_stages"] if stage["stage"] == "reranker")
    assert trace["status"] == "failed"
    assert trace["error"] == "temporary reranker outage"
