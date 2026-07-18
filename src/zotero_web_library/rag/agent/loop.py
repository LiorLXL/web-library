from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from zotero_web_library.rag.query import build_query_plan

from .client import build_client
from .controller import AgentController
from .evidence import EvidenceAccumulator
from .memory import ChatSession, begin_turn, complete_turn, get_or_create_session, load_history
from .models import EvidenceState, TaskPlan
from .prompts import build_system_prompt
from .runtime import AgentRunRecorder
from .tools import TOOL_SCHEMAS, ScopeContext
from .verifier import (
    AnswerEnvelope,
    insufficient_answer,
    parse_answer_envelope,
    parse_semantic_judgement,
    prune_to_verified,
    repair_prompt,
    semantic_judge_prompt,
    verify_answer,
)


MAX_TOOL_ITERATIONS = 5
MAX_TOTAL_TOKENS = 60_000


@dataclass(slots=True)
class PreparedAgenticChat:
    library: dict[str, Any]
    model_config: dict[str, Any]
    session: ChatSession
    question: str
    history: list[dict[str, str]]
    turn_index: int
    recorder: AgentRunRecorder


def prepare_agentic_chat_run(
    *,
    library: dict[str, Any],
    model_config: dict[str, Any],
    conversation_id: str = "",
    question: str,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> PreparedAgenticChat:
    session = get_or_create_session(
        library,
        conversation_id=conversation_id,
        knowledge_base_id=knowledge_base_id,
        item_keys=item_keys,
    )
    history = load_history(library, session.conversation_id, limit_turns=10)
    query_plan = build_query_plan(question)
    task_plan = TaskPlan.initial(
        question,
        task_type=str(query_plan.get("task_type") or "factual"),
        scope_item_keys=session.item_keys,
        planned_queries=query_plan.get("queries") if isinstance(query_plan.get("queries"), list) else None,
    )
    evidence_state = EvidenceState.for_plan(task_plan)
    recorder = AgentRunRecorder.create(
        library,
        conversation_id=session.conversation_id,
        task_plan=task_plan,
        evidence_state=evidence_state,
    )
    turn = begin_turn(
        library,
        session,
        question=question,
        run_id=recorder.run_id,
    )
    return PreparedAgenticChat(
        library=library,
        model_config=model_config,
        session=session,
        question=question,
        history=history,
        turn_index=turn.turn_index,
        recorder=recorder,
    )


def run_agentic_chat(
    *,
    library: dict[str, Any],
    model_config: dict[str, Any],
    conversation_id: str = "",
    question: str,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    client: Any = None,
    prepared: PreparedAgenticChat | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    active_run = prepared or prepare_agentic_chat_run(
        library=library,
        model_config=model_config,
        conversation_id=conversation_id,
        question=question,
        knowledge_base_id=knowledge_base_id,
        item_keys=item_keys,
    )
    library = active_run.library
    model_config = active_run.model_config
    session = active_run.session
    question = active_run.question
    scope = ScopeContext(session.knowledge_base_id, session.item_keys)
    accumulator = EvidenceAccumulator()
    recorder = active_run.recorder
    controller = AgentController(recorder.task_plan.budget)
    try:
        active_client = client or build_client(model_config)
    except Exception as exc:
        recorder.transition(
            "abstain",
            summary="模型客户端初始化失败，任务无法继续。",
            payload={"error_code": type(exc).__name__},
            visibility="diagnostic",
        )
        recorder.finish(
            status="failed",
            stop_reason="provider_unavailable",
            usage={},
            error_code=type(exc).__name__,
        )
        raise

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(max_tool_iterations=MAX_TOOL_ITERATIONS)},
        {"role": "system", "content": _task_plan_instruction(recorder.task_plan.to_dict())},
        *active_run.history,
        {"role": "user", "content": question},
    ]
    tool_trace: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    llm_calls = 0
    max_model_calls = controller.max_model_calls(hard_limit=MAX_TOOL_ITERATIONS)

    for iteration in range(max_model_calls):
        if _is_cancelled(cancel_check):
            return _cancel_run(active_run, accumulator, tool_trace, total_usage, warnings, controller)
        force_final = iteration == max_model_calls - 1
        recorder.transition(
            "inspect",
            summary="正在检查当前证据并选择下一步。",
            payload={"controller": controller.snapshot()},
            visibility="detail",
        )
        resp = _model_completion(
            active_client,
            model_config,
            messages,
            tool_choice="none" if force_final else "auto",
            recorder=recorder,
        )
        llm_calls += 1
        controller.register_model_call()
        _accumulate_usage(total_usage, _response_usage(resp))
        recorder.checkpoint(
            {
                "phase": "model_completed",
                "iteration": iteration + 1,
                "usage": dict(total_usage),
                "controller": controller.snapshot(),
            }
        )
        if _is_cancelled(cancel_check):
            return _cancel_run(active_run, accumulator, tool_trace, total_usage, warnings, controller)
        msg = _response_message(resp)
        messages.append(_message_to_dict(msg))
        tool_calls = _message_tool_calls(msg)

        if not tool_calls:
            content = _message_content(msg)
            completion_gap = (
                {}
                if _declares_insufficient_answer(content)
                else controller.completion_gap(recorder.task_plan, recorder.evidence_state)
            )
            if completion_gap and not force_final:
                recorder.event(
                    "plan.revised",
                    summary=_completion_gap_summary(completion_gap),
                    payload=completion_gap,
                    visibility="detail",
                    status="pending",
                )
                messages.append(
                    {
                        "role": "user",
                        "content": _completion_gap_instruction(completion_gap),
                    }
                )
                continue
            if completion_gap:
                return _finalize(
                    library,
                    session,
                    question=question,
                    answer=_completion_gap_answer(completion_gap),
                    accumulator=accumulator,
                    tool_trace=tool_trace,
                    usage=total_usage,
                    warnings=[*warnings, str(completion_gap.get("gap_type") or "insufficient_evidence")],
                    iterations=llm_calls,
                    recorder=recorder,
                    run_status="abstained",
                    stop_reason="insufficient_evidence",
                    turn_index=active_run.turn_index,
                    controller=controller,
                )
            if content:
                return _verify_and_finalize(
                    active_client,
                    model_config,
                    library,
                    session,
                    question=question,
                    answer=content,
                    accumulator=accumulator,
                    tool_trace=tool_trace,
                    usage=total_usage,
                    warnings=warnings,
                    iterations=llm_calls,
                    recorder=recorder,
                    stop_reason="completed",
                    turn_index=active_run.turn_index,
                    controller=controller,
                    cancel_check=cancel_check,
                )
            return _finalize(
                library,
                session,
                question=question,
                answer=_fallback_final_answer(accumulator),
                accumulator=accumulator,
                tool_trace=tool_trace,
                usage=total_usage,
                warnings=warnings,
                iterations=llm_calls,
                recorder=recorder,
                run_status="abstained",
                stop_reason="insufficient_evidence",
                turn_index=active_run.turn_index,
                controller=controller,
            )

        if force_final:
            warnings.append("final_tool_calls_ignored")
            return _finalize(
                library,
                session,
                question=question,
                answer=_fallback_final_answer(accumulator),
                accumulator=accumulator,
                tool_trace=tool_trace,
                usage=total_usage,
                warnings=warnings,
                iterations=llm_calls,
                recorder=recorder,
                run_status="abstained",
                stop_reason="budget_exceeded",
                turn_index=active_run.turn_index,
                controller=controller,
            )

        force_after_tools = False
        forced_stop_reason = ""
        for index, call in enumerate(tool_calls):
            decision = controller.execute(
                call,
                library=library,
                scope=scope,
                accumulator=accumulator,
                recorder=recorder,
            )
            result, trace = decision.result, decision.trace
            tool_trace.append(trace)
            for warning in result.get("warnings") or []:
                if warning not in warnings:
                    warnings.append(str(warning))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": _tool_call_id(call) or f"tool-{llm_calls}-{index}",
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            if decision.force_final:
                force_after_tools = True
                forced_stop_reason = decision.stop_reason or "budget_exceeded"
            if _is_cancelled(cancel_check):
                return _cancel_run(active_run, accumulator, tool_trace, total_usage, warnings, controller)

        recorder.transition(
            "inspect",
            summary="已检查本轮工具结果和证据覆盖。",
            payload={
                "controller": controller.snapshot(),
                "evidence_count": len(recorder.evidence_state.evidence),
                "gap_count": len(recorder.evidence_state.gaps),
            },
        )
        recorder.checkpoint(
            {
                "phase": "tool_round_completed",
                "iteration": iteration + 1,
                "usage": dict(total_usage),
                "controller": controller.snapshot(),
                "tool_trace_count": len(tool_trace),
            }
        )

        if force_after_tools:
            messages.append({"role": "user", "content": "当前执行策略已经停止，请基于已有证据回答或明确说明不足。"})
            return _force_answer(
                active_client,
                model_config,
                messages,
                library,
                session,
                question=question,
                accumulator=accumulator,
                tool_trace=tool_trace,
                usage=total_usage,
                warnings=warnings,
                iterations=llm_calls,
                recorder=recorder,
                turn_index=active_run.turn_index,
                controller=controller,
                stop_reason=forced_stop_reason,
                cancel_check=cancel_check,
            )

        if total_usage["total_tokens"] >= MAX_TOTAL_TOKENS or controller.soft_token_budget_exceeded(total_usage["total_tokens"]):
            warning = "token_budget_exceeded" if total_usage["total_tokens"] >= MAX_TOTAL_TOKENS else "task_token_budget_exceeded"
            warnings.append(warning)
            messages.append({"role": "user", "content": "已达检索预算上限，请基于已有证据直接作答。"})
            return _force_answer(
                active_client,
                model_config,
                messages,
                library,
                session,
                question=question,
                accumulator=accumulator,
                tool_trace=tool_trace,
                usage=total_usage,
                warnings=warnings,
                iterations=llm_calls,
                recorder=recorder,
                turn_index=active_run.turn_index,
                controller=controller,
                stop_reason="budget_exceeded",
                cancel_check=cancel_check,
            )

    return _finalize(
        library,
        session,
        question=question,
        answer=_fallback_final_answer(accumulator),
        accumulator=accumulator,
        tool_trace=tool_trace,
        usage=total_usage,
        warnings=warnings,
        iterations=llm_calls,
        recorder=recorder,
        run_status="abstained",
        stop_reason="budget_exceeded",
        turn_index=active_run.turn_index,
        controller=controller,
    )


def _force_answer(
    client: Any,
    model_config: dict[str, Any],
    messages: list[dict[str, Any]],
    library: dict[str, Any],
    session: ChatSession,
    *,
    question: str,
    accumulator: EvidenceAccumulator,
    tool_trace: list[dict[str, Any]],
    usage: dict[str, int],
    warnings: list[str],
    iterations: int,
    recorder: AgentRunRecorder,
    turn_index: int,
    controller: AgentController,
    stop_reason: str,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if _is_cancelled(cancel_check):
        active_run = PreparedAgenticChat(
            library=library,
            model_config=model_config,
            session=session,
            question=question,
            history=[],
            turn_index=turn_index,
            recorder=recorder,
        )
        return _cancel_run(active_run, accumulator, tool_trace, usage, warnings, controller)
    recorder.transition(
        "verify",
        summary="预算或错误策略已触发收尾，正在检查现有证据。",
        payload={"stop_reason": stop_reason, "controller": controller.snapshot()},
    )
    resp = _model_completion(
        client,
        model_config,
        messages,
        tool_choice="none",
        recorder=recorder,
    )
    iterations += 1
    controller.register_model_call()
    _accumulate_usage(usage, _response_usage(resp))
    if _is_cancelled(cancel_check):
        active_run = PreparedAgenticChat(
            library=library,
            model_config=model_config,
            session=session,
            question=question,
            history=[],
            turn_index=turn_index,
            recorder=recorder,
        )
        return _cancel_run(active_run, accumulator, tool_trace, usage, warnings, controller)
    msg = _response_message(resp)
    messages.append(_message_to_dict(msg))
    if _message_tool_calls(msg):
        warnings.append("final_tool_calls_ignored")
        answer = _fallback_final_answer(accumulator)
        run_status = "abstained"
    else:
        answer = _message_content(msg) or _fallback_final_answer(accumulator)
        run_status = "completed" if _message_content(msg) else "abstained"
    if run_status == "completed":
        return _verify_and_finalize(
            client,
            model_config,
            library,
            session,
            question=question,
            answer=answer,
            accumulator=accumulator,
            tool_trace=tool_trace,
            usage=usage,
            warnings=warnings,
            iterations=iterations,
            recorder=recorder,
            stop_reason=stop_reason,
            turn_index=turn_index,
            controller=controller,
            cancel_check=cancel_check,
        )
    return _finalize(
        library,
        session,
        question=question,
        answer=answer,
        accumulator=accumulator,
        tool_trace=tool_trace,
        usage=usage,
        warnings=warnings,
        iterations=iterations,
        recorder=recorder,
        run_status=run_status,
        stop_reason=stop_reason,
        turn_index=turn_index,
        controller=controller,
    )


def _verify_and_finalize(
    client: Any,
    model_config: dict[str, Any],
    library: dict[str, Any],
    session: ChatSession,
    *,
    question: str,
    answer: str,
    accumulator: EvidenceAccumulator,
    tool_trace: list[dict[str, Any]],
    usage: dict[str, int],
    warnings: list[str],
    iterations: int,
    recorder: AgentRunRecorder,
    stop_reason: str,
    turn_index: int,
    controller: AgentController,
    cancel_check: Callable[[], bool] | None,
) -> dict[str, Any]:
    recorder.transition(
        "verify",
        summary="正在执行充分性门槛和逐条主张验证。",
        payload={"controller": controller.snapshot()},
    )
    evidence = accumulator.verification_evidence()
    envelope = parse_answer_envelope(answer)
    verification = verify_answer(
        envelope,
        task_plan=recorder.task_plan,
        evidence=evidence,
        scope_item_keys=session.item_keys,
    )
    recorder.event(
        "verification.hard_gate",
        summary=_verification_summary(verification),
        payload={
            "status": verification.get("status"),
            "hard_gate_passed": verification.get("hard_gate_passed"),
            "claim_count": verification.get("claim_count"),
            "issue_codes": [item.get("code") for item in verification.get("issues") or []],
        },
        visibility="detail",
        status=str(verification.get("status") or "failed"),
    )

    if verification.get("semantic_judge_required") and controller.can_run_judge():
        response = _auxiliary_completion(
            client,
            model_config,
            semantic_judge_prompt(envelope, verification, evidence),
            recorder=recorder,
            operation="semantic_judge",
        )
        controller.register_judge_call()
        iterations += 1
        if response is not None:
            _accumulate_usage(usage, _response_usage(response))
            pending_ids = {
                str(item.get("claim_id") or "")
                for item in verification.get("claims") or []
                if item.get("status") == "pending_semantic"
            }
            decisions = parse_semantic_judgement(_message_content(_response_message(response)), pending_ids)
            if decisions:
                verification = verify_answer(
                    envelope,
                    task_plan=recorder.task_plan,
                    evidence=evidence,
                    scope_item_keys=session.item_keys,
                    semantic_decisions=decisions,
                )
            else:
                warnings.append("semantic_judge_invalid_response")
        else:
            warnings.append("semantic_judge_failed")

    if _is_cancelled(cancel_check):
        return _finalize(
            library,
            session,
            question=question,
            answer="已停止本次知识库任务。验证前的候选回答不会保存为最终答案。",
            accumulator=accumulator,
            tool_trace=tool_trace,
            usage=usage,
            warnings=[*warnings, "cancelled"],
            iterations=iterations,
            recorder=recorder,
            run_status="cancelled",
            stop_reason="cancelled",
            turn_index=turn_index,
            controller=controller,
        )

    can_repair = (
        verification.get("status") != "verified"
        and bool(evidence)
        and stop_reason == "completed"
        and controller.can_repair()
        and usage.get("total_tokens", 0) < min(MAX_TOTAL_TOKENS, controller.budget.max_total_tokens)
    )
    if can_repair:
        recorder.event(
            "verification.repair_started",
            summary="验证未通过，正在执行唯一一次受控修复。",
            payload={"issue_count": len(verification.get("issues") or [])},
            visibility="detail",
            status="pending",
        )
        response = _auxiliary_completion(
            client,
            model_config,
            repair_prompt(envelope, verification, evidence),
            recorder=recorder,
            operation="answer_repair",
        )
        controller.register_repair_call()
        iterations += 1
        if response is not None:
            _accumulate_usage(usage, _response_usage(response))
            repaired_content = _message_content(_response_message(response))
            repaired = parse_answer_envelope(repaired_content)
            if repaired.answer_markdown:
                envelope = repaired
                verification = verify_answer(
                    envelope,
                    task_plan=recorder.task_plan,
                    evidence=evidence,
                    scope_item_keys=session.item_keys,
                )
                if verification.get("semantic_judge_required") and controller.can_run_judge():
                    judge_response = _auxiliary_completion(
                        client,
                        model_config,
                        semantic_judge_prompt(envelope, verification, evidence),
                        recorder=recorder,
                        operation="semantic_judge",
                    )
                    controller.register_judge_call()
                    iterations += 1
                    if judge_response is not None:
                        _accumulate_usage(usage, _response_usage(judge_response))
                        pending_ids = {
                            str(item.get("claim_id") or "")
                            for item in verification.get("claims") or []
                            if item.get("status") == "pending_semantic"
                        }
                        decisions = parse_semantic_judgement(
                            _message_content(_response_message(judge_response)),
                            pending_ids,
                        )
                        if decisions:
                            verification = verify_answer(
                                envelope,
                                task_plan=recorder.task_plan,
                                evidence=evidence,
                                scope_item_keys=session.item_keys,
                                semantic_decisions=decisions,
                            )
            else:
                warnings.append("answer_repair_invalid_response")
        else:
            warnings.append("answer_repair_failed")

    run_status = "completed"
    final_stop_reason = stop_reason
    if verification.get("status") != "verified":
        pruned = prune_to_verified(envelope, verification)
        if pruned.answer_markdown:
            pruned_verification = verify_answer(
                pruned,
                task_plan=recorder.task_plan,
                evidence=evidence,
                scope_item_keys=session.item_keys,
            )
            if pruned_verification.get("status") == "verified":
                envelope = pruned
                verification = pruned_verification
                warnings.append("unsupported_claims_removed")
        if verification.get("status") != "verified":
            envelope = AnswerEnvelope(insufficient_answer(verification), [], [], structured=True)
            run_status = "abstained"
            final_stop_reason = "insufficient_evidence"
            warnings.append("answer_verification_failed")

    recorder.event(
        "verification.completed",
        summary=_verification_summary(verification),
        payload={
            "status": verification.get("status"),
            "claim_count": verification.get("claim_count"),
            "supported_claim_count": verification.get("supported_claim_count"),
            "verified_source_count": len(verification.get("verified_evidence_ids") or []),
            "repair_calls": controller.repair_calls,
            "judge_calls": controller.judge_calls,
        },
        visibility="detail",
        status=str(verification.get("status") or "failed"),
    )
    return _finalize(
        library,
        session,
        question=question,
        answer=envelope.answer_markdown,
        accumulator=accumulator,
        tool_trace=tool_trace,
        usage=usage,
        warnings=warnings,
        iterations=iterations,
        recorder=recorder,
        run_status=run_status,
        stop_reason=final_stop_reason,
        turn_index=turn_index,
        controller=controller,
        answer_envelope=envelope,
        verification=verification,
    )


def _finalize(
    library: dict[str, Any],
    session: ChatSession,
    *,
    question: str,
    answer: str,
    accumulator: EvidenceAccumulator,
    tool_trace: list[dict[str, Any]],
    usage: dict[str, int],
    warnings: list[str],
    iterations: int,
    recorder: AgentRunRecorder,
    run_status: str,
    stop_reason: str,
    turn_index: int,
    controller: AgentController,
    answer_envelope: AnswerEnvelope | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recorder.evidence_state.mark_answer_usage(answer)
    if verification is not None:
        recorder.evidence_state.apply_verification(verification)
    verified_ids = set(verification.get("verified_evidence_ids") or []) if verification else set()
    sources = accumulator.sources_by_evidence_ids(verified_ids)
    if recorder.current_state != "verify":
        recorder.transition(
            "verify",
            summary="正在检查回答与当前证据覆盖。",
            payload={
                "source_count": len(sources),
                "citation_count": len(recorder.evidence_state.used_evidence_ids),
            },
        )
    terminal_state = "answer" if run_status == "completed" else "abstain"
    terminal_summary = "正在整理最终回答。" if terminal_state == "answer" else "现有证据不足以继续完成任务。"
    if run_status == "cancelled":
        terminal_summary = "已收到取消请求，停止后续执行。"
    recorder.transition(
        terminal_state,
        summary=terminal_summary,
        payload={
            "source_count": len(sources),
            "used_evidence_count": len(recorder.evidence_state.used_evidence_ids),
        },
    )
    complete_turn(
        library,
        session,
        turn_index=turn_index,
        answer=answer,
        sources=sources,
        tool_trace=tool_trace,
        run_id=recorder.run_id,
    )
    for subquestion in recorder.task_plan.subquestions:
        subquestion.status = "answered" if run_status == "completed" else "unresolved"
    recorder.task_plan.status = "completed" if run_status == "completed" else "stopped"
    run = recorder.finish(
        status=run_status,
        stop_reason=stop_reason,
        usage=usage,
    )
    return {
        "ok": True,
        "conversation_id": session.conversation_id,
        "run_id": recorder.run_id,
        "answer": answer,
        "sources": sources,
        "tool_trace": tool_trace,
        "agent_trace": run.get("events") or recorder.trace(),
        "agent_state": {
            "current_state": run.get("current_state") or terminal_state,
            "status": run.get("status") or run_status,
            "task_plan": run.get("task_plan") or recorder.task_plan.to_dict(),
            "evidence_state": run.get("evidence_state") or recorder.evidence_state.to_dict(),
            "controller": controller.snapshot(),
        },
        "stop_reason": stop_reason,
        "claims": [dict(claim) for claim in (answer_envelope.claims if answer_envelope else [])],
        "citations": list(answer_envelope.citations if answer_envelope else []),
        "verification": dict(verification or {}),
        "iterations": iterations,
        "usage": dict(usage),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _cancel_run(
    prepared: PreparedAgenticChat,
    accumulator: EvidenceAccumulator,
    tool_trace: list[dict[str, Any]],
    usage: dict[str, int],
    warnings: list[str],
    controller: AgentController,
) -> dict[str, Any]:
    if "cancelled" not in warnings:
        warnings.append("cancelled")
    return _finalize(
        prepared.library,
        prepared.session,
        question=prepared.question,
        answer="已停止本次知识库任务。已完成的检索步骤会保留在运行记录中。",
        accumulator=accumulator,
        tool_trace=tool_trace,
        usage=usage,
        warnings=warnings,
        iterations=controller.model_calls,
        recorder=prepared.recorder,
        run_status="cancelled",
        stop_reason="cancelled",
        turn_index=prepared.turn_index,
        controller=controller,
    )


def _is_cancelled(cancel_check: Callable[[], bool] | None) -> bool:
    return bool(cancel_check and cancel_check())


def _model_completion(
    client: Any,
    model_config: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    tool_choice: str,
    recorder: AgentRunRecorder,
) -> Any:
    try:
        return client.chat.completions.create(
            model=str(model_config.get("model") or ""),
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice=tool_choice,
            temperature=0.2,
        )
    except Exception as exc:
        recorder.transition(
            "abstain",
            summary="模型服务调用失败，任务无法继续。",
            payload={"error_code": type(exc).__name__},
            visibility="diagnostic",
        )
        recorder.finish(
            status="failed",
            stop_reason="provider_unavailable",
            usage={},
            error_code=type(exc).__name__,
        )
        raise


def _auxiliary_completion(
    client: Any,
    model_config: dict[str, Any],
    prompt: str,
    *,
    recorder: AgentRunRecorder,
    operation: str,
) -> Any | None:
    try:
        return client.chat.completions.create(
            model=str(model_config.get("model") or ""),
            messages=[
                {
                    "role": "system",
                    "content": "You are a constrained JSON-only verifier inside a scoped RAG runtime.",
                },
                {"role": "user", "content": prompt},
            ],
            tools=TOOL_SCHEMAS,
            tool_choice="none",
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        recorder.event(
            "verification.auxiliary_failed",
            summary="验证辅助调用失败，控制器将按确定性规则降级。",
            payload={"operation": operation, "error_code": type(exc).__name__},
            visibility="diagnostic",
            status="failed",
        )
        return None


def _verification_summary(verification: dict[str, Any]) -> str:
    status = str(verification.get("status") or "failed")
    supported = int(verification.get("supported_claim_count") or 0)
    total = int(verification.get("claim_count") or 0)
    if status == "verified":
        return f"回答验证通过：{supported}/{total} 条事实主张具有有效证据。"
    if status == "pending_semantic":
        return f"硬门槛已通过，{int(verification.get('pending_claim_count') or 0)} 条主张需要语义支持判断。"
    return f"回答验证未通过：{supported}/{total} 条事实主张获得支持。"


def _fallback_final_answer(accumulator: EvidenceAccumulator) -> str:
    if accumulator.all_sources():
        return "已达到工具调用或检索预算上限，无法继续检索；请基于当前已检索证据缩小问题后重试。"
    return "当前没有获得可用证据，无法基于所选知识库回答这个问题。"


def _completion_gap_summary(gap: dict[str, Any]) -> str:
    if str(gap.get("gap_type") or "") == "content_evidence_required":
        return "当前只有题录信息，正在要求检索正文证据。"
    return "比较任务的正文文献覆盖不足，正在要求补充检索。"


def _completion_gap_instruction(gap: dict[str, Any]) -> str:
    if str(gap.get("gap_type") or "") == "content_evidence_required":
        return (
            "控制器检查到当前只有元数据，尚未取得回答内容问题所需的正文证据。"
            "请调用 search_evidence 检索摘要、方法、结果或段落 chunk；必要时再深读上下文，不要直接作答。"
        )
    return (
        "控制器检查到比较任务的正文证据覆盖不足。"
        f"当前覆盖 {int(gap.get('observed') or 0)} 篇，至少需要 {int(gap.get('required') or 0)} 篇。"
        "请按尚未覆盖的文献继续检索或深读正文；不要重复完全相同的参数。"
    )


def _completion_gap_answer(gap: dict[str, Any]) -> str:
    if str(gap.get("gap_type") or "") == "content_evidence_required":
        return "当前只取得题录信息，尚未检索到回答该内容问题所需的正文证据。"
    return (
        "当前正文证据覆盖不足，无法完成可靠的跨论文比较。"
        f"已覆盖 {int(gap.get('observed') or 0)} 篇，任务至少需要 {int(gap.get('required') or 0)} 篇。"
    )


def _declares_insufficient_answer(answer: str) -> bool:
    value = str(answer or "").casefold()
    return any(
        marker in value
        for marker in (
            "证据不足",
            "无法回答",
            "没有获得可用证据",
            "未找到证据",
            "insufficient evidence",
            "evidence is insufficient",
        )
    )


def _task_plan_instruction(task_plan: dict[str, Any]) -> str:
    return (
        "下面是服务端控制器生成的任务计划。它只描述当前会话内的目标、子问题、完成条件和软预算；"
        "不得扩大知识库作用域。优先覆盖未解决子问题，工具失败时根据结构化错误调整参数或明确停止。"
        "准备最终回答时返回 JSON 对象，字段为 answer_markdown、claims、citations；claims 中每项包含 "
        "claim_id、text、citations、factual。citation 必须原样来自工具结果并紧邻 answer_markdown 中的事实主张。\n"
        f"TaskPlan: {json.dumps(task_plan, ensure_ascii=False, separators=(',', ':'))}"
    )


def _response_message(response: Any) -> Any:
    choices = _get(response, "choices", []) or []
    if not choices:
        return {}
    return _get(choices[0], "message", {})


def _response_usage(response: Any) -> Any:
    return _get(response, "usage", {})


def _message_content(message: Any) -> str:
    return str(_get(message, "content", "") or "")


def _message_tool_calls(message: Any) -> list[Any]:
    value = _get(message, "tool_calls", []) or []
    return value if isinstance(value, list) else []


def _message_to_dict(message: Any) -> dict[str, Any]:
    payload = _plain(message)
    if isinstance(payload, dict):
        payload.setdefault("role", "assistant")
        return payload
    return {"role": "assistant", "content": str(payload or "")}


def _tool_call_id(call: Any) -> str:
    return str(_get(call, "id", "") or "")


def _accumulate_usage(total: dict[str, int], usage: Any) -> None:
    payload = _plain(usage)
    if not isinstance(payload, dict):
        payload = {}
    prompt = _int(payload.get("prompt_tokens", payload.get("input_tokens", 0)))
    completion = _int(payload.get("completion_tokens", payload.get("output_tokens", 0)))
    total_tokens = _int(payload.get("total_tokens", prompt + completion))
    if total_tokens <= 0:
        total_tokens = prompt + completion
    total["prompt_tokens"] += prompt
    total["completion_tokens"] += completion
    total["total_tokens"] += total_tokens


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items() if item is not None}
    return value


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
