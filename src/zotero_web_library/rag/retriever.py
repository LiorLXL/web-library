from __future__ import annotations

import re
from math import ceil
from typing import Any

from .embeddings import embedding_config
from .query import build_query_plan, lexical_query
from .reranker import Reranker, rerank_results
from .store import connect, ensure_store, knowledge_base_item_keys
from .tools import chunk_read, keyword_search, metadata_search, semantic_search


VALID_RETRIEVAL_MODES = {"auto", "hybrid", "metadata", "keyword", "semantic"}
SCOPE_CONTEXT_FALLBACK_LIMIT = 4
SCOPE_CONTEXT_PER_ITEM_LIMIT = 2
RRF_K = 60


def retrieve(
    library: dict[str, Any],
    query: str,
    *,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    mode: str = "auto",
    top_k: int = 8,
    include_context: bool = True,
    context_window: int = 1,
    filters: dict[str, Any] | None = None,
    reranker: Reranker | None = None,
) -> dict[str, Any]:
    clean_query = str(query or "").strip()
    clean_mode = str(mode or "auto").strip().lower() or "auto"
    if clean_mode not in VALID_RETRIEVAL_MODES:
        raise ValueError(f"未知检索模式：{mode}")

    limit = _limit(top_k)
    query_plan = build_query_plan(clean_query)
    candidate_limit = min(50, max(12, limit * 4))
    pack: dict[str, Any] = {
        "query": clean_query,
        "mode": clean_mode,
        "task_type": query_plan["task_type"],
        "query_plan": query_plan,
        "knowledge_base_id": str(knowledge_base_id or "").strip(),
        "filters": filters if isinstance(filters, dict) else {},
        "results": [],
        "tool_calls": [],
        "ranking_stages": [],
        "warnings": [],
    }
    if item_keys is not None:
        pack["item_keys"] = _normalize_item_keys(item_keys)
    if not clean_query:
        pack["warnings"].append("empty_query")
        return pack

    raw_results: list[dict[str, Any]] = []
    should_run_semantic = clean_mode in {"hybrid", "semantic"} or (
        clean_mode == "auto" and _semantic_configured(library)
    )

    for planned_query in query_plan.get("queries") or []:
        query_id = str(planned_query.get("query_id") or "q0")
        planned_text = str(planned_query.get("text") or clean_query)
        search_query = str(planned_query.get("lexical_query") or lexical_query(planned_text) or planned_text)
        lineage = {
            "query_id": query_id,
            "parent_query_id": str(planned_query.get("parent_query_id") or ""),
            "query": planned_text,
            "reason": str(planned_query.get("reason") or ""),
        }

        if clean_mode in {"auto", "hybrid", "metadata"}:
            metadata = metadata_search(
                library,
                search_query,
                top_k=candidate_limit,
                knowledge_base_id=pack["knowledge_base_id"],
                item_keys=item_keys,
                filters=filters,
            )
            pack["tool_calls"].append(_tool_call("metadata_search", search_query, metadata, lineage=lineage))
            raw_results.extend(
                _tag_results(metadata.get("results", []), retrieval_type="metadata", lineage=lineage)
            )

        if clean_mode in {"auto", "hybrid", "keyword"}:
            keyword = keyword_search(
                library,
                search_query,
                top_k=candidate_limit,
                knowledge_base_id=pack["knowledge_base_id"],
                item_keys=item_keys,
                filters=filters,
            )
            pack["tool_calls"].append(_tool_call("keyword_search", search_query, keyword, lineage=lineage))
            raw_results.extend(
                _tag_results(keyword.get("results", []), retrieval_type="keyword", lineage=lineage)
            )

        if should_run_semantic:
            try:
                semantic = semantic_search(
                    library,
                    planned_text,
                    top_k=candidate_limit,
                    knowledge_base_id=pack["knowledge_base_id"],
                    item_keys=item_keys,
                    filters=filters,
                )
            except Exception as exc:  # noqa: BLE001
                semantic = {"status": "failed", "results": [], "error": str(exc)}
            status = str(semantic.get("status") or "ok")
            pack["tool_calls"].append(
                _tool_call("semantic_search", planned_text, semantic, status=status, lineage=lineage)
            )
            if status == "not_configured":
                _add_warning(pack, "semantic_search_not_configured")
            elif status == "empty_scope":
                _add_warning(pack, "semantic_search_empty_scope")
            elif status == "failed":
                _add_warning(pack, "semantic_search_failed")
            else:
                raw_results.extend(
                    _tag_results(semantic.get("results", []), retrieval_type="semantic", lineage=lineage)
                )

    if raw_results:
        raw_results = _rank_rrf(raw_results)
        pack["ranking_stages"].append(
            {"stage": "rrf", "status": "ok", "k": RRF_K, "result_count": len(raw_results)}
        )
        raw_results, reranker_trace, reranker_warning = rerank_results(
            query_plan.get("normalized_query") or clean_query,
            raw_results,
            reranker=reranker,
        )
        pack["ranking_stages"].append(reranker_trace)
        if reranker_warning:
            _add_warning(pack, reranker_warning)
        raw_results = _select_diverse_results(
            raw_results,
            top_k=limit,
            task_type=str(query_plan.get("task_type") or "factual"),
        )
        pack["ranking_stages"].append(
            {
                "stage": "diversity",
                "status": "ok",
                "strategy": "comparative_coverage_mmr" if query_plan.get("task_type") == "comparative" else "mmr",
                "result_count": len(raw_results),
            }
        )

    if not raw_results and clean_mode in {"auto", "hybrid", "keyword"}:
        fallback = _scope_context_results(
            library,
            knowledge_base_id=pack["knowledge_base_id"],
            item_keys=item_keys,
            top_k=min(limit, SCOPE_CONTEXT_FALLBACK_LIMIT),
        )
        if fallback:
            raw_results.extend(_tag_results(fallback, retrieval_type="scope_context"))
            pack["tool_calls"].append(
                {
                    "tool": "scope_context_read",
                    "query": query_plan.get("normalized_query") or clean_query,
                    "result_count": len(fallback),
                    "status": "fallback",
                }
            )
            _add_warning(pack, "keyword_no_match_used_scope_context")

    evidence = _build_evidence(
        library,
        raw_results,
        include_context=bool(include_context),
        context_window=context_window,
        top_k=limit,
    )
    pack["results"] = evidence
    if not evidence:
        _add_warning(pack, "no_evidence_found")
    return pack


def _limit(value: Any, default: int = 8, maximum: int = 30) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _normalize_item_keys(item_keys: list[str] | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in item_keys or []:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(key)
    return values


def _scoped_item_keys(
    library: dict[str, Any],
    *,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> list[str]:
    requested = _normalize_item_keys(item_keys)
    clean_knowledge_base_id = str(knowledge_base_id or "").strip()
    if clean_knowledge_base_id:
        base_keys = knowledge_base_item_keys(library, clean_knowledge_base_id)
        if requested:
            allowed = set(base_keys)
            return [key for key in requested if key in allowed]
        return base_keys
    return requested


def _scope_context_results(
    library: dict[str, Any],
    *,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    scoped_keys = _scoped_item_keys(library, knowledge_base_id=knowledge_base_id, item_keys=item_keys)
    if not scoped_keys:
        return []
    ensure_store(library)
    placeholders = ",".join("?" for _ in scoped_keys)
    with connect(library) as conn:
        rows = conn.execute(
            f"""
            SELECT
              c.chunk_id,
              c.doc_id,
              c.item_key,
              c.attachment_key,
              c.chunk_type,
              c.section_title,
              c.section_path,
              c.parent_chunk_id,
              c.chunk_index,
              c.content,
              c.excerpt,
              c.estimated_page,
              d.title,
              d.creators_text,
              d.year,
              d.venue,
              d.source_type AS document_source_type
            FROM rag_chunks c
            JOIN rag_documents d ON d.doc_id = c.doc_id
            WHERE c.item_key IN ({placeholders})
              AND c.content != ''
            ORDER BY
              CASE d.source_type
                WHEN 'mineru_markdown' THEN 0
                WHEN 'note' THEN 1
                WHEN 'zotero_metadata' THEN 2
                ELSE 3
              END,
              CASE c.chunk_type
                WHEN 'metadata' THEN 3
                WHEN 'heading' THEN 1
                ELSE 0
              END,
              c.chunk_index
            LIMIT ?
            """,
            [*scoped_keys, min(_limit(top_k), SCOPE_CONTEXT_FALLBACK_LIMIT * max(1, len(scoped_keys)))],
        ).fetchall()
    results: list[dict[str, Any]] = []
    per_item_counts: dict[str, int] = {}
    for row in rows:
        item = dict(row)
        item_key = str(item.get("item_key") or "")
        current_count = per_item_counts.get(item_key, 0)
        if current_count >= SCOPE_CONTEXT_PER_ITEM_LIMIT:
            continue
        per_item_counts[item_key] = current_count + 1
        item["snippet"] = item.get("excerpt", "")
        item["score"] = None
        item["source"] = {
            "chunk_id": item.get("chunk_id", ""),
            "doc_id": item.get("doc_id", ""),
            "item_key": item.get("item_key", ""),
            "attachment_key": item.get("attachment_key", ""),
            "title": item.get("title", ""),
            "authors_text": item.get("creators_text", ""),
            "year": item.get("year", ""),
            "venue": item.get("venue", ""),
            "source_type": item.get("document_source_type", ""),
            "section_title": item.get("section_title", ""),
            "section_path": item.get("section_path", ""),
            "parent_chunk_id": item.get("parent_chunk_id", ""),
            "estimated_page": item.get("estimated_page"),
            "excerpt": item.get("excerpt", ""),
        }
        results.append(item)
        if len(results) >= min(_limit(top_k), SCOPE_CONTEXT_FALLBACK_LIMIT):
            break
    return results


def _tool_call(
    tool: str,
    query: str,
    result: dict[str, Any],
    *,
    status: str = "",
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "tool": tool,
        "query": query,
        "result_count": len(result.get("results") or []),
    }
    if lineage:
        payload["query_id"] = str(lineage.get("query_id") or "")
        payload["parent_query_id"] = str(lineage.get("parent_query_id") or "")
    if status:
        payload["status"] = status
    if result.get("error"):
        payload["error"] = str(result.get("error"))
    return payload


def _tag_results(
    results: list[dict[str, Any]],
    *,
    retrieval_type: str,
    lineage: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for rank, result in enumerate(results, start=1):
        item = dict(result)
        item["retrieval_type"] = retrieval_type
        item["retriever_rank"] = rank
        item["query_id"] = str((lineage or {}).get("query_id") or "q0")
        item["query_text"] = str((lineage or {}).get("query") or "")
        item["parent_query_id"] = str((lineage or {}).get("parent_query_id") or "")
        tagged.append(item)
    return tagged


def _build_evidence(
    library: dict[str, Any],
    raw_results: list[dict[str, Any]],
    *,
    include_context: bool,
    context_window: int,
    top_k: int,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    for raw in raw_results:
        chunk_id = str(raw.get("chunk_id") or "").strip()
        if chunk_id and chunk_id in seen_chunks:
            continue
        if chunk_id:
            seen_chunks.add(chunk_id)
        entry = _evidence_from_result(
            library,
            raw,
            rank=len(evidence) + 1,
            include_context=include_context,
            context_window=context_window,
        )
        evidence.append(entry)
        if len(evidence) >= top_k:
            break
    return evidence


def _semantic_configured(library: dict[str, Any]) -> bool:
    config = embedding_config(library)
    return bool(config.get("enabled") and config.get("provider") and config.get("model"))


def _rank_rrf(raw_results: list[dict[str, Any]], *, rrf_k: int = RRF_K) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for raw in raw_results:
        chunk_id = str(raw.get("chunk_id") or "")
        if not chunk_id:
            continue
        retrieval_type = str(raw.get("retrieval_type") or "")
        query_id = str(raw.get("query_id") or "q0")
        rank = max(1, int(raw.get("retriever_rank") or 1))
        contribution = 1.0 / (max(1, int(rrf_k)) + rank)
        current = grouped.setdefault(chunk_id, dict(raw))
        scores = dict(current.get("scores") or {})
        if retrieval_type == "keyword":
            scores["keyword_score"] = raw.get("score")
        elif retrieval_type == "semantic":
            scores["semantic_score"] = raw.get("semantic_score", raw.get("score"))
        scores["rrf_score"] = float(scores.get("rrf_score") or 0.0) + contribution
        current["scores"] = scores
        retrieval_types = set(str(item) for item in current.get("retrieval_types", []) if str(item))
        retrieval_types.add(retrieval_type)
        current["retrieval_types"] = sorted(retrieval_types)
        lineage = list(current.get("query_lineage") or [])
        lineage.append(
            {
                "query_id": query_id,
                "parent_query_id": str(raw.get("parent_query_id") or ""),
                "query": str(raw.get("query_text") or ""),
                "retriever": retrieval_type,
                "rank": rank,
                "rrf_contribution": contribution,
            }
        )
        current["query_lineage"] = lineage
        if retrieval_type == "semantic" and not current.get("snippet"):
            current["snippet"] = raw.get("snippet", "")

    ranked: list[dict[str, Any]] = []
    for item in grouped.values():
        scores = dict(item.get("scores") or {})
        rrf_score = float(scores.get("rrf_score") or 0.0)
        item["scores"] = {**scores, "rrf_score": rrf_score}
        item["score"] = rrf_score
        if len(item.get("retrieval_types") or []) > 1:
            item["retrieval_type"] = "hybrid"
        ranked.append(item)
    ranked.sort(key=lambda item: float((item.get("scores") or {}).get("rrf_score") or 0.0), reverse=True)
    return ranked


def _select_diverse_results(
    ranked: list[dict[str, Any]],
    *,
    top_k: int,
    task_type: str,
) -> list[dict[str, Any]]:
    limit = _limit(top_k)
    if len(ranked) <= 1:
        return ranked[:limit]

    selected: list[dict[str, Any]] = []
    remaining = list(ranked)
    unique_items = list(dict.fromkeys(str(item.get("item_key") or "") for item in ranked if str(item.get("item_key") or "")))

    if task_type == "comparative" and len(unique_items) > 1:
        coverage_target = min(limit, max(2, min(3, len(unique_items))))
        for item_key in unique_items[:coverage_target]:
            candidate = next((item for item in remaining if str(item.get("item_key") or "") == item_key), None)
            if candidate is None:
                continue
            selected.append(_with_selection_score(candidate, 1.0, "comparative_item_coverage"))
            remaining.remove(candidate)

    per_item_cap = limit
    if len(unique_items) > 1:
        per_item_cap = max(2, ceil(limit / 2)) if task_type == "comparative" else max(2, ceil(limit * 0.7))

    while remaining and len(selected) < limit:
        counts: dict[str, int] = {}
        for item in selected:
            key = str(item.get("item_key") or "")
            counts[key] = counts.get(key, 0) + 1

        eligible = [
            item
            for item in remaining
            if counts.get(str(item.get("item_key") or ""), 0) < per_item_cap
        ]
        if not eligible:
            eligible = remaining

        best: dict[str, Any] | None = None
        best_score = float("-inf")
        for candidate in eligible:
            relevance = _normalized_relevance(candidate, ranked)
            redundancy = max((_result_similarity(candidate, chosen) for chosen in selected), default=0.0)
            same_item_penalty = 0.0
            item_key = str(candidate.get("item_key") or "")
            if item_key and counts.get(item_key, 0):
                same_item_penalty = min(0.18, counts[item_key] * 0.06)
            selection_score = 0.78 * relevance - 0.16 * redundancy - same_item_penalty
            if selection_score > best_score:
                best = candidate
                best_score = selection_score
        if best is None:
            break
        selected.append(_with_selection_score(best, best_score, "mmr"))
        remaining.remove(best)
    return selected


def _normalized_relevance(item: dict[str, Any], ranked: list[dict[str, Any]]) -> float:
    values = [float(candidate.get("score") or 0.0) for candidate in ranked]
    low = min(values, default=0.0)
    high = max(values, default=0.0)
    value = float(item.get("score") or 0.0)
    if high <= low:
        return 1.0 - (ranked.index(item) / max(1, len(ranked)))
    return (value - low) / (high - low)


def _result_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = _result_tokens(left)
    right_tokens = _result_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    lexical = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    same_doc = bool(left.get("doc_id") and left.get("doc_id") == right.get("doc_id"))
    adjacent = False
    if same_doc and left.get("chunk_index") is not None and right.get("chunk_index") is not None:
        adjacent = abs(int(left["chunk_index"]) - int(right["chunk_index"])) <= 1
    return min(1.0, lexical + (0.25 if same_doc else 0.0) + (0.25 if adjacent else 0.0))


def _result_tokens(item: dict[str, Any]) -> set[str]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    value = " ".join(
        str(part or "")
        for part in (
            source.get("title"),
            item.get("section_path") or item.get("section_title"),
            item.get("snippet") or item.get("excerpt") or item.get("content"),
        )
    ).casefold()
    return set(re.findall(r"[a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", value))


def _with_selection_score(item: dict[str, Any], score: float, reason: str) -> dict[str, Any]:
    payload = dict(item)
    scores = dict(payload.get("scores") or {})
    scores["selection_score"] = float(score)
    payload["scores"] = scores
    payload["selection_reason"] = reason
    return payload


def _add_warning(pack: dict[str, Any], warning: str) -> None:
    warnings = pack.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)


def _evidence_from_result(
    library: dict[str, Any],
    raw: dict[str, Any],
    *,
    rank: int,
    include_context: bool,
    context_window: int,
) -> dict[str, Any]:
    source = dict(raw.get("source") or {})
    item_key = str(raw.get("item_key") or source.get("item_key") or "").strip()
    chunk_id = str(raw.get("chunk_id") or source.get("chunk_id") or "").strip()
    chunk_type = str(raw.get("chunk_type") or "").strip()
    source_type = _evidence_source_type(raw)
    text = _result_text(library, raw, include_context=include_context, context_window=context_window)
    evidence_id = f"ev-{rank}"
    return {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "retrieval_type": str(raw.get("retrieval_type") or ""),
        "item_key": item_key,
        "attachment_key": str(raw.get("attachment_key") or source.get("attachment_key") or ""),
        "doc_id": str(raw.get("doc_id") or source.get("doc_id") or ""),
        "chunk_id": chunk_id,
        "chunk_type": chunk_type,
        "document_source_type": str(source.get("source_type") or ""),
        "title": str(source.get("title") or ""),
        "authors_text": str(source.get("authors_text") or ""),
        "year": str(source.get("year") or ""),
        "venue": str(source.get("venue") or ""),
        "section_title": str(raw.get("section_title") or source.get("section_title") or ""),
        "section_path": str(raw.get("section_path") or source.get("section_path") or ""),
        "parent_chunk_id": str(raw.get("parent_chunk_id") or source.get("parent_chunk_id") or ""),
        "estimated_page": raw.get("estimated_page", source.get("estimated_page")),
        "text": text,
        "excerpt": str(raw.get("snippet") or raw.get("excerpt") or source.get("excerpt") or "")[:700],
        "score": raw.get("score"),
        "scores": raw.get("scores") or {},
        "query_lineage": raw.get("query_lineage") or [],
        "selection_reason": str(raw.get("selection_reason") or ""),
        "rank": rank,
        "citation": _citation(source_type=source_type, item_key=item_key, chunk_id=chunk_id),
    }


def _evidence_source_type(raw: dict[str, Any]) -> str:
    chunk_type = str(raw.get("chunk_type") or "").strip()
    if chunk_type == "metadata":
        return "metadata"
    if chunk_type in {"note", "annotation", "writing"}:
        return "note"
    return "chunk"


def _result_text(
    library: dict[str, Any],
    raw: dict[str, Any],
    *,
    include_context: bool,
    context_window: int,
) -> str:
    if str(raw.get("retrieval_type") or "") == "scope_context":
        return str(raw.get("content") or raw.get("excerpt") or (raw.get("source") or {}).get("excerpt") or "")[:1800]
    if include_context and raw.get("chunk_id"):
        context = chunk_read(library, str(raw.get("chunk_id")), window_size=max(0, min(int(context_window or 0), 3)))
        parent = context.get("parent") if isinstance(context.get("parent"), dict) else {}
        parent_content = str(parent.get("content") or "").strip()
        if parent_content:
            return parent_content[:6000]
        chunks = context.get("chunks") or []
        content = "\n\n".join(str(chunk.get("content") or "").strip() for chunk in chunks if str(chunk.get("content") or "").strip())
        if content:
            return content[:3600]
    return str(raw.get("snippet") or raw.get("excerpt") or (raw.get("source") or {}).get("excerpt") or "")[:1800]


def _citation(*, source_type: str, item_key: str, chunk_id: str) -> str:
    key = item_key or "unknown"
    if source_type == "metadata":
        return f"[{key}:metadata]"
    if chunk_id:
        return f"[{key}:{chunk_id}]"
    return f"[{key}:evidence]"
