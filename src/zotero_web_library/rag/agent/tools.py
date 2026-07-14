from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from zotero_web_library.rag.retriever import retrieve as rag_retrieve
from zotero_web_library.rag.store import connect, ensure_store
from zotero_web_library.rag.tools import chunk_read

from .evidence import EvidenceAccumulator


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_evidence",
            "description": "在当前知识库范围内检索证据。返回证据摘要列表；需要完整上下文时再用 read_chunk_context。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询，可用中文或英文关键词"},
                    "mode": {
                        "type": "string",
                        "enum": ["hybrid", "keyword", "semantic", "metadata"],
                        "description": "hybrid=关键词+语义融合; keyword=全文BM25; semantic=向量; metadata=题录字段",
                    },
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "description": "返回条数，默认 8"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_chunk_context",
            "description": "读取指定 chunk 及相邻上下文的完整文本，用于核实细节、方法、实验结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string", "description": "来自 search_evidence 结果的 chunk_id"},
                    "window_size": {"type": "integer", "minimum": 0, "maximum": 3, "description": "前后各取几个相邻 chunk，默认 1"},
                },
                "required": ["chunk_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scope_documents",
            "description": "列出当前知识库范围内的文献清单（标题/作者/年份/是否有全文解析），用于了解范围或规划检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "最多返回条数，默认 50"}
                },
            },
        },
    },
]


@dataclass(slots=True)
class ScopeContext:
    knowledge_base_id: str
    item_keys: list[str]


def execute_tool(
    call: Any,
    library: dict[str, Any],
    scope: ScopeContext,
    accumulator: EvidenceAccumulator,
) -> tuple[dict[str, Any], dict[str, Any]]:
    name = _tool_name(call)
    args_payload = _tool_arguments(call)
    try:
        args = json.loads(args_payload or "{}")
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be a JSON object")
    except Exception as exc:  # noqa: BLE001
        result = {"error": "invalid_tool_arguments", "message": str(exc)}
        return result, summarize_tool_trace(name or "unknown", {}, result)

    try:
        if name == "search_evidence":
            result = search_evidence(library, scope, accumulator, args)
        elif name == "read_chunk_context":
            result = read_context_scoped(library, scope, accumulator, args)
        elif name == "list_scope_documents":
            result = list_scope_documents(library, scope, args)
        else:
            result = {"error": "unknown_tool", "message": f"unknown tool: {name}"}
    except Exception as exc:  # noqa: BLE001
        result = {"error": "tool_failed", "message": str(exc)}
    return result, summarize_tool_trace(name or "unknown", args, result)


def search_evidence(
    library: dict[str, Any],
    scope: ScopeContext,
    accumulator: EvidenceAccumulator,
    args: dict[str, Any],
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "invalid_tool_arguments", "message": "query is required"}
    raw = rag_retrieve(
        library,
        query,
        knowledge_base_id="",
        item_keys=scope.item_keys,
        mode=str(args.get("mode") or "hybrid"),
        top_k=_clamp(args.get("top_k", 8), 1, 20, default=8),
        include_context=False,
    )
    slim = accumulator.register(raw.get("results") or [], include_text=False, excerpt_limit=300)
    return {
        "mode": raw.get("mode") or args.get("mode") or "hybrid",
        "count": len(slim),
        "results": slim,
        "warnings": raw.get("warnings") or [],
    }


def read_context_scoped(
    library: dict[str, Any],
    scope: ScopeContext,
    accumulator: EvidenceAccumulator,
    args: dict[str, Any],
) -> dict[str, Any]:
    chunk_id = str(args.get("chunk_id") or "").strip()
    if not chunk_id:
        return {"error": "invalid_tool_arguments", "message": "chunk_id is required"}
    context = chunk_read(library, chunk_id, window_size=_clamp(args.get("window_size", 1), 0, 3, default=1))
    chunks = context.get("chunks") or []
    if not chunks:
        return {"error": "chunk_not_found", "message": f"chunk not found: {chunk_id}", "chunk_id": chunk_id}

    allowed = set(scope.item_keys)
    unauthorized = [str(chunk.get("chunk_id") or "") for chunk in chunks if str(chunk.get("item_key") or "") not in allowed]
    if unauthorized:
        return {
            "error": "chunk_out_of_scope",
            "message": "requested chunk context is outside the current session scope",
            "chunk_ids": unauthorized,
        }

    source = context.get("source") if isinstance(context.get("source"), dict) else {}
    raw_results = [_raw_from_chunk(chunk, source) for chunk in chunks]
    slim = accumulator.register(raw_results, include_text=True, excerpt_limit=300, text_limit=1800)
    return {"chunk_id": context.get("chunk_id") or chunk_id, "count": len(slim), "chunks": slim}


def list_scope_documents(library: dict[str, Any], scope: ScopeContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = _clamp(args.get("limit", 50), 1, 100, default=50)
    scoped_keys = [key for key in scope.item_keys if str(key).strip()]
    if not scoped_keys:
        return {"count": 0, "documents": []}
    ensure_store(library)
    placeholders = ",".join("?" for _ in scoped_keys)
    with connect(library) as conn:
        rows = conn.execute(
            f"""
            SELECT
              item_key,
              COALESCE(MAX(NULLIF(title, '')), item_key) AS title,
              COALESCE(MAX(NULLIF(creators_text, '')), '') AS authors_text,
              COALESCE(MAX(NULLIF(year, '')), '') AS year,
              GROUP_CONCAT(DISTINCT source_type) AS source_types,
              COUNT(DISTINCT doc_id) AS document_count,
              MAX(CASE WHEN source_type = 'mineru_markdown' THEN 1 ELSE 0 END) AS has_full_text
            FROM rag_documents
            WHERE item_key IN ({placeholders})
            GROUP BY item_key
            ORDER BY title COLLATE NOCASE, item_key
            LIMIT ?
            """,
            [*scoped_keys, limit],
        ).fetchall()
    documents = [
        {
            "item_key": str(row["item_key"] or ""),
            "title": str(row["title"] or ""),
            "authors_text": str(row["authors_text"] or ""),
            "year": str(row["year"] or ""),
            "source_types": [item for item in str(row["source_types"] or "").split(",") if item],
            "document_count": int(row["document_count"] or 0),
            "has_full_text": bool(int(row["has_full_text"] or 0)),
        }
        for row in rows
    ]
    return {"count": len(documents), "documents": documents}


def summarize_tool_trace(name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    safe_args = {key: args[key] for key in ("query", "mode", "top_k", "chunk_id", "window_size", "limit") if key in args}
    trace: dict[str, Any] = {"tool": name, "args": safe_args, "ok": "error" not in result}
    result_count = result.get("count")
    if result_count is None:
        for key in ("results", "chunks", "documents"):
            if isinstance(result.get(key), list):
                result_count = len(result[key])
                break
    if result_count is not None:
        trace["result_count"] = int(result_count or 0)
    if result.get("warnings"):
        trace["warnings"] = result.get("warnings")
    if result.get("error"):
        trace["error"] = result.get("error")
    return trace


def _raw_from_chunk(chunk: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    item_key = str(chunk.get("item_key") or source.get("item_key") or "")
    chunk_id = str(chunk.get("chunk_id") or "")
    return {
        "source_type": "metadata" if str(chunk.get("chunk_type") or "") == "metadata" else "chunk",
        "item_key": item_key,
        "attachment_key": str(chunk.get("attachment_key") or source.get("attachment_key") or ""),
        "doc_id": str(chunk.get("doc_id") or source.get("doc_id") or ""),
        "chunk_id": chunk_id,
        "chunk_type": str(chunk.get("chunk_type") or ""),
        "document_source_type": str(source.get("source_type") or ""),
        "title": str(source.get("title") or ""),
        "authors_text": str(source.get("authors_text") or ""),
        "year": str(source.get("year") or ""),
        "venue": str(source.get("venue") or ""),
        "section_title": str(chunk.get("section_title") or ""),
        "estimated_page": chunk.get("estimated_page"),
        "text": str(chunk.get("content") or ""),
        "excerpt": str(chunk.get("excerpt") or chunk.get("content") or "")[:700],
        "citation": f"[{item_key}:metadata]" if str(chunk.get("chunk_type") or "") == "metadata" else f"[{item_key}:{chunk_id}]",
    }


def _tool_name(call: Any) -> str:
    function = getattr(call, "function", None)
    if function is None and isinstance(call, dict):
        function = call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "")
    return str(getattr(function, "name", "") or "")


def _tool_arguments(call: Any) -> str:
    function = getattr(call, "function", None)
    if function is None and isinstance(call, dict):
        function = call.get("function")
    if isinstance(function, dict):
        return str(function.get("arguments") or "")
    return str(getattr(function, "arguments", "") or "")


def _clamp(value: Any, minimum: int, maximum: int, *, default: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default
