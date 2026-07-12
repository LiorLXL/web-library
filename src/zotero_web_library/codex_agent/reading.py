from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from openai_codex import ApprovalMode, Codex, CodexConfig, LocalImageInput, Sandbox, TextInput
from openai_codex.generated.v2_all import ReasoningSummary

from zotero_web_library.codex_agent.matrix import _extract_pdf_text
from zotero_web_library.codex_agent.runner import (
    build_config_overrides,
    build_runtime_config,
    codex_home_dir,
    friendly_codex_error,
    run_thread_turn_with_diagnostics,
)
from zotero_web_library.paths import app_data_dir


def build_reading_chat_prompt(
    *,
    item: dict[str, Any],
    pdf_path: str,
    user_question: str,
    include_paper_context: bool,
    image_count: int = 0,
    pdf_text: str = "",
) -> str:
    fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
    creator_values = item.get("creators") if isinstance(item.get("creators"), list) else []
    creators = " / ".join(
        str(c.get("name") or "").strip()
        for c in creator_values
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    )
    tags = [str(t) for t in item.get("tags") or [] if str(t)]
    pdf_exists = bool(pdf_path) and Path(pdf_path).exists()
    paper_context = "\n".join(
        [
            f"条目 Key: {item.get('key', '')}",
            f"标题: {item.get('title', '')}",
            f"作者: {creators}",
            f"年份: {item.get('year', '')}",
            f"来源: {item.get('venue', '')}",
            f"DOI: {fields.get('DOI') or '无'}",
            f"本地 PDF 是否存在: {'是' if pdf_exists else '否'}",
            f"标签: {' / '.join(tags) or '无'}",
            f"摘要: {fields.get('abstractNote') or '无'}",
        ]
    )

    context_rule = (
        "本轮已经提供当前论文上下文。"
        if include_paper_context
        else "本轮不要假装重新读取了新的论文；如果需要引用论文内容，请基于当前 thread 已有上下文。"
    )
    image_rule = (
        f"用户本轮附加了 {image_count} 张当前论文阅读过程中的图片，请你了解图片内容，并结合用户问题回答。"
        if image_count
        else "用户本轮没有附加图片。"
    )
    if include_paper_context:
        if pdf_text:
            pdf_block = f"PDF 正文（已由系统在本地提取，无需你打开或读取任何本地文件）：\n{pdf_text}"
        elif pdf_exists:
            pdf_block = "PDF 正文：系统未能从本地 PDF 提取到文本（可能为扫描件），请仅依据上方元数据与摘要回答。"
        else:
            pdf_block = "PDF 正文：本地 PDF 不存在，请仅依据上方元数据与摘要回答。"
    else:
        pdf_block = "PDF 正文：已在本 thread 前序对话中提供，请基于已有上下文回答，不要重复读取。"
    return f"""
你是 Zotero Web Library 的单篇文献研读助手，正在帮助用户阅读当前文献。

重要要求：
1. 你正在同一个 thread 中持续对话，需要结合前文记忆回答。
2. 本轮只围绕当前这篇文献回答，不要扩展到文库中其他文献，除非用户明确要求比较。
3. 直接依据下方“PDF 正文”及元数据回答（可引用页码/段落），不要调用任何工具去读取、打开或转换本地文件。
4. 如果 PDF 正文或元数据中证据不足，要明确说明，不要编造文献中没有的结论。
5. 回答使用中文。
6. {context_rule}
7. {image_rule}

当前文献：
{paper_context}

{pdf_block}

用户问题：
{user_question}
""".strip()


def run_reading_chat_turn(
    *,
    library: dict[str, Any],
    codex_config: dict[str, Any],
    item: dict[str, Any],
    pdf_path: str,
    thread_id: str | None,
    user_question: str,
    include_paper_context: bool = True,
    image_paths: list[str] | None = None,
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

    with Codex(codex_config_obj) as codex:
        codex.login_api_key(runtime["api_key"])
        if thread_id:
            emit("正在恢复单篇研读对话线程。")
            thread = codex.thread_resume(
                thread_id,
                cwd=str(app_data_dir()),
                sandbox=Sandbox.full_access,
                approval_mode=ApprovalMode.deny_all,
                model=runtime["model"],
                model_provider=provider,
            )
        else:
            emit("正在创建单篇研读对话线程。")
            thread = codex.thread_start(
                cwd=str(app_data_dir()),
                sandbox=Sandbox.full_access,
                approval_mode=ApprovalMode.deny_all,
                model=runtime["model"],
                model_provider=provider,
                ephemeral=False,
            )

        local_image_paths = [str(path) for path in (image_paths or []) if str(path).strip()]
        pdf_text = ""
        if include_paper_context and pdf_path:
            pdf_text = _extract_pdf_text(pdf_path)
            if pdf_text:
                emit(f"已提取本地 PDF 文本（{len(pdf_text)} 字），正在回答。")
        turn_input = [
            TextInput(
                build_reading_chat_prompt(
                    item=item,
                    pdf_path=pdf_path,
                    user_question=user_question,
                    include_paper_context=include_paper_context,
                    image_count=len(local_image_paths),
                    pdf_text=pdf_text,
                )
            ),
            *[LocalImageInput(path) for path in local_image_paths],
        ]
        result = run_thread_turn_with_diagnostics(
            thread,
            turn_input,
            summary=ReasoningSummary(root="concise"),
        )

    if not result.final_response:
        detail = result.diagnostics.get("error") or "Codex turn 已完成，但没有收到任何 assistant 文本。"
        raise RuntimeError(friendly_codex_error(RuntimeError(detail)))
    return {
        "thread_id": thread.id,
        "assistant_message": result.final_response,
        "turn_id": result.turn_id,
        "turn_status": result.status,
        "usage": result.to_api_payload().get("usage"),
        "diagnostics": result.diagnostics,
    }
