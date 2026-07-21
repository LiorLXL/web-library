from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


AGENT_STATES = {"plan", "retrieve", "inspect", "read", "verify", "answer", "abstain"}
RUN_STATUSES = {"running", "completed", "abstained", "failed", "cancelled", "interrupted"}
STOP_REASONS = {
    "",
    "completed",
    "insufficient_evidence",
    "budget_exceeded",
    "provider_unavailable",
    "user_action_required",
    "cancelled",
    "interrupted",
    "internal_error",
}

_CITATION_RE = re.compile(r"\[[A-Za-z0-9_-]+:[^\[\]\s]+\]")
_BIBLIOGRAPHIC_QUERY_RE = re.compile(
    r"(?:标题|作者|年份|期刊|会议|venue|doi|isbn|pmid|arxiv|谁写|何时发表|出版信息)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class TaskBudget:
    max_model_calls: int
    max_tool_calls: int
    max_search_calls: int
    max_read_calls: int
    max_total_tokens: int
    max_repair_calls: int = 1

    @classmethod
    def for_task(cls, task_type: str) -> "TaskBudget":
        profiles = {
            "scope": cls(3, 3, 1, 0, 12_000),
            "factual": cls(5, 6, 2, 2, 20_000),
            "summary": cls(5, 8, 3, 3, 30_000),
            "comparative": cls(5, 10, 4, 4, 40_000),
            "matrix": cls(5, 8, 3, 3, 30_000),
            "writing": cls(5, 10, 4, 4, 45_000),
        }
        return profiles.get(str(task_type or "factual"), profiles["factual"])

    def to_dict(self) -> dict[str, int]:
        return {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_search_calls": self.max_search_calls,
            "max_read_calls": self.max_read_calls,
            "max_total_tokens": self.max_total_tokens,
            "max_repair_calls": self.max_repair_calls,
        }


@dataclass(slots=True)
class PlanSubquestion:
    subquestion_id: str
    question: str
    expected_source_types: list[str]
    expected_chunk_types: list[str] = field(default_factory=list)
    target_item_keys: list[str] = field(default_factory=list)
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "subquestion_id": self.subquestion_id,
            "question": self.question,
            "expected_source_types": list(self.expected_source_types),
            "expected_chunk_types": list(self.expected_chunk_types),
            "target_item_keys": list(self.target_item_keys),
            "status": self.status,
        }


@dataclass(slots=True)
class TaskPlan:
    goal: str
    task_type: str
    subquestions: list[PlanSubquestion]
    budget: TaskBudget
    completion_conditions: dict[str, Any]
    plan_version: str = "phase2-foundation-v1"
    status: str = "active"

    @classmethod
    def initial(
        cls,
        question: str,
        *,
        task_type: str,
        scope_item_keys: list[str],
        planned_queries: list[dict[str, Any]] | None = None,
    ) -> "TaskPlan":
        clean_task_type = str(task_type or "factual")
        expected_source_types = ["metadata"] if clean_task_type == "scope" else ["chunk"]
        if clean_task_type == "factual":
            expected_source_types = ["metadata", "chunk"]
        completion_conditions: dict[str, Any] = {
            "all_subquestions_addressed": True,
            "all_factual_claims_cited": True,
            "minimum_supported_claim_ratio": 1.0,
            "requires_content_evidence": _requires_content_evidence(question, clean_task_type),
        }
        if clean_task_type == "comparative":
            completion_conditions["minimum_item_coverage"] = _comparison_item_coverage(
                question,
                scope_item_keys,
            )
        subquestions = [
            PlanSubquestion(
                subquestion_id="sq-1",
                question=str(question or "").strip(),
                expected_source_types=expected_source_types,
            )
        ]
        for query in planned_queries or []:
            if len(subquestions) >= 3 or str(query.get("reason") or "") != "task_decomposition":
                continue
            subquestion = str(query.get("text") or "").strip()
            if not subquestion or any(item.question.casefold() == subquestion.casefold() for item in subquestions):
                continue
            subquestions.append(
                PlanSubquestion(
                    subquestion_id=f"sq-{len(subquestions) + 1}",
                    question=subquestion,
                    expected_source_types=list(expected_source_types),
                )
            )
        return cls(
            goal=str(question or "").strip(),
            task_type=clean_task_type,
            subquestions=subquestions,
            budget=TaskBudget.for_task(clean_task_type),
            completion_conditions=completion_conditions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "goal": self.goal,
            "task_type": self.task_type,
            "subquestions": [item.to_dict() for item in self.subquestions],
            "budget": self.budget.to_dict(),
            "completion_conditions": dict(self.completion_conditions),
            "status": self.status,
        }


@dataclass(slots=True)
class EvidenceState:
    coverage: dict[str, dict[str, Any]]
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_evidence_ids: list[str] = field(default_factory=list)
    verified_evidence_ids: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "not_run",
            "claim_count": 0,
            "supported_claim_count": 0,
            "unsupported_claim_count": 0,
        }
    )

    @classmethod
    def for_plan(cls, plan: TaskPlan) -> "EvidenceState":
        return cls(
            coverage={
                item.subquestion_id: {
                    "status": "pending",
                    "evidence_ids": [],
                    "item_keys": [],
                    "source_types": [],
                }
                for item in plan.subquestions
            }
        )

    def observe_tool_result(self, tool: str, result: dict[str, Any]) -> None:
        if result.get("error"):
            self.gaps.append(
                {
                    "subquestion_id": "sq-1",
                    "gap_type": "tool_error",
                    "error_code": str(result.get("error") or "tool_failed"),
                    "tool": str(tool or ""),
                }
            )
        for warning in result.get("warnings") or []:
            clean_warning = str(warning or "").strip()
            if clean_warning and clean_warning not in self.warnings:
                self.warnings.append(clean_warning)

        entries: list[dict[str, Any]] = []
        for key in ("results", "chunks", "documents"):
            if isinstance(result.get(key), list):
                entries.extend(item for item in result[key] if isinstance(item, dict))
        parent = result.get("parent_context")
        if isinstance(parent, dict) and parent:
            entries.append(parent)

        coverage = self.coverage.setdefault(
            "sq-1",
            {"status": "pending", "evidence_ids": [], "item_keys": [], "source_types": []},
        )
        for entry in entries:
            evidence_id = str(entry.get("evidence_id") or "").strip()
            if not evidence_id:
                continue
            existing = self.evidence.get(evidence_id, {})
            status = "read" if tool == "read_chunk_context" else str(existing.get("status") or "discovered")
            self.evidence[evidence_id] = {
                "evidence_id": evidence_id,
                "citation": str(entry.get("citation") or existing.get("citation") or ""),
                "source_type": str(entry.get("source_type") or existing.get("source_type") or ""),
                "item_key": str(entry.get("item_key") or existing.get("item_key") or ""),
                "chunk_id": str(entry.get("chunk_id") or existing.get("chunk_id") or ""),
                "title": str(entry.get("title") or existing.get("title") or ""),
                "section_title": str(entry.get("section_title") or existing.get("section_title") or ""),
                "status": status,
            }
            _append_unique(coverage["evidence_ids"], evidence_id)
            _append_unique(coverage["item_keys"], self.evidence[evidence_id]["item_key"])
            _append_unique(coverage["source_types"], self.evidence[evidence_id]["source_type"])
        if coverage["evidence_ids"]:
            coverage["status"] = "evidence_found"

    def mark_answer_usage(self, answer: str) -> None:
        citations = set(_CITATION_RE.findall(str(answer or "")))
        self.used_evidence_ids = []
        for evidence_id, evidence in self.evidence.items():
            if str(evidence.get("citation") or "") in citations:
                evidence["status"] = "used"
                self.used_evidence_ids.append(evidence_id)
        self.verification["status"] = "pending" if citations else "not_run"

    def apply_verification(self, result: dict[str, Any]) -> None:
        self.verification = dict(result)
        self.verified_evidence_ids = [
            str(value)
            for value in result.get("verified_evidence_ids") or []
            if str(value or "").strip()
        ]
        verified = set(self.verified_evidence_ids)
        used = set(self.used_evidence_ids)
        for evidence_id, evidence in self.evidence.items():
            if evidence_id in verified:
                evidence["status"] = "verified"
            elif evidence_id in used:
                evidence["status"] = "used_unverified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage": {key: dict(value) for key, value in self.coverage.items()},
            "evidence": [dict(self.evidence[key]) for key in self.evidence],
            "gaps": [dict(item) for item in self.gaps],
            "conflicts": [dict(item) for item in self.conflicts],
            "warnings": list(self.warnings),
            "used_evidence_ids": list(self.used_evidence_ids),
            "verified_evidence_ids": list(self.verified_evidence_ids),
            "verification": dict(self.verification),
        }


def _append_unique(values: list[str], value: str) -> None:
    clean_value = str(value or "").strip()
    if clean_value and clean_value not in values:
        values.append(clean_value)


def _requires_content_evidence(question: str, task_type: str) -> bool:
    if task_type == "scope":
        return False
    if task_type == "factual" and _BIBLIOGRAPHIC_QUERY_RE.search(str(question or "")):
        return False
    return True


_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _comparison_item_coverage(question: str, scope_item_keys: list[str]) -> int:
    scope_count = len(scope_item_keys)
    value = str(question or "")
    explicit = re.search(r"(?P<count>\d+|[一二两三四五六七八九十])\s*篇(?:论文|文献)?", value)
    if explicit:
        raw_count = explicit.group("count")
        requested = int(raw_count) if raw_count.isdigit() else _CHINESE_NUMBERS.get(raw_count, 2)
        return min(requested, scope_count) if scope_count else requested
    whole_scope = re.search(r"(?:知识库|库里|库中).*(?:论文|文献)|(?:这些|全部|所有).*(?:论文|文献)", value)
    if whole_scope and scope_count:
        return scope_count
    return min(2, scope_count) if scope_count else 2
