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


def save_turn(
    library: dict[str, Any],
    session: ChatSession,
    *,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]],
) -> None:
    ensure_store(library)
    timestamp = now_iso()
    with connect(library) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(turn_index), 0) AS turn_index FROM rag_chat_messages WHERE conversation_id = ?",
            (session.conversation_id,),
        ).fetchone()
        turn_index = int(row["turn_index"] or 0) + 1
        conn.execute(
            """
            INSERT INTO rag_chat_messages (
              message_id, conversation_id, turn_index, role, content,
              sources_json, tool_trace_json, created_at
            )
            VALUES (?, ?, ?, 'user', ?, '[]', '[]', ?)
            """,
            (f"msg-{uuid.uuid4().hex}", session.conversation_id, turn_index, str(question or ""), timestamp),
        )
        conn.execute(
            """
            INSERT INTO rag_chat_messages (
              message_id, conversation_id, turn_index, role, content,
              sources_json, tool_trace_json, created_at
            )
            VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?)
            """,
            (
                f"msg-{uuid.uuid4().hex}",
                session.conversation_id,
                turn_index,
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
