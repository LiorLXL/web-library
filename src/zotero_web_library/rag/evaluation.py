from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from zotero_web_library.rag.agent.loop import run_agentic_chat
from zotero_web_library.rag.chunking import TextChunk, chunk_markdown
from zotero_web_library.rag.embeddings import embed_missing_chunks
from zotero_web_library.rag.retriever import VALID_RETRIEVAL_MODES, retrieve
from zotero_web_library.rag.store import (
    connect,
    create_knowledge_base,
    ensure_store,
    insert_chunks,
    list_knowledge_bases,
    save_embedding_config,
    stable_id,
    text_hash,
    upsert_document,
)
from zotero_web_library.utils import now_iso


EVAL_SUITE_SCHEMA = "agentic-rag-eval/v1"
EVAL_CORPUS_SCHEMA = "agentic-rag-eval-corpus/v1"
EVAL_REPORT_SCHEMA = "agentic-rag-eval-report/v1"
VALID_TARGETS = {"retrieve", "agent"}
VALID_TASK_TYPES = {"factual", "summary", "comparative", "matrix", "writing", "scope", "negative"}


def load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{source} 必须包含 JSON 对象。")
    return payload


def validate_suite(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != EVAL_SUITE_SCHEMA:
        errors.append(f"schema_version 必须为 {EVAL_SUITE_SCHEMA}")
    suite_id = _required_text(payload, "suite_id", errors, prefix="suite")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases 必须是非空数组")
        cases = []

    seen: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        case_id = _required_text(case, "case_id", errors, prefix=prefix)
        _required_text(case, "question", errors, prefix=prefix)
        task_type = _required_text(case, "task_type", errors, prefix=prefix)
        if task_type and task_type not in VALID_TASK_TYPES:
            errors.append(f"{prefix}.task_type 不受支持：{task_type}")
        if case_id in seen:
            errors.append(f"case_id 重复：{case_id}")
        seen.add(case_id)
        mode = str(case.get("mode") or "auto").strip().lower()
        if mode not in VALID_RETRIEVAL_MODES:
            errors.append(f"{prefix}.mode 不受支持：{mode}")
        top_k = case.get("top_k", payload.get("default_top_k", 8))
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 30:
            errors.append(f"{prefix}.top_k 必须是 1 到 30 的整数")
        scope = case.get("scope", {})
        if not isinstance(scope, dict):
            errors.append(f"{prefix}.scope 必须是对象")
        else:
            _optional_string_list(scope, "item_keys", errors, prefix=f"{prefix}.scope")
            if scope.get("knowledge_base_name") is not None and not str(scope.get("knowledge_base_name") or "").strip():
                errors.append(f"{prefix}.scope.knowledge_base_name 不能为空字符串")
        expected = case.get("expected", {})
        if not isinstance(expected, dict):
            errors.append(f"{prefix}.expected 必须是对象")
            continue
        for key in (
            "required_item_keys",
            "any_item_keys",
            "excluded_item_keys",
            "allowed_item_keys",
            "required_warnings",
            "forbidden_warnings",
            "required_sections",
            "answer_contains",
        ):
            _optional_string_list(expected, key, errors, prefix=f"{prefix}.expected")
        for key in ("min_results", "max_results", "min_distinct_items"):
            value = expected.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                errors.append(f"{prefix}.expected.{key} 必须是非负整数")

    if errors:
        raise ValueError("评测集校验失败：\n- " + "\n- ".join(errors))
    return {"ok": True, "suite_id": suite_id, "case_count": len(cases), "schema_version": EVAL_SUITE_SCHEMA}


def validate_corpus(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != EVAL_CORPUS_SCHEMA:
        errors.append(f"schema_version 必须为 {EVAL_CORPUS_SCHEMA}")
    corpus_id = _required_text(payload, "corpus_id", errors, prefix="corpus")
    papers = payload.get("papers")
    if not isinstance(papers, list) or not papers:
        errors.append("papers 必须是非空数组")
        papers = []
    item_keys: set[str] = set()
    for index, paper in enumerate(papers):
        prefix = f"papers[{index}]"
        if not isinstance(paper, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        item_key = _required_text(paper, "item_key", errors, prefix=prefix)
        _required_text(paper, "title", errors, prefix=prefix)
        if item_key in item_keys:
            errors.append(f"item_key 重复：{item_key}")
        item_keys.add(item_key)
        sections = paper.get("sections")
        if not isinstance(sections, list) or not sections:
            errors.append(f"{prefix}.sections 必须是非空数组")
    bases = payload.get("knowledge_bases")
    if not isinstance(bases, list) or not bases:
        errors.append("knowledge_bases 必须是非空数组")
        bases = []
    base_names: set[str] = set()
    for index, base in enumerate(bases):
        prefix = f"knowledge_bases[{index}]"
        if not isinstance(base, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        name = _required_text(base, "name", errors, prefix=prefix)
        if name in base_names:
            errors.append(f"知识库名称重复：{name}")
        base_names.add(name)
        keys = _optional_string_list(base, "item_keys", errors, prefix=prefix) or []
        unknown = [key for key in keys if key not in item_keys]
        if unknown:
            errors.append(f"{prefix}.item_keys 包含未知条目：{', '.join(unknown)}")
    if errors:
        raise ValueError("合成语料校验失败：\n- " + "\n- ".join(errors))
    return {"ok": True, "corpus_id": corpus_id, "paper_count": len(papers), "schema_version": EVAL_CORPUS_SCHEMA}


def build_synthetic_library(corpus: dict[str, Any], data_path: str | Path) -> dict[str, Any]:
    validate_corpus(corpus)
    root = Path(data_path)
    root.mkdir(parents=True, exist_ok=True)
    library = {
        "library_id": str(corpus.get("library_id") or f"eval-{stable_id(str(corpus['corpus_id']))}"),
        "name": str(corpus.get("name") or corpus["corpus_id"]),
        "mode": "eval_synthetic",
        "data_path": str(root),
        "source_path": str(root),
    }
    ensure_store(library)
    save_embedding_config(
        library,
        enabled=True,
        provider="deterministic",
        model="deterministic-hash-v1",
        dim=128,
        batch_size=256,
    )
    timestamp = now_iso()
    with connect(library) as conn:
        for paper in corpus["papers"]:
            _insert_synthetic_paper(conn, library, paper, timestamp=timestamp)
        conn.commit()
    embed_result = embed_missing_chunks(library, batch_size=256)
    if not embed_result.get("ok"):
        raise RuntimeError(f"合成语料 Embedding 失败：{embed_result.get('error') or embed_result.get('status')}")
    for base in corpus["knowledge_bases"]:
        create_knowledge_base(
            library,
            name=str(base["name"]),
            description=str(base.get("description") or "Synthetic evaluation scope"),
            item_keys=base.get("item_keys") or [],
        )
    return library


def run_evaluation_suite(
    library: dict[str, Any],
    suite: dict[str, Any],
    *,
    target: str = "retrieve",
    model_config: dict[str, Any] | None = None,
    retrieve_fn: Callable[..., dict[str, Any]] = retrieve,
    agent_fn: Callable[..., dict[str, Any]] = run_agentic_chat,
) -> dict[str, Any]:
    validation = validate_suite(suite)
    clean_target = str(target or "retrieve").strip().lower()
    if clean_target not in VALID_TARGETS:
        raise ValueError(f"未知评测目标：{target}")
    if clean_target == "agent" and not model_config:
        raise ValueError("Agent 评测需要 model_config。")

    started_at = now_iso()
    run_started = time.perf_counter()
    knowledge_bases = {str(item.get("name") or ""): item for item in list_knowledge_bases(library)}
    case_reports: list[dict[str, Any]] = []
    for case in suite["cases"]:
        case_started = time.perf_counter()
        try:
            scope = case.get("scope") if isinstance(case.get("scope"), dict) else {}
            base_name = str(scope.get("knowledge_base_name") or "").strip()
            knowledge_base_id = ""
            if base_name:
                base = knowledge_bases.get(base_name)
                if not base:
                    raise ValueError(f"评测知识库不存在：{base_name}")
                knowledge_base_id = str(base.get("knowledge_base_id") or "")
            item_keys = scope.get("item_keys") if isinstance(scope.get("item_keys"), list) else None
            mode = str(case.get("mode") or "auto")
            top_k = int(case.get("top_k") or suite.get("default_top_k") or 8)
            if clean_target == "retrieve":
                raw = retrieve_fn(
                    library,
                    str(case["question"]),
                    knowledge_base_id=knowledge_base_id,
                    item_keys=item_keys,
                    mode=mode,
                    top_k=top_k,
                    include_context=False,
                )
                actual = {
                    "answer": "",
                    "sources": raw.get("results") or [],
                    "tool_trace": raw.get("tool_calls") or [],
                    "usage": {},
                    "warnings": raw.get("warnings") or [],
                }
            else:
                raw = agent_fn(
                    library=library,
                    model_config=dict(model_config or {}),
                    question=str(case["question"]),
                    knowledge_base_id=knowledge_base_id,
                    item_keys=item_keys,
                )
                actual = {
                    "answer": str(raw.get("answer") or ""),
                    "sources": raw.get("sources") or [],
                    "tool_trace": raw.get("tool_trace") or [],
                    "usage": raw.get("usage") or {},
                    "warnings": raw.get("warnings") or [],
                }
            latency_ms = round((time.perf_counter() - case_started) * 1000, 3)
            checks = evaluate_expectations(case.get("expected") or {}, actual)
            status = "passed" if all(check["passed"] for check in checks) else "failed"
            case_reports.append(
                _case_report(case, status=status, latency_ms=latency_ms, actual=actual, checks=checks)
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.perf_counter() - case_started) * 1000, 3)
            case_reports.append(
                _case_report(
                    case,
                    status="error",
                    latency_ms=latency_ms,
                    actual={"answer": "", "sources": [], "tool_trace": [], "usage": {}, "warnings": []},
                    checks=[],
                    error=str(exc),
                )
            )

    duration_ms = round((time.perf_counter() - run_started) * 1000, 3)
    return {
        "schema_version": EVAL_REPORT_SCHEMA,
        "run_id": f"eval-{uuid.uuid4().hex[:12]}",
        "suite_id": validation["suite_id"],
        "target": clean_target,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "config": {
            "library_id": str(library.get("library_id") or ""),
            "default_top_k": int(suite.get("default_top_k") or 8),
            "model": str((model_config or {}).get("model") or "") if clean_target == "agent" else "",
        },
        "summary": summarize_cases(case_reports, duration_ms=duration_ms),
        "cases": case_reports,
    }


def evaluate_expectations(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [item for item in actual.get("sources") or [] if isinstance(item, dict)]
    ranked_keys = [str(item.get("item_key") or "") for item in sources if str(item.get("item_key") or "")]
    item_set = set(ranked_keys)
    warnings = {str(item) for item in actual.get("warnings") or []}
    sections = [str(item.get("section_title") or "") for item in sources]
    answer = str(actual.get("answer") or "")
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, expected_value: Any, actual_value: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "expected": expected_value, "actual": actual_value})

    if expected.get("min_results") is not None:
        value = int(expected["min_results"])
        add("min_results", len(sources) >= value, value, len(sources))
    if expected.get("max_results") is not None:
        value = int(expected["max_results"])
        add("max_results", len(sources) <= value, value, len(sources))
    if expected.get("min_distinct_items") is not None:
        value = int(expected["min_distinct_items"])
        add("min_distinct_items", len(item_set) >= value, value, len(item_set))

    required = set(str(item) for item in expected.get("required_item_keys") or [])
    if required:
        add("required_item_keys", required.issubset(item_set), sorted(required), sorted(item_set))
    any_items = set(str(item) for item in expected.get("any_item_keys") or [])
    if any_items:
        add("any_item_keys", bool(any_items & item_set), sorted(any_items), sorted(item_set))
    excluded = set(str(item) for item in expected.get("excluded_item_keys") or [])
    if excluded:
        add("excluded_item_keys", not bool(excluded & item_set), sorted(excluded), sorted(item_set))
    allowed = set(str(item) for item in expected.get("allowed_item_keys") or [])
    if allowed:
        add("allowed_item_keys", item_set.issubset(allowed), sorted(allowed), sorted(item_set))

    required_warnings = set(str(item) for item in expected.get("required_warnings") or [])
    if required_warnings:
        add("required_warnings", required_warnings.issubset(warnings), sorted(required_warnings), sorted(warnings))
    forbidden_warnings = set(str(item) for item in expected.get("forbidden_warnings") or [])
    if forbidden_warnings:
        add("forbidden_warnings", not bool(forbidden_warnings & warnings), sorted(forbidden_warnings), sorted(warnings))

    for term in [str(item) for item in expected.get("required_sections") or []]:
        add(
            f"required_section:{term}",
            any(term.casefold() in section.casefold() for section in sections),
            term,
            sections,
        )
    for term in [str(item) for item in expected.get("answer_contains") or []]:
        add(f"answer_contains:{term}", term.casefold() in answer.casefold(), term, answer[:500])
    return checks


def summarize_cases(cases: list[dict[str, Any]], *, duration_ms: float) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for case in cases if case.get("status") == "passed")
    failed = sum(1 for case in cases if case.get("status") == "failed")
    errors = sum(1 for case in cases if case.get("status") == "error")
    latencies = sorted(float(case.get("latency_ms") or 0.0) for case in cases)
    result_counts = [len(case.get("actual", {}).get("sources") or []) for case in cases]
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": failed,
        "error_cases": errors,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "duration_ms": duration_ms,
        "mean_case_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
        "p95_case_latency_ms": round(latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)], 3) if latencies else 0.0,
        "mean_result_count": round(sum(result_counts) / len(result_counts), 3) if result_counts else 0.0,
    }


def write_evaluation_report(report: dict[str, Any], output_dir: str | Path, *, stem: str = "") -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    clean_stem = stem.strip() or f"{report.get('suite_id', 'eval')}-{report.get('target', 'retrieve')}-baseline"
    json_path = root / f"{clean_stem}.json"
    markdown_path = root / f"{clean_stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        f"# Agentic RAG 评测报告：{report.get('suite_id', '')}",
        "",
        f"- 运行 ID：`{report.get('run_id', '')}`",
        f"- 目标：`{report.get('target', '')}`",
        f"- 开始时间：`{report.get('started_at', '')}`",
        f"- 总用时：{summary.get('duration_ms', 0)} ms",
        f"- 通过率：{summary.get('passed_cases', 0)}/{summary.get('total_cases', 0)} ({float(summary.get('pass_rate', 0)):.1%})",
        f"- P95 单例延迟：{summary.get('p95_case_latency_ms', 0)} ms",
        "",
        "## 用例结果",
        "",
        "| Case | 类型 | 模式 | 状态 | 结果数 | 延迟(ms) |",
        "|---|---|---|---|---:|---:|",
    ]
    for case in report.get("cases") or []:
        actual = case.get("actual") if isinstance(case.get("actual"), dict) else {}
        lines.append(
            f"| `{case.get('case_id', '')}` | {case.get('task_type', '')} | {case.get('mode', '')} | "
            f"{case.get('status', '')} | {len(actual.get('sources') or [])} | {case.get('latency_ms', 0)} |"
        )
    problem_cases = [case for case in report.get("cases") or [] if case.get("status") != "passed"]
    if problem_cases:
        lines.extend(["", "## 未通过详情", ""])
        for case in problem_cases:
            lines.append(f"### {case.get('case_id', '')}")
            lines.append("")
            if case.get("error"):
                lines.append(f"- 运行错误：{case.get('error')}")
            for check in case.get("checks") or []:
                if not check.get("passed"):
                    lines.append(
                        f"- `{check.get('name')}`：期望 `{_compact(check.get('expected'))}`，实际 `{_compact(check.get('actual'))}`"
                    )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _insert_synthetic_paper(conn: Any, library: dict[str, Any], paper: dict[str, Any], *, timestamp: str) -> None:
    item_key = str(paper["item_key"])
    title = str(paper["title"])
    abstract = str(paper.get("abstract") or "")
    metadata_content = "\n".join(
        part
        for part in (
            f"Title: {title}",
            f"Year: {paper.get('year', '')}",
            f"Venue: {paper.get('venue', '')}",
            f"Creators: {paper.get('authors', '')}",
            f"Tags: {', '.join(str(tag) for tag in paper.get('tags') or [])}",
            f"Abstract: {abstract}" if abstract else "",
        )
        if part.split(":", 1)[-1].strip()
    )
    metadata_doc = _synthetic_document(
        library,
        paper,
        doc_id=f"doc-{stable_id(str(library['library_id']), item_key, 'metadata')}",
        source_type="zotero_metadata",
        content=metadata_content,
        chunk_count=1,
        timestamp=timestamp,
    )
    upsert_document(conn, metadata_doc)
    insert_chunks(conn, metadata_doc, [TextChunk(chunk_type="metadata", content=metadata_content, section_title="Metadata")])

    markdown_parts: list[str] = []
    for section in paper.get("sections") or []:
        markdown_parts.append(f"# {section.get('title', '')}\n{section.get('text', '')}")
    markdown = "\n\n".join(markdown_parts)
    chunks = chunk_markdown(markdown, max_chars=1200)
    fulltext_doc = _synthetic_document(
        library,
        paper,
        doc_id=f"doc-{stable_id(str(library['library_id']), item_key, 'fulltext')}",
        source_type="mineru_markdown",
        content=markdown,
        chunk_count=len(chunks),
        timestamp=timestamp,
        attachment_key=f"ATT-{item_key}",
    )
    upsert_document(conn, fulltext_doc)
    insert_chunks(conn, fulltext_doc, chunks)


def _synthetic_document(
    library: dict[str, Any],
    paper: dict[str, Any],
    *,
    doc_id: str,
    source_type: str,
    content: str,
    chunk_count: int,
    timestamp: str,
    attachment_key: str = "",
) -> dict[str, Any]:
    item_key = str(paper["item_key"])
    return {
        "doc_id": doc_id,
        "library_id": str(library["library_id"]),
        "item_key": item_key,
        "attachment_key": attachment_key,
        "source_type": source_type,
        "source_path": f"synthetic:{item_key}:{source_type}",
        "source_relpath": f"synthetic/{item_key}/{source_type}",
        "source_hash": text_hash(content),
        "source_mtime": "",
        "title": str(paper["title"]),
        "item_type": "journalArticle",
        "year": str(paper.get("year") or ""),
        "venue": str(paper.get("venue") or ""),
        "creators_text": str(paper.get("authors") or ""),
        "tags_text": ", ".join(str(tag) for tag in paper.get("tags") or []),
        "mineru_json_path": "",
        "mineru_markdown_path": "",
        "mineru_assets_dir": "",
        "parsed_at": timestamp,
        "structure_json": "{}",
        "stats_json": "{}",
        "total_chunks": chunk_count,
        "total_assets": 0,
        "total_chars": len(content),
        "index_status": "indexed",
        "error_message": "",
        "created_at": timestamp,
        "updated_at": timestamp,
        "indexed_at": timestamp,
    }


def _case_report(
    case: dict[str, Any],
    *,
    status: str,
    latency_ms: float,
    actual: dict[str, Any],
    checks: list[dict[str, Any]],
    error: str = "",
) -> dict[str, Any]:
    sources = [item for item in actual.get("sources") or [] if isinstance(item, dict)]
    compact_sources = [
        {
            key: source.get(key)
            for key in (
                "evidence_id",
                "item_key",
                "chunk_id",
                "source_type",
                "retrieval_type",
                "title",
                "section_title",
                "citation",
                "rank",
                "score",
            )
            if source.get(key) not in (None, "", {})
        }
        for source in sources
    ]
    return {
        "case_id": str(case.get("case_id") or ""),
        "question": str(case.get("question") or ""),
        "task_type": str(case.get("task_type") or ""),
        "mode": str(case.get("mode") or "auto"),
        "status": status,
        "latency_ms": latency_ms,
        "checks": checks,
        "error": error,
        "actual": {
            "answer": str(actual.get("answer") or ""),
            "sources": compact_sources,
            "tool_trace": actual.get("tool_trace") or [],
            "usage": actual.get("usage") or {},
            "warnings": actual.get("warnings") or [],
        },
    }


def _required_text(payload: dict[str, Any], key: str, errors: list[str], *, prefix: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        errors.append(f"{prefix}.{key} 不能为空")
    return value


def _optional_string_list(payload: dict[str, Any], key: str, errors: list[str], *, prefix: str) -> list[str] | None:
    if key not in payload:
        return None
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{prefix}.{key} 必须是非空字符串数组")
        return None
    return [str(item).strip() for item in value]


def _compact(value: Any, limit: int = 240) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "…"
