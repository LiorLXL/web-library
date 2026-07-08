from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from zotero_web_library.metadata_import import ImportedItem


@dataclass
class SearchOptions:
    start_year: int | None = None
    end_year: int | None = None
    material_types: list[str] = field(default_factory=list)
    sort_mode: str = "relevance"
    strategy_mode: str = "fast"

    @classmethod
    def from_payload(cls, value: Any) -> "SearchOptions":
        if isinstance(value, SearchOptions):
            return value
        payload = value if isinstance(value, dict) else {}
        return cls(
            start_year=normalized_year(payload.get("start_year")),
            end_year=normalized_year(payload.get("end_year")),
            material_types=[
                normalized_material_type(item)
                for item in payload.get("material_types") or []
                if normalized_material_type(item)
            ],
            sort_mode=normalized_choice(payload.get("sort_mode"), {"relevance", "date", "authority"}, "relevance"),
            strategy_mode=normalized_choice(payload.get("strategy_mode"), {"fast", "quality", "coverage"}, "fast"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_year": self.start_year,
            "end_year": self.end_year,
            "material_types": self.material_types,
            "sort_mode": self.sort_mode,
            "strategy_mode": self.strategy_mode,
        }


@dataclass
class RetrievedCandidate:
    source: str
    external_id: str
    item: ImportedItem
    raw: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    landing_url: str = ""
    pdf_url: str = ""
    also_seen_in: list[str] = field(default_factory=list)

    def as_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        fields = self.item.fields
        sources = source_names(self)
        authority = authority_signals(self)
        missing_authority = missing_authority_signals(authority)
        quality = quality_score(self, authority)
        coverage = coverage_tags(self, authority)
        resource_type = candidate_resource_type(self)
        source_instance = source_instance_id(self)
        web_meta = webpage_metadata(self)
        payload = {
            "source": self.source,
            "external_id": self.external_id,
            "item_type": self.item.item_type,
            "resource_type": resource_type,
            "resource_type_tags": resource_type_tags(resource_type, coverage),
            "source_category": source_category(self.source, resource_type),
            "source_instance_id": source_instance,
            "title": fields.get("title", ""),
            "year": year_from_fields(fields),
            "venue": venue_from_fields(fields),
            "abstract": fields.get("abstractNote", ""),
            "creators": [creator.__dict__ for creator in self.item.creators],
            "tags": self.item.tags,
            "identifiers": self.item.identifiers,
            "item": self.item.as_dict(),
            "confidence": self.confidence,
            "confidence_label": confidence_label(self.confidence),
            "evidence": self.evidence,
            "rank_reasons": rank_reasons(self),
            "landing_url": self.landing_url or fields.get("url", ""),
            "pdf_url": self.pdf_url,
            "also_seen_in": self.also_seen_in,
            "sources": sources,
            "source_count": len(sources),
            "multi_source": len(sources) > 1,
            "authority_signals": authority,
            "missing_authority_signals": missing_authority,
            "quality_score": quality,
            "quality_bucket": quality_bucket(quality),
            "coverage_tags": coverage,
            "webpage_metadata": web_meta,
        }
        if include_raw:
            payload["raw"] = self.raw
        return payload


@dataclass
class SourceSearchResult:
    source: str
    ok: bool
    candidates: list[RetrievedCandidate] = field(default_factory=list)
    error: str = ""
    error_kind: str = ""
    action: str = ""
    elapsed_ms: int = 0
    rate_limit_wait_ms: int = 0
    rate_limit_seconds: float = 0.0
    filtering: dict[str, Any] = field(default_factory=dict)

    def stats_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "count": len(self.candidates),
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "rate_limit_wait_ms": self.rate_limit_wait_ms,
            "rate_limit_seconds": self.rate_limit_seconds,
        }
        if self.error_kind:
            payload["error_kind"] = self.error_kind
        if self.action:
            payload["action"] = self.action
        if self.filtering:
            payload["filtering"] = self.filtering
        return payload


def normalized_year(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\b(18|19|20|21)\d{2}\b", text)
    if not match:
        return None
    year = int(match.group(0))
    return year if 1800 <= year <= 2199 else None


def normalized_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def normalized_material_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "paper": "paper",
        "papers": "paper",
        "论文": "paper",
        "article": "paper",
        "preprint": "paper",
        "code": "code",
        "software": "code",
        "repo": "code",
        "repository": "code",
        "代码": "code",
        "model": "model",
        "models": "model",
        "ai-model": "model",
        "ml-model": "model",
        "data": "dataset",
        "dataset": "dataset",
        "datasets": "dataset",
        "数据": "dataset",
        "benchmark": "benchmark",
        "benchmarks": "benchmark",
        "leaderboard": "benchmark",
        "leaderboards": "benchmark",
        "website": "website",
        "webpage": "website",
        "web": "website",
        "url": "website",
        "site": "website",
    }
    return aliases.get(text, "")


def year_from_fields(fields: dict[str, str]) -> str:
    value = str(fields.get("date") or "")
    for index in range(max(0, len(value) - 3)):
        chunk = value[index : index + 4]
        if chunk.isdigit():
            return chunk
    return ""


def candidate_material_type(item_type: str, source: str = "") -> str:
    resource_type = candidate_resource_type_from_values(item_type=item_type, source=source)
    return "data" if resource_type == "dataset" else resource_type


def candidate_resource_type(candidate: RetrievedCandidate) -> str:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    return candidate_resource_type_from_values(item_type=candidate.item.item_type, source=candidate.source, raw=raw)


def candidate_resource_type_from_values(
    *,
    item_type: str,
    source: str = "",
    raw: dict[str, Any] | None = None,
) -> str:
    normalized = str(item_type or "").strip()
    source_name = str(source or "").strip().lower()
    source_base = source_name.split(":", 1)[0]
    raw_value = raw if isinstance(raw, dict) else {}
    explicit = normalized_material_type(
        raw_value.get("resource_type")
        or raw_value.get("material_type")
        or raw_value.get("kind")
        or raw_value.get("type")
        or ""
    )
    if explicit:
        return explicit
    if normalized in {"computerProgram"} or source_base in {"github", "gitlab"}:
        return "code"
    if normalized in {"webpage"} or source_base in {"brave"}:
        return "website"
    if normalized in {"dataset"} or source_base in {"zenodo", "datacite", "figshare", "osf", "openml"}:
        return "dataset"
    if source_base == "huggingface":
        text = " ".join(str(raw_value.get(key) or "") for key in ("kind", "resource_type", "pipeline_tag", "tags"))
        if "dataset" in text.casefold():
            return "dataset"
        return "model"
    return "paper"


def source_instance_id(candidate: RetrievedCandidate) -> str:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    for key in ("source_instance_id", "custom_source_id", "instance_id"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value
    return ""


def source_category(source: str, resource_type: str = "") -> str:
    name = str(source or "").strip().lower()
    base = name.split(":", 1)[0]
    if base.startswith("custom-") or base in {"localfile", "httpjson", "sqlite", "manifest"}:
        return "custom"
    if base in {"github", "gitlab"}:
        return "code"
    if base in {"huggingface"}:
        return "model"
    if base in {"datacite", "zenodo", "figshare", "osf", "openml"}:
        return "dataset"
    if base in {"brave"}:
        return "website"
    if resource_type in {"code", "model", "dataset", "benchmark", "website"}:
        return resource_type
    return "paper"


def resource_type_tags(resource_type: str, coverage: list[str]) -> list[str]:
    return list(dict.fromkeys([tag for tag in [resource_type, *coverage] if tag]))


def quality_bucket(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def webpage_metadata(candidate: RetrievedCandidate) -> dict[str, Any]:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    value = raw.get("webpage_metadata")
    return value if isinstance(value, dict) else {}


def venue_from_fields(fields: dict[str, str]) -> str:
    for key in ("publicationTitle", "proceedingsTitle", "conferenceName", "repository"):
        value = str(fields.get(key) or "").strip()
        if value:
            return value
    return ""


def source_names(candidate: RetrievedCandidate) -> list[str]:
    values: list[str] = []
    for source in [candidate.source, *candidate.also_seen_in]:
        if source and source not in values:
            values.append(source)
    return values


def confidence_label(confidence: float) -> str:
    if confidence >= 0.85:
        return "高可信"
    if confidence >= 0.65:
        return "中可信"
    return "低可信"


AUTHORITY_VENUE_TERMS = {
    "nature",
    "science",
    "cell",
    "neurips",
    "icml",
    "iclr",
    "cvpr",
    "iccv",
    "eccv",
    "acl",
    "emnlp",
    "naacl",
    "siggraph",
    "kdd",
    "aaai",
    "ijcai",
    "pnas",
    "jacs",
    "angewandte",
}


def _raw_number(raw: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        text = str(value or "").strip().replace(",", "")
        if text.isdigit():
            return int(text)
    return None


def authority_signals(candidate: RetrievedCandidate) -> dict[str, Any]:
    fields = candidate.item.fields
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    venue = venue_from_fields(fields)
    venue_lower = venue.casefold()
    signals: dict[str, Any] = {
        "source_database": candidate.source,
        "source_count": len(source_names(candidate)),
        "multi_source": bool(candidate.also_seen_in),
        "venue": venue,
        "has_identifier": bool(candidate.item.identifiers),
        "has_url": bool(candidate.landing_url or fields.get("url")),
        "has_pdf": bool(candidate.pdf_url),
    }
    citation_count = _raw_number(raw, ("cited_by_count", "citationCount", "citation_count", "num_citations", "citations"))
    if citation_count is not None:
        signals["citation_count"] = citation_count
    github_stars = _raw_number(raw, ("stars", "stargazers_count"))
    if github_stars is not None:
        signals["github_stars"] = github_stars
    github_forks = _raw_number(raw, ("forks", "forks_count"))
    if github_forks is not None:
        signals["github_forks"] = github_forks
    downloads = _raw_number(raw, ("downloads", "download_count"))
    if downloads is not None:
        signals["downloads"] = downloads
    license_value = str(raw.get("license") or "").strip()
    if license_value:
        signals["license"] = license_value
    if venue and any(term in venue_lower for term in AUTHORITY_VENUE_TERMS):
        signals["venue_authority"] = "high"
    return signals


def missing_authority_signals(signals: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if "citation_count" not in signals and signals.get("source_database") not in {"github", "gitlab", "huggingface", "brave"}:
        missing.append("citation_count")
    if not signals.get("venue"):
        missing.append("venue")
    source = str(signals.get("source_database") or "")
    if source in {"github", "gitlab"} and "github_stars" not in signals:
        missing.append("github_stars")
    if source == "huggingface" and "downloads" not in signals:
        missing.append("downloads")
    return missing


def quality_score(candidate: RetrievedCandidate, signals: dict[str, Any]) -> int:
    fields = candidate.item.fields
    score = 35
    if fields.get("title"):
        score += 12
    if candidate.item.creators:
        score += 8
    if year_from_fields(fields):
        score += 8
    if fields.get("abstractNote"):
        score += 10
    if candidate.item.identifiers:
        score += 12
    if signals.get("multi_source"):
        score += 8
    if signals.get("citation_count"):
        score += min(10, int(signals["citation_count"]) // 25 + 2)
    if signals.get("github_stars"):
        score += min(10, int(signals["github_stars"]) // 100 + 2)
    if signals.get("downloads"):
        score += min(10, int(signals["downloads"]) // 500 + 2)
    if signals.get("venue_authority") == "high":
        score += 6
    return max(0, min(score, 100))


def coverage_tags(candidate: RetrievedCandidate, signals: dict[str, Any]) -> list[str]:
    tags = [candidate_resource_type(candidate)]
    if signals.get("multi_source"):
        tags.append("multi_source")
    if signals.get("citation_count") is not None or signals.get("venue_authority") == "high":
        tags.append("authority")
    if signals.get("github_stars") is not None or signals.get("downloads") is not None:
        tags.append("usage")
    if candidate.pdf_url:
        tags.append("full_text")
    return list(dict.fromkeys(tag for tag in tags if tag))


def rank_reasons(candidate: RetrievedCandidate) -> list[str]:
    identifiers = candidate.item.identifiers
    reasons: list[str] = []
    strong_labels = [
        ("doi", "DOI"),
        ("pmid", "PMID"),
        ("pmcid", "PMCID"),
        ("arxiv", "arXiv ID"),
        ("ads_bibcode", "ADS Bibcode"),
        ("isbn", "ISBN"),
    ]
    matched = [label for key, label in strong_labels if identifiers.get(key)]
    if matched:
        reasons.append(f"强标识符：{' / '.join(matched)}")
    if candidate.also_seen_in:
        sources = " / ".join([candidate.source, *candidate.also_seen_in])
        reasons.append(f"多源命中：{sources}")
    if candidate.confidence >= 0.85:
        reasons.append("元数据置信度高")
    elif candidate.confidence >= 0.65:
        reasons.append("元数据置信度中")
    if candidate.pdf_url:
        reasons.append("包含 PDF 链接")
    if candidate.landing_url or candidate.item.fields.get("url"):
        reasons.append("包含来源页")
    authority = authority_signals(candidate)
    if authority.get("citation_count") is not None:
        reasons.append(f"引用信号：{authority['citation_count']}")
    if authority.get("github_stars") is not None:
        reasons.append(f"GitHub stars：{authority['github_stars']}")
    if authority.get("downloads") is not None:
        reasons.append(f"下载量：{authority['downloads']}")
    if authority.get("venue_authority") == "high":
        reasons.append("内置权威来源名单命中")
    for evidence in candidate.evidence:
        if evidence and evidence not in reasons and evidence not in matched:
            reasons.append(evidence)
    return reasons or ["基础元数据"]
