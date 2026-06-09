from __future__ import annotations

import sqlite3
import shutil
import mimetypes
import re
from contextlib import closing
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import app_store
from .metadata_import import (
    ImportedCreator,
    ImportedItem,
    normalize_ads_bibcode,
    normalize_arxiv_id,
    normalize_doi,
    normalize_isbn,
    normalize_pmcid,
    normalize_pmid,
)
from .semantic_tags import first_value, normalize_hash_tag, parse_tags, rating_tag, stable_tag_color
from .structured_text import extract_structured_fields, source_field_for_block, upsert_block
from .sources import ensure_editable, sqlite_path_for, storage_path_for
from .utils import new_key, now_iso


def connect_zotero(db_path: Path, *, read_only: bool = True) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def import_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(result.get("status", "failed") for result in results)
    return {
        "results": results,
        "created_count": counts.get("created", 0),
        "existing_count": counts.get("existing", 0),
        "conflict_count": counts.get("conflict", 0),
        "failed_count": counts.get("failed", 0),
    }


def safe_attachment_filename(filename: str) -> str:
    value = Path(str(filename or "")).name.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "attachment"


class ZoteroRepository:
    def __init__(self, library: dict[str, Any]) -> None:
        self.library = library
        self.db_path = sqlite_path_for(library)
        self.storage_path = storage_path_for(library)

    def read_conn(self) -> sqlite3.Connection:
        return closing(connect_zotero(self.db_path, read_only=True))

    def write_conn(self) -> sqlite3.Connection:
        ensure_editable(self.library)
        return closing(connect_zotero(self.db_path, read_only=False))

    def schema_tables(self) -> set[str]:
        with self.read_conn() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {row["name"] for row in rows}

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    def _ensure_tag(self, conn: sqlite3.Connection, tag: str) -> int:
        tag_row = conn.execute("SELECT tagID FROM tags WHERE name = ?", (tag,)).fetchone()
        if tag_row:
            return int(tag_row["tagID"])
        conn.execute("INSERT INTO tags (name) VALUES (?)", (tag,))
        return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

    def _attach_tag_to_item(self, conn: sqlite3.Connection, item_id: int, tag_id: int) -> None:
        columns = self._table_columns(conn, "itemTags")
        if "type" in columns:
            conn.execute("INSERT OR IGNORE INTO itemTags (itemID, tagID, type) VALUES (?, ?, 0)", (item_id, tag_id))
        else:
            conn.execute("INSERT OR IGNORE INTO itemTags (itemID, tagID) VALUES (?, ?)", (item_id, tag_id))

    def collections(self) -> list[dict[str, Any]]:
        with self.read_conn() as conn:
            if "collections" not in self.schema_tables():
                return []
            rows = conn.execute(
                """
                SELECT collectionID, collectionName, parentCollectionID, key
                FROM collections
                ORDER BY parentCollectionID IS NOT NULL, collectionName COLLATE NOCASE
                """
            ).fetchall()
        return [
            {
                "collection_id": row["collectionID"],
                "key": row["key"] or str(row["collectionID"]),
                "name": row["collectionName"] or "未命名文件夹",
                "parent_id": row["parentCollectionID"],
            }
            for row in rows
        ]

    def _fields_by_item(self, conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
        rows = conn.execute(
            """
            SELECT d.itemID, f.fieldName, v.value
            FROM itemData d
            JOIN fields f ON f.fieldID = d.fieldID
            JOIN itemDataValues v ON v.valueID = d.valueID
            """
        ).fetchall()
        fields: dict[int, dict[str, str]] = defaultdict(dict)
        for row in rows:
            fields[int(row["itemID"])][row["fieldName"]] = row["value"] or ""
        return fields

    def _field_value(self, conn: sqlite3.Connection, item_id: int, field_id: int) -> str:
        row = conn.execute(
            """
            SELECT v.value FROM itemData d
            JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE d.itemID = ? AND d.fieldID = ?
            """,
            (item_id, field_id),
        ).fetchone()
        return row["value"] if row else ""

    def _field_id(self, conn: sqlite3.Connection, field_name: str) -> int:
        field = conn.execute("SELECT fieldID FROM fields WHERE fieldName = ?", (field_name,)).fetchone()
        if not field:
            raise ValueError(f"Zotero 原生字段不存在：{field_name}")
        return int(field["fieldID"])

    def _set_field_value(self, conn: sqlite3.Connection, item_id: int, field_id: int, value: str) -> None:
        value_row = conn.execute("SELECT valueID FROM itemDataValues WHERE value = ?", (value,)).fetchone()
        if value_row:
            value_id = value_row["valueID"]
        else:
            conn.execute("INSERT INTO itemDataValues (value) VALUES (?)", (value,))
            value_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute("DELETE FROM itemData WHERE itemID = ? AND fieldID = ?", (item_id, field_id))
        conn.execute("INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)", (item_id, field_id, value_id))

    def _optional_field_id(self, conn: sqlite3.Connection, field_name: str) -> int | None:
        field = conn.execute("SELECT fieldID FROM fields WHERE fieldName = ?", (field_name,)).fetchone()
        return int(field["fieldID"]) if field else None

    def _item_type_id(self, conn: sqlite3.Connection, item_type: str) -> int:
        preferred = [item_type, "document", "journalArticle"]
        for type_name in preferred:
            row = conn.execute("SELECT itemTypeID FROM itemTypes WHERE typeName = ?", (type_name,)).fetchone()
            if row:
                return int(row["itemTypeID"])
        row = conn.execute("SELECT itemTypeID FROM itemTypes WHERE typeName NOT IN ('attachment', 'note', 'annotation') ORDER BY itemTypeID LIMIT 1").fetchone()
        if not row:
            raise ValueError("Zotero 条目类型表为空，无法创建条目。")
        return int(row["itemTypeID"])

    def _insert_item(self, conn: sqlite3.Connection, item_type: str, item_key: str, timestamp: str) -> int:
        item_columns = self._table_columns(conn, "items")
        payload: dict[str, Any] = {
            "itemTypeID": self._item_type_id(conn, item_type),
            "dateAdded": timestamp,
            "dateModified": timestamp,
            "clientDateModified": timestamp,
            "libraryID": 1,
            "key": item_key,
            "version": 0,
            "synced": 0,
        }
        insert_payload = {key: value for key, value in payload.items() if key in item_columns}
        columns_sql = ", ".join(insert_payload)
        placeholders = ", ".join(f":{key}" for key in insert_payload)
        conn.execute(f"INSERT INTO items ({columns_sql}) VALUES ({placeholders})", insert_payload)
        return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

    def _creator_type_id(self, conn: sqlite3.Connection, creator_type: str = "author") -> int | None:
        if "creatorTypes" not in self.schema_tables():
            return None
        row = conn.execute("SELECT creatorTypeID FROM creatorTypes WHERE creatorType = ?", (creator_type,)).fetchone()
        if row:
            return int(row["creatorTypeID"])
        row = conn.execute("SELECT creatorTypeID FROM creatorTypes WHERE creatorType = 'author'").fetchone()
        if row:
            return int(row["creatorTypeID"])
        row = conn.execute("SELECT creatorTypeID FROM creatorTypes ORDER BY creatorTypeID LIMIT 1").fetchone()
        return int(row["creatorTypeID"]) if row else None

    def _ensure_creator(self, conn: sqlite3.Connection, creator: ImportedCreator) -> int:
        first_name = creator.first_name or ""
        last_name = creator.last_name or ""
        field_mode = 0 if first_name else 1
        row = conn.execute(
            "SELECT creatorID FROM creators WHERE firstName = ? AND lastName = ? AND fieldMode = ?",
            (first_name, last_name, field_mode),
        ).fetchone()
        if row:
            return int(row["creatorID"])
        conn.execute("INSERT INTO creators (firstName, lastName, fieldMode) VALUES (?, ?, ?)", (first_name, last_name, field_mode))
        return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

    def _creators_by_item(self, conn: sqlite3.Connection) -> dict[int, list[dict[str, str]]]:
        if "creators" not in self.schema_tables():
            return {}
        rows = conn.execute(
            """
            SELECT ic.itemID, c.firstName, c.lastName, c.fieldMode, ct.creatorType, ic.orderIndex
            FROM itemCreators ic
            JOIN creators c ON c.creatorID = ic.creatorID
            LEFT JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
            ORDER BY ic.itemID, ic.orderIndex
            """
        ).fetchall()
        creators: dict[int, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            name = row["lastName"] if row["fieldMode"] == 1 else " ".join([row["firstName"] or "", row["lastName"] or ""]).strip()
            creators[int(row["itemID"])].append({"name": name, "type": row["creatorType"] or "creator"})
        return creators

    def _tags_by_item(self, conn: sqlite3.Connection) -> dict[int, list[str]]:
        if "tags" not in self.schema_tables():
            return {}
        rows = conn.execute(
            """
            SELECT it.itemID, t.name
            FROM itemTags it
            JOIN tags t ON t.tagID = it.tagID
            ORDER BY t.name COLLATE NOCASE
            """
        ).fetchall()
        tags: dict[int, list[str]] = defaultdict(list)
        for row in rows:
            tags[int(row["itemID"])].append(row["name"] or "")
        return tags

    def _collections_by_item(self, conn: sqlite3.Connection) -> dict[int, list[dict[str, Any]]]:
        if "collectionItems" not in self.schema_tables():
            return {}
        rows = conn.execute(
            """
            SELECT ci.itemID, c.collectionID, c.collectionName, c.key
            FROM collectionItems ci
            JOIN collections c ON c.collectionID = ci.collectionID
            ORDER BY c.collectionName COLLATE NOCASE
            """
        ).fetchall()
        values: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            values[int(row["itemID"])].append(
                {"collection_id": row["collectionID"], "key": row["key"] or str(row["collectionID"]), "name": row["collectionName"] or ""}
            )
        return values

    def _attachments_by_parent(self, conn: sqlite3.Connection) -> dict[int, list[dict[str, Any]]]:
        if "itemAttachments" not in self.schema_tables():
            return {}
        rows = conn.execute(
            """
            SELECT a.parentItemID, a.itemID, a.path, a.contentType, a.linkMode, i.key, i.dateAdded, v.value AS title
            FROM itemAttachments a
            JOIN items i ON i.itemID = a.itemID
            LEFT JOIN itemData d ON d.itemID = i.itemID AND d.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
            LEFT JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE a.parentItemID IS NOT NULL
            ORDER BY i.dateAdded
            """
        ).fetchall()
        attachments: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            path = row["path"] or ""
            resolved = self.resolve_attachment_path(row["key"], path)
            kind = self.attachment_kind(path, row["contentType"] or "", row["linkMode"])
            exists = bool(resolved and Path(resolved).exists())
            status = "openable" if exists else ("external" if kind in {"link", "external"} else "missing")
            attachments[int(row["parentItemID"])].append(
                {
                    "item_id": row["itemID"],
                    "key": row["key"],
                    "path": path,
                    "display_label": self.attachment_label(path, row["title"] or ""),
                    "resolved_path": str(resolved) if resolved else "",
                    "content_type": row["contentType"] or "",
                    "link_mode": row["linkMode"],
                    "kind": kind,
                    "status": status,
                    "openable": exists,
                }
            )
        return attachments

    def _notes_by_parent(self, conn: sqlite3.Connection) -> dict[int, list[dict[str, Any]]]:
        if "itemNotes" not in self.schema_tables():
            return {}
        rows = conn.execute(
            """
            SELECT n.parentItemID, n.itemID, n.note, i.key
            FROM itemNotes n
            JOIN items i ON i.itemID = n.itemID
            WHERE n.parentItemID IS NOT NULL
            ORDER BY i.dateAdded
            """
        ).fetchall()
        notes: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            notes[int(row["parentItemID"])].append({"item_id": row["itemID"], "key": row["key"], "note": row["note"] or ""})
        return notes

    def resolve_attachment_path(self, attachment_key: str, path: str) -> Path | None:
        if not path:
            return None
        if path.startswith("storage:"):
            return self.storage_path / attachment_key / path.replace("storage:", "", 1)
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.storage_path / attachment_key / path

    def attachment_kind(self, path: str, content_type: str, link_mode: int | None) -> str:
        lower_path = (path or "").lower()
        lower_type = (content_type or "").lower()
        if lower_path.startswith(("http://", "https://")):
            return "link"
        if link_mode in {2, 3}:
            return "external"
        if lower_type == "application/pdf" or lower_path.endswith(".pdf"):
            return "pdf"
        if "html" in lower_type or lower_path.endswith((".html", ".htm")):
            return "html"
        if lower_type.startswith("image/") or lower_path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            return "image"
        return "file"

    def attachment_label(self, path: str, title: str) -> str:
        if title:
            return title
        if path.startswith("storage:"):
            return path.replace("storage:", "", 1)
        return Path(path).name if path else "Attachment"

    def attachment_badges(self, attachments: list[dict[str, Any]], notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: Counter[tuple[str, bool]] = Counter()
        for attachment in attachments:
            kind = attachment.get("kind") or "file"
            label = {"pdf": "PDF", "html": "HTML", "image": "Image", "link": "Link", "external": "Link"}.get(kind, "File")
            counts[(label, attachment.get("status") == "missing")] += 1
        if notes:
            counts[("Note", False)] += len(notes)
        return [{"label": label, "count": count, "missing": missing} for (label, missing), count in counts.items()]

    def nested_tags(self, items: list[dict[str, Any]] | None = None) -> list[str]:
        values = items if items is not None else self.items()
        tags: list[str] = []
        seen: set[str] = set()
        for item in values:
            for tag in item.get("semantic", {}).get("nested", []):
                normalized = normalize_hash_tag(tag)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                tags.append(normalized)
        return tags

    def ensure_tag_shortcuts_seeded(self, items: list[dict[str, Any]] | None = None, *, force: bool = False) -> list[dict[str, Any]]:
        existing = app_store.list_tag_shortcuts(self.library["library_id"])
        initialized = app_store.tag_shortcuts_initialized(self.library["library_id"])
        if initialized and not force:
            return existing
        app_store.ensure_tag_shortcuts(self.library["library_id"], self.nested_tags(items))
        app_store.mark_tag_shortcuts_initialized(self.library["library_id"])
        return app_store.list_tag_shortcuts(self.library["library_id"])

    def items(self) -> list[dict[str, Any]]:
        with self.read_conn() as conn:
            fields = self._fields_by_item(conn)
            creators = self._creators_by_item(conn)
            tags = self._tags_by_item(conn)
            collections = self._collections_by_item(conn)
            attachments = self._attachments_by_parent(conn)
            notes = self._notes_by_parent(conn)
            deleted_join = "LEFT JOIN deletedItems di ON di.itemID = i.itemID" if "deletedItems" in self.schema_tables() else ""
            deleted_select = "CASE WHEN di.itemID IS NULL THEN 0 ELSE 1 END AS deleted" if "deletedItems" in self.schema_tables() else "0 AS deleted"
            rows = conn.execute(
                f"""
                SELECT i.itemID, i.key, i.dateAdded, i.dateModified, t.typeName, {deleted_select}
                FROM items i
                JOIN itemTypes t ON t.itemTypeID = i.itemTypeID
                {deleted_join}
                WHERE t.typeName NOT IN ('attachment', 'note', 'annotation')
                ORDER BY i.dateModified DESC, i.itemID DESC
                """
            ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            item_id = int(row["itemID"])
            item_fields = fields.get(item_id, {})
            item_tags = tags.get(item_id, [])
            semantic = parse_tags(item_tags, app_store.list_semantic_rules(self.library["library_id"])).as_dict()
            creator_values = creators.get(item_id, [])
            creator_names = [creator["name"] for creator in creator_values if creator.get("name")]
            item_attachments = attachments.get(item_id, [])
            item_notes = notes.get(item_id, [])
            venue = item_fields.get("publicationTitle") or item_fields.get("proceedingsTitle") or item_fields.get("conferenceName") or item_fields.get("repository") or ""
            year = (item_fields.get("date") or "")[:4]
            structured = extract_structured_fields(item_fields.get("extra", ""), item_fields.get("abstractNote", ""))
            values.append(
                {
                    "item_id": item_id,
                    "key": row["key"],
                    "type": row["typeName"],
                    "title": item_fields.get("title", "未命名文献"),
                    "fields": item_fields,
                    "structured": structured,
                    "creators": creator_values,
                    "creator_names": creator_names,
                    "creators_display": creator_names[0] if creator_names else "",
                    "creators_full_display": " / ".join(creator_names),
                    "year": year,
                    "venue": venue,
                    "tags": item_tags,
                    "semantic": semantic,
                    "tag_colors": {tag: stable_tag_color(tag) for tag in semantic["nested"] + semantic["plain"]},
                    "rating": first_value(semantic["rating"]),
                    "collections": collections.get(item_id, []),
                    "attachments": item_attachments,
                    "notes": item_notes,
                    "attachment_badges": self.attachment_badges(item_attachments, item_notes),
                    "deleted": bool(row["deleted"]),
                    "date_added": row["dateAdded"],
                    "date_modified": row["dateModified"],
                }
            )
        return values

    def state(self) -> dict[str, Any]:
        items = self.items()
        collections = self.collections()
        tag_shortcuts = self.ensure_tag_shortcuts_seeded(items)
        tag_counts = Counter(tag for item in items for tag in item["tags"])
        semantic_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for item in items:
            for bucket, values in item["semantic"].items():
                if bucket == "raw":
                    continue
                for value in values:
                    semantic_counts[bucket][value] += 1
        return {
            "library": {
                **self.library,
                "editable": self.library.get("mode") == "local_copy",
                "unsynced_count": app_store.unsynced_count(self.library["library_id"]),
                "columns": app_store.column_preference(self.library["library_id"]),
                "column_widths": app_store.column_width_preference(self.library["library_id"]),
                "plain_tags_collapsed": app_store.plain_tags_collapsed(self.library["library_id"]),
            },
            "collections": collections,
            "items": items,
            "tag_counts": dict(tag_counts),
            "semantic_counts": {key: dict(counter) for key, counter in semantic_counts.items()},
            "tag_shortcuts": tag_shortcuts,
        }

    def _metadata_identifiers(self, metadata: ImportedItem | dict[str, Any]) -> dict[str, str]:
        if isinstance(metadata, ImportedItem):
            fields = metadata.fields
            identifiers = metadata.identifiers
        else:
            fields = metadata.get("fields", {}) or {}
            identifiers = metadata.get("identifiers", {}) or {}
        haystack = "\n".join(str(value or "") for value in fields.values())
        values = {
            "doi": normalize_doi(identifiers.get("doi", "") or fields.get("DOI", "") or haystack),
            "pmid": normalize_pmid(identifiers.get("pmid", "") or fields.get("PMID", "") or fields.get("extra", "")),
            "pmcid": normalize_pmcid(identifiers.get("pmcid", "") or fields.get("PMCID", "") or fields.get("extra", "")),
            "arxiv": normalize_arxiv_id(identifiers.get("arxiv", "") or fields.get("extra", "") or fields.get("url", "") or fields.get("DOI", "")),
            "ads_bibcode": normalize_ads_bibcode(identifiers.get("ads_bibcode", "") or fields.get("extra", "")),
            "isbn": normalize_isbn(identifiers.get("isbn", "") or fields.get("ISBN", "")),
        }
        return {key: value for key, value in values.items() if value}

    def _existing_identifier_index(self, conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
        fields_by_item = self._fields_by_item(conn)
        rows = conn.execute(
            """
            SELECT i.itemID, i.key, t.typeName
            FROM items i
            JOIN itemTypes t ON t.itemTypeID = i.itemTypeID
            WHERE t.typeName NOT IN ('attachment', 'note', 'annotation')
            """
        ).fetchall()
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            item_id = int(row["itemID"])
            fields = fields_by_item.get(item_id, {})
            identifiers = self._metadata_identifiers({"fields": fields, "identifiers": {}})
            title = fields.get("title") or "未命名文献"
            for kind, value in identifiers.items():
                index[f"{kind}:{value}"].append({"item_id": item_id, "key": row["key"], "title": title, "type": row["typeName"]})
        return index

    def _dedupe_candidates(self, conn: sqlite3.Connection, metadata: ImportedItem) -> list[dict[str, Any]]:
        matches: dict[str, dict[str, Any]] = {}
        index = self._existing_identifier_index(conn)
        for kind, value in self._metadata_identifiers(metadata).items():
            for candidate in index.get(f"{kind}:{value}", []):
                matches[candidate["key"]] = candidate
        return list(matches.values())

    def _collection_id_for_key(self, conn: sqlite3.Connection, collection_key: str | None) -> int | None:
        if not collection_key:
            return None
        row = conn.execute("SELECT collectionID FROM collections WHERE key = ?", (collection_key,)).fetchone()
        if not row:
            raise ValueError("目标文件夹不存在。")
        return int(row["collectionID"])

    def _attach_item_to_collection_id(self, conn: sqlite3.Connection, item_id: int, collection_id: int | None) -> None:
        if collection_id is None:
            return
        conn.execute(
            "INSERT OR IGNORE INTO collectionItems (collectionID, itemID, orderIndex) VALUES (?, ?, 0)",
            (collection_id, item_id),
        )

    def _main_item_id_for_key(self, conn: sqlite3.Connection, item_key: str) -> int:
        row = conn.execute(
            """
            SELECT i.itemID
            FROM items i
            JOIN itemTypes t ON t.itemTypeID = i.itemTypeID
            WHERE i.key = ? AND t.typeName NOT IN ('attachment', 'note', 'annotation')
            """,
            (item_key,),
        ).fetchone()
        if not row:
            raise ValueError("主条目不存在。")
        return int(row["itemID"])

    def _attachment_row_for_key(self, conn: sqlite3.Connection, attachment_key: str) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT ia.itemID, ia.parentItemID, ia.linkMode, ia.path, ia.contentType, i.key, v.value AS title
            FROM itemAttachments ia
            JOIN items i ON i.itemID = ia.itemID
            LEFT JOIN itemData d ON d.itemID = i.itemID AND d.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
            LEFT JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE i.key = ?
            """,
            (attachment_key,),
        ).fetchone()
        if not row:
            raise ValueError("附件不存在。")
        return row

    def _unique_storage_filename(self, attachment_dir: Path, filename: str, current_name: str | None = None) -> str:
        safe_name = safe_attachment_filename(filename)
        if current_name and safe_name == current_name:
            return safe_name
        candidate = safe_name
        stem = Path(safe_name).stem or "attachment"
        suffix = Path(safe_name).suffix
        index = 2
        while (attachment_dir / candidate).exists():
            candidate = f"{stem} ({index}){suffix}"
            index += 1
        return candidate

    def _insert_attachment_record(
        self,
        conn: sqlite3.Connection,
        *,
        item_id: int,
        parent_item_id: int,
        link_mode: int,
        path: str,
        content_type: str,
        timestamp: str,
        storage_file: Path | None = None,
    ) -> None:
        columns = self._table_columns(conn, "itemAttachments")
        payload: dict[str, Any] = {
            "itemID": item_id,
            "parentItemID": parent_item_id,
            "linkMode": link_mode,
            "contentType": content_type,
            "charsetID": 1 if content_type.startswith("text/") else None,
            "path": path,
            "syncState": 0,
            "storageModTime": int(storage_file.stat().st_mtime * 1000) if storage_file and storage_file.exists() else None,
            "storageHash": None,
            "lastProcessedModificationTime": None,
            "lastRead": None,
        }
        insert_payload = {key: value for key, value in payload.items() if key in columns}
        columns_sql = ", ".join(insert_payload)
        placeholders = ", ".join(f":{key}" for key in insert_payload)
        conn.execute(f"INSERT INTO itemAttachments ({columns_sql}) VALUES ({placeholders})", insert_payload)

    def _main_item_rows_for_keys(self, conn: sqlite3.Connection, item_keys: list[str]) -> list[sqlite3.Row]:
        keys = [str(key or "").strip() for key in item_keys if str(key or "").strip()]
        if not keys:
            raise ValueError("请先选择条目。")
        placeholders = ", ".join("?" for _ in keys)
        rows = conn.execute(
            f"""
            SELECT i.itemID, i.key
            FROM items i
            JOIN itemTypes t ON t.itemTypeID = i.itemTypeID
            WHERE i.key IN ({placeholders}) AND t.typeName NOT IN ('attachment', 'note', 'annotation')
            """,
            keys,
        ).fetchall()
        if not rows:
            raise ValueError("没有找到可操作的主条目。")
        return rows

    def _descendant_item_ids_for_parents(self, conn: sqlite3.Connection, parent_item_ids: list[int]) -> list[int]:
        if not parent_item_ids:
            return []
        seen: set[int] = set()
        frontier = list(parent_item_ids)
        while frontier:
            placeholders = ", ".join("?" for _ in frontier)
            rows = conn.execute(
                f"""
                SELECT itemID FROM itemAttachments WHERE parentItemID IN ({placeholders})
                UNION
                SELECT itemID FROM itemNotes WHERE parentItemID IN ({placeholders})
                """,
                [*frontier, *frontier],
            ).fetchall()
            next_frontier = [int(row["itemID"]) for row in rows if int(row["itemID"]) not in seen]
            seen.update(next_frontier)
            frontier = next_frontier
        return list(seen)

    def _attachment_storage_dirs_for_item_ids(self, conn: sqlite3.Connection, attachment_item_ids: list[int]) -> list[Path]:
        if not attachment_item_ids:
            return []
        placeholders = ", ".join("?" for _ in attachment_item_ids)
        rows = conn.execute(
            f"""
            SELECT i.key, ia.path
            FROM itemAttachments ia
            JOIN items i ON i.itemID = ia.itemID
            WHERE ia.itemID IN ({placeholders})
            """,
            attachment_item_ids,
        ).fetchall()
        storage_root = self.storage_path.resolve()
        paths: list[Path] = []
        for row in rows:
            if not str(row["path"] or "").startswith("storage:"):
                continue
            target = (self.storage_path / str(row["key"])).resolve()
            if storage_root in [target, *target.parents]:
                paths.append(target)
        return paths

    def _collection_descendant_ids(self, conn: sqlite3.Connection, collection_id: int) -> list[int]:
        rows = conn.execute("SELECT collectionID, parentCollectionID FROM collections").fetchall()
        children: dict[int, list[int]] = defaultdict(list)
        for row in rows:
            parent_id = row["parentCollectionID"]
            if parent_id is not None:
                children[int(parent_id)].append(int(row["collectionID"]))
        values = [collection_id]
        index = 0
        while index < len(values):
            values.extend(children.get(values[index], []))
            index += 1
        return values

    def _insert_imported_item(self, conn: sqlite3.Connection, metadata: ImportedItem, collection_id: int | None) -> dict[str, Any]:
        item_key = new_key()
        timestamp = now_iso()
        item_id = self._insert_item(conn, metadata.item_type, item_key, timestamp)

        fields = {key: str(value or "") for key, value in metadata.fields.items() if str(value or "")}
        if not fields.get("title"):
            fields["title"] = "未命名导入条目"
        skipped_fields: list[str] = []
        for field_name, value in fields.items():
            field_id = self._optional_field_id(conn, field_name)
            if field_id is None:
                skipped_fields.append(field_name)
                continue
            self._set_field_value(conn, item_id, field_id, value)

        creator_type_columns = self._table_columns(conn, "itemCreators") if "itemCreators" in self.schema_tables() else set()
        for index, creator in enumerate(metadata.creators):
            if not creator.last_name:
                continue
            creator_id = self._ensure_creator(conn, creator)
            creator_type_id = self._creator_type_id(conn, creator.creator_type)
            if creator_type_id is None:
                continue
            creator_payload = {
                "itemID": item_id,
                "creatorID": creator_id,
                "creatorTypeID": creator_type_id,
                "orderIndex": index,
            }
            creator_insert = {key: value for key, value in creator_payload.items() if key in creator_type_columns}
            if not creator_insert:
                continue
            conn.execute(
                f"INSERT INTO itemCreators ({', '.join(creator_insert)}) VALUES ({', '.join('?' for _ in creator_insert)})",
                tuple(creator_insert.values()),
            )

        for tag in metadata.tags:
            tag_name = str(tag or "").strip()
            if tag_name:
                self._attach_tag_to_item(conn, item_id, self._ensure_tag(conn, tag_name))

        self._attach_item_to_collection_id(conn, item_id, collection_id)
        return {
            "status": "created",
            "item_key": item_key,
            "title": fields.get("title", ""),
            "source": metadata.source,
            "identifiers": self._metadata_identifiers(metadata),
            "skipped_fields": skipped_fields,
        }

    def import_metadata_items(self, metadata_items: list[ImportedItem], collection_key: str | None = None) -> dict[str, Any]:
        ensure_editable(self.library)
        if not metadata_items:
            raise ValueError("没有可导入的条目。")
        results: list[dict[str, Any]] = []
        with self.write_conn() as conn:
            collection_id = self._collection_id_for_key(conn, collection_key)
            for metadata in metadata_items:
                candidates = self._dedupe_candidates(conn, metadata)
                if len(candidates) == 1:
                    self._attach_item_to_collection_id(conn, int(candidates[0]["item_id"]), collection_id)
                    result = {
                        "status": "existing",
                        "item_key": candidates[0]["key"],
                        "title": candidates[0]["title"],
                        "source": metadata.source,
                        "identifiers": self._metadata_identifiers(metadata),
                    }
                    results.append(result)
                    app_store.append_journal(
                        self.library["library_id"],
                        "reuse_imported_item",
                        "item",
                        candidates[0]["key"],
                        {"collection_key": collection_key, "identifiers": result["identifiers"]},
                    )
                    continue
                if len(candidates) > 1:
                    results.append(
                        {
                            "status": "conflict",
                            "title": metadata.fields.get("title", ""),
                            "source": metadata.source,
                            "identifiers": self._metadata_identifiers(metadata),
                            "candidates": [{key: value for key, value in candidate.items() if key != "item_id"} for candidate in candidates],
                        }
                    )
                    continue
                result = self._insert_imported_item(conn, metadata, collection_id)
                results.append(result)
                app_store.append_journal(
                    self.library["library_id"],
                    "import_item",
                    "item",
                    result["item_key"],
                    {"collection_key": collection_key, "source": metadata.source, "identifiers": result["identifiers"]},
                )
            conn.commit()
        return import_summary(results)

    def add_file_attachment(self, item_key: str, source_path: Path, filename: str | None = None, content_type: str | None = None) -> dict[str, Any]:
        ensure_editable(self.library)
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("上传文件不存在。")
        attachment_key = new_key()
        storage_dir = self.storage_path / attachment_key
        storage_dir.mkdir(parents=True, exist_ok=False)
        target_name = self._unique_storage_filename(storage_dir, filename or source_path.name)
        target_path = storage_dir / target_name
        try:
            shutil.copyfile(source_path, target_path)
            guessed_type = content_type or mimetypes.guess_type(target_name)[0] or "application/octet-stream"
            timestamp = now_iso()
            with self.write_conn() as conn:
                parent_item_id = self._main_item_id_for_key(conn, item_key)
                attachment_item_id = self._insert_item(conn, "attachment", attachment_key, timestamp)
                self._set_field_value(conn, attachment_item_id, self._field_id(conn, "title"), target_name)
                self._insert_attachment_record(
                    conn,
                    item_id=attachment_item_id,
                    parent_item_id=parent_item_id,
                    link_mode=1,
                    path=f"storage:{target_name}",
                    content_type=guessed_type,
                    timestamp=timestamp,
                    storage_file=target_path,
                )
                conn.execute("UPDATE items SET dateModified = ?, synced = 0 WHERE itemID = ?", (timestamp, parent_item_id))
                conn.commit()
        except Exception:
            shutil.rmtree(storage_dir, ignore_errors=True)
            raise
        app_store.append_journal(
            self.library["library_id"],
            "add_file_attachment",
            "attachment",
            attachment_key,
            {"item_key": item_key, "filename": target_name, "content_type": guessed_type},
        )
        return {"attachment_key": attachment_key, "filename": target_name, "content_type": guessed_type}

    def add_url_attachment(self, item_key: str, url: str, title: str | None = None) -> dict[str, Any]:
        ensure_editable(self.library)
        normalized_url = str(url or "").strip()
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError("请输入 http:// 或 https:// 开头的网址。")
        attachment_key = new_key()
        timestamp = now_iso()
        display_title = str(title or "").strip() or normalized_url
        with self.write_conn() as conn:
            parent_item_id = self._main_item_id_for_key(conn, item_key)
            attachment_item_id = self._insert_item(conn, "attachment", attachment_key, timestamp)
            self._set_field_value(conn, attachment_item_id, self._field_id(conn, "title"), display_title)
            url_field_id = self._optional_field_id(conn, "url")
            if url_field_id is not None:
                self._set_field_value(conn, attachment_item_id, url_field_id, normalized_url)
            access_date_field_id = self._optional_field_id(conn, "accessDate")
            if access_date_field_id is not None:
                self._set_field_value(conn, attachment_item_id, access_date_field_id, timestamp)
            self._insert_attachment_record(
                conn,
                item_id=attachment_item_id,
                parent_item_id=parent_item_id,
                link_mode=3,
                path=normalized_url,
                content_type="text/html",
                timestamp=timestamp,
            )
            conn.execute("UPDATE items SET dateModified = ?, synced = 0 WHERE itemID = ?", (timestamp, parent_item_id))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "add_url_attachment",
            "attachment",
            attachment_key,
            {"item_key": item_key, "url": normalized_url, "title": display_title},
        )
        return {"attachment_key": attachment_key, "url": normalized_url, "title": display_title}

    def rename_attachment(self, attachment_key: str, title: str) -> dict[str, Any]:
        ensure_editable(self.library)
        new_title = safe_attachment_filename(title)
        timestamp = now_iso()
        new_path_value = ""
        with self.write_conn() as conn:
            row = self._attachment_row_for_key(conn, attachment_key)
            attachment_item_id = int(row["itemID"])
            old_path = str(row["path"] or "")
            old_filename = old_path.replace("storage:", "", 1) if old_path.startswith("storage:") else ""
            if old_path.startswith("storage:"):
                old_file = self.storage_path / attachment_key / old_filename
                extension = Path(old_filename).suffix
                desired = new_title
                if extension and not Path(desired).suffix:
                    desired = f"{desired}{extension}"
                desired = self._unique_storage_filename(old_file.parent, desired, old_filename)
                new_file = old_file.parent / desired
                if old_file.exists() and old_file.resolve() != new_file.resolve():
                    old_file.rename(new_file)
                new_title = desired
                new_path_value = f"storage:{desired}"
                conn.execute("UPDATE itemAttachments SET path = ? WHERE itemID = ?", (new_path_value, attachment_item_id))
            self._set_field_value(conn, attachment_item_id, self._field_id(conn, "title"), new_title)
            conn.execute("UPDATE items SET dateModified = ?, synced = 0 WHERE itemID = ?", (timestamp, attachment_item_id))
            if row["parentItemID"]:
                conn.execute("UPDATE items SET dateModified = ?, synced = 0 WHERE itemID = ?", (timestamp, row["parentItemID"]))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "rename_attachment",
            "attachment",
            attachment_key,
            {"title": new_title, "path": new_path_value},
        )
        return {"attachment_key": attachment_key, "title": new_title, "path": new_path_value}

    def delete_attachments(self, attachment_keys: list[str]) -> dict[str, Any]:
        ensure_editable(self.library)
        keys = [str(key or "").strip() for key in attachment_keys if str(key or "").strip()]
        if not keys:
            raise ValueError("请选择附件。")
        removed_storage = 0
        deleted_keys: list[str] = []
        storage_dirs: list[Path] = []
        with self.write_conn() as conn:
            rows = [self._attachment_row_for_key(conn, key) for key in keys]
            item_ids = [int(row["itemID"]) for row in rows]
            deleted_keys = [str(row["key"]) for row in rows]
            storage_dirs = self._attachment_storage_dirs_for_item_ids(conn, item_ids)
            placeholders = ", ".join("?" for _ in item_ids)
            for table in ("itemData", "itemTags", "itemCreators", "collectionItems", "deletedItems"):
                if table in self.schema_tables():
                    conn.execute(f"DELETE FROM {table} WHERE itemID IN ({placeholders})", item_ids)
            conn.execute(f"DELETE FROM itemAttachments WHERE itemID IN ({placeholders})", item_ids)
            conn.execute(f"DELETE FROM items WHERE itemID IN ({placeholders})", item_ids)
            parent_ids = sorted({int(row["parentItemID"]) for row in rows if row["parentItemID"]})
            if parent_ids:
                parent_placeholders = ", ".join("?" for _ in parent_ids)
                conn.execute(f"UPDATE items SET dateModified = ?, synced = 0 WHERE itemID IN ({parent_placeholders})", [now_iso(), *parent_ids])
            conn.commit()
        for storage_dir in storage_dirs:
            if storage_dir.exists():
                shutil.rmtree(storage_dir)
                removed_storage += 1
        app_store.append_journal(
            self.library["library_id"],
            "delete_attachments",
            "attachment",
            ",".join(deleted_keys),
            {"attachment_keys": deleted_keys, "removed_storage_dirs": removed_storage},
        )
        return {"deleted_count": len(deleted_keys), "attachment_keys": deleted_keys, "removed_storage_dirs": removed_storage}

    def create_collection(self, name: str, parent_key: str | None = None) -> dict[str, Any]:
        ensure_editable(self.library)
        key = new_key()
        with self.write_conn() as conn:
            parent_id = None
            if parent_key:
                row = conn.execute("SELECT collectionID FROM collections WHERE key = ?", (parent_key,)).fetchone()
                parent_id = row["collectionID"] if row else None
            conn.execute(
                """
                INSERT INTO collections (collectionName, parentCollectionID, libraryID, key, version, synced)
                VALUES (?, ?, 1, ?, 0, 0)
                """,
                (name, parent_id, key),
            )
            conn.commit()
        app_store.append_journal(self.library["library_id"], "create_collection", "collection", key, {"name": name, "parent_key": parent_key})
        return {"key": key, "name": name, "parent_key": parent_key}

    def rename_collection(self, key: str, name: str) -> None:
        ensure_editable(self.library)
        with self.write_conn() as conn:
            row = conn.execute("SELECT collectionName FROM collections WHERE key = ?", (key,)).fetchone()
            old_name = row["collectionName"] if row else ""
            conn.execute("UPDATE collections SET collectionName = ?, synced = 0 WHERE key = ?", (name, key))
            conn.commit()
        app_store.append_journal(self.library["library_id"], "rename_collection", "collection", key, {"old": old_name, "new": name})

    def reparent_collection(self, key: str, parent_key: str | None) -> None:
        ensure_editable(self.library)
        with self.write_conn() as conn:
            current = conn.execute("SELECT collectionID, parentCollectionID FROM collections WHERE key = ?", (key,)).fetchone()
            if not current:
                raise ValueError("文件夹不存在。")
            parent_id = None
            if parent_key:
                parent = conn.execute("SELECT collectionID FROM collections WHERE key = ?", (parent_key,)).fetchone()
                if not parent:
                    raise ValueError("父文件夹不存在。")
                parent_id = parent["collectionID"]
            conn.execute("UPDATE collections SET parentCollectionID = ?, synced = 0 WHERE key = ?", (parent_id, key))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "reparent_collection",
            "collection",
            key,
            {"old_parent_id": current["parentCollectionID"], "new_parent_key": parent_key},
        )

    def delete_collection(self, key: str) -> dict[str, Any]:
        ensure_editable(self.library)
        with self.write_conn() as conn:
            current = conn.execute("SELECT collectionID, collectionName FROM collections WHERE key = ?", (key,)).fetchone()
            if not current:
                raise ValueError("文件夹不存在。")
            collection_ids = self._collection_descendant_ids(conn, int(current["collectionID"]))
            placeholders = ", ".join("?" for _ in collection_ids)
            conn.execute(f"DELETE FROM collectionItems WHERE collectionID IN ({placeholders})", collection_ids)
            conn.execute(f"DELETE FROM collections WHERE collectionID IN ({placeholders})", collection_ids)
            conn.commit()
        result = {"collection_key": key, "deleted_count": len(collection_ids), "name": current["collectionName"]}
        app_store.append_journal(self.library["library_id"], "delete_collection", "collection", key, result)
        return result

    def move_items(self, item_keys: list[str], target_collection_key: str) -> dict[str, Any]:
        ensure_editable(self.library)
        if not target_collection_key:
            raise ValueError("请选择目标文件夹。")
        with self.write_conn() as conn:
            collection_id = self._collection_id_for_key(conn, target_collection_key)
            rows = self._main_item_rows_for_keys(conn, item_keys)
            item_ids = [int(row["itemID"]) for row in rows]
            placeholders = ", ".join("?" for _ in item_ids)
            conn.execute(f"DELETE FROM collectionItems WHERE itemID IN ({placeholders})", item_ids)
            for item_id in item_ids:
                self._attach_item_to_collection_id(conn, item_id, collection_id)
            timestamp = now_iso()
            conn.execute(f"UPDATE items SET dateModified = ?, synced = 0 WHERE itemID IN ({placeholders})", [timestamp, *item_ids])
            conn.commit()
        moved_keys = [row["key"] for row in rows]
        app_store.append_journal(
            self.library["library_id"],
            "move_items",
            "item",
            ",".join(moved_keys),
            {"item_keys": moved_keys, "target_collection_key": target_collection_key},
        )
        return {"moved_count": len(moved_keys), "item_keys": moved_keys, "target_collection_key": target_collection_key}

    def delete_items(self, item_keys: list[str], mode: str = "trash") -> dict[str, Any]:
        ensure_editable(self.library)
        normalized_mode = str(mode or "trash").strip().lower()
        if normalized_mode not in {"trash", "permanent"}:
            raise ValueError("未知删除方式。")
        storage_dirs: list[Path] = []
        with self.write_conn() as conn:
            rows = self._main_item_rows_for_keys(conn, item_keys)
            item_ids = [int(row["itemID"]) for row in rows]
            keys = [str(row["key"]) for row in rows]
            placeholders = ", ".join("?" for _ in item_ids)
            timestamp = now_iso()
            if normalized_mode == "trash":
                for item_id in item_ids:
                    conn.execute("INSERT OR IGNORE INTO deletedItems (itemID) VALUES (?)", (item_id,))
                conn.execute(f"UPDATE items SET dateModified = ?, synced = 0 WHERE itemID IN ({placeholders})", [timestamp, *item_ids])
            else:
                child_ids = self._descendant_item_ids_for_parents(conn, item_ids)
                storage_dirs = self._attachment_storage_dirs_for_item_ids(conn, child_ids)
                all_item_ids = [*item_ids, *child_ids]
                all_placeholders = ", ".join("?" for _ in all_item_ids)
                for table in ("itemData", "itemTags", "itemCreators", "collectionItems", "deletedItems"):
                    if table in self.schema_tables():
                        conn.execute(f"DELETE FROM {table} WHERE itemID IN ({all_placeholders})", all_item_ids)
                if "itemAttachments" in self.schema_tables():
                    conn.execute(f"DELETE FROM itemAttachments WHERE itemID IN ({all_placeholders}) OR parentItemID IN ({placeholders})", [*all_item_ids, *item_ids])
                if "itemNotes" in self.schema_tables():
                    conn.execute(f"DELETE FROM itemNotes WHERE itemID IN ({all_placeholders}) OR parentItemID IN ({placeholders})", [*all_item_ids, *item_ids])
                conn.execute(f"DELETE FROM items WHERE itemID IN ({all_placeholders})", all_item_ids)
            conn.commit()
        removed_storage = 0
        for storage_dir in storage_dirs:
            if storage_dir.exists():
                shutil.rmtree(storage_dir)
                removed_storage += 1
        app_store.append_journal(
            self.library["library_id"],
            "trash_items" if normalized_mode == "trash" else "permanent_delete_items",
            "item",
            ",".join(keys),
            {"item_keys": keys, "mode": normalized_mode, "removed_storage_dirs": removed_storage},
        )
        return {"deleted_count": len(keys), "item_keys": keys, "mode": normalized_mode, "removed_storage_dirs": removed_storage}

    def update_item_field(self, item_key: str, field_name: str, value: str) -> None:
        ensure_editable(self.library)
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            if not item:
                raise ValueError("条目不存在。")
            field_id = self._field_id(conn, field_name)
            old_value = self._field_value(conn, int(item["itemID"]), field_id)
            self._set_field_value(conn, int(item["itemID"]), field_id, value)
            conn.execute("UPDATE items SET dateModified = ?, synced = 0 WHERE itemID = ?", (now_iso(), item["itemID"]))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "update_item_field",
            "item",
            item_key,
            {"field": field_name, "old": old_value, "new": value},
        )

    def update_structured_field(self, item_key: str, block_key: str, value: str) -> None:
        ensure_editable(self.library)
        field_name = source_field_for_block(block_key)
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            if not item:
                raise ValueError("条目不存在。")
            field_id = self._field_id(conn, field_name)
            old_raw = self._field_value(conn, int(item["itemID"]), field_id)
            new_raw = upsert_block(old_raw, block_key, value)
            self._set_field_value(conn, int(item["itemID"]), field_id, new_raw)
            conn.execute("UPDATE items SET dateModified = ?, synced = 0 WHERE itemID = ?", (now_iso(), item["itemID"]))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "update_structured_field",
            "item",
            item_key,
            {"block": block_key, "field": field_name, "new": value},
        )

    def add_tag(self, item_key: str, tag: str) -> None:
        ensure_editable(self.library)
        tag = normalize_hash_tag(tag)
        if not tag:
            raise ValueError("标签不能为空。")
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            if not item:
                raise ValueError("条目不存在。")
            tag_id = self._ensure_tag(conn, tag)
            self._attach_tag_to_item(conn, int(item["itemID"]), tag_id)
            conn.execute("UPDATE items SET synced = 0 WHERE itemID = ?", (item["itemID"],))
            conn.commit()
        app_store.append_journal(self.library["library_id"], "add_tag", "item", item_key, {"tag": tag})

    def remove_tag(self, item_key: str, tag: str) -> None:
        ensure_editable(self.library)
        tag = normalize_hash_tag(tag)
        if not tag:
            raise ValueError("标签不能为空。")
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            tag_row = conn.execute("SELECT tagID FROM tags WHERE name = ?", (tag,)).fetchone()
            if item and tag_row:
                conn.execute("DELETE FROM itemTags WHERE itemID = ? AND tagID = ?", (item["itemID"], tag_row["tagID"]))
                conn.execute("UPDATE items SET synced = 0 WHERE itemID = ?", (item["itemID"],))
                conn.commit()
        app_store.append_journal(self.library["library_id"], "remove_tag", "item", item_key, {"tag": tag})

    def set_reading_status(self, item_key: str, status: str) -> None:
        ensure_editable(self.library)
        normalized_status = str(status or "").strip().lower()
        target_tag = {"read": "/done", "done": "/done", "reading": "/reading", "unread": ""}.get(normalized_status)
        if target_tag is None:
            raise ValueError("未知阅读状态。")
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            if not item:
                raise ValueError("条目不存在。")
            rows = conn.execute(
                """
                SELECT t.tagID, t.name
                FROM itemTags it
                JOIN tags t ON t.tagID = it.tagID
                WHERE it.itemID = ?
                """,
                (item["itemID"],),
            ).fetchall()
            old_tags = [row["name"] for row in rows if parse_tags([row["name"]]).reading_status]
            for row in rows:
                if parse_tags([row["name"]]).reading_status:
                    conn.execute("DELETE FROM itemTags WHERE itemID = ? AND tagID = ?", (item["itemID"], row["tagID"]))
            if target_tag:
                tag_id = self._ensure_tag(conn, target_tag)
                self._attach_tag_to_item(conn, int(item["itemID"]), tag_id)
            conn.execute("UPDATE items SET synced = 0 WHERE itemID = ?", (item["itemID"],))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "set_reading_status",
            "item",
            item_key,
            {"old": old_tags, "new": target_tag, "status": normalized_status},
        )

    def set_rating(self, item_key: str, value: int) -> None:
        ensure_editable(self.library)
        value = max(0, min(5, int(value)))
        new_tag = rating_tag(value)
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            if not item:
                raise ValueError("条目不存在。")
            rows = conn.execute(
                """
                SELECT t.tagID, t.name
                FROM itemTags it
                JOIN tags t ON t.tagID = it.tagID
                WHERE it.itemID = ?
                """,
                (item["itemID"],),
            ).fetchall()
            old_tags = [row["name"] for row in rows if parse_tags([row["name"]]).rating]
            for row in rows:
                if parse_tags([row["name"]]).rating:
                    conn.execute("DELETE FROM itemTags WHERE itemID = ? AND tagID = ?", (item["itemID"], row["tagID"]))
            if new_tag:
                tag_id = self._ensure_tag(conn, new_tag)
                self._attach_tag_to_item(conn, int(item["itemID"]), tag_id)
            conn.execute("UPDATE items SET synced = 0 WHERE itemID = ?", (item["itemID"],))
            conn.commit()
        app_store.append_journal(self.library["library_id"], "set_rating", "item", item_key, {"old": old_tags, "new": new_tag})

    def set_collection_membership(self, item_key: str, collection_key: str, enabled: bool) -> None:
        ensure_editable(self.library)
        with self.write_conn() as conn:
            item = conn.execute("SELECT itemID FROM items WHERE key = ?", (item_key,)).fetchone()
            collection = conn.execute("SELECT collectionID FROM collections WHERE key = ?", (collection_key,)).fetchone()
            if not item or not collection:
                raise ValueError("条目或文件夹不存在。")
            if enabled:
                conn.execute(
                    "INSERT OR IGNORE INTO collectionItems (collectionID, itemID, orderIndex) VALUES (?, ?, 0)",
                    (collection["collectionID"], item["itemID"]),
                )
            else:
                conn.execute("DELETE FROM collectionItems WHERE collectionID = ? AND itemID = ?", (collection["collectionID"], item["itemID"]))
            conn.commit()
        app_store.append_journal(
            self.library["library_id"],
            "set_collection_membership",
            "item",
            item_key,
            {"collection_key": collection_key, "enabled": enabled},
        )
