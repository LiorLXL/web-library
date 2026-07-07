from __future__ import annotations

import re
from typing import Any

from .store import connect, ensure_store, knowledge_base_item_keys
from .tools import chunk_read, keyword_search, metadata_search


VALID_RETRIEVAL_MODES = {"auto", "hybrid", "metadata", "keyword", "semantic"}
SCOPE_CONTEXT_FALLBACK_LIMIT = 4
SCOPE_CONTEXT_PER_ITEM_LIMIT = 2


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
) -> dict[str, Any]:
    clean_query = str(query or "").strip()
    clean_mode = str(mode or "auto").strip().lower() or "auto"
    if clean_mode not in VALID_RETRIEVAL_MODES:
        raise ValueError(f"未知检索模式：{mode}")

    limit = _limit(top_k)
    pack: dict[str, Any] = {
        "query": clean_query,
        "mode": clean_mode,
        "knowledge_base_id": str(knowledge_base_id or "").strip(),
        "results": [],
        "tool_calls": [],
        "warnings": [],
    }
    if item_keys is not None:
        pack["item_keys"] = _normalize_item_keys(item_keys)
    if not clean_query:
        pack["warnings"].append("empty_query")
        return pack

    search_query = _search_query(clean_query)
    raw_results: list[dict[str, Any]] = []
    if clean_mode in {"auto", "hybrid", "metadata"}:
        metadata = metadata_search(
            library,
            search_query,
            top_k=limit,
            knowledge_base_id=pack["knowledge_base_id"],
            item_keys=item_keys,
        )
        pack["tool_calls"].append(_tool_call("metadata_search", search_query, metadata))
        raw_results.extend(_tag_results(metadata.get("results", []), retrieval_type="metadata"))

    if clean_mode in {"auto", "hybrid", "keyword"}:
        keyword = keyword_search(
            library,
            search_query,
            top_k=limit,
            knowledge_base_id=pack["knowledge_base_id"],
            item_keys=item_keys,
        )
        pack["tool_calls"].append(_tool_call("keyword_search", search_query, keyword))
        raw_results.extend(_tag_results(keyword.get("results", []), retrieval_type="keyword"))

    if clean_mode in {"hybrid", "semantic"}:
        pack["warnings"].append("semantic_search_not_configured")
        pack["tool_calls"].append(
            {
                "tool": "semantic_search",
                "query": search_query,
                "result_count": 0,
                "status": "not_configured",
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
                    "query": search_query,
                    "result_count": len(fallback),
                    "status": "fallback",
                }
            )
            pack["warnings"].append("keyword_no_match_used_scope_context")

    evidence = _build_evidence(
        library,
        raw_results,
        include_context=bool(include_context),
        context_window=context_window,
        top_k=limit,
    )
    pack["results"] = evidence
    if not evidence:
        pack["warnings"].append("no_evidence_found")
    return pack


def _limit(value: Any, default: int = 8, maximum: int = 30) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _search_query(query: str) -> str:
    ascii_terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", query)
    if ascii_terms:
        return " ".join(ascii_terms[:8])
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    if cjk_terms:
        return " ".join(cjk_terms[:6])
    cleaned = re.sub(r"[^\w\s-]+", " ", query, flags=re.UNICODE)
    return " ".join(cleaned.split()) or query


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
            "estimated_page": item.get("estimated_page"),
            "excerpt": item.get("excerpt", ""),
        }
        results.append(item)
        if len(results) >= min(_limit(top_k), SCOPE_CONTEXT_FALLBACK_LIMIT):
            break
    return results


def _tool_call(tool: str, query: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": tool,
        "query": query,
        "result_count": len(result.get("results") or []),
    }


def _tag_results(results: list[dict[str, Any]], *, retrieval_type: str) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for result in results:
        item = dict(result)
        item["retrieval_type"] = retrieval_type
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
        "estimated_page": raw.get("estimated_page", source.get("estimated_page")),
        "text": text,
        "excerpt": str(raw.get("snippet") or raw.get("excerpt") or source.get("excerpt") or "")[:700],
        "score": raw.get("score"),
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
