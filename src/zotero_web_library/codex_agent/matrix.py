from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox, TextInput
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    CommandExecutionThreadItem,
    ItemCompletedNotification,
    ReasoningSummary,
)

from zotero_web_library.codex_agent.runner import (
    build_config_overrides,
    build_runtime_config,
    codex_home_dir,
    friendly_codex_error,
    run_thread_turn_with_diagnostics,
)
from zotero_web_library.paths import app_data_dir


def _creator_display(item: dict[str, Any]) -> str:
    creators = item.get("creators") if isinstance(item.get("creators"), list) else []
    names = [str(c.get("name") or "").strip() for c in creators if isinstance(c, dict) and str(c.get("name") or "").strip()]
    return " / ".join(names)


def _extract_pdf_text(pdf_path: str, *, max_pages: int = 12, max_chars: int = 12000) -> str:
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001
        return ""
    try:
        reader = PdfReader(pdf_path)
        chunks: list[str] = []
        total = 0
        for page in reader.pages[:max_pages]:
            try:
                text = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001
                text = ""
            if not text:
                continue
            if total + len(text) > max_chars:
                chunks.append(text[: max(0, max_chars - total)])
                break
            chunks.append(text)
            total += len(text)
        return "\n\n".join(chunks).strip()
    except Exception:  # noqa: BLE001
        return ""


def build_matrix_prompt(
    *,
    item: dict[str, Any],
    fields: list[dict[str, Any]],
    pdf_text: str = "",
) -> str:
    fields = [field for field in fields if field.get("enabled", True)]
    field_lines = "\n".join(
        f'- {field["field_id"]}: {field["name"]}。判断依据和格式要求：{field.get("rule", "")}'
        for field in fields
    )
    item_fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
    authors = _creator_display(item)
    pdf_block = pdf_text or "无（系统未能从本地 PDF 提取到文本，请仅依据上方元数据和摘要判断）"
    return f"""
你正在为“Zotero Web Library”生成单篇论文的文献矩阵。本轮只处理下面列出的目标字段，不要生成未列出的字段。

论文信息：
- item_key: {item.get("key", "")}
- 标题: {item.get("title", "")}
- 作者: {authors}
- 年份: {item.get("year", "")}
- 来源: {item.get("venue", "")}
- DOI: {item_fields.get("DOI") or "无"}
- 摘要: {item_fields.get("abstractNote") or "无"}

PDF 正文（已由系统在本地提取，无需你打开或读取任何本地文件）：
{pdf_block}

本轮目标矩阵字段：
{field_lines}

任务要求：
1. 直接依据上方“PDF 正文”及论文元数据/摘要判断，不要调用任何工具去读取、打开或转换本地文件。
2. 按每个矩阵字段的判断依据和格式要求，生成适合文献综述整理的中文结果。
3. 如果 PDF 正文中找不到足够证据，不要编造，写明“未在当前 PDF 中找到明确证据”并给出可确认的有限信息。
4. 只输出一个 JSON 对象，不要 Markdown，不要代码块，不要解释。
5. JSON 结构必须为：
{{
  "fields": {{
    "field_id": {{
      "value": "中文结果"
    }}
  }}
}}
""".strip()


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("文献矩阵结果不是 JSON 对象")
    return data


def run_reading_matrix_for_item(
    *,
    library: dict[str, Any],
    codex_config: dict[str, Any],
    item: dict[str, Any],
    fields: list[dict[str, Any]],
    pdf_path: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    runtime = build_runtime_config(library, codex_config)
    provider = runtime["model_provider"]

    codex_config_obj = CodexConfig(
        cwd=str(app_data_dir()),
        env={"CODEX_HOME": str(codex_home_dir(library))},
        config_overrides=build_config_overrides(runtime, reasoning_effort=runtime.get("reasoning_effort", "high")),
    )

    def emit(message: str) -> None:
        if progress:
            progress(message)

    def on_codex_event(event: Any) -> None:
        if not progress:
            return
        payload = getattr(event, "payload", None)
        if not isinstance(payload, ItemCompletedNotification):
            return
        item = getattr(payload, "item", None)
        root = getattr(item, "root", item) if item is not None else None
        if isinstance(root, AgentMessageThreadItem):
            phase = (root.phase.value if root.phase else "").lower()
            text = (root.text or "").strip()
            if phase in ("reasoning", "thinking") and len(text) > 10:
                preview = re.sub(r"\s+", " ", text)[:220]
                suffix = "…" if len(text) > 220 else ""
                progress(f"💭 思考：{preview}{suffix}")
        elif isinstance(root, CommandExecutionThreadItem):
            status = root.status.value if root.status else "执行"
            progress(f"🔧 工具调用（{status}）")

    with Codex(codex_config_obj) as codex:
        emit("正在启动文献矩阵智能体。")
        pdf_text = _extract_pdf_text(pdf_path) if pdf_path else ""
        if pdf_path:
            if pdf_text:
                emit(f"已提取本地 PDF 文本（{len(pdf_text)} 字），正在生成矩阵。")
            else:
                emit("本地 PDF 未提取到文本（可能为扫描件），将仅依据元数据与摘要生成。")
        codex.login_api_key(runtime["api_key"])
        thread = codex.thread_start(
            cwd=str(app_data_dir()),
            sandbox=Sandbox.full_access,
            approval_mode=ApprovalMode.deny_all,
            model=runtime["model"],
            model_provider=provider,
            ephemeral=True,
        )
        result = run_thread_turn_with_diagnostics(
            thread,
            [
                TextInput(
                    build_matrix_prompt(
                        item=item,
                        fields=fields,
                        pdf_text=pdf_text,
                    )
                )
            ],
            summary=ReasoningSummary(root="concise"),
            on_event=on_codex_event,
        )

    if not result.final_response:
        detail = result.diagnostics.get("error") or "Codex turn 已完成，但没有收到任何 assistant 文本。"
        raise RuntimeError(friendly_codex_error(RuntimeError(detail)))
    emit("智能体已返回文献矩阵结果，正在校验 JSON。")
    parsed = parse_json_object(result.final_response)
    raw_fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    values: dict[str, Any] = {}
    for field in fields:
        field_id = field.get("field_id")
        entry = raw_fields.get(field_id) if isinstance(raw_fields.get(field_id), dict) else {}
        values[field_id] = {"value": str(entry.get("value") or "").strip()}
    return {"values": values}


def _paper_context_line(item: dict[str, Any]) -> str:
    authors = _creator_display(item)
    return (
        f"- {item.get('title', '')} ({item.get('year', '')}, {item.get('venue', '')})\n"
        f"  作者：{authors or '未知'}\n"
        f"  摘要：{item.get('fields', {}).get('abstractNote') or '无'}"
    )


def parse_json_array(text: str) -> list[dict[str, str]]:
    source = (text or "").strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:json)?", "", source, flags=re.IGNORECASE).strip()
        source = re.sub(r"```$", "", source).strip()
    try:
        data = json.loads(source)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", source, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("AI 推荐字段结果不是 JSON 数组")
    fields: list[dict[str, str]] = []
    for item in data[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        rule = str(item.get("rule") or "").strip()
        if name and rule:
            fields.append({"name": name, "rule": rule})
    return fields


def recommend_matrix_fields(
    *,
    library: dict[str, Any],
    codex_config: dict[str, Any],
    items: list[dict[str, Any]],
    existing_fields: list[dict[str, Any]],
) -> list[dict[str, str]]:
    runtime = build_runtime_config(library, codex_config)
    provider = runtime["model_provider"]

    existing = " / ".join(field.get("name", "") for field in existing_fields if field.get("name")) or "无"
    paper_lines = "\n\n".join(_paper_context_line(item) for item in items[:24]) or "当前没有可用论文。"
    prompt = f"""
你是“Zotero Web Library”的文献矩阵字段设计助手。
请基于当前论文集合，为后续综述写作推荐 3 到 6 个有价值的文献矩阵字段。

已有字段：{existing}

论文信息：
{paper_lines}

要求：
1. 不要重复已有字段或语义高度相同的字段。
2. 字段要适合综述写作中的方法比较、内容核对和章节组织。
3. 每个字段必须包含 name 和 rule。
4. rule 必须写成“判断依据和格式要求”，例如输出布尔值、分类范围、字数限制、证据要求。
5. 只输出 JSON 数组，不要 Markdown，不要解释。

输出格式：
[
  {{
    "name": "任务类型",
    "rule": "判断论文处理的任务类型；输出 1-3 个短语，例如任务规划、双臂操作、装配执行。"
  }}
]
""".strip()

    codex_config_obj = CodexConfig(
        cwd=str(app_data_dir()),
        env={"CODEX_HOME": str(codex_home_dir(library))},
        config_overrides=build_config_overrides(runtime, reasoning_effort="medium"),
    )
    with Codex(codex_config_obj) as codex:
        codex.login_api_key(runtime["api_key"])
        thread = codex.thread_start(
            cwd=str(app_data_dir()),
            sandbox=Sandbox.full_access,
            approval_mode=ApprovalMode.deny_all,
            model=runtime["model"],
            model_provider=provider,
            ephemeral=True,
        )
        result = run_thread_turn_with_diagnostics(
            thread,
            [TextInput(prompt)],
            summary=ReasoningSummary(root="concise"),
        )
    if not result.final_response:
        detail = result.diagnostics.get("error") or "Codex turn 已完成，但没有收到任何 assistant 文本。"
        raise RuntimeError(friendly_codex_error(RuntimeError(detail)))
    return parse_json_array(result.final_response)
