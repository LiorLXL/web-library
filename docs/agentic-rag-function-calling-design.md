# Agentic RAG（Function Calling / ReAct）设计

状态：设计稿（已 grill 确认，已实现）
目标读者：实现该功能的下一个会话
关联：`docs/openai-codex-agentic-rag-plan.md`（旧的 Codex runtime 方案，本方案取代其执行层）

## 0. 已确认实现决策（必须遵守）

- `MAX_TOOL_ITERATIONS = 5`、`MAX_TOTAL_TOKENS = 60_000` 是最终硬值；请求体不提供可控的 `max_iterations`。
- 新会话首轮必须提供 `knowledge_base_id`。`item_keys` 只在首轮作为进一步收窄条件，后端与知识库条目求交集后写入 session 快照；第二轮起忽略请求体里的 `knowledge_base_id` / `item_keys`。
- session 作用域使用首轮快照：`rag_chat_sessions.item_keys_json` 是后续工具执行的准绳，不随知识库成员变动而漂移。
- 删除知识库时级联删除绑定该 `knowledge_base_id` 的 `rag_chat_sessions` 和 `rag_chat_messages`。
- 每次请求都重新组装 `messages = [system] + pruned_history + current_user`；历史只保留最近 10 轮 user + assistant final answer，不加载历史 tool 消息或 assistant `tool_calls`。
- 不持久化 raw tool messages。数据库只保存 user 消息和 assistant final answer；assistant 行保存 `sources_json` 和精简 `tool_trace_json`。
- `search_evidence` 必须调用 `retrieve(..., include_context=False)`，只回灌摘要，不回灌全文。
- `read_chunk_context` 必须校验返回的每个 chunk 的 `item_key` 属于 session scope；target 和邻近 chunk 都注册进 `EvidenceAccumulator` 并进入最终 `sources`。
- 一期 `sources` 返回 accumulator 全集，即 Agent 看过的摘要证据和深读证据全集。
- 最后一轮和 token 超预算强制收尾都传 `tools=TOOL_SCHEMAS`，但强制 `tool_choice="none"`；若模型仍返回 `tool_calls`，后端不再执行工具，返回兜底答案并加 warning。
- 工具参数 JSON 解析失败、未知工具、工具内部异常都作为 tool error 回灌给模型；入口级错误（模型配置缺失、首轮缺 `knowledge_base_id`、session 不存在或跨 library）才让 `/rag/chat` 返回 400。
- 模型配置严格使用 `api_config_model_for_library(library_id)`。`model` 或 `api_key` 为空时 `/rag/chat` 返回 400；`base_url` 可空，若用户填完整 `/v1/chat/completions` URL，后端规范化成 OpenAI SDK 可用的 base URL。
- `/rag/agent/check` 改为新的模型配置检查，不再使用 Codex 配置，也不真调 API。
- `/rag/chat` 不再做旧式预检索和无证据短路；证据不足由 ReAct 循环后的 final answer 表达。
- 一期实现 `list_scope_documents`，默认 50、最大 100，只返回精简题录信息。
- 前端一期做最小可见 `tool_trace` 展示，保存 `knowledgeState.conversationId`，切换/删除知识库时清空会话。
- `run_agentic_chat(..., client=None)` 支持直接注入 fake OpenAI client；生产路径仅在 `client is None` 时调用 `build_client(model_config)`。

## 1. 背景与目标

当前 `/rag/chat` 是"一次性 RAG"：后端固定检索一次（`mode=auto`, `top_k=8`），把 Evidence Pack 整包塞进 prompt，Codex runtime 单轮 `ephemeral` 生成，无对话记忆、无工具调用、无多轮检索。Agent 没有 agency。

本方案用 **OpenAI function calling + ReAct 循环** 重建执行层，让 Agent：

- 自主决定检索什么、用什么模式、检索几次
- 先看摘要证据，再按需拉取全文上下文
- 具备服务端对话记忆（多轮追问）
- 在受控循环上限和 token 预算内运行

**不变的资产（复用，不重写）**：Evidence Pack 结构、检索工具（`retrieve` / `keyword_search` / `metadata_search` / `chunk_read` / 即将有的 `semantic_search`）、`SKILL.md` 证据规则、citation 格式、知识库作用域机制。

**被替换的部分**：仅 `codex_agent/runner.py` 那层 Codex 调用壳。

## 2. 核心原则（保留旧方案的安全边界）

- Agent 不直接访问 `zotero.sqlite` / `rag.sqlite`，只能通过注册的工具。
- **作用域（`knowledge_base_id` / 首轮快照 `item_keys`）由后端在会话创建时绑定，注入到每次工具执行中；Agent 的工具入参里不含作用域字段，无法越权。**
- 检索仍由后端受控执行，Agent 只发起"意图"（query + mode），不碰 SQL。
- 循环有硬上限，token 有预算，保证可终止、成本可控；硬值固定为 `MAX_TOOL_ITERATIONS = 5`、`MAX_TOTAL_TOKENS = 60_000`。

## 3. 目标架构

```text
knowledge.js  /rag/chat
        ↓
Flask: api_rag_chat  (web.py)
        ↓
rag/agent/loop.py      ReAct 主循环
  ├─ 载入会话历史 (rag/agent/memory.py)
  ├─ 组装 system prompt (rag/agent/prompts.py + SKILL.md)
  ├─ while 循环:
  │     client.chat.completions.create(tools=TOOL_SCHEMAS)
  │     ├─ 有 tool_calls → 后端执行工具 (rag/agent/tools.py)
  │     │     └─ 注入作用域 → 调 rag/retriever & rag/tools
  │     │     └─ 结果累积进 EvidenceAccumulator
  │     └─ 无 tool_calls → final answer，退出
        ↓
answer + sources(实际被检索到的证据) + tool_trace + usage
        ↓
持久化本轮对话 (rag/agent/memory.py)
```

新增模块：

```text
rag/agent/
  __init__.py      # 导出 run_agentic_chat
  loop.py          # ReAct 主循环 + 终止逻辑
  tools.py         # 工具 schema 定义 + 后端执行分发（含作用域注入）
  evidence.py      # EvidenceAccumulator：跨多次工具调用的证据池 + 去重 + evidence_id 分配
  memory.py        # 会话持久化（rag_chat_sessions / rag_chat_messages）
  prompts.py       # system prompt 组装
  client.py        # OpenAI 客户端构造（复用 library 的 model 配置）
```

`codex_agent/` 保留不动（未来若需代码执行 agent 再用）。

## 4. 工具设计（暴露给 Agent 的 function schema）

只暴露 3 个工具，覆盖"搜 → 读 → 看范围"。**作用域字段（knowledge_base_id/item_keys）不出现在 schema 里**，由后端注入。

### 4.1 `search_evidence`

Agent 发起一次检索。默认只返回摘要（excerpt），省 token；全文按需再用 `read_chunk_context` 拉。

```json
{
  "type": "function",
  "function": {
    "name": "search_evidence",
    "description": "在当前知识库范围内检索证据。返回证据摘要列表，每条含 evidence_id、citation、标题、摘要。需要某条证据的完整上下文时再用 read_chunk_context。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "检索查询，可用中文或英文关键词"},
        "mode": {
          "type": "string",
          "enum": ["hybrid", "keyword", "semantic", "metadata"],
          "description": "hybrid=关键词+语义融合(默认); keyword=全文BM25; semantic=向量; metadata=题录字段"
        },
        "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "description": "返回条数，默认 8"}
      },
      "required": ["query"]
    }
  }
}
```

后端执行：`mode` 默认 `hybrid`，注入 scope 后调 `rag.retriever.retrieve(..., include_context=False)`（只要摘要）。返回给 Agent 的是精简结构（见 4.4）。

### 4.2 `read_chunk_context`

Agent 决定深读某条证据的完整上下文。

```json
{
  "type": "function",
  "function": {
    "name": "read_chunk_context",
    "description": "读取指定 chunk 及其相邻上下文的完整文本，用于核实细节、方法、实验结果。",
    "parameters": {
      "type": "object",
      "properties": {
        "chunk_id": {"type": "string", "description": "来自 search_evidence 结果的 chunk_id"},
        "window_size": {"type": "integer", "minimum": 0, "maximum": 3, "description": "前后各取几个相邻 chunk，默认 1"}
      },
      "required": ["chunk_id"]
    }
  }
}
```

后端执行：调 `rag.tools.chunk_read`。**安全校验：返回的每个 chunk 必须属于 session 快照 `item_keys`**，否则返回错误（防 Agent 猜 chunk_id 越权）。通过校验后，target chunk 和 window 邻近 chunk 都注册进 `EvidenceAccumulator`，并以带 citation 的精简结构回灌给 Agent；这里可以返回全文 `text`，因为深读是按需触发。

### 4.3 `list_scope_documents`

Agent 想先了解知识库里有哪些文献（尤其"综述这个库讲了什么"这类问题）。

```json
{
  "type": "function",
  "function": {
    "name": "list_scope_documents",
    "description": "列出当前知识库范围内的文献清单（标题/作者/年份/是否有全文解析），用于了解可用范围或规划检索。",
    "parameters": {
      "type": "object",
      "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "最多返回条数，默认 50"}
      }
    }
  }
}
```

后端执行：读作用域内 `rag_documents`（去重到 item_key 级），返回标题/作者/年份/source_type 汇总。

### 4.4 工具返回给 Agent 的精简格式

工具结果作为 `role: "tool"` 消息回灌，必须精简以省 token。`search_evidence` 返回：

```json
{
  "mode": "hybrid",
  "count": 6,
  "results": [
    {
      "evidence_id": "ev-1",
      "citation": "[ITEM0001:chunk-abc123]",
      "source_type": "chunk",
      "title": "标题",
      "authors_text": "作者",
      "year": "2023",
      "section_title": "Method",
      "chunk_id": "chunk-abc123",
      "excerpt": "不超过 300 字的摘要"
    }
  ],
  "warnings": ["semantic_search_not_configured"]
}
```

不回灌全文（`text` 字段），全文只在 `read_chunk_context` 时给。这是控制 token 的关键。

`read_chunk_context` 返回示例：

```json
{
  "chunk_id": "chunk-abc123",
  "count": 3,
  "chunks": [
    {
      "evidence_id": "ev-7",
      "citation": "[ITEM0001:chunk-abc123]",
      "title": "标题",
      "section_title": "Method",
      "chunk_id": "chunk-abc123",
      "text": "完整 chunk 文本，按实现截断到安全长度"
    }
  ]
}
```

`tool_trace` 不保存这些完整结果，只保存工具名、精简 args、`ok`、`result_count`、`warnings` / `error`。

## 5. EvidenceAccumulator（证据池）

跨多次工具调用累积 Agent 实际看过的证据，用于：(1) 稳定分配 `evidence_id`；(2) 去重；(3) 最终把"Agent 看过的证据全集"作为 `sources` 返回给前端。

```python
class EvidenceAccumulator:
    def __init__(self) -> None:
        self._by_chunk: dict[str, dict] = {}   # chunk_id -> evidence dict
        self._order: list[str] = []             # 首次出现顺序
        self._counter: int = 0

    def register(self, raw_results: list[dict]) -> list[dict]:
        """接收 retriever 结果，去重，分配/复用 evidence_id，返回精简列表。"""
        # chunk_id 已存在 → 复用旧 evidence_id
        # 新 chunk_id → ev-{++counter}
        # metadata 类无 chunk_id → 用 f"{item_key}:metadata" 作 key

    def all_sources(self) -> list[dict]:
        """按出现顺序返回完整证据，用于最终 sources 字段。"""
```

要点：
- citation 用现成的 `[item_key:chunk_id]`，本来就跨调用稳定，`evidence_id` 只是会话内的短标签。
- 最终返回前端的 `sources` = accumulator 里所有证据（Agent 看过的全集），包括 `search_evidence` 摘要结果和 `read_chunk_context` 深读结果。若想更精确，可后处理只保留答案文本里 citation 命中的，但一期先返回全集。

## 6. ReAct 主循环（loop.py）

### 6.1 伪代码

```python
MAX_TOOL_ITERATIONS = 5        # 硬上限
MAX_TOTAL_TOKENS = 60_000      # 预算（累计 usage，超了强制收尾）

def run_agentic_chat(*, library, model_config, conversation_id, question,
                     knowledge_base_id="", item_keys=None,
                     client=None) -> dict:
    session = memory.get_or_create_session(
        library,
        conversation_id=conversation_id,
        knowledge_base_id=knowledge_base_id,  # 仅首轮必填并生效
        item_keys=item_keys,                  # 仅首轮收窄，求交集后快照
    )
    scope = ScopeContext(session.knowledge_base_id, session.item_keys)   # 后端持有，不给 Agent
    accumulator = EvidenceAccumulator()
    active_client = client or build_client(model_config)

    history = memory.load_history(library, session.conversation_id, limit_turns=10)
    # 每轮都重新注入 system；history 只含 user + assistant final answer。
    messages = [{"role": "system", "content": build_system_prompt(max_tool_iterations=MAX_TOOL_ITERATIONS)}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    tool_trace = []
    warnings = []
    total_usage = {}

    for iteration in range(MAX_TOOL_ITERATIONS):
        force_final = iteration == MAX_TOOL_ITERATIONS - 1   # 最后一轮禁用工具，强制作答
        resp = active_client.chat.completions.create(
            model=model_config["model"],
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="none" if force_final else "auto",
            temperature=0.2,
        )
        accumulate_usage(total_usage, resp.usage)
        msg = resp.choices[0].message
        messages.append(msg.model_dump())

        if not msg.tool_calls:
            # Agent 给出最终答案
            return finalize(msg.content, accumulator, tool_trace, total_usage,
                            messages, session, library, warnings)

        if force_final:
            # 兼容 fake client 或不遵守 tool_choice 的模型：最后一轮绝不执行工具。
            warnings.append("final_tool_calls_ignored")
            return finalize(fallback_final_answer(accumulator), accumulator, tool_trace,
                            total_usage, messages, session, library, warnings)

        # 执行所有 tool_calls
        for call in msg.tool_calls:
            result, trace = execute_tool(call, library, scope, accumulator)
            tool_trace.append(trace)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        if tokens_exceeded(total_usage, MAX_TOTAL_TOKENS):
            # 预算超限 → 追加一条强制收尾指令，再跑一次 tool_choice=none；不二次强制收尾。
            messages.append({"role": "user",
                             "content": "已达检索预算上限，请基于已有证据直接作答。"})
            return force_answer(active_client, model_config, messages, accumulator,
                                tool_trace, total_usage, session, library, warnings)

    # 理论上不会走到（最后一轮 force_final 已收尾），兜底
    return force_answer(...)
```

### 6.2 终止保证

- `MAX_TOOL_ITERATIONS` 硬上限固定为 5，请求体不可调；最后一轮仍传 `tools=TOOL_SCHEMAS`，但 `tool_choice="none"` 强制不能再调工具，必须作答。
- token 预算按每次模型响应后的累计 `usage.total_tokens` 判断；`total_tokens >= 60_000` 且当前还没最终回答时，追加一次强制收尾指令，再调用一次 `tool_choice="none"`。强制收尾调用本身超预算时，不再二次调用。
- usage 兼容不同 SDK 形态：优先 `total_tokens`，没有就用 `prompt_tokens + completion_tokens`，再没有按 0 处理。
- 如果强制收尾轮仍返回 `tool_calls`，后端不执行这些工具，返回兜底答案并加 `final_tool_calls_ignored` warning。
- 两条路径都保证一定产出 final answer，不会死循环。

### 6.3 工具执行分发（tools.py）

```python
def execute_tool(call, library, scope, accumulator) -> tuple[dict, dict]:
    name = getattr(call.function, "name", "")
    try:
        args = json.loads(call.function.arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be a JSON object")
    except Exception as exc:
        result = {"error": "invalid_tool_arguments", "message": str(exc)}
        return result, {"tool": name or "unknown", "args": {}, "ok": False, "error": "invalid_tool_arguments"}

    try:
        if name == "search_evidence":
            raw = rag_retrieve(library, args["query"],
                               knowledge_base_id=scope.kb_id,   # 后端注入
                               item_keys=scope.item_keys,        # 后端注入
                               mode=args.get("mode", "hybrid"),
                               top_k=clamp(args.get("top_k", 8), 1, 20),
                               include_context=False)
            slim = accumulator.register(raw["results"])
            result = {"mode": raw["mode"], "count": len(slim),
                      "results": slim, "warnings": raw.get("warnings", [])}
        elif name == "read_chunk_context":
            result = read_context_scoped(library, scope, args, accumulator)   # 校验并注册返回 chunks
        elif name == "list_scope_documents":
            result = list_scope_docs(library, scope, args.get("limit", 50))
        else:
            result = {"error": "unknown_tool", "message": f"unknown tool: {name}"}
    except Exception as exc:
        result = {"error": "tool_failed", "message": str(exc)}     # 错误回灌给 Agent，让它自己决定下一步
    trace = summarize_tool_trace(name, args, result)  # 不含完整结果/全文
    return result, trace
```

工具报错不抛出，作为结构化 `{"error": "...", "message": "..."}` 回灌，Agent 可以据此换策略（换 query、换 mode 或直接说证据不足）。`tool_trace` 只保存精简摘要：工具名、精简 args、`ok`、`result_count`、`warnings` / `error`，不保存全文或完整工具结果。

## 7. 会话记忆（memory.py + 新表）

服务端持久化对话，支持多轮追问。加到 `store.py` 的 SCHEMA：

```sql
CREATE TABLE IF NOT EXISTS rag_chat_sessions (
  conversation_id   TEXT PRIMARY KEY,
  library_id        TEXT NOT NULL,
  knowledge_base_id TEXT NOT NULL DEFAULT '',
  item_keys_json    TEXT NOT NULL DEFAULT '[]',
  title             TEXT NOT NULL DEFAULT '',
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_chat_messages (
  message_id      TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  turn_index      INTEGER NOT NULL,
  role            TEXT NOT NULL,          -- user / assistant
  content         TEXT NOT NULL DEFAULT '',
  sources_json    TEXT NOT NULL DEFAULT '[]', -- assistant 最终答案关联的 sources
  tool_trace_json TEXT NOT NULL DEFAULT '[]', -- assistant 最终答案关联的精简工具轨迹
  created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chat_msg_conv ON rag_chat_messages(conversation_id, turn_index);
```

关键设计：
- **作用域绑定在 session 上**：新会话首轮必须传 `knowledge_base_id`；后端把知识库条目与首轮 `item_keys`（若有）求交集，写入 `rag_chat_sessions.item_keys_json` 作为快照。第二轮起从 session 读，不信任前端每次传的作用域（防止追问时作用域被篡改扩大）。
- **不持久化 raw tool messages**：当前轮的 assistant `tool_calls` / `tool` messages 只存在内存里供 ReAct 循环使用；落库只写 user 和 assistant final answer。assistant 行保存 `sources_json` 与精简 `tool_trace_json`。
- `load_history` 重建 messages 数组时，只加载最近 10 轮 user + assistant final answer，丢弃历史 tool 结果和 assistant `tool_calls`。这个裁剪策略在 memory.py 里实现，是 token 控制的第二个关键点。
- 无 `conversation_id` 传入时新建一个（`uuid4`），随响应返回，前端后续追问带上；若传入的 `conversation_id` 不存在或不属于当前 library，`/rag/chat` 返回 400。
- 删除知识库时，级联删除绑定该 `knowledge_base_id` 的 `rag_chat_sessions` 和 `rag_chat_messages`，避免旧会话继续使用已删除知识库的 scope。

## 8. API 契约变更（web.py）

`POST /api/library/<library_id>/rag/chat` 请求：

```json
{
  "question": "用户问题",
  "conversation_id": "可选，追问时带上；不带则新建会话",
  "knowledge_base_id": "首轮必须；追问忽略（以 session 存的为准）",
  "item_keys": ["可选，首轮生效，用于在 knowledge_base_id 内进一步收窄"]
}
```

入口规则：
- 无 `conversation_id` 表示新会话，必须提供 `knowledge_base_id`；否则返回 400。
- 有 `conversation_id` 表示追问，后端从 session 读取 `knowledge_base_id` / `item_keys_json`，忽略请求体里的作用域字段。
- 请求体不提供可控的 `max_iterations`；即使前端传入，后端也忽略，实际固定 `MAX_TOOL_ITERATIONS = 5`。
- `/rag/chat` 不再做旧式预检索和无证据短路；证据不足由 Agent 最终回答表达。

响应（在原字段基础上增加）：

```json
{
  "ok": true,
  "conversation_id": "conv-xxx",
  "answer": "带 citation 的答案",
  "sources": [ /* accumulator 全集，格式同现有 _rag_chat_sources */ ],
  "tool_trace": [
    {"tool": "search_evidence", "args": {"query": "...", "mode": "hybrid"}, "ok": true, "result_count": 6},
    {"tool": "read_chunk_context", "args": {"chunk_id": "chunk-abc"}, "ok": true}
  ],
  "iterations": 3,
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "warnings": []
}
```

`tool_trace` 是新的可观测性字段，前端可折叠展示"Agent 做了哪些检索"，这也是"看起来 Agentic"的直观体现。

模型配置来源：用 `api_config_model_for_library(library_id)`（现有函数，返回 model/base_url/api_key），**不再用 codex 配置**。`model` 或 `api_key` 为空时 `/rag/chat` 直接返回 400，提示先配置模型 API；`base_url` 可为空，空则让 OpenAI SDK 使用默认。若用户填的是完整 `/v1/chat/completions` URL，后端规范化成 SDK 可用的 base URL（参考 `retrieval.providers.ai_pixel_base_url` 的处理思路）。

`POST /api/library/<library_id>/rag/agent/check` 改为模型配置检查：返回 `configured`、`model`、规范化后的 `base_url`、缺失字段列表；不使用 Codex 配置，也不真调 API。

## 9. System Prompt（prompts.py）

复用 `SKILL.md` 的证据规则，但改写成"你有工具"的 agentic 版本。要点：

```text
你是 Zotero Web Library 的文库内研究助手，在受控知识库范围内回答问题。

工作方式（ReAct）：
- 你可以多次调用 search_evidence 检索证据，用 read_chunk_context 深读细节，用 list_scope_documents 了解范围。
- 先规划：判断问题需要什么证据，再检索。首次检索结果不足时，换关键词/模式再检索。
- 只有当你认为证据足够时，才直接输出最终答案（不再调用工具）。

证据与引用规则（同 SKILL.md）：
- 只能基于检索到的证据回答，不得使用外部知识补全。
- 每个事实性结论保留 Evidence Pack 中的 citation 标记 [item_key:chunk_id]。
- 证据不足时明确说明缺失的证据类型，不要编造。
- 区分论文原文、用户笔记、你的综合归纳。

约束：
- 你最多可以进行 N 轮工具调用。请高效检索，不要重复相同查询。
- 不要暴露本地路径、内部 API、chunk_id 之外的实现细节。
- 用中文回答，先给结论再给依据。
```

`N` 固定填 `MAX_TOOL_ITERATIONS = 5`，让 Agent 知道预算。每次请求都重新注入 system prompt，不依赖历史里保存 system 消息。

## 10. 安全与边界

| 风险 | 处置 |
|------|------|
| Agent 猜 chunk_id 越权读其他库 | `read_chunk_context` 校验返回的每个 chunk 的 item_key ∈ session 快照 scope，否则报错 |
| Agent 试图扩大作用域 | 作用域不在工具 schema 里，后端注入，Agent 无法influence |
| 追问时前端篡改作用域 | 第二轮起作用域从 session 快照读，忽略请求体；首轮 item_keys 只会收窄，不会扩大 knowledge_base_id |
| 删除知识库后旧会话继续可用 | 删除知识库时级联删除绑定的 chat sessions/messages |
| 死循环 / 成本失控 | 固定 `MAX_TOOL_ITERATIONS = 5` + token 预算 + 最后一轮强制 `tool_choice="none"` |
| 强制收尾轮模型仍请求工具 | 不执行工具，返回兜底答案并记录 `final_tool_calls_ignored` |
| 工具异常拖垮请求 | execute_tool 捕获工具参数/未知工具/内部异常，回灌结构化 error，不中断循环 |
| LLM 调用无超时 | client 构造时设 timeout（如 60s），避免 worker 永久阻塞 |
| 敏感信息泄露 | system prompt 明确禁止暴露路径/内部细节；sources 只含展示字段 |

## 11. 测试策略

参考现有 `tests/test_rag.py` 风格，新增 `tests/test_rag_agent.py`：

- **工具执行单测**：mock library + 内存 rag.sqlite，验证 `execute_tool` 三个工具的 scope 注入、越权 chunk 被拒、错误回灌格式。
- **EvidenceAccumulator 单测**：多次 register 去重、evidence_id 稳定复用、metadata 无 chunk_id 的 key 处理；`read_chunk_context` 返回的 target/邻近 chunks 会注册进 sources。
- **循环终止单测**：用 fake OpenAI client（返回预设的 tool_calls 序列 → 最终答案），验证：
  - 正常收敛（2-3 轮后给答案）
  - 达 `MAX_TOOL_ITERATIONS = 5` 时最后一轮 `tool_choice="none"` 且必产出答案
  - token 超预算触发一次强制收尾，强制收尾本身超预算时不二次调用
  - 最后一轮若 fake client 仍返回 tool_calls，后端不执行并返回 `final_tool_calls_ignored`
- **记忆单测**：两轮对话，验证第二轮 load_history 拿到第一轮 user/assistant final answer、作用域从 session 快照读、历史 tool 消息/assistant tool_calls 被裁剪、历史最多保留 10 轮。
- **作用域/删除单测**：首轮缺 `knowledge_base_id` 返回 400；首轮 `item_keys` 与 KB 求交集并快照；追问忽略请求体作用域；删除知识库级联删除 chat sessions/messages。
- **模型配置单测**：`/rag/chat` 缺 `model` 或 `api_key` 返回 400；完整 `/v1/chat/completions` URL 会规范化成 SDK base URL；`/rag/agent/check` 不走 Codex。
- **契约测试**：更新 `tests/test_frontend_contract.py`，`/rag/chat` 响应含 `conversation_id` / `tool_trace` / `iterations`；前端有 `knowledgeState.conversationId` 和最小 tool_trace 展示。
- **旧测试迁移**：更新或替换 `tests/test_codex_agent.py` 中断言 `/rag/chat` 调用 `rag_codex_prompt` 的用例；Codex 只保留独立能力，不再是 RAG chat 主链路。

fake client 是关键：不要在测试里真调 API。`run_agentic_chat(..., client=None)` 允许直接注入 fake client；生产路径仅 `client is None` 时调用 `build_client(model_config)`。fake client 只需实现 `client.chat.completions.create(...)`，记录每次调用的 `messages` / `tools` / `tool_choice`，并按脚本返回 assistant final 或 tool_calls。

## 12. 实现顺序（给下一个会话的 checklist）

1. `store.py`：加 `rag_chat_sessions` / `rag_chat_messages` 两张表到 SCHEMA；实现删除知识库时级联删除 chat sessions/messages。
2. `rag/agent/client.py`：从 model_config 构造 OpenAI client（base_url/api_key/timeout），处理完整 `/v1/chat/completions` URL 到 SDK base URL 的规范化；`model/api_key` 缺失由 web 入口返回 400。
3. `rag/agent/evidence.py`：EvidenceAccumulator。
4. `rag/agent/tools.py`：TOOL_SCHEMAS 常量 + execute_tool 分发 + 三个工具实现（含 scope 注入与越权校验）。
5. `rag/agent/prompts.py`：build_system_prompt。
6. `rag/agent/memory.py`：会话建/读/写 + 首轮 scope 快照 + 最近 10 轮历史裁剪；只持久化 user/assistant final answer、sources_json、tool_trace_json。
7. `rag/agent/loop.py`：run_agentic_chat 主循环 + 终止/预算逻辑；支持 `client=None` 注入 fake client。
8. `rag/agent/__init__.py` + `rag/__init__.py`：导出 run_agentic_chat。
9. `web.py`：改写 `api_rag_chat` 用 run_agentic_chat；模型配置切到 `api_config_model_for_library(library_id)`；首轮缺 `knowledge_base_id` 或模型配置缺失时返回 400；改写 `/rag/agent/check` 为模型配置检查；补 conversation_id/tool_trace。
10. `knowledge.js`：submitKnowledgeChat 带 conversation_id（存 knowledgeState）；切换/删除知识库清空 conversationId/chatMessages；渲染最小可见 tool_trace。
11. 测试：test_rag_agent.py + 更新 test_frontend_contract.py + 迁移旧 test_codex_agent.py 的 `/rag/chat` 断言。
12. 文档：更新 SKILL.md 说明工具已可实际调用（或在 references/tool-contract.md 标注）。

**依赖 semantic_search**：`search_evidence` 的 `mode=hybrid/semantic` 依赖向量检索先实现（见 `docs/semantic-search.md`）。若语义检索未就绪，`hybrid` 退化为 keyword+metadata（retriever 已有该行为），Agent 仍可工作，只是少一路召回。两个功能可并行开发，agent 循环不阻塞在 semantic 上。

## 13. 与旧 Codex 方案的关系

- `codex_agent/` 代码保留；`/rag/agent/check` 迁移为模型配置检查，不再检查 Codex 连通性。
- 若日后需要"代码执行型" agent（跑数据分析、写文件），再启用 Codex，两者不冲突：本方案是"读取推理型" agent 的执行层。
- `pyproject.toml` 的 `openai-codex` 依赖：本方案不移除（保留 Codex 能力），但 RAG 主链路不再依赖它，linux-only 限制不再阻塞 RAG 在其他平台运行。若确定短期不用 Codex，可考虑将其降级为可选依赖。

## 14. 一期明确做/不做

- 做：`list_scope_documents`，默认 50、最大 100，只返回精简题录信息。
- 做：历史裁剪为最近 10 轮 user + assistant final answer，且不持久化 raw tool messages。
- 做：前端最小可见 tool_trace 展示。
- 暂不做：sources 后处理（只保留答案 citation 命中的）；一期返回 accumulator 全集。
