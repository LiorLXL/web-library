# Agentic RAG 设计文档

状态：设计 v1.2  
最后更新：2026-07-06  
适用项目：Zotero Web Library + MinerU PDF 解析 + 多源异构检索

## 1. 与当前项目的对齐结论

### 1.1 旧版设计的问题

旧版 v1.0 的方向正确，但和当前项目状态有几处不匹配：

1. **把 PDF 解析当作待实现能力**  
   当前代码已经接入 MinerU API，并提供 `POST /api/library/<library_id>/items/parse-pdfs`。解析结果会保存到当前文库目录的 `mineru-results/`，所以 Agentic RAG 的第一步应该是复用已有 MinerU Markdown/JSON/图片结果，而不是重新实现 PDF 解析。

2. **过早把 ChromaDB 和 sentence-transformers 作为 MVP 依赖**  
   当前 `pyproject.toml` 依赖很克制，已有可跑通功能主要基于 Flask、SQLite、OpenAI SDK 和现有 Python 标准库。MVP 应优先用 SQLite + FTS5 跑通索引、关键词检索、chunk 读取和问答证据链；向量检索作为第二阶段可选增强。

3. **没有区分外部多源检索和文库内 RAG**  
   现有 `retrieval/` 模块负责“从外部源搜索候选文献并导入 Zotero”。Agentic RAG 应负责“对已经进入当前文库的 Zotero 元数据、MinerU 解析结果、HTML、笔记和写作材料做证据检索与写作辅助”。二者可协同，但不能混成同一层。

4. **数据存储位置不够清晰**  
   旧稿把大量 RAG 表写入 `app.sqlite`。更合适的做法是：`app.sqlite` 继续保存文库记录、偏好和全局配置；每个文库自己的 RAG 索引放在文库目录下，例如 `app-data/libraries/<library_id>/rag.sqlite`，避免污染 Zotero 原生库，也便于按文库删除和重建。

5. **工具层过窄**  
   旧稿只有 `keyword_search`、`semantic_search`、`chunk_read`。用户规划中的 A-RAG 需要覆盖元数据、全文、chunk、图表、HTML、引用、笔记和写作材料，因此工具层需要扩展为 8 类。

6. **前端入口没有对齐现有规划**  
   当前 `knowledge.html` 已经有知识库列表、文献矩阵和右侧智能体对话骨架；`reader.html` 也已有 PDF 研读入口。设计应复用这些页面，而不是另起一套孤立的 RAG UI。

## 2. 功能定位

Agentic RAG 是文库内知识工作台，不是外部文献搜索器。

```text
外部多源检索 retrieval/
  用途：找文献、去重、导入 Zotero
  输入：query / DOI / arXiv / PubMed / GitHub / HuggingFace 等外部源
  输出：ImportedItem + Zotero 条目

Agentic RAG rag/
  用途：读已入库材料、追证、问答、生成矩阵、辅助综述写作
  输入：Zotero metadata / MinerU markdown / HTML / notes / writing materials
  输出：带来源证据的回答、矩阵单元格、写作草稿和引用依据
```

一句话目标：

> 让上层研读、知识库问答、文献矩阵和综述写作 Agent，都能通过统一工具层访问当前文库中的多源异构知识，并且每个结论都能回到 Zotero 条目、chunk、页码、图表或笔记来源。

## 3. 上层应用流程

```text
上层应用
  ├─ 研读界面
  │    └─ 基于当前 PDF、当前条目、当前选区继续提问
  ├─ 知识库问答
  │    └─ 面向一个或多个知识库做证据问答
  ├─ 文献矩阵生成
  │    └─ 按用户定义字段逐篇抽取结构化结论
  └─ 综述写作 Agent
       └─ 基于知识库、矩阵、笔记和项目材料生成大纲/段落/引用依据
        ↓
A-RAG Agent Controller
        ↓
知识库工具层
  ├─ metadata_search
  ├─ keyword_search
  ├─ semantic_search
  ├─ chunk_read
  ├─ figure_read
  ├─ html_read
  ├─ citation_search
  └─ note_search
        ↓
多源异构知识库
  ├─ Zotero metadata
  ├─ PDF parsed markdown / JSON from MinerU
  ├─ PDF page images / figures / screenshots
  ├─ HTML documents
  ├─ user notes
  └─ writing project materials
```

## 4. 当前可复用基础

### 4.1 已有后端能力

- `src/zotero_web_library/web.py`
  - MinerU API 配置、调用、结果下载与保存。
  - `POST /api/library/<library_id>/items/parse-pdfs` 批量解析已勾选 PDF。
  - `GET/POST /api/library/<library_id>/api-config` 保存模型、代码源和 MinerU 配置。
- `src/zotero_web_library/zotero_adapter.py`
  - 读取 Zotero 主条目、字段、作者、标签、附件、笔记。
  - 读取 PDF 附件路径。
  - 读取和写入 PDF 标注。
- `src/zotero_web_library/retrieval/`
  - 外部多源检索、候选导入、检索计划和 AI 候选评分。
  - 这部分可为综述写作补充新文献，但不是 RAG 内部索引层。
- `src/zotero_web_library/templates/knowledge.html`
  - 已有知识库列表、文献矩阵和智能体对话三栏骨架。
- `src/zotero_web_library/templates/reader.html`
  - 已有单篇 PDF 研读入口，可在后续接入“当前条目上下文问答”。

### 4.2 已有 MinerU 结果结构

当前 MinerU 解析结果由 `write_mineru_parse_result()` 写入：

```text
app-data/libraries/<library_id>/mineru-results/
  {timestamp}-{attachment_key}.json
  {timestamp}-{attachment_key}.md
  {timestamp}-{attachment_key}/
    downloaded-*.md
    image-*.png
    extracted files from zip...
```

JSON 包装中已经包含：

- `library_id`
- `item_key`
- `attachment`
- `parsed_at`
- `mineru.base_url`
- `result`

RAG 索引器应优先读取这些结果，并通过 `item_key`、`attachment.key` 关联 Zotero 主条目和附件。

## 5. 目标架构

```text
src/zotero_web_library/rag/
  __init__.py
  models.py          # RAG 数据模型：Document、Chunk、ToolResult、CitationSource
  store.py           # rag.sqlite 初始化、迁移、读写
  ingest.py          # 扫描 Zotero + MinerU + HTML + notes + writing materials
  chunking.py        # Markdown/HTML/notes 分块策略
  tools.py           # metadata_search / keyword_search / chunk_read 等工具
  retriever.py       # 统一检索入口：metadata + keyword + semantic 的混合编排
  agent.py           # A-RAG Agent Controller
  citations.py       # 来源证据格式化

src/zotero_web_library/codex_agent/
  __init__.py
  runner.py          # OpenAI Codex Agent runtime 封装
  prompts.py         # Agentic RAG prompt / Evidence Pack prompt

skills/
  agentic-rag/
    SKILL.md         # 告诉智能体如何基于文库内证据回答
    references/
      tool-contract.md
      retrieval-policy.md
      citation-format.md
```

文库目录建议：

```text
app-data/libraries/<library_id>/
  zotero.sqlite
  storage/
  mineru-results/
  rag.sqlite
  rag-assets/
```

原则：

- 不修改 Zotero 原生 schema。
- 不把 RAG chunk 写进 Zotero `extra`、`tags` 或 `itemData`。
- `rag.sqlite` 只保存派生索引，可随时删除重建。
- RAG 索引记录 `source_hash` 和 `indexed_at`，支持增量更新。
- 每个 Agent 回答必须带来源证据；无法追证时明确标记“未找到依据”。

## 6. 工具层设计

### 6.1 metadata_search

用途：在 Zotero 元数据中搜索。

来源：

- 标题
- 作者
- 年份
- 期刊/会议
- 摘要
- DOI / arXiv / ISBN / PMID 等标识符
- 标签、阅读状态、评分、期刊等级

适合问题：

- “ReKep 是哪一年发表的？”
- “有哪些 VLA 相关论文？”
- “我标为 #必读 的论文有哪些？”

### 6.2 keyword_search

用途：在已索引 chunk 中做 SQLite FTS5 全文检索。

来源：

- MinerU Markdown chunk
- HTML chunk
- notes chunk
- writing project materials chunk

适合问题：

- “哪些论文提到了 action chunking？”
- “找出包含 ablation study 的段落。”

### 6.3 semantic_search

用途：向量语义检索。MVP 可先保留接口，第二阶段接 embedding provider。

优先级：

- 第一阶段：接口和返回格式先定，未配置 embedding 时返回 `not_configured`。
- 第二阶段：接页面级 embedding 配置或本地模型。

### 6.4 chunk_read

用途：读取指定 chunk、同一章节或上下文窗口。

关键能力：

- 按 `chunk_id` 读取。
- 按 `item_key` + `section_title` 读取。
- 按 `chunk_index ± window_size` 读取。
- 返回 Zotero 条目标题、附件 key、页码估计、章节标题和原文。

### 6.5 figure_read

用途：读取图、表、公式、截图等视觉资产的索引信息。

MVP 不做视觉理解，只返回：

- 图片路径
- 图注或相邻文本
- 来源 chunk
- item_key / attachment_key
- estimated_page

后续可接多模态模型或 OCR。

### 6.6 html_read

用途：读取 HTML 附件的正文结构。

MVP 可用简单文本抽取：

- 去掉 script/style/nav。
- 保留标题、段落、列表、表格文本。
- 记录简化 DOM 路径或标题层级。

### 6.7 citation_search

用途：追踪文内引用、参考文献和本地条目之间的关系。

MVP 做本地引用文本索引：

- 识别 MinerU Markdown 中的 References / Bibliography 段。
- 保存参考文献原文。
- 尝试按 DOI、标题、年份匹配当前 Zotero 文库已有条目。

第二阶段再接 Semantic Scholar / OpenAlex 等外部 citation API。

### 6.8 note_search

用途：检索 Zotero notes 和写作项目材料。

来源：

- Zotero `itemNotes`
- PDF 标注 comment / text
- 用户保存的阅读笔记
- 综述写作项目中的大纲、草稿、CSV/Markdown 辅助材料

## 7. Agent Controller

第一阶段采用“后端统一检索 + OpenAI Codex Agent runtime 生成回答”的方式。Agent 不直接自由访问 Zotero SQLite 或本机文件系统，而是由后端先执行受控检索，生成 Evidence Pack，再把 Evidence Pack 和 `agentic-rag` skill 一起交给智能体。

### 7.1 OpenAI Codex Agent runtime 接入边界

同级项目 `guangming-ai-workbench` 的实现不是直接 shell 调用 `codex` 命令，而是通过 Python 包 `openai-codex` 使用 Codex Agent runtime。可迁移的核心模式是：

- 用 `CodexConfig` 指定 `cwd`、`CODEX_HOME` 和模型 provider 覆盖项。
- 用 `codex.login_api_key()` 注入当前配置的 API Key。
- 用 `thread_start()` / `thread_resume()` 管理一次或多次 Agent 对话。
- 用 `TextInput` 传入任务 prompt。
- 用 `SkillInput(name="...", path=".../SKILL.md")` 显式注入仓库内 skill。
- 收集 turn stream，保存 final answer、token usage、诊断信息和错误信息。

本项目第一阶段只迁移最小 runner，不迁移 `guangming-ai-workbench` 的完整 `model_profiles + Moon Bridge + 设置页`。原因是 `web-library` 已经有按文库保存的 Codex API 配置，先复用现有配置可以避免两套模型配置并存。

建议新增：

```text
POST /api/library/<library_id>/rag/agent/check
POST /api/library/<library_id>/rag/chat
```

其中 `/rag/agent/check` 只做最小连通性测试；`/rag/chat` 先走后端检索，再调用 Codex Agent 生成带引用回答。

### 7.2 Skill 的职责

`skills/agentic-rag/SKILL.md` 不直接实现检索，也不保存知识库数据。它和三个 references 共同告诉智能体：

- 只能基于当前受控 scope 内的工具结果或 Evidence Pack 回答。
- 证据不足时必须说明“不足以回答”，不能编造论文、页码、实验结论或引用。
- 回答中必须保留来源标记，来源标记来自 Evidence Pack。
- 区分“原文证据”“模型归纳”“用户笔记”。
- 做矩阵或综述时，必须让每个结论可回溯到 chunk、note、metadata 或 figure。

真正执行检索和 scope 强制的是后端 `rag/retriever.py` 和 `rag/tools.py`。Skill 是智能体行为契约，不是数据库查询层。Phase 1.5 起，Function Calling Agent 会把主 Skill 与 references 直接注入 system prompt；Codex SDK 的 `SkillInput` 与它复用同一个路径解析函数。

### 7.3 统一检索入口

Agent 不直接选择底层 `metadata_search`、`keyword_search` 或 `semantic_search`。后端提供统一入口：

```python
retrieve(
    query,
    knowledge_base_id=None,
    item_keys=None,
    mode="auto",  # auto / metadata / keyword / semantic / hybrid
    top_k=8,
)
```

MVP 的 `auto` 等同于轻量 hybrid：

1. `metadata_search` 找标题、作者、年份、DOI、标签等结构化线索。
2. `keyword_search` 用 SQLite FTS5 找正文 chunk。
3. 对高分 chunk 执行 `chunk_read` 补上下文窗口。
4. 合并去重，按来源类型、分数和知识库范围生成 Evidence Pack。

当前检索算法以 SQLite FTS5 为主，排序使用 FTS5 `bm25()`；metadata 检索属于结构化过滤和文本匹配；semantic_search 先保留接口，后续接 embedding provider。

### 7.4 规则驱动阶段保留

在 Codex runtime 接入前后，后端仍保留规则驱动 tool plan，用于控制不同任务的检索范围和证据类型：

```python
TASK_RULES = {
    "factual": ["metadata_search", "keyword_search", "chunk_read"],
    "analytical": ["keyword_search", "chunk_read", "note_search"],
    "comparative": ["metadata_search", "keyword_search", "chunk_read"],
    "matrix": ["metadata_search", "keyword_search", "chunk_read", "note_search"],
    "writing": ["metadata_search", "keyword_search", "chunk_read", "citation_search", "note_search"],
}
```

典型流程：

```text
用户问题
  -> 任务分类
  -> 生成工具计划
  -> 执行工具
  -> 合并证据
  -> 判断是否需要补读 chunk
  -> 生成答案 / 矩阵单元格 / 写作片段
  -> 保存 tool_calls 和 sources
```

后续再引入 LLM planner：

- 动态选择工具。
- 多轮迭代检索。
- 自我检查“答案是否有足够来源”。
- 对不确定结论主动补查。

## 8. API 设计

### 8.1 索引

```http
POST /api/library/<library_id>/rag/index
GET  /api/library/<library_id>/rag/index/status
POST /api/library/<library_id>/rag/index/mineru
```

说明：

- `/rag/index`：全量或增量索引当前文库。
- `/rag/index/mineru`：只扫描已有 `mineru-results/`，不重新调用 MinerU API。

### 8.2 知识库管理

```http
GET    /api/library/<library_id>/rag/knowledge-bases
POST   /api/library/<library_id>/rag/knowledge-bases
GET    /api/library/<library_id>/rag/knowledge-bases/<knowledge_base_id>
POST   /api/library/<library_id>/rag/knowledge-bases/<knowledge_base_id>/items
DELETE /api/library/<library_id>/rag/knowledge-bases/<knowledge_base_id>/items
```

MVP 中，知识库是对 Zotero/RAG `item_key` 的应用侧作用域，不复制 Zotero 条目，也不修改 Zotero schema。`metadata_search` 和 `keyword_search` 接收 `knowledge_base_id` 后只在该知识库条目集合内检索；如果同时传 `item_keys`，后端使用“知识库集合 ∩ item_keys”，避免越界检索。

### 8.3 工具

```http
POST /api/library/<library_id>/rag/tools/retrieve
POST /api/library/<library_id>/rag/tools/metadata_search
POST /api/library/<library_id>/rag/tools/keyword_search
POST /api/library/<library_id>/rag/tools/semantic_search
POST /api/library/<library_id>/rag/tools/chunk_read
POST /api/library/<library_id>/rag/tools/figure_read
POST /api/library/<library_id>/rag/tools/html_read
POST /api/library/<library_id>/rag/tools/citation_search
POST /api/library/<library_id>/rag/tools/note_search
```

`retrieve` 是 Agent 优先使用的统一检索入口；其他工具 API 主要用于调试、测试和后端内部编排。前端普通用户优先走 chat/matrix/writing API。

### 8.4 知识库问答

```http
POST /api/library/<library_id>/rag/chat
Body: {
  "question": "Diffusion-VLA 的核心方法是什么？",
  "conversation_id": "conv-123",
  "scope": {
    "knowledge_base_id": "kb-core",
    "item_keys": ["ABCD1234"]
  }
}
```

响应：

```json
{
  "ok": true,
  "answer": "...",
  "sources": [
    {
      "item_key": "ABCD1234",
      "chunk_id": "chunk-...",
      "title": "Paper title",
      "section_title": "Method",
      "estimated_page": 4,
      "excerpt": "..."
    }
  ],
  "tool_calls": []
}
```

### 8.5 文献矩阵

```http
POST /api/library/<library_id>/rag/matrix
Body: {
  "item_keys": ["A", "B", "C"],
  "fields": [
    {"name": "研究问题", "instruction": "提取论文要解决的问题"},
    {"name": "方法思路", "instruction": "总结核心方法"}
  ]
}
```

矩阵生成必须保存单元格来源：

- 每个 cell 的 answer。
- 支持该 answer 的 chunk sources。
- Agent 使用过的 tool calls。
- 失败或证据不足时的状态。

### 8.6 综述写作项目

```http
POST /api/library/<library_id>/rag/writing-projects
POST /api/library/<library_id>/rag/writing-projects/<project_id>/outline
POST /api/library/<library_id>/rag/writing-projects/<project_id>/draft
```

第一阶段只设计接口和数据结构；实现可放在矩阵稳定之后。

## 9. 实施计划

### Phase 1：MinerU 结果复用型索引 MVP

- [x] 新增 `rag/` 模块。
- [x] 新增文库侧 `rag.sqlite` 初始化逻辑。
- [x] 扫描 Zotero metadata、notes 和已有 `mineru-results/`。
- [x] 实现 Markdown/notes 基础分块。
- [x] 创建 FTS5 全文索引。
- [x] 实现 `metadata_search`、`keyword_search`、`chunk_read`。
- [x] 提供索引状态 API。
- [ ] 扫描 HTML 附件并实现 HTML 基础分块。
- [ ] 实现独立 `note_search` 工具 API。

### Phase 2：知识库问答

- [x] 创建知识库 CRUD API。
- [x] 支持 `metadata_search` / `keyword_search` 按 `knowledge_base_id` 限定范围。
- [x] 文库页批量“导入知识库”接入真实 API。
- [x] `knowledge.html` 接入真实知识库列表、条目状态和 scoped keyword_search 预览。
- [x] 新增 `skills/agentic-rag/SKILL.md`、引用规范和 Function Calling 注入。
- [x] 新增 `rag/retriever.py` 统一检索入口。
- [x] 新增 `codex_agent/runner.py`，迁移 OpenAI Codex Agent runtime 最小封装。
- [x] 实现 `/rag/agent/check`。
- [x] 实现 `/rag/chat`。
- [x] 接入 `knowledge.html` 右侧智能体对话。
- [x] 展示来源、chunk 摘录和工具调用过程。

### Phase 3：文献矩阵

- [ ] 设计知识库、矩阵字段和矩阵运行记录。
- [ ] 接入 `knowledge.html` 中间文献矩阵区。
- [ ] 支持用户定义字段、逐篇抽取、单元格重跑。
- [ ] 单元格保存 sources_json 和 tool_calls_json。

### Phase 4：语义检索

- [ ] 定义 embedding provider 抽象。
- [ ] 支持页面级 embedding 配置。
- [ ] 实现 `semantic_search`。
- [ ] 实现 keyword + semantic 混合排序。

### Phase 5：图表、引用和写作 Agent

- [ ] `figure_read` 读取 MinerU 图片、图注和相邻 chunk。
- [ ] `citation_search` 解析 References 并做本地条目匹配。
- [ ] 写作项目支持大纲、草稿、引用证据和项目材料。

## 10. 验收标准

MVP 完成时至少满足：

- 不重新调用 MinerU，也能把已有 `mineru-results/` 索引进 RAG。
- 不修改 Zotero 原生 schema。
- 删除 `rag.sqlite` 后可以重建索引。
- `keyword_search` 可以搜到 MinerU Markdown 中的正文。
- `chunk_read` 可以返回上下文窗口和来源条目。
- 知识库问答返回答案时带 sources。
- 文献矩阵的每个单元格能追溯到 chunk 或 note。

## 11. 安全与隐私

- 默认本地存储，索引数据放在当前文库目录。
- LLM 请求只发送必要 chunk 和元数据，不发送完整 Zotero SQLite、API key 或本地绝对路径。
- 前端展示来源时可显示条目标题、章节、页码和摘录；避免暴露本机敏感路径。
- 只读连接模式允许建立派生索引，但不写 Zotero 源库。
- 本地副本模式仍只写应用复制出的文库，不直接修改用户真实 Zotero 源库。

## 12. 和现有文档的关系

- `docs/data-mapping.md`：约束 Zotero 原生字段、附件、笔记和标注来源。
- `docs/multi-source-retrieval-design.md`：约束外部多源检索和候选导入。
- `docs/rag-knowledge-base-schema.md`：约束 RAG 派生索引表结构。
- `docs/openai-codex-agentic-rag-plan.md`：约束 OpenAI Codex Agent runtime、仓库内 skill 和统一检索的迁移计划。
- `docs/agentic-rag-optimization-roadmap.md`：作为后续质量优化、Agency 演进和阶段验收的主执行路线。
- `docs/retrieval-deployment.md`：继续负责外部检索源部署，不承担 RAG 索引部署。
