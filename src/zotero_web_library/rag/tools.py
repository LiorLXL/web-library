from __future__ import annotations

import sqlite3
from typing import Any

from zotero_web_library.rag.embeddings import semantic_search_vectors
from zotero_web_library.rag.store import connect, ensure_store, knowledge_base_item_keys, row_to_dict


def _limit(value: Any, default: int = 10, maximum: int = 50) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _source_for_chunk(conn: sqlite3.Connection, chunk: dict[str, Any]) -> dict[str, Any]:
    doc = row_to_dict(conn.execute("SELECT * FROM rag_documents WHERE doc_id = ?", (chunk.get("doc_id"),)).fetchone())
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "doc_id": chunk.get("doc_id", ""),
        "item_key": chunk.get("item_key", ""),
        "attachment_key": chunk.get("attachment_key", ""),
        "title": doc.get("title", ""),
        "authors_text": doc.get("creators_text", ""),
        "year": doc.get("year", ""),
        "venue": doc.get("venue", ""),
        "source_type": doc.get("source_type", ""),
        "section_title": chunk.get("section_title", ""),
        "estimated_page": chunk.get("estimated_page"),
        "excerpt": chunk.get("excerpt") or str(chunk.get("content") or "")[:320],
    }


def keyword_search(
    library: dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    chunk_type: str = "",
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> dict[str, Any]:
    ensure_store(library)
    clean_query = str(query or "").strip()
    if not clean_query:
        return {"query": clean_query, "results": []}
    limit = _limit(top_k)
    scoped_item_keys = _scope_item_keys(library, knowledge_base_id=knowledge_base_id, item_keys=item_keys)
    if knowledge_base_id and not scoped_item_keys:
        return {"query": clean_query, "knowledge_base_id": str(knowledge_base_id or ""), "results": []}
    with connect(library) as conn:
        where = "rag_chunk_fts MATCH ?"
        params: list[Any] = [clean_query]
        if chunk_type:
            where += " AND f.chunk_type = ?"
            params.append(str(chunk_type))
        if scoped_item_keys is not None:
            placeholders = ",".join("?" for _ in scoped_item_keys)
            where += f" AND f.item_key IN ({placeholders})"
            params.extend(scoped_item_keys)
        rows = conn.execute(
            f"""
            SELECT
              f.chunk_id,
              f.doc_id,
              f.item_key,
              f.attachment_key,
              f.chunk_type,
              f.section_title,
              snippet(rag_chunk_fts, 7, '[', ']', '...', 18) AS snippet,
              bm25(rag_chunk_fts) AS score,
              c.excerpt,
              c.estimated_page
            FROM rag_chunk_fts f
            JOIN rag_chunks c ON c.chunk_id = f.chunk_id
            WHERE {where}
            ORDER BY score
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            source = _source_for_chunk(conn, item)
            item["source"] = source
            results.append(item)
    return {"query": clean_query, "knowledge_base_id": str(knowledge_base_id or ""), "results": results}


def metadata_search(
    library: dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> dict[str, Any]:
    return keyword_search(
        library,
        query,
        top_k=top_k,
        chunk_type="metadata",
        knowledge_base_id=knowledge_base_id,
        item_keys=item_keys,
    )


def semantic_search(
    library: dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    chunk_type: str = "",
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> dict[str, Any]:
    return semantic_search_vectors(
        library,
        query,
        top_k=top_k,
        chunk_type=chunk_type,
        knowledge_base_id=knowledge_base_id,
        item_keys=item_keys,
    )


def chunk_read(library: dict[str, Any], chunk_id: str = "", *, doc_id: str = "", window_size: int = 2) -> dict[str, Any]:
    ensure_store(library)
    clean_chunk_id = str(chunk_id or "").strip()
    clean_doc_id = str(doc_id or "").strip()
    window = max(0, min(int(window_size or 0), 10))
    with connect(library) as conn:
        if clean_chunk_id:
            target = conn.execute("SELECT * FROM rag_chunks WHERE chunk_id = ?", (clean_chunk_id,)).fetchone()
        elif clean_doc_id:
            target = conn.execute("SELECT * FROM rag_chunks WHERE doc_id = ? ORDER BY chunk_index LIMIT 1", (clean_doc_id,)).fetchone()
        else:
            target = None
        if not target:
            return {"chunk_id": clean_chunk_id, "doc_id": clean_doc_id, "chunks": [], "source": {}}
        target_dict = dict(target)
        rows = conn.execute(
            """
            SELECT *
            FROM rag_chunks
            WHERE doc_id = ?
              AND chunk_index BETWEEN ? AND ?
            ORDER BY chunk_index
            """,
            (
                target_dict["doc_id"],
                int(target_dict["chunk_index"]) - window,
                int(target_dict["chunk_index"]) + window,
            ),
        ).fetchall()
        chunks = [dict(row) for row in rows]
        source = _source_for_chunk(conn, target_dict)
    return {"chunk_id": target_dict["chunk_id"], "doc_id": target_dict["doc_id"], "source": source, "chunks": chunks}


def _scope_item_keys(
    library: dict[str, Any],
    *,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> list[str] | None:
    requested_keys: list[str] | None = None
    if item_keys is not None:
        requested_keys = list(dict.fromkeys(str(key or "").strip() for key in item_keys if str(key or "").strip()))

    clean_knowledge_base_id = str(knowledge_base_id or "").strip()
    if clean_knowledge_base_id:
        base_keys = knowledge_base_item_keys(library, clean_knowledge_base_id)
        if requested_keys is None:
            return base_keys
        allowed = set(base_keys)
        return [key for key in requested_keys if key in allowed]

    if requested_keys is not None:
        return requested_keys
    return None
