"""综述写作 (writing) 的 AI 对话与任务编排。

搬运自 guangming-ai-workbench（_gwb_orig），适配 web-library 的 Codex 接入方式：
- 复用 ``codex_agent.runner`` 的 ``Codex`` / ``thread_start`` / ``thread_resume`` /
  ``run_thread_turn_with_diagnostics``，使同一 thread 跨阶段保留对话记忆。
- 复用原版的阶段提示词、<guangming_actions> 动作块协议与解析逻辑。
- mapping 阶段按大纲叶子小节逐段调用 Codex，生成"小节-文献"映射（含引用角色 /
  写作内容备注 / 证据细节 / 缺失细节），写入本地 writing_section_mappings.json。
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox, TextInput
from openai_codex.generated.v2_all import ReasoningSummary

from .runner import (
    build_config_overrides,
    build_runtime_config,
    codex_home_dir,
    friendly_codex_error,
    run_thread_turn_with_diagnostics,
)
from .. import writing as store

STAGE_GUIDES = {
    "topic": "当前阶段是「拟定主题」。你需要基于 CSV 中的已选文献和已选主题状态，帮助用户形成合适的综述主题；如果文献不足，请给出可复制到文献检索页的完整快速检索要求；如果需要更多矩阵信息，请建议新增文献矩阵字段、判断依据和格式要求。",
    "outline": "当前阶段是「大纲生成」。你需要基于 CSV、已选主题、前序讨论和本地大纲文件，帮助用户生成、比较或修改综述大纲。用户修改的大纲以本地 outline.md 为准。",
    "mapping": "当前阶段是「内容核对」。你必须先读取最新 outline.md，以没有下级子节的叶子小节作为分配依据；再基于 writing_sources.csv、文献矩阵和每篇论文的 paper_dir，为当前叶子小节生成小节-文献映射记录；如果缺少文献，请给出可复制到文献检索页的完整快速检索要求。",
    "draft": "当前阶段是「综述生成」。你需要基于 CSV、outline.md、writing_section_mappings.json 和用户要求，直接查看并编辑本地 survey.md。右侧回复只说明你做了什么、还需要用户确认什么，不要把完整正文复制到聊天气泡。",
}

_ACTION_SCHEMA_FULL = """\
<guangming_actions>{{
  "topic_options": [
    {{"id": "A", "title": "可选综述主题", "reason": "为什么适合"}}
  ],
  "search_prompts": [
    {{"label": "补充检索", "request": "完整检索要求，可以直接粘贴到文献检索框", "reason": "为什么需要补充检索"}}
  ],
  "matrix_field_suggestions": [
    {{"name": "字段名称", "rule": "判断依据和格式要求，例如输出布尔值/分类/字数限制", "reason": "为什么需要这个字段"}}
  ],
  "writing_mappings": [
    {{"section_id": "section-id", "paper_id": "paper-xxxx", "citation_role": "核心证据/背景定义/方法对比/实验支撑/挑战展望/辅助证据", "writing_note": "这篇文献在当前小节中具体写什么", "evidence_detail": "可写入正文的真实方法、实验、数据或论据细节", "missing_detail": "仍需从 PDF 或资料补查的内容"}}
  ]
}}</guangming_actions>"""

# 每阶段允许出现的 action 键；用于裁剪动作块示例
_ACTION_KEYS_BY_STAGE: dict[str, list[str]] = {
    "topic": ["topic_options", "search_prompts", "matrix_field_suggestions"],
    "outline": ["topic_options", "search_prompts", "matrix_field_suggestions"],
    "mapping": ["topic_options", "search_prompts", "matrix_field_suggestions", "writing_mappings"],
    "draft": ["search_prompts", "writing_mappings"],
}


def _action_schema_for_stage(stage: str) -> str:
    keys = _ACTION_KEYS_BY_STAGE.get(stage, _ACTION_KEYS_BY_STAGE["topic"])
    lines: list[str] = []
    for key in keys:
        if key == "topic_options":
            lines.append('  "topic_options": [')
            lines.append('    {"id": "A", "title": "可选综述主题", "reason": "为什么适合"}')
            lines.append('  ],')
        elif key == "search_prompts":
            lines.append('  "search_prompts": [')
            lines.append('    {"label": "补充检索", "request": "完整检索要求，可以直接粘贴到文献检索框", "reason": "为什么需要补充检索"}')
            lines.append('  ],')
        elif key == "matrix_field_suggestions":
            lines.append('  "matrix_field_suggestions": [')
            lines.append('    {"name": "字段名称", "rule": "判断依据和格式要求，例如输出布尔值/分类/字数限制", "reason": "为什么需要这个字段"}')
            lines.append('  ],')
        elif key == "writing_mappings":
            lines.append('  "writing_mappings": [')
            lines.append('    {"section_id": "section-id", "paper_id": "paper-xxxx", "citation_role": "核心证据/背景定义/方法对比/实验支撑/挑战展望/辅助证据", "writing_note": "这篇文献在当前小节中具体写什么", "evidence_detail": "可写入正文的真实方法、实验、数据或论据细节", "missing_detail": "仍需从 PDF 或资料补查的内容"}')
            lines.append('  ]')
    # 去掉最后一项的逗号
    body = "\n".join(lines)
    return f"<guangming_actions>{{\n{body}\n}}</guangming_actions>"


# 保留旧引用兼容 ACTION_SCHEMA
ACTION_SCHEMA = _ACTION_SCHEMA_FULL

STAGE_LABELS = {
    "topic": "拟定主题",
    "outline": "大纲生成",
    "mapping": "内容核对",
    "draft": "综述生成",
}


# --------------------------------------------------------------------------- #
# action block parsing (verbatim from guangming-ai-workbench)
# --------------------------------------------------------------------------- #
def clean_action_items(items: Any, allowed_keys: set[str]) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        row = {key: str(item.get(key) or "").strip() for key in allowed_keys}
        if any(row.values()):
            cleaned.append(row)
    return cleaned


def normalize_actions(data: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(data, dict):
        data = {}
    return {
        "topic_options": clean_action_items(data.get("topic_options"), {"id", "title", "reason"}),
        "search_prompts": clean_action_items(data.get("search_prompts"), {"label", "request", "reason"}),
        "matrix_field_suggestions": clean_action_items(data.get("matrix_field_suggestions"), {"name", "rule", "reason"}),
        "writing_mappings": clean_action_items(
            data.get("writing_mappings"),
            {"section_id", "paper_id", "citation_role", "writing_note", "evidence_detail", "missing_detail"},
        ),
    }


def extract_actions(text: str) -> tuple[str, dict[str, list[dict[str, str]]]]:
    pattern = re.compile(r"<guangming_actions>\s*(\{.*?\})\s*</guangming_actions>", flags=re.DOTALL)
    match = pattern.search(text or "")
    if not match:
        return (text or "").strip(), normalize_actions({})
    display_text = pattern.sub("", text or "").strip()
    try:
        actions = normalize_actions(json.loads(match.group(1)))
    except json.JSONDecodeError:
        actions = normalize_actions({})
    return display_text, actions


# --------------------------------------------------------------------------- #
# prompt building (verbatim from guangming-ai-workbench)
# --------------------------------------------------------------------------- #
def build_writing_prompt(
    *,
    stage: str,
    user_question: str,
    writing_dir: str,
    csv_path: str,
    outline_path: str,
    survey_path: str,
    mapping_path: str,
    selected_topic: str,
    include_context: bool,
    outline_changed: bool,
    draft_changed: bool,
    library_id: str,
) -> str:
    stage_guide = STAGE_GUIDES.get(stage, STAGE_GUIDES["topic"])
    context_rule = (
        "本轮需要重新关注提供的 CSV、outline.md 和 survey.md 路径。"
        if include_context
        else "本轮沿用当前 thread 中已经提供过的项目写作上下文；只有当用户问题需要时再读取本地文件。"
    )
    outline_rule = "用户修改过 outline.md，本轮必须以最新 outline.md 为准。" if outline_changed else "outline.md 未检测到新的用户修改。"
    draft_rule = "用户修改过 survey.md，本轮必须尊重最新 survey.md。" if draft_changed else "survey.md 未检测到新的用户修改。"
    topic_rule = f"当前用户已选择的综述主题是：{selected_topic}" if selected_topic else "当前还没有用户确认的综述主题。"

    is_topic = stage == "topic"
    is_outline = stage == "outline"
    is_mapping = stage == "mapping"
    is_draft = stage == "draft"
    after_topic = not is_topic  # outline / mapping / draft
    mapping_or_draft = is_mapping or is_draft

    rules: list[str] = []
    rule_num = 0

    def R(text: str) -> str:
        nonlocal rule_num
        rule_num += 1
        return f"{rule_num}. {text}"

    # ---- 始终包含 ----
    rules.append(R("你必须围绕当前文库工作，不要修改无关文件。"))
    rules.append(R(f"当前写作 CSV 路径：{csv_path}"))

    # ---- 大纲阶段及之后 ----
    if after_topic:
        rules.append(R(f"当前大纲 Markdown 路径：{outline_path}"))

    # ---- draft 阶段 ----
    if is_draft:
        rules.append(R(f"当前综述 Markdown 路径：{survey_path}"))

    # ---- mapping / draft ----
    if mapping_or_draft:
        rules.append(R(f"当前小节-文献映射 JSON 路径：{store.writing_section_mappings_relative_path(library_id)}；生成正文时必须优先按这个文件中的小节级备注组织引用和论据。"))

    # ---- 始终包含 ----
    rules.append(R(topic_rule))
    rules.append(R(context_rule))

    # ---- 大纲阶段及之后 ----
    if after_topic:
        rules.append(R(outline_rule))

    # ---- outline 阶段 ----
    if is_outline:
        rules.append(R("如果用户要求生成或修改大纲，必须将最终大纲直接写入 outline.md；聊天回复只保留沟通摘要，不要输出完整大纲。"))

    # ---- draft 阶段 ----
    if is_draft:
        rules.append(R(draft_rule))
        rules.append(R("如果需要生成正文，必须直接编辑 survey.md；聊天回复只保留沟通摘要，不要输出完整文章。"))
        rules.append(R('正文引用第一版使用数字引用，例如 [1]、[2]，并在文末生成「参考文献」列表。'))

    # ---- topic / outline 阶段：信息缺口检查 ----
    if is_topic or is_outline:
        rules.append(R("如果信息不足，要先在面向用户的回复中清楚说明缺口是什么、为什么会影响后续写作，再给出后续检索提示词或文献矩阵字段建议。"))
        rules.append(R("如果你建议继续检索，必须在正文中解释「为什么要检索」和「希望补到什么类型的证据」，并给出完整、可直接执行的检索要求，不要只给关键词片段。"))
        rules.append(R("如果你建议新增文献矩阵字段，必须在正文中解释「为什么需要这些字段」和「这些字段会服务哪个写作判断」，并同时给出字段名、判断依据和格式要求，例如布尔值、分类范围、字数限制或输出格式。"))

    # ---- topic 阶段 ----
    if is_topic:
        rules.append(R("如果你给出主题候选，请使用 A/B/C/D 这样的选项 id，并给出简短理由。"))

    # ---- mapping 阶段 ----
    if is_mapping:
        rules.append(R("必须以最新 outline.md 的叶子小节为准：如果 `1` 下面有 `1.1 / 1.2`，只处理 `1.1 / 1.2`，不要再把 `1` 当成独立小节分配；只有没有下级子节的章节才作为分配单元。必须在动作块的 writing_mappings 中返回当前小节的 section_id、paper_id、citation_role、writing_note、evidence_detail、missing_detail，由后端写入 writing_section_mappings.json；不要只在正文里描述。"))
        rules.append(R("正文可以说明分配逻辑，但不要声称「我已经手动编辑了 CSV」。系统会根据 writing_mappings 自动写入；如果无法给出 writing_mappings，必须明确告诉用户「尚未写入」。"))

    # ---- 始终包含 ----
    rules.append(R("跳转检索和跳转文献矩阵不是固定流程。只有当你已经在正文中明确建议用户补充检索或新增矩阵字段时，才在动作块中填入对应数组；如果当前信息已经足够，就保持对应数组为空，不要生成不必要的按钮。"))

    action_schema = _action_schema_for_stage(stage)
    rules.append(f"回复末尾必须附加一个可解析动作块；如果没有对应内容，数组留空。动作块格式如下：\n{action_schema}")

    rule_lines = "\n".join(rules)
    return f"""
你是「光明文献库」的综述写作助手，正在同一个 thread 中跨阶段帮助用户完成本地文献综述。
阶段任务：{stage_guide}

重要要求：
{rule_lines}

用户本轮请求：{user_question}
""".strip()


def build_writing_prompt_v2(
    *,
    stage: str,
    user_question: str,
    writing_dir: str,
    csv_path: str,
    outline_path: str,
    survey_path: str,
    mapping_path: str,
    selected_topic: str,
    include_context: bool,
    outline_changed: bool,
    draft_changed: bool,
) -> str:
    stage_guide = STAGE_GUIDES.get(stage, STAGE_GUIDES["topic"])
    context_rule = (
        "本轮需要重新关注下面提供的绝对路径和当前写作目录。"
        if include_context
        else "本轮沿用当前 thread 中已经提供过的项目上下文，只有在需要时再读取本地文件。"
    )
    outline_rule = (
        f"用户修改过大纲，本轮必须以最新的 `{outline_path}` 为准。"
        if outline_changed
        else "outline.md 未检测到新的用户修改。"
    )
    draft_rule = (
        f"用户修改过正文，本轮必须尊重最新的 `{survey_path}`。"
        if draft_changed
        else "survey.md 未检测到新的用户修改。"
    )
    topic_rule = f"当前用户已选择的综述主题是：{selected_topic}" if selected_topic else "当前还没有用户确认的综述主题。"

    is_topic = stage == "topic"
    is_outline = stage == "outline"
    is_mapping = stage == "mapping"
    is_draft = stage == "draft"
    after_topic = not is_topic
    mapping_or_draft = is_mapping or is_draft

    rules: list[str] = []
    rule_num = 0

    def R(text: str) -> str:
        nonlocal rule_num
        rule_num += 1
        return f"{rule_num}. {text}"

    rules.append(R("你必须围绕当前文库工作，不要修改无关文件。"))
    rules.append(R(f"当前唯一允许创建、编辑或覆盖的写作目录是：`{writing_dir}`。严禁修改任何其他文库的 `writing/` 目录。"))
    rules.append(R(f"当前写作 CSV 的绝对路径是：`{csv_path}`。"))

    if after_topic:
        rules.append(R(f"当前大纲 Markdown 的绝对路径是：`{outline_path}`。"))

    if is_draft:
        rules.append(R(f"当前综述 Markdown 的绝对路径是：`{survey_path}`。"))

    if mapping_or_draft:
        rules.append(R(f"当前小节-文献映射 JSON 的绝对路径是：`{mapping_path}`；生成正文时必须优先按这个文件中的小节级备注组织引用和论据。"))

    rules.append(R(topic_rule))
    rules.append(R(context_rule))

    if after_topic:
        rules.append(R(outline_rule))

    if is_outline:
        rules.append(R(f"如果用户要求生成或修改大纲，必须把最终结果直接写入 `{outline_path}`；聊天回复只保留沟通摘要，不要输出完整大纲。"))

    if is_draft:
        rules.append(R(draft_rule))
        rules.append(R(f"如果需要生成正文，必须直接编辑 `{survey_path}`；聊天回复只保留沟通摘要，不要输出完整文章。"))
        rules.append(R("正文引用第一版使用数字引用，例如 [1]、[2]，并在文末生成“参考文献”列表。"))

    if is_topic or is_outline:
        rules.append(R("如果信息不足，要先在面向用户的回复中清楚说明缺口是什么、为什么会影响后续写作，再给出后续检索提示词或文献矩阵字段建议。"))
        rules.append(R("如果你建议继续检索，必须在正文中解释为什么要检索，以及希望补到什么类型的证据，并给出完整、可直接执行的检索要求。"))
        rules.append(R("如果你建议新增文献矩阵字段，必须解释为什么需要这些字段，以及这些字段服务哪个写作判断，并同时给出字段名、判断依据和格式要求。"))

    if is_topic:
        rules.append(R("如果你给出主题候选，请使用 A/B/C/D 这样的选项 id，并给出简短理由。"))

    if is_mapping:
        rules.append(R("必须以最新大纲的叶子小节为准：如果 `1` 下面有 `1.1 / 1.2`，只处理 `1.1 / 1.2`，不要再把 `1` 当成独立小节分配。"))
        rules.append(R("必须在动作块的 `writing_mappings` 中返回当前小节的 `section_id`、`paper_id`、`citation_role`、`writing_note`、`evidence_detail`、`missing_detail`，由后端写入映射文件；不要只在正文里描述。"))
        rules.append(R("正文可以说明分配逻辑，但不要声称已经手动编辑了 CSV；系统会根据 `writing_mappings` 自动写入。"))

    rules.append(R("跳转检索和跳转文献矩阵不是固定流程。只有当你已经在正文中明确建议用户补充检索或新增矩阵字段时，才在动作块中填入对应数组。"))

    action_schema = _action_schema_for_stage(stage)
    rules.append(f"回复末尾必须附加一个可解析动作块；如果没有对应内容，数组留空。动作块格式如下：\n{action_schema}")

    rule_lines = "\n".join(rules)
    return f"""
你是「光明文献库」的综述写作助手，正在同一个 thread 中跨阶段帮助用户完成本地文献综述。
阶段任务：{stage_guide}

重要要求：
{rule_lines}

用户本轮请求：{user_question}
""".strip()


def build_writing_prompt(
    *,
    stage: str,
    user_question: str,
    writing_dir: str,
    csv_path: str,
    outline_path: str,
    survey_path: str,
    mapping_path: str,
    selected_topic: str,
    include_context: bool,
    outline_changed: bool,
    draft_changed: bool,
    library_id: str,
) -> str:
    # Keep the legacy entry point, but force it onto the current-library,
    # absolute-path prompt contract.
    _ = library_id
    return build_writing_prompt_v2(
        stage=stage,
        user_question=user_question,
        writing_dir=writing_dir,
        csv_path=csv_path,
        outline_path=outline_path,
        survey_path=survey_path,
        mapping_path=mapping_path,
        selected_topic=selected_topic,
        include_context=include_context,
        outline_changed=outline_changed,
        draft_changed=draft_changed,
    )


# --------------------------------------------------------------------------- #
# single turn via persistent thread
# --------------------------------------------------------------------------- #
def run_writing_turn(
    *,
    library: dict[str, Any],
    thread_id: str | None,
    stage: str,
    user_question: str,
    csv_path: str,
    outline_path: str,
    survey_path: str,
    selected_topic: str = "",
    include_context: bool,
    outline_changed: bool,
    draft_changed: bool,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    runtime = build_runtime_config(library, store.codex_config_for(library))
    provider = runtime["model_provider"]
    working_dir = store.writing_dir_path(library).resolve()
    config = CodexConfig(
        cwd=str(working_dir),
        env={"CODEX_HOME": str(codex_home_dir(library))},
        config_overrides=build_config_overrides(runtime, reasoning_effort=runtime.get("reasoning_effort", "high")),
    )

    def emit(message: str) -> None:
        if progress:
            progress(message)

    with Codex(config) as codex:
        codex.login_api_key(runtime["api_key"])
        if thread_id:
            emit("正在恢复综述写作对话线程。")
            thread = codex.thread_resume(
                thread_id,
                cwd=str(working_dir),
                sandbox=Sandbox.workspace_write,
                approval_mode=ApprovalMode.deny_all,
                model=runtime["model"],
                model_provider=provider,
            )
        else:
            emit("正在创建综述写作对话线程。")
            thread = codex.thread_start(
                cwd=str(working_dir),
                sandbox=Sandbox.workspace_write,
                approval_mode=ApprovalMode.deny_all,
                model=runtime["model"],
                model_provider=provider,
                ephemeral=False,
            )

        turn_input = [
            TextInput(
                build_writing_prompt_v2(
                    stage=stage,
                    user_question=user_question,
                    writing_dir=str(working_dir),
                    csv_path=csv_path,
                    outline_path=outline_path,
                    survey_path=survey_path,
                    mapping_path=str(store.writing_section_mappings_path(library).resolve()),
                    selected_topic=selected_topic,
                    include_context=include_context,
                    outline_changed=outline_changed,
                    draft_changed=draft_changed,
                )
            )
        ]
        emit("智能体已接收任务，开始处理当前写作阶段。")
        result = run_thread_turn_with_diagnostics(
            thread,
            turn_input,
            approval_mode=ApprovalMode.deny_all,
            sandbox=Sandbox.workspace_write,
            summary=ReasoningSummary(root="concise"),
            on_event=_observe_progress(progress),
        )

    if not result.final_response:
        detail = result.diagnostics.get("error") or "Codex turn 已完成，但没有收到任何 assistant 文本。"
        raise RuntimeError(friendly_codex_error(RuntimeError(detail)))
    display_text, actions = extract_actions(result.final_response)
    return {
        "thread_id": thread.id,
        "assistant_message": display_text,
        "actions": actions,
        "turn_id": result.turn_id,
        "turn_status": result.status,
        "usage": result.to_api_payload().get("usage"),
        "diagnostics": result.diagnostics,
    }


def _observe_progress(progress: Callable[[str], None] | None):
    """Translate codex streaming events into human-readable progress lines."""

    def on_event(event: Any) -> None:
        if progress is None:
            return
        payload = getattr(event, "payload", None)
        from openai_codex.generated.v2_all import (
            AgentMessageDeltaNotification,
            ItemCompletedNotification,
            ReasoningTextDeltaNotification,
            ReasoningSummaryTextDeltaNotification,
            CommandExecutionThreadItem,
        )

        if isinstance(payload, AgentMessageDeltaNotification):
            # delta-only events are too noisy; skip detailed emit here.
            return
        if isinstance(payload, ReasoningSummaryTextDeltaNotification):
            return
        if isinstance(payload, ReasoningTextDeltaNotification):
            progress("智能体正在分析当前阶段任务与本地写作材料。")
            return
        if isinstance(payload, ItemCompletedNotification):
            item = payload.item.root if hasattr(payload.item, "root") else payload.item
            if isinstance(item, CommandExecutionThreadItem):
                progress(f"已执行本地辅助命令，状态：{item.status.value}。")
            return

    return on_event


# --------------------------------------------------------------------------- #
# background task orchestration
# --------------------------------------------------------------------------- #
_TASKS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _store_task(library_id: str, data: dict[str, Any]) -> None:
    with _LOCK:
        _TASKS[library_id] = data


def get_task(library_id: str) -> dict[str, Any]:
    with _LOCK:
        return dict(_TASKS.get(library_id, {"status": "idle", "progress": [], "result": "", "error": ""}))


def _is_running(library_id: str, run_id: str) -> bool:
    with _LOCK:
        task = _TASKS.get(library_id)
        return bool(task and task.get("run_id") == run_id and task.get("status") == "running")


def _append_event(library_id: str, run_id: str, message: str, kind: str = "info") -> None:
    with _LOCK:
        task = _TASKS.get(library_id)
        if not task or task.get("run_id") != run_id:
            return
        task.setdefault("events", []).append({"message": message, "kind": kind})
        task["events"] = task["events"][-30:]


def _upsert_task(library_id: str, run_id: str, **fields: Any) -> None:
    with _LOCK:
        task = _TASKS.get(library_id)
        if not task or task.get("run_id") != run_id:
            task = {"run_id": run_id, "status": "running", "events": []}
            _TASKS[library_id] = task
        task.update(fields)


def start_writing_task(
    *,
    library: dict[str, Any],
    library_id: str,
    run_id: str,
    user_question: str,
    stage: str,
) -> None:
    _store_task(library_id, {"run_id": run_id, "status": "running", "events": ["已提交 AI 生成任务。"], "result": "", "error": ""})
    thread = threading.Thread(
        target=execute_writing_chat_task,
        args=(library, library_id, run_id, user_question, stage),
        daemon=True,
    )
    thread.start()


def stop_writing_task(library_id: str, run_id: str) -> None:
    _upsert_task(library_id, run_id, status="stopped", finished_at=store.now_iso())


def execute_writing_chat_task(
    library: dict[str, Any],
    library_id: str,
    run_id: str,
    user_question: str,
    stage: str,
) -> None:
    try:
        store.ensure_writing_files(library)
        chat_state = store.load_writing_chat_state(library)
        thread_id = chat_state.get("thread_id")
        csv_path = str(store.writing_sources_path(library).resolve())
        outline_path = str(store.writing_outline_path(library).resolve())
        survey_path = str(store.writing_survey_path(library).resolve())
        mapping_path = str(store.writing_section_mappings_path(library).resolve())
        csv_hash = store.text_hash(store.load_writing_csv(library))
        outline_hash = store.text_hash(store.load_outline(library))
        draft_hash = store.text_hash(store.load_survey(library))
        include_context = not thread_id or chat_state.get("last_stage") != stage or chat_state.get("last_csv_hash") != csv_hash
        outline_changed = chat_state.get("last_outline_hash") != outline_hash
        draft_changed = chat_state.get("last_draft_hash") != draft_hash
        _append_event(library_id, run_id, f"正在进入「{STAGE_LABELS.get(stage, stage)}」阶段对话。")

        if stage == "mapping":
            sections = store.parse_outline_sections(store.load_outline(library))
            paper_context = store.selected_writing_paper_context(library)
            _upsert_task(library_id, run_id, total_sections=len(sections), completed_sections=0, current_section="")
            if not sections:
                raise RuntimeError("当前大纲没有可识别章节，请先生成并保存大纲。")
            if not paper_context:
                raise RuntimeError("当前没有已选写作文献，请先在第一阶段选择论文。")
            _append_event(library_id, run_id, f"将按 {len(sections)} 个小节逐段生成小节-文献映射。")
            completed_sections = 0
            collected_count = 0
            for section in sections:
                if not _is_running(library_id, run_id):
                    _append_event(library_id, run_id, "用户已停止本次内容核对任务。", kind="warning")
                    return
                _upsert_task(library_id, run_id, current_section=section.get("title"))
                _append_event(library_id, run_id, f"正在处理小节：{section.get('title')}")
                section_question = "\n".join(
                    [
                        "请只处理下面这个大纲小节，生成该小节需要引用的文献及小节级写作内容备注。",
                        "必须从候选论文中选择真正适合本小节的论文，不要把所有论文都塞进来。",
                        "写作备注必须针对当前小节，说明这篇文献在本小节可以写成什么具体内容；如果需要实验指标、方法细节或数据但资料不足，写入 missing_detail。",
                        "论文的文献矩阵字段是论文本地资料，目录中可能有 PDF 和相关资料；可以读取它们补充真实细节，不能虚构。",
                        "必须在 <guangming_actions> 的 writing_mappings 数组里返回结果，section_id 必须使用给定值。",
                        "",
                        f"当前小节：{json.dumps(section, ensure_ascii=False)}",
                        f"已选论文上下文：{json.dumps(paper_context, ensure_ascii=False)}",
                        f"用户原始任务：{user_question}",
                    ]
                )
                result = run_writing_turn(
                    library=library,
                    thread_id=thread_id,
                    stage=stage,
                    user_question=section_question,
                    csv_path=csv_path,
                    outline_path=outline_path,
                    survey_path=survey_path,
                    selected_topic=str(store.load_writing_state(library).get("topic") or ""),
                    include_context=include_context or completed_sections == 0,
                    outline_changed=outline_changed and completed_sections == 0,
                    draft_changed=draft_changed and completed_sections == 0,
                    progress=lambda message: _append_event(library_id, run_id, message),
                )
                thread_id = result.get("thread_id") or thread_id
                result_actions = result.get("actions") or {}
                section_mappings = result_actions.get("writing_mappings") if isinstance(result_actions, dict) else []
                latest = store.replace_section_mappings(library, section, section_mappings)
                completed_sections += 1
                collected_count = len(latest)
                _upsert_task(library_id, run_id, completed_sections=completed_sections)
                _append_event(library_id, run_id, f"已写入小节映射：{section.get('title')}（累计 {collected_count} 条）。")
            store.save_writing_chat_state(
                library,
                {
                    "thread_id": thread_id,
                    "created_at": chat_state.get("created_at") or store.now_iso(),
                    "updated_at": store.now_iso(),
                    "last_stage": stage,
                    "last_csv_hash": store.text_hash(store.load_writing_csv(library)),
                    "last_outline_hash": store.text_hash(store.load_outline(library)),
                    "last_draft_hash": store.text_hash(store.load_survey(library)),
                },
            )
            store.append_writing_chat_message(
                library,
                {
                    "role": "assistant",
                    "content": f"已按当前大纲逐小节完成内容核对，并写入 `{mapping_path}`。本次共处理 {completed_sections} 个小节，生成 {collected_count} 条小节-文献映射。左侧卡片已按小节显示每篇文献的引用角色、写作内容备注、证据细节和缺失细节。",
                    "actions": {},
                    "created_at": store.now_iso(),
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "stage": stage,
                },
            )
            _upsert_task(library_id, run_id, stage=stage, status="success", finished_at=store.now_iso(), thread_id=thread_id, completed_sections=completed_sections, current_section="")
            return

        result = run_writing_turn(
            library=library,
            thread_id=thread_id,
            stage=stage,
            user_question=user_question,
            csv_path=csv_path,
            outline_path=outline_path,
            survey_path=survey_path,
            selected_topic=str(store.load_writing_state(library).get("topic") or ""),
            include_context=include_context,
            outline_changed=outline_changed,
            draft_changed=draft_changed,
            progress=lambda message: _append_event(library_id, run_id, message),
        )
        if not _is_running(library_id, run_id):
            _append_event(library_id, run_id, "用户已停止本次综述写作任务，丢弃迟到回复。", kind="warning")
            return
        thread_id = result.get("thread_id") or thread_id
        result_actions = result.get("actions") or {}
        display_actions = dict(result_actions) if isinstance(result_actions, dict) else {}
        display_actions.pop("writing_mappings", None)
        store.save_writing_chat_state(
            library,
            {
                "thread_id": thread_id,
                "created_at": chat_state.get("created_at") or store.now_iso(),
                "updated_at": store.now_iso(),
                "last_stage": stage,
                "last_csv_hash": store.text_hash(store.load_writing_csv(library)),
                "last_outline_hash": store.text_hash(store.load_outline(library)),
                "last_draft_hash": store.text_hash(store.load_survey(library)),
            },
        )
        store.append_writing_chat_message(
            library,
            {
                "role": "assistant",
                "content": result.get("assistant_message") or "综述写作任务已完成，但没有返回内容。",
                "actions": display_actions,
                "created_at": store.now_iso(),
                "run_id": run_id,
                "thread_id": thread_id,
                "stage": stage,
            },
        )
        _upsert_task(library_id, run_id, stage=stage, status="success", finished_at=store.now_iso(), thread_id=thread_id)
    except Exception as exc:  # noqa: BLE001
        store.append_writing_chat_message(
            library,
            {
                "role": "assistant",
                "content": f"综述写作任务失败：{exc}",
                "created_at": store.now_iso(),
                "run_id": run_id,
                "stage": stage,
                "error": True,
            },
        )
        _upsert_task(library_id, run_id, stage=stage, status="failed", finished_at=store.now_iso(), error=str(exc))
    finally:
        with _LOCK:
            task = _TASKS.get(library_id)
            if task and task.get("run_id") == run_id:
                _TASKS.pop(library_id, None)
