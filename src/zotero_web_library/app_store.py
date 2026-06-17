from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .paths import app_db_path, app_data_dir, libraries_dir
from .semantic_tags import normalize_hash_tag, stable_tag_color
from .utils import now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS libraries (
  library_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  mode TEXT NOT NULL,
  source_path TEXT NOT NULL,
  data_path TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
  library_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (library_id, key)
);

CREATE TABLE IF NOT EXISTS semantic_rules (
  rule_id TEXT PRIMARY KEY,
  library_id TEXT NOT NULL,
  bucket TEXT NOT NULL,
  pattern TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tag_shortcuts (
  library_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  color TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (library_id, tag)
);

CREATE TABLE IF NOT EXISTS sync_journal (
  journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
  library_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  object_kind TEXT NOT NULL,
  object_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
"""


DEFAULT_COLUMNS = [
    "title",
    "creators",
    "year",
    "venue",
    "rating",
    "nested",
    "venue_rank",
    "reading_status",
    "collections",
]

SUPPORTED_COLUMNS = {
    "title",
    "remark",
    "title_zh",
    "abstract_zh",
    "creators",
    "year",
    "venue",
    "rating",
    "nested",
    "venue_rank",
    "reading_status",
    "plain",
    "collections",
}

TAG_SHORTCUTS_INITIALIZED_KEY = "tag_shortcuts_initialized"
LOCAL_COPY_MODE = "local_copy"


def ensure_app_store() -> None:
    app_data_dir().mkdir(parents=True, exist_ok=True)
    libraries_dir().mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def connect() -> sqlite3.Connection:
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(app_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def list_libraries() -> list[dict[str, Any]]:
    ensure_app_store()
    with connect() as conn:
        rows = [_portable_library_row(dict(row)) for row in conn.execute("SELECT * FROM libraries ORDER BY updated_at DESC").fetchall()]
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.get("mode") == LOCAL_COPY_MODE:
            deduped.append(row)
            continue
        key = (row.get("mode", ""), _source_key(row.get("source_path", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def list_all_libraries() -> list[dict[str, Any]]:
    ensure_app_store()
    with connect() as conn:
        return [_portable_library_row(dict(row)) for row in conn.execute("SELECT * FROM libraries ORDER BY updated_at DESC").fetchall()]


def _source_key(path: str | Path) -> str:
    try:
        return str(Path(path).expanduser().resolve()).casefold()
    except (OSError, RuntimeError):
        return str(path).casefold()


def get_library(library_id: str) -> dict[str, Any] | None:
    ensure_app_store()
    with connect() as conn:
        row = conn.execute("SELECT * FROM libraries WHERE library_id = ?", (library_id,)).fetchone()
        return _portable_library_row(dict(row)) if row else None


def _portable_library_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("mode") != LOCAL_COPY_MODE:
        return row
    portable_path = libraries_dir() / str(row.get("library_id", ""))
    if (portable_path / "zotero.sqlite").exists():
        row["data_path"] = str(portable_path)
        return row
    data_path = Path(str(row.get("data_path", "")))
    if (data_path / "zotero.sqlite").exists():
        return row
    return row


def delete_library_record(library_id: str) -> None:
    ensure_app_store()
    with connect() as conn:
        conn.execute("DELETE FROM libraries WHERE library_id = ?", (library_id,))
        conn.execute("DELETE FROM preferences WHERE library_id = ?", (library_id,))
        conn.execute("DELETE FROM semantic_rules WHERE library_id = ?", (library_id,))
        conn.execute("DELETE FROM tag_shortcuts WHERE library_id = ?", (library_id,))
        conn.commit()


def upsert_library(record: dict[str, Any]) -> dict[str, Any]:
    ensure_app_store()
    timestamp = now_iso()
    payload = {
        "library_id": record["library_id"],
        "name": record["name"],
        "mode": record["mode"],
        "source_path": str(record["source_path"]),
        "data_path": str(record["data_path"]),
        "source_fingerprint": record.get("source_fingerprint", ""),
        "created_at": record.get("created_at", timestamp),
        "updated_at": timestamp,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO libraries (library_id, name, mode, source_path, data_path, source_fingerprint, created_at, updated_at)
            VALUES (:library_id, :name, :mode, :source_path, :data_path, :source_fingerprint, :created_at, :updated_at)
            ON CONFLICT(library_id) DO UPDATE SET
              name = excluded.name,
              mode = excluded.mode,
              source_path = excluded.source_path,
              data_path = excluded.data_path,
              source_fingerprint = excluded.source_fingerprint,
              updated_at = excluded.updated_at
            """,
            payload,
        )
        conn.commit()
    return payload


def get_preference(library_id: str, key: str, default: Any = None) -> Any:
    ensure_app_store()
    with connect() as conn:
        row = conn.execute("SELECT value_json FROM preferences WHERE library_id = ? AND key = ?", (library_id, key)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except json.JSONDecodeError:
        return default


def set_preference(library_id: str, key: str, value: Any) -> None:
    ensure_app_store()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO preferences (library_id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(library_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (library_id, key, json.dumps(value, ensure_ascii=False), now_iso()),
        )
        conn.commit()


def column_preference(library_id: str) -> list[str]:
    value = get_preference(library_id, "columns", DEFAULT_COLUMNS)
    if not isinstance(value, list):
        return DEFAULT_COLUMNS
    columns = [str(item) for item in value if str(item) in SUPPORTED_COLUMNS]
    return columns or DEFAULT_COLUMNS


def column_width_preference(library_id: str) -> dict[str, int]:
    value = get_preference(library_id, "column_widths", {})
    if not isinstance(value, dict):
        return {}
    widths: dict[str, int] = {}
    for key, raw in value.items():
        if str(key) not in SUPPORTED_COLUMNS:
            continue
        try:
            width = int(raw)
        except (TypeError, ValueError):
            continue
        if 40 <= width <= 1200:
            widths[str(key)] = width
    return widths


def plain_tags_collapsed(library_id: str) -> bool:
    return bool(get_preference(library_id, "plain_tags_collapsed", True))


def append_journal(library_id: str, operation: str, object_kind: str, object_key: str, payload: dict[str, Any]) -> None:
    ensure_app_store()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO sync_journal (library_id, operation, object_kind, object_key, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (library_id, operation, object_kind, object_key, json.dumps(payload, ensure_ascii=False), now_iso()),
        )
        conn.commit()


def list_semantic_rules(library_id: str) -> list[dict[str, Any]]:
    ensure_app_store()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM semantic_rules WHERE library_id = ? AND enabled = 1 ORDER BY created_at",
            (library_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_semantic_rule(library_id: str, bucket: str, pattern: str, label: str = "") -> dict[str, Any]:
    ensure_app_store()
    rule_id = f"rule-{now_iso()}-{abs(hash((library_id, bucket, pattern))) % 100000}"
    record = {
        "rule_id": rule_id,
        "library_id": library_id,
        "bucket": bucket,
        "pattern": pattern,
        "label": label,
        "enabled": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO semantic_rules (rule_id, library_id, bucket, pattern, label, enabled, created_at, updated_at)
            VALUES (:rule_id, :library_id, :bucket, :pattern, :label, :enabled, :created_at, :updated_at)
            """,
            record,
        )
        conn.commit()
    return record


def list_tag_shortcuts(library_id: str) -> list[dict[str, Any]]:
    ensure_app_store()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tag_shortcuts WHERE library_id = ? ORDER BY created_at, tag COLLATE NOCASE",
            (library_id,),
        ).fetchall()
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = dict(row)
        normalized = normalize_hash_tag(item.get("tag", ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        item["tag"] = normalized
        values.append(item)
    return values


def ensure_tag_shortcuts(library_id: str, tags: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for tag in tags:
        normalized = normalize_hash_tag(tag)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        upsert_tag_shortcut(library_id, normalized, stable_tag_color(normalized))
    return list_tag_shortcuts(library_id)


def tag_shortcuts_initialized(library_id: str) -> bool:
    return bool(get_preference(library_id, TAG_SHORTCUTS_INITIALIZED_KEY, False))


def mark_tag_shortcuts_initialized(library_id: str) -> None:
    set_preference(library_id, TAG_SHORTCUTS_INITIALIZED_KEY, True)


def upsert_tag_shortcut(library_id: str, tag: str, color: str) -> dict[str, Any]:
    ensure_app_store()
    clean_tag = normalize_hash_tag(tag)
    if not clean_tag:
        raise ValueError("标签不能为空。")
    timestamp = now_iso()
    record = {
        "library_id": library_id,
        "tag": clean_tag,
        "color": color,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM tag_shortcuts WHERE library_id = ? AND tag = ?",
            (library_id, clean_tag),
        ).fetchone()
        if existing:
            record["created_at"] = existing["created_at"]
        conn.execute(
            """
            INSERT INTO tag_shortcuts (library_id, tag, color, created_at, updated_at)
            VALUES (:library_id, :tag, :color, :created_at, :updated_at)
            ON CONFLICT(library_id, tag) DO UPDATE SET
              color = excluded.color,
              updated_at = excluded.updated_at
            """,
            record,
        )
        conn.commit()
    return record


def delete_tag_shortcut(library_id: str, tag: str) -> None:
    ensure_app_store()
    normalized = normalize_hash_tag(tag)
    raw_without_hash = normalized[1:] if normalized.startswith("#") else normalized
    with connect() as conn:
        conn.execute(
            "DELETE FROM tag_shortcuts WHERE library_id = ? AND tag IN (?, ?, ?)",
            (library_id, tag, normalized, raw_without_hash),
        )
        conn.commit()


def unsynced_count(library_id: str) -> int:
    ensure_app_store()
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM sync_journal WHERE library_id = ? AND status IN ('pending', 'conflicted')",
            (library_id,),
        ).fetchone()
        return int(row["count"] if row else 0)


def pending_journal(library_id: str) -> list[dict[str, Any]]:
    ensure_app_store()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_journal WHERE library_id = ? AND status IN ('pending', 'conflicted') ORDER BY journal_id",
            (library_id,),
        ).fetchall()
    values = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except json.JSONDecodeError:
            item["payload"] = {}
        values.append(item)
    return values


def mark_conflicted(library_id: str, journal_id: int) -> None:
    ensure_app_store()
    with connect() as conn:
        conn.execute("UPDATE sync_journal SET status = 'conflicted' WHERE library_id = ? AND journal_id = ?", (library_id, journal_id))
        conn.commit()


def app_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()
