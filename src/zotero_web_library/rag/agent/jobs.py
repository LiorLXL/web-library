from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from zotero_web_library.rag.store import connect

from .loop import PreparedAgenticChat, prepare_agentic_chat_run, run_agentic_chat
from .memory import complete_turn
from .runtime import load_agent_run, reconcile_interrupted_runs


@dataclass(slots=True)
class ActiveAgentJob:
    prepared: PreparedAgenticChat
    cancel_event: threading.Event
    thread: threading.Thread


_AGENT_JOB_LOCK = threading.Lock()
_ACTIVE_AGENT_JOBS: dict[str, ActiveAgentJob] = {}


def start_agentic_chat_job(
    *,
    library: dict[str, Any],
    model_config: dict[str, Any],
    conversation_id: str = "",
    question: str,
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
    client: Any = None,
    restart_of_run_id: str = "",
) -> dict[str, Any]:
    with _AGENT_JOB_LOCK:
        active_run_ids = {
            run_id for run_id, job in _ACTIVE_AGENT_JOBS.items() if job.thread.is_alive()
        }
        reconcile_interrupted_runs(library, active_run_ids=active_run_ids)
        if conversation_id and any(
            job.prepared.session.conversation_id == conversation_id and job.thread.is_alive()
            for job in _ACTIVE_AGENT_JOBS.values()
        ):
            raise ValueError("当前会话已有正在运行的 Agent 任务。")

        prepared = prepare_agentic_chat_run(
            library=library,
            model_config=model_config,
            conversation_id=conversation_id,
            question=question,
            knowledge_base_id=knowledge_base_id,
            item_keys=item_keys,
        )
        if restart_of_run_id:
            prepared.recorder.event(
                "run.restarted",
                summary="已从中断任务的原始用户问题重新开始。",
                payload={"previous_run_id": restart_of_run_id},
                visibility="detail",
            )
            prepared.recorder.checkpoint(
                {
                    "phase": "restarted",
                    "previous_run_id": restart_of_run_id,
                    "resume_policy": "restart_from_user_turn",
                }
            )
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=_execute_agent_job,
            args=(prepared, cancel_event, client),
            daemon=True,
            name=f"agent-{prepared.recorder.run_id[:18]}",
        )
        job = ActiveAgentJob(prepared=prepared, cancel_event=cancel_event, thread=thread)
        _ACTIVE_AGENT_JOBS[prepared.recorder.run_id] = job
        thread.start()

    run = load_agent_run(library, prepared.recorder.run_id)
    return {
        "ok": True,
        "accepted": True,
        "run_id": prepared.recorder.run_id,
        "conversation_id": prepared.session.conversation_id,
        "status": run.get("status") or "running",
        "current_state": run.get("current_state") or "plan",
        "task_plan": run.get("task_plan") or prepared.recorder.task_plan.to_dict(),
        "events": run.get("events") or prepared.recorder.trace(),
        "user_message": {
            "role": "user",
            "content": prepared.question,
            "run_id": prepared.recorder.run_id,
            "turn_index": prepared.turn_index,
        },
    }


def cancel_agent_chat_job(library: dict[str, Any], run_id: str) -> dict[str, Any]:
    clean_run_id = str(run_id or "").strip()
    run = load_agent_run(library, clean_run_id)
    if not run:
        raise ValueError("Agent 运行记录不存在。")
    if run.get("status") != "running":
        return {"ok": True, "cancel_requested": False, "run": run}

    with _AGENT_JOB_LOCK:
        job = _ACTIVE_AGENT_JOBS.get(clean_run_id)
        if not job:
            raise ValueError("任务运行进程已经中断，无法发送取消信号。")
        job.cancel_event.set()
        job.prepared.recorder.event(
            "run.cancel_requested",
            summary="用户已请求停止当前任务。",
            payload={},
            status="pending",
        )
    return {
        "ok": True,
        "cancel_requested": True,
        "run": load_agent_run(library, clean_run_id),
    }


def restart_agent_chat_job(
    *,
    library: dict[str, Any],
    model_config: dict[str, Any],
    run_id: str,
    client: Any = None,
) -> dict[str, Any]:
    clean_run_id = str(run_id or "").strip()
    with _AGENT_JOB_LOCK:
        active_run_ids = {
            active_id for active_id, job in _ACTIVE_AGENT_JOBS.items() if job.thread.is_alive()
        }
        reconcile_interrupted_runs(library, active_run_ids=active_run_ids)
    run = load_agent_run(library, clean_run_id)
    if not run:
        raise ValueError("Agent 运行记录不存在。")
    if run.get("status") != "interrupted":
        raise ValueError("只有已中断的 Agent 任务可以重新开始。")
    checkpoint = run.get("checkpoint") or {}
    if checkpoint.get("restart_allowed") is False:
        raise ValueError("该任务检查点不允许自动重新开始。")
    with connect(library) as conn:
        row = conn.execute(
            """
            SELECT content, conversation_id
            FROM rag_chat_messages
            WHERE run_id = ? AND role = 'user'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (clean_run_id,),
        ).fetchone()
    if not row or not str(row["content"] or "").strip():
        raise ValueError("中断任务缺少原始用户问题，无法安全重新开始。")
    return start_agentic_chat_job(
        library=library,
        model_config=model_config,
        conversation_id=str(row["conversation_id"] or ""),
        question=str(row["content"] or "").strip(),
        client=client,
        restart_of_run_id=clean_run_id,
    )


def active_agent_job_count() -> int:
    with _AGENT_JOB_LOCK:
        return sum(1 for job in _ACTIVE_AGENT_JOBS.values() if job.thread.is_alive())


def active_agent_run_ids() -> set[str]:
    with _AGENT_JOB_LOCK:
        return {run_id for run_id, job in _ACTIVE_AGENT_JOBS.items() if job.thread.is_alive()}


def _execute_agent_job(prepared: PreparedAgenticChat, cancel_event: threading.Event, client: Any) -> None:
    try:
        run_agentic_chat(
            library=prepared.library,
            model_config=prepared.model_config,
            conversation_id=prepared.session.conversation_id,
            question=prepared.question,
            knowledge_base_id=prepared.session.knowledge_base_id,
            item_keys=prepared.session.item_keys,
            client=client,
            prepared=prepared,
            cancel_check=cancel_event.is_set,
        )
    except Exception as exc:  # noqa: BLE001
        run = load_agent_run(prepared.library, prepared.recorder.run_id)
        if run.get("status") == "running":
            prepared.recorder.transition(
                "abstain",
                summary="Agent 后台任务异常停止。",
                payload={"error_code": type(exc).__name__},
                visibility="diagnostic",
            )
            prepared.recorder.finish(
                status="failed",
                stop_reason="internal_error",
                usage={},
                error_code=type(exc).__name__,
            )
        complete_turn(
            prepared.library,
            prepared.session,
            turn_index=prepared.turn_index,
            answer="智能体任务执行失败。请检查模型服务配置或稍后重试。",
            sources=[],
            tool_trace=[],
            run_id=prepared.recorder.run_id,
        )
    finally:
        with _AGENT_JOB_LOCK:
            _ACTIVE_AGENT_JOBS.pop(prepared.recorder.run_id, None)
