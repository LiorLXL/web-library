from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from zotero_web_library.rag.store import connect, ensure_store, json_dumps
from zotero_web_library.utils import now_iso

from .models import AGENT_STATES, RUN_STATUSES, STOP_REASONS, EvidenceState, TaskPlan


PROCESS_WORKER_ID = f"worker-{uuid.uuid4().hex}"
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "password",
    "authorization",
    "cookie",
    "set_cookie",
}
_SENSITIVE_KEY_SUFFIXES = ("_api_key", "_token", "_secret", "_password")


@dataclass(slots=True)
class AgentRunRecorder:
    library: dict[str, Any]
    run_id: str
    conversation_id: str
    current_state: str
    task_plan: TaskPlan
    evidence_state: EvidenceState
    event_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def create(
        cls,
        library: dict[str, Any],
        *,
        conversation_id: str,
        task_plan: TaskPlan,
        evidence_state: EvidenceState,
    ) -> "AgentRunRecorder":
        ensure_store(library)
        timestamp = now_iso()
        run_id = f"run-{uuid.uuid4().hex}"
        with connect(library) as conn:
            conn.execute(
                """
                INSERT INTO rag_agent_runs (
                  run_id, conversation_id, library_id, status, current_state,
                  task_plan_json, evidence_state_json, budget_json, usage_json,
                  checkpoint_json, worker_id, heartbeat_at,
                  stop_reason, error_code, created_at, updated_at, finished_at
                )
                VALUES (?, ?, ?, 'running', 'plan', ?, ?, ?, '{}', '{}', ?, ?, '', '', ?, ?, '')
                """,
                (
                    run_id,
                    conversation_id,
                    str(library["library_id"]),
                    json_dumps(task_plan.to_dict()),
                    json_dumps(evidence_state.to_dict()),
                    json_dumps(task_plan.budget.to_dict()),
                    PROCESS_WORKER_ID,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()
        recorder = cls(library, run_id, conversation_id, "plan", task_plan, evidence_state)
        recorder.event("run.started", summary="Agent 已开始处理任务。")
        recorder.event(
            "plan.created",
            summary=f"已识别为 {task_plan.task_type} 任务，并建立初始计划。",
            payload={
                "task_type": task_plan.task_type,
                "subquestion_count": len(task_plan.subquestions),
                "budget": task_plan.budget.to_dict(),
            },
        )
        recorder.checkpoint({"phase": "created", "restart_allowed": True})
        return recorder

    def transition(
        self,
        state: str,
        *,
        summary: str,
        payload: dict[str, Any] | None = None,
        visibility: str = "summary",
    ) -> None:
        clean_state = str(state or "").strip()
        if clean_state not in AGENT_STATES:
            raise ValueError(f"unknown agent state: {state}")
        self.current_state = clean_state
        timestamp = now_iso()
        with connect(self.library) as conn:
            conn.execute(
                "UPDATE rag_agent_runs SET current_state = ?, updated_at = ?, heartbeat_at = ? WHERE run_id = ?",
                (clean_state, timestamp, timestamp, self.run_id),
            )
            conn.commit()
        self.event("state.entered", summary=summary, payload=payload, visibility=visibility)
        self.checkpoint({"transition_summary": summary, "transition_payload": payload or {}})

    def observe_tool(self, trace: dict[str, Any], result: dict[str, Any]) -> None:
        tool = str(trace.get("tool") or "unknown")
        state = "retrieve"
        if tool == "read_chunk_context":
            state = "read"
        elif tool == "list_scope_documents":
            state = "inspect"
        self.transition(
            state,
            summary=_tool_summary(tool, trace),
            payload={
                "tool": tool,
                "args": trace.get("args") or {},
                "ok": bool(trace.get("ok")),
                "result_count": trace.get("result_count"),
                "warnings": trace.get("warnings") or [],
                "error": trace.get("error") or "",
            },
        )
        self.evidence_state.observe_tool_result(tool, result)
        self.persist_evidence_state()

    def persist_evidence_state(self) -> None:
        with connect(self.library) as conn:
            conn.execute(
                "UPDATE rag_agent_runs SET evidence_state_json = ?, updated_at = ? WHERE run_id = ?",
                (json_dumps(self.evidence_state.to_dict()), now_iso(), self.run_id),
            )
            conn.commit()

    def persist_task_plan(self) -> None:
        with connect(self.library) as conn:
            conn.execute(
                "UPDATE rag_agent_runs SET task_plan_json = ?, updated_at = ? WHERE run_id = ?",
                (json_dumps(self.task_plan.to_dict()), now_iso(), self.run_id),
            )
            conn.commit()

    def checkpoint(self, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
        timestamp = now_iso()
        with connect(self.library) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM rag_agent_events WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            payload = _sanitize_payload(
                {
                    "checkpoint_version": "phase2-v1",
                    "run_id": self.run_id,
                    "conversation_id": self.conversation_id,
                    "current_state": self.current_state,
                    "task_plan": self.task_plan.to_dict(),
                    "evidence_state": self.evidence_state.to_dict(),
                    "last_event_sequence": int(row["sequence"] or 0),
                    "resume_policy": "restart_from_user_turn",
                    "restart_allowed": True,
                    "runtime": runtime or {},
                    "saved_at": timestamp,
                }
            )
            conn.execute(
                """
                UPDATE rag_agent_runs
                SET checkpoint_json = ?, heartbeat_at = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (json_dumps(payload), timestamp, timestamp, self.run_id),
            )
            conn.commit()
        return payload

    def event(
        self,
        event_type: str,
        *,
        summary: str,
        payload: dict[str, Any] | None = None,
        visibility: str = "summary",
        status: str = "ok",
    ) -> dict[str, Any]:
        if visibility not in {"summary", "detail", "diagnostic", "internal"}:
            raise ValueError(f"unknown event visibility: {visibility}")
        clean_payload = _sanitize_payload(payload or {})
        with self.event_lock:
            timestamp = now_iso()
            with connect(self.library) as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM rag_agent_events WHERE run_id = ?",
                    (self.run_id,),
                ).fetchone()
                sequence = int(row["sequence"] or 0) + 1
                event_id = f"evt-{uuid.uuid4().hex}"
                conn.execute(
                    """
                    INSERT INTO rag_agent_events (
                      event_id, run_id, sequence, event_type, state, status,
                      visibility, summary, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        self.run_id,
                        sequence,
                        str(event_type or "event"),
                        self.current_state,
                        str(status or ""),
                        visibility,
                        str(summary or ""),
                        json_dumps(clean_payload),
                        timestamp,
                    ),
                )
                conn.execute(
                    "UPDATE rag_agent_runs SET heartbeat_at = ?, updated_at = ? WHERE run_id = ?",
                    (timestamp, timestamp, self.run_id),
                )
                conn.commit()
        return {
            "event_id": event_id,
            "run_id": self.run_id,
            "sequence": sequence,
            "event_type": str(event_type or "event"),
            "state": self.current_state,
            "status": str(status or ""),
            "visibility": visibility,
            "summary": str(summary or ""),
            "payload": dict(clean_payload),
            "created_at": timestamp,
        }

    def finish(
        self,
        *,
        status: str,
        stop_reason: str,
        usage: dict[str, Any],
        error_code: str = "",
    ) -> dict[str, Any]:
        if status not in RUN_STATUSES - {"running"}:
            raise ValueError(f"unknown terminal run status: {status}")
        if stop_reason not in STOP_REASONS - {""}:
            raise ValueError(f"unknown stop reason: {stop_reason}")
        existing = load_agent_run(self.library, self.run_id)
        if existing.get("status") in RUN_STATUSES - {"running"}:
            return existing
        timestamp = now_iso()
        self.persist_task_plan()
        self.persist_evidence_state()
        checkpoint = self.checkpoint({"terminal_status": status, "stop_reason": stop_reason})
        with connect(self.library) as conn:
            conn.execute(
                """
                UPDATE rag_agent_runs
                SET status = ?, current_state = ?, evidence_state_json = ?, usage_json = ?,
                    stop_reason = ?, error_code = ?, checkpoint_json = ?, heartbeat_at = ?, updated_at = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    self.current_state,
                    json_dumps(self.evidence_state.to_dict()),
                    json_dumps(usage or {}),
                    stop_reason,
                    str(error_code or ""),
                    json_dumps(checkpoint),
                    timestamp,
                    timestamp,
                    timestamp,
                    self.run_id,
                ),
            )
            conn.commit()
        event_type = "run.completed" if status in {"completed", "abstained"} else "run.failed"
        if status == "cancelled":
            event_type = "run.cancelled"
        self.event(
            event_type,
            summary=_finish_summary(status, stop_reason),
            payload={
                "status": status,
                "stop_reason": stop_reason,
                "usage": dict(usage or {}),
                "error_code": str(error_code or ""),
            },
            visibility="detail",
            status=status,
        )
        return load_agent_run(self.library, self.run_id)

    def trace(self, *, include_internal: bool = False) -> list[dict[str, Any]]:
        return load_agent_events(self.library, self.run_id, include_internal=include_internal)


def load_agent_run(library: dict[str, Any], run_id: str) -> dict[str, Any]:
    ensure_store(library)
    with connect(library) as conn:
        row = conn.execute("SELECT * FROM rag_agent_runs WHERE run_id = ?", (str(run_id or ""),)).fetchone()
    if not row:
        return {}
    payload = dict(row)
    for source, target in (
        ("task_plan_json", "task_plan"),
        ("evidence_state_json", "evidence_state"),
        ("budget_json", "budget"),
        ("usage_json", "usage"),
        ("checkpoint_json", "checkpoint"),
    ):
        payload[target] = _json_object(payload.pop(source, "{}"))
    payload.pop("worker_id", None)
    payload["events"] = load_agent_events(library, str(payload.get("run_id") or ""))
    return payload


def load_agent_events(
    library: dict[str, Any],
    run_id: str,
    *,
    after_sequence: int = 0,
    include_internal: bool = False,
) -> list[dict[str, Any]]:
    ensure_store(library)
    clauses = ["run_id = ?", "sequence > ?"]
    params: list[Any] = [str(run_id or ""), max(0, int(after_sequence or 0))]
    if not include_internal:
        clauses.append("visibility != 'internal'")
    with connect(library) as conn:
        rows = conn.execute(
            f"SELECT * FROM rag_agent_events WHERE {' AND '.join(clauses)} ORDER BY sequence ASC",
            params,
        ).fetchall()
    return [
        {
            "event_id": str(row["event_id"] or ""),
            "run_id": str(row["run_id"] or ""),
            "sequence": int(row["sequence"] or 0),
            "event_type": str(row["event_type"] or ""),
            "state": str(row["state"] or ""),
            "status": str(row["status"] or ""),
            "visibility": str(row["visibility"] or ""),
            "summary": str(row["summary"] or ""),
            "payload": _sanitize_payload(_json_object(row["payload_json"])),
            "created_at": str(row["created_at"] or ""),
        }
        for row in rows
    ]


def _json_object(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def reconcile_interrupted_runs(
    library: dict[str, Any],
    *,
    active_run_ids: set[str] | None = None,
) -> list[str]:
    ensure_store(library)
    timestamp = now_iso()
    interrupted: list[str] = []
    with connect(library) as conn:
        rows = conn.execute(
            """
            SELECT run_id, conversation_id, worker_id, checkpoint_json
            FROM rag_agent_runs
            WHERE library_id = ? AND status = 'running'
            """,
            (str(library["library_id"]),),
        ).fetchall()
        for row in rows:
            run_id = str(row["run_id"] or "")
            worker_id = str(row["worker_id"] or "")
            belongs_to_dead_worker = worker_id != PROCESS_WORKER_ID
            missing_active_job = active_run_ids is not None and run_id not in active_run_ids
            if not belongs_to_dead_worker and not missing_active_job:
                continue
            checkpoint = _json_object(row["checkpoint_json"])
            checkpoint.update(
                {
                    "interrupted_at": timestamp,
                    "terminal_status": "interrupted",
                    "stop_reason": "interrupted",
                    "restart_allowed": True,
                    "resume_policy": "restart_from_user_turn",
                }
            )
            checkpoint = _sanitize_payload(checkpoint)
            conn.execute(
                """
                UPDATE rag_agent_runs
                SET status = 'interrupted', current_state = 'abstain', stop_reason = 'interrupted',
                    error_code = 'worker_interrupted', checkpoint_json = ?, heartbeat_at = ?,
                    updated_at = ?, finished_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (json_dumps(checkpoint), timestamp, timestamp, timestamp, run_id),
            )
            sequence_row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM rag_agent_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO rag_agent_events (
                  event_id, run_id, sequence, event_type, state, status,
                  visibility, summary, payload_json, created_at
                ) VALUES (?, ?, ?, 'run.interrupted', 'abstain', 'interrupted',
                          'detail', ?, ?, ?)
                """,
                (
                    f"evt-{uuid.uuid4().hex}",
                    run_id,
                    int(sequence_row["sequence"] or 0) + 1,
                    "服务进程已变化，未完成任务已安全标记为中断。",
                    json_dumps({"stop_reason": "interrupted", "restart_allowed": True}),
                    timestamp,
                ),
            )
            _ensure_interrupted_assistant(conn, run_id, timestamp)
            interrupted.append(run_id)
        conn.commit()
    return interrupted


def _ensure_interrupted_assistant(conn: Any, run_id: str, timestamp: str) -> None:
    user_row = conn.execute(
        """
        SELECT conversation_id, turn_index
        FROM rag_chat_messages
        WHERE run_id = ? AND role = 'user'
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if not user_row:
        return
    exists = conn.execute(
        "SELECT 1 FROM rag_chat_messages WHERE run_id = ? AND role = 'assistant' LIMIT 1",
        (run_id,),
    ).fetchone()
    if exists:
        return
    conn.execute(
        """
        INSERT INTO rag_chat_messages (
          message_id, conversation_id, run_id, turn_index, role, content,
          sources_json, tool_trace_json, created_at
        ) VALUES (?, ?, ?, ?, 'assistant', ?, '[]', '[]', ?)
        """,
        (
            f"msg-{uuid.uuid4().hex}",
            str(user_row["conversation_id"] or ""),
            run_id,
            int(user_row["turn_index"] or 0),
            "任务因服务进程中断而停止。可以从这个问题安全地重新开始。",
            timestamp,
        ),
    )
    conn.execute(
        "UPDATE rag_chat_sessions SET updated_at = ? WHERE conversation_id = ?",
        (timestamp, str(user_row["conversation_id"] or "")),
    )


def _sanitize_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = str(key)
            normalized_key = clean_key.casefold().replace("-", "_")
            if normalized_key in _SENSITIVE_KEYS or normalized_key.endswith(_SENSITIVE_KEY_SUFFIXES):
                output[clean_key] = "[redacted]"
            else:
                output[clean_key] = _sanitize_payload(item, depth=depth + 1)
        return output
    if isinstance(value, list):
        return [_sanitize_payload(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, tuple):
        return [_sanitize_payload(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _tool_summary(tool: str, trace: dict[str, Any]) -> str:
    count = trace.get("result_count")
    if tool == "search_evidence":
        return f"已检索证据，获得 {int(count or 0)} 条结果。"
    if tool == "read_chunk_context":
        return f"已深读上下文，读取 {int(count or 0)} 个片段。"
    if tool == "list_scope_documents":
        return f"已检查知识库范围，找到 {int(count or 0)} 篇文献。"
    return f"已执行工具 {tool}。"


def _finish_summary(status: str, stop_reason: str) -> str:
    if status == "completed":
        return "任务已完成。"
    if status == "abstained":
        return "任务因证据不足而停止。"
    if status == "cancelled":
        return "任务已取消。"
    if status == "interrupted" or stop_reason == "interrupted":
        return "任务因服务进程中断而停止，可安全重新开始。"
    if stop_reason == "provider_unavailable":
        return "模型服务不可用，任务已停止。"
    return "任务执行失败。"
