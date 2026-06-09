from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


class MetadataImportError(ValueError):
    pass


@dataclass
class ImportedCreator:
    first_name: str = ""
    last_name: str = ""
    creator_type: str = "author"


@dataclass
class ImportedItem:
    item_type: str
    fields: dict[str, str] = field(default_factory=dict)
    creators: list[ImportedCreator] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    identifiers: dict[str, str] = field(default_factory=dict)
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_type": self.item_type,
            "fields": self.fields,
            "creators": [creator.__dict__ for creator in self.creators],
            "tags": self.tags,
            "identifiers": self.identifiers,
            "source": self.source,
        }


DOI_RE = re.compile(r"\b(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[^\s\"<>]+)", re.I)
PMID_RE = re.compile(r"\b(?:pmid:\s*)?(\d{5,9})\b", re.I)
PMCID_RE = re.compile(r"\b(PMC\d+)\b", re.I)
ARXIV_RE = re.compile(r"\b(?:arxiv:\s*|https?://arxiv\.org/(?:abs|pdf)/)?([a-z-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?\b", re.I)
ISBN_RE = re.compile(r"\b(?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx]\b")
ADS_BIBCODE_RE = re.compile(r"\b\d{4}[A-Za-z0-9.&]{14}[A-Za-z0-9]\b")


def normalize_doi(value: str) -> str:
    match = DOI_RE.search(str(value or "").strip())
    if not match:
        return ""
    return match.group(1).rstrip(".,;").lower()


def normalize_pmid(value: str) -> str:
    match = PMID_RE.search(str(value or ""))
    return match.group(1) if match else ""


def normalize_pmcid(value: str) -> str:
    match = PMCID_RE.search(str(value or ""))
    return match.group(1).upper() if match else ""


def normalize_arxiv_id(value: str) -> str:
    match = ARXIV_RE.search(str(value or "").strip())
    if not match:
        return ""
    return re.sub(r"v\d+$", "", match.group(1), flags=re.I).lower()


def _isbn_digits(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def _isbn10_to_13(isbn10: str) -> str:
    body = "978" + isbn10[:9]
    total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(body))
    check = (10 - total % 10) % 10
    return f"{body}{check}"


def normalize_isbn(value: str) -> str:
    raw = _isbn_digits(value)
    if len(raw) == 10:
        return _isbn10_to_13(raw)
    if len(raw) == 13:
        return raw
    match = ISBN_RE.search(str(value or ""))
    if not match:
        return ""
    return normalize_isbn(match.group(0))


def normalize_ads_bibcode(value: str) -> str:
    match = ADS_BIBCODE_RE.search(str(value or "").strip())
    return match.group(0) if match else ""


def detect_identifier(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    for key, normalizer in (
        ("doi", normalize_doi),
        ("arxiv", normalize_arxiv_id),
        ("pmcid", normalize_pmcid),
        ("ads_bibcode", normalize_ads_bibcode),
        ("isbn", normalize_isbn),
        ("pmid", normalize_pmid),
    ):
        normalized = normalizer(text)
        if normalized:
            return key, normalized
    raise MetadataImportError("没有识别出 DOI / PMID / arXiv ID / ADS Bibcode / ISBN。")


def _http_get_json(url: str, *, timeout: int = 15) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "zotero-web-library/0.1 (metadata import)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_text(url: str, *, timeout: int = 15) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "zotero-web-library/0.1 (metadata import)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _name_parts(name: str) -> ImportedCreator:
    clean = " ".join(str(name or "").strip().split())
    if not clean:
        return ImportedCreator()
    if "," in clean:
        last, first = [part.strip() for part in clean.split(",", 1)]
        return ImportedCreator(first_name=first, last_name=last)
    parts = clean.split(" ")
    if len(parts) == 1:
        return ImportedCreator(last_name=parts[0])
    return ImportedCreator(first_name=" ".join(parts[:-1]), last_name=parts[-1])


def _crossref_item(message: dict[str, Any], *, source: str = "Crossref") -> ImportedItem:
    fields = {
        "title": " ".join(message.get("title") or []) or "",
        "DOI": normalize_doi(message.get("DOI") or ""),
        "publicationTitle": " ".join(message.get("container-title") or []) or "",
        "abstractNote": re.sub(r"<[^>]+>", " ", message.get("abstract") or "").strip(),
        "url": message.get("URL") or "",
        "publisher": message.get("publisher") or "",
    }
    date_parts = (message.get("published-print") or message.get("published-online") or message.get("issued") or {}).get("date-parts") or []
    if date_parts and date_parts[0]:
        fields["date"] = "-".join(str(part) for part in date_parts[0])
    for key in ("volume", "issue", "page"):
        if message.get(key):
            fields["pages" if key == "page" else key] = str(message[key])
    creators = []
    for author in message.get("author") or []:
        creators.append(ImportedCreator(first_name=author.get("given", ""), last_name=author.get("family", ""), creator_type="author"))
    item_type = "journalArticle"
    if message.get("type") == "proceedings-article":
        item_type = "conferencePaper"
    if message.get("type") == "book":
        item_type = "book"
    identifiers = {"doi": fields["DOI"]} if fields.get("DOI") else {}
    return ImportedItem(item_type=item_type, fields={k: v for k, v in fields.items() if v}, creators=creators, identifiers=identifiers, source=source)


def resolve_doi(doi: str) -> ImportedItem:
    normalized = normalize_doi(doi)
    if not normalized:
        raise MetadataImportError("DOI 格式无效。")
    url = f"https://api.crossref.org/works/{urllib.parse.quote(normalized)}"
    try:
        data = _http_get_json(url)
        return _crossref_item(data["message"], source="Crossref REST")
    except Exception as exc:  # noqa: BLE001 - external APIs can fail in many ways
        raise MetadataImportError(f"DOI 查询失败：{exc}") from exc


def parse_pubmed_xml(text: str) -> list[ImportedItem]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise MetadataImportError(f"PubMed XML 解析失败：{exc}") from exc
    values: list[ImportedItem] = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("./MedlineCitation")
        article_node = medline.find("./Article") if medline is not None else None
        if article_node is None:
            continue
        fields: dict[str, str] = {}
        title = "".join(article_node.findtext("./ArticleTitle") or "").strip()
        if title:
            fields["title"] = title
        journal = article_node.find("./Journal")
        if journal is not None:
            fields["publicationTitle"] = journal.findtext("./Title") or journal.findtext("./ISOAbbreviation") or ""
            year = journal.findtext("./JournalIssue/PubDate/Year") or journal.findtext("./JournalIssue/PubDate/MedlineDate") or ""
            if year:
                fields["date"] = year[:4]
        abstract = " ".join("".join(node.itertext()).strip() for node in article_node.findall("./Abstract/AbstractText") if "".join(node.itertext()).strip())
        if abstract:
            fields["abstractNote"] = abstract
        ids: dict[str, str] = {}
        pmid = medline.findtext("./PMID") if medline is not None else ""
        if pmid:
            ids["pmid"] = normalize_pmid(pmid)
            fields["extra"] = f"PMID: {ids['pmid']}"
        for node in article.findall(".//ArticleId"):
            id_type = (node.attrib.get("IdType") or "").lower()
            if id_type == "doi":
                ids["doi"] = normalize_doi(node.text or "")
                fields["DOI"] = ids["doi"]
            if id_type == "pmc":
                ids["pmcid"] = normalize_pmcid(node.text or "")
                fields["extra"] = "\n".join(filter(None, [fields.get("extra", ""), f"PMCID: {ids['pmcid']}"]))
        creators = []
        for author in article_node.findall("./AuthorList/Author"):
            creators.append(ImportedCreator(first_name=author.findtext("./ForeName") or "", last_name=author.findtext("./LastName") or ""))
        values.append(ImportedItem(item_type="journalArticle", fields={k: v for k, v in fields.items() if v}, creators=creators, identifiers={k: v for k, v in ids.items() if v}, source="PubMed XML"))
    if not values:
        raise MetadataImportError("PubMed XML 中没有可导入的条目。")
    return values


def resolve_pmid(pmid: str) -> ImportedItem:
    normalized = normalize_pmid(pmid)
    if not normalized:
        raise MetadataImportError("PMID 格式无效。")
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={normalized}&retmode=xml"
    return parse_pubmed_xml(_http_get_text(url))[0]


def parse_arxiv_atom(text: str) -> list[ImportedItem]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise MetadataImportError(f"arXiv XML 解析失败：{exc}") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    values: list[ImportedItem] = []
    for entry in root.findall("atom:entry", ns):
        arxiv_url = entry.findtext("atom:id", default="", namespaces=ns)
        arxiv_id = normalize_arxiv_id(arxiv_url)
        fields = {
            "title": " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split()),
            "abstractNote": " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split()),
            "date": (entry.findtext("atom:published", default="", namespaces=ns) or "")[:10],
            "repository": "arXiv",
            "url": arxiv_url,
            "extra": f"arXiv: {arxiv_id}" if arxiv_id else "",
        }
        creators = [_name_parts(author.findtext("atom:name", default="", namespaces=ns) or "") for author in entry.findall("atom:author", ns)]
        values.append(ImportedItem(item_type="preprint", fields={k: v for k, v in fields.items() if v}, creators=[c for c in creators if c.last_name], identifiers={"arxiv": arxiv_id} if arxiv_id else {}, source="arXiv API"))
    if not values:
        raise MetadataImportError("arXiv API 没有返回可导入条目。")
    return values


def resolve_arxiv(arxiv_id: str) -> ImportedItem:
    normalized = normalize_arxiv_id(arxiv_id)
    if not normalized:
        raise MetadataImportError("arXiv ID 格式无效。")
    url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(normalized)}"
    return parse_arxiv_atom(_http_get_text(url))[0]


def resolve_ads_bibcode(bibcode: str) -> ImportedItem:
    normalized = normalize_ads_bibcode(bibcode)
    if not normalized:
        raise MetadataImportError("ADS Bibcode 格式无效。")
    raise MetadataImportError("ADS Bibcode v1 需要 ADS API token；当前仅完成识别与去重，不创建半成品。")


def resolve_isbn(isbn: str) -> ImportedItem:
    normalized = normalize_isbn(isbn)
    if not normalized:
        raise MetadataImportError("ISBN 格式无效。")
    url = f"https://openlibrary.org/isbn/{normalized}.json"
    try:
        data = _http_get_json(url)
    except Exception as exc:  # noqa: BLE001
        raise MetadataImportError(f"ISBN 查询失败：{exc}") from exc
    fields = {
        "title": data.get("title") or "",
        "date": str(data.get("publish_date") or ""),
        "publisher": " / ".join(data.get("publishers") or []),
        "ISBN": normalized,
        "url": f"https://openlibrary.org/isbn/{normalized}",
    }
    return ImportedItem(item_type="book", fields={k: v for k, v in fields.items() if v}, identifiers={"isbn": normalized}, source="OpenLibrary ISBN")


def resolve_identifier(value: str) -> ImportedItem:
    kind, normalized = detect_identifier(value)
    if kind == "doi":
        return resolve_doi(normalized)
    if kind == "pmid":
        return resolve_pmid(normalized)
    if kind == "arxiv":
        return resolve_arxiv(normalized)
    if kind == "ads_bibcode":
        return resolve_ads_bibcode(normalized)
    if kind == "isbn":
        return resolve_isbn(normalized)
    raise MetadataImportError("未知标识符类型。")


RIS_TYPE_MAP = {
    "JOUR": "journalArticle",
    "CONF": "conferencePaper",
    "CPAPER": "conferencePaper",
    "BOOK": "book",
    "CHAP": "bookSection",
    "THES": "thesis",
    "RPRT": "report",
    "ELEC": "webpage",
}


def _finish_ris_record(record: dict[str, list[str]]) -> ImportedItem | None:
    if not record:
        return None
    fields: dict[str, str] = {}
    fields["title"] = (record.get("TI") or record.get("T1") or [""])[0]
    fields["publicationTitle"] = (record.get("JO") or record.get("JF") or record.get("T2") or [""])[0]
    fields["date"] = (record.get("PY") or record.get("Y1") or [""])[0]
    fields["DOI"] = normalize_doi(" ".join(record.get("DO") or []))
    fields["ISBN"] = normalize_isbn(" ".join(record.get("SN") or []))
    fields["url"] = (record.get("UR") or [""])[0]
    fields["abstractNote"] = " ".join(record.get("AB") or [])
    identifiers = {}
    if fields.get("DOI"):
        identifiers["doi"] = fields["DOI"]
    if fields.get("ISBN"):
        identifiers["isbn"] = fields["ISBN"]
    creators = [_name_parts(name) for name in (record.get("AU") or record.get("A1") or [])]
    return ImportedItem(
        item_type=RIS_TYPE_MAP.get((record.get("TY") or [""])[0].upper(), "document"),
        fields={k: v for k, v in fields.items() if v},
        creators=[creator for creator in creators if creator.last_name],
        identifiers=identifiers,
        source="RIS",
    )


def parse_ris(text: str) -> list[ImportedItem]:
    records: list[ImportedItem] = []
    current: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Z0-9]{2})  -\s?(.*)$", line.rstrip())
        if not match:
            continue
        tag, value = match.group(1), match.group(2).strip()
        if tag == "TY":
            current = {"TY": [value]}
            continue
        if tag == "ER":
            item = _finish_ris_record(current)
            if item:
                records.append(item)
            current = {}
            continue
        current.setdefault(tag, []).append(value)
    item = _finish_ris_record(current)
    if item:
        records.append(item)
    if not records:
        raise MetadataImportError("没有识别出 RIS 条目。")
    return records


BIB_TYPE_MAP = {
    "article": "journalArticle",
    "inproceedings": "conferencePaper",
    "conference": "conferencePaper",
    "book": "book",
    "inbook": "bookSection",
    "incollection": "bookSection",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "misc": "document",
}


def _split_bib_entries(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for match in re.finditer(r"@(\w+)\s*\{", text):
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        entries.append((match.group(1).lower(), text[start : index - 1]))
    return entries


def _parse_bib_fields(body: str) -> dict[str, str]:
    _, _, payload = body.partition(",")
    fields: dict[str, str] = {}
    for match in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)", payload, re.S):
        value = match.group(2).strip().strip(",")
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fields[match.group(1).lower()] = re.sub(r"\s+", " ", value).strip()
    return fields


def parse_bibtex(text: str) -> list[ImportedItem]:
    records: list[ImportedItem] = []
    for entry_type, body in _split_bib_entries(text):
        data = _parse_bib_fields(body)
        fields = {
            "title": data.get("title", ""),
            "date": data.get("year", ""),
            "publicationTitle": data.get("journal") or data.get("booktitle") or "",
            "DOI": normalize_doi(data.get("doi", "")),
            "ISBN": normalize_isbn(data.get("isbn", "")),
            "url": data.get("url", ""),
            "abstractNote": data.get("abstract", ""),
            "pages": data.get("pages", ""),
            "volume": data.get("volume", ""),
            "issue": data.get("number", ""),
        }
        identifiers = {}
        if fields.get("DOI"):
            identifiers["doi"] = fields["DOI"]
        if fields.get("ISBN"):
            identifiers["isbn"] = fields["ISBN"]
        creators = [_name_parts(name) for name in re.split(r"\s+and\s+", data.get("author", ""), flags=re.I) if name.strip()]
        records.append(
            ImportedItem(
                item_type=BIB_TYPE_MAP.get(entry_type, "document"),
                fields={k: v for k, v in fields.items() if v},
                creators=[creator for creator in creators if creator.last_name],
                identifiers=identifiers,
                source="BibTeX",
            )
        )
    if not records:
        raise MetadataImportError("没有识别出 BibTeX 条目。")
    return records


CSL_TYPE_MAP = {
    "article-journal": "journalArticle",
    "paper-conference": "conferencePaper",
    "book": "book",
    "chapter": "bookSection",
    "thesis": "thesis",
    "report": "report",
    "webpage": "webpage",
}


def parse_csl_json(text: str) -> list[ImportedItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataImportError(f"CSL JSON 解析失败：{exc}") from exc
    entries = data if isinstance(data, list) else [data]
    records: list[ImportedItem] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fields = {
            "title": entry.get("title") or "",
            "publicationTitle": entry.get("container-title") or "",
            "DOI": normalize_doi(entry.get("DOI") or ""),
            "ISBN": normalize_isbn(entry.get("ISBN") or ""),
            "url": entry.get("URL") or "",
            "abstractNote": entry.get("abstract") or "",
        }
        issued = entry.get("issued", {}).get("date-parts") if isinstance(entry.get("issued"), dict) else None
        if issued and issued[0]:
            fields["date"] = "-".join(str(part) for part in issued[0])
        identifiers = {}
        if fields.get("DOI"):
            identifiers["doi"] = fields["DOI"]
        if fields.get("ISBN"):
            identifiers["isbn"] = fields["ISBN"]
        creators = []
        for author in entry.get("author") or []:
            creators.append(ImportedCreator(first_name=author.get("given", ""), last_name=author.get("family", "")))
        records.append(
            ImportedItem(
                item_type=CSL_TYPE_MAP.get(entry.get("type"), "document"),
                fields={k: v for k, v in fields.items() if v},
                creators=creators,
                identifiers=identifiers,
                source="CSL JSON",
            )
        )
    if not records:
        raise MetadataImportError("CSL JSON 中没有可导入条目。")
    return records


def parse_import_text(text: str, fmt: str = "auto") -> list[ImportedItem]:
    value = str(text or "").strip()
    if not value:
        raise MetadataImportError("导入文本不能为空。")
    normalized = str(fmt or "auto").strip().lower().replace("-", "_")
    parsers = {
        "ris": parse_ris,
        "bibtex": parse_bibtex,
        "bib": parse_bibtex,
        "csl_json": parse_csl_json,
        "json": parse_csl_json,
        "pubmed_xml": parse_pubmed_xml,
        "xml": parse_pubmed_xml,
    }
    if normalized != "auto":
        parser = parsers.get(normalized)
        if not parser:
            raise MetadataImportError("未知导入格式。")
        return parser(value)
    errors: list[str] = []
    for parser in (parse_csl_json, parse_pubmed_xml, parse_ris, parse_bibtex):
        try:
            return parser(value)
        except MetadataImportError as exc:
            errors.append(str(exc))
    raise MetadataImportError("自动识别失败：" + "；".join(errors[:2]))
