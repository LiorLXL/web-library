from __future__ import annotations

import json
from typing import Any


def build_agentic_rag_chat_prompt(*, question: str, evidence_pack: dict[str, Any]) -> str:
    compact_pack = _compact_evidence_pack(evidence_pack)
    return f"""
你正在执行 Zotero Web Library 的文库内 Agentic RAG 问答。

请严格遵守已经注入的 agentic-rag skill：
- 只能基于 Evidence Pack 回答。
- 每个事实性结论都要保留 Evidence Pack 中的 citation 标记。
- 证据不足时明确说明，不要使用常识或外部知识补全。
- 区分论文原文证据、用户笔记和你的综合归纳。

用户问题：
{question}

Evidence Pack JSON：
{json.dumps(compact_pack, ensure_ascii=False, indent=2)}

输出要求：
1. 用中文回答。
2. 先直接回答问题，再给出关键依据。
3. 引用标记必须使用 Evidence Pack 中已有的 citation 字段。
4. 不要暴露本地路径、内部 API、工具实现细节或 JSON 原文。
""".strip()


def _compact_evidence_pack(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for result in evidence_pack.get("results") or []:
        if not isinstance(result, dict):
            continue
        results.append(
            {
                "evidence_id": result.get("evidence_id", ""),
                "source_type": result.get("source_type", ""),
                "retrieval_type": result.get("retrieval_type", ""),
                "item_key": result.get("item_key", ""),
                "chunk_id": result.get("chunk_id", ""),
                "title": result.get("title", ""),
                "authors_text": result.get("authors_text", ""),
                "year": result.get("year", ""),
                "venue": result.get("venue", ""),
                "section_title": result.get("section_title", ""),
                "estimated_page": result.get("estimated_page"),
                "text": str(result.get("text") or "")[:2600],
                "excerpt": str(result.get("excerpt") or "")[:700],
                "citation": result.get("citation", ""),
            }
        )
    return {
        "query": evidence_pack.get("query", ""),
        "mode": evidence_pack.get("mode", ""),
        "knowledge_base_id": evidence_pack.get("knowledge_base_id", ""),
        "results": results,
        "warnings": evidence_pack.get("warnings") or [],
    }
