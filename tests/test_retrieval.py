from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import urllib.error
import zipfile
from pathlib import Path

import pytest

from zotero_web_library.metadata_import import ImportedCreator, ImportedItem
from zotero_web_library.retrieval import providers as retrieval_providers
from zotero_web_library.retrieval.importing import imported_items_from_candidates
from zotero_web_library.retrieval.models import RetrievedCandidate
from zotero_web_library.retrieval.providers import (
    ADSProvider,
    ArxivProvider,
    BioRxivProvider,
    CrossrefProvider,
    DataCiteProvider,
    GitHubProvider,
    HuggingFaceProvider,
    HttpJsonProvider,
    LocalFileProvider,
    ManifestProvider,
    MedRxivProvider,
    OpenLibraryProvider,
    OpenAlexProvider,
    PubMedProvider,
    SemanticScholarProvider,
    SQLiteProvider,
    ZenodoProvider,
    retrieval_source_statuses,
    search_retrieval,
)
from zotero_web_library.sources import create_local_copy, create_read_only_source
from zotero_web_library import app_store, web
from zotero_web_library.web import create_app
from zotero_web_library.zotero_adapter import ZoteroRepository


class FakeHttpResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_http_json_fetch_retries_rate_limits_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "1.25"}, None)
        return FakeHttpResponse('{"ok": true}')

    monkeypatch.setattr(retrieval_providers.urllib.request, "urlopen", fake_urlopen)

    payload = retrieval_providers._http_get_json("https://example.test/data", retries=1, sleep=sleeps.append)

    assert payload == {"ok": True}
    assert calls == ["https://example.test/data", "https://example.test/data"]
    assert sleeps == [1.25]


def test_http_text_fetch_retries_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("timed out")
        return FakeHttpResponse("retry ok")

    monkeypatch.setattr(retrieval_providers.urllib.request, "urlopen", fake_urlopen)

    text = retrieval_providers._http_get_text("https://example.test/text", retries=1, sleep=sleeps.append)

    assert text == "retry ok"
    assert calls == 2
    assert sleeps == [0.25]


def test_http_fetch_does_not_retry_auth_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(retrieval_providers.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError):
        retrieval_providers._http_get_json("https://example.test/auth", retries=3, sleep=lambda seconds: None)

    assert calls == 1


def test_run_provider_search_tracks_source_rate_limit_wait() -> None:
    class LimitedProvider:
        name = "limited"
        rate_limit_seconds = 0.5

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            return []

    provider = LimitedProvider()
    sleeps: list[float] = []
    retrieval_providers.reset_source_rate_limit_state()
    try:
        first = retrieval_providers.run_provider_search(
            "limited",
            provider,
            "robot",
            1,
            sleep=sleeps.append,
            now=lambda: 100.0,
        )
        second = retrieval_providers.run_provider_search(
            "limited",
            provider,
            "robot",
            1,
            sleep=sleeps.append,
            now=lambda: 100.0,
        )
    finally:
        retrieval_providers.reset_source_rate_limit_state()

    assert first.stats_dict()["rate_limit_seconds"] == 0.5
    assert first.stats_dict()["rate_limit_wait_ms"] == 0
    assert second.stats_dict()["rate_limit_wait_ms"] == 500
    assert sleeps == [0.5]


def test_crossref_provider_maps_search_results_to_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "message": {
                "items": [
                    {
                        "type": "proceedings-article",
                        "title": ["Vision Language Action Demo"],
                        "DOI": "10.1234/DEMO",
                        "container-title": ["ICRA"],
                        "published-print": {"date-parts": [[2026, 5, 1]]},
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "abstract": "<jats:p>Robot abstract.</jats:p>",
                        "URL": "https://doi.org/10.1234/demo",
                    }
                ]
            }
        }

    candidates = CrossrefProvider(get_json=fake_json).search("vision robot", limit=3)

    assert "query.bibliographic=vision+robot" in seen_urls[0]
    assert "rows=3" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "crossref"
    assert candidate.item.item_type == "conferencePaper"
    assert candidate.item.fields["title"] == "Vision Language Action Demo"
    assert candidate.item.fields["abstractNote"] == "Robot abstract."
    assert candidate.item.identifiers["doi"] == "10.1234/demo"
    assert candidate.item.creators[0].last_name == "Lovelace"


def test_arxiv_provider_maps_atom_results_to_candidates() -> None:
    xml = """
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2406.09246v2</id>
    <title> OpenVLA: An Open Vision-Language-Action Model </title>
    <summary> A robot policy paper. </summary>
    <published>2024-06-13T00:00:00Z</published>
    <author><name>Moo Jin Kim</name></author>
    <category term="cs.RO" />
    <link title="pdf" href="http://arxiv.org/pdf/2406.09246v2" type="application/pdf" />
  </entry>
</feed>
"""

    candidates = ArxivProvider(get_text=lambda url: xml).search("openvla", limit=1)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "arxiv"
    assert candidate.external_id == "2406.09246"
    assert candidate.item.item_type == "preprint"
    assert candidate.item.fields["repository"] == "arXiv"
    assert candidate.item.fields["extra"] == "arXiv: 2406.09246"
    assert candidate.item.creators[0].last_name == "Kim"
    assert candidate.item.tags == ["cs.RO"]
    assert candidate.pdf_url == "http://arxiv.org/pdf/2406.09246v2"


def test_pubmed_provider_searches_ids_then_maps_xml_to_candidates() -> None:
    seen_json_urls: list[str] = []
    seen_text_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_json_urls.append(url)
        return {"esearchresult": {"idlist": ["12345678"]}}

    def fake_text(url: str) -> str:
        seen_text_urls.append(url)
        return """
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>PubMed Retrieval Demo</ArticleTitle>
        <Journal><Title>Journal of Robots</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
        <Abstract><AbstractText>Biomedical robot abstract.</AbstractText></Abstract>
        <AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.8888/pubmed-demo</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

    candidates = PubMedProvider(get_json=fake_json, get_text=fake_text).search("robot therapy", limit=5)

    assert "term=robot+therapy" in seen_json_urls[0]
    assert "retmax=5" in seen_json_urls[0]
    assert "id=12345678" in seen_text_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "pubmed"
    assert candidate.external_id == "12345678"
    assert candidate.item.fields["title"] == "PubMed Retrieval Demo"
    assert candidate.item.identifiers["pmid"] == "12345678"
    assert candidate.item.identifiers["doi"] == "10.8888/pubmed-demo"
    assert candidate.landing_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"


def test_biorxiv_provider_maps_doi_details_to_preprint_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "collection": [
                {
                    "doi": "10.1101/2024.06.01.123456",
                    "title": "bioRxiv Retrieval Demo",
                    "authors": "Ada Lovelace; Grace Hopper",
                    "date": "2024-06-01",
                    "category": "Bioinformatics",
                    "abstract": "A preprint retrieval abstract.",
                    "version": "2",
                    "published": "10.1000/published-demo",
                }
            ]
        }

    candidates = BioRxivProvider(get_json=fake_json).search("10.1101/2024.06.01.123456", limit=3)

    assert "details/biorxiv/10.1101%2F2024.06.01.123456/na/json" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "biorxiv"
    assert candidate.external_id == "10.1101/2024.06.01.123456"
    assert candidate.item.item_type == "preprint"
    assert candidate.item.fields["title"] == "bioRxiv Retrieval Demo"
    assert candidate.item.fields["repository"] == "bioRxiv"
    assert candidate.item.fields["DOI"] == "10.1101/2024.06.01.123456"
    assert candidate.item.fields["abstractNote"] == "A preprint retrieval abstract."
    assert candidate.item.identifiers["doi"] == "10.1101/2024.06.01.123456"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.item.tags == ["Bioinformatics"]
    assert "bioRxiv Version: 2" in candidate.item.fields["extra"]


def test_medrxiv_provider_filters_recent_records_by_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_urls: list[str] = []
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_PREPRINT_DAYS", "30")

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "collection": [
                {
                    "doi": "10.1101/2025.01.02.222222",
                    "title": "Clinical Robot Trial",
                    "authors": "Ada Lovelace",
                    "date": "2025-01-02",
                    "category": "Clinical Trials",
                    "abstract": "Robot rehabilitation trial.",
                    "version": "1",
                },
                {
                    "doi": "10.1101/2025.01.03.333333",
                    "title": "Unrelated Infection Study",
                    "authors": "Grace Hopper",
                    "abstract": "No robots here.",
                },
            ]
        }

    candidates = MedRxivProvider(get_json=fake_json).search("clinical robot", limit=5)

    assert "details/medrxiv/30d/0/json" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "medrxiv"
    assert candidate.item.fields["title"] == "Clinical Robot Trial"
    assert candidate.item.fields["repository"] == "medRxiv"
    assert candidate.item.identifiers["doi"] == "10.1101/2025.01.02.222222"


def test_openalex_provider_maps_work_results_to_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_urls: list[str] = []
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "doi": "https://doi.org/10.4242/openalex-demo",
                    "ids": {
                        "openalex": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.4242/openalex-demo",
                        "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345678",
                    },
                    "title": "OpenAlex Retrieval Demo",
                    "publication_date": "2026-06-01",
                    "type": "article",
                    "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                    "primary_location": {
                        "landing_page_url": "https://doi.org/10.4242/openalex-demo",
                        "pdf_url": "https://example.org/demo.pdf",
                        "source": {"display_name": "Journal of Retrieval"},
                    },
                    "biblio": {"volume": "12", "issue": "3", "first_page": "15", "last_page": "22"},
                    "abstract_inverted_index": {"Robot": [0], "retrieval": [1], "demo": [2]},
                }
            ]
        }

    candidates = OpenAlexProvider(get_json=fake_json).search("robot retrieval", limit=4)

    assert "search=robot+retrieval" in seen_urls[0]
    assert "per_page=4" in seen_urls[0]
    assert "api_key=secret-key" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "openalex"
    assert candidate.external_id == "https://openalex.org/W123"
    assert candidate.item.item_type == "journalArticle"
    assert candidate.item.fields["title"] == "OpenAlex Retrieval Demo"
    assert candidate.item.fields["publicationTitle"] == "Journal of Retrieval"
    assert candidate.item.fields["pages"] == "15-22"
    assert candidate.item.fields["abstractNote"] == "Robot retrieval demo"
    assert candidate.item.identifiers["doi"] == "10.4242/openalex-demo"
    assert candidate.item.identifiers["pmid"] == "12345678"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.pdf_url == "https://example.org/demo.pdf"


def test_openalex_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENALEX_API_KEY"):
        OpenAlexProvider(get_json=lambda url: {}).search("robot", limit=1)


def test_semantic_scholar_provider_maps_paper_results_to_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "data": [
                {
                    "paperId": "s2-paper-123",
                    "corpusId": 424242,
                    "title": "Semantic Scholar Retrieval Demo",
                    "abstract": "A paper about robot retrieval.",
                    "venue": "NeurIPS",
                    "year": 2026,
                    "publicationDate": "2026-12-01",
                    "publicationTypes": ["Conference"],
                    "authors": [{"name": "Ada Lovelace"}],
                    "externalIds": {
                        "DOI": "10.7777/S2-DEMO",
                        "ArXiv": "2406.09246v2",
                        "PubMed": "12345678",
                        "PubMedCentral": "PMC7654321",
                    },
                    "url": "https://www.semanticscholar.org/paper/s2-paper-123",
                    "openAccessPdf": {"url": "https://example.org/s2.pdf"},
                    "journal": {"name": "Conference on Retrieval", "volume": "1", "pages": "7-9"},
                }
            ]
        }

    candidates = SemanticScholarProvider(get_json=fake_json).search("robot retrieval", limit=6)

    assert "query=robot+retrieval" in seen_urls[0]
    assert "limit=6" in seen_urls[0]
    assert "fields=paperId" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "semanticscholar"
    assert candidate.external_id == "s2-paper-123"
    assert candidate.item.item_type == "conferencePaper"
    assert candidate.item.fields["title"] == "Semantic Scholar Retrieval Demo"
    assert candidate.item.fields["proceedingsTitle"] == "Conference on Retrieval"
    assert candidate.item.fields["date"] == "2026-12-01"
    assert candidate.item.fields["volume"] == "1"
    assert candidate.item.fields["pages"] == "7-9"
    assert candidate.item.fields["abstractNote"] == "A paper about robot retrieval."
    assert candidate.item.identifiers["doi"] == "10.7777/s2-demo"
    assert candidate.item.identifiers["arxiv"] == "2406.09246"
    assert candidate.item.identifiers["pmid"] == "12345678"
    assert candidate.item.identifiers["pmcid"] == "PMC7654321"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.pdf_url == "https://example.org/s2.pdf"
    assert "Semantic Scholar Corpus ID: 424242" in candidate.item.fields["extra"]


def test_datacite_provider_maps_doi_records_to_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "data": [
                {
                    "id": "10.5438/datacite-demo",
                    "type": "dois",
                    "attributes": {
                        "doi": "10.5438/DATACITE-DEMO",
                        "titles": [{"title": "DataCite Retrieval Dataset"}],
                        "creators": [
                            {
                                "givenName": "Ada",
                                "familyName": "Lovelace",
                                "name": "Lovelace, Ada",
                            }
                        ],
                        "publisher": "Demo Repository",
                        "publicationYear": 2026,
                        "types": {
                            "resourceTypeGeneral": "Dataset",
                            "resourceType": "Robot dataset",
                        },
                        "descriptions": [
                            {
                                "descriptionType": "Abstract",
                                "description": "<p>Robot dataset abstract.</p>",
                            }
                        ],
                        "url": "https://example.org/dataset",
                        "subjects": [{"subject": "robotics"}, {"subject": "AI"}],
                        "rightsList": [{"rights": "CC-BY-4.0"}],
                        "version": "1.0",
                    },
                }
            ]
        }

    candidates = DataCiteProvider(get_json=fake_json).search("robot dataset", limit=5)

    assert "query=robot+dataset" in seen_urls[0]
    assert "page%5Bsize%5D=5" in seen_urls[0]
    assert "sort=relevance" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "datacite"
    assert candidate.external_id == "10.5438/datacite-demo"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "DataCite Retrieval Dataset"
    assert candidate.item.fields["publisher"] == "Demo Repository"
    assert candidate.item.fields["date"] == "2026"
    assert candidate.item.fields["abstractNote"] == "Robot dataset abstract."
    assert candidate.item.fields["url"] == "https://example.org/dataset"
    assert candidate.item.identifiers["doi"] == "10.5438/datacite-demo"
    assert candidate.item.creators[0].first_name == "Ada"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.item.tags == ["robotics", "AI"]
    assert "DataCite Resource Type: Dataset" in candidate.item.fields["extra"]
    assert "DataCite Resource Type Detail: Robot dataset" in candidate.item.fields["extra"]
    assert "Rights: CC-BY-4.0" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://example.org/dataset"


def test_github_provider_maps_repository_results_to_software_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "items": [
                {
                    "id": 123,
                    "full_name": "openai/robot-retrieval",
                    "description": "Robot retrieval toolkit.",
                    "html_url": "https://github.com/openai/robot-retrieval",
                    "language": "Python",
                    "stargazers_count": 4242,
                    "forks_count": 42,
                    "license": {"spdx_id": "MIT"},
                    "topics": ["robotics", "retrieval"],
                    "updated_at": "2026-06-01T10:00:00Z",
                    "default_branch": "main",
                }
            ]
        }

    candidates = GitHubProvider(get_json=fake_json).search("robot retrieval", limit=4)

    assert "q=robot+retrieval" in seen_urls[0]
    assert "per_page=4" in seen_urls[0]
    candidate = candidates[0]
    assert candidate.source == "github"
    assert candidate.item.item_type == "computerProgram"
    assert candidate.item.fields["title"] == "openai/robot-retrieval"
    assert candidate.item.fields["abstractNote"] == "Robot retrieval toolkit."
    assert candidate.item.fields["programmingLanguage"] == "Python"
    assert candidate.item.fields["repository"] == "GitHub"
    assert candidate.item.tags == ["robotics", "retrieval"]
    assert "Stars: 4242" in candidate.item.fields["extra"]
    assert "License: MIT" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://github.com/openai/robot-retrieval"


def test_huggingface_provider_maps_models_and_datasets() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> list[dict[str, object]]:
        seen_urls.append(url)
        if "/api/models" in url:
            return [
                {
                    "id": "org/robot-model",
                    "pipeline_tag": "text-generation",
                    "tags": ["pytorch", "robotics"],
                    "downloads": 1000,
                    "likes": 50,
                    "lastModified": "2026-05-20T00:00:00Z",
                }
            ]
        return [
            {
                "id": "org/robot-dataset",
                "tags": ["dataset", "robotics"],
                "downloads": 200,
                "likes": 12,
                "lastModified": "2026-05-21T00:00:00Z",
            }
        ]

    candidates = HuggingFaceProvider(get_json=fake_json).search("robot", limit=4)

    assert any("/api/models" in url for url in seen_urls)
    assert any("/api/datasets" in url for url in seen_urls)
    model = candidates[0]
    dataset = candidates[1]
    assert model.source == "huggingface"
    assert model.item.item_type == "computerProgram"
    assert model.item.fields["title"] == "org/robot-model"
    assert model.item.fields["repository"] == "HuggingFace Hub"
    assert "Downloads: 1000" in model.item.fields["extra"]
    assert dataset.item.item_type == "dataset"
    assert dataset.item.fields["title"] == "org/robot-dataset"
    assert dataset.landing_url == "https://huggingface.co/datasets/org/robot-dataset"


def test_zenodo_provider_maps_records_to_doi_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "hits": {
                "hits": [
                    {
                        "id": 99,
                        "conceptdoi": "10.5281/zenodo.100",
                        "links": {"html": "https://zenodo.org/records/99"},
                        "metadata": {
                            "title": "Robot Dataset Release",
                            "doi": "10.5281/ZENODO.99",
                            "description": "<p>Dataset record.</p>",
                            "publication_date": "2026-06-15",
                            "upload_type": "dataset",
                            "creators": [{"name": "Lovelace, Ada"}],
                            "keywords": ["robotics", "dataset"],
                            "license": {"id": "cc-by-4.0"},
                            "version": "1.0",
                        },
                    }
                ]
            }
        }

    candidates = ZenodoProvider(get_json=fake_json).search("robot dataset", limit=2)

    assert "q=robot+dataset" in seen_urls[0]
    assert "size=2" in seen_urls[0]
    candidate = candidates[0]
    assert candidate.source == "zenodo"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "Robot Dataset Release"
    assert candidate.item.fields["abstractNote"] == "Dataset record."
    assert candidate.item.identifiers["doi"] == "10.5281/zenodo.99"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.item.tags == ["robotics", "dataset"]
    assert "License: cc-by-4.0" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://zenodo.org/records/99"


def test_local_file_provider_maps_csv_rows_to_candidates(tmp_path: Path) -> None:
    csv_path = tmp_path / "competition.csv"
    csv_path.write_text(
        "\n".join(
            [
                "local_id,title,authors,year,doi,abstract,keywords,item_type,url,venue",
                "row-1,Robot Dataset Benchmark,Ada Lovelace; Grace Hopper,2026,10.5555/LOCAL-DEMO,Internal robot dataset abstract.,robotics; dataset,dataset,https://example.test/local,AI4S Data Repo",
                "row-2,Unrelated Chemistry Note,Marie Curie,2025,,Chemistry note.,chemistry,journalArticle,https://example.test/chem,Lab Notes",
            ]
        ),
        encoding="utf-8",
    )

    candidates = LocalFileProvider(paths=[csv_path]).search("robot dataset", limit=5)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "localfile"
    assert candidate.external_id == "10.5555/local-demo"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "Robot Dataset Benchmark"
    assert candidate.item.fields["date"] == "2026"
    assert candidate.item.fields["DOI"] == "10.5555/local-demo"
    assert candidate.item.fields["abstractNote"] == "Internal robot dataset abstract."
    assert candidate.item.fields["publicationTitle"] == "AI4S Data Repo"
    assert candidate.item.identifiers["doi"] == "10.5555/local-demo"
    assert [creator.last_name for creator in candidate.item.creators] == ["Lovelace", "Hopper"]
    assert candidate.item.tags == ["robotics", "dataset"]
    assert "Local Source File: competition.csv" in candidate.item.fields["extra"]
    assert "Local Source Row: 2" in candidate.item.fields["extra"]
    assert "Local Source ID: row-1" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://example.test/local"


def test_local_file_provider_uses_configured_field_map(tmp_path: Path) -> None:
    csv_path = tmp_path / "custom-columns.csv"
    csv_path.write_text(
        "\n".join(
            [
                "row_key,headline,published_on,identifier_value,creator_names,body_text,topic_terms,kind,landing",
                "custom-1,Custom Mapped Robot Dataset,2026,10.6060/CUSTOM-MAP,Ada Lovelace; Grace Hopper,Custom mapped abstract,robotics; mapping,dataset,https://example.test/custom",
            ]
        ),
        encoding="utf-8",
    )
    field_map = {
        "external_id": "row_key",
        "title": "headline",
        "date": "published_on",
        "doi": "identifier_value",
        "authors": "creator_names",
        "abstract": "body_text",
        "tags": "topic_terms",
        "item_type": "kind",
        "url": "landing",
    }

    candidates = LocalFileProvider(paths=[csv_path], field_map=field_map).search("custom robot", limit=3)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.external_id == "10.6060/custom-map"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "Custom Mapped Robot Dataset"
    assert candidate.item.fields["date"] == "2026"
    assert candidate.item.fields["abstractNote"] == "Custom mapped abstract"
    assert candidate.item.identifiers["doi"] == "10.6060/custom-map"
    assert [creator.last_name for creator in candidate.item.creators] == ["Lovelace", "Hopper"]
    assert candidate.item.tags == ["robotics", "mapping"]
    assert "Local Source ID: custom-1" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://example.test/custom"


def test_local_file_provider_maps_jsonl_rows_with_structured_lists(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "internal.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "skip", "title": "Unrelated", "keywords": ["chemistry"]}),
                json.dumps(
                    {
                        "id": "local-jsonl-1",
                        "title": "Vision Robot Software Toolkit",
                        "type": "software",
                        "authors": [{"givenName": "Ada", "familyName": "Lovelace"}],
                        "keywords": ["robotics", "software"],
                        "arxiv_id": "2406.09246v2",
                        "description": "Local toolkit metadata.",
                        "link": "https://example.test/toolkit",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    candidates = LocalFileProvider(paths=[jsonl_path]).search("vision robot", limit=5)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.external_id == "2406.09246"
    assert candidate.item.item_type == "computerProgram"
    assert candidate.item.fields["title"] == "Vision Robot Software Toolkit"
    assert candidate.item.fields["abstractNote"] == "Local toolkit metadata."
    assert candidate.item.identifiers["arxiv"] == "2406.09246"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.item.tags == ["robotics", "software"]
    assert "arXiv ID" in candidate.evidence


def test_http_json_provider_maps_configured_results_to_candidates() -> None:
    seen_urls: list[str] = []
    config = {
        "label": "Internal API",
        "url_template": "https://internal.test/search?q={query}&limit={limit}",
        "items_path": "results.items",
        "field_map": {
            "title": "metadata.title",
            "date": "metadata.year",
            "doi": "ids.doi",
            "abstract": "metadata.abstract",
            "authors": "metadata.authors",
            "url": "links.landing",
            "venue": "metadata.venue",
            "item_type": "kind",
            "tags": "metadata.keywords",
            "external_id": "id",
            "pdf_url": "links.pdf",
        },
    }

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "results": {
                "items": [
                    {
                        "id": "internal-1",
                        "kind": "dataset",
                        "ids": {"doi": "10.6060/HTTP-JSON"},
                        "metadata": {
                            "title": "HTTP JSON Robot Dataset",
                            "year": 2026,
                            "abstract": "Internal API abstract.",
                            "venue": "AI4S Internal Registry",
                            "authors": [{"givenName": "Ada", "familyName": "Lovelace"}],
                            "keywords": ["robotics", "dataset"],
                        },
                        "links": {
                            "landing": "https://internal.test/items/internal-1",
                            "pdf": "https://internal.test/items/internal-1.pdf",
                        },
                    }
                ]
            }
        }

    candidates = HttpJsonProvider(config=config, get_json=fake_json).search("robot dataset", limit=3)

    assert seen_urls == ["https://internal.test/search?q=robot+dataset&limit=3"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "httpjson"
    assert candidate.external_id == "10.6060/http-json"
    assert candidate.item.source == "Internal API"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "HTTP JSON Robot Dataset"
    assert candidate.item.fields["date"] == "2026"
    assert candidate.item.fields["DOI"] == "10.6060/http-json"
    assert candidate.item.fields["abstractNote"] == "Internal API abstract."
    assert candidate.item.fields["publicationTitle"] == "AI4S Internal Registry"
    assert candidate.item.identifiers["doi"] == "10.6060/http-json"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.item.tags == ["robotics", "dataset"]
    assert "HTTP JSON Source: Internal API" in candidate.item.fields["extra"]
    assert "HTTP JSON Source ID: internal-1" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://internal.test/items/internal-1"
    assert candidate.pdf_url == "https://internal.test/items/internal-1.pdf"
    assert "DOI" in candidate.evidence


def test_http_json_provider_paginates_with_template_placeholders() -> None:
    seen_urls: list[str] = []
    config = {
        "url_template": "https://internal.test/search?q={query}&limit={limit}&page={page}&offset={offset}",
        "items_path": "results",
        "max_pages": 5,
        "field_map": {"title": "title", "doi": "doi", "external_id": "id"},
    }

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        if "page=1" in url:
            return {"results": [{"id": "page-1", "title": "Paged Result One", "doi": "10.6060/PAGE-1"}]}
        if "page=2" in url:
            return {
                "results": [
                    {"id": "page-2", "title": "Paged Result Two", "doi": "10.6060/PAGE-2"},
                    {"id": "page-3", "title": "Paged Result Three", "doi": "10.6060/PAGE-3"},
                ]
            }
        return {"results": []}

    candidates = HttpJsonProvider(config=config, get_json=fake_json).search("paged robot", limit=3)

    assert seen_urls == [
        "https://internal.test/search?q=paged+robot&limit=3&page=1&offset=0",
        "https://internal.test/search?q=paged+robot&limit=3&page=2&offset=3",
    ]
    assert [candidate.item.fields["title"] for candidate in candidates] == [
        "Paged Result One",
        "Paged Result Two",
        "Paged Result Three",
    ]


def test_http_json_provider_paginates_with_next_url_path() -> None:
    seen_urls: list[str] = []
    config = {
        "url_template": "https://internal.test/search?q={query}&limit={limit}",
        "items_path": "items",
        "next_url_path": "links.next",
        "max_pages": 3,
        "field_map": {"title": "title", "external_id": "id"},
    }

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        if len(seen_urls) == 1:
            return {
                "items": [{"id": "next-1", "title": "Next Link Result One"}],
                "links": {"next": "/search?page=cursor-2"},
            }
        return {"items": [{"id": "next-2", "title": "Next Link Result Two"}], "links": {}}

    candidates = HttpJsonProvider(config=config, get_json=fake_json).search("next robot", limit=5)

    assert seen_urls == [
        "https://internal.test/search?q=next+robot&limit=5",
        "https://internal.test/search?page=cursor-2",
    ]
    assert [candidate.external_id for candidate in candidates] == ["next-1", "next-2"]


def test_http_json_provider_expands_env_headers_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_TEAM", "ai4s")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret-token")
    seen: list[tuple[str, dict[str, str] | None]] = []
    config = {
        "url_template": "https://internal.test/search?q={query}",
        "items_path": "items",
        "headers": {
            "X-Team": "${ENV:INTERNAL_TEAM}",
            "Accept": "application/json",
        },
        "auth": {"type": "bearer_env", "env": "INTERNAL_API_TOKEN"},
        "field_map": {"title": "title", "external_id": "id"},
    }

    def fake_get_json(url: str, *, headers=None, **kwargs) -> dict:
        seen.append((url, headers))
        return {"items": [{"id": "secure-1", "title": "Secure Internal Result"}]}

    monkeypatch.setattr(retrieval_providers, "_http_get_json", fake_get_json)

    candidates = HttpJsonProvider(config=config).search("secure robot", limit=2)

    assert seen == [
        (
            "https://internal.test/search?q=secure+robot",
            {
                "X-Team": "ai4s",
                "Accept": "application/json",
                "Authorization": "Bearer secret-token",
            },
        )
    ]
    assert candidates[0].external_id == "secure-1"


def test_http_json_source_status_reports_missing_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    statuses = retrieval_source_statuses(
        registry={
            "httpjson": HttpJsonProvider(
                config={
                    "url_template": "https://internal.test/search?q={query}",
                    "auth": {"type": "bearer_env", "env": "INTERNAL_API_TOKEN"},
                }
            )
        }
    )

    status = statuses[0]
    assert status["name"] == "httpjson"
    assert status["available"] is False
    assert status["configured"] is False
    assert "INTERNAL_API_TOKEN" in status["message"]


def test_http_json_preview_reports_mapping_quality() -> None:
    config = {
        "label": "Preview API",
        "url_template": "https://internal.test/search?q={query}&limit={limit}",
        "items_path": "results",
        "field_map": {
            "title": "title",
            "date": "year",
            "doi": "doi",
            "authors": "authors",
            "tags": "keywords",
            "external_id": "id",
        },
    }

    def fake_json(url: str) -> dict:
        return {
            "results": [
                {
                    "id": "preview-1",
                    "title": "Preview Robot Dataset",
                    "year": "2026",
                    "doi": "10.6060/PREVIEW",
                    "authors": "Ada Lovelace",
                    "keywords": "robotics; dataset",
                },
                {"id": "preview-2", "title": "Incomplete Preview Row"},
            ]
        }

    preview = retrieval_providers.preview_http_json_mappings(
        config,
        query="preview robot",
        sample_size=2,
        get_json=fake_json,
    )

    assert preview["label"] == "Preview API"
    assert preview["query"] == "preview robot"
    assert preview["quality"]["row_count"] == 2
    assert preview["quality"]["rows_with_issues"] == 1
    assert preview["samples"][0]["item"]["fields"]["title"] == "Preview Robot Dataset"
    assert preview["samples"][0]["item"]["identifiers"]["doi"] == "10.6060/preview"
    assert preview["samples"][0]["quality"]["status"] == "good"
    assert preview["samples"][1]["quality"]["status"] == "poor"


def test_http_json_config_templates_are_valid_configs() -> None:
    templates = retrieval_providers.http_json_config_templates()

    assert {template["id"] for template in templates} == {"basic-rest", "bearer-page", "api-key-cursor"}
    for template in templates:
        config = retrieval_providers.http_json_config(template["config"])
        assert config["url_template"]
        assert isinstance(config["field_map"], dict)
        assert "title" in config["field_map"]


def test_retrieval_field_map_suggestion_builds_config_draft_from_nested_sample() -> None:
    sample = {
        "record_id": "sample-1",
        "metadata": {
            "paperTitle": "Nested Robot Dataset",
            "publication_year": "2026",
            "creators": [{"givenName": "Ada", "familyName": "Lovelace"}],
            "keywords": ["robotics", "dataset"],
            "summary": "A nested sample abstract.",
        },
        "identifiers": {"doi": "10.6060/NESTED"},
        "links": {
            "object_url": "https://example.test/object/sample-1",
            "pdf": "https://example.test/object/sample-1.pdf",
        },
    }

    suggestion = retrieval_providers.retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "httpjson",
            "config": {
                "label": "Competition API",
                "url_template": "https://example.test/search?q={query}",
                "items_path": "data.records",
                "field_map": {"external_id": "record_id"},
            },
            "samples": [sample],
        }
    )

    field_map = suggestion["field_map"]
    assert field_map["title"] == "metadata.paperTitle"
    assert field_map["date"] == "metadata.publication_year"
    assert field_map["abstract"] == "metadata.summary"
    assert field_map["authors"] == "metadata.creators"
    assert field_map["tags"] == "metadata.keywords"
    assert field_map["doi"] == "identifiers.doi"
    assert field_map["url"] == "links.object_url"
    assert field_map["pdf_url"] == "links.pdf"
    assert field_map["external_id"] == "record_id"
    assert suggestion["quality"]["status"] == "good"
    assert suggestion["quality"]["coverage"] == {
        "title": True,
        "identifier": True,
        "date": True,
        "creators": True,
    }
    assert suggestion["config_draft"]["field_map"]["title"] == "metadata.paperTitle"
    assert any(item["target"] == "external_id" and item["existing"] is True for item in suggestion["suggestions"])

    text_config_suggestion = retrieval_providers.retrieval_field_map_suggestion_from_payload(
        {
            "config_text": json.dumps({"label": "Text Config API", "field_map": {"external_id": "record_id"}}),
            "columns": ["paper_title", "doi"],
        }
    )
    assert text_config_suggestion["config_draft"]["label"] == "Text Config API"
    assert text_config_suggestion["config_draft"]["field_map"]["title"] == "paper_title"

    sqlite_starter = retrieval_providers.retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "sqlite",
            "columns": ["paper_title", "publication_year", "doi", "authors", "object_url"],
        }
    )
    assert sqlite_starter["config_draft"]["label"] == "Draft SQLite"
    assert sqlite_starter["config_draft"]["path"] == "C:/data/retrieval.sqlite"
    assert "paper_title" in sqlite_starter["config_draft"]["query"]
    assert sqlite_starter["config_draft"]["field_map"]["title"] == "paper_title"

    http_starter = retrieval_providers.retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "http-json",
            "samples": [sample],
        }
    )
    assert http_starter["source_type"] == "httpjson"
    assert http_starter["config_draft"]["label"] == "Draft HTTP JSON"
    assert http_starter["config_draft"]["items_path"] == "results"
    assert http_starter["config_draft"]["field_map"]["doi"] == "identifiers.doi"


def test_retrieval_source_intake_classifies_real_source_drafts(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_local_copy(zotero_fixture, name="Source Intake Target")
    client = create_app().test_client()

    csv_payload = {
        "input": "paper_title,publication_year,doi,authors,abstract\nRobot Dataset,2026,10.6060/INTAKE,Ada,Summary"
    }
    csv_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json=csv_payload,
    )

    assert csv_response.status_code == 200
    csv_intake = csv_response.get_json()["intake"]
    assert csv_intake["schema"] == "web-library.retrieval-source-intake/v1"
    assert csv_intake["source_type"] == "localfile"
    assert csv_intake["target_source"]["name"] == "localfile"
    assert csv_intake["target_source"]["endpoint"] == "/retrieval/local-files"
    assert csv_intake["validation_plan"]["target_source"] == "localfile"
    assert csv_intake["validation_plan"]["status"] == "needs_config"
    assert csv_intake["validation_plan"]["source_status"]["known"] is True
    assert csv_intake["validation_plan"]["source_status"]["available"] is False
    assert csv_intake["validation_plan"]["minimum_queries"] == 3
    assert {gate["name"] for gate in csv_intake["validation_plan"]["gates"]} >= {
        "save_config",
        "readiness",
        "batch_validation",
        "onboarding",
    }
    gates_by_name = {gate["name"]: gate for gate in csv_intake["validation_plan"]["gates"]}
    assert gates_by_name["save_config"]["status"] == "pending"
    assert gates_by_name["readiness"]["status"] == "blocked"
    assert gates_by_name["batch_validation"]["status"] == "blocked"
    assert csv_intake["candidates"][0]["endpoint"] == "/retrieval/local-files"
    assert csv_intake["signals"]["column_count"] == 5
    assert csv_intake["field_map_suggestion"]["field_map"]["title"] == "paper_title"
    assert csv_intake["field_map_lab"]["input_mode"] == "columns"

    markdown_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake/report",
        json=csv_payload,
    )
    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-source-intake-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "Retrieval source intake" in markdown_text
    assert "Local CSV/JSONL" in markdown_text
    assert "Target batch source: localfile" in markdown_text
    assert "Validation Plan" in markdown_text
    assert "Run READY preflight" in markdown_text
    assert "paper_title" in markdown_text
    assert "Field map" in markdown_text
    assert "Validation Queries" in markdown_text

    csv_report_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake/report?format=csv",
        json=csv_payload,
    )
    assert csv_report_response.status_code == 200
    assert csv_report_response.headers["Content-Type"].startswith("text/csv")
    csv_report_text = csv_report_response.get_data(as_text=True)
    assert csv_report_text.startswith("section,name,value,details")
    assert "overview,target_source,localfile" in csv_report_text
    assert "validation_plan,status" in csv_report_text
    assert "validation_gate,readiness" in csv_report_text
    assert "validation_artifact,ONB ZIP,/retrieval/onboarding/package" in csv_report_text
    assert "candidate,localfile" in csv_report_text
    assert "field_map,title,paper_title" in csv_report_text
    assert "validation_query_status,empty,0" in csv_report_text

    json_report_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake/report?format=json",
        json=csv_payload,
    )
    assert json_report_response.status_code == 200
    assert json_report_response.headers["Content-Type"].startswith("application/json")
    json_report = json_report_response.get_json()
    assert json_report["schema"] == "web-library.retrieval-source-intake/v1"
    assert json_report["source_type"] == "localfile"
    assert json_report["target_source"]["name"] == "localfile"
    assert json_report["validation_plan"]["artifacts"][-1]["label"] == "ONB ZIP"

    sqlite_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": "SELECT title, year, doi, authors FROM records WHERE title LIKE :like_query LIMIT :limit"},
    )

    assert sqlite_response.status_code == 200
    sqlite_intake = sqlite_response.get_json()["intake"]
    assert sqlite_intake["source_type"] == "sqlite"
    assert sqlite_intake["target_source"]["name"] == "sqlite"
    assert sqlite_intake["candidates"][0]["endpoint"] == "/retrieval/sqlite"
    assert sqlite_intake["signals"]["has_sql"] is True
    assert sqlite_intake["field_map_suggestion"]["config_draft"]["path"] == "C:/data/retrieval.sqlite"

    manifest_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={
            "input": json.dumps(
                {
                    "objects": [
                        {
                            "object_id": "obj-1",
                            "metadata": {"title": "Manifest Robot Dataset", "year": "2026"},
                            "links": {"pdf": "https://example.test/obj-1.pdf"},
                        }
                    ]
                }
            )
        },
    )

    assert manifest_response.status_code == 200
    manifest_intake = manifest_response.get_json()["intake"]
    assert manifest_intake["source_type"] == "manifest"
    assert manifest_intake["target_source"]["name"] == "manifest"
    assert manifest_intake["signals"]["items_path"] == "objects"
    assert manifest_intake["field_map_lab"]["input_mode"] == "samples"
    assert manifest_intake["field_map_suggestion"]["config_draft"]["items_path"] == "objects"
    assert manifest_intake["validation_queries"]["status"] == "low_sample"
    assert manifest_intake["validation_queries"]["query_count"] == 1
    assert "manifest robot" in manifest_intake["validation_queries"]["query_text"]


def test_retrieval_source_intake_samples_http_json_url_only_when_requested(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture, name="Source Intake HTTP Target")
    client = create_app().test_client()
    seen_configs: list[dict[str, object]] = []

    def fake_http_json_sample_items(
        config_value: dict[str, object] | str | None = None,
        *,
        query: str = "robot",
        sample_size: int = 3,
        get_json=None,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        config = dict(config_value if isinstance(config_value, dict) else {})
        seen_configs.append({"config": config, "query": query, "sample_size": sample_size})
        config["items_path"] = "results"
        return config, [
            {
                "paper_title": "HTTP Intake Dataset",
                "keywords": ["robot", "catalyst"],
                "publication_year": "2026",
                "doi": "10.6060/HTTPINTAKE",
                "authors": "Ada Lovelace",
                "abstract": "Remote HTTP sample",
            }
        ]

    monkeypatch.setattr(web, "http_json_sample_items", fake_http_json_sample_items)
    url = "https://api.example.test/search?q={query}&limit={limit}"

    no_sample_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": url},
    )

    assert no_sample_response.status_code == 200
    no_sample_intake = no_sample_response.get_json()["intake"]
    assert no_sample_intake["source_type"] == "httpjson"
    assert no_sample_intake["status"] == "needs_sample"
    assert no_sample_intake["signals"]["sample_url_requested"] is False
    assert no_sample_intake["signals"]["sample_count"] == 0
    assert seen_configs == []

    sample_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": url, "sample_url": True, "query": "robotics", "sample_size": 2},
    )

    assert sample_response.status_code == 200
    intake = sample_response.get_json()["intake"]
    config_draft = intake["field_map_suggestion"]["config_draft"]
    assert seen_configs[0]["config"]["url_template"] == url
    assert seen_configs[0]["query"] == "robotics"
    assert seen_configs[0]["sample_size"] == 2
    assert intake["source_type"] == "httpjson"
    assert intake["target_source"]["name"] == "httpjson"
    assert intake["signals"]["sample_url_requested"] is True
    assert intake["signals"]["sampled_url"] == url
    assert intake["signals"]["sample_query"] == "robotics"
    assert intake["signals"]["items_path"] == "results"
    assert intake["signals"]["sample_count"] == 1
    assert intake["signals"]["has_json_sample"] is True
    assert intake["field_map_lab"]["input_mode"] == "samples"
    assert intake["field_map_suggestion"]["field_map"]["title"] == "paper_title"
    assert intake["field_map_suggestion"]["field_map"]["doi"] == "doi"
    assert intake["validation_queries"]["status"] == "low_sample"
    assert intake["validation_queries"]["query_count"] == 1
    assert "http intake" in intake["validation_queries"]["query_text"]
    assert config_draft["url_template"] == url
    assert config_draft["items_path"] == "results"


def test_retrieval_source_intake_samples_existing_local_paths(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_local_copy(zotero_fixture, name="Source Intake Path Target")
    client = create_app().test_client()

    csv_path = tmp_path / "records.csv"
    csv_path.write_text(
        "paper_title,publication_year,doi,authors,abstract\n"
        "Path Sample Dataset,2026,10.6060/PATH,Ada Lovelace,CSV row sample\n",
        encoding="utf-8",
    )

    csv_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(csv_path)},
    )

    assert csv_response.status_code == 200
    csv_intake = csv_response.get_json()["intake"]
    assert csv_intake["source_type"] == "localfile"
    assert csv_intake["signals"]["sampled_path"] == str(csv_path)
    assert csv_intake["signals"]["sample_count"] == 1
    assert csv_intake["signals"]["column_count"] == 5
    assert csv_intake["field_map_lab"]["input_mode"] == "samples"
    assert csv_intake["field_map_suggestion"]["field_map"]["title"] == "paper_title"
    assert csv_intake["field_map_suggestion"]["config_draft"]["paths"] == [str(csv_path)]
    initial_plan_gates = {gate["name"]: gate for gate in csv_intake["validation_plan"]["gates"]}
    assert initial_plan_gates["save_config"]["status"] == "pending"

    save_local_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(csv_path)]},
    )
    assert save_local_response.status_code == 200
    configured_csv_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(csv_path)},
    )
    assert configured_csv_response.status_code == 200
    configured_csv_intake = configured_csv_response.get_json()["intake"]
    configured_plan_gates = {gate["name"]: gate for gate in configured_csv_intake["validation_plan"]["gates"]}
    assert configured_csv_intake["validation_plan"]["source_status"]["available"] is True
    assert configured_csv_intake["validation_plan"]["batch_validation"]["status"] == "missing"
    assert configured_plan_gates["save_config"]["status"] == "passed"
    assert configured_plan_gates["readiness"]["status"] == "ready"
    assert configured_plan_gates["batch_validation"]["status"] == "needs_queries"
    draft_query = configured_csv_intake["validation_queries"]["queries"][0]["query"]

    validation_job = app_store.create_retrieval_batch_job(
        library["library_id"],
        [draft_query, "path sample two", "path sample three"],
        ["localfile"],
        3,
    )
    validation_items = app_store.retrieval_batch_items_for_job(library["library_id"], validation_job["job_id"])
    for index, item in enumerate(validation_items, start=1):
        app_store.complete_retrieval_batch_item(
            library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id=f"run-source-intake-validation-{index}",
            candidate_count=1,
            source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 6}},
        )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], validation_job["job_id"], "completed")

    validated_csv_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(csv_path)},
    )
    assert validated_csv_response.status_code == 200
    validated_csv_intake = validated_csv_response.get_json()["intake"]
    validated_plan = validated_csv_intake["validation_plan"]
    validated_plan_gates = {gate["name"]: gate for gate in validated_plan["gates"]}
    assert validated_plan["status"] == "passed"
    assert validated_plan["batch_validation"]["status"] == "passed"
    assert validated_plan["batch_validation"]["completed_queries"] == 3
    assert validated_plan["batch_validation"]["validated_sources"] == ["localfile"]
    assert validated_plan["batch_validation"]["required_queries"] == [draft_query]
    assert validated_plan["batch_validation"]["covered_queries"] == [draft_query]
    assert validated_plan["batch_validation"]["missing_queries"] == []
    assert validated_plan["batch_validation"]["config_context_status"] == "unknown"
    assert validated_plan["batch_validation"]["remediation"]["action"] == "download_batch_report"
    assert validated_plan_gates["batch_validation"]["status"] == "passed"
    assert "Config context unknown." in validated_plan_gates["batch_validation"]["evidence"]
    assert "Next: Download batch report." in validated_plan_gates["batch_validation"]["evidence"]
    assert validated_plan_gates["batch_validation"]["endpoint"] == f"/retrieval/batches/{validation_job['job_id']}/report"
    assert validated_plan["artifacts"][-2]["label"] == "Latest batch report"

    report_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake/report?format=csv",
        json={"input": str(csv_path)},
    )
    assert report_response.status_code == 200
    report_text = report_response.get_data(as_text=True)
    assert "validation_batch,config_context,unknown" in report_text
    assert "validation_batch,remediation,download_batch_report" in report_text

    db_path = tmp_path / "retrieval.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE records (
                id TEXT,
                paper_title TEXT,
                publication_year TEXT,
                doi TEXT,
                authors TEXT,
                abstract TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO records (id, paper_title, publication_year, doi, authors, abstract)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("sqlite-1", "SQLite Path Sample", "2026", "10.6060/SQLITEPATH", "Grace Hopper", "SQLite row sample"),
        )

    sqlite_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(db_path)},
    )

    assert sqlite_response.status_code == 200
    sqlite_intake = sqlite_response.get_json()["intake"]
    sqlite_config = sqlite_intake["field_map_suggestion"]["config_draft"]
    assert sqlite_intake["source_type"] == "sqlite"
    assert sqlite_intake["signals"]["sampled_path"] == str(db_path)
    assert sqlite_intake["signals"]["sampled_table"] == "records"
    assert sqlite_intake["signals"]["sample_count"] == 1
    assert sqlite_intake["field_map_suggestion"]["field_map"]["title"] == "paper_title"
    assert sqlite_config["path"] == str(db_path)
    assert 'FROM "records"' in sqlite_config["query"]

    manifest_path = tmp_path / "object-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "data": {
                    "records": [
                        {
                            "id": "manifest-path-1",
                            "name": "Manifest Path Sample",
                            "publicationYear": "2026",
                            "doi": "10.6060/MANIFESTPATH",
                            "authors": "Katherine Johnson",
                            "description": "Manifest path sample",
                            "object_url": "https://example.test/object/manifest-path-1",
                            "pdf_url": "https://example.test/object/manifest-path-1.pdf",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    manifest_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(manifest_path)},
    )

    assert manifest_response.status_code == 200
    manifest_intake = manifest_response.get_json()["intake"]
    manifest_config = manifest_intake["field_map_suggestion"]["config_draft"]
    assert manifest_intake["source_type"] == "manifest"
    assert manifest_intake["signals"]["sampled_path"] == str(manifest_path)
    assert manifest_intake["signals"]["items_path"] == "data.records"
    assert manifest_intake["signals"]["sample_count"] == 1
    assert manifest_intake["field_map_suggestion"]["field_map"]["title"] == "name"
    assert manifest_config["manifest_path"] == str(manifest_path)
    assert manifest_config["items_path"] == "data.records"


def test_retrieval_source_intake_detects_batch_config_drift(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_local_copy(zotero_fixture, name="Source Intake Config Drift")
    client = create_app().test_client()
    first_csv = tmp_path / "intake-config-first.csv"
    first_csv.write_text(
        "paper_title,publication_year,doi,authors,abstract\n"
        "Intake Config First,2026,10.6060/INTAKE-CONFIG-1,Ada Lovelace,First config sample\n",
        encoding="utf-8",
    )
    second_csv = tmp_path / "intake-config-second.csv"
    second_csv.write_text(
        "paper_title,publication_year,doi,authors,abstract\n"
        "Intake Config Second,2026,10.6060/INTAKE-CONFIG-2,Ada Lovelace,Second config sample\n",
        encoding="utf-8",
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(first_csv)]},
        ).status_code
        == 200
    )
    first_intake = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(first_csv)},
    ).get_json()["intake"]
    first_query = first_intake["validation_queries"]["queries"][0]["query"]
    batch_job = app_store.create_retrieval_batch_job(
        library["library_id"],
        [first_query, "intake config beta", "intake config gamma"],
        ["localfile"],
        3,
        context=web.retrieval_batch_context_for_library(library["library_id"]),
    )
    batch_items = app_store.retrieval_batch_items_for_job(library["library_id"], batch_job["job_id"])
    for index, item in enumerate(batch_items, start=1):
        app_store.complete_retrieval_batch_item(
            library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id=f"run-source-intake-config-drift-{index}",
            candidate_count=1,
            source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 6}},
        )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], batch_job["job_id"], "completed")

    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(second_csv)]},
        ).status_code
        == 200
    )
    drift_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake",
        json={"input": str(second_csv)},
    )

    assert drift_response.status_code == 200
    drift_intake = drift_response.get_json()["intake"]
    drift_plan = drift_intake["validation_plan"]
    drift_gates = {gate["name"]: gate for gate in drift_plan["gates"]}
    assert drift_plan["status"] == "config_drift"
    assert drift_plan["batch_validation"]["status"] == "config_drift"
    assert drift_plan["batch_validation"]["config_context_status"] == "mismatch"
    assert drift_plan["batch_validation"]["config_mismatch_job_count"] == 1
    assert drift_plan["batch_validation"]["remediation"]["action"] == "rerun_current_config_batch"
    assert drift_gates["batch_validation"]["status"] == "config_drift"
    assert "Config context mismatch." in drift_gates["batch_validation"]["evidence"]
    assert "Next: Run current-config batch." in drift_gates["batch_validation"]["evidence"]

    report_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/source-intake/report?format=markdown",
        json={"input": str(second_csv)},
    )
    assert report_response.status_code == 200
    report_text = report_response.get_data(as_text=True)
    assert "- Config context: mismatch" in report_text
    assert "- Remediation: Run current-config batch" in report_text


def test_retrieval_field_map_suggestion_can_use_ai_pixel_enhancement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PIXEL_API_KEY", "secret-ai-key")
    calls: list[dict[str, object]] = []

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, object], timeout: int) -> dict:
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "field_map": {
                                    "date": "yr",
                                    "authors": "writer_names",
                                    "publisher": "missing_path",
                                },
                                "notes": ["yr is the publication year"],
                            }
                        )
                    }
                }
            ]
        }

    suggestion = retrieval_providers.retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "httpjson",
            "columns": ["paper_title", "yr", "doi", "writer_names"],
            "use_ai": True,
            "_ai_post_json": fake_post_json,
        }
    )

    assert calls
    assert calls[0]["url"] == "https://ai-pixel.online/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-ai-key"
    assert suggestion["field_map"]["title"] == "paper_title"
    assert suggestion["field_map"]["date"] == "yr"
    assert suggestion["field_map"]["authors"] == "writer_names"
    assert suggestion["quality"]["coverage"]["creators"] is True
    assert suggestion["ai_enhancement"]["status"] == "applied"
    assert suggestion["ai_enhancement"]["applied_field_count"] == 2
    assert suggestion["ai_enhancement"]["rejected"][0]["source_path"] == "missing_path"
    assert any(item.get("ai") is True and item["target"] == "date" for item in suggestion["suggestions"])


def test_library_api_config_saves_masks_and_overrides_environment(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("AI_PIXEL_API_KEY", "env-secret")
    monkeypatch.setenv("AI_PIXEL_MODEL", "env-model")
    monkeypatch.setenv("AI_PIXEL_BASE_URL", "https://env.example.test")
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    initial = client.get(f"/api/library/{library['library_id']}/api-config").get_json()["config"]
    assert initial["model"]["configured"] is True
    assert initial["model"]["source"] == "environment"
    assert initial["model"]["api_key"] == ""
    assert initial["model"]["model"] == "env-model"

    response = client.post(
        f"/api/library/{library['library_id']}/api-config",
        json={
            "model": {
                "model": "gpt-5.5",
                "base_url": "https://ai-pixel.online",
                "api_key": "page-secret",
            },
            "code_sources": {
                "github_token": "ghp-demo",
                "huggingface_token": "hf-demo",
                "zenodo_token": "zen-demo",
            },
        },
    )
    assert response.status_code == 200
    saved = response.get_json()["config"]
    assert saved["model"]["configured"] is True
    assert saved["model"]["source"] == "preference"
    assert saved["model"]["api_key"] == ""
    assert saved["model"]["model"] == "gpt-5.5"
    assert saved["model"]["chat_url"] == "https://ai-pixel.online/v1/chat/completions"
    assert saved["code_sources"]["github"]["source"] == "preference"

    shown = client.get(f"/api/library/{library['library_id']}/api-config?include_secrets=1").get_json()["config"]
    assert shown["model"]["api_key"] == "page-secret"
    assert shown["code_sources"]["huggingface"]["token"] == "hf-demo"

    status = client.get(f"/api/library/{library['library_id']}/retrieval/model-status").get_json()["model"]
    assert status["configured"] is True
    assert status["model"] == "gpt-5.5"
    assert status["chat_url"] == "https://ai-pixel.online/v1/chat/completions"
    assert status["source"] == "preference"

    client.post(
        f"/api/library/{library['library_id']}/api-config",
        json={
            "model": {
                "model": "gpt-5.5-mini",
                "base_url": "https://custom.example.test/v1/chat/completions",
                "api_key": web.API_CONFIG_SECRET_KEEP_VALUE,
            },
            "code_sources": {
                "github_token": web.API_CONFIG_SECRET_KEEP_VALUE,
                "huggingface_token": web.API_CONFIG_SECRET_KEEP_VALUE,
                "zenodo_token": web.API_CONFIG_SECRET_KEEP_VALUE,
            },
        },
    )
    kept = client.get(f"/api/library/{library['library_id']}/api-config?include_secrets=1").get_json()["config"]
    assert kept["model"]["api_key"] == "page-secret"
    assert kept["model"]["chat_url"] == "https://custom.example.test/v1/chat/completions"
    assert kept["code_sources"]["github"]["token"] == "ghp-demo"


def test_retrieval_field_map_suggestion_reports_unconfigured_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_PIXEL_API_KEY", raising=False)

    suggestion = retrieval_providers.retrieval_field_map_suggestion_from_payload(
        {
            "source_type": "sqlite",
            "columns": ["paper_title", "doi"],
            "use_ai": True,
        }
    )

    assert suggestion["field_map"]["title"] == "paper_title"
    assert suggestion["ai_enhancement"]["requested"] is True
    assert suggestion["ai_enhancement"]["configured"] is False
    assert suggestion["ai_enhancement"]["status"] == "not_configured"
    assert "AI_PIXEL_API_KEY" in suggestion["ai_enhancement"]["message"]


def test_retrieval_model_status_api_does_not_expose_api_key(
    zotero_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("AI_PIXEL_API_KEY", "secret-ai-key")
    monkeypatch.setenv("AI_PIXEL_BASE_URL", "https://ai-pixel.online")
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/model-status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["model"]["configured"] is True
    assert payload["model"]["api_key_env"] == "AI_PIXEL_API_KEY"
    assert payload["model"]["base_url"] == "https://ai-pixel.online"
    assert "secret-ai-key" not in json.dumps(payload, ensure_ascii=False)


def test_retrieval_model_health_check_calls_ai_pixel_without_exposing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PIXEL_API_KEY", "secret-ai-key")
    monkeypatch.setenv("AI_PIXEL_BASE_URL", "https://ai-pixel.online")
    calls: list[dict[str, object]] = []
    ticks = iter([10.0, 10.25])

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, object], timeout: int) -> dict:
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    health = retrieval_providers.retrieval_model_health_check(
        post_json=fake_post_json,
        now=lambda: next(ticks),
    )

    assert health["ok"] is True
    assert health["configured"] is True
    assert health["base_url"] == "https://ai-pixel.online"
    assert health["elapsed_ms"] == 250.0
    assert health["response_preview"] == '{"ok":true}'
    assert "secret-ai-key" not in json.dumps(health, ensure_ascii=False)
    assert calls[0]["url"] == "https://ai-pixel.online/v1/chat/completions"
    assert calls[0]["headers"] == {"Authorization": "Bearer secret-ai-key"}
    assert calls[0]["payload"]["max_tokens"] == 32


def test_retrieval_model_health_check_reports_missing_key_as_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_PIXEL_API_KEY", raising=False)
    calls: list[object] = []
    ticks = iter([10.0, 10.0])

    health = retrieval_providers.retrieval_model_health_check(
        post_json=lambda *args: calls.append(args),
        now=lambda: next(ticks),
    )

    assert calls == []
    assert health["ok"] is False
    assert health["configured"] is False
    assert health["error_kind"] == "configuration"
    assert "AI_PIXEL_API_KEY" in health["error"]


def test_retrieval_model_status_check_api_includes_health_without_key(
    zotero_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("AI_PIXEL_API_KEY", "secret-ai-key")
    monkeypatch.setattr(
        web,
        "retrieval_model_health_check",
        lambda: {
            "checked": True,
            "ok": True,
            "configured": True,
            "provider": "ai-pixel",
            "base_url": "https://ai-pixel.online",
            "chat_path": "/v1/chat/completions",
            "model": "gpt-4o-mini",
            "elapsed_ms": 12.5,
            "error_kind": "",
            "error": "",
            "message": "AI Pixel model endpoint responded.",
        },
    )
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/model-status?check=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"]["configured"] is True
    assert payload["model"]["health"]["checked"] is True
    assert payload["model"]["health"]["ok"] is True
    assert payload["model"]["health"]["elapsed_ms"] == 12.5
    assert "secret-ai-key" not in json.dumps(payload, ensure_ascii=False)


def test_retrieval_query_plan_can_use_ai_pixel_enhancement(
    zotero_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("AI_PIXEL_API_KEY", "secret-ai-key")
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture, name="AI Query Plan")
    local_csv = tmp_path / "ai-query-plan.csv"
    local_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Robot Catalyst Dataset,2026,10.6060/AI-PLAN,Ada Lovelace,"
        "Robot catalyst screening evidence for AI query planning,robot catalyst,https://example.test/ai-plan,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(local_csv)]},
    )
    assert save_response.status_code == 200
    calls: list[dict[str, object]] = []

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, object], timeout: int) -> dict:
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "queries": [
                                    {
                                        "query": "robot catalyst kinetics",
                                        "reason": "supported by robot catalyst evidence",
                                        "intent": "method_alias",
                                        "sources": ["localfile"],
                                    },
                                    {"query": "unrelated astronomy", "reason": "not supported"},
                                    {"query": "https://secret.example.test", "reason": "invalid"},
                                ],
                                "notes": ["AI query refinement applied"],
                            }
                        )
                    }
                }
            ]
        }

    plan = web.retrieval_query_plan_for_library(
        library["library_id"],
        seed_query="robot catalyst",
        sample_size=1,
        limit=3,
        use_ai=True,
        ai_post_json=fake_post_json,
    )

    assert calls
    assert calls[0]["url"] == "https://ai-pixel.online/v1/chat/completions"
    assert calls[0]["headers"] == {"Authorization": "Bearer secret-ai-key"}
    model_payload = calls[0]["payload"]
    assert isinstance(model_payload, dict)
    messages = model_payload["messages"]
    task = json.loads(messages[1]["content"])
    assert task["expansion_hints"]
    assert {hint["intent"] for hint in task["expansion_hints"]} >= {"core_concept", "benchmark"}
    assert "Use real neighboring concepts" in " ".join(task["planning_rules"])
    assert plan["ai_enhancement"]["status"] == "applied"
    assert plan["ai_enhancement"]["suggested_query_count"] == 3
    assert plan["ai_enhancement"]["accepted_query_count"] == 1
    assert plan["queries"][0]["query"] == "robot catalyst kinetics"
    assert plan["queries"][0]["ai"] is True
    assert plan["queries"][0]["intent"] == "method_alias"
    assert "robot catalyst kinetics" in plan["query_text"]
    assert {item["reason"] for item in plan["ai_enhancement"]["rejected"]} == {
        "query terms not supported by seed or evidence",
        "invalid query text",
    }
    assert "secret-ai-key" not in json.dumps(plan, ensure_ascii=False)


def test_retrieval_query_plan_ignores_unrelated_source_samples(
    zotero_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture, name="Focused Query Plan")
    local_csv = tmp_path / "focused-query-plan.csv"
    local_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Graph Protein Interaction,2026,10.6060/UNRELATED,Ada Lovelace,"
        "Protein graph interaction dataset,protein graph,https://example.test/unrelated,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(local_csv)]},
    )
    assert save_response.status_code == 200

    plan = web.retrieval_query_plan_for_library(
        library["library_id"],
        seed_query="speculative decoding",
        sample_size=1,
        limit=5,
    )

    planned_queries = [item["query"].lower() for item in plan["queries"]]
    assert planned_queries[0] == "speculative decoding"
    assert all("graph protein" not in query for query in planned_queries)
    assert all("protein interaction" not in query for query in planned_queries)
    assert "speculative decoding draft model" in planned_queries
    assert "speculative sampling verification" in planned_queries
    assert "llm inference acceleration" in planned_queries
    assert "assisted generation draft verify" in planned_queries
    hint_terms = web.retrieval_query_plan_expansion_terms("speculative decoding")
    assert "推测解码" in hint_terms
    assert "medusa" in hint_terms
    assert "eagle" in hint_terms


def test_retrieval_query_plan_api_reports_unconfigured_ai_without_key(
    zotero_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("AI_PIXEL_API_KEY", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture, name="AI Query Plan API")
    local_csv = tmp_path / "ai-query-plan-api.csv"
    local_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "API Robot Dataset,2026,10.6060/AI-PLAN-API,Ada Lovelace,"
        "API robot evidence for query planning,api robot,https://example.test/ai-plan-api,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(local_csv)]},
        ).status_code
        == 200
    )

    response = client.get(
        f"/api/library/{library['library_id']}/retrieval/query-plan?seed_query=api+robot&sample_size=1&use_ai=1"
    )

    assert response.status_code == 200
    plan = response.get_json()["plan"]
    assert plan["query_count"] >= 1
    assert plan["ai_enhancement"]["requested"] is True
    assert plan["ai_enhancement"]["configured"] is False
    assert plan["ai_enhancement"]["status"] == "not_configured"
    assert "AI_PIXEL_API_KEY" in plan["ai_enhancement"]["message"]


def test_retrieval_query_plan_job_runs_inline_and_can_be_restored(
    zotero_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_QUERY_PLAN_INLINE", "1")
    library = create_read_only_source(zotero_fixture, name="Query Plan Job")
    calls: list[dict[str, object]] = []

    def fake_query_plan(library_id: str, **kwargs) -> dict[str, object]:
        calls.append({"library_id": library_id, **kwargs})
        return {
            "seed_query": kwargs["seed_query"],
            "query_count": 1,
            "query_text": "background robot",
            "message": "Background query plan ready.",
            "queries": [{"query": "background robot", "sources": ["crossref"], "reason": "job test"}],
        }

    monkeypatch.setattr(web, "retrieval_query_plan_for_library", fake_query_plan)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/query-plan/jobs",
        json={"seed_query": "robot", "sources": ["crossref"], "use_ai": True, "limit": 3},
    )

    assert response.status_code == 200
    job = response.get_json()["job"]
    assert job["status"] == "completed"
    assert job["plan"]["query_text"] == "background robot"
    assert calls[0]["seed_query"] == "robot"
    assert calls[0]["use_ai"] is True
    latest = client.get(f"/api/library/{library['library_id']}/retrieval/query-plan/jobs/latest").get_json()["job"]
    assert latest["job_id"] == job["job_id"]
    assert latest["status"] == "completed"


def test_http_json_field_map_suggestion_samples_configured_source() -> None:
    seen_urls: list[str] = []
    config = {
        "label": "Competition API",
        "url_template": "https://internal.test/search?q={query}&limit={limit}",
        "field_map": {"external_id": "record_id"},
    }

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "data": {
                "records": [
                    {
                        "record_id": "sample-http-1",
                        "kind": "dataset",
                        "metadata": {
                            "paperTitle": "HTTP Suggest Robot Dataset",
                            "publication_year": "2026",
                            "creators": "Ada Lovelace",
                            "summary": "Suggested HTTP abstract.",
                            "keywords": ["robotics", "dataset"],
                            "venue": "Internal Registry",
                        },
                        "identifiers": {"doi": "10.6060/HTTP-SUGGEST"},
                        "links": {
                            "object_url": "https://example.test/http-suggest",
                            "pdf": "https://example.test/http-suggest.pdf",
                        },
                    }
                ]
            }
        }

    suggestion = retrieval_providers.suggest_http_json_field_map(
        config,
        query="robot",
        sample_size=3,
        get_json=fake_json,
    )

    assert seen_urls == ["https://internal.test/search?q=robot&limit=3"]
    assert suggestion["sample_count"] == 1
    assert suggestion["config_draft"]["items_path"] == "data.records"
    assert suggestion["field_map"]["title"] == "metadata.paperTitle"
    assert suggestion["field_map"]["date"] == "metadata.publication_year"
    assert suggestion["field_map"]["doi"] == "identifiers.doi"
    assert suggestion["field_map"]["authors"] == "metadata.creators"
    assert suggestion["field_map"]["url"] == "links.object_url"
    assert suggestion["field_map"]["pdf_url"] == "links.pdf"
    assert suggestion["field_map"]["external_id"] == "record_id"
    assert suggestion["quality"]["status"] == "good"


def test_sqlite_field_map_suggestion_samples_configured_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "field-map.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE records (
              source_id TEXT, paper_title TEXT, publication_year TEXT, doi TEXT, authors TEXT,
              summary TEXT, keywords TEXT, object_url TEXT, venue_name TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records VALUES (
              'sqlite-suggest-1', 'SQLite Suggest Robot Dataset', '2026', '10.6060/SQLITE-SUGGEST',
              'Ada Lovelace', 'Suggested SQLite abstract.', 'robotics; dataset',
              'https://example.test/sqlite-suggest', 'SQLite Registry'
            )
            """
        )
        conn.commit()
    config = {
        "label": "Suggest SQLite",
        "path": str(db_path),
        "query": (
            "SELECT source_id, paper_title, publication_year, doi, authors, summary, keywords, object_url, venue_name "
            "FROM records WHERE paper_title LIKE :like_query OR summary LIKE :like_query LIMIT :limit"
        ),
        "field_map": {"external_id": "source_id"},
    }

    suggestion = retrieval_providers.suggest_sqlite_field_map(config, query="robot", sample_size=2)

    assert suggestion["sample_count"] == 1
    assert "paper_title" in suggestion["columns"]
    assert suggestion["field_map"]["title"] == "paper_title"
    assert suggestion["field_map"]["date"] == "publication_year"
    assert suggestion["field_map"]["doi"] == "doi"
    assert suggestion["field_map"]["authors"] == "authors"
    assert suggestion["field_map"]["abstract"] == "summary"
    assert suggestion["field_map"]["tags"] == "keywords"
    assert suggestion["field_map"]["url"] == "object_url"
    assert suggestion["field_map"]["venue"] == "venue_name"
    assert suggestion["config_draft"]["field_map"]["external_id"] == "source_id"


def test_manifest_field_map_suggestion_samples_configured_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "field-map-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "data": {
                    "records": [
                        {
                            "id": "manifest-suggest-1",
                            "item_type": "dataset",
                            "name": "Manifest Suggest Robot Dataset",
                            "publicationYear": "2026",
                            "doi": "10.6060/MANIFEST-SUGGEST",
                            "authors": "Ada Lovelace",
                            "description": "Suggested manifest abstract.",
                            "keywords": "robotics; dataset",
                            "object_url": "https://example.test/manifest-suggest",
                            "pdf_url": "https://example.test/manifest-suggest.pdf",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    config = {
        "label": "Suggest Manifest",
        "manifest_path": str(manifest_path),
        "field_map": {"external_id": "id"},
    }

    suggestion = retrieval_providers.suggest_manifest_field_map(config, sample_size=2)

    assert suggestion["sample_count"] == 1
    assert suggestion["config_draft"]["items_path"] == "data.records"
    assert suggestion["field_map"]["title"] == "name"
    assert suggestion["field_map"]["date"] == "publicationYear"
    assert suggestion["field_map"]["doi"] == "doi"
    assert suggestion["field_map"]["authors"] == "authors"
    assert suggestion["field_map"]["abstract"] == "description"
    assert suggestion["field_map"]["tags"] == "keywords"
    assert suggestion["field_map"]["url"] == "object_url"
    assert suggestion["field_map"]["pdf_url"] == "pdf_url"


def test_sqlite_provider_maps_configured_rows_to_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "retrieval.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE items (
              id TEXT, title TEXT, year TEXT, doi TEXT, authors TEXT,
              abstract TEXT, keywords TEXT, url TEXT, venue TEXT, item_type TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO items VALUES (
              'sqlite-1', 'SQLite Robot Dataset', '2026', '10.6060/SQLITE',
              'Ada Lovelace; Grace Hopper', 'SQLite dataset abstract.',
              'robotics; dataset', 'https://example.test/sqlite', 'Internal DB', 'dataset'
            )
            """
        )
        conn.commit()
    config = {
        "label": "Competition SQLite",
        "path": str(db_path),
        "query": (
            "SELECT id, title, year, doi, authors, abstract, keywords, url, venue, item_type "
            "FROM items WHERE title LIKE :like_query OR abstract LIKE :like_query LIMIT :limit"
        ),
    }

    candidates = SQLiteProvider(config=config).search("robot", limit=3)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "sqlite"
    assert candidate.external_id == "10.6060/sqlite"
    assert candidate.item.source == "Competition SQLite"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "SQLite Robot Dataset"
    assert candidate.item.fields["date"] == "2026"
    assert candidate.item.fields["DOI"] == "10.6060/sqlite"
    assert candidate.item.fields["publicationTitle"] == "Internal DB"
    assert candidate.item.identifiers["doi"] == "10.6060/sqlite"
    assert [creator.last_name for creator in candidate.item.creators] == ["Lovelace", "Hopper"]
    assert candidate.item.tags == ["robotics", "dataset"]
    assert "SQLite Source: Competition SQLite" in candidate.item.fields["extra"]
    assert candidate.landing_url == "https://example.test/sqlite"


def test_sqlite_config_templates_are_valid_configs() -> None:
    templates = retrieval_providers.sqlite_config_templates()

    assert {template["id"] for template in templates} == {"basic-like"}
    config = retrieval_providers.sqlite_config(templates[0]["config"])
    assert config["path"].endswith("retrieval.sqlite")
    assert "LIKE :like_query" in config["query"]
    assert "title" in config["field_map"]


def test_manifest_provider_maps_local_json_manifest_to_candidates(tmp_path: Path) -> None:
    manifest_path = tmp_path / "object-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "objects": [
                    {
                        "id": "obj-1",
                        "title": "Object Manifest Robot Dataset",
                        "year": "2026",
                        "doi": "10.6060/MANIFEST",
                        "authors": "Ada Lovelace; Grace Hopper",
                        "abstract": "Object storage manifest abstract.",
                        "keywords": "robotics; dataset",
                        "object_url": "https://objects.example.test/obj-1",
                        "pdf_url": "https://objects.example.test/obj-1.pdf",
                        "venue": "Object Registry",
                        "item_type": "dataset",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = {
        "label": "Competition Objects",
        "manifest_path": str(manifest_path),
        "items_path": "objects",
        "field_map": {
            "title": "title",
            "date": "year",
            "doi": "doi",
            "authors": "authors",
            "abstract": "abstract",
            "tags": "keywords",
            "url": "object_url",
            "pdf_url": "pdf_url",
            "venue": "venue",
            "item_type": "item_type",
            "external_id": "id",
        },
    }

    candidates = ManifestProvider(config=config).search("robot dataset", limit=3)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "manifest"
    assert candidate.external_id == "10.6060/manifest"
    assert candidate.item.source == "Competition Objects"
    assert candidate.item.item_type == "dataset"
    assert candidate.item.fields["title"] == "Object Manifest Robot Dataset"
    assert candidate.item.fields["date"] == "2026"
    assert candidate.item.fields["DOI"] == "10.6060/manifest"
    assert candidate.item.fields["publicationTitle"] == "Object Registry"
    assert candidate.item.identifiers["doi"] == "10.6060/manifest"
    assert candidate.item.tags == ["robotics", "dataset"]
    assert candidate.landing_url == "https://objects.example.test/obj-1"
    assert candidate.pdf_url == "https://objects.example.test/obj-1.pdf"
    assert "Object Manifest Source: Competition Objects" in candidate.item.fields["extra"]


def test_manifest_config_templates_are_valid_configs() -> None:
    templates = retrieval_providers.manifest_config_templates()

    assert {template["id"] for template in templates} == {"local-json", "remote-json"}
    for template in templates:
        config = retrieval_providers.manifest_config(template["config"])
        assert config["manifest_path"] or config["manifest_url"]
        assert isinstance(config["field_map"], dict)
        assert "title" in config["field_map"]


def test_openlibrary_provider_maps_book_results_to_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "docs": [
                {
                    "key": "/works/OL45883W",
                    "title": "Artificial Intelligence: A Modern Approach",
                    "author_name": ["Stuart Russell", "Peter Norvig"],
                    "first_publish_year": 1995,
                    "isbn": ["0136042597", "9780136042594"],
                    "publisher": ["Prentice Hall", "Pearson"],
                    "subject": ["Artificial intelligence", "Computer science"],
                    "language": ["eng"],
                    "edition_key": ["OL2623672M"],
                    "cover_edition_key": "OL2623672M",
                    "ebook_access": "borrowable",
                }
            ]
        }

    candidates = OpenLibraryProvider(get_json=fake_json).search("artificial intelligence", limit=3)

    assert "q=artificial+intelligence" in seen_urls[0]
    assert "limit=3" in seen_urls[0]
    assert "fields=key%2Ctitle%2Cauthor_name" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "openlibrary"
    assert candidate.external_id == "9780136042594"
    assert candidate.item.item_type == "book"
    assert candidate.item.fields["title"] == "Artificial Intelligence: A Modern Approach"
    assert candidate.item.fields["date"] == "1995"
    assert candidate.item.fields["ISBN"] == "9780136042594"
    assert candidate.item.fields["publisher"] == "Prentice Hall; Pearson"
    assert candidate.item.fields["url"] == "https://openlibrary.org/works/OL45883W"
    assert candidate.item.identifiers["isbn"] == "9780136042594"
    assert candidate.item.creators[0].last_name == "Russell"
    assert candidate.item.creators[1].last_name == "Norvig"
    assert candidate.item.tags == ["Artificial intelligence", "Computer science"]
    assert "OpenLibrary Key: /works/OL45883W" in candidate.item.fields["extra"]
    assert "ISBN" in candidate.evidence


def test_ads_provider_maps_search_results_to_candidates() -> None:
    seen_urls: list[str] = []

    def fake_json(url: str) -> dict:
        seen_urls.append(url)
        return {
            "response": {
                "docs": [
                    {
                        "bibcode": "2024ApJ...962...42A",
                        "title": ["ADS Retrieval Demo"],
                        "author": ["Lovelace, Ada", "Hopper, Grace"],
                        "year": "2024",
                        "pubdate": "2024-02-01",
                        "pub": "The Astrophysical Journal",
                        "doi": ["10.3847/1538-4357/demo"],
                        "identifier": ["2024ApJ...962...42A", "10.3847/1538-4357/demo"],
                        "abstract": "A telescope retrieval abstract.",
                        "keyword": ["methods: data analysis", "astronomical databases"],
                        "volume": "962",
                        "issue": "1",
                        "page": ["42", "51"],
                        "doctype": "article",
                    }
                ]
            }
        }

    candidates = ADSProvider(get_json=fake_json).search("telescope retrieval", limit=4)

    assert "q=telescope+retrieval" in seen_urls[0]
    assert "rows=4" in seen_urls[0]
    assert "fl=bibcode%2Ctitle%2Cauthor" in seen_urls[0]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "ads"
    assert candidate.external_id == "2024ApJ...962...42A"
    assert candidate.item.item_type == "journalArticle"
    assert candidate.item.fields["title"] == "ADS Retrieval Demo"
    assert candidate.item.fields["date"] == "2024-02-01"
    assert candidate.item.fields["publicationTitle"] == "The Astrophysical Journal"
    assert candidate.item.fields["DOI"] == "10.3847/1538-4357/demo"
    assert candidate.item.fields["pages"] == "42-51"
    assert candidate.item.fields["abstractNote"] == "A telescope retrieval abstract."
    assert candidate.item.identifiers["ads_bibcode"] == "2024ApJ...962...42A"
    assert candidate.item.identifiers["doi"] == "10.3847/1538-4357/demo"
    assert candidate.item.creators[0].last_name == "Lovelace"
    assert candidate.item.tags == ["methods: data analysis", "astronomical databases"]
    assert "ADS Bibcode" in candidate.evidence


def test_retrieval_source_statuses_report_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("ADS_API_TOKEN", raising=False)
    monkeypatch.delenv("ADS_DEV_KEY", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    by_name = {source["name"]: source for source in retrieval_source_statuses()}

    assert by_name["crossref"]["available"] is True
    assert by_name["openalex"]["available"] is False
    assert by_name["openalex"]["requires_config"] is True
    assert by_name["openalex"]["config_key"] == "OPENALEX_API_KEY"
    assert by_name["openalex"]["setup"]["config_mode"] == "required_env"
    assert by_name["openalex"]["setup"]["config_env"] == "OPENALEX_API_KEY"
    assert by_name["openalex"]["setup"]["rate_limit_env"] == "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_OPENALEX_SECONDS"
    assert by_name["semanticscholar"]["available"] is True
    assert by_name["semanticscholar"]["requires_config"] is False
    assert by_name["semanticscholar"]["optional_config"] is True
    assert by_name["semanticscholar"]["config_key"] == "SEMANTIC_SCHOLAR_API_KEY"
    assert by_name["semanticscholar"]["setup"]["config_mode"] == "optional_env"
    assert by_name["datacite"]["available"] is True
    assert by_name["datacite"]["requires_config"] is False
    assert by_name["datacite"]["config_key"] == ""
    assert by_name["datacite"]["setup"]["config_mode"] == "none"
    assert by_name["datacite"]["rate_limit_seconds"] == 0.25
    assert "DataCite" in by_name["datacite"]["rate_limit_note"]
    assert by_name["biorxiv"]["available"] is True
    assert by_name["biorxiv"]["requires_config"] is False
    assert by_name["biorxiv"]["rate_limit_seconds"] == 1.0
    assert "bioRxiv" in by_name["biorxiv"]["rate_limit_note"]
    assert by_name["medrxiv"]["available"] is True
    assert by_name["medrxiv"]["requires_config"] is False
    assert by_name["medrxiv"]["rate_limit_seconds"] == 1.0
    assert "medRxiv" in by_name["medrxiv"]["rate_limit_note"]
    assert by_name["openlibrary"]["available"] is True
    assert by_name["openlibrary"]["requires_config"] is False
    assert by_name["openlibrary"]["rate_limit_seconds"] == 0.5
    assert "OpenLibrary" in by_name["openlibrary"]["rate_limit_note"]
    assert by_name["ads"]["available"] is False
    assert by_name["ads"]["requires_config"] is True
    assert by_name["ads"]["config_key"] == "ADS_API_TOKEN"
    assert by_name["ads"]["setup"]["config_mode"] == "required_any_env"
    assert by_name["ads"]["setup"]["alternate_config_env"] == "ADS_DEV_KEY"
    assert by_name["ads"]["rate_limit_seconds"] == 1.0
    assert "NASA ADS" in by_name["ads"]["rate_limit_note"]
    assert by_name["localfile"]["available"] is False
    assert by_name["localfile"]["requires_config"] is True
    assert by_name["localfile"]["config_key"] == "WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS"
    assert by_name["localfile"]["setup"]["config_mode"] == "preference_or_env"
    assert by_name["localfile"]["setup"]["preference_api"] == "/retrieval/local-files"
    assert by_name["localfile"]["rate_limit_seconds"] == 0.0
    assert "CSV / JSONL" in by_name["localfile"]["rate_limit_note"]
    assert by_name["httpjson"]["available"] is False
    assert by_name["httpjson"]["requires_config"] is True
    assert by_name["httpjson"]["config_key"] == "WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG"
    assert by_name["httpjson"]["setup"]["config_mode"] == "preference_or_env"
    assert by_name["httpjson"]["setup"]["preference_api"] == "/retrieval/http-json"
    assert by_name["httpjson"]["rate_limit_seconds"] == 0.5
    assert "HTTP JSON" in by_name["httpjson"]["rate_limit_note"]
    assert by_name["sqlite"]["available"] is False
    assert by_name["sqlite"]["requires_config"] is True
    assert by_name["sqlite"]["config_key"] == "WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG"
    assert by_name["sqlite"]["setup"]["config_mode"] == "preference_or_env"
    assert by_name["sqlite"]["setup"]["preference_api"] == "/retrieval/sqlite"
    assert by_name["sqlite"]["rate_limit_seconds"] == 0.0
    assert "SQLite" in by_name["sqlite"]["rate_limit_note"]
    assert by_name["manifest"]["available"] is False
    assert by_name["manifest"]["requires_config"] is True
    assert by_name["manifest"]["config_key"] == "WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG"
    assert by_name["manifest"]["setup"]["config_mode"] == "preference_or_env"
    assert by_name["manifest"]["setup"]["preference_api"] == "/retrieval/manifest"
    assert by_name["manifest"]["setup"]["global_rate_limit_env"] == "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_SECONDS"
    assert by_name["manifest"]["rate_limit_seconds"] == 0.5
    assert "Object Manifest" in by_name["manifest"]["rate_limit_note"]

    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "s2-key")
    monkeypatch.setenv("ADS_DEV_KEY", "ads-token")
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", str(Path.cwd()))
    monkeypatch.setenv(
        "WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG",
        json.dumps({"url_template": "https://internal.test/search?q={query}", "items_path": "results"}),
    )
    monkeypatch.setenv(
        "WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG",
        json.dumps({"path": __file__, "query": "SELECT 1 AS title"}),
    )
    monkeypatch.setenv(
        "WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG",
        json.dumps({"manifest_path": __file__, "items_path": "items"}),
    )
    by_name = {source["name"]: source for source in retrieval_source_statuses()}
    assert by_name["openalex"]["available"] is True
    assert by_name["semanticscholar"]["available"] is True
    assert by_name["ads"]["available"] is True
    assert by_name["localfile"]["available"] is True
    assert by_name["httpjson"]["available"] is True
    assert by_name["sqlite"]["available"] is True
    assert by_name["manifest"]["available"] is True


def test_retrieval_source_statuses_allow_rate_limit_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_CROSSREF_SECONDS", "1.25")
    by_name = {source["name"]: source for source in retrieval_source_statuses()}
    assert by_name["crossref"]["rate_limit_seconds"] == 1.25

    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_CROSSREF_SECONDS", raising=False)
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_SECONDS", "0.75")
    by_name = {source["name"]: source for source in retrieval_source_statuses()}
    assert by_name["crossref"]["rate_limit_seconds"] == 0.75
    assert by_name["datacite"]["rate_limit_seconds"] == 0.75


def test_retrieval_source_statuses_can_run_health_checks() -> None:
    class HealthyProvider:
        name = "healthy"

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            return []

    class RateLimitedProvider:
        name = "limited"

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            raise urllib.error.HTTPError("https://example.test", 429, "Too Many Requests", {}, None)

    statuses = retrieval_source_statuses(
        registry={"healthy": HealthyProvider(), "limited": RateLimitedProvider()},
        include_health=True,
    )
    by_name = {source["name"]: source for source in statuses}

    assert by_name["healthy"]["health"]["ok"] is True
    assert by_name["healthy"]["health"]["elapsed_ms"] >= 0
    assert by_name["limited"]["health"]["ok"] is False
    assert by_name["limited"]["health"]["error_kind"] == "rate_limited"
    assert "API Key" in by_name["limited"]["health"]["action"]


def test_public_code_and_dataset_sources_are_available_without_tokens() -> None:
    by_name = {source["name"]: source for source in retrieval_source_statuses()}

    for name in ["github", "huggingface", "zenodo"]:
        assert by_name[name]["available"] is True
        assert by_name[name]["optional_config"] is True
        assert by_name[name]["requires_config"] is False


def test_search_retrieval_merges_duplicate_strong_identifiers_and_keeps_partial_failures() -> None:
    crossref_candidate = RetrievedCandidate(
        source="crossref",
        external_id="10.1234/demo",
        item=ImportedItem(
            item_type="journalArticle",
            fields={"title": "Demo Paper", "DOI": "10.1234/demo"},
            identifiers={"doi": "10.1234/demo"},
            source="Crossref",
        ),
        confidence=0.9,
        evidence=["DOI"],
    )
    openalex_candidate = RetrievedCandidate(
        source="openalex",
        external_id="W123",
        item=ImportedItem(
            item_type="journalArticle",
            fields={"title": "Demo Paper", "DOI": "https://doi.org/10.1234/DEMO", "abstractNote": "Merged abstract"},
            identifiers={"doi": "10.1234/demo"},
            source="OpenAlex",
        ),
        confidence=0.8,
        evidence=["OpenAlex work"],
    )

    class StaticProvider:
        def __init__(self, name: str, candidates: list[RetrievedCandidate]) -> None:
            self.name = name
            self.candidates = candidates

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            return self.candidates

    class FailingProvider:
        name = "bad"

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            raise RuntimeError("source down")

    result = search_retrieval(
        "demo",
        sources=["crossref", "openalex", "bad"],
        registry={
            "crossref": StaticProvider("crossref", [crossref_candidate]),
            "openalex": StaticProvider("openalex", [openalex_candidate]),
            "bad": FailingProvider(),
        },
    )

    assert result["source_stats"]["bad"]["ok"] is False
    assert result["source_stats"]["bad"]["error_kind"] == "provider_error"
    assert result["source_stats"]["bad"]["action"] == "该源本次检索失败，其他源结果仍可继续导入。"
    assert result["source_stats"]["crossref"]["count"] == 1
    assert result["source_stats"]["crossref"]["elapsed_ms"] >= 0
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source"] == "crossref"
    assert candidate["also_seen_in"] == ["openalex"]
    assert candidate["abstract"] == "Merged abstract"
    assert candidate["rank"] == 1
    assert candidate["confidence_label"] == "高可信"
    assert "强标识符：DOI" in candidate["rank_reasons"]
    assert "多源命中：crossref / openalex" in candidate["rank_reasons"]


def test_search_retrieval_uses_source_specific_limits() -> None:
    calls: list[tuple[str, int]] = []

    class LimitProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            calls.append((self.name, limit))
            return []

    result = search_retrieval(
        "robot",
        sources=["paper", "code"],
        limit=7,
        source_limits={"paper": 9, "code": 2},
        registry={"paper": LimitProvider("paper"), "code": LimitProvider("code")},
    )

    assert sorted(calls) == [("code", 2), ("paper", 9)]
    assert result["source_stats"]["paper"]["count"] == 0
    assert result["source_stats"]["code"]["count"] == 0


def test_search_retrieval_applies_options_and_authority_signals() -> None:
    class OptionsProvider:
        name = "mixed"

        def search(self, query: str, limit: int = 10, options=None) -> list[RetrievedCandidate]:
            assert options.start_year == 2020
            assert options.material_types == ["paper"]
            return [
                RetrievedCandidate(
                    source="mixed",
                    external_id="old-paper",
                    item=ImportedItem(
                        item_type="journalArticle",
                        fields={"title": "Old Paper", "date": "2018"},
                        identifiers={"doi": "10.1000/old"},
                    ),
                    confidence=0.8,
                ),
                RetrievedCandidate(
                    source="mixed",
                    external_id="code",
                    item=ImportedItem(
                        item_type="computerProgram",
                        fields={"title": "Robot Code", "date": "2025"},
                    ),
                    raw={"stars": 500},
                    confidence=0.7,
                ),
                RetrievedCandidate(
                    source="mixed",
                    external_id="paper",
                    item=ImportedItem(
                        item_type="journalArticle",
                        fields={"title": "Robot Paper", "date": "2024", "publicationTitle": "Nature Machine Intelligence"},
                        identifiers={"doi": "10.1000/new"},
                    ),
                    raw={"citation_count": 80},
                    confidence=0.9,
                ),
            ]

    result = search_retrieval(
        "robot",
        sources=["mixed"],
        registry={"mixed": OptionsProvider()},
        options={"start_year": 2020, "material_types": ["paper"], "sort_mode": "authority", "strategy_mode": "quality"},
    )

    assert [candidate["title"] for candidate in result["candidates"]] == ["Robot Paper"]
    candidate = result["candidates"][0]
    assert candidate["authority_signals"]["citation_count"] == 80
    assert candidate["authority_signals"]["venue_authority"] == "high"
    assert candidate["quality_score"] >= 75
    assert "authority" in candidate["coverage_tags"]
    assert result["source_stats"]["mixed"]["filtering"]["removed_by_year"] == 1
    assert result["source_stats"]["mixed"]["filtering"]["removed_by_material_type"] == 1


def test_search_retrieval_caches_same_query_and_returns_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    retrieval_providers.reset_retrieval_search_cache()
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_SEARCH_CACHE_SECONDS", "60")
    calls: list[tuple[str, int]] = []

    class CacheProvider:
        name = "cache"

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            calls.append((query, limit))
            return [
                RetrievedCandidate(
                    source="cache",
                    external_id="cache-1",
                    item=ImportedItem(
                        item_type="journalArticle",
                        fields={"title": "Cached Retrieval Result", "date": "2026"},
                        creators=[ImportedCreator(first_name="Ada", last_name="Lovelace")],
                        identifiers={"doi": "10.4242/cache"},
                    ),
                    confidence=0.8,
                )
            ]

    registry = {"cache": CacheProvider()}
    first = search_retrieval("cache query", sources=["cache"], limit=3, registry=registry)
    first["candidates"][0]["title"] = "Mutated by caller"
    second = search_retrieval("cache query", sources=["cache"], limit=3, registry=registry)

    assert calls == [("cache query", 3)]
    assert second["cached"] is True
    assert second["source_stats"]["cache"]["cached"] is True
    assert second["candidates"][0]["title"] == "Cached Retrieval Result"
    retrieval_providers.reset_retrieval_search_cache()


def test_code_and_data_providers_use_shorter_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_json(url: str, timeout: int = 15, headers: dict[str, str] | None = None, **kwargs: object) -> dict:
        calls.append({"url": url, "timeout": timeout, "headers": headers or {}})
        if "api.github.com" in url:
            return {"items": []}
        if "huggingface.co" in url:
            return []
        if "zenodo.org" in url:
            return {"hits": {"hits": []}}
        return {}

    monkeypatch.setattr(retrieval_providers, "_http_get_json", fake_get_json)

    GitHubProvider().search("speculative decoding", limit=1)
    HuggingFaceProvider().search("speculative decoding", limit=1)
    ZenodoProvider().search("speculative decoding", limit=1)

    assert [call["timeout"] for call in calls] == [8, 8, 8, 8]


def test_search_retrieval_dedupes_exact_title_year_candidates_without_identifiers() -> None:
    local_candidate = RetrievedCandidate(
        source="localfile",
        external_id="row:1",
        item=ImportedItem(
            item_type="dataset",
            fields={"title": "AI4S Catalyst Benchmark Dataset", "date": "2026", "abstractNote": "Local abstract."},
            creators=[ImportedCreator(first_name="Ada", last_name="Lovelace")],
            source="Local CSV",
        ),
        confidence=0.72,
        evidence=["Local CSV row"],
    )
    manifest_candidate = RetrievedCandidate(
        source="manifest",
        external_id="object:1",
        item=ImportedItem(
            item_type="dataset",
            fields={"title": "AI4S Catalyst Benchmark Dataset", "date": "2026", "url": "https://example.test/dataset"},
            creators=[ImportedCreator(first_name="Ada", last_name="Lovelace")],
            source="Object Manifest",
        ),
        confidence=0.68,
        evidence=["Object manifest record"],
    )

    class StaticProvider:
        def __init__(self, name: str, candidates: list[RetrievedCandidate]) -> None:
            self.name = name
            self.candidates = candidates

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            return self.candidates

    result = search_retrieval(
        "AI4S Catalyst",
        sources=["localfile", "manifest"],
        registry={
            "localfile": StaticProvider("localfile", [local_candidate]),
            "manifest": StaticProvider("manifest", [manifest_candidate]),
        },
    )

    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["sources"] == ["localfile", "manifest"]
    assert candidate["also_seen_in"] == ["manifest"]
    assert candidate["source_count"] == 2
    assert candidate["multi_source"] is True
    assert candidate["landing_url"] == "https://example.test/dataset"


def test_search_retrieval_keeps_same_title_year_with_different_authors_separate() -> None:
    first = RetrievedCandidate(
        source="localfile",
        external_id="row:1",
        item=ImportedItem(
            item_type="report",
            fields={"title": "AI4S Shared Benchmark Report", "date": "2026"},
            creators=[ImportedCreator(first_name="Ada", last_name="Lovelace")],
            source="Local CSV",
        ),
        confidence=0.72,
    )
    second = RetrievedCandidate(
        source="manifest",
        external_id="object:1",
        item=ImportedItem(
            item_type="report",
            fields={"title": "AI4S Shared Benchmark Report", "date": "2026"},
            creators=[ImportedCreator(first_name="Grace", last_name="Hopper")],
            source="Object Manifest",
        ),
        confidence=0.68,
    )

    class StaticProvider:
        def __init__(self, candidates: list[RetrievedCandidate]) -> None:
            self.candidates = candidates

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            return self.candidates

    result = search_retrieval(
        "AI4S report",
        sources=["localfile", "manifest"],
        registry={
            "localfile": StaticProvider([first]),
            "manifest": StaticProvider([second]),
        },
    )

    assert len(result["candidates"]) == 2
    assert all(candidate["multi_source"] is False for candidate in result["candidates"])


def test_search_retrieval_classifies_rate_limits_and_timeouts() -> None:
    class RateLimitedProvider:
        name = "limited"

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            raise urllib.error.HTTPError("https://example.test", 429, "Too Many Requests", {}, None)

    class TimeoutProvider:
        name = "slow"

        def search(self, query: str, limit: int = 10) -> list[RetrievedCandidate]:
            raise TimeoutError("timed out")

    result = search_retrieval(
        "demo",
        sources=["limited", "slow"],
        registry={"limited": RateLimitedProvider(), "slow": TimeoutProvider()},
    )

    assert result["source_stats"]["limited"]["error_kind"] == "rate_limited"
    assert "稍后重试" in result["source_stats"]["limited"]["action"]
    assert result["source_stats"]["slow"]["error_kind"] == "timeout"
    assert "其他源" in result["source_stats"]["slow"]["action"]


def test_retrieval_search_api_uses_shared_service(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)

    def fake_search(query: str, **kwargs):
        return {
            "query": query,
            "sources": kwargs["sources"],
            "candidates": [{"source": "crossref", "title": "API Candidate"}],
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": ""}},
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot", "sources": ["crossref"], "limit": 5},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["query"] == "robot"
    assert payload["run_id"].startswith("run-")
    assert payload["candidates"][0]["candidate_id"].startswith("cand-")
    assert payload["candidates"][0]["title"] == "API Candidate"


def test_retrieval_search_job_runs_inline_and_can_be_restored(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_SEARCH_INLINE", "1")
    library = create_read_only_source(zotero_fixture)

    def fake_search(query: str, **kwargs):
        return {
            "query": query,
            "sources": kwargs["sources"],
            "candidates": [{"source": "crossref", "title": "Background Search Candidate"}],
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": ""}},
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search/jobs",
        json={"query": "robot", "sources": ["crossref"], "limit": 5, "use_ai_evaluation": False},
    )

    assert response.status_code == 200
    job = response.get_json()["job"]
    assert job["status"] == "completed"
    assert job["candidate_count"] == 1
    assert job["result"]["run_id"].startswith("run-")
    assert job["result"]["candidates"][0]["title"] == "Background Search Candidate"
    latest = client.get(f"/api/library/{library['library_id']}/retrieval/search/jobs/latest").get_json()["job"]
    assert latest["job_id"] == job["job_id"]
    assert latest["status"] == "completed"


def test_guided_search_job_runs_inline_and_restores_candidates(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_GUIDED_INLINE", "1")
    library = create_read_only_source(zotero_fixture)
    captured_options: list[dict[str, object]] = []

    def fake_plan(library_id: str, **kwargs):
        return {
            "queries": [
                {"query": "robot science paper", "query_text": "robot science paper", "intent": "paper", "sources": ["crossref"]},
                {"query": "robot benchmark dataset", "query_text": "robot benchmark dataset", "intent": "data", "sources": ["crossref"]},
            ],
            "message": "fake plan",
        }

    def fake_search(query: str, **kwargs):
        options = kwargs.get("options")
        captured_options.append(options.as_dict() if hasattr(options, "as_dict") else dict(options or {}))
        item_type = "dataset" if "dataset" in query else "journalArticle"
        return {
            "query": query,
            "sources": kwargs["sources"],
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": query,
                    "item_type": item_type,
                    "title": f"Candidate for {query}",
                    "year": "2024",
                    "identifiers": {"doi": f"10.1000/{len(captured_options)}"},
                    "item": {"item_type": item_type, "fields": {"title": f"Candidate for {query}", "date": "2024"}, "creators": [], "identifiers": {}},
                    "confidence": 0.9,
                    "quality_score": 88,
                    "coverage_tags": ["data" if item_type == "dataset" else "paper", "authority"],
                    "authority_signals": {"citation_count": 50},
                    "missing_authority_signals": [],
                    "ai_evaluation": {"score_source": "deterministic_rules", "decision": "review", "auto_select": False},
                }
            ],
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": ""}},
        }

    monkeypatch.setattr(web, "retrieval_query_plan_for_library", fake_plan)
    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/guided-search-jobs",
        json={
            "topic": "robot",
            "mode": "quality",
            "time_range": {"preset": "10y"},
            "material_types": ["paper", "data"],
            "sources": ["crossref"],
        },
    )

    assert response.status_code == 200
    job = response.get_json()["job"]
    assert job["status"] == "completed"
    assert job["progress"]["completed_queries"] == 2
    assert job["candidate_count"] == 2
    assert captured_options[0]["start_year"] == 2017
    assert captured_options[0]["material_types"] == ["paper", "data"]

    latest = client.get(f"/api/library/{library['library_id']}/retrieval/guided-search-jobs/latest").get_json()["job"]
    assert latest["job_id"] == job["job_id"]
    candidates_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/guided-search-jobs/{job['job_id']}/candidates"
    )
    candidates_payload = candidates_response.get_json()
    assert candidates_payload["ok"] is True
    assert len(candidates_payload["candidates"]) == 2
    assert candidates_payload["coverage"]["material_counts"]["paper"] == 1
    assert candidates_payload["coverage"]["material_counts"]["data"] == 1


def test_ai_candidate_evaluation_sends_metadata_only_and_rejects_unknown_ids(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    app_store.set_preference(
        library["library_id"],
        web.API_CONFIG_PREFERENCE_KEY,
        {"model": {"model": "gpt-5.5", "base_url": "https://ai-pixel.online", "api_key": "secret"}, "code_sources": {}},
    )
    captured: dict[str, object] = {}
    candidates = [
        {
            "source": "crossref",
            "title": "Speculative Decoding for Scientific Models",
            "year": "2026",
            "abstract": "Speculative decoding speeds up model inference.",
            "identifiers": {"doi": "10.1000/spec"},
            "item_type": "journalArticle",
            "landing_url": "https://doi.org/10.1000/spec",
            "raw": {"secret": "do-not-send"},
            "item": {
                "item_type": "journalArticle",
                "fields": {"title": "Speculative Decoding for Scientific Models", "DOI": "10.1000/spec"},
                "creators": [{"first_name": "Ada", "last_name": "Lovelace"}],
                "identifiers": {"doi": "10.1000/spec"},
            },
        },
        {
            "source": "github",
            "title": "demo/speculative-decoding",
            "abstract": "Code repository.",
            "identifiers": {},
            "item_type": "computerProgram",
            "landing_url": "https://github.com/demo/speculative-decoding",
            "item": {"item_type": "computerProgram", "fields": {"title": "demo/speculative-decoding"}},
        },
    ]

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, object], timeout: int) -> dict:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout"] = timeout
        system_content = payload["messages"][0]["content"]  # type: ignore[index]
        user_content = payload["messages"][1]["content"]  # type: ignore[index]
        assert "final_confidence_score" in system_content
        assert "topic_relevance_score" in system_content
        assert "reason 必须使用简洁中文" in system_content
        assert "do-not-send" not in user_content
        assert "raw" not in user_content
        assert "Speculative Decoding" in user_content
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "evaluations": [
                                    {
                                        "candidate_id": "candidate-1",
                                        "decision": "recommend",
                                        "topic_relevance_score": 95,
                                        "metadata_quality_score": 90,
                                        "source_evidence_score": 92,
                                        "import_risk_score": 12,
                                        "final_confidence_score": 93,
                                        "risk_level": "low",
                                        "reason": "Highly relevant and complete metadata.",
                                        "missing_fields": [],
                                    },
                                    {
                                        "candidate_id": "unknown",
                                        "decision": "recommend",
                                        "topic_relevance_score": 100,
                                        "metadata_quality_score": 100,
                                        "source_evidence_score": 100,
                                        "import_risk_score": 5,
                                        "final_confidence_score": 99,
                                        "risk_level": "low",
                                        "reason": "Invalid id.",
                                        "missing_fields": [],
                                    },
                                ]
                            }
                        )
                    }
                }
            ]
        }

    summary = web.evaluate_retrieval_candidates_with_ai(
        library["library_id"],
        "speculative decoding",
        candidates,
        ai_post_json=fake_post_json,
    )

    assert captured["url"] == "https://ai-pixel.online/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["payload"]["model"] == "gpt-5.5"
    assert captured["payload"]["max_tokens"] == 1800
    assert captured["timeout"] == 90
    assert summary["status"] == "evaluated"
    assert summary["accepted_evaluation_count"] == 1
    assert summary["rejected_evaluation_count"] == 1
    assert summary["auto_selected_count"] == 1
    assert candidates[0]["ai_evaluation"]["decision"] == "recommend"
    assert candidates[0]["ai_evaluation"]["auto_select"] is True
    assert candidates[1]["ai_evaluation"]["status"] == "fallback"
    assert candidates[1]["ai_evaluation"]["auto_select"] is False


def test_ai_candidate_evaluation_batches_large_candidate_sets(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    app_store.set_preference(
        library["library_id"],
        web.API_CONFIG_PREFERENCE_KEY,
        {"model": {"model": "gpt-5.5", "base_url": "https://ai-pixel.online", "api_key": "secret"}, "code_sources": {}},
    )
    candidates = [
        {
            "source": "crossref",
            "title": f"Speculative Decoding Candidate {index}",
            "abstract": "Speculative decoding speeds up model inference.",
            "identifiers": {"doi": f"10.1000/spec-{index}"},
            "item_type": "journalArticle",
            "landing_url": f"https://doi.org/10.1000/spec-{index}",
            "item": {
                "item_type": "journalArticle",
                "fields": {"title": f"Speculative Decoding Candidate {index}", "DOI": f"10.1000/spec-{index}"},
                "creators": [{"first_name": "Ada", "last_name": "Lovelace"}],
                "identifiers": {"doi": f"10.1000/spec-{index}"},
            },
        }
        for index in range(45)
    ]
    batch_sizes: list[int] = []

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, object], timeout: int) -> dict:
        task = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        metadata = task["candidates"]
        batch_sizes.append(len(metadata))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "evaluations": [
                                    {
                                        "candidate_id": item["candidate_id"],
                                        "decision": "recommend",
                                        "topic_relevance_score": 90,
                                        "metadata_quality_score": 85,
                                        "source_evidence_score": 88,
                                        "import_risk_score": 16,
                                        "final_confidence_score": 89,
                                        "risk_level": "low",
                                        "reason": "Relevant metadata.",
                                        "missing_fields": [],
                                    }
                                    for item in metadata
                                ]
                            }
                        )
                    }
                }
            ]
        }

    summary = web.evaluate_retrieval_candidates_with_ai(
        library["library_id"],
        "speculative decoding",
        candidates,
        ai_post_json=fake_post_json,
    )

    assert batch_sizes == [5, 5, 5, 5, 5, 5, 5, 5, 5]
    assert summary["evaluation_batch_count"] == 9
    assert summary["accepted_evaluation_count"] == 45
    assert summary["auto_selected_count"] == 45
    assert all(candidate["ai_evaluation"]["decision"] == "recommend" for candidate in candidates)


def test_ai_candidate_evaluation_keeps_successful_batches_when_later_batch_times_out(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    app_store.set_preference(
        library["library_id"],
        web.API_CONFIG_PREFERENCE_KEY,
        {"model": {"model": "gpt-5.5", "base_url": "https://ai-pixel.online", "api_key": "secret"}, "code_sources": {}},
    )
    candidates = [
        {
            "source": "crossref",
            "title": f"Speculative Decoding Candidate {index}",
            "abstract": "Speculative decoding speeds up model inference.",
            "identifiers": {"doi": f"10.1000/spec-{index}"},
            "item": {"fields": {"title": f"Speculative Decoding Candidate {index}", "DOI": f"10.1000/spec-{index}"}},
        }
        for index in range(6)
    ]
    call_count = 0

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, object], timeout: int) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise TimeoutError("The read operation timed out")
        task = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        metadata = task["candidates"]
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "evaluations": [
                                    {
                                        "candidate_id": item["candidate_id"],
                                        "decision": "recommend",
                                        "topic_relevance_score": 90,
                                        "metadata_quality_score": 85,
                                        "source_evidence_score": 88,
                                        "import_risk_score": 16,
                                        "final_confidence_score": 89,
                                        "risk_level": "low",
                                        "reason": "Relevant metadata.",
                                        "missing_fields": [],
                                    }
                                    for item in metadata
                                ]
                            }
                        )
                    }
                }
            ]
        }

    summary = web.evaluate_retrieval_candidates_with_ai(
        library["library_id"],
        "speculative decoding",
        candidates,
        ai_post_json=fake_post_json,
    )

    assert summary["status"] == "partial"
    assert summary["score_source"] == "mixed_ai_rules"
    assert summary["accepted_evaluation_count"] == 5
    assert summary["failed_batch_count"] == 1
    assert "timed out" in summary["error"]
    assert candidates[0]["ai_evaluation"]["score_source"] == "ai_model"
    assert candidates[-1]["ai_evaluation"]["status"] == "fallback"


def test_retrieval_search_api_adds_ai_evaluation_and_strict_auto_select(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    app_store.set_preference(
        library["library_id"],
        web.API_CONFIG_PREFERENCE_KEY,
        {"model": {"model": "gpt-5.5", "base_url": "https://ai-pixel.online", "api_key": "secret"}, "code_sources": {}},
    )

    def fake_search(query: str, **kwargs):
        return {
            "query": query,
            "sources": kwargs["sources"],
            "source_stats": {"crossref": {"ok": True, "count": 2, "error": ""}},
            "candidates": [
                {
                    "source": "crossref",
                    "title": "Good Candidate",
                    "abstract": "Robot speculative decoding.",
                    "identifiers": {"doi": "10.1000/good"},
                    "landing_url": "https://doi.org/10.1000/good",
                    "item_type": "journalArticle",
                    "item": {"item_type": "journalArticle", "fields": {"title": "Good Candidate", "DOI": "10.1000/good"}, "identifiers": {"doi": "10.1000/good"}},
                },
                {
                    "source": "crossref",
                    "title": "Needs Review",
                    "abstract": "Possibly related.",
                    "identifiers": {},
                    "landing_url": "https://example.test/review",
                    "item_type": "journalArticle",
                    "item": {"item_type": "journalArticle", "fields": {"title": "Needs Review"}},
                },
            ],
        }

    def fake_ai(messages, post_json=None, max_tokens=900, timeout_seconds=None):
        return {
            "evaluations": [
                {
                    "candidate_id": "candidate-1",
                    "decision": "recommend",
                    "topic_relevance_score": 92,
                    "metadata_quality_score": 88,
                    "source_evidence_score": 86,
                    "import_risk_score": 14,
                    "final_confidence_score": 90,
                    "risk_level": "low",
                    "reason": "Strong metadata.",
                    "missing_fields": [],
                },
                {
                    "candidate_id": "candidate-2",
                    "decision": "review",
                    "topic_relevance_score": 70,
                    "metadata_quality_score": 60,
                    "source_evidence_score": 54,
                    "import_risk_score": 45,
                    "final_confidence_score": 66,
                    "risk_level": "medium",
                    "reason": "Needs checking.",
                    "missing_fields": ["authors"],
                },
            ]
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    monkeypatch.setattr(web, "ai_pixel_chat_json", fake_ai)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot", "sources": ["crossref"], "limit": 5},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ai_evaluation_summary"]["status"] == "evaluated"
    assert payload["ai_evaluation_summary"]["auto_selected_count"] == 1
    evaluations = [candidate["ai_evaluation"] for candidate in payload["candidates"]]
    assert evaluations[0]["decision"] == "recommend"
    assert evaluations[0]["auto_select"] is True
    assert evaluations[1]["decision"] == "review"
    assert evaluations[1]["auto_select"] is False


def test_retrieval_batch_api_runs_queries_and_tracks_progress(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_BATCH_INLINE", "1")
    library = create_read_only_source(zotero_fixture)
    calls: list[tuple[str, list[str], int, dict[str, int]]] = []
    ai_evaluation_flags: list[bool] = []

    def fake_search(query: str, **kwargs):
        sources = list(kwargs["sources"])
        limit = int(kwargs["limit"])
        calls.append((query, sources, limit, dict(kwargs.get("source_limits") or {})))
        slug = query.lower().replace(" ", "-")
        return {
            "query": query,
            "sources": sources,
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": "", "elapsed_ms": 3}},
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": f"10.7000/{slug}",
                    "title": f"Batch {query}",
                    "identifiers": {"doi": f"10.7000/{slug}"},
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": f"Batch {query}", "DOI": f"10.7000/{slug}"},
                        "identifiers": {"doi": f"10.7000/{slug}"},
                        "source": "Crossref",
                    },
                }
            ],
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)

    def fake_evaluate(
        library_id: str,
        query: str,
        candidates: list[dict[str, object]],
        *,
        use_ai_evaluation: bool = True,
        ai_post_json: object = None,
    ) -> dict[str, object]:
        ai_evaluation_flags.append(use_ai_evaluation)
        for candidate in candidates:
            candidate["ai_evaluation"] = {"decision": "review", "auto_select": False}
        return {"requested": use_ai_evaluation, "status": "skipped", "candidate_count": len(candidates)}

    monkeypatch.setattr(web, "evaluate_retrieval_candidates_with_ai", fake_evaluate)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/batches",
        json={
            "queries": ["robot batch", "robot batch", "AI4S batch"],
            "sources": ["crossref"],
            "limit": 2,
            "source_limits": {"crossref": 1, "unknown": 9},
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    job = payload["job"]
    assert job["status"] == "completed"
    assert job["total_queries"] == 2
    assert job["completed_queries"] == 2
    assert job["failed_queries"] == 0
    assert job["total_candidates"] == 2
    assert job["progress"] == 1
    assert len(job["run_ids"]) == 2
    assert job["context"]["source_limits"] == {"crossref": 1}
    assert [item["status"] for item in job["items"]] == ["completed", "completed"]
    assert all(item["run_id"].startswith("run-") for item in job["items"])
    assert calls == [
        ("robot batch", ["crossref"], 2, {"crossref": 1}),
        ("AI4S batch", ["crossref"], 2, {"crossref": 1}),
    ]
    assert ai_evaluation_flags == [False, False]

    list_response = client.get(f"/api/library/{library['library_id']}/retrieval/batches")
    assert list_response.status_code == 200
    assert list_response.get_json()["jobs"][0]["job_id"] == job["job_id"]

    detail_response = client.get(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()["job"]
    assert [item["query"] for item in detail["items"]] == ["robot batch", "AI4S batch"]
    assert app_store.recent_retrieval_runs(library["library_id"], limit=5)[0]["query"] in {"robot batch", "AI4S batch"}

    candidates_response = client.get(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/candidates")
    assert candidates_response.status_code == 200
    candidates_payload = candidates_response.get_json()
    assert candidates_payload["ai_evaluation_summary"]["status"] == "skipped"
    assert len(candidates_payload["candidates"]) == 2
    assert candidates_payload["candidates"][0]["candidate_id"] == ""
    assert candidates_payload["candidates"][0]["stored_candidate_id"].startswith("cand-")
    assert candidates_payload["candidates"][0]["batch_job_id"] == job["job_id"]
    assert candidates_payload["candidates"][0]["batch_query"] in {"robot batch", "AI4S batch"}
    assert candidates_payload["candidates"][0]["ai_evaluation"]["decision"] == "review"
    assert ai_evaluation_flags == [False, False, True]

    markdown_response = client.get(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/report")
    assert markdown_response.status_code == 200
    assert f"{job['job_id']}-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "Retrieval batch report" in markdown_text
    assert "## Source summary" in markdown_text
    assert "| crossref | yes | 2 | 2 | 0 | 2 | 6ms | - |" in markdown_text
    assert "robot batch" in markdown_text
    assert "crossref:1" in markdown_text

    csv_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/report?format=csv"
    )
    assert csv_response.status_code == 200
    csv_text = csv_response.get_data(as_text=True)
    assert "query_number,query,status,run_id,candidate_count" in csv_text
    assert "AI4S batch" in csv_text

    source_csv_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/report?format=csv&scope=sources"
    )
    assert source_csv_response.status_code == 200
    assert f"{job['job_id']}-report-sources.csv" in source_csv_response.headers["Content-Disposition"]
    source_csv_text = source_csv_response.get_data(as_text=True)
    assert source_csv_text.startswith(
        "source,status,requested,query_count,success_count,failure_count,candidate_count,elapsed_ms"
    )
    assert "crossref,passed,true,2,2,0,2,6,," in source_csv_text

    json_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/report?format=json"
    )
    assert json_response.status_code == 200
    json_report = json.loads(json_response.get_data(as_text=True))
    assert json_report["summary"]["job_id"] == job["job_id"]
    assert json_report["summary"]["total_candidates"] == 2
    assert json_report["summary"]["source_error_count"] == 0
    assert json_report["source_evidence"][0]["source"] == "crossref"
    assert json_report["source_evidence"][0]["query_count"] == 2
    assert json_report["source_evidence"][0]["candidate_count"] == 2
    assert json_report["source_evidence"][0]["success_count"] == 2
    assert [row["query"] for row in json_report["rows"]] == ["robot batch", "AI4S batch"]


def test_retrieval_batch_api_can_cancel_queued_jobs(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    job = app_store.create_retrieval_batch_job(library["library_id"], ["robot one", "robot two"], ["crossref"], 2)
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/cancel")

    assert response.status_code == 200
    canceled = response.get_json()["job"]
    assert canceled["status"] == "canceled"
    assert canceled["completed_queries"] == 2
    assert canceled["failed_queries"] == 0
    assert canceled["progress"] == 1
    assert [item["status"] for item in canceled["items"]] == ["canceled", "canceled"]


def test_retrieval_batch_progress_estimates_remaining_time(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    job = app_store.create_retrieval_batch_job(library["library_id"], ["done query", "queued query"], ["crossref"], 2)
    items = app_store.retrieval_batch_items_for_job(library["library_id"], job["job_id"])
    app_store.complete_retrieval_batch_item(
        library["library_id"],
        items[0]["job_item_id"],
        status="completed",
        run_id="run-existing",
        candidate_count=1,
    )
    with app_store.connect() as conn:
        conn.execute(
            "UPDATE retrieval_batch_jobs SET started_at = ? WHERE library_id = ? AND job_id = ?",
            ("2026-01-01T00:00:00+00:00", library["library_id"], job["job_id"]),
        )
        conn.execute(
            "UPDATE retrieval_batch_items SET started_at = ?, finished_at = ? WHERE library_id = ? AND job_item_id = ?",
            (
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:10+00:00",
                library["library_id"],
                items[0]["job_item_id"],
            ),
        )
        conn.commit()

    app_store.refresh_retrieval_batch_job_progress(library["library_id"], job["job_id"])
    updated = app_store.retrieval_batch_job(library["library_id"], job["job_id"])

    assert updated["completed_queries"] == 1
    assert updated["remaining_queries"] == 1
    assert updated["active_queries"] == 1
    assert updated["average_seconds_per_completed_query"] == 10
    assert updated["eta_seconds"] == 10


def test_retrieval_batch_api_pauses_and_resumes_remaining_queries(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_BATCH_INLINE", "1")
    library = create_read_only_source(zotero_fixture)
    job = app_store.create_retrieval_batch_job(library["library_id"], ["pause one", "pause two"], ["crossref"], 2)
    calls: list[str] = []

    def fake_search(query: str, **kwargs):
        calls.append(query)
        slug = query.replace(" ", "-")
        return {
            "query": query,
            "sources": list(kwargs["sources"]),
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": "", "elapsed_ms": 4}},
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": f"10.7000/{slug}",
                    "title": f"Paused {query}",
                    "identifiers": {"doi": f"10.7000/{slug}"},
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": f"Paused {query}", "DOI": f"10.7000/{slug}"},
                        "identifiers": {"doi": f"10.7000/{slug}"},
                        "source": "Crossref",
                    },
                }
            ],
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    pause_response = client.post(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/pause")

    assert pause_response.status_code == 200
    paused = pause_response.get_json()["job"]
    assert paused["status"] == "paused"
    assert paused["remaining_queries"] == 2
    assert paused["active_queries"] == 2
    assert calls == []

    resume_response = client.post(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/resume")

    assert resume_response.status_code == 200
    resumed = resume_response.get_json()["job"]
    assert resumed["status"] == "completed"
    assert resumed["completed_queries"] == 2
    assert resumed["remaining_queries"] == 0
    assert [item["status"] for item in resumed["items"]] == ["completed", "completed"]
    assert calls == ["pause one", "pause two"]


def test_retrieval_batch_api_retries_failed_items_only(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_BATCH_INLINE", "1")
    library = create_read_only_source(zotero_fixture)
    job = app_store.create_retrieval_batch_job(library["library_id"], ["done query", "retry query"], ["crossref"], 2)
    items = app_store.retrieval_batch_items_for_job(library["library_id"], job["job_id"])
    app_store.complete_retrieval_batch_item(
        library["library_id"],
        items[0]["job_item_id"],
        status="completed",
        run_id="run-existing",
        candidate_count=1,
        source_stats={"crossref": {"ok": True, "count": 1}},
    )
    app_store.complete_retrieval_batch_item(library["library_id"], items[1]["job_item_id"], status="failed", error="temporary upstream failure")
    app_store.mark_retrieval_batch_job_finished(library["library_id"], job["job_id"], "completed")
    calls: list[str] = []

    def fake_search(query: str, **kwargs):
        calls.append(query)
        return {
            "query": query,
            "sources": list(kwargs["sources"]),
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": "", "elapsed_ms": 5}},
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": "10.7000/retry",
                    "title": "Retried Candidate",
                    "identifiers": {"doi": "10.7000/retry"},
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": "Retried Candidate", "DOI": "10.7000/retry"},
                        "identifiers": {"doi": "10.7000/retry"},
                        "source": "Crossref",
                    },
                }
            ],
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/retrieval/batches/{job['job_id']}/retry-failed")

    assert response.status_code == 200
    retried = response.get_json()["job"]
    assert retried["status"] == "completed"
    assert retried["completed_queries"] == 2
    assert retried["failed_queries"] == 0
    assert retried["progress"] == 1
    assert [item["status"] for item in retried["items"]] == ["completed", "completed"]
    assert retried["items"][0]["run_id"] == "run-existing"
    assert retried["items"][1]["run_id"].startswith("run-")
    assert calls == ["retry query"]


def test_retrieval_sources_api_reports_provider_statuses(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/sources")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    by_name = {source["name"]: source for source in payload["sources"]}
    assert by_name["crossref"]["available"] is True
    assert by_name["openalex"]["available"] is False
    assert by_name["openalex"]["message"] == "需要配置 OPENALEX_API_KEY"
    assert by_name["openalex"]["setup"]["config_mode"] == "required_env"
    assert by_name["openalex"]["setup"]["config_env"] == "OPENALEX_API_KEY"
    assert by_name["openalex"]["setup"]["rate_limit_env"] == "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_OPENALEX_SECONDS"
    assert by_name["crossref"]["timeout_seconds"] == 15
    assert by_name["crossref"]["setup"]["config_mode"] == "none"
    assert "公共接口" in by_name["crossref"]["rate_limit_note"]


def test_retrieval_sources_report_api_exports_setup_guidance(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    markdown_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources/report")
    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-source-setup-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "# 多源检索源配置报告" in markdown_text
    assert "OPENALEX_API_KEY" in markdown_text
    assert "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_OPENALEX_SECONDS" in markdown_text
    assert "/retrieval/http-json" in markdown_text

    csv_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources/report?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["Content-Type"].startswith("text/csv")
    csv_text = csv_response.get_data(as_text=True)
    assert "name,label,available,configured,config_mode,config_env" in csv_text
    assert "openalex,OpenAlex,false,false,required_env,OPENALEX_API_KEY" in csv_text

    json_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources/report?format=json")
    assert json_response.status_code == 200
    assert json_response.headers["Content-Type"].startswith("application/json")
    json_payload = json_response.get_json()
    by_name = {source["name"]: source for source in json_payload["sources"]}
    assert json_payload["source_count"] >= 10
    assert by_name["openalex"]["setup"]["config_mode"] == "required_env"
    assert by_name["manifest"]["setup"]["preference_api"] == "/retrieval/manifest"


def test_retrieval_readiness_api_preflights_configured_internal_sources(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    local_csv = tmp_path / "competition.csv"
    local_csv.write_text(
        "\n".join(
            [
                "id,title,year,doi,authors,abstract,keywords,item_type,url",
                "local-1,Local Robot Dataset,2026,10.6060/LOCAL-READY,Ada Lovelace,Local abstract,robotics; dataset,dataset,https://example.test/local-ready",
            ]
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "competition.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE items (
              id TEXT, title TEXT, year TEXT, doi TEXT, authors TEXT,
              abstract TEXT, keywords TEXT, url TEXT, venue TEXT, item_type TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO items VALUES (
              'db-ready-1', 'SQLite Ready Robot Dataset', '2026', '10.6060/SQLITE-READY',
              'Ada Lovelace', 'SQLite ready abstract.',
              'robotics; dataset', 'https://example.test/sqlite-ready', 'SQLite Registry', 'dataset'
            )
            """
        )
        conn.commit()
    manifest_path = tmp_path / "object-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "objects": [
                    {
                        "id": "manifest-ready-1",
                        "title": "Manifest Ready Robot Dataset",
                        "year": "2026",
                        "doi": "10.6060/MANIFEST-READY",
                        "authors": "Ada Lovelace",
                        "abstract": "Manifest ready abstract.",
                        "keywords": "robotics; dataset",
                        "object_url": "https://example.test/manifest-ready",
                        "item_type": "dataset",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(local_csv)]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/sqlite",
            json={
                "config": {
                    "label": "Ready SQLite",
                    "path": str(db_path),
                    "query": (
                        "SELECT id, title, year, doi, authors, abstract, keywords, url, venue, item_type "
                        "FROM items WHERE title LIKE :like_query OR abstract LIKE :like_query LIMIT :limit"
                    ),
                }
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/manifest",
            json={
                "config": {
                    "label": "Ready Manifest",
                    "manifest_path": str(manifest_path),
                    "items_path": "objects",
                    "field_map": {
                        "title": "title",
                        "date": "year",
                        "doi": "doi",
                        "authors": "authors",
                        "abstract": "abstract",
                        "tags": "keywords",
                        "url": "object_url",
                        "item_type": "item_type",
                        "external_id": "id",
                    },
                }
            },
        ).status_code
        == 200
    )

    response = client.get(f"/api/library/{library['library_id']}/retrieval/readiness?query=robot&sample_size=1")

    assert response.status_code == 200
    payload = response.get_json()
    readiness = payload["readiness"]
    assert payload["ok"] is True
    assert readiness["status"] == "ready"
    assert readiness["summary"]["configured_internal_count"] == 3
    assert readiness["summary"]["previewed_internal_count"] == 3
    assert readiness["summary"]["sample_count"] == 3
    assert readiness["summary"]["error_count"] == 0
    by_name = {entry["name"]: entry for entry in readiness["previews"]}
    assert by_name["localfile"]["source"] == "preference"
    assert by_name["localfile"]["quality"]["status"] == "good"
    local_suggestion = by_name["localfile"]["field_map_suggestion"]
    assert local_suggestion["draft_available"] is True
    assert local_suggestion["field_map"]["title"] == "title"
    assert local_suggestion["field_map"]["doi"] == "doi"
    assert local_suggestion["config_draft"]["field_map"]["title"] == "title"
    assert local_suggestion["files"][0]["file"] == "competition.csv"
    assert by_name["sqlite"]["quality"]["status"] == "good"
    assert by_name["sqlite"]["preview"]["samples"][0]["item"]["fields"]["title"] == "SQLite Ready Robot Dataset"
    sqlite_suggestion = by_name["sqlite"]["field_map_suggestion"]
    assert sqlite_suggestion["draft_available"] is True
    assert sqlite_suggestion["field_map"]["title"] == "title"
    assert sqlite_suggestion["field_map"]["doi"] == "doi"
    assert sqlite_suggestion["config_draft"]["field_map"]["title"] == "title"
    assert by_name["manifest"]["quality"]["status"] == "good"
    manifest_suggestion = by_name["manifest"]["field_map_suggestion"]
    assert manifest_suggestion["draft_available"] is True
    assert manifest_suggestion["field_map"]["url"] == "object_url"
    assert by_name["httpjson"]["status"] == "skipped"

    markdown_response = client.get(f"/api/library/{library['library_id']}/retrieval/readiness/report?query=robot&sample_size=1")
    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-readiness-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "# 多源检索上线前预检报告" in markdown_text
    assert "预检状态：ready" in markdown_text
    assert "| Ready SQLite | preference | 是 | 是 | good | 1 |" in markdown_text
    assert "| Ready Manifest | preference | 是 | 是 | good | 1 |" in markdown_text

    csv_response = client.get(f"/api/library/{library['library_id']}/retrieval/readiness/report?query=robot&sample_size=1&format=csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["Content-Type"].startswith("text/csv")
    csv_text = csv_response.get_data(as_text=True)
    assert "name,label,source,configured,available,previewed,status" in csv_text
    assert "field_map_status,field_map_fields,field_map_draft_available" in csv_text
    assert "sqlite,Ready SQLite,preference,true,true,true,good,1" in csv_text

    json_response = client.get(f"/api/library/{library['library_id']}/retrieval/readiness/report?query=robot&sample_size=1&format=json")
    assert json_response.status_code == 200
    assert json_response.headers["Content-Type"].startswith("application/json")
    report_payload = json_response.get_json()
    assert report_payload["status"] == "ready"
    assert report_payload["summary"]["configured_internal_count"] == 3


def test_retrieval_readiness_redacts_environment_field_map_draft(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    library = create_read_only_source(zotero_fixture)
    db_path = tmp_path / "environment-readiness.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE records (
              id TEXT, paper_title TEXT, publication_year TEXT, doi TEXT, authors TEXT, object_url TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records VALUES (
              'env-ready-1', 'Environment Ready Robot Dataset', '2026', '10.6060/ENV-READY',
              'Ada Lovelace', 'https://example.test/env-ready'
            )
            """
        )
        conn.commit()
    monkeypatch.setenv(
        "WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG",
        json.dumps(
            {
                "label": "Environment SQLite",
                "path": str(db_path),
                "query": (
                    "SELECT id, paper_title, publication_year, doi, authors, object_url "
                    "FROM records WHERE paper_title LIKE :like_query LIMIT :limit"
                ),
            }
        ),
    )
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/readiness?query=robot&sample_size=1")

    assert response.status_code == 200
    payload = response.get_json()
    by_name = {entry["name"]: entry for entry in payload["readiness"]["previews"]}
    suggestion = by_name["sqlite"]["field_map_suggestion"]
    assert by_name["sqlite"]["source"] == "environment"
    assert suggestion["field_map"]["title"] == "paper_title"
    assert suggestion["field_map"]["date"] == "publication_year"
    assert suggestion["field_map"]["doi"] == "doi"
    assert suggestion["draft_available"] is False
    assert suggestion["config_draft"] == {}


def test_retrieval_local_file_preference_enables_localfile_source(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture)
    local_csv = tmp_path / "local-retrieval.csv"
    local_csv.write_text(
        "\n".join(
            [
                "title,authors,year,doi,abstract,keywords,item_type,url",
                "Configured Robot Dataset,Ada Lovelace,2026,10.6060/CONFIGURED,Configured local abstract.,robotics; dataset,dataset,https://example.test/configured",
            ]
        ),
        encoding="utf-8",
    )
    client = create_app().test_client()

    initial_response = client.get(f"/api/library/{library['library_id']}/retrieval/local-files")
    assert initial_response.status_code == 200
    initial_payload = initial_response.get_json()
    assert initial_payload["paths"] == []
    assert initial_payload["status"]["available"] is False

    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": str(local_csv)},
    )
    assert save_response.status_code == 200
    save_payload = save_response.get_json()
    assert save_payload["paths"] == [str(local_csv)]
    assert save_payload["status"]["available"] is True
    assert save_payload["status"]["file_count"] == 1

    sources_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources")
    by_name = {source["name"]: source for source in sources_response.get_json()["sources"]}
    assert by_name["localfile"]["available"] is True
    assert by_name["localfile"]["configured"] is True

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "configured robot", "sources": ["localfile"], "limit": 3},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["source_stats"]["localfile"]["ok"] is True
    assert search_payload["candidates"][0]["title"] == "Configured Robot Dataset"
    assert search_payload["candidates"][0]["identifiers"]["doi"] == "10.6060/configured"


def test_retrieval_local_file_preference_saves_field_map_for_preview_and_search(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture)
    local_csv = tmp_path / "custom-local.csv"
    local_csv.write_text(
        "\n".join(
            [
                "row_key,headline,published_on,identifier_value,creator_names,body_text,topic_terms,kind,landing",
                "mapped-1,Preference Mapped Robot Dataset,2026,10.6060/PREF-MAP,Ada Lovelace; Grace Hopper,Preference mapped abstract,robotics; local,dataset,https://example.test/pref-map",
            ]
        ),
        encoding="utf-8",
    )
    field_map = {
        "external_id": "row_key",
        "title": "headline",
        "date": "published_on",
        "doi": "identifier_value",
        "authors": "creator_names",
        "abstract": "body_text",
        "tags": "topic_terms",
        "item_type": "kind",
        "url": "landing",
    }
    client = create_app().test_client()

    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(local_csv)], "field_map_text": json.dumps(field_map)},
    )

    assert save_response.status_code == 200
    save_payload = save_response.get_json()
    assert save_payload["field_map"] == field_map
    assert save_payload["status"]["field_map_count"] == len(field_map)

    config_payload = client.get(f"/api/library/{library['library_id']}/retrieval/local-files").get_json()
    assert config_payload["field_map"] == field_map
    preview_response = client.get(f"/api/library/{library['library_id']}/retrieval/local-files/preview?sample_size=1")
    assert preview_response.status_code == 200
    preview_payload = preview_response.get_json()
    assert preview_payload["field_map"] == field_map
    preview_file = preview_payload["preview"]["files"][0]
    mappings = {mapping["column"]: mapping["target"] for mapping in preview_file["mappings"]}
    assert mappings["headline"] == "item.fields.title"
    assert mappings["identifier_value"] == "item.fields.DOI"
    assert mappings["creator_names"] == "item.creators"
    sample_item = preview_file["samples"][0]["item"]
    assert sample_item["fields"]["title"] == "Preference Mapped Robot Dataset"
    assert sample_item["fields"]["date"] == "2026"
    assert sample_item["identifiers"]["doi"] == "10.6060/pref-map"
    assert sample_item["creators"][0]["last_name"] == "Lovelace"

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "preference mapped robot", "sources": ["localfile"], "limit": 3},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["source_stats"]["localfile"]["ok"] is True
    assert search_payload["candidates"][0]["title"] == "Preference Mapped Robot Dataset"
    assert search_payload["candidates"][0]["identifiers"]["doi"] == "10.6060/pref-map"


def test_retrieval_source_configs_reject_unsupported_field_map_targets(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    local_csv = tmp_path / "invalid-field-map.csv"
    local_csv.write_text("title,doi\nInvalid Target Dataset,10.6060/INVALID\n", encoding="utf-8")
    client = create_app().test_client()

    requests = [
        (
            "/retrieval/local-files",
            {"paths": [str(local_csv)], "field_map": {"title": "title", "bad_target": "doi"}},
        ),
        (
            "/retrieval/http-json",
            {
                "config": {
                    "url_template": "https://example.test/search?q={query}",
                    "items_path": "results",
                    "field_map": {"title": "title", "bad_target": "doi"},
                }
            },
        ),
        (
            "/retrieval/sqlite",
            {
                "config": {
                    "path": str(tmp_path / "items.sqlite"),
                    "query": "SELECT title, doi FROM items WHERE title LIKE :query",
                    "field_map": {"title": "title", "bad_target": "doi"},
                }
            },
        ),
        (
            "/retrieval/manifest",
            {
                "config": {
                    "manifest_url": "https://example.test/manifest.json",
                    "items_path": "items",
                    "field_map": {"title": "title", "bad_target": "doi"},
                }
            },
        ),
    ]

    for endpoint, payload in requests:
        response = client.post(f"/api/library/{library['library_id']}{endpoint}", json=payload)
        assert response.status_code == 400
        body = response.get_json()
        assert body["ok"] is False
        assert "bad_target" in body["error"]
        assert "Supported targets" in body["error"]


def test_retrieval_http_json_preference_enables_httpjson_source(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("COMPETITION_API_KEY", "demo-env")
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    initial_response = client.get(f"/api/library/{library['library_id']}/retrieval/http-json")
    assert initial_response.status_code == 200
    initial_payload = initial_response.get_json()
    assert initial_payload["source"] == "environment"
    assert initial_payload["summary"]["configured"] is False

    config = {
        "label": "Competition API",
        "url_template": "https://internal.test/search?q={query}&limit={limit}",
        "items_path": "results",
        "next_url_path": "links.next",
        "max_pages": 2,
        "auth": {"type": "header_env", "env": "COMPETITION_API_KEY", "header": "X-API-Key"},
        "field_map": {
            "title": "title",
            "date": "year",
            "doi": "doi",
            "authors": "authors",
            "abstract": "abstract",
            "tags": "keywords",
            "external_id": "id",
            "item_type": "item_type",
        },
    }
    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/http-json",
        json={"config": json.dumps(config)},
    )
    assert save_response.status_code == 200
    save_payload = save_response.get_json()
    assert save_payload["source"] == "preference"
    assert save_payload["summary"]["configured"] is True
    assert save_payload["summary"]["max_pages"] == 2
    assert save_payload["summary"]["next_url_path"] == "links.next"
    assert save_payload["summary"]["auth_type"] == "header_env"
    assert save_payload["summary"]["auth_env"] == "COMPETITION_API_KEY"
    assert save_payload["summary"]["auth_header"] == "X-API-Key"
    assert "Competition API" in save_payload["config"]

    sources_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources")
    by_name = {source["name"]: source for source in sources_response.get_json()["sources"]}
    assert by_name["httpjson"]["available"] is True
    assert by_name["httpjson"]["configured"] is True

    seen: list[tuple[str, dict[str, str] | None]] = []

    def fake_get_json(url: str, *, headers=None, **kwargs) -> dict:
        seen.append((url, headers))
        return {
            "results": [
                {
                    "id": "api-1",
                    "item_type": "dataset",
                    "title": "Competition Robot Dataset",
                    "year": "2026",
                    "doi": "10.6060/COMPETITION",
                    "authors": "Ada Lovelace; Grace Hopper",
                    "abstract": "Competition API abstract.",
                    "keywords": "robotics; dataset",
                }
            ]
        }

    monkeypatch.setattr(retrieval_providers, "_http_get_json", fake_get_json)
    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "competition robot", "sources": ["httpjson"], "limit": 2},
    )

    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert seen == [("https://internal.test/search?q=competition+robot&limit=2", {"X-API-Key": "demo-env"})]
    assert search_payload["source_stats"]["httpjson"]["ok"] is True
    assert search_payload["candidates"][0]["title"] == "Competition Robot Dataset"
    assert search_payload["candidates"][0]["identifiers"]["doi"] == "10.6060/competition"
    assert search_payload["candidates"][0]["item"]["source"] == "Competition API"


def test_retrieval_http_json_preview_api_reports_mapped_samples(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()
    config = {
        "label": "Preview API",
        "url_template": "https://internal.test/search?q={query}&limit={limit}",
        "items_path": "results",
        "field_map": {
            "title": "title",
            "date": "year",
            "doi": "doi",
            "authors": "authors",
            "external_id": "id",
        },
    }
    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/http-json",
        json={"config": config},
    )
    assert save_response.status_code == 200

    seen_urls: list[str] = []

    def fake_get_json(url: str, *, headers=None, **kwargs) -> dict:
        seen_urls.append(url)
        return {
            "results": [
                {
                    "id": "api-preview-1",
                    "title": "API Preview Robot Dataset",
                    "year": "2026",
                    "doi": "10.6060/API-PREVIEW",
                    "authors": "Ada Lovelace",
                }
            ]
        }

    monkeypatch.setattr(retrieval_providers, "_http_get_json", fake_get_json)
    preview_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/http-json/preview?query=api%20preview&sample_size=2"
    )

    assert preview_response.status_code == 200
    payload = preview_response.get_json()
    assert payload["ok"] is True
    assert payload["source"] == "preference"
    assert seen_urls == ["https://internal.test/search?q=api+preview&limit=2"]
    preview = payload["preview"]
    assert preview["query"] == "api preview"
    assert preview["quality"]["status"] == "good"
    assert preview["samples"][0]["item"]["fields"]["title"] == "API Preview Robot Dataset"
    assert preview["samples"][0]["item"]["identifiers"]["doi"] == "10.6060/api-preview"


def test_retrieval_http_json_templates_api_returns_editable_templates(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/http-json/templates")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    by_id = {template["id"]: template for template in payload["templates"]}
    assert "basic-rest" in by_id
    assert "bearer-page" in by_id
    assert "api-key-cursor" in by_id
    assert by_id["bearer-page"]["config"]["auth"]["type"] == "bearer_env"
    assert by_id["api-key-cursor"]["config"]["next_url_path"] == "links.next"


def test_retrieval_field_map_suggestion_api_returns_targets_and_draft(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    targets_response = client.get(f"/api/library/{library['library_id']}/retrieval/field-map/targets")

    assert targets_response.status_code == 200
    targets_payload = targets_response.get_json()
    assert targets_payload["ok"] is True
    assert {"title", "doi", "authors", "pdf_url"} <= {target["target"] for target in targets_payload["targets"]}

    suggest_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/field-map/suggest",
        json={
            "source_type": "sqlite",
            "columns": ["paper_title", "publication_year", "doi", "authors", "object_url"],
            "config": {
                "label": "Draft SQLite",
                "path": "C:/data/retrieval.sqlite",
                "query": "SELECT paper_title, publication_year, doi, authors, object_url FROM items LIMIT :limit",
            },
        },
    )

    assert suggest_response.status_code == 200
    payload = suggest_response.get_json()
    assert payload["ok"] is True
    assert payload["source_type"] == "sqlite"
    assert payload["field_map"]["title"] == "paper_title"
    assert payload["field_map"]["date"] == "publication_year"
    assert payload["field_map"]["doi"] == "doi"
    assert payload["field_map"]["authors"] == "authors"
    assert payload["field_map"]["url"] == "object_url"
    assert payload["config_draft"]["field_map"]["title"] == "paper_title"
    assert payload["quality"]["coverage"]["identifier"] is True


def test_retrieval_field_map_report_exports_mapping_evidence(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()
    request_payload = {
        "source_type": "sqlite",
        "columns": ["paper_title", "publication_year", "doi", "authors", "object_url"],
        "config": {
            "label": "Draft SQLite",
            "path": "C:/data/retrieval.sqlite",
            "query": "SELECT paper_title, publication_year, doi, authors, object_url FROM items LIMIT :limit",
        },
    }

    markdown_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/field-map/report",
        json=request_payload,
    )

    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-field-map-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "Retrieval field map report" in markdown_text
    assert "paper_title" in markdown_text
    assert "publication_year" in markdown_text
    assert "Config Draft" in markdown_text

    csv_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/field-map/report?format=csv",
        json=request_payload,
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["Content-Type"].startswith("text/csv")
    csv_text = csv_response.get_data(as_text=True)
    assert csv_text.startswith("section,name,value,details")
    assert "mapping,title,paper_title" in csv_text
    assert "coverage,identifier,true" in csv_text

    json_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/field-map/report?format=json",
        json=request_payload,
    )
    assert json_response.status_code == 200
    assert json_response.headers["Content-Type"].startswith("application/json")
    json_report = json_response.get_json()
    assert json_report["schema"] == "web-library.retrieval-field-map-report/v1"
    assert json_report["source_type"] == "sqlite"
    assert json_report["field_map"]["title"] == "paper_title"
    assert json_report["config_draft"]["field_map"]["doi"] == "doi"


def test_configured_source_field_map_suggestion_apis_return_drafts(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    local_csv = tmp_path / "suggest-api-local.csv"
    local_csv.write_text(
        "\n".join(
            [
                "id,paper_title,publication_year,doi,authors,summary,object_url,resource_type",
                "local-suggest-1,API Local Suggest Robot Dataset,2026,10.6060/API-LOCAL-SUGGEST,Ada Lovelace,API local suggest abstract.,https://example.test/api-local-suggest,dataset",
            ]
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "suggest-api.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE records (
              id TEXT, paper_title TEXT, publication_year TEXT, doi TEXT, authors TEXT, summary TEXT, object_url TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records VALUES (
              'db-suggest-1', 'API SQLite Suggest Robot Dataset', '2026', '10.6060/API-SQLITE-SUGGEST',
              'Ada Lovelace', 'API SQLite suggest abstract.', 'https://example.test/api-sqlite-suggest'
            )
            """
        )
        conn.commit()
    manifest_path = tmp_path / "suggest-api-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "objects": [
                    {
                        "id": "manifest-suggest-api-1",
                        "name": "API Manifest Suggest Robot Dataset",
                        "publicationYear": "2026",
                        "doi": "10.6060/API-MANIFEST-SUGGEST",
                        "authors": "Ada Lovelace",
                        "object_url": "https://example.test/api-manifest-suggest",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(local_csv)]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/http-json",
            json={
                "config": {
                    "label": "Suggest API HTTP",
                    "url_template": "https://internal.test/search?q={query}&limit={limit}",
                }
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/sqlite",
            json={
                "config": {
                    "label": "Suggest API SQLite",
                    "path": str(db_path),
                    "query": (
                        "SELECT id, paper_title, publication_year, doi, authors, summary, object_url "
                        "FROM records WHERE paper_title LIKE :like_query OR summary LIKE :like_query LIMIT :limit"
                    ),
                }
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/manifest",
            json={
                "config": {
                    "label": "Suggest API Manifest",
                    "manifest_path": str(manifest_path),
                }
            },
        ).status_code
        == 200
    )

    def fake_get_json(url: str, *, headers=None, **kwargs) -> dict:
        return {
            "items": [
                {
                    "id": "http-suggest-api-1",
                    "paper_title": "API HTTP Suggest Robot Dataset",
                    "publication_year": "2026",
                    "doi": "10.6060/API-HTTP-SUGGEST",
                    "authors": "Ada Lovelace",
                    "object_url": "https://example.test/api-http-suggest",
                }
            ]
        }

    monkeypatch.setattr(retrieval_providers, "_http_get_json", fake_get_json)
    local_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/local-files/field-map/suggest?sample_size=2"
    )
    http_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/http-json/field-map/suggest?query=robot&sample_size=2"
    )
    sqlite_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/sqlite/field-map/suggest?query=robot&sample_size=2"
    )
    manifest_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/manifest/field-map/suggest?sample_size=2"
    )

    assert local_response.status_code == 200
    local_suggestion = local_response.get_json()["suggestion"]
    assert local_suggestion["draft_available"] is True
    assert local_suggestion["config_draft"]["field_map"]["title"] == "paper_title"
    assert local_suggestion["field_map"]["date"] == "publication_year"
    assert local_suggestion["field_map"]["doi"] == "doi"
    assert local_suggestion["files"][0]["file"] == "suggest-api-local.csv"

    assert http_response.status_code == 200
    http_suggestion = http_response.get_json()["suggestion"]
    assert http_suggestion["draft_available"] is True
    assert http_suggestion["config_draft"]["items_path"] == "items"
    assert http_suggestion["field_map"]["title"] == "paper_title"
    assert http_suggestion["field_map"]["doi"] == "doi"

    assert sqlite_response.status_code == 200
    sqlite_suggestion = sqlite_response.get_json()["suggestion"]
    assert sqlite_suggestion["draft_available"] is True
    assert sqlite_suggestion["field_map"]["title"] == "paper_title"
    assert sqlite_suggestion["field_map"]["date"] == "publication_year"
    assert "paper_title" in sqlite_suggestion["columns"]

    assert manifest_response.status_code == 200
    manifest_suggestion = manifest_response.get_json()["suggestion"]
    assert manifest_suggestion["draft_available"] is True
    assert manifest_suggestion["config_draft"]["items_path"] == "objects"
    assert manifest_suggestion["field_map"]["title"] == "name"
    assert manifest_suggestion["field_map"]["url"] == "object_url"

    local_report = client.get(
        f"/api/library/{library['library_id']}/retrieval/local-files/field-map/report?sample_size=2"
    )
    assert local_report.status_code == 200
    assert local_report.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-local-files-field-map-report.md" in local_report.headers["Content-Disposition"]
    local_report_text = local_report.get_data(as_text=True)
    assert "Retrieval field map report" in local_report_text
    assert "paper_title" in local_report_text

    http_report = client.get(
        f"/api/library/{library['library_id']}/retrieval/http-json/field-map/report?query=robot&sample_size=2&format=csv"
    )
    assert http_report.status_code == 200
    assert http_report.headers["Content-Type"].startswith("text/csv")
    assert "retrieval-http-json-field-map-report.csv" in http_report.headers["Content-Disposition"]
    http_report_text = http_report.get_data(as_text=True)
    assert http_report_text.startswith("section,name,value,details")
    assert "mapping,title,paper_title" in http_report_text

    sqlite_report = client.get(
        f"/api/library/{library['library_id']}/retrieval/sqlite/field-map/report?query=robot&sample_size=2&format=json"
    )
    assert sqlite_report.status_code == 200
    assert sqlite_report.headers["Content-Type"].startswith("application/json")
    sqlite_report_json = sqlite_report.get_json()
    assert sqlite_report_json["schema"] == "web-library.retrieval-field-map-report/v1"
    assert sqlite_report_json["source_config_source"] == "preference"
    assert sqlite_report_json["field_map"]["title"] == "paper_title"

    manifest_report = client.get(
        f"/api/library/{library['library_id']}/retrieval/manifest/field-map/report?sample_size=2&format=json"
    )
    assert manifest_report.status_code == 200
    assert manifest_report.headers["Content-Type"].startswith("application/json")
    manifest_report_json = manifest_report.get_json()
    assert manifest_report_json["field_map"]["title"] == "name"
    assert manifest_report_json["field_map"]["url"] == "object_url"

    redacted = web.field_map_suggestion_response_for_source(
        "environment",
        {"field_map": {"title": "title"}, "config_draft": {"headers": {"Authorization": "secret"}}},
    )
    assert redacted["field_map"] == {"title": "title"}
    assert redacted["config_draft"] == {}
    assert redacted["draft_available"] is False


def test_retrieval_batch_validation_summary_reports_validation_state(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    missing_library = create_local_copy(zotero_fixture, name="Batch Missing")

    missing = web.retrieval_batch_validation_summary(missing_library["library_id"])

    assert missing["status"] == "missing"
    assert missing["job_count"] == 0
    assert "No batch validation jobs" in missing["message"]
    assert missing["remediation"]["action"] == "run_validation_batch"
    assert missing["remediation"]["method"] == "POST"

    active_library = create_local_copy(zotero_fixture, name="Batch Active")
    active_job = app_store.create_retrieval_batch_job(
        active_library["library_id"],
        ["active validation"],
        ["localfile"],
        3,
    )

    active = web.retrieval_batch_validation_summary(active_library["library_id"])

    assert active["status"] == "active"
    assert active["active_job_count"] == 1
    assert active["latest_job_id"] == active_job["job_id"]
    assert active["remediation"]["action"] == "review_batch_progress"

    low_sample_library = create_local_copy(zotero_fixture, name="Batch Low Sample")
    low_sample_job = app_store.create_retrieval_batch_job(
        low_sample_library["library_id"],
        ["low sample validation"],
        ["localfile"],
        3,
    )
    low_sample_items = app_store.retrieval_batch_items_for_job(
        low_sample_library["library_id"], low_sample_job["job_id"]
    )
    app_store.complete_retrieval_batch_item(
        low_sample_library["library_id"],
        low_sample_items[0]["job_item_id"],
        status="completed",
        run_id="run-low-sample-validation",
        candidate_count=1,
        source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 6}},
    )
    app_store.mark_retrieval_batch_job_finished(
        low_sample_library["library_id"], low_sample_job["job_id"], "completed"
    )

    low_sample = web.retrieval_batch_validation_summary(
        low_sample_library["library_id"], required_sources=["localfile"]
    )

    assert low_sample["status"] == "low_sample"
    assert low_sample["completed_queries"] == 1
    assert low_sample["required_completed_queries"] == 3
    assert low_sample["completed_query_gap"] == 2
    assert "3-5 query" in low_sample["message"]
    assert low_sample["remediation"]["action"] == "run_validation_batch"

    passed_library = create_local_copy(zotero_fixture, name="Batch Passed")
    passed_job = app_store.create_retrieval_batch_job(
        passed_library["library_id"],
        ["passed validation one", "passed validation two", "passed validation three"],
        ["localfile"],
        3,
    )
    passed_items = app_store.retrieval_batch_items_for_job(passed_library["library_id"], passed_job["job_id"])
    for index, item in enumerate(passed_items, start=1):
        app_store.complete_retrieval_batch_item(
            passed_library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id=f"run-passed-validation-{index}",
            candidate_count=1,
            source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 6}},
        )
    app_store.mark_retrieval_batch_job_finished(passed_library["library_id"], passed_job["job_id"], "completed")

    passed = web.retrieval_batch_validation_summary(passed_library["library_id"], required_sources=["localfile"])

    assert passed["status"] == "passed"
    assert passed["completed_job_count"] == 1
    assert passed["completed_queries"] == 3
    assert passed["required_completed_queries"] == 3
    assert passed["completed_query_gap"] == 0
    assert passed["failed_queries"] == 0
    assert passed["total_candidates"] == 3
    assert passed["required_sources"] == ["localfile"]
    assert passed["validated_sources"] == ["localfile"]
    assert passed["missing_sources"] == []
    assert passed["source_evidence"][0]["success_count"] == 3
    assert passed["source_evidence"][0]["candidate_count"] == 3
    assert passed["remediation"]["action"] == "download_batch_report"
    assert passed["remediation"]["endpoint"] == f"/retrieval/batches/{passed_job['job_id']}/report"

    covered_query = web.retrieval_batch_validation_summary(
        passed_library["library_id"],
        required_sources=["localfile"],
        required_queries=["passed validation one"],
    )

    assert covered_query["status"] == "passed"
    assert covered_query["required_queries"] == ["passed validation one"]
    assert covered_query["covered_queries"] == ["passed validation one"]
    assert covered_query["missing_queries"] == []

    query_gap = web.retrieval_batch_validation_summary(
        passed_library["library_id"],
        required_sources=["localfile"],
        required_queries=["unseen intake query"],
    )

    assert query_gap["status"] == "query_gap"
    assert query_gap["covered_query_count"] == 0
    assert query_gap["missing_queries"] == ["unseen intake query"]
    assert "Use queries" in query_gap["message"]
    assert query_gap["remediation"]["action"] == "run_required_query_batch"
    assert query_gap["remediation"]["method"] == "POST"
    assert query_gap["remediation"]["queries"] == ["unseen intake query"]

    source_gap = web.retrieval_batch_validation_summary(
        passed_library["library_id"], required_sources=["localfile", "sqlite"]
    )

    assert source_gap["status"] == "source_gap"
    assert source_gap["required_sources"] == ["localfile", "sqlite"]
    assert source_gap["validated_sources"] == ["localfile"]
    assert source_gap["missing_sources"] == ["sqlite"]
    assert "sqlite" in source_gap["message"]
    assert source_gap["remediation"]["action"] == "run_missing_source_batch"
    assert source_gap["remediation"]["sources"] == ["sqlite"]

    source_error_library = create_local_copy(zotero_fixture, name="Batch Source Error")
    source_error_job = app_store.create_retrieval_batch_job(
        source_error_library["library_id"],
        ["source error validation"],
        ["localfile", "sqlite"],
        3,
    )
    source_error_items = app_store.retrieval_batch_items_for_job(
        source_error_library["library_id"], source_error_job["job_id"]
    )
    app_store.complete_retrieval_batch_item(
        source_error_library["library_id"],
        source_error_items[0]["job_item_id"],
        status="completed",
        run_id="run-source-error-validation",
        candidate_count=1,
        source_stats={
            "localfile": {"ok": True, "count": 1, "elapsed_ms": 3},
            "sqlite": {"ok": False, "count": 0, "elapsed_ms": 5, "error_kind": "timeout"},
        },
    )
    app_store.mark_retrieval_batch_job_finished(
        source_error_library["library_id"], source_error_job["job_id"], "completed"
    )

    source_errors = web.retrieval_batch_validation_summary(
        source_error_library["library_id"], required_sources=["localfile", "sqlite"]
    )

    assert source_errors["status"] == "source_errors"
    assert source_errors["validated_sources"] == ["localfile", "sqlite"]
    assert source_errors["missing_sources"] == []
    assert source_errors["source_errors"] == ["sqlite"]
    by_source = {item["source"]: item for item in source_errors["source_evidence"]}
    assert by_source["sqlite"]["failure_count"] == 1
    assert by_source["sqlite"]["latest_error_kind"] == "timeout"
    assert source_errors["remediation"]["action"] == "review_source_errors"
    assert source_errors["remediation"]["endpoint"].endswith("scope=sources")


def test_retrieval_batch_import_readiness_checks_cached_candidates(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture, name="Batch Import Readiness")
    run = app_store.create_retrieval_run(
        library["library_id"],
        "bad import candidate",
        ["localfile"],
        {"localfile": {"ok": True, "count": 1, "elapsed_ms": 4}},
        [
            {
                "source": "localfile",
                "external_id": "bad-import",
                "title": "Bad Import Candidate",
                "item": {"fields": {"title": "Bad Import Candidate"}},
            }
        ],
    )
    job = app_store.create_retrieval_batch_job(
        library["library_id"],
        ["bad import candidate", "second import candidate", "third import candidate"],
        ["localfile"],
        3,
    )
    items = app_store.retrieval_batch_items_for_job(library["library_id"], job["job_id"])
    app_store.complete_retrieval_batch_item(
        library["library_id"],
        items[0]["job_item_id"],
        status="completed",
        run_id=run["run_id"],
        candidate_count=1,
        source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 4}},
    )
    for item in items[1:]:
        app_store.complete_retrieval_batch_item(
            library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id="",
            candidate_count=0,
            source_stats={"localfile": {"ok": True, "count": 0, "elapsed_ms": 4}},
        )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], job["job_id"], "completed")

    batch_validation = web.retrieval_batch_validation_summary(library["library_id"], required_sources=["localfile"])
    readiness = web.retrieval_batch_import_readiness(library["library_id"], batch_validation)

    assert readiness["status"] == "blocked"
    assert readiness["checked_candidate_count"] == 1
    assert readiness["ready_candidate_count"] == 0
    assert readiness["error_candidate_count"] == 1
    assert "item_type" in readiness["errors"][0]


def test_retrieval_onboarding_report_combines_readiness_tuning_and_config_bundle(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture)
    local_csv = tmp_path / "onboarding.csv"
    local_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Onboarding Robot Dataset,2026,10.6060/ONBOARDING,Ada Lovelace,Onboarding abstract,robotics,https://example.test/onboarding,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(local_csv)]},
    )
    assert save_response.status_code == 200
    batch_job = app_store.create_retrieval_batch_job(
        library["library_id"],
        ["robot validation", "failing validation"],
        ["localfile"],
        3,
    )
    batch_items = app_store.retrieval_batch_items_for_job(library["library_id"], batch_job["job_id"])
    app_store.complete_retrieval_batch_item(
        library["library_id"],
        batch_items[0]["job_item_id"],
        status="completed",
        run_id="run-validation",
        candidate_count=2,
        source_stats={"localfile": {"ok": True, "count": 2, "elapsed_ms": 4}},
    )
    app_store.complete_retrieval_batch_item(
        library["library_id"],
        batch_items[1]["job_item_id"],
        status="failed",
        error="fixture timeout",
        source_stats={"localfile": {"ok": False, "count": 0, "elapsed_ms": 9, "error_kind": "timeout"}},
    )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], batch_job["job_id"], "completed")

    response = client.get(f"/api/library/{library['library_id']}/retrieval/onboarding?query=robot&sample_size=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    onboarding = payload["onboarding"]
    assert onboarding["status"] == "warning"
    assert onboarding["summary"]["readiness_status"] == "ready"
    assert onboarding["summary"]["tuning_status"] == "no_data"
    assert onboarding["summary"]["batch_validation_status"] == "failed_queries"
    assert "failed queries" in onboarding["summary"]["batch_validation_message"]
    assert onboarding["summary"]["configured_internal_count"] == 1
    assert onboarding["summary"]["batch_required_source_count"] == 1
    assert onboarding["summary"]["batch_validated_source_count"] == 1
    assert onboarding["summary"]["batch_missing_source_count"] == 0
    assert onboarding["summary"]["batch_missing_sources"] == []
    assert onboarding["summary"]["batch_source_error_count"] == 1
    assert onboarding["summary"]["batch_source_errors"] == ["localfile"]
    assert onboarding["summary"]["config_bundle_configured_source_count"] >= 1
    assert onboarding["summary"]["acceptance_gate_count"] == 6
    assert onboarding["summary"]["acceptance_gate_passed_count"] == 3
    assert onboarding["summary"]["acceptance_gate_warning_count"] == 1
    assert onboarding["summary"]["acceptance_gate_needs_sampling_count"] == 2
    assert onboarding["summary"]["acceptance_gate_blocked_count"] == 0
    assert onboarding["summary"]["batch_job_count"] == 1
    assert onboarding["summary"]["batch_completed_queries"] == 2
    assert onboarding["summary"]["batch_required_completed_queries"] == 3
    assert onboarding["summary"]["batch_completed_query_gap"] == 1
    assert onboarding["summary"]["batch_failed_queries"] == 1
    assert onboarding["summary"]["batch_total_candidates"] == 2
    assert onboarding["summary"]["import_readiness_status"] == "needs_sampling"
    assert onboarding["summary"]["import_readiness_checked_candidate_count"] == 0
    assert onboarding["summary"]["latest_batch_report_endpoint"] == f"/retrieval/batches/{batch_job['job_id']}/report"
    assert (
        onboarding["summary"]["latest_batch_source_report_endpoint"]
        == f"/retrieval/batches/{batch_job['job_id']}/report?format=csv&scope=sources"
    )
    assert onboarding["summary"]["source_field_map_report_count"] == 1
    assert onboarding["config_bundle"]["download_endpoint"] == "/retrieval/config-bundle/download"
    assert onboarding["batch_validation"]["status"] == "failed_queries"
    assert "failed queries" in onboarding["batch_validation"]["message"]
    assert onboarding["batch_validation"]["required_completed_queries"] == 3
    assert onboarding["batch_validation"]["completed_query_gap"] == 1
    assert onboarding["batch_validation"]["required_sources"] == ["localfile"]
    assert onboarding["batch_validation"]["validated_sources"] == ["localfile"]
    assert onboarding["batch_validation"]["source_errors"] == ["localfile"]
    assert onboarding["batch_validation"]["remediation"]["action"] == "retry_failed_queries"
    assert onboarding["batch_validation"]["remediation"]["method"] == "POST"
    assert (
        onboarding["batch_validation"]["remediation"]["endpoint"]
        == f"/retrieval/batches/{batch_job['job_id']}/retry-failed"
    )
    assert onboarding["batch_validation"]["jobs"][0]["job_id"] == batch_job["job_id"]
    assert onboarding["batch_validation"]["jobs"][0]["report_endpoint"] == f"/retrieval/batches/{batch_job['job_id']}/report"
    assert (
        onboarding["batch_validation"]["jobs"][0]["source_report_endpoint"]
        == f"/retrieval/batches/{batch_job['job_id']}/report?format=csv&scope=sources"
    )
    gates_by_name = {gate["name"]: gate for gate in onboarding["acceptance_gates"]}
    assert gates_by_name["source_readiness"]["status"] == "passed"
    assert gates_by_name["source_readiness"]["action_endpoint"].startswith(
        "/retrieval/readiness/report?format=markdown&query=robot"
    )
    assert gates_by_name["batch_validation"]["status"] == "warning"
    assert "failed queries" in gates_by_name["batch_validation"]["message"]
    assert gates_by_name["batch_validation"]["action_label"] == "Retry failed queries"
    assert gates_by_name["batch_validation"]["action_method"] == "POST"
    batch_artifacts = {artifact["label"]: artifact["endpoint"] for artifact in gates_by_name["batch_validation"]["artifacts"]}
    assert batch_artifacts["Batch report"] == f"/retrieval/batches/{batch_job['job_id']}/report"
    assert batch_artifacts["Source CSV"] == f"/retrieval/batches/{batch_job['job_id']}/report?format=csv&scope=sources"
    assert gates_by_name["tuning_signal"]["status"] == "needs_sampling"
    assert gates_by_name["tuning_signal"]["action_endpoint"] == "/retrieval/tuning/report?format=markdown&limit=100"
    assert gates_by_name["import_readiness"]["status"] == "needs_sampling"
    assert "0/0 sampled candidates" in gates_by_name["import_readiness"]["evidence"]
    assert gates_by_name["config_bundle"]["status"] == "passed"
    assert gates_by_name["config_bundle"]["action_endpoint"] == "/retrieval/config-bundle/download"
    assert gates_by_name["handoff_artifacts"]["status"] == "passed"
    handoff_artifacts = {
        artifact["label"]: artifact["endpoint"] for artifact in gates_by_name["handoff_artifacts"]["artifacts"]
    }
    assert handoff_artifacts["ONB report"].startswith("/retrieval/onboarding/report?format=markdown&query=robot")
    assert handoff_artifacts["Source setup"] == "/retrieval/sources/report?format=markdown"
    assert handoff_artifacts["PLAN report"].startswith("/retrieval/query-plan/report?format=markdown&seed_query=robot")
    assert handoff_artifacts["Local field_map report"].startswith(
        "/retrieval/local-files/field-map/report?format=markdown&sample_size=1"
    )
    assert handoff_artifacts["CFG bundle"] == "/retrieval/config-bundle/download"
    assert any("query" in item for item in onboarding["recommendations"])
    assert any("failed queries" in item for item in onboarding["recommendations"])

    markdown_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding/report?query=robot&sample_size=1"
    )
    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-onboarding-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "readiness" in markdown_text
    assert "config_bundle" in markdown_text
    assert "batch_validation" in markdown_text
    assert "入库模型检查" in markdown_text
    assert "Acceptance Gates" in markdown_text
    assert "acceptance_gate" in markdown_text
    assert "Batch report: /retrieval/batches/" in markdown_text
    assert "CFG bundle: /retrieval/config-bundle/download" in markdown_text
    assert "recent_batch_validation" in markdown_text
    assert "batch_source" in markdown_text
    assert "batch_evidence" in markdown_text
    assert "failed_queries" in markdown_text
    assert f"/retrieval/batches/{batch_job['job_id']}/report" in markdown_text
    assert f"/retrieval/batches/{batch_job['job_id']}/report?format=csv&scope=sources" in markdown_text

    csv_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding/report?query=robot&sample_size=1&format=csv"
    )
    assert csv_response.status_code == 200
    csv_text = csv_response.get_data(as_text=True)
    assert csv_text.startswith("section,name,status,configured")
    assert "batch_validation" in csv_text
    assert "acceptance_gate" in csv_text
    assert "source_readiness" in csv_text
    assert "Batch report=/retrieval/batches/" in csv_text
    assert "CFG bundle=/retrieval/config-bundle/download" in csv_text
    assert "recent_batch_validation" in csv_text
    assert "import_readiness,batch_candidates,needs_sampling" in csv_text
    assert "batch_evidence" in csv_text
    assert f"/retrieval/batches/{batch_job['job_id']}/report?format=csv&scope=sources" in csv_text

    package_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding/package?query=robot&sample_size=1"
    )
    assert package_response.status_code == 200
    assert package_response.headers["Content-Type"].startswith("application/zip")
    assert "retrieval-onboarding-package.zip" in package_response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(package_response.get_data())) as package:
        names = set(package.namelist())
        assert "README.md" in names
        assert "manifest.json" in names
        assert "onboarding/retrieval-onboarding-report.md" in names
        assert "onboarding/retrieval-onboarding-report.csv" in names
        assert "onboarding/retrieval-onboarding-report.json" in names
        assert "query-plan/retrieval-query-plan.md" in names
        assert "query-plan/retrieval-query-plan.csv" in names
        assert "query-plan/retrieval-query-plan.json" in names
        assert "source-setup/retrieval-source-setup-report.md" in names
        assert "source-setup/retrieval-source-setup-report.csv" in names
        assert "source-setup/retrieval-source-setup-report.json" in names
        assert "readiness/retrieval-readiness-report.md" in names
        assert "field-map/local-files/retrieval-local-files-field-map-report.md" in names
        assert "field-map/local-files/retrieval-local-files-field-map-report.csv" in names
        assert "field-map/local-files/retrieval-local-files-field-map-report.json" in names
        assert "tuning/retrieval-tuning-report.md" in names
        assert "config/retrieval-config-bundle.json" in names
        assert f"batch/{batch_job['job_id']}-report.md" in names
        assert f"batch/{batch_job['job_id']}-report-sources.csv" in names
        readme_bytes = package.read("README.md")
        readme_text = readme_bytes.decode("utf-8")
        assert "Retrieval onboarding handoff package" in readme_text
        assert "SHA256" in readme_text
        manifest = json.loads(package.read("manifest.json").decode("utf-8"))
        assert manifest["schema"] == "web-library.retrieval-onboarding-package/v1"
        assert manifest["status"] == "warning"
        assert manifest["query"] == "robot"
        assert manifest["sample_size"] == 1
        assert manifest["query_plan"]["seed_query"] == "robot"
        assert manifest["query_plan"]["query_count"] >= 1
        assert "robot" in manifest["query_plan"]["query_text"]
        assert manifest["source_setup"]["source_count"] >= 10
        assert manifest["source_setup"]["configured_count"] >= 1
        assert manifest["source_setup"]["include_health"] is False
        assert manifest["field_map_reports"] == [
            {
                "source": "localfile",
                "label": "Local field_map report",
                "path_prefix": "field-map/local-files",
            }
        ]
        files_by_path = {file["path"]: file for file in manifest["files"]}
        assert "manifest.json" not in files_by_path
        assert files_by_path["README.md"]["bytes"] == len(readme_bytes)
        assert files_by_path["README.md"]["sha256"] == hashlib.sha256(readme_bytes).hexdigest()
        query_plan_bytes = package.read("query-plan/retrieval-query-plan.md")
        assert files_by_path["query-plan/retrieval-query-plan.md"]["bytes"] == len(query_plan_bytes)
        assert files_by_path["query-plan/retrieval-query-plan.md"]["sha256"] == hashlib.sha256(
            query_plan_bytes
        ).hexdigest()
        source_setup_bytes = package.read("source-setup/retrieval-source-setup-report.md")
        assert files_by_path["source-setup/retrieval-source-setup-report.md"]["bytes"] == len(source_setup_bytes)
        assert files_by_path["source-setup/retrieval-source-setup-report.md"]["sha256"] == hashlib.sha256(
            source_setup_bytes
        ).hexdigest()
        config_bytes = package.read("config/retrieval-config-bundle.json")
        assert files_by_path["config/retrieval-config-bundle.json"]["bytes"] == len(config_bytes)
        assert files_by_path["config/retrieval-config-bundle.json"]["sha256"] == hashlib.sha256(
            config_bytes
        ).hexdigest()
        field_map_bytes = package.read("field-map/local-files/retrieval-local-files-field-map-report.md")
        assert files_by_path["field-map/local-files/retrieval-local-files-field-map-report.md"]["bytes"] == len(
            field_map_bytes
        )
        assert files_by_path["field-map/local-files/retrieval-local-files-field-map-report.md"]["sha256"] == hashlib.sha256(
            field_map_bytes
        ).hexdigest()


def test_retrieval_onboarding_requires_query_plan_coverage(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture, name="ONB Query Coverage")
    local_csv = tmp_path / "onboarding-query-coverage.csv"
    local_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Coverage Robot Dataset,2026,10.6060/ONB-COVERAGE,Ada Lovelace,"
        "Coverage abstract for onboarding query planning,coverage robot,https://example.test/coverage,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    save_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(local_csv)]},
    )
    assert save_response.status_code == 200

    plan = web.retrieval_query_plan_for_library(
        library["library_id"],
        seed_query="coverage robot",
        sample_size=1,
        limit=5,
    )
    planned_queries = [item["query"] for item in plan["queries"]]
    assert planned_queries

    batch_job = app_store.create_retrieval_batch_job(
        library["library_id"],
        ["unrelated one", "unrelated two", "unrelated three"],
        ["localfile"],
        3,
    )
    batch_items = app_store.retrieval_batch_items_for_job(library["library_id"], batch_job["job_id"])
    for index, item in enumerate(batch_items, start=1):
        app_store.complete_retrieval_batch_item(
            library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id=f"run-onb-query-gap-{index}",
            candidate_count=1,
            source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 4}},
        )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], batch_job["job_id"], "completed")

    response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding?query=coverage+robot&sample_size=1"
    )

    assert response.status_code == 200
    onboarding = response.get_json()["onboarding"]
    assert onboarding["summary"]["query_plan_query_count"] == len(planned_queries)
    assert onboarding["summary"]["batch_validation_status"] == "query_gap"
    assert onboarding["summary"]["batch_required_query_count"] == len(planned_queries)
    assert onboarding["summary"]["batch_covered_query_count"] == 0
    assert onboarding["summary"]["batch_missing_queries"] == planned_queries
    assert onboarding["batch_validation"]["missing_queries"] == planned_queries
    gates_by_name = {gate["name"]: gate for gate in onboarding["acceptance_gates"]}
    assert gates_by_name["batch_validation"]["status"] == "needs_sampling"
    assert "PLAN queries" in gates_by_name["batch_validation"]["evidence"]
    assert onboarding["batch_validation"]["remediation"]["action"] == "run_required_query_batch"
    assert onboarding["batch_validation"]["remediation"]["method"] == "POST"
    assert gates_by_name["batch_validation"]["action_label"] == "Run required-query batch"
    assert gates_by_name["batch_validation"]["action_endpoint"] == "/retrieval/batches"
    assert gates_by_name["batch_validation"]["action_method"] == "POST"


def test_retrieval_onboarding_can_validate_explicit_required_queries(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture, name="ONB Explicit Queries")
    local_csv = tmp_path / "onboarding-explicit-queries.csv"
    local_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Explicit Robot Dataset,2026,10.6060/ONB-EXPLICIT,Ada Lovelace,"
        "Explicit abstract for onboarding query planning,explicit robot,https://example.test/explicit,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(local_csv)]},
        ).status_code
        == 200
    )
    explicit_queries = ["manual alpha", "manual beta", "manual gamma"]
    batch_job = app_store.create_retrieval_batch_job(
        library["library_id"],
        explicit_queries,
        ["localfile"],
        3,
    )
    for index, item in enumerate(app_store.retrieval_batch_items_for_job(library["library_id"], batch_job["job_id"]), start=1):
        app_store.complete_retrieval_batch_item(
            library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id=f"run-onb-explicit-{index}",
            candidate_count=1,
            source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 4}},
        )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], batch_job["job_id"], "completed")

    response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding",
        query_string={
            "query": "explicit robot",
            "sample_size": "1",
            "required_queries": "\n".join(explicit_queries),
        },
    )

    assert response.status_code == 200
    onboarding = response.get_json()["onboarding"]
    assert onboarding["validation_query_source"] == "explicit"
    assert onboarding["validation_queries"] == explicit_queries
    assert onboarding["summary"]["validation_query_source"] == "explicit"
    assert onboarding["summary"]["validation_query_count"] == 3
    assert onboarding["summary"]["batch_validation_status"] == "passed"
    assert onboarding["summary"]["batch_covered_query_count"] == 3
    assert onboarding["summary"]["batch_missing_query_count"] == 0
    assert onboarding["batch_validation"]["required_queries"] == explicit_queries
    gates_by_name = {gate["name"]: gate for gate in onboarding["acceptance_gates"]}
    assert gates_by_name["batch_validation"]["status"] == "passed"
    assert "explicit queries" in gates_by_name["batch_validation"]["evidence"]
    csv_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding/report",
        query_string={
            "format": "csv",
            "query": "explicit robot",
            "sample_size": "1",
            "required_queries": "\n".join(explicit_queries),
        },
    )
    assert csv_response.status_code == 200
    csv_text = csv_response.get_data(as_text=True)
    assert "validation_query_source" in csv_text
    assert "manual alpha" in csv_text


def test_retrieval_onboarding_detects_batch_config_drift(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture, name="ONB Config Drift")
    first_csv = tmp_path / "onboarding-config-first.csv"
    first_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Config First Dataset,2026,10.6060/ONB-CONFIG-1,Ada Lovelace,"
        "First config abstract,config robot,https://example.test/config-1,dataset\n",
        encoding="utf-8",
    )
    second_csv = tmp_path / "onboarding-config-second.csv"
    second_csv.write_text(
        "title,year,doi,authors,abstract,keywords,url,item_type\n"
        "Config Second Dataset,2026,10.6060/ONB-CONFIG-2,Ada Lovelace,"
        "Second config abstract,config robot,https://example.test/config-2,dataset\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(first_csv)]},
        ).status_code
        == 200
    )
    explicit_queries = ["config drift alpha", "config drift beta", "config drift gamma"]
    batch_context = web.retrieval_batch_context_for_library(library["library_id"])
    batch_job = app_store.create_retrieval_batch_job(
        library["library_id"],
        explicit_queries,
        ["localfile"],
        3,
        context=batch_context,
    )
    stored_job = app_store.retrieval_batch_job(library["library_id"], batch_job["job_id"])
    assert stored_job["context"]["config_fingerprint"] == batch_context["config_fingerprint"]
    batch_items = app_store.retrieval_batch_items_for_job(library["library_id"], batch_job["job_id"])
    for index, item in enumerate(batch_items, start=1):
        app_store.complete_retrieval_batch_item(
            library["library_id"],
            item["job_item_id"],
            status="completed",
            run_id=f"run-onb-config-drift-{index}",
            candidate_count=1,
            source_stats={"localfile": {"ok": True, "count": 1, "elapsed_ms": 4}},
        )
    app_store.mark_retrieval_batch_job_finished(library["library_id"], batch_job["job_id"], "completed")

    matched = web.retrieval_batch_validation_summary(
        library["library_id"],
        required_sources=["localfile"],
        required_queries=explicit_queries,
    )
    assert matched["status"] == "passed"
    assert matched["config_context_status"] == "matched"
    assert matched["config_matched_job_count"] == 1

    assert (
        client.post(
            f"/api/library/{library['library_id']}/retrieval/local-files",
            json={"paths": [str(second_csv)]},
        ).status_code
        == 200
    )
    response = client.get(
        f"/api/library/{library['library_id']}/retrieval/onboarding",
        query_string={
            "query": "config robot",
            "sample_size": "1",
            "required_queries": "\n".join(explicit_queries),
        },
    )

    assert response.status_code == 200
    onboarding = response.get_json()["onboarding"]
    assert onboarding["status"] == "needs_sampling"
    assert onboarding["summary"]["batch_validation_status"] == "config_drift"
    assert onboarding["summary"]["batch_config_context_status"] == "mismatch"
    assert onboarding["batch_validation"]["status"] == "config_drift"
    assert onboarding["batch_validation"]["config_context_status"] == "mismatch"
    assert onboarding["batch_validation"]["config_mismatch_job_count"] == 1
    assert onboarding["batch_validation"]["remediation"]["action"] == "rerun_current_config_batch"
    assert onboarding["batch_validation"]["remediation"]["method"] == "POST"
    assert onboarding["batch_validation"]["jobs"][0]["config_context_status"] == "mismatch"
    gates_by_name = {gate["name"]: gate for gate in onboarding["acceptance_gates"]}
    assert gates_by_name["batch_validation"]["status"] == "needs_sampling"
    assert "config mismatch" in gates_by_name["batch_validation"]["evidence"]
    assert gates_by_name["batch_validation"]["action_label"] == "Run current-config batch"
    assert gates_by_name["batch_validation"]["action_endpoint"] == "/retrieval/batches"
    assert gates_by_name["batch_validation"]["action_method"] == "POST"


def test_retrieval_sqlite_preference_enables_sqlite_source(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG", raising=False)
    db_path = tmp_path / "competition.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE items (
              id TEXT, title TEXT, year TEXT, doi TEXT, authors TEXT,
              abstract TEXT, keywords TEXT, url TEXT, venue TEXT, item_type TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO items VALUES (
              'db-1', 'Configured SQLite Robot Dataset', '2026', '10.6060/SQLITE-CONFIG',
              'Ada Lovelace', 'Configured SQLite abstract.',
              'robotics; dataset', 'https://example.test/sqlite-config', 'SQLite Registry', 'dataset'
            )
            """
        )
        conn.commit()
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()
    config = {
        "label": "Competition SQLite",
        "path": str(db_path),
        "query": (
            "SELECT id, title, year, doi, authors, abstract, keywords, url, venue, item_type "
            "FROM items WHERE title LIKE :like_query OR abstract LIKE :like_query LIMIT :limit"
        ),
    }

    initial_response = client.get(f"/api/library/{library['library_id']}/retrieval/sqlite")
    assert initial_response.status_code == 200
    assert initial_response.get_json()["summary"]["configured"] is False

    save_response = client.post(f"/api/library/{library['library_id']}/retrieval/sqlite", json={"config": config})
    assert save_response.status_code == 200
    save_payload = save_response.get_json()
    assert save_payload["summary"]["configured"] is True
    assert save_payload["summary"]["label"] == "Competition SQLite"

    sources_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources")
    by_name = {source["name"]: source for source in sources_response.get_json()["sources"]}
    assert by_name["sqlite"]["available"] is True
    assert by_name["sqlite"]["configured"] is True

    preview_response = client.get(f"/api/library/{library['library_id']}/retrieval/sqlite/preview?query=robot&sample_size=2")
    assert preview_response.status_code == 200
    preview = preview_response.get_json()["preview"]
    assert preview["quality"]["status"] == "good"
    assert preview["samples"][0]["item"]["fields"]["title"] == "Configured SQLite Robot Dataset"

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot", "sources": ["sqlite"], "limit": 2},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["source_stats"]["sqlite"]["ok"] is True
    assert search_payload["candidates"][0]["title"] == "Configured SQLite Robot Dataset"
    assert search_payload["candidates"][0]["identifiers"]["doi"] == "10.6060/sqlite-config"


def test_retrieval_manifest_preference_enables_manifest_source(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    manifest_path = tmp_path / "object-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "objects": [
                    {
                        "id": "obj-config-1",
                        "item_type": "dataset",
                        "title": "Configured Object Manifest Robot Dataset",
                        "year": "2026",
                        "doi": "10.6060/MANIFEST-CONFIG",
                        "authors": "Ada Lovelace",
                        "abstract": "Configured object manifest abstract.",
                        "keywords": "robotics; dataset",
                        "object_url": "https://objects.example.test/obj-config-1",
                        "pdf_url": "https://objects.example.test/obj-config-1.pdf",
                        "venue": "Object Registry",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()
    config = {
        "label": "Competition Objects",
        "manifest_path": str(manifest_path),
        "items_path": "objects",
        "field_map": {
            "title": "title",
            "date": "year",
            "doi": "doi",
            "authors": "authors",
            "abstract": "abstract",
            "tags": "keywords",
            "url": "object_url",
            "pdf_url": "pdf_url",
            "venue": "venue",
            "item_type": "item_type",
            "external_id": "id",
        },
    }

    initial_response = client.get(f"/api/library/{library['library_id']}/retrieval/manifest")
    assert initial_response.status_code == 200
    assert initial_response.get_json()["summary"]["configured"] is False

    save_response = client.post(f"/api/library/{library['library_id']}/retrieval/manifest", json={"config": config})
    assert save_response.status_code == 200
    save_payload = save_response.get_json()
    assert save_payload["source"] == "preference"
    assert save_payload["summary"]["configured"] is True
    assert save_payload["summary"]["label"] == "Competition Objects"
    assert "object-manifest.json" in save_payload["config"]

    sources_response = client.get(f"/api/library/{library['library_id']}/retrieval/sources")
    by_name = {source["name"]: source for source in sources_response.get_json()["sources"]}
    assert by_name["manifest"]["available"] is True
    assert by_name["manifest"]["configured"] is True

    preview_response = client.get(f"/api/library/{library['library_id']}/retrieval/manifest/preview?query=robot&sample_size=2")
    assert preview_response.status_code == 200
    preview = preview_response.get_json()["preview"]
    assert preview["quality"]["status"] == "good"
    assert preview["samples"][0]["item"]["fields"]["title"] == "Configured Object Manifest Robot Dataset"
    assert preview["samples"][0]["item"]["identifiers"]["doi"] == "10.6060/manifest-config"

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot", "sources": ["manifest"], "limit": 2},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["source_stats"]["manifest"]["ok"] is True
    assert search_payload["candidates"][0]["title"] == "Configured Object Manifest Robot Dataset"
    assert search_payload["candidates"][0]["identifiers"]["doi"] == "10.6060/manifest-config"
    assert search_payload["candidates"][0]["pdf_url"] == "https://objects.example.test/obj-config-1.pdf"


def test_retrieval_manifest_templates_api_returns_editable_templates(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/manifest/templates")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    by_id = {template["id"]: template for template in payload["templates"]}
    assert set(by_id) == {"local-json", "remote-json"}
    assert by_id["local-json"]["config"]["manifest_path"].endswith("object-manifest.json")
    assert by_id["remote-json"]["config"]["manifest_url"].startswith("https://")
    assert by_id["remote-json"]["config"]["auth"]["type"] == "bearer_env"


def test_retrieval_local_file_preview_api_maps_heterogeneous_sources(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_read_only_source(zotero_fixture)
    fixture_dir = Path(__file__).parent / "fixtures" / "retrieval_sources"
    client = create_app().test_client()

    config_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(fixture_dir)]},
    )
    assert config_response.status_code == 200

    preview_response = client.get(f"/api/library/{library['library_id']}/retrieval/local-files/preview?sample_size=1")

    assert preview_response.status_code == 200
    payload = preview_response.get_json()
    assert payload["ok"] is True
    preview = payload["preview"]
    assert preview["file_count"] == 2
    by_name = {file["name"]: file for file in preview["files"]}

    csv_file = by_name["ai4s_registry.csv"]
    csv_mappings = {mapping["column"]: mapping["target"] for mapping in csv_file["mappings"]}
    assert csv_mappings["title"] == "item.fields.title"
    assert csv_mappings["doi"] == "item.fields.DOI"
    assert csv_mappings["keywords"] == "item.tags"
    assert csv_file["quality"]["status"] == "good"
    assert csv_file["quality"]["fields"][0]["field"] == "title"
    assert csv_file["quality"]["fields"][0]["missing_count"] == 0
    assert csv_file["field_map_suggestion"]["draft_available"] is True
    assert csv_file["field_map_suggestion"]["field_map"]["title"] == "title"
    assert csv_file["field_map_suggestion"]["field_map"]["doi"] == "doi"
    assert csv_file["field_map_suggestion"]["config_draft"]["field_map"]["title"] == "title"
    assert csv_file["field_map_suggestion"]["sample_count"] == 1
    assert csv_file["samples"][0]["item"]["item_type"] == "dataset"
    assert csv_file["samples"][0]["item"]["fields"]["title"] == "AI4S Retrieval Benchmark Dataset"
    assert csv_file["samples"][0]["item"]["identifiers"]["doi"] == "10.6060/ai4s-benchmark"
    assert csv_file["samples"][0]["quality"]["status"] == "good"

    jsonl_file = by_name["ai4s_exports.jsonl"]
    jsonl_mappings = {mapping["column"]: mapping["target"] for mapping in jsonl_file["mappings"]}
    assert jsonl_mappings["name"] == "item.fields.title"
    assert jsonl_mappings["publicationYear"] == "item.fields.date"
    assert jsonl_mappings["resource_type"] == "item.item_type"
    assert jsonl_file["field_map_suggestion"]["field_map"]["title"] == "name"
    assert jsonl_file["field_map_suggestion"]["field_map"]["date"] == "publicationYear"
    sample_item = jsonl_file["samples"][0]["item"]
    assert sample_item["item_type"] == "computerProgram"
    assert sample_item["fields"]["title"] == "AI4S Retrieval Pipeline Software"
    assert sample_item["creators"][0]["last_name"] == "Hopper"
    assert sample_item["tags"] == ["AI4S", "retrieval", "software"]


def test_local_file_preview_reports_mapping_quality_issues(tmp_path: Path) -> None:
    csv_path = tmp_path / "quality.csv"
    csv_path.write_text(
        "\n".join(
            [
                "title,authors,year,doi",
                "Complete Row,Ada Lovelace,2026,10.5555/complete",
                ",Ada Lovelace,,",
                "No Identifier,Grace Hopper,2025,",
            ]
        ),
        encoding="utf-8",
    )

    preview = retrieval_providers.preview_local_file_mappings([csv_path], sample_size=3)
    file = preview["files"][0]
    quality = file["quality"]
    fields = {field["field"]: field for field in quality["fields"]}

    assert quality["status"] == "poor"
    assert quality["row_count"] == 3
    assert quality["rows_with_issues"] == 2
    assert quality["rows_with_errors"] == 1
    assert fields["title"]["missing_count"] == 1
    assert fields["identifier"]["missing_count"] == 2
    assert fields["date"]["missing_count"] == 1
    assert any("Strong identifier" in message for message in quality["recommendations"])
    assert file["field_map_suggestion"]["field_map"]["title"] == "title"
    assert file["field_map_suggestion"]["field_map"]["date"] == "year"
    assert file["field_map_suggestion"]["draft_available"] is True
    assert file["field_map_suggestion"]["config_draft"]["field_map"]["title"] == "title"
    assert file["samples"][1]["quality"]["status"] == "poor"
    assert file["samples"][1]["quality"]["issues"][0]["field"] == "title"
    assert file["samples"][2]["quality"]["issues"][0]["field"] == "identifier"


def test_local_csv_jsonl_retrieval_full_loop_imports_and_records_provenance(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    library = create_local_copy(zotero_fixture)
    fixture_dir = Path(__file__).parent / "fixtures" / "retrieval_sources"
    client = create_app().test_client()

    config_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(fixture_dir)]},
    )
    assert config_response.status_code == 200
    assert config_response.get_json()["status"]["file_count"] == 2

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "AI4S retrieval", "sources": ["localfile"], "limit": 5},
    )

    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["source_stats"]["localfile"]["ok"] is True
    assert search_payload["source_stats"]["localfile"]["count"] == 2
    assert [candidate["title"] for candidate in search_payload["candidates"]] == [
        "AI4S Retrieval Benchmark Dataset",
        "AI4S Retrieval Pipeline Software",
    ]
    assert search_payload["candidates"][0]["identifiers"]["doi"] == "10.6060/ai4s-benchmark"
    assert search_payload["candidates"][1]["item"]["item_type"] == "computerProgram"
    assert search_payload["candidates"][1]["item"]["tags"] == ["AI4S", "retrieval", "software"]

    import_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/import",
        json={
            "run_id": search_payload["run_id"],
            "candidate_ids": [candidate["candidate_id"] for candidate in search_payload["candidates"]],
            "collection_key": "COLL0001",
        },
    )

    assert import_response.status_code == 200
    import_payload = import_response.get_json()
    assert import_payload["created_count"] == 2
    assert [result["status"] for result in import_payload["results"]] == ["created", "created"]
    evidence = import_payload["import_evidence"]
    assert evidence["status"] == "recorded"
    assert evidence["run_id"] == search_payload["run_id"]
    assert evidence["run_linked"] is True
    assert evidence["candidate_count"] == 2
    assert evidence["result_count"] == 2
    assert evidence["provenance_recorded_count"] == 2
    assert evidence["item_key_count"] == 2
    assert evidence["created_count"] == 2
    assert evidence["sources"] == ["localfile"]
    assert evidence["run_report_markdown_endpoint"] == (
        f"/api/library/{library['library_id']}/retrieval/runs/{search_payload['run_id']}/report?format=markdown"
    )
    assert evidence["summary_report_endpoint"] == (
        f"/api/library/{library['library_id']}/retrieval/summary/report?format=markdown"
    )
    assert [item["candidate_id"] for item in evidence["items"]] == [
        candidate["candidate_id"] for candidate in search_payload["candidates"]
    ]

    state = ZoteroRepository(library).state()
    imported_by_title = {
        item["title"]: item
        for item in state["items"]
        if item["title"] in {"AI4S Retrieval Benchmark Dataset", "AI4S Retrieval Pipeline Software"}
    }
    assert set(imported_by_title) == {"AI4S Retrieval Benchmark Dataset", "AI4S Retrieval Pipeline Software"}
    assert imported_by_title["AI4S Retrieval Benchmark Dataset"]["fields"]["DOI"] == "10.6060/ai4s-benchmark"
    assert imported_by_title["AI4S Retrieval Pipeline Software"]["creators_full_display"] == "Grace Hopper / Alan Turing"
    assert "software" in imported_by_title["AI4S Retrieval Pipeline Software"]["tags"]
    assert all(any(collection["key"] == "COLL0001" for collection in item["collections"]) for item in imported_by_title.values())

    runs = app_store.recent_retrieval_runs(library["library_id"])
    assert runs[0]["run_id"] == search_payload["run_id"]
    assert runs[0]["candidate_count"] == 2
    assert runs[0]["imported_count"] == 2

    with app_store.connect() as conn:
        rows = conn.execute(
            """
            SELECT candidate_id, item_key, source, status, operator, identifiers_json
            FROM import_provenance
            WHERE library_id = ? AND run_id = ?
            ORDER BY provenance_id
            """,
            (library["library_id"], search_payload["run_id"]),
        ).fetchall()
    assert len(rows) == 2
    assert {row["source"] for row in rows} == {"localfile"}
    assert {row["status"] for row in rows} == {"created"}
    assert {row["operator"] for row in rows} == {"cjh"}
    assert {json.loads(row["identifiers_json"])["doi"] for row in rows} == {
        "10.6060/ai4s-benchmark",
        "10.6060/ai4s-software",
    }


def test_retrieval_local_file_preference_rejects_invalid_paths(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/local-files",
        json={"paths": [str(tmp_path / "missing.csv")]},
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
    assert "有效路径" in response.get_json()["error"]


def test_retrieval_sources_api_can_run_health_checks(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)

    def fake_statuses(**kwargs):
        return [
            {
                "name": "crossref",
                "label": "Crossref",
                "available": True,
                "requires_config": False,
                "health": {"ok": True, "count": 1, "elapsed_ms": 12, "error": ""},
            }
        ]

    monkeypatch.setattr(web, "retrieval_source_statuses", fake_statuses)
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/sources?check=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["sources"][0]["health"]["ok"] is True


def test_retrieval_run_summary_aggregates_runs_sources_and_imports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    first = app_store.create_retrieval_run(
        "summary-lib",
        "robot",
        ["crossref", "semanticscholar"],
        {
            "crossref": {
                "ok": True,
                "count": 2,
                "error": "",
                "elapsed_ms": 100,
                "rate_limit_wait_ms": 25,
                "rate_limit_seconds": 0.5,
            },
            "semanticscholar": {
                "ok": False,
                "count": 0,
                "error": "HTTP 429",
                "error_kind": "rate_limited",
                "action": "稍后重试",
                "elapsed_ms": 50,
                "rate_limit_wait_ms": 0,
                "rate_limit_seconds": 1.0,
            },
        },
        [
            {"source": "crossref", "title": "A", "identifiers": {"doi": "10.1/a"}},
            {"source": "crossref", "title": "B", "identifiers": {"doi": "10.1/b"}},
        ],
    )
    app_store.create_retrieval_run(
        "summary-lib",
        "robot",
        ["crossref"],
        {
            "crossref": {
                "ok": True,
                "count": 1,
                "error": "",
                "elapsed_ms": 300,
                "rate_limit_wait_ms": 75,
                "rate_limit_seconds": 0.5,
            }
        },
        [],
    )
    app_store.record_import_provenance(
        "summary-lib",
        first["run_id"],
        [first["candidates"][0]],
        [{"status": "created", "item_key": "ITEM0001", "source": "Crossref"}],
    )

    summary = app_store.retrieval_run_summary("summary-lib")

    assert summary["totals"]["run_count"] == 2
    assert summary["totals"]["candidate_count"] == 2
    assert summary["totals"]["imported_count"] == 1
    assert summary["totals"]["import_rate"] == 0.5
    assert summary["totals"]["source_attempt_count"] == 3
    assert summary["totals"]["source_success_count"] == 2
    assert summary["totals"]["source_failure_count"] == 1
    assert summary["sources"]["crossref"]["run_count"] == 2
    assert summary["sources"]["crossref"]["candidate_count"] == 3
    assert summary["sources"]["crossref"]["elapsed_avg_ms"] == 200
    assert summary["sources"]["crossref"]["rate_limit_wait_total_ms"] == 100
    assert summary["sources"]["crossref"]["rate_limit_wait_avg_ms"] == 50
    assert summary["sources"]["crossref"]["observed_rate_limit_seconds"] == 0.5
    assert summary["sources"]["semanticscholar"]["failure_count"] == 1
    assert summary["error_kinds"]["rate_limited"] == 1
    assert summary["top_queries"] == [{"query": "robot", "count": 2}]


def test_retrieval_summary_api_returns_stage_dashboard_data(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    app_store.create_retrieval_run(
        library["library_id"],
        "dashboard",
        ["crossref"],
        {"crossref": {"ok": True, "count": 1, "error": "", "elapsed_ms": 12}},
        [{"source": "crossref", "title": "Dashboard Candidate"}],
    )
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/summary")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["summary"]["totals"]["run_count"] == 1
    assert payload["summary"]["sources"]["crossref"]["elapsed_avg_ms"] == 12


def test_retrieval_tuning_api_reports_rate_limit_recommendations(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    library = create_read_only_source(zotero_fixture)
    app_store.create_retrieval_run(
        library["library_id"],
        "robot",
        ["semanticscholar", "openalex", "crossref"],
        {
            "semanticscholar": {
                "ok": False,
                "count": 0,
                "error": "HTTP 429",
                "error_kind": "rate_limited",
                "action": "retry later",
                "elapsed_ms": 40,
                "rate_limit_wait_ms": 0,
                "rate_limit_seconds": 1.0,
            },
            "openalex": {
                "ok": False,
                "count": 0,
                "error": "requires OPENALEX_API_KEY",
                "error_kind": "configuration",
                "action": "configure OPENALEX_API_KEY",
                "elapsed_ms": 5,
                "rate_limit_wait_ms": 0,
                "rate_limit_seconds": 0.5,
            },
            "crossref": {
                "ok": True,
                "count": 1,
                "error": "",
                "elapsed_ms": 20,
                "rate_limit_wait_ms": 25,
                "rate_limit_seconds": 0.25,
            },
        },
        [{"source": "crossref", "title": "Tuning Candidate"}],
    )
    client = create_app().test_client()

    response = client.get(f"/api/library/{library['library_id']}/retrieval/tuning")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    tuning = payload["tuning"]
    assert tuning["status"] == "blocked"
    assert tuning["summary"]["slow_down_count"] == 1
    assert tuning["summary"]["fix_config_count"] == 1
    by_source = {row["source"]: row for row in tuning["sources"]}
    assert by_source["semanticscholar"]["level"] == "slow_down"
    assert by_source["semanticscholar"]["recommended_rate_limit_seconds"] > by_source["semanticscholar"]["current_rate_limit_seconds"]
    assert by_source["semanticscholar"]["rate_limit_env"] == "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_SEMANTICSCHOLAR_SECONDS"
    assert by_source["openalex"]["level"] == "fix_config"
    assert by_source["crossref"]["rate_limit_wait_avg_ms"] == 25

    markdown_response = client.get(f"/api/library/{library['library_id']}/retrieval/tuning/report")
    assert markdown_response.status_code == 200
    assert markdown_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-tuning-report.md" in markdown_response.headers["Content-Disposition"]
    markdown_text = markdown_response.get_data(as_text=True)
    assert "# 多源检索限流调优报告" in markdown_text
    assert "Semantic Scholar" in markdown_text
    assert "WEB_LIBRARY_RETRIEVAL_RATE_LIMIT_SEMANTICSCHOLAR_SECONDS" in markdown_text

    csv_response = client.get(f"/api/library/{library['library_id']}/retrieval/tuning/report?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["Content-Type"].startswith("text/csv")
    csv_text = csv_response.get_data(as_text=True)
    assert "source,label,available,configured,run_count" in csv_text
    assert "semanticscholar,Semantic Scholar" in csv_text

    json_response = client.get(f"/api/library/{library['library_id']}/retrieval/tuning/report?format=json")
    assert json_response.status_code == 200
    assert json_response.headers["Content-Type"].startswith("application/json")
    json_payload = json_response.get_json()
    assert json_payload["summary"]["needs_action_count"] == 2


def test_retrieval_rehearsal_setup_generates_and_configures_internal_sources(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    library = create_local_copy(zotero_fixture, name="Rehearsal Target")
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/retrieval/rehearsal/setup?replace_existing=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["applied"] is True
    kit = payload["kit"]
    assert kit["schema"] == "web-library.retrieval-rehearsal-kit/v1"
    assert kit["queries"] == ["robot catalyst", "graph protein", "spectroscopy battery"]
    assert set(kit["configs"]) == {"localfile", "sqlite", "manifest"}
    assert set(item["source"] for item in payload["import_result"]["applied"]) == {"localfile", "sqlite", "manifest"}
    for file_entry in kit["files"]:
        assert Path(file_entry["path"]).exists()
        assert file_entry["rows"] == 3

    local_config = client.get(f"/api/library/{library['library_id']}/retrieval/local-files").get_json()
    assert local_config["paths"] == kit["configs"]["localfile"]["paths"]
    sqlite_config = client.get(f"/api/library/{library['library_id']}/retrieval/sqlite").get_json()
    assert json.loads(sqlite_config["config"])["path"] == kit["configs"]["sqlite"]["path"]
    manifest_config = client.get(f"/api/library/{library['library_id']}/retrieval/manifest").get_json()
    assert json.loads(manifest_config["config"])["manifest_path"] == kit["configs"]["manifest"]["manifest_path"]

    readiness_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/readiness?query=robot+catalyst&sample_size=2"
    )
    assert readiness_response.status_code == 200
    readiness = readiness_response.get_json()["readiness"]
    assert readiness["status"] == "ready"
    assert readiness["summary"]["configured_internal_count"] == 3
    assert readiness["summary"]["previewed_internal_count"] == 3
    assert readiness["summary"]["error_count"] == 0

    query_plan_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/query-plan?seed_query=robot+catalyst&sample_size=5&limit=5"
    )
    assert query_plan_response.status_code == 200
    query_plan = query_plan_response.get_json()["plan"]
    assert query_plan["status"] == "ready"
    assert query_plan["query_count"] >= 3
    assert "robot catalyst" in query_plan["query_text"]
    assert "robot catalyst benchmark" in query_plan["query_text"]
    assert "robot catalyst dataset" in query_plan["query_text"]
    assert "robot catalyst model" in query_plan["query_text"]
    assert "robot catalyst screening" in query_plan["query_text"]
    assert "graph protein" not in query_plan["query_text"]
    assert "spectroscopy battery" not in query_plan["query_text"]
    assert any(query["source_count"] >= 1 for query in query_plan["queries"])
    assert {source["source"] for source in query_plan["sources"]} == {"localfile", "httpjson", "sqlite", "manifest"}

    query_plan_report_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/query-plan/report"
        "?seed_query=robot+catalyst&sample_size=5&limit=5"
    )
    assert query_plan_report_response.status_code == 200
    assert query_plan_report_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-query-plan.md" in query_plan_report_response.headers["Content-Disposition"]
    query_plan_report_text = query_plan_report_response.get_data(as_text=True)
    assert "Retrieval query plan" in query_plan_report_text
    assert "robot catalyst" in query_plan_report_text
    assert "graph protein" not in query_plan_report_text
    assert "spectroscopy battery" not in query_plan_report_text

    query_plan_csv_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/query-plan/report"
        "?seed_query=robot+catalyst&sample_size=5&limit=5&format=csv"
    )
    assert query_plan_csv_response.status_code == 200
    assert query_plan_csv_response.headers["Content-Type"].startswith("text/csv")
    query_plan_csv_text = query_plan_csv_response.get_data(as_text=True)
    assert query_plan_csv_text.startswith("section,query,status,reason")
    assert "robot catalyst" in query_plan_csv_text
    assert "localfile" in query_plan_csv_text

    query_plan_json_response = client.get(
        f"/api/library/{library['library_id']}/retrieval/query-plan/report"
        "?seed_query=robot+catalyst&sample_size=5&limit=5&format=json"
    )
    assert query_plan_json_response.status_code == 200
    assert query_plan_json_response.headers["Content-Type"].startswith("application/json")
    query_plan_report_payload = query_plan_json_response.get_json()
    assert query_plan_report_payload["status"] == "ready"
    assert query_plan_report_payload["query_count"] >= 3

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot catalyst", "sources": ["localfile", "sqlite", "manifest"], "limit": 5},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["ok"] is True
    assert search_payload["candidates"]
    stats = search_payload["source_stats"]
    for source in ["localfile", "sqlite", "manifest"]:
        assert stats[source]["ok"] is True
        assert stats[source]["count"] >= 1

    conflict_response = client.post(f"/api/library/{library['library_id']}/retrieval/rehearsal/setup")
    assert conflict_response.status_code == 409
    conflict_payload = conflict_response.get_json()
    assert conflict_payload["ok"] is False
    assert set(conflict_payload["conflicts"]) == {"localfile", "sqlite", "manifest"}


def test_retrieval_rehearsal_validate_runs_batch_and_returns_onboarding(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_BATCH_INLINE", "1")
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_HTTP_JSON_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_SQLITE_CONFIG", raising=False)
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_MANIFEST_CONFIG", raising=False)
    library = create_local_copy(zotero_fixture, name="Rehearsal Validation Target")
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/retrieval/rehearsal/validate?replace_existing=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["setup"]["applied"] is True
    assert payload["seed_queries"] == ["robot catalyst", "graph protein", "spectroscopy battery"]
    planned_queries = [item["query"] for item in payload["query_plan"]["queries"]]
    assert payload["queries"] == planned_queries
    assert len(planned_queries) >= 3
    assert "robot catalyst" in payload["query_plan"]["query_text"]
    assert "robot catalyst benchmark" in payload["query_plan"]["query_text"]
    assert "robot catalyst dataset" in payload["query_plan"]["query_text"]
    assert "robot catalyst model" in payload["query_plan"]["query_text"]
    assert "robot catalyst screening" in payload["query_plan"]["query_text"]
    assert "graph protein" not in payload["query_plan"]["query_text"]
    assert "spectroscopy battery" not in payload["query_plan"]["query_text"]
    assert payload["sources"] == ["localfile", "sqlite", "manifest"]
    assert payload["readiness"]["status"] == "ready"
    assert payload["readiness"]["summary"]["previewed_internal_count"] == 3
    job = payload["job"]
    assert job["status"] == "completed"
    assert job["total_queries"] == len(planned_queries)
    assert job["completed_queries"] == len(planned_queries)
    assert job["failed_queries"] == 0
    assert job["total_candidates"] >= 1
    onboarding = payload["onboarding"]
    assert onboarding["summary"]["batch_validation_status"] == "passed"
    assert onboarding["summary"]["batch_required_query_count"] == len(planned_queries)
    assert onboarding["summary"]["batch_covered_query_count"] == len(planned_queries)
    assert onboarding["summary"]["import_readiness_status"] == "passed"
    assert onboarding["summary"]["import_readiness_ready_candidate_count"] >= 1
    assert set(onboarding["batch_validation"]["validated_sources"]) == {"localfile", "sqlite", "manifest"}
    assert onboarding["batch_validation"]["completed_queries"] == len(planned_queries)
    assert onboarding["batch_validation"]["latest_report_endpoint"] == f"/retrieval/batches/{job['job_id']}/report"
    assert onboarding["import_readiness"]["status"] == "passed"
    assert onboarding["import_readiness"]["checked_candidate_count"] >= 1
    artifacts = payload["artifacts"]
    assert artifacts["query_plan"].startswith("/retrieval/query-plan?seed_query=robot+catalyst")
    assert artifacts["query_plan_report"].startswith(
        "/retrieval/query-plan/report?format=markdown&seed_query=robot+catalyst"
    )
    assert artifacts["batch_report"] == f"/retrieval/batches/{job['job_id']}/report"
    assert artifacts["batch_source_csv"] == f"/retrieval/batches/{job['job_id']}/report?format=csv&scope=sources"
    assert artifacts["onboarding_package"].startswith("/retrieval/onboarding/package?query=robot+catalyst")
    validation_summary = payload["validation_summary"]
    assert validation_summary["status"] == "passed"
    assert validation_summary["query_count"] == len(planned_queries)
    assert validation_summary["source_count"] == 3
    assert validation_summary["completed_queries"] == len(planned_queries)
    assert validation_summary["failed_queries"] == 0
    assert validation_summary["total_candidates"] >= 1
    assert validation_summary["batch_validation_status"] == "passed"
    assert set(validation_summary["validated_sources"]) == {"localfile", "sqlite", "manifest"}
    assert validation_summary["artifact_count"] >= 8
    assert payload["validation_gates"] == validation_summary["gates"]
    gates_by_name = {gate["name"]: gate for gate in validation_summary["gates"]}
    assert gates_by_name["setup_sources"]["status"] == "passed"
    assert gates_by_name["readiness"]["status"] == "passed"
    assert gates_by_name["batch_validation"]["status"] == "passed"
    assert gates_by_name["import_readiness"]["status"] == "passed"
    assert gates_by_name["batch_validation"]["artifacts"] == [
        f"/retrieval/batches/{job['job_id']}/report",
        f"/retrieval/batches/{job['job_id']}/report?format=csv&scope=sources",
    ]
    assert gates_by_name["onboarding"]["status"] == "passed"

    package_response = client.get(f"/api/library/{library['library_id']}{artifacts['onboarding_package']}")
    assert package_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package_response.data)) as archive:
        names = set(archive.namelist())
        assert "README.md" in names
        assert "manifest.json" in names
        assert "query-plan/retrieval-query-plan.md" in names
        assert "query-plan/retrieval-query-plan.csv" in names
        assert "query-plan/retrieval-query-plan.json" in names
        assert "source-setup/retrieval-source-setup-report.md" in names
        assert "field-map/local-files/retrieval-local-files-field-map-report.md" in names
        assert "field-map/sqlite/retrieval-sqlite-field-map-report.md" in names
        assert "field-map/manifest/retrieval-manifest-field-map-report.md" in names
        assert f"batch/{job['job_id']}-report.md" in names
        assert f"batch/{job['job_id']}-report-sources.csv" in names
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["source_setup"]["configured_count"] >= 3
        assert {entry["source"] for entry in manifest["field_map_reports"]} == {"localfile", "sqlite", "manifest"}


def test_retrieval_config_bundle_exports_redacted_configs_and_imports_safe_entries(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("WEB_LIBRARY_RETRIEVAL_LOCAL_PATHS", raising=False)
    source_library = create_read_only_source(zotero_fixture, name="Bundle Source")
    target_library = create_local_copy(zotero_fixture, name="Bundle Target")
    local_csv = tmp_path / "bundle.csv"
    local_csv.write_text(
        "title,doi\nBundle Config Dataset,10.6060/BUNDLE\n",
        encoding="utf-8",
    )
    client = create_app().test_client()
    assert (
        client.post(
            f"/api/library/{source_library['library_id']}/retrieval/local-files",
            json={"paths": [str(local_csv)], "field_map": {"title": "title", "doi": "doi"}},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{source_library['library_id']}/retrieval/http-json",
            json={
                "config": {
                    "label": "Bundle API",
                    "url_template": "https://bundle.example.test/search?q={query}",
                    "items_path": "results",
                    "headers": {"Authorization": "Bearer direct-secret-token", "X-Team": "${ENV:TEAM_NAME}"},
                    "field_map": {"title": "title", "doi": "doi"},
                }
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/library/{source_library['library_id']}/retrieval/manifest",
            json={
                "config": {
                    "label": "Bundle Manifest",
                    "manifest_url": "https://bundle.example.test/manifest.json",
                    "items_path": "items",
                    "auth": {"type": "bearer_env", "env": "BUNDLE_MANIFEST_TOKEN"},
                    "field_map": {"title": "title", "doi": "doi"},
                }
            },
        ).status_code
        == 200
    )

    response = client.get(f"/api/library/{source_library['library_id']}/retrieval/config-bundle")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    bundle = payload["bundle"]
    assert bundle["schema"] == "web-library.retrieval-config-bundle/v1"
    assert bundle["redacted"] is True
    assert bundle["sources"]["localfile"]["paths"] == [str(local_csv)]
    assert bundle["sources"]["localfile"]["config"]["field_map"] == {"title": "title", "doi": "doi"}
    http_config = bundle["sources"]["httpjson"]["config"]
    assert http_config["headers"]["Authorization"] == "__REDACTED__"
    assert http_config["headers"]["X-Team"] == "${ENV:TEAM_NAME}"
    manifest_config = bundle["sources"]["manifest"]["config"]
    assert manifest_config["auth"]["env"] == "BUNDLE_MANIFEST_TOKEN"
    assert "httpjson" in bundle["redacted_sources"]

    download_response = client.get(f"/api/library/{source_library['library_id']}/retrieval/config-bundle/download")
    assert download_response.status_code == 200
    assert download_response.headers["Content-Type"].startswith("application/json")
    assert "retrieval-config-bundle.json" in download_response.headers["Content-Disposition"]

    dry_run_response = client.post(
        f"/api/library/{target_library['library_id']}/retrieval/config-bundle?dry_run=1",
        json={"bundle": bundle},
    )
    assert dry_run_response.status_code == 200
    dry_run_payload = dry_run_response.get_json()
    dry_run_sources = {item["source"] for item in dry_run_payload["applied"]}
    dry_run_skipped = {item["source"]: item["reason"] for item in dry_run_payload["skipped"]}
    assert dry_run_payload["dry_run"] is True
    assert dry_run_sources == {"localfile", "manifest"}
    assert {item["action"] for item in dry_run_payload["applied"]} == {"would_apply"}
    assert dry_run_skipped["httpjson"] == "config contains redacted values"
    target_local_after_dry_run = client.get(
        f"/api/library/{target_library['library_id']}/retrieval/local-files"
    ).get_json()
    assert target_local_after_dry_run["paths"] == []
    assert target_local_after_dry_run["field_map"] == {}
    target_manifest_after_dry_run = client.get(
        f"/api/library/{target_library['library_id']}/retrieval/manifest"
    ).get_json()
    assert target_manifest_after_dry_run["summary"]["configured"] is False

    import_response = client.post(
        f"/api/library/{target_library['library_id']}/retrieval/config-bundle",
        json={"bundle": bundle},
    )
    assert import_response.status_code == 200
    import_payload = import_response.get_json()
    applied_sources = {item["source"] for item in import_payload["applied"]}
    skipped = {item["source"]: item["reason"] for item in import_payload["skipped"]}
    assert import_payload["dry_run"] is False
    assert applied_sources == {"localfile", "manifest"}
    assert {item["action"] for item in import_payload["applied"]} == {"applied"}
    assert skipped["httpjson"] == "config contains redacted values"
    target_local = client.get(f"/api/library/{target_library['library_id']}/retrieval/local-files").get_json()
    assert target_local["paths"] == [str(local_csv)]
    assert target_local["field_map"] == {"title": "title", "doi": "doi"}
    target_manifest = client.get(f"/api/library/{target_library['library_id']}/retrieval/manifest").get_json()
    assert target_manifest["summary"]["configured"] is True
    target_http = client.get(f"/api/library/{target_library['library_id']}/retrieval/http-json").get_json()
    assert target_http["summary"]["configured"] is False

    safe_bundle = json.loads(json.dumps(bundle))
    safe_bundle["sources"]["httpjson"]["config"]["headers"]["Authorization"] = "${ENV:BUNDLE_API_AUTH}"
    safe_import_response = client.post(
        f"/api/library/{target_library['library_id']}/retrieval/config-bundle",
        json={"bundle": safe_bundle, "sources": ["httpjson"]},
    )
    assert safe_import_response.status_code == 200
    assert safe_import_response.get_json()["applied"][0]["source"] == "httpjson"
    target_http_after = client.get(f"/api/library/{target_library['library_id']}/retrieval/http-json").get_json()
    assert target_http_after["summary"]["configured"] is True


def test_retrieval_config_bundle_skips_unsupported_field_map_targets(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    target_library = create_local_copy(zotero_fixture, name="Invalid Field Map Bundle Target")
    local_csv = tmp_path / "invalid-bundle.csv"
    local_csv.write_text("title,doi\nInvalid Bundle Dataset,10.6060/INVALID-BUNDLE\n", encoding="utf-8")
    client = create_app().test_client()
    bundle = {
        "schema": "web-library.retrieval-config-bundle/v1",
        "sources": {
            "localfile": {
                "config": {
                    "paths": [str(local_csv)],
                    "field_map": {"title": "title", "bad_target": "doi"},
                }
            },
            "manifest": {
                "config": {
                    "label": "Valid Bundle Manifest",
                    "manifest_url": "https://bundle.example.test/valid-manifest.json",
                    "items_path": "items",
                    "field_map": {"title": "title", "doi": "doi"},
                }
            }
        },
    }

    dry_run_response = client.post(
        f"/api/library/{target_library['library_id']}/retrieval/config-bundle?dry_run=1",
        json={"bundle": bundle},
    )

    assert dry_run_response.status_code == 200
    dry_run_payload = dry_run_response.get_json()
    dry_run_applied = {item["source"]: item for item in dry_run_payload["applied"]}
    dry_run_skipped = {item["source"]: item["reason"] for item in dry_run_payload["skipped"]}
    assert dry_run_payload["dry_run"] is True
    assert dry_run_applied["manifest"]["action"] == "would_apply"
    assert "invalid config:" in dry_run_skipped["localfile"]
    assert "bad_target" in dry_run_skipped["localfile"]
    target_local = client.get(f"/api/library/{target_library['library_id']}/retrieval/local-files").get_json()
    assert target_local["paths"] == []
    assert target_local["field_map"] == {}
    target_manifest_after_dry_run = client.get(
        f"/api/library/{target_library['library_id']}/retrieval/manifest"
    ).get_json()
    assert target_manifest_after_dry_run["summary"]["configured"] is False

    import_response = client.post(
        f"/api/library/{target_library['library_id']}/retrieval/config-bundle",
        json={"bundle": bundle},
    )

    assert import_response.status_code == 200
    import_payload = import_response.get_json()
    applied = {item["source"]: item for item in import_payload["applied"]}
    skipped = {item["source"]: item["reason"] for item in import_payload["skipped"]}
    assert import_payload["dry_run"] is False
    assert applied["manifest"]["action"] == "applied"
    assert "bad_target" in skipped["localfile"]
    target_local_after_import = client.get(
        f"/api/library/{target_library['library_id']}/retrieval/local-files"
    ).get_json()
    assert target_local_after_import["paths"] == []
    assert target_local_after_import["field_map"] == {}
    target_manifest = client.get(f"/api/library/{target_library['library_id']}/retrieval/manifest").get_json()
    assert target_manifest["summary"]["configured"] is True


def test_retrieval_search_api_marks_existing_identifier_matches(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    ZoteroRepository(library).import_metadata_items(
        [
            ImportedItem(
                item_type="journalArticle",
                fields={"title": "Existing Robot Paper", "DOI": "10.4242/existing"},
                identifiers={"doi": "10.4242/existing"},
                source="fixture",
            )
        ]
    )

    def fake_search(query: str, **kwargs):
        return {
            "query": query,
            "sources": ["crossref"],
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": ""}},
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": "10.4242/existing",
                    "title": "Retrieved Robot Paper",
                    "identifiers": {"doi": "10.4242/existing"},
                    "rank_reasons": ["强标识符：DOI"],
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": "Retrieved Robot Paper", "DOI": "10.4242/existing"},
                        "identifiers": {"doi": "10.4242/existing"},
                        "source": "Crossref",
                    },
                }
            ],
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot", "sources": ["crossref"], "limit": 5},
    )

    assert response.status_code == 200
    candidate = response.get_json()["candidates"][0]
    assert candidate["duplicate_hint"]["status"] == "existing"
    assert candidate["duplicate_hint"]["message"] == "文库已有匹配条目"
    assert candidate["existing_matches"][0]["title"] == "Existing Robot Paper"
    assert candidate["existing_matches"][0]["matched_identifiers"] == [{"kind": "doi", "value": "10.4242/existing"}]
    assert candidate["rank_reasons"][0] == "文库已有匹配"


def test_retrieval_search_api_marks_weak_similarity_matches(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    ZoteroRepository(library).import_metadata_items(
        [
            ImportedItem(
                item_type="journalArticle",
                fields={"title": "Robot Manipulation with Vision Language Models", "date": "2026"},
                creators=[],
                source="fixture",
            )
        ]
    )

    def fake_search(query: str, **kwargs):
        return {
            "query": query,
            "sources": ["crossref"],
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": ""}},
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": "weak-1",
                    "title": "Robot Manipulation With Vision-Language Models",
                    "year": "2026",
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": "Robot Manipulation With Vision-Language Models", "date": "2026"},
                        "source": "Crossref",
                    },
                }
            ],
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "robot", "sources": ["crossref"], "limit": 5},
    )

    assert response.status_code == 200
    candidate = response.get_json()["candidates"][0]
    assert "duplicate_hint" not in candidate
    assert candidate["similarity_hint"]["status"] == "similar"
    assert candidate["weak_similarity_matches"][0]["title"] == "Robot Manipulation with Vision Language Models"
    assert candidate["rank_reasons"][0] == "文库疑似相似"


def test_retrieval_search_api_rejects_empty_query(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.post(f"/api/library/{library['library_id']}/retrieval/search", json={"query": " "})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_retrieval_candidates_evaluate_scores_existing_candidates(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    calls: list[tuple[str, str, bool]] = []

    def fake_evaluate(library_id: str, query: str, candidates: list[dict], **kwargs):
        calls.append((library_id, query, kwargs["use_ai_evaluation"]))
        for index, candidate in enumerate(candidates):
            decision = "recommend" if candidate["title"] == "Relevant Candidate" else "review"
            candidate["ai_evaluation"] = {
                "status": "evaluated",
                "score_source": "ai_model",
                "decision": decision,
                "auto_select": decision == "recommend",
                "final_confidence_score": 0.91 if decision == "recommend" else 0.45,
                "reason": "AI rerank test",
            }
            candidate["rank"] = index + 1
        candidates.sort(key=lambda candidate: candidate["ai_evaluation"]["final_confidence_score"], reverse=True)
        return {
            "status": "evaluated",
            "score_source": "ai_model",
            "score_framework": "ai_rubric_v1",
            "auto_selected_count": 1,
            "decision_counts": {"recommend": 1, "review": 1, "reject": 0},
        }

    monkeypatch.setattr(web, "evaluate_retrieval_candidates_with_ai", fake_evaluate)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/candidates/evaluate",
        json={
            "query": "robot",
            "candidates": [
                {"title": "Less Relevant Candidate", "source": "crossref"},
                {"title": "Relevant Candidate", "source": "arxiv"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert calls == [(library["library_id"], "robot", True)]
    assert payload["ai_evaluation_summary"]["score_source"] == "ai_model"
    assert payload["candidates"][0]["title"] == "Relevant Candidate"
    assert payload["candidates"][0]["ai_evaluation"]["auto_select"] is True


def test_retrieval_candidates_evaluate_limits_manual_ai_scoring(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    calls: list[int] = []

    def fake_evaluate(library_id: str, query: str, candidates: list[dict], **kwargs):
        calls.append(len(candidates))
        for candidate in candidates:
            candidate["ai_evaluation"] = {
                "status": "evaluated",
                "score_source": "ai_model",
                "decision": "recommend",
                "auto_select": True,
                "final_confidence_score": 90,
            }
        return {
            "status": "evaluated",
            "score_source": "ai_model",
            "score_framework": "ai_rubric_v1",
            "auto_selected_count": len(candidates),
            "decision_counts": {"recommend": len(candidates), "review": 0, "reject": 0},
        }

    monkeypatch.setattr(web, "evaluate_retrieval_candidates_with_ai", fake_evaluate)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/candidates/evaluate",
        json={
            "query": "robot",
            "candidates": [{"title": f"Candidate {index}", "source": "crossref"} for index in range(12)],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert calls == [10]
    assert payload["ai_evaluation_summary"]["status"] == "partial"
    assert payload["ai_evaluation_summary"]["score_source"] == "mixed_ai_rules"
    assert payload["ai_evaluation_summary"]["partial_reason"] == "candidate_limit"
    assert payload["ai_evaluation_summary"]["skipped_candidate_count"] == 2
    assert len(payload["candidates"]) == 12
    assert sum(1 for candidate in payload["candidates"] if candidate["ai_evaluation"]["status"] == "skipped") == 2


def test_retrieval_ai_scoring_job_runs_inline_and_can_be_restored(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.setenv("WEB_LIBRARY_RETRIEVAL_AI_SCORING_INLINE", "1")
    library = create_local_copy(zotero_fixture)
    app_store.set_preference(
        library["library_id"],
        web.API_CONFIG_PREFERENCE_KEY,
        {"model": {"model": "gpt-5.5", "base_url": "https://ai-pixel.online", "api_key": "secret"}, "code_sources": {}},
    )
    calls: list[str] = []

    def fake_evaluate(library_id: str, query: str, candidates: list[dict], **kwargs):
        calls.append(candidates[0]["title"])
        decision = "recommend" if candidates[0]["title"] == "High Confidence" else "review"
        candidates[0]["ai_evaluation"] = {
            "status": "evaluated",
            "score_source": "ai_model",
            "score_framework": "ai_rubric_v1",
            "decision": decision,
            "auto_select": decision == "recommend",
            "final_confidence_score": 95 if decision == "recommend" else 65,
            "reason": "后台 AI 评分测试",
        }
        return {
            "status": "evaluated",
            "score_source": "ai_model",
            "score_framework": "ai_rubric_v1",
            "auto_selected_count": 1 if decision == "recommend" else 0,
            "decision_counts": {"recommend": 1 if decision == "recommend" else 0, "review": 0 if decision == "recommend" else 1, "reject": 0},
        }

    monkeypatch.setattr(web, "evaluate_retrieval_candidates_with_ai", fake_evaluate)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/ai-scoring-jobs",
        json={
            "query": "robot",
            "candidates": [
                {"title": "Low Confidence", "source": "crossref", "confidence": 0.2},
                {"title": "High Confidence", "source": "arxiv", "confidence": 0.9},
            ],
        },
    )

    assert response.status_code == 200
    job = response.get_json()["job"]
    assert job["status"] == "completed"
    assert calls == ["High Confidence", "Low Confidence"]
    assert job["completed_count"] == 2
    assert job["summary"]["score_source"] == "ai_model"
    assert job["summary"]["auto_selected_count"] == 1
    assert all(candidate["ai_evaluation"]["score_source"] == "ai_model" for candidate in job["candidates"])
    latest = client.get(f"/api/library/{library['library_id']}/retrieval/ai-scoring-jobs/latest").get_json()["job"]
    assert latest["job_id"] == job["job_id"]
    assert latest["status"] == "completed"


def test_imported_items_from_retrieval_candidates_accepts_search_payload() -> None:
    items = imported_items_from_candidates(
        [
            {
                "source": "crossref",
                "title": "Fallback Title",
                "item": {
                    "item_type": "journalArticle",
                    "fields": {"DOI": "10.1234/demo"},
                    "creators": [{"name": "Ada Lovelace"}],
                    "tags": ["robotics"],
                    "identifiers": {"doi": "10.1234/demo"},
                    "source": "Crossref",
                },
            }
        ]
    )

    assert len(items) == 1
    item = items[0]
    assert item.fields["title"] == "Fallback Title"
    assert item.identifiers["doi"] == "10.1234/demo"
    assert item.creators[0].first_name == "Ada"
    assert item.creators[0].last_name == "Lovelace"
    assert item.tags == ["robotics"]


def test_imported_items_from_candidates_backfills_top_level_metadata() -> None:
    items = imported_items_from_candidates(
        [
            {
                "source": "pubmed",
                "title": "Top Level Title",
                "abstract": "Top level abstract.",
                "landing_url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                "identifiers": {"doi": "https://doi.org/10.4242/TOP", "pmid": "12345678"},
                "creators": [{"name": "Ada Lovelace"}],
                "item": {
                    "item_type": "journalArticle",
                    "fields": {},
                    "source": "PubMed",
                },
            }
        ]
    )

    item = items[0]
    assert item.fields["title"] == "Top Level Title"
    assert item.fields["abstractNote"] == "Top level abstract."
    assert item.fields["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert item.fields["DOI"] == "10.4242/top"
    assert "PMID: 12345678" in item.fields["extra"]
    assert item.identifiers == {"doi": "10.4242/top", "pmid": "12345678"}
    assert item.creators[0].last_name == "Lovelace"


def test_imported_items_from_candidates_ignores_null_payload_fields_when_backfilling() -> None:
    items = imported_items_from_candidates(
        [
            {
                "source": "datacite",
                "title": "Fallback Dataset Title",
                "abstract": "Fallback abstract.",
                "landing_url": "https://example.test/dataset",
                "identifiers": {"doi": "10.4242/null-fallback"},
                "item": {
                    "item_type": "dataset",
                    "fields": {"title": None, "abstractNote": None, "url": None, "DOI": None},
                    "identifiers": {"doi": None},
                    "source": "DataCite",
                },
            }
        ]
    )

    item = items[0]
    assert item.fields["title"] == "Fallback Dataset Title"
    assert item.fields["abstractNote"] == "Fallback abstract."
    assert item.fields["url"] == "https://example.test/dataset"
    assert item.fields["DOI"] == "10.4242/null-fallback"
    assert "None" not in item.fields.values()


def test_retrieval_import_api_uses_existing_import_pipeline(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/import",
        json={
            "collection_key": "COLL0001",
            "candidates": [
                {
                    "source": "crossref",
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {
                            "title": "Retrieved Paper",
                            "DOI": "10.4242/retrieved",
                            "publicationTitle": "Retrieval Journal",
                            "date": "2026",
                        },
                        "creators": [{"first_name": "Grace", "last_name": "Hopper"}],
                        "identifiers": {"doi": "10.4242/retrieved"},
                        "source": "Crossref",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["created_count"] == 1
    evidence = payload["import_evidence"]
    assert evidence["status"] == "recorded_without_run"
    assert evidence["run_id"] == ""
    assert evidence["run_linked"] is False
    assert evidence["candidate_count"] == 1
    assert evidence["provenance_recorded_count"] == 1
    assert evidence["item_key_count"] == 1
    assert evidence["run_report_markdown_endpoint"] == ""
    assert evidence["summary_report_endpoint"] == (
        f"/api/library/{library['library_id']}/retrieval/summary/report?format=markdown"
    )
    item_key = payload["results"][0]["item_key"]
    item = next(item for item in ZoteroRepository(library).state()["items"] if item["key"] == item_key)
    assert item["title"] == "Retrieved Paper"
    assert item["fields"]["DOI"] == "10.4242/retrieved"
    assert item["creators_display"] == "Grace Hopper"
    assert any(collection["key"] == "COLL0001" for collection in item["collections"])


def test_retrieval_search_run_can_import_by_candidate_ids(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)

    def fake_search(query: str, **kwargs):
        return {
            "query": query,
            "sources": ["crossref"],
            "source_stats": {"crossref": {"ok": True, "count": 1, "error": ""}},
            "candidates": [
                {
                    "source": "crossref",
                    "external_id": "10.5151/cache",
                    "title": "Cached Candidate",
                    "identifiers": {"doi": "10.5151/cache"},
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": "Cached Candidate", "DOI": "10.5151/cache"},
                        "creators": [{"first_name": "Alan", "last_name": "Turing"}],
                        "identifiers": {"doi": "10.5151/cache"},
                        "source": "Crossref",
                    },
                }
            ],
        }

    monkeypatch.setattr(web, "search_retrieval", fake_search)
    client = create_app().test_client()

    search_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/search",
        json={"query": "cache test", "sources": ["crossref"]},
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    candidate_id = search_payload["candidates"][0]["candidate_id"]

    import_response = client.post(
        f"/api/library/{library['library_id']}/retrieval/import",
        json={"run_id": search_payload["run_id"], "candidate_ids": [candidate_id], "collection_key": "COLL0001"},
    )

    assert import_response.status_code == 200
    import_payload = import_response.get_json()
    assert import_payload["created_count"] == 1
    evidence = import_payload["import_evidence"]
    assert evidence["status"] == "recorded"
    assert evidence["run_id"] == search_payload["run_id"]
    assert evidence["candidate_count"] == 1
    assert evidence["result_count"] == 1
    assert evidence["provenance_recorded_count"] == 1
    assert evidence["item_key_count"] == 1
    assert evidence["statuses"] == {"created": 1}
    assert evidence["sources"] == ["crossref"]
    assert evidence["items"][0]["candidate_id"] == candidate_id
    assert evidence["items"][0]["item_key"] == import_payload["results"][0]["item_key"]
    assert evidence["run_report_endpoint"] == f"/api/library/{library['library_id']}/retrieval/runs/{search_payload['run_id']}/report"
    assert evidence["run_report_markdown_endpoint"] == (
        f"/api/library/{library['library_id']}/retrieval/runs/{search_payload['run_id']}/report?format=markdown"
    )
    runs = app_store.recent_retrieval_runs(library["library_id"])
    assert runs[0]["run_id"] == search_payload["run_id"]
    assert runs[0]["candidate_count"] == 1
    assert runs[0]["imported_count"] == 1

    runs_response = client.get(f"/api/library/{library['library_id']}/retrieval/runs")
    assert runs_response.status_code == 200
    runs_payload = runs_response.get_json()
    assert runs_payload["ok"] is True
    assert runs_payload["runs"][0]["run_id"] == search_payload["run_id"]
    assert runs_payload["runs"][0]["candidate_count"] == 1
    assert runs_payload["runs"][0]["imported_count"] == 1
    assert runs_payload["runs"][0]["source_stats"]["crossref"]["count"] == 1

    report_response = client.get(f"/api/library/{library['library_id']}/retrieval/runs/{search_payload['run_id']}/report")
    assert report_response.status_code == 200
    assert report_response.headers["Content-Type"].startswith("text/markdown")
    assert "attachment" in report_response.headers["Content-Disposition"]
    report_text = report_response.get_data(as_text=True)
    assert "# 多源检索报告" in report_text
    assert "cache test" in report_text
    assert "Cached Candidate" in report_text
    assert "created" in report_text
    assert "10.5151/cache" in report_text

    csv_response = client.get(f"/api/library/{library['library_id']}/retrieval/runs/{search_payload['run_id']}/report?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["Content-Type"].startswith("text/csv")
    csv_text = csv_response.get_data(as_text=True)
    assert "rank,candidate_id,source,title,identifiers,confidence,import_status,item_key" in csv_text
    assert "Cached Candidate" in csv_text

    json_response = client.get(f"/api/library/{library['library_id']}/retrieval/runs/{search_payload['run_id']}/report?format=json")
    assert json_response.status_code == 200
    assert json_response.headers["Content-Type"].startswith("application/json")
    json_payload = json_response.get_json()
    assert json_payload["run"]["run_id"] == search_payload["run_id"]
    assert json_payload["candidates"][0]["payload"]["title"] == "Cached Candidate"

    summary_report_response = client.get(f"/api/library/{library['library_id']}/retrieval/summary/report")
    assert summary_report_response.status_code == 200
    assert summary_report_response.headers["Content-Type"].startswith("text/markdown")
    assert "retrieval-summary-report.md" in summary_report_response.headers["Content-Disposition"]
    summary_report_text = summary_report_response.get_data(as_text=True)
    assert "# 多源检索阶段统计报告" in summary_report_text
    assert "| 检索批次 | 1 |" in summary_report_text
    assert "| 导入记录 | 1 |" in summary_report_text
    assert "| crossref | 1 | 1 | 0 | 1 |" in summary_report_text
    assert "| cache test | 1 |" in summary_report_text

    summary_csv_response = client.get(f"/api/library/{library['library_id']}/retrieval/summary/report?format=csv")
    assert summary_csv_response.status_code == 200
    assert summary_csv_response.headers["Content-Type"].startswith("text/csv")
    summary_csv_text = summary_csv_response.get_data(as_text=True)
    assert "section,name,run_count,candidate_count,imported_count,success_count,failure_count,success_rate,import_rate,elapsed_avg_ms,details" in summary_csv_text
    assert "totals,阶段合计,1,1,1,1,0,1.0,1.0" in summary_csv_text
    assert "source,crossref,1,1,,1,0,1.0" in summary_csv_text

    summary_json_response = client.get(f"/api/library/{library['library_id']}/retrieval/summary/report?format=json")
    assert summary_json_response.status_code == 200
    assert summary_json_response.headers["Content-Type"].startswith("application/json")
    summary_json_payload = summary_json_response.get_json()
    assert summary_json_payload["totals"]["run_count"] == 1
    assert summary_json_payload["totals"]["imported_count"] == 1
    assert summary_json_payload["sources"]["crossref"]["candidate_count"] == 1


def test_retrieval_import_api_is_blocked_for_read_only_sources(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_read_only_source(zotero_fixture)
    client = create_app().test_client()

    response = client.post(
        f"/api/library/{library['library_id']}/retrieval/import",
        json={
            "candidates": [
                {
                    "item": {
                        "item_type": "journalArticle",
                        "fields": {"title": "No Write"},
                        "source": "test",
                    }
                }
            ]
        },
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False
