from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .evidence import EvidenceAccumulator
from .models import EvidenceState, TaskBudget, TaskPlan
from .runtime import AgentRunRecorder
from .tools import ScopeContext, execute_tool, parse_tool_call, summarize_tool_trace


@dataclass(slots=True)
class ToolExecutionDecision:
    result: dict[str, Any]
    trace: dict[str, Any]
    executed: bool
    force_final: bool = False
    stop_reason: str = ""


@dataclass(slots=True)
class AgentController:
    budget: TaskBudget
    model_calls: int = 0
    tool_calls: int = 0
    search_calls: int = 0
    read_calls: int = 0
    duplicate_calls: int = 0
    judge_calls: int = 0
    repair_calls: int = 0
    _invocations: set[str] = field(default_factory=set)
    _error_counts: dict[str, int] = field(default_factory=dict)

    def max_model_calls(self, *, hard_limit: int) -> int:
        return max(2, min(int(hard_limit), int(self.budget.max_model_calls)))

    def register_model_call(self) -> None:
        self.model_calls += 1

    def register_judge_call(self) -> None:
        self.judge_calls += 1

    def can_run_judge(self) -> bool:
        return self.judge_calls < 1

    def register_repair_call(self) -> None:
        self.repair_calls += 1

    def can_repair(self) -> bool:
        return self.repair_calls < self.budget.max_repair_calls

    def soft_token_budget_exceeded(self, total_tokens: int) -> bool:
        return int(total_tokens or 0) >= int(self.budget.max_total_tokens)

    def completion_gap(self, task_plan: TaskPlan, evidence_state: EvidenceState) -> dict[str, Any]:
        all_evidence = list(evidence_state.evidence.values())
        content_evidence = [
            evidence
            for evidence in all_evidence
            if str(evidence.get("source_type") or "") not in {"", "metadata", "scope"}
        ]
        requires_content = bool(task_plan.completion_conditions.get("requires_content_evidence"))
        if requires_content and not content_evidence:
            return {
                "gap_type": "content_evidence_required",
                "required": 1,
                "observed": 0,
                "observed_item_keys": [],
                "evidence_kind": "content",
            }
        if task_plan.task_type != "comparative":
            return {}
        required = int(task_plan.completion_conditions.get("minimum_item_coverage") or 0)
        coverage_evidence = content_evidence if requires_content else all_evidence
        observed = sorted(
            {
                str(evidence.get("item_key") or "")
                for evidence in coverage_evidence
                if str(evidence.get("item_key") or "")
            }
        )
        if required and len(observed) < required:
            return {
                "gap_type": "minimum_item_coverage_not_met",
                "required": required,
                "observed": len(observed),
                "observed_item_keys": observed,
                "evidence_kind": "content" if requires_content else "any",
            }
        return {}

    def execute(
        self,
        call: Any,
        *,
        library: dict[str, Any],
        scope: ScopeContext,
        accumulator: EvidenceAccumulator,
        recorder: AgentRunRecorder,
    ) -> ToolExecutionDecision:
        name, args, argument_error = parse_tool_call(call)
        clean_name = name or "unknown"
        invocation_key = _invocation_key(clean_name, args, argument_error)

        if not argument_error and invocation_key in self._invocations:
            self.duplicate_calls += 1
            result = {
                "error": "duplicate_invocation",
                "message": "相同工具参数已经执行过，请改变 query、mode、filters 或目标 chunk。",
            }
            trace = summarize_tool_trace(clean_name, args, result)
            recorder.observe_tool(trace, result)
            recorder.event(
                "tool.skipped",
                summary="已跳过一次完全重复的工具调用。",
                payload={"tool": clean_name, "reason": "duplicate_invocation"},
                visibility="detail",
                status="skipped",
            )
            return ToolExecutionDecision(result, trace, executed=False)

        budget_error = self._budget_error(clean_name)
        if budget_error:
            result = {"error": "task_budget_exceeded", "message": budget_error}
            trace = summarize_tool_trace(clean_name, args, result)
            recorder.observe_tool(trace, result)
            return ToolExecutionDecision(
                result,
                trace,
                executed=False,
                force_final=True,
                stop_reason="budget_exceeded",
            )

        self.tool_calls += 1
        if clean_name == "search_evidence":
            self.search_calls += 1
        elif clean_name == "read_chunk_context":
            self.read_calls += 1
        if not argument_error:
            self._invocations.add(invocation_key)

        result, trace = execute_tool(call, library, scope, accumulator)
        recorder.observe_tool(trace, result)
        decision = ToolExecutionDecision(result, trace, executed=True)
        error_code = str(result.get("error") or "")
        if not error_code:
            return decision

        self._error_counts[error_code] = self._error_counts.get(error_code, 0) + 1
        if error_code == "chunk_out_of_scope":
            decision.force_final = True
            decision.stop_reason = "user_action_required"
        elif error_code == "unknown_tool":
            decision.force_final = True
            decision.stop_reason = "internal_error"
        elif error_code == "tool_failed" and self._error_counts[error_code] >= 2:
            decision.force_final = True
            decision.stop_reason = "provider_unavailable"
        recorder.event(
            "controller.error_policy",
            summary=_error_policy_summary(error_code, decision),
            payload={
                "error": error_code,
                "error_count": self._error_counts[error_code],
                "force_final": decision.force_final,
                "stop_reason": decision.stop_reason,
            },
            visibility="detail",
            status="handled",
        )
        return decision

    def snapshot(self) -> dict[str, int]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "search_calls": self.search_calls,
            "read_calls": self.read_calls,
            "duplicate_calls": self.duplicate_calls,
            "judge_calls": self.judge_calls,
            "repair_calls": self.repair_calls,
        }

    def _budget_error(self, tool: str) -> str:
        if self.tool_calls >= self.budget.max_tool_calls:
            return "已达到当前任务的工具调用软预算。"
        if tool == "search_evidence" and self.search_calls >= self.budget.max_search_calls:
            return "已达到当前任务的检索调用软预算。"
        if tool == "read_chunk_context" and self.read_calls >= self.budget.max_read_calls:
            return "已达到当前任务的深读调用软预算。"
        return ""


def _invocation_key(name: str, args: dict[str, Any], argument_error: str) -> str:
    if argument_error:
        return f"{name}:invalid:{argument_error}"
    return json.dumps([name, args], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _error_policy_summary(error_code: str, decision: ToolExecutionDecision) -> str:
    if error_code == "invalid_tool_arguments":
        return "工具参数无效，已将结构化错误返回给模型进行一次修正。"
    if error_code == "chunk_out_of_scope":
        return "目标证据不在会话作用域内，需要用户调整知识库范围。"
    if error_code == "unknown_tool":
        return "模型请求了未注册工具，控制器已停止继续调用。"
    if error_code == "tool_failed" and decision.force_final:
        return "工具连续失败，控制器已停止并保留诊断信息。"
    return "工具错误已返回模型，允许在剩余预算内调整策略。"
