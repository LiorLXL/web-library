from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .models import TaskPlan


_CITATION_RE = re.compile(r"\[[A-Za-z0-9_-]+:[^\[\]\s]+\]")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_CLAIM_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|(?<=[.])\s+|[\r\n]+")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_INSUFFICIENT_MARKERS = (
    "证据不足",
    "无法回答",
    "无法完成",
    "没有获得可用证据",
    "未找到证据",
    "evidence is insufficient",
    "insufficient evidence",
)
_ASCII_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "paper",
    "method",
    "model",
    "using",
    "used",
    "into",
    "are",
    "was",
    "were",
}


@dataclass(slots=True)
class AnswerEnvelope:
    answer_markdown: str
    claims: list[dict[str, Any]]
    citations: list[str]
    structured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_markdown": self.answer_markdown,
            "claims": [dict(claim) for claim in self.claims],
            "citations": list(self.citations),
            "structured": self.structured,
        }


def parse_answer_envelope(content: str) -> AnswerEnvelope:
    raw = str(content or "").strip()
    match = _JSON_FENCE_RE.match(raw)
    candidate = match.group(1).strip() if match else raw
    payload: dict[str, Any] = {}
    if candidate.startswith("{") and candidate.endswith("}"):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            payload = parsed

    answer = str(payload.get("answer_markdown") or payload.get("answer") or raw).strip()
    structured_claims = payload.get("claims") if isinstance(payload.get("claims"), list) else []
    claims = _normalize_claims(structured_claims, answer) if payload else _extract_claims(answer)
    citations = _ordered_unique(
        [
            *_CITATION_RE.findall(answer),
            *[str(value) for value in payload.get("citations") or [] if isinstance(value, str)],
            *[citation for claim in claims for citation in claim.get("citations") or []],
        ]
    )
    return AnswerEnvelope(answer, claims, citations, structured=bool(payload))


def verify_answer(
    envelope: AnswerEnvelope,
    *,
    task_plan: TaskPlan,
    evidence: list[dict[str, Any]],
    scope_item_keys: list[str],
    semantic_decisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence_by_citation = {
        str(item.get("citation") or ""): item
        for item in evidence
        if str(item.get("citation") or "")
    }
    scope = {str(value or "") for value in scope_item_keys if str(value or "")}
    decisions = semantic_decisions or {}
    issues: list[dict[str, Any]] = []
    claim_results: list[dict[str, Any]] = []
    verified_evidence_ids: list[str] = []
    factual_claims = [claim for claim in envelope.claims if bool(claim.get("factual", True))]

    for claim in factual_claims:
        claim_id = str(claim.get("claim_id") or f"claim-{len(claim_results) + 1}")
        citations = _ordered_unique([str(value) for value in claim.get("citations") or [] if str(value or "")])
        claim_issues: list[str] = []
        valid_evidence: list[dict[str, Any]] = []
        if not citations:
            claim_issues.append("missing_citation")
        for citation in citations:
            source = evidence_by_citation.get(citation)
            if not source:
                claim_issues.append("citation_not_in_registry")
                continue
            item_key = str(source.get("item_key") or "")
            if scope and item_key not in scope:
                claim_issues.append("citation_out_of_scope")
                continue
            valid_evidence.append(source)

        support_status = "unsupported"
        support_reason = ""
        if valid_evidence and not claim_issues:
            if any(_lexically_supported(str(claim.get("text") or ""), source) for source in valid_evidence):
                support_status = "supported"
                support_reason = "deterministic_text_overlap"
            elif claim_id in decisions:
                semantic = decisions[claim_id]
                support_status = "supported" if bool(semantic.get("supported")) else "unsupported"
                support_reason = str(semantic.get("reason") or "semantic_judge")
            else:
                support_status = "pending_semantic"
                support_reason = "text_support_requires_semantic_judge"

        if claim_issues:
            support_status = "unsupported"
        if support_status == "unsupported" and not claim_issues:
            claim_issues.append("citation_text_not_supporting_claim")
        for issue in _ordered_unique(claim_issues):
            issues.append({"claim_id": claim_id, "code": issue})

        supported_ids = []
        if support_status == "supported":
            supported_ids = [str(item.get("evidence_id") or "") for item in valid_evidence if item.get("evidence_id")]
            verified_evidence_ids.extend(supported_ids)
        claim_results.append(
            {
                "claim_id": claim_id,
                "text": str(claim.get("text") or ""),
                "citations": citations,
                "status": support_status,
                "support_reason": support_reason,
                "supported_evidence_ids": supported_ids,
                "issues": _ordered_unique(claim_issues),
            }
        )

    if task_plan.task_type != "scope" and not factual_claims:
        issues.append({"claim_id": "", "code": "no_verifiable_claims"})

    answer_citations = set(_CITATION_RE.findall(envelope.answer_markdown))
    for citation in envelope.citations:
        if citation not in evidence_by_citation:
            issues.append({"claim_id": "", "code": "citation_not_in_registry", "citation": citation})
        if citation not in answer_citations:
            issues.append({"claim_id": "", "code": "citation_not_present_in_answer", "citation": citation})

    cited_sources = [evidence_by_citation[value] for value in answer_citations if value in evidence_by_citation]
    requires_content = bool(task_plan.completion_conditions.get("requires_content_evidence"))
    content_sources = [item for item in cited_sources if _is_content_evidence(item)]
    if requires_content and not content_sources:
        issues.append({"claim_id": "", "code": "content_evidence_required"})

    required_coverage = int(task_plan.completion_conditions.get("minimum_item_coverage") or 0)
    coverage_sources = content_sources if requires_content else cited_sources
    cited_item_keys = {
        str(item.get("item_key") or "")
        for item in coverage_sources
        if str(item.get("item_key") or "")
    }
    if required_coverage and len(cited_item_keys) < required_coverage:
        issues.append(
            {
                "claim_id": "",
                "code": "minimum_item_coverage_not_met",
                "required": required_coverage,
                "observed": len(cited_item_keys),
            }
        )

    pending = [item["claim_id"] for item in claim_results if item["status"] == "pending_semantic"]
    unsupported = [item["claim_id"] for item in claim_results if item["status"] == "unsupported"]
    hard_issue_codes = {
        "missing_citation",
        "citation_not_in_registry",
        "citation_out_of_scope",
        "citation_not_present_in_answer",
        "content_evidence_required",
        "minimum_item_coverage_not_met",
        "no_verifiable_claims",
    }
    hard_gate_passed = not any(str(item.get("code") or "") in hard_issue_codes for item in issues)
    status = "verified"
    if not hard_gate_passed or unsupported:
        status = "failed"
    elif pending:
        status = "pending_semantic"
    supported_count = sum(item["status"] == "supported" for item in claim_results)
    return {
        "status": status,
        "hard_gate_passed": hard_gate_passed,
        "semantic_judge_required": bool(pending and hard_gate_passed),
        "claim_count": len(factual_claims),
        "supported_claim_count": supported_count,
        "unsupported_claim_count": len(unsupported),
        "pending_claim_count": len(pending),
        "supported_claim_ratio": (supported_count / len(factual_claims)) if factual_claims else (1.0 if task_plan.task_type == "scope" else 0.0),
        "verified_evidence_ids": _ordered_unique(verified_evidence_ids),
        "claims": claim_results,
        "issues": _dedupe_issues(issues),
    }


def semantic_judge_prompt(
    envelope: AnswerEnvelope,
    verification: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> str:
    pending_ids = {
        str(item.get("claim_id") or "")
        for item in verification.get("claims") or []
        if item.get("status") == "pending_semantic"
    }
    pending_claims = [claim for claim in envelope.claims if str(claim.get("claim_id") or "") in pending_ids]
    citations = {citation for claim in pending_claims for citation in claim.get("citations") or []}
    cited_evidence = [
        {
            "citation": str(item.get("citation") or ""),
            "item_key": str(item.get("item_key") or ""),
            "source_type": str(item.get("source_type") or ""),
            "text": str(item.get("support_text") or item.get("excerpt") or "")[:1600],
        }
        for item in evidence
        if str(item.get("citation") or "") in citations
    ]
    payload = {
        "claims": [
            {
                "claim_id": str(claim.get("claim_id") or ""),
                "text": str(claim.get("text") or ""),
                "citations": list(claim.get("citations") or []),
            }
            for claim in pending_claims
        ],
        "evidence": cited_evidence,
    }
    return (
        "You are a constrained evidence sufficiency judge. Decide only whether each claim is directly supported "
        "by its cited evidence. Do not use outside knowledge and do not repair the answer. Return JSON only: "
        '{"claims":[{"claim_id":"...","supported":true,"reason":"short reason"}]}.\n'
        f"Input: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def parse_semantic_judgement(content: str, allowed_claim_ids: set[str]) -> dict[str, dict[str, Any]]:
    raw = str(content or "").strip()
    match = _JSON_FENCE_RE.match(raw)
    candidate = match.group(1).strip() if match else raw
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    rows = payload.get("claims") if isinstance(payload, dict) and isinstance(payload.get("claims"), list) else []
    decisions: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("claim_id") or "")
        if claim_id not in allowed_claim_ids or not isinstance(row.get("supported"), bool):
            continue
        decisions[claim_id] = {
            "supported": bool(row["supported"]),
            "reason": str(row.get("reason") or "semantic_judge")[:240],
        }
    return decisions


def repair_prompt(
    envelope: AnswerEnvelope,
    verification: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> str:
    safe_evidence = [
        {
            "citation": str(item.get("citation") or ""),
            "item_key": str(item.get("item_key") or ""),
            "source_type": str(item.get("source_type") or ""),
            "title": str(item.get("title") or ""),
            "text": str(item.get("support_text") or item.get("excerpt") or "")[:1600],
        }
        for item in evidence
    ]
    payload = {
        "answer_markdown": envelope.answer_markdown,
        "verification_issues": verification.get("issues") or [],
        "evidence": safe_evidence,
    }
    return (
        "Repair the answer using only the supplied evidence. Remove unsupported claims; do not invent citations. "
        "Return JSON only with answer_markdown, claims, and citations. Each claims item must contain claim_id, text, "
        "citations, and factual. Keep citation markers adjacent to claims.\n"
        f"Input: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def prune_to_verified(envelope: AnswerEnvelope, verification: dict[str, Any]) -> AnswerEnvelope:
    supported_ids = {
        str(item.get("claim_id") or "")
        for item in verification.get("claims") or []
        if item.get("status") == "supported"
    }
    claims = [claim for claim in envelope.claims if str(claim.get("claim_id") or "") in supported_ids]
    lines: list[str] = []
    for claim in claims:
        text = str(claim.get("text") or "").strip()
        citations = [str(value) for value in claim.get("citations") or [] if str(value or "")]
        for citation in citations:
            if citation not in text:
                text = f"{text} {citation}".strip()
        if text:
            lines.append(text)
    answer = "\n\n".join(lines)
    return AnswerEnvelope(answer, [dict(claim) for claim in claims], _ordered_unique([c for claim in claims for c in claim.get("citations") or []]), True)


def insufficient_answer(verification: dict[str, Any]) -> str:
    codes = _ordered_unique([str(item.get("code") or "") for item in verification.get("issues") or []])
    labels = {
        "missing_citation": "回答中的事实主张缺少引用",
        "citation_not_in_registry": "引用不属于本次检索证据",
        "citation_out_of_scope": "引用超出当前知识库作用域",
        "citation_text_not_supporting_claim": "引用文本不足以支持主张",
        "content_evidence_required": "内容问题只有元数据、缺少正文证据",
        "minimum_item_coverage_not_met": "比较任务未覆盖足够文献",
        "no_verifiable_claims": "没有可验证的事实主张",
    }
    reasons = [labels[code] for code in codes if code in labels]
    detail = "；".join(reasons[:3]) or "当前证据无法通过充分性检查"
    return f"当前证据不足，无法给出可靠回答：{detail}。请补充或重新检索相关证据后再试。"


def _normalize_claims(rows: list[Any], answer: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            text = row.strip()
            citations = _CITATION_RE.findall(text)
            factual = _is_factual_claim(text)
            raw_id = ""
        elif isinstance(row, dict):
            text = str(row.get("text") or row.get("claim") or "").strip()
            citations = _ordered_unique(
                [
                    *_CITATION_RE.findall(text),
                    *[str(value) for value in row.get("citations") or [] if isinstance(value, str)],
                ]
            )
            factual = bool(row.get("factual", _is_factual_claim(text)))
            raw_id = str(row.get("claim_id") or "")
        else:
            continue
        if not text:
            continue
        claims.append(
            {
                "claim_id": raw_id or f"claim-{len(claims) + 1}",
                "text": text,
                "citations": citations,
                "factual": factual,
            }
        )
    return claims or _extract_claims(answer)


def _extract_claims(answer: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for part in _CLAIM_SPLIT_RE.split(str(answer or "")):
        text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", part).strip()
        if not text or text.startswith("#"):
            continue
        claims.append(
            {
                "claim_id": f"claim-{len(claims) + 1}",
                "text": text,
                "citations": _ordered_unique(_CITATION_RE.findall(text)),
                "factual": _is_factual_claim(text),
            }
        )
    return claims


def _is_factual_claim(text: str) -> bool:
    value = str(text or "").strip().casefold()
    return bool(value) and not any(marker in value for marker in _INSUFFICIENT_MARKERS)


def _lexically_supported(claim: str, evidence: dict[str, Any]) -> bool:
    claim_text = _CITATION_RE.sub("", str(claim or "")).strip().casefold()
    evidence_text = str(evidence.get("support_text") or evidence.get("excerpt") or "").strip().casefold()
    if not claim_text or not evidence_text:
        return False
    normalized_claim = re.sub(r"\s+", " ", claim_text)
    normalized_evidence = re.sub(r"\s+", " ", evidence_text)
    if len(normalized_claim) >= 10 and normalized_claim in normalized_evidence:
        return True
    claim_ascii = {token.casefold() for token in _ASCII_TOKEN_RE.findall(claim_text) if token.casefold() not in _ASCII_STOPWORDS}
    evidence_ascii = {token.casefold() for token in _ASCII_TOKEN_RE.findall(evidence_text)}
    if len(claim_ascii & evidence_ascii) >= 2:
        return True
    claim_cjk = _cjk_bigrams(claim_text)
    evidence_cjk = _cjk_bigrams(evidence_text)
    overlap = claim_cjk & evidence_cjk
    return len(overlap) >= 2 and len(overlap) / max(1, min(len(claim_cjk), 12)) >= 0.18


def _is_content_evidence(evidence: dict[str, Any]) -> bool:
    return str(evidence.get("source_type") or "") not in {"", "metadata", "scope"}


def _cjk_bigrams(value: str) -> set[str]:
    chars = [char for char in value if _CJK_RE.fullmatch(char)]
    return {"".join(chars[index : index + 2]) for index in range(max(0, len(chars) - 1))}


def _ordered_unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            output.append(clean)
    return output


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in issues:
        key = json.dumps(issue, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            output.append(dict(issue))
    return output
