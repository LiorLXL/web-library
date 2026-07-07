# OpenAI Codex Agentic RAG 接入计划

状态：设计计划   
参考项目：`../guangming-ai-workbench`

## 1. 目标

把当前项目的文库内 RAG 能力接到 OpenAI Codex Agent runtime 上，让知识库问答、文献矩阵和综述写作可以由智能体组织回答，但证据检索仍由本项目后端受控执行。

核心目标：

- 复用当前已实现的 `rag.sqlite`、知识库作用域、MinerU Markdown 索引和 FTS5 检索。
- 迁移 `guangming-ai-workbench` 中成熟的 Codex runtime 调用模式。
- 用仓库内 `skills/agentic-rag/SKILL.md` 约束智能体行为。
- 先实现最小闭环，不一次性迁移完整模型配置系统和 Moon Bridge。

## 2. 从 guangming-ai-workbench 得到的结论

`guangming-ai-workbench` 并不是直接用 shell 调用 `codex` 命令，而是通过 Python 包 `openai-codex` 使用 Codex Agent runtime。

可复用模式：

- `CodexConfig`：设置 `cwd`、`CODEX_HOME`、模型 provider、base URL、reasoning effort。
- `Codex(...)`：启动 runtime。
- `codex.login_api_key(...)`：用当前配置登录。
- `thread_start(...)` / `thread_resume(...)`：创建或恢复 agent thread。
- `TextInput(...)`：传入任务 prompt。
- `SkillInput(name=..., path=...)`：显式注入仓库内 skill。
- stream 事件收集：保存 final answer、usage、diagnostics、错误信息。

暂不迁移：

- 完整 `model_profiles.py`。
- Moon Bridge 本地路由。
- 另一个模型设置页面。
- 深度外部学术检索 skill。

原因：

- `web-library` 已经有按 library 保存的 Codex API 配置。
- 当前任务是文库内 RAG，不是外部论文检索。
- 第一阶段需要稳定跑通 Agentic RAG 闭环，而不是先引入第二套模型配置体系。

## 3. 目标架构

```text
knowledge.html / reader.html / matrix / writing
        ↓
Flask API
        ↓
rag/retriever.py
  ├─ metadata_search
  ├─ keyword_search
  ├─ semantic_search  后续
  └─ chunk_read
        ↓
Evidence Pack
        ↓
codex_agent/runner.py
        ↓
OpenAI Codex Agent runtime
  ├─ SkillInput("agentic-rag", "skills/agentic-rag/SKILL.md")
  └─ TextInput(prompt + Evidence Pack)
        ↓
answer + sources + diagnostics
```

关键原则：

- Agent 不直接读取 `zotero.sqlite`。
- Agent 不直接扫描本地附件目录。
- Agent 不直接决定越过知识库作用域。
- 后端先生成 Evidence Pack，再交给 Agent 归纳和写作。

## 4. Skill 设计

计划新增：

```text
skills/
  agentic-rag/
    SKILL.md
    references/
      tool-contract.md
      retrieval-policy.md
      citation-format.md
```

### 4.1 SKILL.md 职责

`SKILL.md` 负责告诉智能体：

- 当前任务是文库内 RAG，不是外部联网检索。
- 回答只能基于 prompt 中提供的 Evidence Pack。
- 证据不足时要明确说明不足，不能编造。
- 必须保留 Evidence Pack 中的 citation 标记。
- 写综述或矩阵时，每个关键结论都要有来源。
- 区分用户笔记、论文原文、元数据和模型归纳。

### 4.2 references/tool-contract.md

定义后端提供给 Agent 的统一工具语义：

- `retrieve`：统一检索入口。
- `metadata_search`：元数据匹配。
- `keyword_search`：SQLite FTS5 全文检索。
- `semantic_search`：后续向量检索。
- `chunk_read`：上下文补读。

注意：这些不是 Codex runtime 直接调用的真实函数，而是后端已经执行过并写进 Evidence Pack 的工具记录。第一阶段不让 Agent 自由发起工具调用。

### 4.3 references/retrieval-policy.md

定义检索和证据使用策略：

- factual 问题优先 metadata + keyword。
- 方法总结优先 keyword + chunk_read。
- 对比问题要尽量覆盖多个 `item_key`。
- 矩阵单元格必须保留单元格级 sources。
- 综述写作必须区分证据、归纳和待确认内容。

### 4.4 references/citation-format.md

定义第一阶段引用格式：

```text
[<item_key>:<chunk_id>]
[<item_key>:metadata]
[<item_key>:note:<note_id>]
```

正式参考文献格式后续由 Zotero citation export 处理；Agent 回答中的 citation 只用于本系统内部追证。

## 5. 统一检索计划

计划新增：

```text
src/zotero_web_library/rag/retriever.py
```

公开函数：

```python
retrieve(
    library_id: str,
    query: str,
    knowledge_base_id: str | None = None,
    item_keys: list[str] | None = None,
    mode: str = "auto",
    top_k: int = 8,
    include_context: bool = True,
) -> dict
```

当前 `auto` 策略：

1. 对 query 做轻量规范化。
2. 调 `metadata_search` 获取相关条目。
3. 调 `keyword_search` 获取正文 chunk。
4. 对高分 chunk 调 `chunk_read` 补上下文。
5. 合并去重，生成 Evidence Pack。

当前检索算法：

- `keyword_search`：SQLite FTS5，使用 `bm25(rag_chunk_fts)` 排序。
- `metadata_search`：结构化字段过滤 + 文本匹配。
- `semantic_search`：暂不启用，返回 `not_configured` 或不参与排序。

## 6. Codex runner 计划

计划新增：

```text
src/zotero_web_library/codex_agent/
  __init__.py
  runner.py
  prompts.py
```

### 6.1 runner.py

职责：

- 从当前 library 的 API 配置中读取 Codex 配置。
- 构造 Codex provider override。
- 设置项目级或文库级 `CODEX_HOME`。
- 调用 `Codex` runtime。
- 注入 `SkillInput("agentic-rag", ".../skills/agentic-rag/SKILL.md")`。
- 收集 final answer、usage、diagnostics。

第一阶段不支持：

- Agent 自由执行 shell 命令。
- Agent 直接写本地文件。
- Moon Bridge。
- 多 provider profile UI。

### 6.2 prompts.py

职责：

- 组装系统任务说明。
- 注入 Evidence Pack。
- 限制输出格式。
- 按任务类型生成问答、矩阵、综述写作 prompt。

## 7. API 计划

### 7.1 连通性检查

```http
POST /api/library/<library_id>/rag/agent/check
```

用途：

- 验证当前 library 的 Codex API 配置是否可用。
- 不读取知识库。
- 只发送最小测试 prompt。

响应：

```json
{
  "ok": true,
  "message": "测试成功",
  "assistant_text": "正常",
  "usage": {},
  "diagnostics": {}
}
```

### 7.2 统一检索调试

```http
POST /api/library/<library_id>/rag/tools/retrieve
```

用途：

- 调试 Evidence Pack。
- 给前端预览检索结果。
- 给测试验证知识库范围约束。

### 7.3 知识库问答

```http
POST /api/library/<library_id>/rag/chat
```

流程：

1. 读取 question、knowledge_base_id、item_keys。
2. 调 `retrieve()` 生成 Evidence Pack。
3. 调 Codex runner，注入 `agentic-rag` skill。
4. 返回 answer、sources、tool_calls、usage、diagnostics。

## 8. 分阶段实施

### Phase A：文档和契约

- [x] 更新 Agentic RAG 主设计文档。
- [x] 更新知识库 schema 文档中的 Evidence Pack 契约。
- [x] 新增本迁移计划。

### Phase B：Skill 骨架

- [ ] 新增 `skills/agentic-rag/SKILL.md`。
- [ ] 新增 `references/tool-contract.md`。
- [ ] 新增 `references/retrieval-policy.md`。
- [ ] 新增 `references/citation-format.md`。

### Phase C：统一检索

- [ ] 新增 `rag/retriever.py`。
- [ ] 新增 `/rag/tools/retrieve`。
- [ ] 为知识库范围、`item_keys` 交集、空结果和 FTS 排序写测试。

### Phase D：Codex runtime

- [x] 新增 `codex_agent/runner.py`。
- [x] 新增 `/rag/agent/check`。
- [x] 用 mock runner 写单元测试，避免 CI 真实请求 OpenAI。
- [ ] 手动本地测试真实 API Key。

### Phase E：知识库问答

- [ ] 新增 `/rag/chat`。
- [ ] 接入 `knowledge.html` 右侧智能体对话。
- [ ] 展示 answer、sources、tool_calls。
- [ ] 保存 conversation/message 记录。

## 9. 风险和边界

- Base URL 需要通过 `/rag/agent/check` 验证。`guangming-ai-workbench` 原生 OpenAI 示例使用根地址，当前项目设置页默认值可能包含 `/v1`，实现时要做兼容或明确提示。
- 第一阶段不要把完整 Zotero 数据库、PDF 原文全量或本机绝对路径发给模型。
- Skill 只能约束 Agent 行为，不能替代后端权限检查；知识库范围必须在后端强制执行。
- 自动测试不应依赖真实 OpenAI 网络请求。
- 如果后续需要非 OpenAI Chat API provider，再评估迁移 Moon Bridge 和完整 model profile 系统。
