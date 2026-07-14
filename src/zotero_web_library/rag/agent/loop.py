from __future__ import annotations

import json
from typing import Any

from .client import build_client
from .evidence import EvidenceAccumulator
from .memory import ChatSession, get_or_create_session, load_history, save_turn
from .prompts import build_system_prompt
from .tools import TOOL_SCHEMAS, ScopeContext, execute_tool


MAX_TOOL_ITERATIONS = 5
MAX_TOTAL_TOKENS = 60_000


def run_agentic_chat(
    *,
    library: dict[str, Any],
    model_config: dict[str, Any],
    conversation_id: str = "",
    question: str,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    client: Any = None,
) -> dict[str, Any]:
    session = get_or_create_session(
        library,
        conversation_id=conversation_id,
        knowledge_base_id=knowledge_base_id,
        item_keys=item_keys,
    )
    scope = ScopeContext(session.knowledge_base_id, session.item_keys)
    accumulator = EvidenceAccumulator()
    active_client = client or build_client(model_config)

    history = load_history(library, session.conversation_id, limit_turns=10)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(max_tool_iterations=MAX_TOOL_ITERATIONS)},
        *history,
        {"role": "user", "content": question},
    ]
    tool_trace: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    llm_calls = 0

    for iteration in range(MAX_TOOL_ITERATIONS):
        force_final = iteration == MAX_TOOL_ITERATIONS - 1
        resp = active_client.chat.completions.create(
            model=str(model_config.get("model") or ""),
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="none" if force_final else "auto",
            temperature=0.2,
        )
        llm_calls += 1
        _accumulate_usage(total_usage, _response_usage(resp))
        msg = _response_message(resp)
        messages.append(_message_to_dict(msg))
        tool_calls = _message_tool_calls(msg)

        if not tool_calls:
            return _finalize(
                library,
                session,
                question=question,
                answer=_message_content(msg) or _fallback_final_answer(accumulator),
                accumulator=accumulator,
                tool_trace=tool_trace,
                usage=total_usage,
                warnings=warnings,
                iterations=llm_calls,
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
            )

        for index, call in enumerate(tool_calls):
            result, trace = execute_tool(call, library, scope, accumulator)
            tool_trace.append(trace)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": _tool_call_id(call) or f"tool-{llm_calls}-{index}",
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        if total_usage["total_tokens"] >= MAX_TOTAL_TOKENS:
            warnings.append("token_budget_exceeded")
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
) -> dict[str, Any]:
    resp = client.chat.completions.create(
        model=str(model_config.get("model") or ""),
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="none",
        temperature=0.2,
    )
    iterations += 1
    _accumulate_usage(usage, _response_usage(resp))
    msg = _response_message(resp)
    messages.append(_message_to_dict(msg))
    if _message_tool_calls(msg):
        warnings.append("final_tool_calls_ignored")
        answer = _fallback_final_answer(accumulator)
    else:
        answer = _message_content(msg) or _fallback_final_answer(accumulator)
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
) -> dict[str, Any]:
    sources = accumulator.all_sources()
    save_turn(library, session, question=question, answer=answer, sources=sources, tool_trace=tool_trace)
    return {
        "ok": True,
        "conversation_id": session.conversation_id,
        "answer": answer,
        "sources": sources,
        "tool_trace": tool_trace,
        "iterations": iterations,
        "usage": dict(usage),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _fallback_final_answer(accumulator: EvidenceAccumulator) -> str:
    if accumulator.all_sources():
        return "已达到工具调用或检索预算上限，无法继续检索；请基于当前已检索证据缩小问题后重试。"
    return "当前没有获得可用证据，无法基于所选知识库回答这个问题。"


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
