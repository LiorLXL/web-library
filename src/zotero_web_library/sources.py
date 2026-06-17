from __future__ import annotations

import json
import os
import shutil
import string
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import unquote

from . import app_store
from .paths import BASE_DIR, libraries_dir
from .utils import file_fingerprint, new_key, normalize_path, now_iso


READ_ONLY = "read_only_connection"
LOCAL_COPY = "local_copy"
SERVER_VIRTUAL_ROOT = "__server_root__"


class SourceError(ValueError):
    pass


def validate_zotero_dir(path: str | Path) -> dict[str, Any]:
    root = normalize_path(path)
    sqlite_path = root / "zotero.sqlite"
    storage_path = root / "storage"
    if not root.exists() or not root.is_dir():
        raise SourceError("请选择存在的 Zotero 数据目录。")
    if not sqlite_path.exists():
        raise SourceError("目录中没有 zotero.sqlite，无法作为 Zotero 数据目录。")
    return {
        "root": root,
        "sqlite_path": sqlite_path,
        "storage_path": storage_path if storage_path.exists() else None,
        "fingerprint": file_fingerprint(sqlite_path),
    }


def normalized_source_path(path: str | Path) -> str:
    return str(normalize_path(path)).casefold()


def find_existing_source(path: str | Path, mode: str) -> dict[str, Any] | None:
    source_key = normalized_source_path(path)
    for library in app_store.list_all_libraries():
        if library.get("mode") != mode:
            continue
        if normalized_source_path(library.get("source_path", "")) != source_key:
            continue
        if mode == LOCAL_COPY and not (Path(library["data_path"]) / "zotero.sqlite").exists():
            continue
        return library
    return None


def library_name_exists(name: str) -> bool:
    clean_name = name.strip().casefold()
    if not clean_name:
        return False
    return any(str(library.get("name", "")).strip().casefold() == clean_name for library in app_store.list_all_libraries())


def unique_copy_name(base_name: str) -> str:
    clean_base = base_name.strip() or "副本：文库"
    existing = {str(library.get("name", "")).strip().casefold() for library in app_store.list_all_libraries()}
    if clean_base.casefold() not in existing:
        return clean_base
    index = 2
    while True:
        candidate = f"{clean_base} {index}"
        if candidate.casefold() not in existing:
            return candidate
        index += 1


def _copy_name_or_raise(name: str | None, fallback: str) -> str:
    clean_name = (name or "").strip()
    if clean_name:
        if library_name_exists(clean_name):
            raise SourceError("副本文库名称已存在，请换一个名称。")
        return clean_name
    return unique_copy_name(fallback)


def _seed_shortcuts_for_library(record: dict[str, Any]) -> dict[str, Any]:
    from .zotero_adapter import ZoteroRepository

    ZoteroRepository(record).ensure_tag_shortcuts_seeded(force=True)
    return record


def create_read_only_source(path: str | Path, *, name: str | None = None) -> dict[str, Any]:
    info = validate_zotero_dir(path)
    existing = find_existing_source(info["root"], READ_ONLY)
    if existing:
        if name:
            existing["name"] = name
            return app_store.upsert_library(existing)
        return existing
    library_id = f"ro-{new_key(10).lower()}"
    record = app_store.upsert_library(
        {
            "library_id": library_id,
            "name": name or f"只读连接：{info['root'].name}",
            "mode": READ_ONLY,
            "source_path": info["root"],
            "data_path": info["root"],
            "source_fingerprint": info["fingerprint"],
        }
    )
    return _seed_shortcuts_for_library(record)


def create_local_copy(path: str | Path, *, name: str | None = None) -> dict[str, Any]:
    info = validate_zotero_dir(path)
    library_id = f"copy-{new_key(10).lower()}"
    target = libraries_dir() / library_id
    display_name = _copy_name_or_raise(name, f"副本：{info['root'].name}")
    try:
        target.mkdir(parents=True, exist_ok=False)
        shutil.copy2(info["sqlite_path"], target / "zotero.sqlite")
        if info["storage_path"]:
            shutil.copytree(info["storage_path"], target / "storage")
        source_json = {
            "source_path": str(info["root"]),
            "source_fingerprint": info["fingerprint"],
            "copied_at": now_iso(),
        }
        (target / "source.json").write_text(json.dumps(source_json, ensure_ascii=False, indent=2), encoding="utf-8")
        record = app_store.upsert_library(
            {
                "library_id": library_id,
                "name": display_name,
                "mode": LOCAL_COPY,
                "source_path": info["root"],
                "data_path": target,
                "source_fingerprint": info["fingerprint"],
            }
        )
        return _seed_shortcuts_for_library(record)
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise


def _safe_upload_relative_path(filename: str) -> Path:
    raw = unquote(str(filename or "")).strip().replace("\x00", "")
    if not raw:
        raise SourceError("上传文件路径不能为空。")
    raw = raw.replace("\\", "/")
    path = Path(raw)
    if path.is_absolute() or raw.startswith("/") or ":" in path.parts[0]:
        raise SourceError("上传文件包含非法绝对路径。")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise SourceError("上传文件包含非法相对路径。")
    return Path(*parts)


def _relative_to_prefix(path: Path, prefix: Path | None) -> Path | None:
    if prefix is None or str(prefix) == ".":
        return path
    try:
        return path.relative_to(prefix)
    except ValueError:
        return None


def create_local_copy_from_uploads(files: Iterable[Any], *, name: str | None = None) -> dict[str, Any]:
    uploads: list[tuple[Any, Path]] = []
    for upload in files:
        filename = getattr(upload, "filename", "")
        rel_path = _safe_upload_relative_path(filename)
        if rel_path.name:
            uploads.append((upload, rel_path))
    if not uploads:
        raise SourceError("请选择要上传的文库文件夹。")

    sqlite_candidates = [rel_path for _, rel_path in uploads if rel_path.name == "zotero.sqlite"]
    if not sqlite_candidates:
        raise SourceError("上传的文件夹中没有 zotero.sqlite，无法创建副本。")
    sqlite_rel = min(sqlite_candidates, key=lambda item: len(item.parts))
    root_prefix = sqlite_rel.parent if sqlite_rel.parent != Path(".") else None
    library_id = f"copy-{new_key(10).lower()}"
    target = libraries_dir() / library_id
    root_label = root_prefix.name if root_prefix else "上传文库"
    display_name = _copy_name_or_raise(name, f"副本：{root_label}")
    try:
        target.mkdir(parents=True, exist_ok=False)
        wrote_any = False
        for upload, rel_path in uploads:
            target_rel = _relative_to_prefix(rel_path, root_prefix)
            if target_rel is None or not target_rel.parts:
                continue
            destination = target / target_rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            upload.save(destination)
            wrote_any = True
        if not wrote_any or not (target / "zotero.sqlite").exists():
            raise SourceError("上传结构无效，未能在根目录生成 zotero.sqlite。")
        fingerprint = file_fingerprint(target / "zotero.sqlite")
        source_json = {
            "source_path": f"browser-upload:{root_label}",
            "source_fingerprint": fingerprint,
            "uploaded_at": now_iso(),
        }
        (target / "source.json").write_text(json.dumps(source_json, ensure_ascii=False, indent=2), encoding="utf-8")
        record = app_store.upsert_library(
            {
                "library_id": library_id,
                "name": display_name,
                "mode": LOCAL_COPY,
                "source_path": source_json["source_path"],
                "data_path": target,
                "source_fingerprint": fingerprint,
            }
        )
        return _seed_shortcuts_for_library(record)
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise


def default_service_source_path() -> str:
    opt_demo = _first_demo_library(Path("/opt/demo-data/libraries"))
    if opt_demo:
        return str(opt_demo)
    repo_demo = _first_demo_library(BASE_DIR / "demo-data" / "libraries")
    if repo_demo:
        return str(repo_demo)
    return str(Path.home() / "Zotero")


def _first_demo_library(root: Path) -> Path | None:
    if not root.exists() or not root.is_dir():
        return None
    for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_dir() and (child / "zotero.sqlite").exists():
            return child.resolve()
    return None


def server_path_roots() -> list[dict[str, Any]]:
    candidates = _server_root_candidates()
    roots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, raw_path in candidates:
        try:
            path = raw_path.expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if not path.exists() or not path.is_dir():
            continue
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        roots.append(_directory_payload(path, label=label))
    return roots


def _server_root_candidates() -> Sequence[tuple[str, Path]]:
    configured = os.environ.get("WEB_LIBRARY_SERVER_ROOTS")
    if configured:
        return [(Path(path).name or str(Path(path)), Path(path)) for path in configured.split(os.pathsep) if path.strip()]
    if os.name == "nt":
        drives = [(f"{letter}:\\", Path(f"{letter}:\\")) for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]
        return drives or [("用户目录", Path.home())]
    return [
        ("opt", Path("/opt")),
        ("app", Path("/app")),
        ("用户目录", Path.home()),
        ("mnt", Path("/mnt")),
        ("data", Path("/data")),
    ]


def _allowed_root_paths() -> list[Path]:
    return [Path(root["path"]).resolve() for root in server_path_roots()]


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _allowed_root_for(path: Path) -> Path | None:
    for root in sorted(_allowed_root_paths(), key=lambda item: len(str(item)), reverse=True):
        if _is_within(path, root):
            return root
    return None


def _directory_payload(path: Path, *, label: str | None = None) -> dict[str, Any]:
    return {
        "label": label or path.name or str(path),
        "name": path.name or str(path),
        "path": str(path),
        "contains_sqlite": (path / "zotero.sqlite").exists(),
    }


def list_server_directory(path: str | Path) -> dict[str, Any]:
    if str(path) == SERVER_VIRTUAL_ROOT:
        return {
            "path": SERVER_VIRTUAL_ROOT,
            "root": SERVER_VIRTUAL_ROOT,
            "parent": None,
            "label": "服务器根目录",
            "contains_sqlite": False,
            "children": server_path_roots(),
            "is_virtual_root": True,
        }
    try:
        target = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        raise SourceError("服务路径无效。")
    root = _allowed_root_for(target)
    if root is None:
        raise SourceError("该服务路径不在允许浏览的目录内。")
    if not target.exists() or not target.is_dir():
        raise SourceError("请选择存在的服务目录。")
    children: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.casefold()):
        if not child.is_dir():
            continue
        children.append(_directory_payload(child.resolve()))
    parent = SERVER_VIRTUAL_ROOT if target == root else target.parent.resolve()
    return {
        "path": str(target),
        "root": str(root),
        "parent": str(parent),
        "contains_sqlite": (target / "zotero.sqlite").exists(),
        "children": children,
        "is_virtual_root": False,
    }


def delete_source(library_id: str) -> dict[str, Any]:
    library = app_store.get_library(library_id)
    if not library:
        raise SourceError("文库不存在。")
    data_path = Path(library["data_path"])
    if library["mode"] == LOCAL_COPY:
        root = libraries_dir().resolve()
        target = data_path.resolve()
        if root not in [target, *target.parents]:
            raise SourceError("本地副本路径不在应用管理目录内，拒绝删除。")
        if target.exists():
            shutil.rmtree(target)
    app_store.delete_library_record(library_id)
    return library


def sqlite_path_for(library: dict[str, Any]) -> Path:
    return Path(library["data_path"]) / "zotero.sqlite"


def storage_path_for(library: dict[str, Any]) -> Path:
    return Path(library["data_path"]) / "storage"


def ensure_editable(library: dict[str, Any]) -> None:
    if library.get("mode") != LOCAL_COPY:
        raise SourceError("只读连接模式不能修改字段、标签、文件夹或附件。请先创建本地副本。")
