from __future__ import annotations

import math
import re
import sqlite3
import struct
from dataclasses import dataclass
from typing import Any, Protocol

from zotero_web_library.rag.query import intersect_item_keys, normalize_search_filters
from zotero_web_library.rag.store import (
    connect,
    embedding_config,
    ensure_store,
    knowledge_base_item_keys,
    normalize_item_keys,
    row_to_dict,
    text_hash,
)
from zotero_web_library.utils import now_iso


TOKEN_RE = re.compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}", re.UNICODE)
DEFAULT_EMBEDDING_BATCH_SIZE = 64
DEFAULT_PROVIDER_MAX_BATCH_SIZE = 10


class EmbeddingConfigError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    provider_name: str
    model: str
    dim: int
    max_batch_size: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(slots=True)
class DeterministicEmbeddingProvider:
    model: str = "deterministic-hash-v1"
    dim: int = 64
    provider_name: str = "deterministic"
    max_batch_size: int = 512

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_hashed_bag(text, self.dim)) for text in texts]


@dataclass(slots=True)
class OpenAIEmbeddingProvider:
    model: str
    api_key: str
    base_url: str = ""
    dim: int = 0
    provider_name: str = "openai"
    max_batch_size: int = DEFAULT_PROVIDER_MAX_BATCH_SIZE

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise EmbeddingConfigError("OpenAI embedding API key is not configured.")
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = OpenAI(**kwargs)
        response = client.embeddings.create(model=self.model, input=texts)
        vectors = [list(item.embedding) for item in response.data]
        if vectors and not self.dim:
            self.dim = len(vectors[0])
        return vectors


def provider_from_config(config: dict[str, Any]) -> EmbeddingProvider | None:
    if not bool(config.get("enabled")):
        return None
    provider_name = str(config.get("provider") or "").strip().lower()
    model = str(config.get("model") or "").strip()
    if not provider_name or not model:
        return None
    dim = int(config.get("dim") or 0)
    if provider_name in {"deterministic", "test", "local_hash"}:
        return DeterministicEmbeddingProvider(model=model or "deterministic-hash-v1", dim=dim or 64)
    if provider_name == "openai":
        return OpenAIEmbeddingProvider(
            model=model,
            api_key=str(config.get("api_key") or ""),
            base_url=str(config.get("base_url") or ""),
            dim=dim,
        )
    raise EmbeddingConfigError(f"Unsupported embedding provider: {provider_name}")


def embedding_status(library: dict[str, Any]) -> dict[str, Any]:
    ensure_store(library)
    config = embedding_config(library)
    with connect(library) as conn:
        if config.get("enabled") and config.get("provider") and config.get("model"):
            provider_name = str(config.get("provider") or "").strip().lower()
            model = str(config.get("model") or "").strip()
            model_label = f"{provider_name}:{model}"
            rows = conn.execute(
                """
                SELECT normalized_status AS embedding_status, COUNT(*) AS chunk_count
                FROM (
                  SELECT CASE
                    WHEN e.chunk_id IS NOT NULL
                      AND e.provider = ? AND e.model = ?
                      AND e.content_hash = c.content_hash
                      AND e.content_version = c.content_version
                      AND c.embedding_model = ?
                    THEN 'embedded'
                    WHEN c.embedding_status = 'failed' THEN 'failed'
                    ELSE 'pending'
                  END AS normalized_status
                  FROM rag_chunks c
                  LEFT JOIN rag_embeddings e ON e.chunk_id = c.chunk_id
                )
                GROUP BY normalized_status
                ORDER BY normalized_status
                """,
                (provider_name, model, model_label),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT embedding_status, COUNT(*) AS chunk_count
                FROM rag_chunks
                GROUP BY embedding_status
                ORDER BY embedding_status
                """
            ).fetchall()
        stored = conn.execute("SELECT COUNT(*) FROM rag_embeddings").fetchone()[0]
    return {
        "configured": bool(config.get("enabled") and config.get("provider") and config.get("model")),
        "config": {key: value for key, value in config.items() if key != "api_key"},
        "stored_embeddings": int(stored or 0),
        "statuses": [dict(row) for row in rows],
    }


def embed_missing_chunks(
    library: dict[str, Any],
    *,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    batch_size: int | None = None,
    force: bool = False,
    provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    ensure_store(library)
    config = embedding_config(library)
    active_provider = provider or provider_from_config(config)
    if active_provider is None:
        with connect(library) as conn:
            conn.execute(
                """
                UPDATE rag_chunks
                SET embedding_status = 'not_configured',
                    embedding_model = '',
                    embedding_hash = ''
                """
            )
            conn.commit()
        return {
            "ok": False,
            "status": "not_configured",
            "processed_chunks": 0,
            "embedded_chunks": 0,
            "failed_chunks": 0,
        }

    scope = _scope_item_keys(library, knowledge_base_id=knowledge_base_id, item_keys=item_keys)
    if knowledge_base_id and not scope:
        return _empty_index_result(active_provider, status="empty_scope")

    provider_batch_size = max(
        1,
        min(int(batch_size or config.get("batch_size") or DEFAULT_EMBEDDING_BATCH_SIZE), 512),
    )
    model_label = _model_label(active_provider)
    rows = _chunks_needing_embedding(
        library,
        provider=active_provider,
        model_label=model_label,
        item_keys=scope,
        force=force,
    )
    if not rows:
        return {
            **_empty_index_result(active_provider, status="up_to_date"),
            "configured": True,
        }

    timestamp = now_iso()
    embedded_count = 0
    failed_count = 0
    processed_count = 0
    error_message = ""
    batch_limit = _embedding_batch_limit(active_provider, provider_batch_size)
    for start in range(0, len(rows), batch_limit):
        batch_rows = rows[start : start + batch_limit]
        batch_texts = [str(row["content"] or "") for row in batch_rows]
        try:
            vectors = active_provider.embed_texts(batch_texts)
            if len(vectors) != len(batch_rows):
                raise EmbeddingConfigError(
                    f"Embedding provider returned {len(vectors)} vectors for {len(batch_rows)} input texts."
                )
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            with connect(library) as conn:
                for row in batch_rows:
                    conn.execute(
                        """
                        UPDATE rag_chunks
                        SET embedding_status = 'failed', embedding_model = ?, embedding_hash = ''
                        WHERE chunk_id = ?
                        """,
                        (model_label, row["chunk_id"]),
                    )
                conn.commit()
            failed_count += len(batch_rows)
            processed_count += len(batch_rows)
            break

        batch_embedded = 0
        batch_failed = 0
        observed_dim: int | None = None
        with connect(library) as conn:
            for row, vector in zip(batch_rows, vectors):
                if not vector:
                    batch_failed += 1
                    conn.execute(
                        "UPDATE rag_chunks SET embedding_status = 'failed', embedding_model = ?, embedding_hash = '' WHERE chunk_id = ?",
                        (model_label, row["chunk_id"]),
                    )
                    continue
                normalized = _normalize([float(value) for value in vector])
                observed_dim = observed_dim or len(normalized)
                packed = pack_embedding(normalized)
                payload = {
                    "chunk_id": row["chunk_id"],
                    "library_id": str(library["library_id"]),
                    "provider": active_provider.provider_name,
                    "model": active_provider.model,
                    "dim": len(normalized),
                    "embedding": packed,
                    "content_hash": row["content_hash"],
                    "content_version": row["content_version"],
                    "embedding_hash": text_hash(packed),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                conn.execute(
                    """
                    INSERT INTO rag_embeddings (
                      chunk_id, library_id, provider, model, dim, embedding,
                      content_hash, content_version, embedding_hash, created_at, updated_at
                    )
                    VALUES (
                      :chunk_id, :library_id, :provider, :model, :dim, :embedding,
                      :content_hash, :content_version, :embedding_hash, :created_at, :updated_at
                    )
                    ON CONFLICT(chunk_id) DO UPDATE SET
                      library_id = excluded.library_id,
                      provider = excluded.provider,
                      model = excluded.model,
                      dim = excluded.dim,
                      embedding = excluded.embedding,
                      content_hash = excluded.content_hash,
                      content_version = excluded.content_version,
                      embedding_hash = excluded.embedding_hash,
                      updated_at = excluded.updated_at
                    """,
                    payload,
                )
                conn.execute(
                    """
                    UPDATE rag_chunks
                    SET embedding_status = 'embedded', embedding_model = ?, embedding_hash = ?
                    WHERE chunk_id = ?
                    """,
                    (model_label, payload["embedding_hash"], row["chunk_id"]),
                )
                batch_embedded += 1
            if observed_dim:
                conn.execute(
                    """
                    UPDATE rag_config
                    SET embedding_dim = ?, embedding_provider = ?, embedding_model = ?,
                        vector_store_type = CASE WHEN vector_store_type = 'none' THEN 'sqlite_blob' ELSE vector_store_type END,
                        updated_at = ?
                    WHERE library_id = ?
                    """,
                    (
                        observed_dim,
                        active_provider.provider_name,
                        active_provider.model,
                        timestamp,
                        str(library["library_id"]),
                    ),
                )
            conn.commit()
        embedded_count += batch_embedded
        failed_count += batch_failed
        processed_count += len(batch_rows)

    remaining_count = max(0, len(rows) - processed_count)
    status = "completed"
    if error_message and embedded_count == 0:
        status = "failed"
    elif error_message or failed_count:
        status = "partial"
    return {
        "ok": not error_message and failed_count == 0,
        "status": status,
        **({"error": error_message} if error_message else {}),
        "provider": active_provider.provider_name,
        "model": active_provider.model,
        "processed_chunks": processed_count,
        "embedded_chunks": embedded_count,
        "failed_chunks": failed_count,
        "remaining_chunks": remaining_count,
    }


def semantic_search_vectors(
    library: dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    chunk_type: str = "",
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    ensure_store(library)
    clean_query = str(query or "").strip()
    if not clean_query:
        return {"query": clean_query, "results": []}
    config = embedding_config(library)
    active_provider = provider or provider_from_config(config)
    if active_provider is None:
        return {"query": clean_query, "results": [], "status": "not_configured"}

    filter_payload = normalize_search_filters(filters)
    scope = _scope_item_keys(library, knowledge_base_id=knowledge_base_id, item_keys=item_keys)
    filter_item_keys = filter_payload.get("item_keys")
    if filter_item_keys is not None:
        scope = intersect_item_keys(scope, filter_item_keys)
    if knowledge_base_id and not scope:
        return {"query": clean_query, "knowledge_base_id": str(knowledge_base_id or ""), "filters": filter_payload, "results": [], "status": "empty_scope"}
    if filter_item_keys is not None and not scope:
        return {"query": clean_query, "knowledge_base_id": str(knowledge_base_id or ""), "filters": filter_payload, "results": [], "status": "empty_scope"}

    query_vector = _normalize(_embed_texts_batched(active_provider, [clean_query])[0])
    rows = _candidate_embeddings(
        library,
        provider=active_provider,
        chunk_type=chunk_type,
        item_keys=scope,
        filters=filter_payload,
    )
    scored: list[dict[str, Any]] = []
    for row in rows:
        vector = unpack_embedding(row["embedding"], int(row["dim"]))
        score = cosine_similarity(query_vector, vector)
        item = dict(row)
        item.pop("embedding", None)
        item["score"] = score
        item["semantic_score"] = score
        item["snippet"] = item.get("excerpt", "")
        item["source"] = _source_for_chunk_row(row)
        scored.append(item)
    scored.sort(key=lambda item: float(item.get("semantic_score") or 0.0), reverse=True)
    return {
        "query": clean_query,
        "knowledge_base_id": str(knowledge_base_id or ""),
        "filters": filter_payload,
        "status": "ok",
        "provider": active_provider.provider_name,
        "model": active_provider.model,
        "results": scored[: max(1, min(int(top_k or 10), 50))],
    }


def pack_embedding(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *[float(value) for value in vector])


def unpack_embedding(payload: bytes, dim: int) -> list[float]:
    if dim <= 0:
        return []
    return list(struct.unpack(f"<{dim}f", payload))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _chunks_needing_embedding(
    library: dict[str, Any],
    *,
    provider: EmbeddingProvider,
    model_label: str,
    item_keys: list[str] | None,
    force: bool,
) -> list[dict[str, Any]]:
    where = ["c.content != ''"]
    params: list[Any] = []
    if item_keys is not None:
        if not item_keys:
            return []
        placeholders = ",".join("?" for _ in item_keys)
        where.append(f"c.item_key IN ({placeholders})")
        params.extend(item_keys)
    if force:
        where.append("1 = 1")
    else:
        where.append(
            """
            (
              c.embedding_status != 'embedded'
              OR c.embedding_model != ?
              OR e.chunk_id IS NULL
              OR e.provider != ?
              OR e.model != ?
              OR e.content_hash != c.content_hash
              OR e.content_version != c.content_version
            )
            """
        )
        params.extend([model_label, provider.provider_name, provider.model])
    with connect(library) as conn:
        rows = conn.execute(
            f"""
            SELECT c.*
            FROM rag_chunks c
            LEFT JOIN rag_embeddings e ON e.chunk_id = c.chunk_id
            WHERE {" AND ".join(where)}
            ORDER BY c.created_at, c.doc_id, c.chunk_index
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _candidate_embeddings(
    library: dict[str, Any],
    *,
    provider: EmbeddingProvider,
    chunk_type: str,
    item_keys: list[str] | None,
    filters: dict[str, Any],
) -> list[sqlite3.Row]:
    where = [
        "e.provider = ?",
        "e.model = ?",
        "e.content_hash = c.content_hash",
        "e.content_version = c.content_version",
        "c.embedding_status = 'embedded'",
    ]
    params: list[Any] = [provider.provider_name, provider.model]
    chunk_types = list(filters.get("chunk_types") or [])
    if chunk_type and chunk_types and str(chunk_type) not in chunk_types:
        return []
    if chunk_type:
        chunk_types = [str(chunk_type)]
    if chunk_types:
        placeholders = ",".join("?" for _ in chunk_types)
        where.append(f"c.chunk_type IN ({placeholders})")
        params.extend(chunk_types)
    if item_keys is not None:
        if not item_keys:
            return []
        placeholders = ",".join("?" for _ in item_keys)
        where.append(f"c.item_key IN ({placeholders})")
        params.extend(item_keys)
    if filters.get("year_from") is not None:
        where.append("CAST(NULLIF(d.year, '') AS INTEGER) >= ?")
        params.append(filters["year_from"])
    if filters.get("year_to") is not None:
        where.append("CAST(NULLIF(d.year, '') AS INTEGER) <= ?")
        params.append(filters["year_to"])
    authors = list(filters.get("authors") or [])
    if authors:
        where.append("(" + " OR ".join("d.creators_text LIKE ?" for _ in authors) + ")")
        params.extend(f"%{author}%" for author in authors)
    venues = list(filters.get("venues") or [])
    if venues:
        where.append("(" + " OR ".join("d.venue LIKE ?" for _ in venues) + ")")
        params.extend(f"%{venue}%" for venue in venues)
    with connect(library) as conn:
        return conn.execute(
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
              c.excerpt,
              c.estimated_page,
              c.content,
              c.content_hash,
              e.dim,
              e.embedding,
              d.title,
              d.creators_text,
              d.year,
              d.venue,
              d.source_type AS document_source_type
            FROM rag_embeddings e
            JOIN rag_chunks c ON c.chunk_id = e.chunk_id
            JOIN rag_documents d ON d.doc_id = c.doc_id
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchall()


def _scope_item_keys(
    library: dict[str, Any],
    *,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> list[str] | None:
    requested_keys = normalize_item_keys(item_keys or []) if item_keys is not None else None
    clean_knowledge_base_id = str(knowledge_base_id or "").strip()
    if clean_knowledge_base_id:
        base_keys = knowledge_base_item_keys(library, clean_knowledge_base_id)
        if requested_keys is None:
            return base_keys
        allowed = set(base_keys)
        return [key for key in requested_keys if key in allowed]
    return requested_keys


def _source_for_chunk_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = row_to_dict(row) if isinstance(row, sqlite3.Row) else dict(row)
    return {
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
        "excerpt": item.get("excerpt") or str(item.get("content") or "")[:320],
    }


def _empty_index_result(provider: EmbeddingProvider, *, status: str) -> dict[str, Any]:
    return {
        "ok": True,
        "status": status,
        "provider": provider.provider_name,
        "model": provider.model,
        "processed_chunks": 0,
        "embedded_chunks": 0,
        "failed_chunks": 0,
    }


def _model_label(provider: EmbeddingProvider) -> str:
    return f"{provider.provider_name}:{provider.model}"


def _embed_texts_batched(
    provider: EmbeddingProvider,
    texts: list[str],
    *,
    batch_size: int | None = None,
) -> list[list[float]]:
    limit = _embedding_batch_limit(provider, batch_size)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), limit):
        batch = texts[start : start + limit]
        batch_vectors = provider.embed_texts(batch)
        if len(batch_vectors) != len(batch):
            raise EmbeddingConfigError(
                f"Embedding provider returned {len(batch_vectors)} vectors for {len(batch)} input texts."
            )
        vectors.extend(batch_vectors)
    return vectors


def _embedding_batch_limit(provider: EmbeddingProvider, batch_size: int | None = None) -> int:
    provider_limit = max(
        1,
        min(
            int(getattr(provider, "max_batch_size", DEFAULT_PROVIDER_MAX_BATCH_SIZE) or DEFAULT_PROVIDER_MAX_BATCH_SIZE),
            512,
        ),
    )
    requested_limit = max(1, min(int(batch_size or provider_limit), 512))
    return min(provider_limit, requested_limit)


def _hashed_bag(text: str, dim: int) -> list[float]:
    vector = [0.0] * dim
    for token in TOKEN_RE.findall(str(text or "").lower()):
        digest = int(text_hash(token)[:8], 16)
        index = digest % dim
        sign = 1.0 if digest % 2 == 0 else -1.0
        vector[index] += sign
    return vector


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]
