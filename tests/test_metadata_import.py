from __future__ import annotations

import pytest

from zotero_web_library.metadata_import import (
    MetadataImportError,
    normalize_arxiv_id,
    normalize_doi,
    normalize_isbn,
    parse_bibtex,
    parse_csl_json,
    parse_import_text,
    parse_pubmed_xml,
    parse_ris,
)


def test_identifier_normalization_rules() -> None:
    assert normalize_doi("https://doi.org/10.1038/S41586-024-00000-0.") == "10.1038/s41586-024-00000-0"
    assert normalize_isbn("0-306-40615-2") == "9780306406157"
    assert normalize_arxiv_id("https://arxiv.org/abs/2406.09246v2") == "2406.09246"


def test_parse_ris_to_unified_metadata() -> None:
    item = parse_ris(
        """
TY  - JOUR
TI  - Example Paper
AU  - Kim, Moo Jin
PY  - 2024
JO  - Nature
DO  - 10.1234/example
ER  -
"""
    )[0]

    assert item.item_type == "journalArticle"
    assert item.fields["title"] == "Example Paper"
    assert item.identifiers["doi"] == "10.1234/example"
    assert item.creators[0].last_name == "Kim"


def test_parse_bibtex_to_unified_metadata() -> None:
    item = parse_bibtex(
        """
@inproceedings{demo,
  title = {Conference Demo},
  author = {Kim, Moo Jin and Li Fei},
  booktitle = {ICRA},
  year = {2025},
  doi = {10.5555/demo}
}
"""
    )[0]

    assert item.item_type == "conferencePaper"
    assert item.fields["publicationTitle"] == "ICRA"
    assert item.identifiers["doi"] == "10.5555/demo"


def test_parse_csl_json_and_pubmed_xml() -> None:
    csl = parse_csl_json(
        """
[
  {
    "type": "article-journal",
    "title": "CSL Demo",
    "DOI": "10.7777/csl",
    "issued": {"date-parts": [[2026, 1, 2]]},
    "author": [{"given": "Ada", "family": "Lovelace"}]
  }
]
"""
    )[0]
    assert csl.fields["date"] == "2026-1-2"
    assert csl.creators[0].last_name == "Lovelace"

    pubmed = parse_pubmed_xml(
        """
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>PubMed Demo</ArticleTitle>
        <Journal><Title>Journal</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
        <Abstract><AbstractText>Abstract text.</AbstractText></Abstract>
        <AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.8888/pubmed</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""
    )[0]
    assert pubmed.identifiers["pmid"] == "12345678"
    assert pubmed.identifiers["doi"] == "10.8888/pubmed"


def test_auto_import_text_rejects_unknown_content() -> None:
    with pytest.raises(MetadataImportError):
        parse_import_text("这不是引用格式", "auto")
