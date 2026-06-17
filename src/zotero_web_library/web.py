from __future__ import annotations

import tempfile
import mimetypes
import os
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory

from . import app_store
from .citation_export import CitationExportError, export_citations, export_filename
from .metadata_import import MetadataImportError, parse_import_text, resolve_identifier
from .semantic_tags import normalize_hash_tag, stable_tag_color
from .sources import SourceError, create_local_copy, create_read_only_source, delete_source
from .sync import mark_conflicts_for_changed_keys, prepare_sync_payloads
from .zotero_adapter import ZoteroRepository


def create_app() -> Flask:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    static_dir = Path(__file__).resolve().parent / "static"
    app = Flask(__name__, template_folder="templates", static_folder=None)
    app_store.ensure_app_store()

    @app.get("/static/<path:filename>", endpoint="static")
    def static_files(filename: str):
        mimetype = "application/javascript" if filename.endswith((".js", ".mjs")) else None
        return send_from_directory(static_dir, filename, mimetype=mimetype)

    @app.after_request
    def fix_static_javascript_mimetype(response):
        if request.path.startswith("/static/") and request.path.endswith((".js", ".mjs")):
            response.headers["Content-Type"] = "application/javascript; charset=utf-8"
        return response

    def library_or_404(library_id: str) -> dict[str, Any]:
        library = app_store.get_library(library_id)
        if not library:
            raise SourceError("文库不存在。")
        return library

    @app.get("/")
    def index():
        libraries = app_store.list_libraries()
        default_source = str(Path.home() / "Zotero")
        return render_template("index.html", libraries=libraries, default_source=default_source)

    @app.get("/library/<library_id>")
    def library_page(library_id: str):
        library = library_or_404(library_id)
        libraries = app_store.list_libraries()
        return render_template("library.html", library=library, libraries=libraries)

    @app.get("/library/<library_id>/reader")
    def reader_page(library_id: str):
        library = library_or_404(library_id)
        libraries = app_store.list_libraries()
        return render_template("reader.html", library=library, libraries=libraries)

    @app.post("/api/sources/read-only")
    def api_read_only_source():
        payload = request.get_json(silent=True) or request.form
        try:
            record = create_read_only_source(str(payload.get("path") or ""), name=str(payload.get("name") or "").strip() or None)
            return jsonify({"ok": True, "library": record})
        except (SourceError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/sources/local-copy")
    def api_local_copy_source():
        payload = request.get_json(silent=True) or request.form
        try:
            record = create_local_copy(str(payload.get("path") or ""), name=str(payload.get("name") or "").strip() or None)
            return jsonify({"ok": True, "library": record})
        except (SourceError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.delete("/api/sources/<library_id>")
    def api_delete_source(library_id: str):
        try:
            library = library_or_404(library_id)
            if library.get("mode") == "local_copy" and app_store.unsynced_count(library_id) and not request.args.get("confirm"):
                return jsonify({"ok": False, "requires_confirmation": True, "error": "本地副本有未同步更改，确认后才会删除。"}), 409
            deleted = delete_source(library_id)
            return jsonify({"ok": True, "library": deleted})
        except (SourceError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/library/<library_id>/state")
    def api_library_state(library_id: str):
        try:
            repo = ZoteroRepository(library_or_404(library_id))
            state = repo.state()
            return jsonify({"ok": True, **state})
        except (SourceError, OSError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/preferences/columns")
    def api_columns(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        columns = payload.get("columns")
        if not isinstance(columns, list):
            return jsonify({"ok": False, "error": "columns must be a list"}), 400
        app_store.set_preference(library_id, "columns", [str(item) for item in columns if str(item)])
        return jsonify({"ok": True, "columns": app_store.column_preference(library_id)})

    @app.post("/api/library/<library_id>/preferences/column-widths")
    def api_column_widths(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        widths = payload.get("widths")
        if not isinstance(widths, dict):
            return jsonify({"ok": False, "error": "widths must be an object"}), 400
        app_store.set_preference(library_id, "column_widths", widths)
        return jsonify({"ok": True, "widths": app_store.column_width_preference(library_id)})

    @app.post("/api/library/<library_id>/preferences/plain-tags")
    def api_plain_tags_preference(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        collapsed = bool(payload.get("collapsed"))
        app_store.set_preference(library_id, "plain_tags_collapsed", collapsed)
        return jsonify({"ok": True, "collapsed": collapsed})

    @app.post("/api/library/<library_id>/collections")
    def api_create_collection(library_id: str):
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name") or "").strip()
        parent_key = str(payload.get("parent_key") or "").strip() or None
        if not name:
            return jsonify({"ok": False, "error": "文件夹名称不能为空。"}), 400
        try:
            collection = ZoteroRepository(library_or_404(library_id)).create_collection(name, parent_key)
            return jsonify({"ok": True, "collection": collection})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.patch("/api/library/<library_id>/collections/<collection_key>")
    def api_rename_collection(library_id: str, collection_key: str):
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name") or "").strip()
        try:
            repo = ZoteroRepository(library_or_404(library_id))
            if name:
                repo.rename_collection(collection_key, name)
            if "parent_key" in payload:
                parent_key = str(payload.get("parent_key") or "").strip() or None
                repo.reparent_collection(collection_key, parent_key)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.delete("/api/library/<library_id>/collections/<collection_key>")
    def api_delete_collection(library_id: str, collection_key: str):
        try:
            result = ZoteroRepository(library_or_404(library_id)).delete_collection(collection_key)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/delete")
    def api_delete_items(library_id: str):
        payload = request.get_json(silent=True) or {}
        item_keys = payload.get("item_keys")
        mode = str(payload.get("mode") or "trash").strip()
        if not isinstance(item_keys, list):
            return jsonify({"ok": False, "error": "item_keys must be a list"}), 400
        try:
            result = ZoteroRepository(library_or_404(library_id)).delete_items([str(key) for key in item_keys], mode)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/move")
    def api_move_items(library_id: str):
        payload = request.get_json(silent=True) or {}
        item_keys = payload.get("item_keys")
        target_collection_key = str(payload.get("target_collection_key") or "").strip()
        if not isinstance(item_keys, list):
            return jsonify({"ok": False, "error": "item_keys must be a list"}), 400
        if not target_collection_key:
            return jsonify({"ok": False, "error": "请选择目标文件夹。"}), 400
        try:
            result = ZoteroRepository(library_or_404(library_id)).move_items([str(key) for key in item_keys], target_collection_key)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.patch("/api/library/<library_id>/items/<item_key>/field")
    def api_update_item_field(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        field = str(payload.get("field") or "").strip()
        value = str(payload.get("value") or "")
        if not field:
            return jsonify({"ok": False, "error": "字段名不能为空。"}), 400
        try:
            ZoteroRepository(library_or_404(library_id)).update_item_field(item_key, field, value)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.patch("/api/library/<library_id>/items/<item_key>/structured-field")
    def api_update_structured_field(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        field = str(payload.get("field") or "").strip()
        value = str(payload.get("value") or "")
        if field not in {"remark", "title_zh", "abstract_zh"}:
            return jsonify({"ok": False, "error": "未知结构化字段。"}), 400
        try:
            ZoteroRepository(library_or_404(library_id)).update_structured_field(item_key, field, value)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/<item_key>/tags")
    def api_add_tag(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        tag = str(payload.get("tag") or "").strip()
        if not tag:
            return jsonify({"ok": False, "error": "标签不能为空。"}), 400
        try:
            ZoteroRepository(library_or_404(library_id)).add_tag(item_key, tag)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.delete("/api/library/<library_id>/items/<item_key>/tags")
    def api_remove_tag(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        tag = str(payload.get("tag") or "").strip()
        if not tag:
            return jsonify({"ok": False, "error": "标签不能为空。"}), 400
        try:
            ZoteroRepository(library_or_404(library_id)).remove_tag(item_key, tag)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.patch("/api/library/<library_id>/items/<item_key>/rating")
    def api_set_rating(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        try:
            value = int(payload.get("rating") or 0)
            ZoteroRepository(library_or_404(library_id)).set_rating(item_key, value)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.patch("/api/library/<library_id>/items/<item_key>/reading-status")
    def api_set_reading_status(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status") or "").strip()
        try:
            ZoteroRepository(library_or_404(library_id)).set_reading_status(item_key, status)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/<item_key>/collections")
    def api_item_collection(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        collection_key = str(payload.get("collection_key") or "").strip()
        enabled = bool(payload.get("enabled"))
        if not collection_key:
            return jsonify({"ok": False, "error": "collection_key is required"}), 400
        try:
            ZoteroRepository(library_or_404(library_id)).set_collection_membership(item_key, collection_key, enabled)
            return jsonify({"ok": True})
        except (SourceError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/import-identifier")
    def api_import_identifier(library_id: str):
        payload = request.get_json(silent=True) or {}
        identifier = str(payload.get("identifier") or "").strip()
        collection_key = str(payload.get("collection_key") or "").strip() or None
        if not identifier:
            return jsonify({"ok": False, "error": "标识符不能为空。"}), 400
        try:
            repo = ZoteroRepository(library_or_404(library_id))
            summary = repo.import_metadata_items([resolve_identifier(identifier)], collection_key)
            return jsonify({"ok": True, **summary})
        except (SourceError, ValueError, MetadataImportError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/import-text")
    def api_import_text(library_id: str):
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text") or "")
        fmt = str(payload.get("format") or "auto").strip() or "auto"
        collection_key = str(payload.get("collection_key") or "").strip() or None
        if not text.strip():
            return jsonify({"ok": False, "error": "导入文本不能为空。"}), 400
        try:
            repo = ZoteroRepository(library_or_404(library_id))
            summary = repo.import_metadata_items(parse_import_text(text, fmt), collection_key)
            return jsonify({"ok": True, **summary})
        except (SourceError, ValueError, MetadataImportError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/export-citations")
    def api_export_citations(library_id: str):
        payload = request.get_json(silent=True) or {}
        item_keys = payload.get("item_keys") or []
        fmt = str(payload.get("format") or "").strip()
        if not isinstance(item_keys, list):
            return jsonify({"ok": False, "error": "item_keys must be a list"}), 400
        try:
            repo = ZoteroRepository(library_or_404(library_id))
            content, meta = export_citations(repo.items(), [str(key) for key in item_keys], fmt)
            return Response(
                content,
                mimetype=meta["mime"].split(";")[0],
                headers={
                    "Content-Type": meta["mime"],
                    "Content-Disposition": f"attachment; filename={export_filename(fmt)}",
                },
            )
        except (SourceError, ValueError, CitationExportError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/library/<library_id>/items/<item_key>/pdf-attachments")
    def api_item_pdf_attachments(library_id: str, item_key: str):
        try:
            attachments = ZoteroRepository(library_or_404(library_id)).pdf_attachments_for_item(item_key)
            return jsonify({"ok": True, "attachments": attachments})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/library/<library_id>/semantic-rules")
    def api_semantic_rules(library_id: str):
        library_or_404(library_id)
        return jsonify({"ok": True, "rules": app_store.list_semantic_rules(library_id)})

    @app.post("/api/library/<library_id>/semantic-rules")
    def api_add_semantic_rule(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        bucket = str(payload.get("bucket") or "").strip()
        pattern = str(payload.get("pattern") or "").strip()
        label = str(payload.get("label") or "").strip()
        if bucket not in {"rating", "nested", "venue_rank", "reading_status", "plain"}:
            return jsonify({"ok": False, "error": "未知语义桶。"}), 400
        if not pattern:
            return jsonify({"ok": False, "error": "pattern 不能为空。"}), 400
        rule = app_store.add_semantic_rule(library_id, bucket, pattern, label)
        return jsonify({"ok": True, "rule": rule})

    @app.get("/api/library/<library_id>/tag-shortcuts")
    def api_tag_shortcuts(library_id: str):
        library_or_404(library_id)
        return jsonify({"ok": True, "shortcuts": app_store.list_tag_shortcuts(library_id)})

    @app.post("/api/library/<library_id>/tag-shortcuts")
    def api_add_tag_shortcut(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        tag = str(payload.get("tag") or "").strip()
        if not tag:
            return jsonify({"ok": False, "error": "标签不能为空。"}), 400
        normalized_tag = normalize_hash_tag(tag)
        shortcut = app_store.upsert_tag_shortcut(library_id, normalized_tag, stable_tag_color(normalized_tag))
        return jsonify({"ok": True, "shortcut": shortcut})

    @app.delete("/api/library/<library_id>/tag-shortcuts")
    def api_delete_tag_shortcut(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        tag = str(payload.get("tag") or "").strip()
        if not tag:
            return jsonify({"ok": False, "error": "标签不能为空。"}), 400
        app_store.delete_tag_shortcut(library_id, tag)
        return jsonify({"ok": True})

    @app.post("/api/library/<library_id>/items/<item_key>/attachments/file")
    def api_add_file_attachment(library_id: str, item_key: str):
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"ok": False, "error": "请选择要上传的文件。"}), 400
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                filename = Path(upload.filename).name
                temp_path = Path(tmp_dir) / filename
                upload.save(temp_path)
                result = ZoteroRepository(library_or_404(library_id)).add_file_attachment(
                    item_key,
                    temp_path,
                    filename,
                    upload.mimetype or None,
                )
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/items/<item_key>/attachments/url")
    def api_add_url_attachment(library_id: str, item_key: str):
        payload = request.get_json(silent=True) or {}
        url = str(payload.get("url") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not url:
            return jsonify({"ok": False, "error": "网址不能为空。"}), 400
        try:
            result = ZoteroRepository(library_or_404(library_id)).add_url_attachment(item_key, url, title)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.patch("/api/library/<library_id>/attachments/<attachment_key>")
    def api_rename_attachment(library_id: str, attachment_key: str):
        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "附件名称不能为空。"}), 400
        try:
            result = ZoteroRepository(library_or_404(library_id)).rename_attachment(attachment_key, title)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.delete("/api/library/<library_id>/attachments/<attachment_key>")
    def api_delete_attachment(library_id: str, attachment_key: str):
        payload = request.get_json(silent=True) or {}
        keys = payload.get("attachment_keys")
        attachment_keys = [str(key) for key in keys] if isinstance(keys, list) else [attachment_key]
        try:
            result = ZoteroRepository(library_or_404(library_id)).delete_attachments(attachment_keys)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/library/<library_id>/attachments/<attachment_key>/annotations")
    def api_attachment_annotations(library_id: str, attachment_key: str):
        try:
            annotations = ZoteroRepository(library_or_404(library_id)).annotations_for_attachment(attachment_key)
            return jsonify({"ok": True, "annotations": annotations})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/attachments/<attachment_key>/annotations")
    def api_create_attachment_annotation(library_id: str, attachment_key: str):
        payload = request.get_json(silent=True) or {}
        try:
            annotation = ZoteroRepository(library_or_404(library_id)).create_pdf_annotation(attachment_key, payload)
            return jsonify({"ok": True, "annotation": annotation})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/library/<library_id>/attachments/<attachment_key>/annotations/clear")
    def api_clear_attachment_annotations(library_id: str, attachment_key: str):
        payload = request.get_json(silent=True) or {}
        try:
            result = ZoteroRepository(library_or_404(library_id)).clear_pdf_annotations(attachment_key, payload)
            return jsonify({"ok": True, **result})
        except (SourceError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/library/<library_id>/sync/payloads")
    def api_sync_payloads(library_id: str):
        library_or_404(library_id)
        return jsonify({"ok": True, "payloads": prepare_sync_payloads(library_id)})

    @app.post("/api/library/<library_id>/sync/conflicts")
    def api_mark_conflicts(library_id: str):
        library_or_404(library_id)
        payload = request.get_json(silent=True) or {}
        keys = {str(key) for key in payload.get("changed_keys") or []}
        return jsonify({"ok": True, "conflicted": mark_conflicts_for_changed_keys(library_id, keys)})

    @app.get("/api/library/<library_id>/attachments/<attachment_key>")
    def api_open_attachment(library_id: str, attachment_key: str):
        repo = ZoteroRepository(library_or_404(library_id))
        for item in repo.items():
            for attachment in item.get("attachments", []):
                if attachment.get("key") == attachment_key and attachment.get("openable") and attachment.get("resolved_path"):
                    path = Path(attachment["resolved_path"])
                    if path.exists():
                        return send_file(path, as_attachment=False)
        return jsonify({"ok": False, "error": "附件文件缺失或不可直接打开。"}), 404

    return app


app = create_app()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def main() -> None:
    host = os.environ.get("WEB_LIBRARY_HOST", "127.0.0.1")
    port = _env_int("WEB_LIBRARY_PORT", 8686)
    debug = _env_bool("WEB_LIBRARY_DEBUG", True)
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    main()
