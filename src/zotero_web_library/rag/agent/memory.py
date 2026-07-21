from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from zotero_web_library.rag.store import connect, ensure_store, json_dumps, knowledge_base_item_keys, normalize_item_keys
from zotero_web_library.utils import now_iso


DEFAULT_HISTORY_TURNS = 10


@dataclass(slots=True)
class ChatSession:
    conversation_id: str
    library_id: str
    knowledge_base_id: str
    item_keys: list[str]


@dataclass(slots=True)
class ChatTurn:
    turn_index: int
    user_message_id: str


def get_or_create_session(
    library: dict[str, Any],
    *,
    conversation_id: str = "",
    knowledge_base_id: str = "",
    item_keys: list[str] | None = None,
) -> ChatSession:
    ensure_store(library)
    clean_conversation_id = str(conversation_id or "").strip()
    library_id = str(library["library_id"])
    if clean_conversation_id:
        with connect(library) as conn:
            row = conn.execute(
                """
                SELECT *
                FROM rag_chat_sessions
                WHERE conversation_id = ? AND library_id = ?
                """,
                (clean_conversation_id, library_id),
            ).fetchone()
        if not row:
            raise ValueError("会话不存在或不属于当前文库。")
        return _session_from_row(dict(row))

    clean_knowledge_base_id = str(knowledge_base_id or "").strip()
    if not clean_knowledge_base_id:
        raise ValueError("新会话必须先选择知识库。")
    base_keys = knowledge_base_item_keys(library, clean_knowledge_base_id)
    requested_keys = normalize_item_keys(item_keys or []) if item_keys is not None else []
    if requested_keys:
        allowed = set(base_keys)
        scoped_keys = [key for key in requested_keys if key in allowed]
    else:
        scoped_keys = base_keys

    timestamp = now_iso()
    new_conversation_id = f"conv-{uuid.uuid4().hex}"
    with connect(library) as conn:
        conn.execute(
            """
            INSERT INTO rag_chat_sessions (
              conversation_id, library_id, knowledge_base_id, item_keys_json,
              title, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, '', ?, ?)
            """,
            (
                new_conversation_id,
                library_id,
                clean_knowledge_base_id,
                json_dumps(scoped_keys),
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
    return ChatSession(
        conversation_id=new_conversation_id,
        library_id=library_id,
        knowledge_base_id=clean_knowledge_base_id,
        item_keys=scoped_keys,
    )


def load_history(
    library: dict[str, Any],
    conversation_id: str,
    *,
    limit_turns: int = DEFAULT_HISTORY_TURNS,
) -> list[dict[str, str]]:
    ensure_store(library)
    clean_conversation_id = str(conversation_id or "").strip()
    limit = max(1, int(limit_turns or DEFAULT_HISTORY_TURNS))
    with connect(library) as conn:
        turn_rows = conn.execute(
            """
            SELECT DISTINCT turn_index
            FROM rag_chat_messages
            WHERE conversation_id = ?
              AND role IN ('user', 'assistant')
            ORDER BY turn_index DESC
            LIMIT ?
            """,
            (clean_conversation_id, limit),
        ).fetchall()
        turn_indices = [int(row["turn_index"]) for row in turn_rows]
        if not turn_indices:
            return []
        placeholders = ",".join("?" for _ in turn_indices)
        rows = conn.execute(
            f"""
            SELECT role, content
            FROM rag_chat_messages
            WHERE conversation_id = ?
              AND turn_index IN ({placeholders})
              AND role IN ('user', 'assistant')
            ORDER BY turn_index ASC,
              CASE role WHEN 'user' THEN 0 WHEN 'assistant' THEN 1 ELSE 2 END,
              created_at ASC
            """,
            [clean_conversation_id, *sorted(turn_indices)],
        ).fetchall()
    return [{"role": str(row["role"]), "content": str(row["content"] or "")} for row in rows]


def load_conversation(
    library: dict[str, Any],
    *,
    conversation_id: str = "",
    knowledge_base_id: str = "",
) -> dict[str, Any]:
    """Load one persisted chat for restoring the knowledge-base workbench.

    When no conversation id is supplied, the most recently updated
    conversation in the requested knowledge base is returned.
    """
    ensure_store(library)
    library_id = str(library["library_id"])
    clean_conversation_id = str(conversation_id or "").strip()
    clean_knowledge_base_id = str(knowledge_base_id or "").strip()
    if not clean_conversation_id and not clean_knowledge_base_id:
        raise ValueError("conversation_id 和 knowledge_base_id 至少需要一个。")

    with connect(library) as conn:
        if clean_conversation_id:
            session_row = conn.execute(
                """
                SELECT *
                FROM rag_chat_sessions
                WHERE conversation_id = ? AND library_id = ?
                """,
                (clean_conversation_id, library_id),
            ).fetchone()
        else:
            session_row = conn.execute(
                """
                SELECT *
                FROM rag_chat_sessions
                WHERE library_id = ? AND knowledge_base_id = ?
                ORDER BY updated_at DESC, created_at DESC, conversation_id DESC
                LIMIT 1
                """,
                (library_id, clean_knowledge_base_id),
            ).fetchone()

        if not session_row:
            return {
                "conversation_id": "",
                "knowledge_base_id": clean_knowledge_base_id,
                "item_keys": [],
                "messages": [],
                "active_run": {},
            }

        session = _session_from_row(dict(session_row))
        message_rows = conn.execute(
            """
            SELECT turn_index, role, content, sources_json, tool_trace_json, run_id, created_at
            FROM rag_chat_messages
            WHERE conversation_id = ? AND role IN ('user', 'assistant')
            ORDER BY turn_index ASC,
              CASE role WHEN 'user' THEN 0 WHEN 'assistant' THEN 1 ELSE 2 END,
              created_at ASC
            """,
            (session.conversation_id,),
        ).fetchall()

        latest_run_row = conn.execute(
            """
            SELECT run_id
            FROM rag_agent_runs
            WHERE conversation_id = ?
            ORDER BY created_at DESC, run_id DESC
            LIMIT 1
            """,
            (session.conversation_id,),
        ).fetchone()

    from .runtime import load_agent_run

    run_cache: dict[str, dict[str, Any]] = {}
    for row in message_rows:
        run_id = str(row["run_id"] or "")
        if run_id and run_id not in run_cache:
            run_cache[run_id] = load_agent_run(library, run_id)

    messages: list[dict[str, Any]] = []
    for row in message_rows:
        run_id = str(row["run_id"] or "")
        message = {
            "turn_index": int(row["turn_index"] or 0),
            "role": str(row["role"] or ""),
            "content": str(row["content"] or ""),
            "sources": _json_list(row["sources_json"]),
            "tool_trace": _json_list(row["tool_trace_json"]),
            "run_id": run_id,
            "created_at": str(row["created_at"] or ""),
        }
        run = run_cache.get(run_id) or {}
        if message["role"] == "assistant" and run:
            message.update(
                {
                    "agent_trace": run.get("events") or [],
                    "agent_state": {
                        "current_state": run.get("current_state") or "",
                        "status": run.get("status") or "",
                        "task_plan": run.get("task_plan") or {},
                        "evidence_state": run.get("evidence_state") or {},
                    },
                    "stop_reason": run.get("stop_reason") or "",
                    "run_status": run.get("status") or "",
                }
            )
        messages.append(message)

    latest_run_id = str(latest_run_row["run_id"] or "") if latest_run_row else ""
    latest_run = run_cache.get(latest_run_id) or (load_agent_run(library, latest_run_id) if latest_run_id else {})
    active_run = latest_run if latest_run.get("status") == "running" else {}
    return {
        "conversation_id": session.conversation_id,
        "knowledge_base_id": session.knowledge_base_id,
        "item_keys": session.item_keys,
        "messages": messages,
        "active_run": active_run,
        "title": str(session_row["title"] or ""),
        "created_at": str(session_row["created_at"] or ""),
        "updated_at": str(session_row["updated_at"] or ""),
    }


def save_turn(
    library: dict[str, Any],
    session: ChatSession,
    *,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]],
    run_id: str = "",
) -> None:
    turn = begin_turn(library, session, question=question, run_id=run_id)
    complete_turn(
        library,
        session,
        turn_index=turn.turn_index,
        answer=answer,
        sources=sources,
        tool_trace=tool_trace,
        run_id=run_id,
    )


def begin_turn(
    library: dict[str, Any],
    session: ChatSession,
    *,
    question: str,
    run_id: str,
) -> ChatTurn:
    ensure_store(library)
    timestamp = now_iso()
    message_id = f"msg-{uuid.uuid4().hex}"
    with connect(library) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(turn_index), 0) AS turn_index FROM rag_chat_messages WHERE conversation_id = ?",
            (session.conversation_id,),
        ).fetchone()
        turn_index = int(row["turn_index"] or 0) + 1
        conn.execute(
            """
            INSERT INTO rag_chat_messages (
              message_id, conversation_id, run_id, turn_index, role, content,
              sources_json, tool_trace_json, created_at
            )
            VALUES (?, ?, ?, ?, 'user', ?, '[]', '[]', ?)
            """,
            (
                message_id,
                session.conversation_id,
                str(run_id or ""),
                turn_index,
                str(question or ""),
                timestamp,
            ),
        )
        conn.execute(
            """
            UPDATE rag_chat_sessions
            SET updated_at = ?
            WHERE conversation_id = ? AND library_id = ?
            """,
            (timestamp, session.conversation_id, session.library_id),
        )
        conn.commit()
    return ChatTurn(turn_index=turn_index, user_message_id=message_id)


def complete_turn(
    library: dict[str, Any],
    session: ChatSession,
    *,
    turn_index: int,
    answer: str,
    sources: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]],
    run_id: str,
) -> None:
    ensure_store(library)
    timestamp = now_iso()
    with connect(library) as conn:
        existing = conn.execute(
            """
            SELECT message_id
            FROM rag_chat_messages
            WHERE conversation_id = ? AND turn_index = ? AND role = 'assistant'
            LIMIT 1
            """,
            (session.conversation_id, int(turn_index)),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE rag_chat_messages
                SET run_id = ?, content = ?, sources_json = ?, tool_trace_json = ?, created_at = ?
                WHERE message_id = ?
                """,
                (
                    str(run_id or ""),
                    str(answer or ""),
                    json_dumps(sources),
                    json_dumps(tool_trace),
                    timestamp,
                    str(existing["message_id"] or ""),
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO rag_chat_messages (
                  message_id, conversation_id, run_id, turn_index, role, content,
                  sources_json, tool_trace_json, created_at
                )
                VALUES (?, ?, ?, ?, 'assistant', ?, ?, ?, ?)
                """,
                (
                    f"msg-{uuid.uuid4().hex}",
                    session.conversation_id,
                    str(run_id or ""),
                    int(turn_index),
                    str(answer or ""),
                    json_dumps(sources),
                    json_dumps(tool_trace),
                    timestamp,
                ),
            )
        conn.execute(
            """
            UPDATE rag_chat_sessions
            SET updated_at = ?
            WHERE conversation_id = ? AND library_id = ?
            """,
            (timestamp, session.conversation_id, session.library_id),
        )
        conn.commit()


def _session_from_row(row: dict[str, Any]) -> ChatSession:
    try:
        item_keys = json.loads(str(row.get("item_keys_json") or "[]"))
    except json.JSONDecodeError:
        item_keys = []
    if not isinstance(item_keys, list):
        item_keys = []
    return ChatSession(
        conversation_id=str(row.get("conversation_id") or ""),
        library_id=str(row.get("library_id") or ""),
        knowledge_base_id=str(row.get("knowledge_base_id") or ""),
        item_keys=normalize_item_keys(item_keys),
    )


def _json_list(value: Any) -> list[Any]:
    try:
        payload = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []
