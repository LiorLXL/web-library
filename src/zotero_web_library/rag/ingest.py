from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from zotero_web_library.rag.chunking import chunk_markdown, chunk_plain_text, clean_text, html_to_text
from zotero_web_library.rag.embeddings import EmbeddingConfigError, embed_missing_chunks
from zotero_web_library.rag.store import (
    cleanup_orphan_embeddings,
    connect,
    embedding_config,
    ensure_store,
    file_hash,
    insert_asset,
    insert_chunks,
    json_dumps,
    reset_index,
    stable_id,
    text_hash,
    update_config_stats,
    upsert_document,
)
from zotero_web_library.utils import now_iso
from zotero_web_library.zotero_adapter import ZoteroRepository


def creators_text(item: dict[str, Any]) -> str:
    values: list[str] = []
    for creator in item.get("creators") or []:
        if not isinstance(creator, dict):
            continue
        name = " ".join(str(creator.get(key) or "").strip() for key in ("first_name", "last_name")).strip()
        if not name:
            name = str(creator.get("name") or "").strip()
        if name:
            values.append(name)
    return "; ".join(values)


def item_metadata_document(library: dict[str, Any], item: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
    title = str(item.get("title") or fields.get("title") or "")
    abstract = str(fields.get("abstractNote") or "")
    tags = [str(tag) for tag in item.get("tags") or [] if str(tag)]
    creators = creators_text(item)
    parts = [
        f"Title: {title}" if title else "",
        f"Type: {item.get('type')}" if item.get("type") else "",
        f"Year: {item.get('year')}" if item.get("year") else "",
        f"Venue: {item.get('venue')}" if item.get("venue") else "",
        f"Creators: {creators}" if creators else "",
        f"Tags: {', '.join(tags)}" if tags else "",
        f"DOI: {fields.get('DOI')}" if fields.get("DOI") else "",
        f"Abstract: {abstract}" if abstract else "",
    ]
    content = clean_text("\n".join(part for part in parts if part))
    doc_id = f"doc-{stable_id(str(library['library_id']), str(item.get('key')), 'metadata', text_hash(content))}"
    timestamp = now_iso()
    doc = {
        "doc_id": doc_id,
        "library_id": str(library["library_id"]),
        "item_key": str(item.get("key") or ""),
        "attachment_key": "",
        "source_type": "zotero_metadata",
        "source_path": str(Path(str(library["data_path"])) / "zotero.sqlite"),
        "source_relpath": "zotero.sqlite",
        "source_hash": text_hash(content),
        "source_mtime": "",
        "title": title,
        "item_type": str(item.get("type") or ""),
        "year": str(item.get("year") or ""),
        "venue": str(item.get("venue") or ""),
        "creators_text": creators,
        "tags_text": ", ".join(tags),
        "structure_json": "{}",
        "stats_json": "{}",
        "total_chunks": 1 if content else 0,
        "total_assets": 0,
        "total_chars": len(content),
        "index_status": "indexed",
        "created_at": timestamp,
        "updated_at": timestamp,
        "indexed_at": timestamp,
    }
    return doc, chunk_plain_text(content, chunk_type="metadata")


def note_documents(library: dict[str, Any], item: dict[str, Any]) -> list[tuple[dict[str, Any], list[Any], dict[str, Any]]]:
    values: list[tuple[dict[str, Any], list[Any], dict[str, Any]]] = []
    title = str(item.get("title") or "")
    for note in item.get("notes") or []:
        if not isinstance(note, dict):
            continue
        raw = str(note.get("note") or "")
        content = html_to_text(raw)
        if not content:
            continue
        source_id = str(note.get("key") or note.get("item_id") or stable_id(content))
        note_id = f"note-{stable_id(str(library['library_id']), str(item.get('key')), source_id, text_hash(content))}"
        doc_id = f"doc-{stable_id(note_id, 'doc')}"
        timestamp = now_iso()
        note_payload = {
            "note_id": note_id,
            "library_id": str(library["library_id"]),
            "item_key": str(item.get("key") or ""),
            "attachment_key": "",
            "note_type": "zotero_note",
            "source_id": source_id,
            "title": str(note.get("title") or "Zotero note"),
            "content": content,
            "content_hash": text_hash(content),
            "source_json": json_dumps({"zotero_note": {key: note.get(key) for key in ("item_id", "key", "title")}}),
            "created_at": timestamp,
            "updated_at": timestamp,
            "indexed_at": timestamp,
        }
        doc = {
            "doc_id": doc_id,
            "library_id": str(library["library_id"]),
            "item_key": str(item.get("key") or ""),
            "attachment_key": "",
            "source_type": "note",
            "source_path": "zotero:itemNotes",
            "source_relpath": "zotero:itemNotes",
            "source_hash": text_hash(content),
            "source_mtime": "",
            "title": title,
            "item_type": str(item.get("type") or ""),
            "year": str(item.get("year") or ""),
            "venue": str(item.get("venue") or ""),
            "creators_text": creators_text(item),
            "tags_text": ", ".join(str(tag) for tag in item.get("tags") or []),
            "structure_json": "{}",
            "stats_json": "{}",
            "total_chunks": 1,
            "total_assets": 0,
            "total_chars": len(content),
            "index_status": "indexed",
            "created_at": timestamp,
            "updated_at": timestamp,
            "indexed_at": timestamp,
        }
        values.append((doc, chunk_plain_text(content, chunk_type="note"), note_payload))
    return values


def latest_mineru_results(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not root.exists():
        return []
    grouped: dict[tuple[str, str], tuple[Path, dict[str, Any], float]] = {}
    for json_path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        item_key = str(payload.get("item_key") or "")
        attachment = payload.get("attachment") if isinstance(payload.get("attachment"), dict) else {}
        attachment_key = str(attachment.get("key") or "")
        if not item_key or not attachment_key:
            continue
        parsed_at = str(payload.get("parsed_at") or "")
        score = json_path.stat().st_mtime
        key = (item_key, attachment_key)
        current = grouped.get(key)
        if current is None or (parsed_at, score) > (str(current[1].get("parsed_at") or ""), current[2]):
            grouped[key] = (json_path, payload, score)
    return [(path, payload) for path, payload, _score in grouped.values()]


def markdown_for_mineru_json(json_path: Path) -> Path | None:
    same_stem = json_path.with_suffix(".md")
    if same_stem.exists():
        return same_stem
    sibling_dir = json_path.with_suffix("")
    candidates = []
    if sibling_dir.exists():
        candidates.extend(sorted(sibling_dir.rglob("*.md")))
        candidates.extend(sorted(sibling_dir.rglob("*.markdown")))
    return candidates[0] if candidates else None


def item_by_key(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key") or ""): item for item in items if str(item.get("key") or "")}


def relative_to_library(library: dict[str, Any], path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(str(library["data_path"])).resolve()))
    except ValueError:
        return path.name


def mineru_document(
    library: dict[str, Any],
    json_path: Path,
    payload: dict[str, Any],
    item: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[Any], list[Path]]:
    markdown_path = markdown_for_mineru_json(json_path)
    markdown = markdown_path.read_text(encoding="utf-8", errors="replace") if markdown_path else ""
    attachment = payload.get("attachment") if isinstance(payload.get("attachment"), dict) else {}
    item_key = str(payload.get("item_key") or "")
    attachment_key = str(attachment.get("key") or "")
    title = str((item or {}).get("title") or attachment.get("title") or (markdown_path.stem if markdown_path else json_path.stem))
    source_hash = file_hash(markdown_path) if markdown_path else text_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    doc_id = f"doc-{stable_id(str(library['library_id']), item_key, attachment_key, 'mineru', source_hash)}"
    assets_root = json_path.with_suffix("")
    image_paths: list[Path] = []
    for base in [assets_root, json_path.parent]:
        if base.exists():
            image_paths.extend(sorted(base.rglob("*.png")))
            image_paths.extend(sorted(base.rglob("*.jpg")))
            image_paths.extend(sorted(base.rglob("*.jpeg")))
    image_paths = list(dict.fromkeys(path for path in image_paths if path.exists()))
    timestamp = now_iso()
    doc = {
        "doc_id": doc_id,
        "library_id": str(library["library_id"]),
        "item_key": item_key,
        "attachment_key": attachment_key,
        "source_type": "mineru_markdown",
        "source_path": str(markdown_path or json_path),
        "source_relpath": relative_to_library(library, markdown_path or json_path),
        "source_hash": source_hash,
        "source_mtime": str((markdown_path or json_path).stat().st_mtime),
        "title": title,
        "item_type": str((item or {}).get("type") or ""),
        "year": str((item or {}).get("year") or ""),
        "venue": str((item or {}).get("venue") or ""),
        "creators_text": creators_text(item or {}),
        "tags_text": ", ".join(str(tag) for tag in (item or {}).get("tags") or []),
        "mineru_json_path": str(json_path),
        "mineru_markdown_path": str(markdown_path or ""),
        "mineru_assets_dir": str(assets_root if assets_root.exists() else ""),
        "parsed_at": str(payload.get("parsed_at") or ""),
        "structure_json": "{}",
        "stats_json": json_dumps({"asset_count": len(image_paths)}),
        "total_chunks": 0,
        "total_assets": len(image_paths),
        "total_chars": len(markdown),
        "index_status": "indexed" if markdown else "failed",
        "error_message": "" if markdown else "No MinerU markdown found for result JSON.",
        "created_at": timestamp,
        "updated_at": timestamp,
        "indexed_at": timestamp,
    }
    chunks = chunk_markdown(markdown)
    doc["total_chunks"] = len(chunks)
    return doc, chunks, image_paths


def index_library(library: dict[str, Any]) -> dict[str, Any]:
    ensure_store(library)
    repo = ZoteroRepository(library)
    items = repo.items()
    reset_index(library, preserve_embeddings=True)
    with connect(library) as conn:
        for item in items:
            doc, chunks = item_metadata_document(library, item)
            if chunks:
                upsert_document(conn, doc)
                insert_chunks(conn, doc, chunks)
            for note_doc, note_chunks, note_payload in note_documents(library, item):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO rag_notes (
                      note_id, library_id, item_key, attachment_key, note_type, source_id, title,
                      content, content_hash, source_json, created_at, updated_at, indexed_at
                    )
                    VALUES (
                      :note_id, :library_id, :item_key, :attachment_key, :note_type, :source_id, :title,
                      :content, :content_hash, :source_json, :created_at, :updated_at, :indexed_at
                    )
                    """,
                    note_payload,
                )
                upsert_document(conn, note_doc)
                insert_chunks(conn, note_doc, note_chunks)
        conn.commit()
    index_mineru_results(library, reset_existing=False, finalize=False)
    return _final_index_status(library)


def index_mineru_results(library: dict[str, Any], *, reset_existing: bool = True, finalize: bool = True) -> dict[str, Any]:
    ensure_store(library)
    repo = ZoteroRepository(library)
    items = repo.items()
    items_by_key = item_by_key(items)
    if reset_existing:
        reset_index(library, source_types=["mineru_markdown"], preserve_embeddings=True)
    root = Path(str(library["data_path"])) / "mineru-results"
    results = latest_mineru_results(root)
    with connect(library) as conn:
        for json_path, payload in results:
            item_key = str(payload.get("item_key") or "")
            doc, chunks, image_paths = mineru_document(library, json_path, payload, items_by_key.get(item_key))
            upsert_document(conn, doc)
            if chunks:
                conn.execute("DELETE FROM rag_chunk_fts WHERE doc_id = ?", (doc["doc_id"],))
                conn.execute("DELETE FROM rag_chunk_parents WHERE doc_id = ?", (doc["doc_id"],))
                conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc["doc_id"],))
                insert_chunks(conn, doc, chunks)
            conn.execute("DELETE FROM rag_assets WHERE doc_id = ?", (doc["doc_id"],))
            for image_path in image_paths:
                try:
                    stat = image_path.stat()
                    source_hash = file_hash(image_path)
                except OSError:
                    continue
                mime_type = mimetypes.guess_type(str(image_path))[0] or "image/*"
                insert_asset(
                    conn,
                    {
                        "asset_id": f"asset-{stable_id(doc['doc_id'], str(image_path), source_hash)}",
                        "doc_id": doc["doc_id"],
                        "chunk_id": "",
                        "library_id": doc["library_id"],
                        "item_key": doc["item_key"],
                        "attachment_key": doc["attachment_key"],
                        "asset_type": "image",
                        "source_path": str(image_path),
                        "source_relpath": relative_to_library(library, image_path),
                        "source_hash": source_hash,
                        "mime_type": mime_type,
                        "file_size": int(stat.st_size),
                        "width": None,
                        "height": None,
                        "caption": "",
                        "alt_text": "",
                        "ocr_text": "",
                        "position_json": "{}",
                        "created_at": now_iso(),
                    },
                )
        cleanup_orphan_embeddings(conn)
        conn.commit()
    if not finalize:
        return update_config_stats(library)
    return _final_index_status(library)


def _final_index_status(library: dict[str, Any]) -> dict[str, Any]:
    status = update_config_stats(library)
    config = embedding_config(library)
    if not (config.get("enabled") and config.get("provider") and config.get("model")):
        return status
    try:
        embedding_index = embed_missing_chunks(library, batch_size=int(config.get("batch_size") or 64))
    except EmbeddingConfigError as exc:
        embedding_index = {"ok": False, "status": "failed", "error": str(exc)}
    next_status = update_config_stats(library)
    next_status["embedding_index"] = embedding_index
    return next_status
