from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import datetime
from typing import Any


class CitationExportError(ValueError):
    pass


EXPORT_FORMATS = {
    "bibtex": {"extension": "bib", "mime": "text/x-bibtex; charset=utf-8", "label": "BibTeX"},
    "biblatex": {"extension": "bib", "mime": "text/x-bibtex; charset=utf-8", "label": "BibLaTeX"},
    "ris": {"extension": "ris", "mime": "application/x-research-info-systems; charset=utf-8", "label": "RIS"},
    "csl_json": {"extension": "csl.json", "mime": "application/json; charset=utf-8", "label": "CSL JSON"},
    "csv": {"extension": "csv", "mime": "text/csv; charset=utf-8", "label": "CSV"},
}

BIBTEX_TYPE_MAP = {
    "book": "book",
    "bookSection": "incollection",
    "journalArticle": "article",
    "magazineArticle": "article",
    "newspaperArticle": "article",
    "thesis": "phdthesis",
    "letter": "misc",
    "manuscript": "unpublished",
    "patent": "patent",
    "interview": "misc",
    "film": "misc",
    "artwork": "misc",
    "webpage": "misc",
    "conferencePaper": "inproceedings",
    "report": "techreport",
    "preprint": "misc",
    "dataset": "misc",
    "computerProgram": "misc",
}

BIBLATEX_TYPE_MAP = {
    "book": "book",
    "bookSection": "incollection",
    "journalArticle": "article",
    "magazineArticle": "article",
    "newspaperArticle": "article",
    "thesis": "thesis",
    "letter": "letter",
    "manuscript": "unpublished",
    "interview": "misc",
    "film": "movie",
    "artwork": "artwork",
    "webpage": "online",
    "conferencePaper": "inproceedings",
    "report": "report",
    "patent": "patent",
    "blogPost": "online",
    "forumPost": "online",
    "audioRecording": "audio",
    "videoRecording": "video",
    "podcast": "audio",
    "computerProgram": "software",
    "document": "misc",
    "encyclopediaArticle": "inreference",
    "dictionaryEntry": "inreference",
    "preprint": "online",
    "dataset": "dataset",
}

RIS_TYPE_MAP = {
    "artwork": "ART",
    "audioRecording": "SOUND",
    "bill": "BILL",
    "blogPost": "BLOG",
    "book": "BOOK",
    "bookSection": "CHAP",
    "case": "CASE",
    "computerProgram": "COMP",
    "conferencePaper": "CONF",
    "dictionaryEntry": "DICT",
    "encyclopediaArticle": "ENCYC",
    "email": "ICOMM",
    "dataset": "DATA",
    "film": "MPCT",
    "forumPost": "COMM",
    "hearing": "HEAR",
    "instantMessage": "ICOMM",
    "interview": "INPR",
    "journalArticle": "JOUR",
    "letter": "PCOMM",
    "magazineArticle": "MGZN",
    "manuscript": "MANSCPT",
    "map": "MAP",
    "newspaperArticle": "NEWS",
    "patent": "PAT",
    "podcast": "SOUND",
    "preprint": "EJOUR",
    "presentation": "SLIDE",
    "radioBroadcast": "RPRT",
    "report": "RPRT",
    "standard": "STAND",
    "statute": "STAT",
    "thesis": "THES",
    "tvBroadcast": "MPCT",
    "videoRecording": "VIDEO",
    "webpage": "ELEC",
}

CSL_TYPE_MAP = {
    "artwork": "graphic",
    "audioRecording": "song",
    "bill": "bill",
    "blogPost": "post-weblog",
    "book": "book",
    "bookSection": "chapter",
    "case": "legal_case",
    "computerProgram": "software",
    "conferencePaper": "paper-conference",
    "dataset": "dataset",
    "dictionaryEntry": "entry-dictionary",
    "email": "personal_communication",
    "encyclopediaArticle": "entry-encyclopedia",
    "film": "motion_picture",
    "hearing": "hearing",
    "interview": "interview",
    "journalArticle": "article-journal",
    "letter": "personal_communication",
    "magazineArticle": "article-magazine",
    "manuscript": "manuscript",
    "map": "map",
    "newspaperArticle": "article-newspaper",
    "patent": "patent",
    "preprint": "article",
    "report": "report",
    "standard": "standard",
    "statute": "legislation",
    "thesis": "thesis",
    "videoRecording": "motion_picture",
    "webpage": "webpage",
}


def export_filename(fmt: str) -> str:
    meta = format_meta(fmt)
    return f"zotero-web-library-{datetime.now().strftime('%Y%m%d')}.{meta['extension']}"


def format_meta(fmt: str) -> dict[str, str]:
    normalized = normalize_format(fmt)
    return EXPORT_FORMATS[normalized]


def normalize_format(fmt: str) -> str:
    normalized = str(fmt or "").strip().lower().replace("-", "_")
    if normalized not in EXPORT_FORMATS:
        raise CitationExportError("未知引用导出格式。")
    return normalized


def export_citations(items: list[dict[str, Any]], item_keys: list[str], fmt: str) -> tuple[str, dict[str, str]]:
    normalized = normalize_format(fmt)
    selected = select_items(items, item_keys)
    if not selected:
        raise CitationExportError("没有可导出的条目。")
    if normalized == "bibtex":
        content = export_bibtex(selected, biblatex=False)
    elif normalized == "biblatex":
        content = export_bibtex(selected, biblatex=True)
    elif normalized == "ris":
        content = export_ris(selected)
    elif normalized == "csl_json":
        content = export_csl_json(selected)
    elif normalized == "csv":
        content = export_csv(selected)
    else:
        raise CitationExportError("未知引用导出格式。")
    return content, format_meta(normalized)


def select_items(items: list[dict[str, Any]], item_keys: list[str]) -> list[dict[str, Any]]:
    keys = [str(key or "").strip() for key in item_keys if str(key or "").strip()]
    if not keys:
        raise CitationExportError("请先选择要导出的条目。")
    by_key = {str(item.get("key") or ""): item for item in items}
    return [by_key[key] for key in keys if key in by_key]


def field(item: dict[str, Any], name: str) -> str:
    return str((item.get("fields") or {}).get(name) or "").strip()


def first_field(item: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = field(item, name)
        if value:
            return value
    return ""


def year_from_item(item: dict[str, Any]) -> str:
    value = field(item, "date") or str(item.get("year") or "")
    match = re.search(r"\d{4}", value)
    return match.group(0) if match else ""


def creators_by_type(item: dict[str, Any], creator_type: str) -> list[dict[str, str]]:
    creators = item.get("creators") or []
    return [creator for creator in creators if (creator.get("type") or "author") == creator_type]


def creator_name(creator: dict[str, str], *, bibtex: bool = False) -> str:
    name = str(creator.get("name") or "").strip()
    if not name:
        return ""
    if bibtex and "," not in name:
        parts = name.split()
        if len(parts) > 1:
            return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return name


def creator_names(item: dict[str, Any], creator_type: str = "author", *, bibtex: bool = False) -> list[str]:
    creators = creators_by_type(item, creator_type)
    if not creators and creator_type == "author":
        creators = item.get("creators") or []
    return [name for name in (creator_name(creator, bibtex=bibtex) for creator in creators) if name]


def first_author_surname(item: dict[str, Any]) -> str:
    names = creator_names(item, "author")
    if not names:
        return "zotero"
    first = names[0].replace(",", " ").split()
    return first[-1] if first else "zotero"


def first_title_word(item: dict[str, Any]) -> str:
    words = re.findall(r"[\w\u4e00-\u9fff]+", str(item.get("title") or ""), flags=re.UNICODE)
    return words[0] if words else "item"


def sanitize_citekey(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "", value)
    return clean or "zotero_item"


def citekeys_for(items: list[dict[str, Any]]) -> list[str]:
    bases: list[str] = []
    for item in items:
        base = sanitize_citekey(f"{first_author_surname(item)}_{first_title_word(item)}_{year_from_item(item)}")
        bases.append(base)
    seen: Counter[str] = Counter()
    values: list[str] = []
    for base in bases:
        seen[base] += 1
        values.append(base if seen[base] == 1 else f"{base}{seen[base]}")
    return values


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    return "".join(replacements.get(char, char) for char in str(value or ""))


def bib_fields(item: dict[str, Any], *, biblatex: bool) -> dict[str, str]:
    values: dict[str, str] = {}
    title = str(item.get("title") or field(item, "title") or "").strip()
    if title:
        values["title"] = title
    authors = creator_names(item, "author", bibtex=True)
    if authors:
        values["author"] = " and ".join(authors)
    year = year_from_item(item)
    if year:
        values["year"] = year
    venue = first_field(item, ["publicationTitle", "proceedingsTitle", "conferenceName", "repository"])
    if venue:
        values["booktitle" if item.get("type") in {"bookSection", "conferencePaper"} else "journal"] = venue
    direct_map = {
        "volume": "volume",
        "issue": "number",
        "pages": "pages",
        "publisher": "publisher",
        "place": "location" if biblatex else "address",
        "DOI": "doi",
        "ISBN": "isbn",
        "ISSN": "issn",
        "url": "url",
        "abstractNote": "abstract",
        "shortTitle": "shorttitle",
        "language": "language",
        "extra": "note",
    }
    for zotero_name, bib_name in direct_map.items():
        value = field(item, zotero_name)
        if value:
            values[bib_name] = value
    tags = item.get("tags") or []
    if tags:
        values["keywords"] = ", ".join(str(tag) for tag in tags if str(tag).strip())
    if biblatex and item.get("type") == "preprint" and field(item, "repository"):
        values["eprinttype"] = field(item, "repository")
    return values


def export_bibtex(items: list[dict[str, Any]], *, biblatex: bool) -> str:
    type_map = BIBLATEX_TYPE_MAP if biblatex else BIBTEX_TYPE_MAP
    citekeys = citekeys_for(items)
    records: list[str] = []
    for index, item in enumerate(items):
        entry_type = type_map.get(str(item.get("type") or ""), "misc")
        lines = [f"@{entry_type}{{{citekeys[index]},"]
        fields = bib_fields(item, biblatex=biblatex)
        for key, value in fields.items():
            if not value:
                continue
            lines.append(f"  {key} = {{{tex_escape(value)}}},")
        if lines[-1].endswith(","):
            lines[-1] = lines[-1].rstrip(",")
        lines.append("}")
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


def ris_line(tag: str, value: str) -> str:
    return f"{tag}  - {value}"


def export_ris(items: list[dict[str, Any]]) -> str:
    records: list[str] = []
    for item in items:
        lines = [ris_line("TY", RIS_TYPE_MAP.get(str(item.get("type") or ""), "GEN"))]
        title = str(item.get("title") or field(item, "title") or "").strip()
        if title:
            lines.append(ris_line("TI", title))
        for author in creator_names(item, "author"):
            lines.append(ris_line("AU", author))
        year = year_from_item(item)
        if year:
            lines.append(ris_line("PY", year))
        venue = first_field(item, ["publicationTitle", "proceedingsTitle", "conferenceName", "repository"])
        if venue:
            lines.append(ris_line("T2", venue))
            lines.append(ris_line("JO", venue))
        simple_fields = {
            "DOI": "DO",
            "ISBN": "SN",
            "ISSN": "SN",
            "url": "UR",
            "abstractNote": "AB",
            "pages": "SP",
            "volume": "VL",
            "issue": "IS",
            "publisher": "PB",
            "place": "CY",
        }
        for zotero_name, ris_tag in simple_fields.items():
            value = field(item, zotero_name)
            if value:
                lines.append(ris_line(ris_tag, value))
        for tag in item.get("tags") or []:
            value = str(tag or "").strip()
            if value:
                lines.append(ris_line("KW", value))
        lines.append(ris_line("ER", ""))
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


def csl_name(creator: dict[str, str]) -> dict[str, str]:
    name = str(creator.get("name") or "").strip()
    if not name:
        return {}
    if "," in name:
        family, given = [part.strip() for part in name.split(",", 1)]
        return {"family": family, "given": given}
    parts = name.split()
    if len(parts) == 1:
        return {"family": parts[0]}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def csl_date(value: str) -> dict[str, list[list[int | str]]]:
    parts = re.findall(r"\d+", value or "")
    if not parts:
        return {}
    date_parts: list[int | str] = []
    for part in parts[:3]:
        try:
            date_parts.append(int(part))
        except ValueError:
            date_parts.append(part)
    return {"date-parts": [date_parts]}


def export_csl_json(items: list[dict[str, Any]]) -> str:
    values: list[dict[str, Any]] = []
    for item in items:
        entry: dict[str, Any] = {
            "id": item.get("key"),
            "type": CSL_TYPE_MAP.get(str(item.get("type") or ""), "article"),
            "title": item.get("title") or field(item, "title") or "",
        }
        authors = [csl_name(creator) for creator in creators_by_type(item, "author")]
        authors = [author for author in authors if author]
        if authors:
            entry["author"] = authors
        issued = csl_date(field(item, "date"))
        if issued:
            entry["issued"] = issued
        csl_fields = {
            "publicationTitle": "container-title",
            "publisher": "publisher",
            "place": "publisher-place",
            "volume": "volume",
            "issue": "issue",
            "pages": "page",
            "DOI": "DOI",
            "ISBN": "ISBN",
            "ISSN": "ISSN",
            "url": "URL",
            "abstractNote": "abstract",
            "language": "language",
        }
        for zotero_name, csl_name_key in csl_fields.items():
            value = field(item, zotero_name)
            if value:
                entry[csl_name_key] = value
        values.append({key: value for key, value in entry.items() if value not in ("", None)})
    return json.dumps(values, ensure_ascii=False, indent=2) + "\n"


def export_csv(items: list[dict[str, Any]]) -> str:
    columns = [
        "key",
        "itemType",
        "publicationYear",
        "creators/author",
        "title",
        "publicationTitle",
        "ISBN",
        "ISSN",
        "DOI",
        "url",
        "abstractNote",
        "date",
        "dateAdded",
        "dateModified",
        "pages",
        "issue",
        "volume",
        "publisher",
        "place",
        "extra",
        "tags",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for item in items:
        row = {
            "key": item.get("key") or "",
            "itemType": item.get("type") or "",
            "publicationYear": year_from_item(item),
            "creators/author": "; ".join(creator_names(item, "author")),
            "title": item.get("title") or "",
            "publicationTitle": first_field(item, ["publicationTitle", "proceedingsTitle", "conferenceName", "repository"]),
            "ISBN": field(item, "ISBN"),
            "ISSN": field(item, "ISSN"),
            "DOI": field(item, "DOI"),
            "url": field(item, "url"),
            "abstractNote": field(item, "abstractNote").replace("\n", " "),
            "date": field(item, "date"),
            "dateAdded": item.get("date_added") or "",
            "dateModified": item.get("date_modified") or "",
            "pages": field(item, "pages"),
            "issue": field(item, "issue"),
            "volume": field(item, "volume"),
            "publisher": field(item, "publisher"),
            "place": field(item, "place"),
            "extra": field(item, "extra").replace("\n", " "),
            "tags": "; ".join(str(tag) for tag in item.get("tags") or []),
        }
        writer.writerow(row)
    return "\ufeff" + output.getvalue()
