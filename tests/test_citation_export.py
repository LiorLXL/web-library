from __future__ import annotations

import json
from pathlib import Path

import pytest

from zotero_web_library.citation_export import CitationExportError, export_citations
from zotero_web_library.sources import create_read_only_source
from zotero_web_library.web import create_app
from zotero_web_library.zotero_adapter import ZoteroRepository


def fixture_items(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict, list[dict]]:
    monkeypatch.setenv("ZOTERO_WEB_LIBRARY_DATA", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    return library, ZoteroRepository(library).items()


def test_export_bibtex_contains_core_journal_fields(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, items = fixture_items(zotero_fixture, monkeypatch, tmp_path)
    content, meta = export_citations(items, ["ITEM0001"], "bibtex")

    assert meta["extension"] == "bib"
    assert "@article{" in content
    assert "title = {OpenVLA}" in content
    assert "author = {Kim, Moo Jin}" in content
    assert "year = {2024}" in content
    assert "journal = {arXiv}" in content
    assert "doi = {10.48550/arXiv.2406.09246}" in content
    assert "keywords = {\\#VLA/端到端, \\#有代码, /done, CCF-A, ★★★★★}" in content


def test_export_biblatex_maps_software_and_keeps_unique_citekeys(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, items = fixture_items(zotero_fixture, monkeypatch, tmp_path)
    content, _ = export_citations(items, ["ITEM0006", "ITEM0006"], "biblatex")

    assert content.count("@software{") == 2
    citekey_lines = [line for line in content.splitlines() if line.startswith("@software{")]
    assert len(set(citekey_lines)) == 2


def test_export_ris_contains_core_tags(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, items = fixture_items(zotero_fixture, monkeypatch, tmp_path)
    content, meta = export_citations(items, ["ITEM0001"], "ris")

    assert meta["extension"] == "ris"
    assert "TY  - JOUR" in content
    assert "TI  - OpenVLA" in content
    assert "AU  - Moo Jin Kim" in content
    assert "PY  - 2024" in content
    assert "DO  - 10.48550/arXiv.2406.09246" in content
    assert "KW  - #有代码" in content
    assert "ER  - " in content


def test_export_csl_json_and_csv(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, items = fixture_items(zotero_fixture, monkeypatch, tmp_path)
    csl_content, _ = export_citations(items, ["ITEM0001"], "csl_json")
    csl = json.loads(csl_content)
    assert csl[0]["id"] == "ITEM0001"
    assert csl[0]["type"] == "article-journal"
    assert csl[0]["title"] == "OpenVLA"
    assert csl[0]["DOI"] == "10.48550/arXiv.2406.09246"
    assert csl[0]["issued"]["date-parts"][0][0] == 2024

    csv_content, meta = export_citations(items, ["ITEM0001"], "csv")
    assert meta["extension"] == "csv"
    assert csv_content.startswith("\ufeffkey,itemType,publicationYear")
    assert "ITEM0001,journalArticle,2024" in csv_content


def test_export_rejects_empty_unknown_and_missing_selection(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, items = fixture_items(zotero_fixture, monkeypatch, tmp_path)
    with pytest.raises(CitationExportError, match="请先选择"):
        export_citations(items, [], "bibtex")
    with pytest.raises(CitationExportError, match="未知引用导出格式"):
        export_citations(items, ["ITEM0001"], "unknown")
    with pytest.raises(CitationExportError, match="没有可导出的条目"):
        export_citations(items, ["NOPE0001"], "bibtex")


def test_export_api_allows_read_only_library(zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZOTERO_WEB_LIBRARY_DATA", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/items/export-citations",
        json={"item_keys": ["ITEM0001"], "format": "bibtex"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Disposition"].endswith(".bib")
    assert b"@article" in response.data
