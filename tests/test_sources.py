from __future__ import annotations

import io
from pathlib import Path

import pytest

from zotero_web_library import app_store
from zotero_web_library.paths import libraries_dir
from zotero_web_library.sources import (
    LOCAL_COPY,
    READ_ONLY,
    SERVER_VIRTUAL_ROOT,
    SourceError,
    create_local_copy,
    create_read_only_source,
    delete_source,
    list_server_directory,
    server_path_roots,
    validate_zotero_dir,
)
from zotero_web_library.web import create_app


def test_validate_zotero_dir(zotero_fixture: Path) -> None:
    info = validate_zotero_dir(zotero_fixture)
    assert info["sqlite_path"].name == "zotero.sqlite"
    assert info["storage_path"].name == "storage"


def test_invalid_zotero_dir_rejected(tmp_path: Path) -> None:
    with pytest.raises(SourceError):
        validate_zotero_dir(tmp_path)


def test_read_only_source_records_original_path(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    record = create_read_only_source(zotero_fixture)
    assert record["mode"] == READ_ONLY
    assert Path(record["data_path"]) == zotero_fixture.resolve()
    assert create_read_only_source(zotero_fixture)["library_id"] == record["library_id"]
    assert len([library for library in app_store.list_libraries() if library["mode"] == READ_ONLY]) == 1


def test_local_copy_copies_sqlite_and_storage(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    record = create_local_copy(zotero_fixture)
    assert record["mode"] == LOCAL_COPY
    assert Path(record["data_path"]) != zotero_fixture.resolve()
    assert (Path(record["data_path"]) / "zotero.sqlite").exists()
    assert (Path(record["data_path"]) / "storage" / "ATTACH01" / "paper.pdf").exists()
    assert (zotero_fixture / "zotero.sqlite").exists()


def test_local_copy_allows_same_source_when_names_differ(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    first = create_local_copy(zotero_fixture, name="副本 A")
    second = create_local_copy(zotero_fixture, name="副本 B")

    assert first["library_id"] != second["library_id"]
    assert len([library for library in app_store.list_libraries() if library["mode"] == LOCAL_COPY]) == 2


def test_local_copy_rejects_duplicate_copy_name(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    create_local_copy(zotero_fixture, name="副本 A")

    with pytest.raises(SourceError, match="名称已存在"):
        create_local_copy(zotero_fixture, name="副本 A")


def test_local_copy_generates_unique_default_names(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    first = create_local_copy(zotero_fixture)
    second = create_local_copy(zotero_fixture)

    assert first["name"] == "副本：Zotero"
    assert second["name"] == "副本：Zotero 2"


def test_local_copy_data_path_is_portable(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    record = create_local_copy(zotero_fixture)
    portable_path = Path(record["data_path"])
    stale_path = tmp_path / "old-location" / record["library_id"]
    app_store.upsert_library({**record, "data_path": stale_path})

    restored = app_store.get_library(record["library_id"])
    assert restored is not None
    assert Path(restored["data_path"]) == portable_path
    assert Path(app_store.list_libraries()[0]["data_path"]) == portable_path


def test_delete_local_copy_removes_only_managed_copy(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    record = create_local_copy(zotero_fixture)
    data_path = Path(record["data_path"])
    assert data_path.exists()
    delete_source(record["library_id"])
    assert not data_path.exists()
    assert (zotero_fixture / "zotero.sqlite").exists()


def test_delete_source_api_handles_local_copy_and_read_only(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    local_copy = create_local_copy(zotero_fixture)
    read_only = create_read_only_source(zotero_fixture, name="只读测试")
    client = create_app().test_client()

    local_copy_response = client.delete(f"/api/sources/{local_copy['library_id']}")
    assert local_copy_response.status_code == 200
    assert local_copy_response.is_json
    assert local_copy_response.get_json()["ok"] is True
    assert Path(local_copy["data_path"]).exists() is False

    read_only_response = client.delete(f"/api/sources/{read_only['library_id']}")
    assert read_only_response.status_code == 200
    assert read_only_response.is_json
    assert read_only_response.get_json()["ok"] is True
    assert zotero_fixture.exists()


def test_upload_folder_creates_local_copy(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    client = create_app().test_client()
    sqlite_bytes = (zotero_fixture / "zotero.sqlite").read_bytes()

    response = client.post(
        "/api/sources/upload-folder",
        data={
            "name": "上传副本",
            "files": [
                (io.BytesIO(sqlite_bytes), "Zotero/zotero.sqlite"),
                (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "Zotero/storage/ATTACH01/paper.pdf"),
            ],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    data_path = Path(payload["library"]["data_path"])
    assert (data_path / "zotero.sqlite").exists()
    assert (data_path / "storage" / "ATTACH01" / "paper.pdf").exists()


def test_upload_folder_without_sqlite_fails_and_cleans_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    client = create_app().test_client()

    response = client.post(
        "/api/sources/upload-folder",
        data={"files": [(io.BytesIO(b"bad"), "Zotero/storage/ATTACH01/paper.pdf")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert not any(libraries_dir().iterdir())


def test_upload_folder_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    client = create_app().test_client()

    response = client.post(
        "/api/sources/upload-folder",
        data={"files": [(io.BytesIO(b"bad"), "../zotero.sqlite")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert not any(libraries_dir().iterdir())


def test_upload_folder_too_large_returns_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_MAX_UPLOAD_BYTES", "128")
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/sources/upload-folder",
        data={"files": [(io.BytesIO(b"x" * 512), "Zotero/zotero.sqlite")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.is_json
    assert response.get_json()["ok"] is False


def test_service_directory_browser_uses_virtual_root_parent_chain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    opt_root = tmp_path / "server" / "opt"
    demo_copy = opt_root / "demo-data" / "libraries" / "copy-demo"
    demo_copy.mkdir(parents=True)
    (demo_copy / "zotero.sqlite").write_bytes(b"sqlite")
    monkeypatch.setenv("WEB_LIBRARY_SERVER_ROOTS", str(opt_root))
    outside = tmp_path / "outside"
    outside.mkdir()

    roots = server_path_roots()
    assert [Path(root["path"]) for root in roots] == [opt_root.resolve()]
    assert list_server_directory(demo_copy)["parent"] == str((opt_root / "demo-data" / "libraries").resolve())
    assert list_server_directory(opt_root / "demo-data" / "libraries")["parent"] == str((opt_root / "demo-data").resolve())
    assert list_server_directory(opt_root / "demo-data")["parent"] == str(opt_root.resolve())
    assert list_server_directory(opt_root)["parent"] == SERVER_VIRTUAL_ROOT
    virtual_root = list_server_directory(SERVER_VIRTUAL_ROOT)
    assert virtual_root["parent"] is None
    assert virtual_root["is_virtual_root"] is True
    assert virtual_root["children"][0]["path"] == str(opt_root.resolve())
    with pytest.raises(SourceError):
        list_server_directory(outside)
