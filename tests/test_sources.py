from __future__ import annotations

import os
from pathlib import Path

import pytest

from zotero_web_library import app_store
from zotero_web_library.sources import LOCAL_COPY, READ_ONLY, SourceError, create_local_copy, create_read_only_source, delete_source, validate_zotero_dir


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
    assert create_local_copy(zotero_fixture)["library_id"] == record["library_id"]


def test_delete_local_copy_removes_only_managed_copy(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    record = create_local_copy(zotero_fixture)
    data_path = Path(record["data_path"])
    assert data_path.exists()
    delete_source(record["library_id"])
    assert not data_path.exists()
    assert (zotero_fixture / "zotero.sqlite").exists()
