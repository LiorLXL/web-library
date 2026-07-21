from __future__ import annotations

from typing import Any


class EvidenceAccumulator:
    def __init__(self) -> None:
        self._by_key: dict[str, dict[str, Any]] = {}
        self._support_text_by_key: dict[str, str] = {}
        self._order: list[str] = []
        self._counter = 0

    def register(
        self,
        raw_results: list[dict[str, Any]],
        *,
        include_text: bool = False,
        excerpt_limit: int = 300,
        text_limit: int = 1800,
    ) -> list[dict[str, Any]]:
        slim: list[dict[str, Any]] = []
        for raw in raw_results:
            evidence, text = self._register_one(raw)
            slim.append(_slim_evidence(evidence, text=text, include_text=include_text, excerpt_limit=excerpt_limit, text_limit=text_limit))
        return slim

    def all_sources(self) -> list[dict[str, Any]]:
        return [dict(self._by_key[key]) for key in self._order if key in self._by_key]

    def sources_by_evidence_ids(self, evidence_ids: list[str] | set[str]) -> list[dict[str, Any]]:
        allowed = {str(value or "") for value in evidence_ids}
        return [
            dict(self._by_key[key])
            for key in self._order
            if key in self._by_key and str(self._by_key[key].get("evidence_id") or "") in allowed
        ]

    def verification_evidence(self) -> list[dict[str, Any]]:
        return [
            {
                **dict(self._by_key[key]),
                "support_text": self._support_text_by_key.get(key) or str(self._by_key[key].get("excerpt") or ""),
            }
            for key in self._order
            if key in self._by_key
        ]

    def _register_one(self, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        evidence = _normalize_evidence(raw)
        key = _evidence_key(evidence)
        text = str(raw.get("text") or raw.get("content") or "")
        if key in self._by_key:
            evidence_id = str(self._by_key[key].get("evidence_id") or "")
            evidence["evidence_id"] = evidence_id
            if len(text) > len(self._support_text_by_key.get(key, "")):
                self._support_text_by_key[key] = text[:6000]
            return self._by_key[key], text

        self._counter += 1
        evidence["evidence_id"] = f"ev-{self._counter}"
        self._by_key[key] = evidence
        self._support_text_by_key[key] = (text or str(evidence.get("excerpt") or ""))[:6000]
        self._order.append(key)
        return evidence, text


def _normalize_evidence(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    item_key = str(raw.get("item_key") or source.get("item_key") or "").strip()
    chunk_id = str(raw.get("chunk_id") or source.get("chunk_id") or "").strip()
    source_type = _source_type(raw)
    excerpt = str(raw.get("excerpt") or raw.get("snippet") or source.get("excerpt") or raw.get("text") or raw.get("content") or "")
    evidence = {
        "evidence_id": "",
        "source_type": source_type,
        "retrieval_type": str(raw.get("retrieval_type") or ""),
        "item_key": item_key,
        "attachment_key": str(raw.get("attachment_key") or source.get("attachment_key") or ""),
        "doc_id": str(raw.get("doc_id") or source.get("doc_id") or ""),
        "chunk_id": chunk_id,
        "chunk_type": str(raw.get("chunk_type") or ""),
        "document_source_type": str(raw.get("document_source_type") or source.get("source_type") or ""),
        "title": str(raw.get("title") or source.get("title") or ""),
        "authors_text": str(raw.get("authors_text") or source.get("authors_text") or ""),
        "year": str(raw.get("year") or source.get("year") or ""),
        "venue": str(raw.get("venue") or source.get("venue") or ""),
        "section_title": str(raw.get("section_title") or source.get("section_title") or ""),
        "section_path": str(raw.get("section_path") or source.get("section_path") or ""),
        "parent_chunk_id": str(raw.get("parent_chunk_id") or source.get("parent_chunk_id") or ""),
        "estimated_page": raw.get("estimated_page", source.get("estimated_page")),
        "excerpt": excerpt[:700],
        "score": raw.get("score"),
        "scores": raw.get("scores") or {},
        "query_lineage": raw.get("query_lineage") or [],
        "selection_reason": str(raw.get("selection_reason") or ""),
        "rank": raw.get("rank"),
        "citation": str(raw.get("citation") or _citation(source_type=source_type, item_key=item_key, chunk_id=chunk_id)),
    }
    return evidence


def _source_type(raw: dict[str, Any]) -> str:
    raw_source_type = str(raw.get("source_type") or "")
    if raw_source_type:
        return raw_source_type
    chunk_type = str(raw.get("chunk_type") or "")
    if chunk_type == "metadata":
        return "metadata"
    if chunk_type in {"note", "annotation", "writing"}:
        return "note"
    return "chunk"


def _evidence_key(evidence: dict[str, Any]) -> str:
    chunk_id = str(evidence.get("chunk_id") or "")
    item_key = str(evidence.get("item_key") or "")
    source_type = str(evidence.get("source_type") or "evidence")
    if chunk_id:
        return chunk_id
    if source_type == "metadata" and item_key:
        return f"{item_key}:metadata"
    return f"{item_key}:{source_type}:{evidence.get('doc_id') or evidence.get('title') or evidence.get('citation')}"


def _slim_evidence(
    evidence: dict[str, Any],
    *,
    text: str,
    include_text: bool,
    excerpt_limit: int,
    text_limit: int,
) -> dict[str, Any]:
    payload = {
        "evidence_id": evidence.get("evidence_id", ""),
        "citation": evidence.get("citation", ""),
        "source_type": evidence.get("source_type", ""),
        "title": evidence.get("title", ""),
        "authors_text": evidence.get("authors_text", ""),
        "year": evidence.get("year", ""),
        "section_title": evidence.get("section_title", ""),
        "section_path": evidence.get("section_path", ""),
        "parent_chunk_id": evidence.get("parent_chunk_id", ""),
        "item_key": evidence.get("item_key", ""),
        "chunk_id": evidence.get("chunk_id", ""),
        "excerpt": str(evidence.get("excerpt") or "")[:excerpt_limit],
        "retrieval_type": evidence.get("retrieval_type", ""),
        "scores": evidence.get("scores") or {},
        "query_lineage": evidence.get("query_lineage") or [],
        "selection_reason": evidence.get("selection_reason", ""),
    }
    if include_text:
        payload["text"] = str(text or evidence.get("excerpt") or "")[:text_limit]
    return payload


def _citation(*, source_type: str, item_key: str, chunk_id: str) -> str:
    key = item_key or "unknown"
    if source_type == "metadata":
        return f"[{key}:metadata]"
    if chunk_id:
        return f"[{key}:{chunk_id}]"
    return f"[{key}:evidence]"
