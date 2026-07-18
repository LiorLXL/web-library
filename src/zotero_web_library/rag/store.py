from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from zotero_web_library.utils import now_iso


RAG_SCHEMA_VERSION = 4
CHUNK_CONTENT_VERSION = "structured-parent-v1"


SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_config (
  library_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL DEFAULT 4,
  chunk_strategy TEXT NOT NULL DEFAULT 'structured_markdown_parent_child',
  chunk_content_version TEXT NOT NULL DEFAULT 'structured-parent-v1',
  chunk_size INTEGER NOT NULL DEFAULT 900,
  chunk_overlap INTEGER NOT NULL DEFAULT 120,
  embedding_enabled INTEGER NOT NULL DEFAULT 0,
  embedding_provider TEXT NOT NULL DEFAULT '',
  embedding_model TEXT NOT NULL DEFAULT '',
  embedding_dim INTEGER,
  vector_store_type TEXT NOT NULL DEFAULT 'none',
  vector_store_path TEXT NOT NULL DEFAULT '',
  index_status TEXT NOT NULL DEFAULT 'pending',
  total_items INTEGER NOT NULL DEFAULT 0,
  indexed_items INTEGER NOT NULL DEFAULT 0,
  total_documents INTEGER NOT NULL DEFAULT 0,
  total_chunks INTEGER NOT NULL DEFAULT 0,
  total_assets INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_indexed_at TEXT NOT NULL DEFAULT '',
  config_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rag_documents (
  doc_id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  attachment_key TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL,
  source_path TEXT NOT NULL DEFAULT '',
  source_relpath TEXT NOT NULL DEFAULT '',
  source_hash TEXT NOT NULL DEFAULT '',
  source_mtime TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  item_type TEXT NOT NULL DEFAULT '',
  year TEXT NOT NULL DEFAULT '',
  venue TEXT NOT NULL DEFAULT '',
  creators_text TEXT NOT NULL DEFAULT '',
  tags_text TEXT NOT NULL DEFAULT '',
  mineru_json_path TEXT NOT NULL DEFAULT '',
  mineru_markdown_path TEXT NOT NULL DEFAULT '',
  mineru_assets_dir TEXT NOT NULL DEFAULT '',
  parsed_at TEXT NOT NULL DEFAULT '',
  structure_json TEXT NOT NULL DEFAULT '{}',
  stats_json TEXT NOT NULL DEFAULT '{}',
  total_chunks INTEGER NOT NULL DEFAULT 0,
  total_assets INTEGER NOT NULL DEFAULT 0,
  total_chars INTEGER NOT NULL DEFAULT 0,
  index_status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  indexed_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_docs_item ON rag_documents(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_docs_attachment ON rag_documents(attachment_key);
CREATE INDEX IF NOT EXISTS idx_rag_docs_source_type ON rag_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_rag_docs_hash ON rag_documents(source_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_docs_unique_source
ON rag_documents(item_key, attachment_key, source_type, source_hash);

CREATE TABLE IF NOT EXISTS rag_chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  library_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  attachment_key TEXT NOT NULL DEFAULT '',
  chunk_index INTEGER NOT NULL,
  parent_chunk_id TEXT NOT NULL DEFAULT '',
  chunk_type TEXT NOT NULL,
  content_version TEXT NOT NULL DEFAULT 'structured-parent-v1',
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  excerpt TEXT NOT NULL DEFAULT '',
  section_title TEXT NOT NULL DEFAULT '',
  section_path TEXT NOT NULL DEFAULT '',
  section_level INTEGER NOT NULL DEFAULT 0,
  estimated_page INTEGER,
  position_json TEXT NOT NULL DEFAULT '{}',
  token_count INTEGER NOT NULL DEFAULT 0,
  char_count INTEGER NOT NULL DEFAULT 0,
  word_count INTEGER NOT NULL DEFAULT 0,
  has_assets INTEGER NOT NULL DEFAULT 0,
  has_tables INTEGER NOT NULL DEFAULT 0,
  has_equations INTEGER NOT NULL DEFAULT 0,
  has_code INTEGER NOT NULL DEFAULT 0,
  embedding_status TEXT NOT NULL DEFAULT 'not_configured',
  embedding_model TEXT NOT NULL DEFAULT '',
  embedding_hash TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_item ON rag_chunks(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_attachment ON rag_chunks(attachment_key);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_type ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_section ON rag_chunks(section_title);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_hash ON rag_chunks(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_chunks_unique_index ON rag_chunks(doc_id, chunk_index);
CREATE TABLE IF NOT EXISTS rag_chunk_parents (
  parent_chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  library_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  attachment_key TEXT NOT NULL DEFAULT '',
  section_title TEXT NOT NULL DEFAULT '',
  section_path TEXT NOT NULL DEFAULT '',
  section_level INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  child_count INTEGER NOT NULL DEFAULT 0,
  char_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chunk_parents_doc ON rag_chunk_parents(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunk_parents_item ON rag_chunk_parents(item_key);

CREATE TABLE IF NOT EXISTS rag_embeddings (
  chunk_id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  embedding BLOB NOT NULL,
  content_hash TEXT NOT NULL,
  content_version TEXT NOT NULL DEFAULT 'structured-parent-v1',
  embedding_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_embeddings_library ON rag_embeddings(library_id);
CREATE INDEX IF NOT EXISTS idx_rag_embeddings_model ON rag_embeddings(provider, model);
CREATE INDEX IF NOT EXISTS idx_rag_embeddings_hash ON rag_embeddings(content_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunk_fts USING fts5(
  chunk_id UNINDEXED,
  doc_id UNINDEXED,
  item_key UNINDEXED,
  attachment_key UNINDEXED,
  chunk_type UNINDEXED,
  title,
  section_title,
  content,
  tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS rag_assets (
  asset_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL DEFAULT '',
  library_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  attachment_key TEXT NOT NULL DEFAULT '',
  asset_type TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_relpath TEXT NOT NULL DEFAULT '',
  source_hash TEXT NOT NULL DEFAULT '',
  mime_type TEXT NOT NULL DEFAULT '',
  file_size INTEGER NOT NULL DEFAULT 0,
  width INTEGER,
  height INTEGER,
  caption TEXT NOT NULL DEFAULT '',
  alt_text TEXT NOT NULL DEFAULT '',
  ocr_text TEXT NOT NULL DEFAULT '',
  position_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_assets_doc ON rag_assets(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_assets_chunk ON rag_assets(chunk_id);
CREATE INDEX IF NOT EXISTS idx_rag_assets_item ON rag_assets(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_assets_type ON rag_assets(asset_type);

CREATE TABLE IF NOT EXISTS rag_notes (
  note_id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  item_key TEXT NOT NULL DEFAULT '',
  attachment_key TEXT NOT NULL DEFAULT '',
  note_type TEXT NOT NULL,
  source_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  source_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  indexed_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_notes_item ON rag_notes(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_notes_type ON rag_notes(note_type);
CREATE INDEX IF NOT EXISTS idx_rag_notes_hash ON rag_notes(content_hash);

CREATE TABLE IF NOT EXISTS rag_knowledge_bases (
  knowledge_base_id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  base_mode TEXT NOT NULL DEFAULT 'manual',
  scope_json TEXT NOT NULL DEFAULT '{}',
  index_policy_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_kb_library ON rag_knowledge_bases(library_id);
CREATE INDEX IF NOT EXISTS idx_rag_kb_updated ON rag_knowledge_bases(updated_at);

CREATE TABLE IF NOT EXISTS rag_knowledge_base_items (
  knowledge_base_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  note TEXT NOT NULL DEFAULT '',
  pinned INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (knowledge_base_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_rag_kb_items_item ON rag_knowledge_base_items(item_key);

CREATE TABLE IF NOT EXISTS rag_chat_sessions (
  conversation_id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  knowledge_base_id TEXT NOT NULL DEFAULT '',
  item_keys_json TEXT NOT NULL DEFAULT '[]',
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chat_sessions_library ON rag_chat_sessions(library_id);
CREATE INDEX IF NOT EXISTS idx_rag_chat_sessions_kb ON rag_chat_sessions(knowledge_base_id);

CREATE TABLE IF NOT EXISTS rag_chat_messages (
  message_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  run_id TEXT NOT NULL DEFAULT '',
  turn_index INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  sources_json TEXT NOT NULL DEFAULT '[]',
  tool_trace_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chat_msg_conv ON rag_chat_messages(conversation_id, turn_index);

CREATE TABLE IF NOT EXISTS rag_agent_runs (
  run_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  library_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  current_state TEXT NOT NULL DEFAULT 'plan',
  task_plan_json TEXT NOT NULL DEFAULT '{}',
  evidence_state_json TEXT NOT NULL DEFAULT '{}',
  budget_json TEXT NOT NULL DEFAULT '{}',
  usage_json TEXT NOT NULL DEFAULT '{}',
  checkpoint_json TEXT NOT NULL DEFAULT '{}',
  worker_id TEXT NOT NULL DEFAULT '',
  heartbeat_at TEXT NOT NULL DEFAULT '',
  stop_reason TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_agent_runs_conv ON rag_agent_runs(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rag_agent_runs_status ON rag_agent_runs(library_id, status, updated_at);

CREATE TABLE IF NOT EXISTS rag_agent_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'summary',
  summary TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_rag_agent_events_run ON rag_agent_events(run_id, sequence);
"""


def rag_db_path(library: dict[str, Any]) -> Path:
    return Path(str(library["data_path"])) / "rag.sqlite"


def connect(library: dict[str, Any]) -> sqlite3.Connection:
    path = rag_db_path(library)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_store(library: dict[str, Any]) -> None:
    with connect(library) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT INTO rag_config (library_id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(library_id) DO NOTHING
            """,
            (str(library["library_id"]), now_iso(), now_iso()),
        )
        _migrate_store(conn)
        conn.execute(
            """
            UPDATE rag_config
            SET schema_version = ?, chunk_strategy = ?, chunk_content_version = ?, updated_at = ?
            WHERE library_id = ?
            """,
            (
                RAG_SCHEMA_VERSION,
                "structured_markdown_parent_child",
                CHUNK_CONTENT_VERSION,
                now_iso(),
                str(library["library_id"]),
            ),
        )
        conn.commit()


def _migrate_store(conn: sqlite3.Connection) -> None:
    config_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(rag_config)").fetchall()}
    if "chunk_content_version" not in config_columns:
        conn.execute("ALTER TABLE rag_config ADD COLUMN chunk_content_version TEXT NOT NULL DEFAULT 'legacy-v1'")
    chunk_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()}
    if "parent_chunk_id" not in chunk_columns:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN parent_chunk_id TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_parent ON rag_chunks(parent_chunk_id)")
    if "embedding_status" not in chunk_columns:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN embedding_status TEXT NOT NULL DEFAULT 'not_configured'")
    if "embedding_model" not in chunk_columns:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''")
    if "embedding_hash" not in chunk_columns:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN embedding_hash TEXT NOT NULL DEFAULT ''")
    if "content_version" not in chunk_columns:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN content_version TEXT NOT NULL DEFAULT 'legacy-v1'")
    embedding_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(rag_embeddings)").fetchall()}
    if "content_version" not in embedding_columns:
        conn.execute("ALTER TABLE rag_embeddings ADD COLUMN content_version TEXT NOT NULL DEFAULT 'legacy-v1'")
    message_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(rag_chat_messages)").fetchall()}
    if message_columns and "tool_trace_json" not in message_columns:
        conn.execute("ALTER TABLE rag_chat_messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT '[]'")
    if message_columns and "run_id" not in message_columns:
        conn.execute("ALTER TABLE rag_chat_messages ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chat_msg_run ON rag_chat_messages(run_id)")
    run_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(rag_agent_runs)").fetchall()}
    if run_columns and "checkpoint_json" not in run_columns:
        conn.execute("ALTER TABLE rag_agent_runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'")
    if run_columns and "worker_id" not in run_columns:
        conn.execute("ALTER TABLE rag_agent_runs ADD COLUMN worker_id TEXT NOT NULL DEFAULT ''")
    if run_columns and "heartbeat_at" not in run_columns:
        conn.execute("ALTER TABLE rag_agent_runs ADD COLUMN heartbeat_at TEXT NOT NULL DEFAULT ''")


def text_hash(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else str(value or "").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*values: str) -> str:
    return hashlib.sha1("\x1f".join(str(value or "") for value in values).encode("utf-8")).hexdigest()[:24]


def reset_index(
    library: dict[str, Any],
    *,
    source_types: Iterable[str] | None = None,
    preserve_embeddings: bool = False,
) -> None:
    ensure_store(library)
    with connect(library) as conn:
        if source_types:
            source_types_list = [str(item) for item in source_types if str(item)]
            placeholders = ",".join("?" for _ in source_types_list)
            rows = conn.execute(
                f"SELECT doc_id FROM rag_documents WHERE source_type IN ({placeholders})",
                source_types_list,
            ).fetchall()
            doc_ids = [str(row["doc_id"]) for row in rows]
        else:
            doc_ids = [str(row["doc_id"]) for row in conn.execute("SELECT doc_id FROM rag_documents").fetchall()]
        for doc_id in doc_ids:
            chunk_rows = conn.execute("SELECT chunk_id FROM rag_chunks WHERE doc_id = ?", (doc_id,)).fetchall()
            chunk_ids = [str(row["chunk_id"]) for row in chunk_rows]
            if chunk_ids and not preserve_embeddings:
                placeholders = ",".join("?" for _ in chunk_ids)
                conn.execute(f"DELETE FROM rag_embeddings WHERE chunk_id IN ({placeholders})", chunk_ids)
            conn.execute("DELETE FROM rag_chunk_fts WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM rag_assets WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM rag_chunk_parents WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM rag_documents WHERE doc_id = ?", (doc_id,))
        if not source_types:
            conn.execute("DELETE FROM rag_notes")
        conn.commit()


def cleanup_orphan_embeddings(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        DELETE FROM rag_embeddings
        WHERE NOT EXISTS (
          SELECT 1 FROM rag_chunks WHERE rag_chunks.chunk_id = rag_embeddings.chunk_id
        )
        """
    )
    return max(0, int(cursor.rowcount or 0))


def upsert_document(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    keys = [
        "doc_id",
        "library_id",
        "item_key",
        "attachment_key",
        "source_type",
        "source_path",
        "source_relpath",
        "source_hash",
        "source_mtime",
        "title",
        "item_type",
        "year",
        "venue",
        "creators_text",
        "tags_text",
        "mineru_json_path",
        "mineru_markdown_path",
        "mineru_assets_dir",
        "parsed_at",
        "structure_json",
        "stats_json",
        "total_chunks",
        "total_assets",
        "total_chars",
        "index_status",
        "error_message",
        "created_at",
        "updated_at",
        "indexed_at",
    ]
    normalized = {key: payload.get(key, "") for key in keys}
    for key in ("total_chunks", "total_assets", "total_chars"):
        normalized[key] = int(normalized.get(key) or 0)
    conn.execute(
        f"""
        INSERT INTO rag_documents ({", ".join(keys)})
        VALUES ({", ".join(":" + key for key in keys)})
        ON CONFLICT(doc_id) DO UPDATE SET
          total_chunks = excluded.total_chunks,
          total_assets = excluded.total_assets,
          total_chars = excluded.total_chars,
          index_status = excluded.index_status,
          error_message = excluded.error_message,
          updated_at = excluded.updated_at,
          indexed_at = excluded.indexed_at
        """,
        normalized,
    )


def insert_chunks(conn: sqlite3.Connection, document: dict[str, Any], chunks: list[Any]) -> None:
    title = str(document.get("title") or "")
    config = conn.execute("SELECT embedding_enabled, embedding_provider, embedding_model FROM rag_config WHERE library_id = ?", (str(document["library_id"]),)).fetchone()
    embedding_enabled = bool(config and int(config["embedding_enabled"] or 0) and str(config["embedding_provider"] or "") and str(config["embedding_model"] or ""))
    embedding_provider = str(config["embedding_provider"] or "").strip().lower() if config else ""
    embedding_name = str(config["embedding_model"] or "").strip() if config else ""
    embedding_model = f"{embedding_provider}:{embedding_name}" if embedding_enabled else ""
    parent_ids = _insert_chunk_parents(conn, document, chunks)
    for index, chunk in enumerate(chunks):
        content = str(chunk.content or "").strip()
        if not content:
            continue
        chunk_id = f"chunk-{stable_id(str(document['doc_id']), str(index), text_hash(content))}"
        content_digest = text_hash(content)
        existing_embedding = None
        if embedding_enabled:
            existing_embedding = conn.execute(
                """
                SELECT embedding_hash
                FROM rag_embeddings
                WHERE chunk_id = ? AND provider = ? AND model = ?
                  AND content_hash = ? AND content_version = ?
                """,
                (chunk_id, embedding_provider, embedding_name, content_digest, CHUNK_CONTENT_VERSION),
            ).fetchone()
        reusable_embedding = bool(existing_embedding and str(existing_embedding["embedding_hash"] or ""))
        excerpt = content[:320]
        payload = {
            "chunk_id": chunk_id,
            "doc_id": document["doc_id"],
            "library_id": document["library_id"],
            "item_key": document["item_key"],
            "attachment_key": document.get("attachment_key", ""),
            "chunk_index": index,
            "parent_chunk_id": parent_ids.get(index, ""),
            "chunk_type": chunk.chunk_type,
            "content_version": CHUNK_CONTENT_VERSION,
            "content": content,
            "content_hash": content_digest,
            "excerpt": excerpt,
            "section_title": chunk.section_title,
            "section_path": str(getattr(chunk, "section_path", "") or chunk.section_title or ""),
            "section_level": int(chunk.section_level or 0),
            "estimated_page": chunk.estimated_page,
            "position_json": "{}",
            "token_count": max(1, len(content) // 4),
            "char_count": len(content),
            "word_count": len(content.split()),
            "has_assets": 0,
            "has_tables": 1 if "|" in content and "---" in content else 0,
            "has_equations": 1 if "$" in content else 0,
            "has_code": 1 if "```" in content else 0,
            "embedding_status": "embedded" if reusable_embedding else ("pending" if embedding_enabled else "not_configured"),
            "embedding_model": embedding_model,
            "embedding_hash": str(existing_embedding["embedding_hash"] or "") if reusable_embedding else "",
            "created_at": now_iso(),
        }
        conn.execute(
            """
            INSERT INTO rag_chunks (
              chunk_id, doc_id, library_id, item_key, attachment_key, chunk_index, parent_chunk_id, chunk_type,
              content_version, content, content_hash, excerpt, section_title, section_path, section_level,
              estimated_page, position_json, token_count, char_count, word_count, has_assets,
              has_tables, has_equations, has_code, embedding_status, embedding_model,
              embedding_hash, created_at
            )
            VALUES (
              :chunk_id, :doc_id, :library_id, :item_key, :attachment_key, :chunk_index, :parent_chunk_id, :chunk_type,
              :content_version, :content, :content_hash, :excerpt, :section_title, :section_path, :section_level,
              :estimated_page, :position_json, :token_count, :char_count, :word_count, :has_assets,
              :has_tables, :has_equations, :has_code, :embedding_status, :embedding_model,
              :embedding_hash, :created_at
            )
            """,
            payload,
        )
        conn.execute(
            """
            INSERT INTO rag_chunk_fts
              (chunk_id, doc_id, item_key, attachment_key, chunk_type, title, section_title, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                str(document["doc_id"]),
                str(document["item_key"]),
                str(document.get("attachment_key") or ""),
                str(chunk.chunk_type),
                title,
                str(chunk.section_title or ""),
                content,
            ),
        )


def _insert_chunk_parents(
    conn: sqlite3.Connection,
    document: dict[str, Any],
    chunks: list[Any],
) -> dict[int, str]:
    groups: dict[str, list[tuple[int, Any]]] = {}
    for index, chunk in enumerate(chunks):
        content = str(getattr(chunk, "content", "") or "").strip()
        if not content:
            continue
        section_path = str(getattr(chunk, "section_path", "") or getattr(chunk, "section_title", "") or "").strip()
        group_key = section_path or f"__root__:{getattr(chunk, 'chunk_type', 'paragraph')}"
        groups.setdefault(group_key, []).append((index, chunk))

    parent_ids: dict[int, str] = {}
    for group_key, members in groups.items():
        first = members[0][1]
        section_title = str(getattr(first, "section_title", "") or "")
        section_path = str(getattr(first, "section_path", "") or section_title)
        section_level = int(getattr(first, "section_level", 0) or 0)
        content_parts: list[str] = []
        seen: set[str] = set()
        for _, chunk in members:
            value = str(getattr(chunk, "content", "") or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            content_parts.append(value)
        parent_content = "\n\n".join(content_parts)[:12000]
        if not parent_content:
            continue
        parent_chunk_id = f"parent-{stable_id(str(document['doc_id']), group_key)}"
        conn.execute(
            """
            INSERT OR REPLACE INTO rag_chunk_parents (
              parent_chunk_id, doc_id, library_id, item_key, attachment_key,
              section_title, section_path, section_level, content, content_hash,
              child_count, char_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parent_chunk_id,
                str(document["doc_id"]),
                str(document["library_id"]),
                str(document["item_key"]),
                str(document.get("attachment_key") or ""),
                section_title,
                section_path,
                section_level,
                parent_content,
                text_hash(parent_content),
                len(members),
                len(parent_content),
                now_iso(),
            ),
        )
        for index, _ in members:
            parent_ids[index] = parent_chunk_id
    return parent_ids


def insert_asset(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO rag_assets (
          asset_id, doc_id, chunk_id, library_id, item_key, attachment_key, asset_type, source_path,
          source_relpath, source_hash, mime_type, file_size, width, height, caption, alt_text,
          ocr_text, position_json, created_at
        )
        VALUES (
          :asset_id, :doc_id, :chunk_id, :library_id, :item_key, :attachment_key, :asset_type, :source_path,
          :source_relpath, :source_hash, :mime_type, :file_size, :width, :height, :caption, :alt_text,
          :ocr_text, :position_json, :created_at
        )
        """,
        payload,
    )


def update_config_stats(library: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
    ensure_store(library)
    timestamp = now_iso()
    with connect(library) as conn:
        docs = conn.execute("SELECT COUNT(*) FROM rag_documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        assets = conn.execute("SELECT COUNT(*) FROM rag_assets").fetchone()[0]
        items = conn.execute("SELECT COUNT(DISTINCT item_key) FROM rag_documents WHERE item_key != ''").fetchone()[0]
        conn.execute(
            """
            UPDATE rag_config
            SET index_status = ?, total_items = ?, indexed_items = ?, total_documents = ?,
                total_chunks = ?, total_assets = ?, updated_at = ?, last_indexed_at = ?
            WHERE library_id = ?
            """,
            (status, items, items, docs, chunks, assets, timestamp, timestamp, str(library["library_id"])),
        )
        conn.commit()
    return index_status(library)


def embedding_config(library: dict[str, Any]) -> dict[str, Any]:
    ensure_store(library)
    with connect(library) as conn:
        row = conn.execute("SELECT * FROM rag_config WHERE library_id = ?", (str(library["library_id"]),)).fetchone()
    payload = dict(row) if row else {}
    config_json = payload.get("config_json") or "{}"
    try:
        extra = json.loads(str(config_json))
    except json.JSONDecodeError:
        extra = {}
    embedding_extra = extra.get("embedding") if isinstance(extra.get("embedding"), dict) else {}
    return {
        "enabled": bool(int(payload.get("embedding_enabled") or 0)),
        "provider": str(payload.get("embedding_provider") or ""),
        "model": str(payload.get("embedding_model") or ""),
        "dim": int(payload["embedding_dim"]) if payload.get("embedding_dim") is not None else None,
        "vector_store_type": str(payload.get("vector_store_type") or "none"),
        "vector_store_path": str(payload.get("vector_store_path") or ""),
        "batch_size": int(embedding_extra.get("batch_size") or 64),
        "api_key": str(embedding_extra.get("api_key") or ""),
        "base_url": str(embedding_extra.get("base_url") or ""),
    }


def save_embedding_config(
    library: dict[str, Any],
    *,
    enabled: bool,
    provider: str,
    model: str,
    dim: int | None = None,
    vector_store_type: str = "sqlite_blob",
    api_key: str = "",
    base_url: str = "",
    batch_size: int = 64,
) -> dict[str, Any]:
    ensure_store(library)
    clean_provider = str(provider or "").strip().lower()
    clean_model = str(model or "").strip()
    clean_vector_store = str(vector_store_type or "sqlite_blob").strip() or "sqlite_blob"
    clean_dim = int(dim) if dim is not None else None
    timestamp = now_iso()
    with connect(library) as conn:
        row = conn.execute("SELECT config_json FROM rag_config WHERE library_id = ?", (str(library["library_id"]),)).fetchone()
        try:
            extra = json.loads(str((row or {})["config_json"] or "{}")) if row else {}
        except json.JSONDecodeError:
            extra = {}
        extra["embedding"] = {
            "api_key": str(api_key or "").strip(),
            "base_url": str(base_url or "").strip(),
            "batch_size": max(1, min(int(batch_size or 64), 512)),
        }
        conn.execute(
            """
            UPDATE rag_config
            SET embedding_enabled = ?, embedding_provider = ?, embedding_model = ?,
                embedding_dim = ?, vector_store_type = ?, config_json = ?,
                updated_at = ?
            WHERE library_id = ?
            """,
            (
                1 if enabled else 0,
                clean_provider,
                clean_model,
                clean_dim,
                clean_vector_store,
                json_dumps(extra),
                timestamp,
                str(library["library_id"]),
            ),
        )
        if not enabled:
            conn.execute(
                """
                UPDATE rag_chunks
                SET embedding_status = 'not_configured',
                    embedding_model = '',
                    embedding_hash = ''
                """
            )
        else:
            model_label = f"{clean_provider}:{clean_model}"
            conn.execute(
                """
                UPDATE rag_chunks
                SET embedding_status = CASE WHEN EXISTS (
                      SELECT 1 FROM rag_embeddings e
                      WHERE e.chunk_id = rag_chunks.chunk_id
                        AND e.provider = ? AND e.model = ?
                        AND e.content_hash = rag_chunks.content_hash
                        AND e.content_version = rag_chunks.content_version
                    ) THEN 'embedded' ELSE 'pending' END,
                    embedding_model = ?,
                    embedding_hash = COALESCE((
                      SELECT e.embedding_hash FROM rag_embeddings e
                      WHERE e.chunk_id = rag_chunks.chunk_id
                        AND e.provider = ? AND e.model = ?
                        AND e.content_hash = rag_chunks.content_hash
                        AND e.content_version = rag_chunks.content_version
                      LIMIT 1
                    ), '')
                """,
                (clean_provider, clean_model, model_label, clean_provider, clean_model),
            )
        conn.commit()
    return embedding_config(library)


def index_status(library: dict[str, Any]) -> dict[str, Any]:
    ensure_store(library)
    with connect(library) as conn:
        config = conn.execute("SELECT * FROM rag_config WHERE library_id = ?", (str(library["library_id"]),)).fetchone()
        source_rows = conn.execute(
            """
            SELECT source_type, COUNT(*) AS document_count
            FROM rag_documents
            GROUP BY source_type
            ORDER BY source_type
            """
        ).fetchall()
        chunk_rows = conn.execute(
            """
            SELECT chunk_type, COUNT(*) AS chunk_count
            FROM rag_chunks
            GROUP BY chunk_type
            ORDER BY chunk_type
            """
        ).fetchall()
        embedding_rows = conn.execute(
            """
            SELECT embedding_status, COUNT(*) AS chunk_count
            FROM rag_chunks
            GROUP BY embedding_status
            ORDER BY embedding_status
            """
        ).fetchall()
        embedding_count = conn.execute("SELECT COUNT(*) FROM rag_embeddings").fetchone()[0]
        stale_chunk_count = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE content_version != ?",
            (CHUNK_CONTENT_VERSION,),
        ).fetchone()[0]
    payload = dict(config) if config else {"library_id": str(library["library_id"]), "index_status": "pending"}
    payload["rag_db_path"] = str(rag_db_path(library))
    payload["sources"] = [dict(row) for row in source_rows]
    payload["chunk_types"] = [dict(row) for row in chunk_rows]
    payload["embedding"] = {
        "enabled": bool(int(payload.get("embedding_enabled") or 0)),
        "provider": str(payload.get("embedding_provider") or ""),
        "model": str(payload.get("embedding_model") or ""),
        "dim": payload.get("embedding_dim"),
        "vector_store_type": str(payload.get("vector_store_type") or "none"),
        "stored_embeddings": int(embedding_count or 0),
        "statuses": [dict(row) for row in embedding_rows],
    }
    payload["content_version"] = CHUNK_CONTENT_VERSION
    payload["stale_chunk_count"] = int(stale_chunk_count or 0)
    payload["requires_reindex"] = bool(stale_chunk_count)
    return payload


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row else {}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize_item_keys(item_keys: Iterable[Any]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in item_keys:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(key)
    return values


def create_knowledge_base(
    library: dict[str, Any],
    *,
    name: str,
    description: str = "",
    item_keys: Iterable[Any] | None = None,
    base_mode: str = "manual",
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_store(library)
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("知识库名称不能为空。")
    mode = str(base_mode or "manual").strip() or "manual"
    if mode not in {"manual", "collection", "tag_filter", "search_filter", "hybrid"}:
        raise ValueError("未知知识库模式。")
    timestamp = now_iso()
    knowledge_base_id = f"kb-{stable_id(str(library['library_id']), clean_name, timestamp)}"
    keys = normalize_item_keys(item_keys or [])
    with connect(library) as conn:
        conn.execute(
            """
            INSERT INTO rag_knowledge_bases (
              knowledge_base_id, library_id, name, description, base_mode,
              scope_json, index_policy_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                knowledge_base_id,
                str(library["library_id"]),
                clean_name,
                str(description or "").strip(),
                mode,
                json_dumps(scope or {}),
                timestamp,
                timestamp,
            ),
        )
        for item_key in keys:
            conn.execute(
                """
                INSERT OR IGNORE INTO rag_knowledge_base_items
                  (knowledge_base_id, item_key, source, added_at)
                VALUES (?, ?, 'manual', ?)
                """,
                (knowledge_base_id, item_key, timestamp),
            )
        conn.commit()
    return knowledge_base(library, knowledge_base_id)


def list_knowledge_bases(library: dict[str, Any]) -> list[dict[str, Any]]:
    ensure_store(library)
    with connect(library) as conn:
        rows = conn.execute(
            """
            SELECT
              kb.*,
              COUNT(DISTINCT kbi.item_key) AS item_count,
              COUNT(DISTINCT d.doc_id) AS document_count,
              COUNT(DISTINCT c.chunk_id) AS chunk_count
            FROM rag_knowledge_bases kb
            LEFT JOIN rag_knowledge_base_items kbi ON kbi.knowledge_base_id = kb.knowledge_base_id
            LEFT JOIN rag_documents d ON d.item_key = kbi.item_key
            LEFT JOIN rag_chunks c ON c.item_key = kbi.item_key
            WHERE kb.library_id = ?
            GROUP BY kb.knowledge_base_id
            ORDER BY kb.updated_at DESC, kb.name COLLATE NOCASE
            """,
            (str(library["library_id"]),),
        ).fetchall()
    return [_knowledge_base_row(row) for row in rows]


def knowledge_base(library: dict[str, Any], knowledge_base_id: str) -> dict[str, Any]:
    ensure_store(library)
    clean_id = str(knowledge_base_id or "").strip()
    if not clean_id:
        raise ValueError("知识库不存在。")
    with connect(library) as conn:
        row = conn.execute(
            """
            SELECT
              kb.*,
              COUNT(DISTINCT kbi.item_key) AS item_count,
              COUNT(DISTINCT d.doc_id) AS document_count,
              COUNT(DISTINCT c.chunk_id) AS chunk_count
            FROM rag_knowledge_bases kb
            LEFT JOIN rag_knowledge_base_items kbi ON kbi.knowledge_base_id = kb.knowledge_base_id
            LEFT JOIN rag_documents d ON d.item_key = kbi.item_key
            LEFT JOIN rag_chunks c ON c.item_key = kbi.item_key
            WHERE kb.library_id = ? AND kb.knowledge_base_id = ?
            GROUP BY kb.knowledge_base_id
            """,
            (str(library["library_id"]), clean_id),
        ).fetchone()
        if not row:
            raise ValueError("知识库不存在。")
        item_rows = conn.execute(
            """
            SELECT
              kbi.*,
              COALESCE(MAX(d.title), '') AS title,
              COALESCE(MAX(d.year), '') AS year,
              COALESCE(MAX(d.venue), '') AS venue,
              COUNT(DISTINCT d.doc_id) AS document_count,
              COUNT(DISTINCT c.chunk_id) AS chunk_count
            FROM rag_knowledge_base_items kbi
            LEFT JOIN rag_documents d ON d.item_key = kbi.item_key
            LEFT JOIN rag_chunks c ON c.item_key = kbi.item_key
            WHERE kbi.knowledge_base_id = ?
            GROUP BY kbi.knowledge_base_id, kbi.item_key
            ORDER BY kbi.pinned DESC, kbi.added_at DESC, kbi.item_key
            """,
            (clean_id,),
        ).fetchall()
    payload = _knowledge_base_row(row)
    payload["items"] = [dict(item) for item in item_rows]
    return payload


def delete_knowledge_base(library: dict[str, Any], knowledge_base_id: str) -> dict[str, Any]:
    ensure_store(library)
    existing = knowledge_base(library, knowledge_base_id)
    clean_id = str(existing["knowledge_base_id"])
    timestamp = now_iso()
    with connect(library) as conn:
        conn.execute(
            """
            DELETE FROM rag_agent_events
            WHERE run_id IN (
              SELECT run_id
              FROM rag_agent_runs
              WHERE conversation_id IN (
                SELECT conversation_id
                FROM rag_chat_sessions
                WHERE library_id = ? AND knowledge_base_id = ?
              )
            )
            """,
            (str(library["library_id"]), clean_id),
        )
        conn.execute(
            """
            DELETE FROM rag_agent_runs
            WHERE conversation_id IN (
              SELECT conversation_id
              FROM rag_chat_sessions
              WHERE library_id = ? AND knowledge_base_id = ?
            )
            """,
            (str(library["library_id"]), clean_id),
        )
        conn.execute(
            """
            DELETE FROM rag_chat_messages
            WHERE conversation_id IN (
              SELECT conversation_id
              FROM rag_chat_sessions
              WHERE library_id = ? AND knowledge_base_id = ?
            )
            """,
            (str(library["library_id"]), clean_id),
        )
        conn.execute(
            """
            DELETE FROM rag_chat_sessions
            WHERE library_id = ? AND knowledge_base_id = ?
            """,
            (str(library["library_id"]), clean_id),
        )
        conn.execute("DELETE FROM rag_knowledge_base_items WHERE knowledge_base_id = ?", (clean_id,))
        conn.execute(
            """
            DELETE FROM rag_knowledge_bases
            WHERE library_id = ? AND knowledge_base_id = ?
            """,
            (str(library["library_id"]), clean_id),
        )
        conn.execute(
            "UPDATE rag_config SET updated_at = ? WHERE library_id = ?",
            (timestamp, str(library["library_id"])),
        )
        conn.commit()
    return {"knowledge_base_id": clean_id, "deleted": True}


def add_knowledge_base_items(
    library: dict[str, Any],
    knowledge_base_id: str,
    item_keys: Iterable[Any],
    *,
    source: str = "manual",
) -> dict[str, Any]:
    ensure_store(library)
    existing = knowledge_base(library, knowledge_base_id)
    keys = normalize_item_keys(item_keys)
    if not keys:
        raise ValueError("item_keys 不能为空。")
    timestamp = now_iso()
    clean_source = str(source or "manual").strip() or "manual"
    with connect(library) as conn:
        for item_key in keys:
            conn.execute(
                """
                INSERT INTO rag_knowledge_base_items (knowledge_base_id, item_key, source, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(knowledge_base_id, item_key) DO UPDATE SET
                  source = excluded.source
                """,
                (existing["knowledge_base_id"], item_key, clean_source, timestamp),
            )
        conn.execute(
            "UPDATE rag_knowledge_bases SET updated_at = ? WHERE knowledge_base_id = ?",
            (timestamp, existing["knowledge_base_id"]),
        )
        conn.commit()
    return knowledge_base(library, existing["knowledge_base_id"])


def remove_knowledge_base_items(
    library: dict[str, Any],
    knowledge_base_id: str,
    item_keys: Iterable[Any],
) -> dict[str, Any]:
    ensure_store(library)
    existing = knowledge_base(library, knowledge_base_id)
    keys = normalize_item_keys(item_keys)
    if not keys:
        raise ValueError("item_keys 不能为空。")
    timestamp = now_iso()
    placeholders = ",".join("?" for _ in keys)
    with connect(library) as conn:
        conn.execute(
            f"""
            DELETE FROM rag_knowledge_base_items
            WHERE knowledge_base_id = ? AND item_key IN ({placeholders})
            """,
            [existing["knowledge_base_id"], *keys],
        )
        conn.execute(
            "UPDATE rag_knowledge_bases SET updated_at = ? WHERE knowledge_base_id = ?",
            (timestamp, existing["knowledge_base_id"]),
        )
        conn.commit()
    return knowledge_base(library, existing["knowledge_base_id"])


def knowledge_base_item_keys(library: dict[str, Any], knowledge_base_id: str) -> list[str]:
    existing = knowledge_base(library, knowledge_base_id)
    return [str(item.get("item_key") or "") for item in existing.get("items", []) if str(item.get("item_key") or "")]


def _knowledge_base_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key in ("scope_json", "index_policy_json"):
        try:
            item[key.removesuffix("_json")] = json.loads(str(item.get(key) or "{}"))
        except json.JSONDecodeError:
            item[key.removesuffix("_json")] = {}
    for key in ("item_count", "document_count", "chunk_count"):
        item[key] = int(item.get(key) or 0)
    return item
