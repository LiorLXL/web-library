# Agentic RAG 知识库数据结构设计

版本：v1.4
日期：2026-07-18
基于：Zotero metadata、MinerU 解析结果、HTML 附件、Zotero notes、写作项目材料

---

## 一、修订结论

旧版 v1.0 的 schema 方向基本正确，但需要按当前项目实际情况调整：

1. **PDF 解析不是 RAG schema 的职责**  
   当前项目已经通过 MinerU API 完成 PDF 解析，RAG 索引只负责读取 `mineru-results/` 中的 JSON、Markdown 和图片资产。

2. **不要在 RAG 表里声明 Zotero `items(key)` 外键**  
   RAG 索引建议放在文库目录的独立 `rag.sqlite`。它和 `zotero.sqlite` 是两个 SQLite 文件，不能直接用普通外键引用 Zotero 表。`item_key`、`attachment_key` 作为逻辑关联字段即可。

3. **MVP 不强依赖 ChromaDB**  
   ChromaDB 可作为第二阶段向量存储。第一阶段应优先保证 SQLite + FTS5 可用，降低部署和测试成本。

4. **需要覆盖知识库、矩阵和写作项目**  
   旧版只覆盖文档、chunk、图片、对话。当前界面规划还需要知识库列表、文献矩阵字段、矩阵运行结果和写作项目材料。

5. **需要显式记录来源和可重建信息**  
   所有 chunk、图片、笔记和矩阵单元格都必须记录来源路径、source_hash、item_key、attachment_key、section/page 等信息，保证可以增量更新和追证。

6. **索引数据和运行时数据必须分开管理**
   当前实现继续把两类数据放在同一个文库级 `rag.sqlite` 中，但普通索引刷新只允许重建 `rag_documents`、`rag_chunks`、FTS、Embedding 等派生索引，不能删除 `rag_chat_*`、`rag_agent_*`、矩阵或写作运行记录。显式删除整个 `rag.sqlite` 会同时丢失索引和运行时历史，不再属于普通“重建索引”操作。

---

## 二、存储布局

每个文库的 RAG 索引独立存放：

```text
app-data/libraries/<library_id>/
  zotero.sqlite              # Zotero 原生副本，不修改 schema
  storage/                   # Zotero 附件
  mineru-results/            # MinerU API 解析结果
  rag.sqlite                 # RAG 派生索引 + 知识库/对话/Agent 运行时记录
  rag-assets/                # 可选：后续缓存、导出、写作项目材料
```

`app-data/app.sqlite` 继续保存：

- 文库记录。
- API 配置。
- 检索源偏好。
- UI 偏好。

`rag.sqlite` 当前保存两类数据：

派生索引数据，可由 Zotero、MinerU 和附件重新生成：

- RAG 文档索引。
- chunk 和 FTS5。
- 图表/图片资产。
- 笔记索引。
- Embedding。

运行时与用户工作数据，不参与普通索引重建：

- 知识库定义。
- 文献矩阵。
- 对话、AgentRun、状态事件和工具调用证据。
- 写作项目材料。

长期如需支持“删除全部派生索引但绝不影响用户历史”，可再拆出 `rag-runtime.sqlite`；Phase 2 先通过清晰的表级重建边界保证安全，不提前引入第二个数据库。

---

## 三、数据源

| 数据类型 | 来源 | 当前存储位置 | RAG 处理 |
| --- | --- | --- | --- |
| Zotero 元数据 | `zotero.sqlite` | `items` / `itemData` / `creators` / `tags` | 生成 metadata document 和 metadata_search 索引 |
| PDF 解析 Markdown | MinerU | `mineru-results/*.md` 或解压出的 `*.md` | Markdown 结构分块 |
| PDF 解析 JSON | MinerU | `mineru-results/*.json` | 读取 `item_key`、`attachment`、`parsed_at`、结果路径 |
| PDF 图片/截图 | MinerU | `mineru-results/<stem>/.../*.png|jpg` | 建立 `rag_assets`，供 figure_read |
| HTML 附件 | Zotero attachment | `storage/<attachment_key>/*.html` 或 URL 附件 | HTML 正文分块 |
| Zotero notes | `itemNotes` | `zotero.sqlite` | note_search 索引 |
| PDF 标注 | `itemAnnotations` | `zotero.sqlite` | 后续作为 note/annotation chunk |
| 写作项目材料 | 应用侧 | `rag-assets/writing-projects/` 或 `rag.sqlite` | 进入 note_search / writing Agent |

---

## 四、Schema 总览

```text
rag_config
rag_index_jobs
rag_index_job_items

rag_documents
rag_chunks
rag_chunk_fts
rag_assets
rag_notes
rag_citations

rag_knowledge_bases
rag_knowledge_base_items

rag_matrix_fields
rag_matrix_runs
rag_matrix_cells

rag_chat_sessions
rag_chat_messages
rag_agent_runs
rag_agent_events

rag_writing_projects
rag_writing_materials
rag_writing_outputs
```

---

## 五、配置与索引任务

### 5.1 rag_config

```sql
CREATE TABLE IF NOT EXISTS rag_config (
    library_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 4,

    chunk_strategy TEXT NOT NULL DEFAULT 'structured_markdown_parent_child',
    chunk_content_version TEXT NOT NULL DEFAULT 'structured-parent-v1',
    chunk_size INTEGER NOT NULL DEFAULT 900,
    chunk_overlap INTEGER NOT NULL DEFAULT 120,

    embedding_enabled INTEGER NOT NULL DEFAULT 0,
    embedding_provider TEXT NOT NULL DEFAULT '',
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_dim INTEGER,
    vector_store_type TEXT NOT NULL DEFAULT 'none',
    vector_store_path TEXT NOT NULL DEFAULT '',

    index_status TEXT NOT NULL DEFAULT 'pending',
    total_items INTEGER NOT NULL DEFAULT 0,
    indexed_items INTEGER NOT NULL DEFAULT 0,
    total_documents INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    total_assets INTEGER NOT NULL DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_indexed_at TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}'
);
```

说明：

- `embedding_enabled=0` 是 MVP 默认值。
- `vector_store_type='none'` 表示只启用 SQLite FTS5。
- 后续可设置为 `sqlite_blob`、`chromadb`、`faiss` 等。

### 5.2 rag_index_jobs

```sql
CREATE TABLE IF NOT EXISTS rag_index_jobs (
    job_id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'incremental',
    target_items_json TEXT NOT NULL DEFAULT '[]',
    target_sources_json TEXT NOT NULL DEFAULT '[]',

    status TEXT NOT NULL DEFAULT 'queued',
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    documents_created INTEGER NOT NULL DEFAULT 0,
    chunks_created INTEGER NOT NULL DEFAULT 0,
    assets_created INTEGER NOT NULL DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_jobs_status ON rag_index_jobs(status);
CREATE INDEX IF NOT EXISTS idx_rag_jobs_created ON rag_index_jobs(created_at);
```

### 5.3 rag_index_job_items

```sql
CREATE TABLE IF NOT EXISTS rag_index_job_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    attachment_key TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    doc_id TEXT NOT NULL DEFAULT '',
    chunks_created INTEGER NOT NULL DEFAULT 0,
    assets_created INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    processed_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_job_items_job ON rag_index_job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_rag_job_items_item ON rag_index_job_items(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_job_items_status ON rag_index_job_items(status);
```

---

## 六、文档与 chunk

### 6.1 rag_documents

```sql
CREATE TABLE IF NOT EXISTS rag_documents (
    doc_id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    attachment_key TEXT NOT NULL DEFAULT '',

    source_type TEXT NOT NULL,
    -- zotero_metadata / mineru_markdown / mineru_json / html / markdown / note / annotation / writing_material

    source_path TEXT NOT NULL DEFAULT '',
    source_relpath TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL DEFAULT '',
    source_mtime TEXT NOT NULL DEFAULT '',

    title TEXT NOT NULL DEFAULT '',
    item_type TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '',
    creators_text TEXT NOT NULL DEFAULT '',
    tags_text TEXT NOT NULL DEFAULT '',

    mineru_json_path TEXT NOT NULL DEFAULT '',
    mineru_markdown_path TEXT NOT NULL DEFAULT '',
    mineru_assets_dir TEXT NOT NULL DEFAULT '',
    parsed_at TEXT NOT NULL DEFAULT '',

    structure_json TEXT NOT NULL DEFAULT '{}',
    stats_json TEXT NOT NULL DEFAULT '{}',

    total_chunks INTEGER NOT NULL DEFAULT 0,
    total_assets INTEGER NOT NULL DEFAULT 0,
    total_chars INTEGER NOT NULL DEFAULT 0,

    index_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    indexed_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_docs_item ON rag_documents(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_docs_attachment ON rag_documents(attachment_key);
CREATE INDEX IF NOT EXISTS idx_rag_docs_source_type ON rag_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_rag_docs_hash ON rag_documents(source_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_docs_unique_source
ON rag_documents(item_key, attachment_key, source_type, source_hash);
```

设计说明：

- `source_hash` 用于判断 MinerU Markdown、HTML 或 note 是否变化。
- `source_relpath` 用于前端展示或迁移，避免把绝对路径暴露给模型。
- `mineru_json_path` 和 `mineru_markdown_path` 用于追溯解析来源。

### 6.2 rag_chunks

```sql
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    attachment_key TEXT NOT NULL DEFAULT '',

    chunk_index INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,
    -- metadata / title / abstract / heading / paragraph / list / table / figure_caption / equation / reference / note / annotation / writing

    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',

    section_title TEXT NOT NULL DEFAULT '',
    section_path TEXT NOT NULL DEFAULT '',
    section_level INTEGER NOT NULL DEFAULT 0,
    estimated_page INTEGER,
    position_json TEXT NOT NULL DEFAULT '{}',

    token_count INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,

    has_assets INTEGER NOT NULL DEFAULT 0,
    has_tables INTEGER NOT NULL DEFAULT 0,
    has_equations INTEGER NOT NULL DEFAULT 0,
    has_code INTEGER NOT NULL DEFAULT 0,

    embedding_status TEXT NOT NULL DEFAULT 'not_configured',
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_hash TEXT NOT NULL DEFAULT '',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_item ON rag_chunks(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_attachment ON rag_chunks(attachment_key);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_type ON rag_chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_section ON rag_chunks(section_title);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_hash ON rag_chunks(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_chunks_unique_index
ON rag_chunks(doc_id, chunk_index);
```

说明：

- `estimated_page` 来自 MinerU JSON、Markdown 页面标记或后续启发式估计。
- `position_json` 可保存 page、bbox、HTML 路径、Markdown heading path 等。
- `embedding_status` 可为 `not_configured`、`pending`、`embedded`、`failed`。

### 6.3 rag_chunk_fts

MVP 使用独立 FTS5 表，不使用外部 content 表，避免 rowid 同步复杂度。

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunk_fts USING fts5(
    chunk_id UNINDEXED,
    doc_id UNINDEXED,
    item_key UNINDEXED,
    attachment_key UNINDEXED,
    chunk_type UNINDEXED,
    title,
    section_title,
    content,
    tokenize = 'unicode61'
);
```

同步策略由应用代码在写入 chunk 时同时维护：

```sql
INSERT INTO rag_chunk_fts
  (chunk_id, doc_id, item_key, attachment_key, chunk_type, title, section_title, content)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);
```

删除文档或重建索引时：

```sql
DELETE FROM rag_chunk_fts WHERE doc_id = ?;
DELETE FROM rag_chunks WHERE doc_id = ?;
```

普通“刷新文档索引”会在删除并重插 chunk 的短暂窗口内保留 `rag_embeddings`，新 chunk 写入时用稳定 `chunk_id + provider + model + content_hash + content_version` 恢复完全匹配的向量。索引完成后只删除已没有对应 chunk 的孤儿 embedding。显式清空派生索引时才直接删除相关向量。

---

## 七、图片、图表和引用

### 7.1 rag_assets

```sql
CREATE TABLE IF NOT EXISTS rag_assets (
    asset_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL DEFAULT '',
    library_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    attachment_key TEXT NOT NULL DEFAULT '',

    asset_type TEXT NOT NULL,
    -- image / figure / table_image / equation_image / screenshot / html_image

    source_path TEXT NOT NULL,
    source_relpath TEXT NOT NULL DEFAULT '',
    source_hash TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,

    caption TEXT NOT NULL DEFAULT '',
    alt_text TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    position_json TEXT NOT NULL DEFAULT '{}',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_assets_doc ON rag_assets(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_assets_chunk ON rag_assets(chunk_id);
CREATE INDEX IF NOT EXISTS idx_rag_assets_item ON rag_assets(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_assets_type ON rag_assets(asset_type);
```

MVP 的 `figure_read` 只读取本表，不调用视觉模型。

### 7.2 rag_citations

```sql
CREATE TABLE IF NOT EXISTS rag_citations (
    citation_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL DEFAULT '',
    library_id TEXT NOT NULL,
    item_key TEXT NOT NULL,

    raw_text TEXT NOT NULL,
    normalized_title TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    arxiv_id TEXT NOT NULL DEFAULT '',
    matched_item_key TEXT NOT NULL DEFAULT '',
    match_confidence REAL NOT NULL DEFAULT 0,
    match_reason TEXT NOT NULL DEFAULT '',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_citations_doc ON rag_citations(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_citations_item ON rag_citations(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_citations_matched ON rag_citations(matched_item_key);
```

MVP 只解析本地 References 段落；外部被引/共引关系以后再接外部 provider。

---

## 八、笔记和写作材料

### 8.1 rag_notes

```sql
CREATE TABLE IF NOT EXISTS rag_notes (
    note_id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    item_key TEXT NOT NULL DEFAULT '',
    attachment_key TEXT NOT NULL DEFAULT '',

    note_type TEXT NOT NULL,
    -- zotero_note / annotation / user_note / writing_material

    source_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_json TEXT NOT NULL DEFAULT '{}',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    indexed_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_notes_item ON rag_notes(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_notes_type ON rag_notes(note_type);
CREATE INDEX IF NOT EXISTS idx_rag_notes_hash ON rag_notes(content_hash);
```

说明：

- Zotero `itemNotes` 可进入本表。
- PDF 标注 `itemAnnotations.text/comment` 后续也可进入本表。
- 写作项目材料可以用 `note_type='writing_material'`。

---

## 九、知识库组织

知识库是“选中条目 + 配置 + 任务上下文”的应用侧组织方式，不等于一个新的 Zotero collection。

### 9.1 rag_knowledge_bases

```sql
CREATE TABLE IF NOT EXISTS rag_knowledge_bases (
    knowledge_base_id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    base_mode TEXT NOT NULL DEFAULT 'manual',
    scope_json TEXT NOT NULL DEFAULT '{}',
    index_policy_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_kb_library ON rag_knowledge_bases(library_id);
CREATE INDEX IF NOT EXISTS idx_rag_kb_updated ON rag_knowledge_bases(updated_at);
```

### 9.2 rag_knowledge_base_items

```sql
CREATE TABLE IF NOT EXISTS rag_knowledge_base_items (
    knowledge_base_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (knowledge_base_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_rag_kb_items_item ON rag_knowledge_base_items(item_key);
```

知识库条目可以来自：

- 用户在文库页勾选后加入。
- Zotero collection。
- 标签筛选结果。
- 检索候选导入后的指定集合。

当前 MVP 已实现 `manual` 模式：知识库保存 `item_key` 集合，检索时作为作用域使用；Zotero metadata、notes 和 MinerU Markdown/图片仍保存在派生索引表中，Zotero 原始库继续作为事实源。

---

## 十、文献矩阵

### 10.1 rag_matrix_fields

```sql
CREATE TABLE IF NOT EXISTS rag_matrix_fields (
    field_id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL,
    name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    output_format TEXT NOT NULL DEFAULT 'text',
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_matrix_fields_kb ON rag_matrix_fields(knowledge_base_id);
```

### 10.2 rag_matrix_runs

```sql
CREATE TABLE IF NOT EXISTS rag_matrix_runs (
    matrix_run_id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    item_count INTEGER NOT NULL DEFAULT 0,
    field_count INTEGER NOT NULL DEFAULT 0,
    completed_cells INTEGER NOT NULL DEFAULT 0,
    failed_cells INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rag_matrix_runs_kb ON rag_matrix_runs(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_rag_matrix_runs_status ON rag_matrix_runs(status);
```

### 10.3 rag_matrix_cells

```sql
CREATE TABLE IF NOT EXISTS rag_matrix_cells (
    cell_id TEXT PRIMARY KEY,
    matrix_run_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    field_id TEXT NOT NULL,
    item_key TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',
    answer TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    sources_json TEXT NOT NULL DEFAULT '[]',
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT NOT NULL DEFAULT '',

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_matrix_cells_unique
ON rag_matrix_cells(matrix_run_id, field_id, item_key);
CREATE INDEX IF NOT EXISTS idx_rag_matrix_cells_item ON rag_matrix_cells(item_key);
CREATE INDEX IF NOT EXISTS idx_rag_matrix_cells_status ON rag_matrix_cells(status);
```

矩阵单元格必须能追溯来源：

```json
[
  {
    "chunk_id": "chunk-...",
    "item_key": "ABCD1234",
    "title": "Paper title",
    "section_title": "Method",
    "estimated_page": 4,
    "excerpt": "..."
  }
]
```

---

## 十一、对话和 Agent 证据

### 11.1 rag_chat_sessions

```sql
CREATE TABLE IF NOT EXISTS rag_chat_sessions (
    conversation_id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL DEFAULT '',
    item_keys_json TEXT NOT NULL DEFAULT '[]',
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chat_sessions_library ON rag_chat_sessions(library_id);
CREATE INDEX IF NOT EXISTS idx_rag_chat_sessions_kb ON rag_chat_sessions(knowledge_base_id);
```

`item_keys_json` 是会话首轮建立的知识库作用域快照。后续追问不能通过请求体扩大该范围。

### 11.2 rag_chat_messages

```sql
CREATE TABLE IF NOT EXISTS rag_chat_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    -- 当前持久化 user / assistant final answer
    content TEXT NOT NULL DEFAULT '',
    sources_json TEXT NOT NULL DEFAULT '[]',
    tool_trace_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_chat_msg_conv ON rag_chat_messages(conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_rag_chat_msg_run ON rag_chat_messages(run_id);
```

`tool_trace_json` 保留一期精简工具轨迹，用于向后兼容。Phase 2 的权威执行过程改由 `rag_agent_events` 保存；不持久化模型原始隐式推理或完整 tool result。

### 11.3 rag_agent_runs

```sql
CREATE TABLE IF NOT EXISTS rag_agent_runs (
    run_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    library_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    current_state TEXT NOT NULL DEFAULT 'plan',
    task_plan_json TEXT NOT NULL DEFAULT '{}',
    evidence_state_json TEXT NOT NULL DEFAULT '{}',
    budget_json TEXT NOT NULL DEFAULT '{}',
    usage_json TEXT NOT NULL DEFAULT '{}',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    worker_id TEXT NOT NULL DEFAULT '',
    heartbeat_at TEXT NOT NULL DEFAULT '',
    stop_reason TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT NOT NULL DEFAULT ''
);
```

约束：

- `status`：`running`、`completed`、`abstained`、`failed`、`cancelled`、`interrupted`。
- `current_state`：`plan`、`retrieve`、`inspect`、`read`、`verify`、`answer`、`abstain`。
- `stop_reason`：`completed`、`insufficient_evidence`、`budget_exceeded`、`provider_unavailable`、`user_action_required`、`cancelled`、`interrupted` 或 `internal_error`。
- `checkpoint_json` 在状态边界保存 TaskPlan、EvidenceState、事件序号、运行计数和恢复策略；敏感键落库前过滤。
- `worker_id` / `heartbeat_at` 用于识别旧工作进程遗留的 `running` 记录。当前安全恢复策略是将其标为 `interrupted`，再显式 `restart_from_user_turn`，不重放半截调用。
- 当前以 JSON 快照保存 TaskPlan、EvidenceState 和 verifier 结果；后续只有在出现明确查询需求时才拆成更多关系表。

### 11.4 rag_agent_events

```sql
CREATE TABLE IF NOT EXISTS rag_agent_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'summary',
    summary TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, sequence)
);
```

事件只保存可审计过程：计划摘要、状态转换、工具名和安全参数摘要、结果数量、证据覆盖变化、warning、验证结果和停止原因。`visibility` 分为 `summary`、`detail`、`diagnostic`、`internal`，前端默认只展示前两级。

---

## 十二、综述写作项目

### 12.1 rag_writing_projects

```sql
CREATE TABLE IF NOT EXISTS rag_writing_projects (
    project_id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_writing_projects_library ON rag_writing_projects(library_id);
CREATE INDEX IF NOT EXISTS idx_rag_writing_projects_kb ON rag_writing_projects(knowledge_base_id);
```

### 12.2 rag_writing_materials

```sql
CREATE TABLE IF NOT EXISTS rag_writing_materials (
    material_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    material_type TEXT NOT NULL,
    -- outline / draft / csv / markdown / note / instruction

    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_writing_materials_project ON rag_writing_materials(project_id);
CREATE INDEX IF NOT EXISTS idx_rag_writing_materials_type ON rag_writing_materials(material_type);
```

### 12.3 rag_writing_outputs

```sql
CREATE TABLE IF NOT EXISTS rag_writing_outputs (
    output_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    output_type TEXT NOT NULL,
    -- outline / section_draft / revision / summary

    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_writing_outputs_project ON rag_writing_outputs(project_id);
```

---

## 十三、向量存储扩展

MVP 不强制创建向量表。第二阶段如果不引入 ChromaDB，可先用 SQLite BLOB 保存 embedding：

```sql
CREATE TABLE IF NOT EXISTS rag_embeddings (
    chunk_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_embeddings_model ON rag_embeddings(model);
CREATE INDEX IF NOT EXISTS idx_rag_embeddings_hash ON rag_embeddings(content_hash);
```

如果使用 ChromaDB，建议路径：

```text
app-data/libraries/<library_id>/rag-assets/chromadb/
```

ChromaDB 只保存 chunk 向量和过滤元数据，权威 chunk 文本仍以 `rag.sqlite.rag_chunks` 为准。

---

## 十四、索引流程

### 14.1 MinerU 结果索引

```text
mineru-results/*.json
  -> 读取 item_key / attachment.key / parsed_at / result
  -> 找到同 stem 的 .md 或解压 Markdown
  -> 创建 rag_documents(source_type='mineru_markdown')
  -> Markdown heading + paragraph 分块
  -> 写 rag_chunks
  -> 写 rag_chunk_fts
  -> 扫描图片资产写 rag_assets
```

注意：

- 不重新调用 MinerU。
- 同一个附件多次解析时，优先使用最新 `parsed_at` 或最新 mtime 的结果。
- 旧结果可保留，但同一个 `item_key + attachment_key + source_type` 默认只索引最新有效版本。

### 14.2 Zotero metadata 索引

```text
ZoteroRepository.items()
  -> title / abstractNote / creators / tags / year / venue
  -> 创建 rag_documents(source_type='zotero_metadata')
  -> 创建 metadata chunk
  -> 写 rag_chunk_fts
```

### 14.3 Notes 索引

```text
item.notes
  -> 清理 HTML note 文本
  -> 创建 rag_notes
  -> 创建 rag_documents(source_type='note')
  -> 创建 note chunk
```

### 14.4 HTML 附件索引

```text
HTML attachment
  -> 读取 storage/<attachment_key>/*.html
  -> 去除 script/style/nav
  -> 提取 title / h1-h3 / paragraph / list / table text
  -> 创建 html chunks
```

---

## 十五、工具查询

### 15.1 keyword_search

```sql
SELECT
    f.chunk_id,
    f.item_key,
    f.doc_id,
    f.chunk_type,
    f.section_title,
    snippet(rag_chunk_fts, 7, '[', ']', '...', 16) AS snippet,
    bm25(rag_chunk_fts) AS score
FROM rag_chunk_fts f
WHERE rag_chunk_fts MATCH ?
ORDER BY score
LIMIT ?;
```

### 15.2 chunk_read

```sql
SELECT *
FROM rag_chunks
WHERE doc_id = ?
  AND chunk_index BETWEEN ? AND ?
ORDER BY chunk_index;
```

### 15.3 figure_read

```sql
SELECT *
FROM rag_assets
WHERE item_key = ?
  AND (chunk_id = ? OR ? = '')
ORDER BY created_at;
```

### 15.4 note_search

第一阶段可通过 `rag_chunk_fts` 搜索 `chunk_type='note'`，也可直接查 `rag_notes`。

---

## 十六、统一检索与 Evidence Pack 契约

Agentic RAG 对外优先暴露统一检索入口 `retrieve`，底层再编排 `metadata_search`、`keyword_search`、`semantic_search` 和 `chunk_read`。这样 Codex Agent 和前端不需要直接判断应该用哪一种检索方式。

### 16.1 retrieve 请求

```json
{
  "query": "Diffusion-VLA 的核心方法是什么？",
  "knowledge_base_id": "kb-core",
  "item_keys": ["ABCD1234"],
  "mode": "auto",
  "top_k": 8,
  "include_context": true
}
```

字段说明：

- `query`：用户问题或矩阵字段抽取指令。
- `knowledge_base_id`：知识库作用域。传入后只能检索该知识库中的 `item_key`。
- `item_keys`：可选二次限定。与知识库范围取交集，不能扩大范围。
- `mode`：`auto`、`metadata`、`keyword`、`semantic` 或 `hybrid`。
- `include_context`：为 true 时，对高分 chunk 执行 `chunk_read` 补上下文窗口。

### 16.2 Evidence Pack 返回

```json
{
  "query": "Diffusion-VLA 的核心方法是什么？",
  "mode": "auto",
  "knowledge_base_id": "kb-core",
  "results": [
    {
      "evidence_id": "ev-1",
      "source_type": "chunk",
      "item_key": "ABCD1234",
      "attachment_key": "ATTACH01",
      "doc_id": "doc-...",
      "chunk_id": "chunk-...",
      "title": "Paper title",
      "authors_text": "Author A; Author B",
      "year": "2024",
      "section_title": "Method",
      "estimated_page": 4,
      "text": "Evidence text...",
      "excerpt": "Short evidence excerpt...",
      "score": 0.82,
      "rank": 1,
      "citation": "[ABCD1234:chunk-4]"
    }
  ],
  "tool_calls": [
    {
      "tool": "keyword_search",
      "query": "Diffusion-VLA core method",
      "result_count": 5
    }
  ],
  "warnings": []
}
```

约束：

- Evidence Pack 不包含本机绝对路径、API key 或完整 SQLite 内容。
- `citation` 是给 Agent 使用的稳定来源标记，不等于正式参考文献格式。
- `source_type` 第一阶段包括 `metadata`、`chunk`、`note`，后续扩展 `figure`、`citation`、`writing_material`。
- `score` 是检索内部排序分，不作为事实置信度。
- `warnings` 用于表达 `semantic_search_not_configured`、`knowledge_base_empty`、`no_evidence_found` 等状态。

### 16.3 当前检索算法

MVP 的 `auto` / `hybrid` 使用轻量规则编排：

1. `metadata_search`：结构化字段匹配，优先返回可能相关的论文条目。
2. `keyword_search`：SQLite FTS5 全文检索，使用 `bm25(rag_chunk_fts)` 排序。
3. `chunk_read`：读取高分 chunk 的上下文窗口。
4. 合并去重：优先保留同一 `chunk_id` 的最高分结果；同一 `item_key` 可保留多个章节证据。

`semantic_search` 第一阶段只保留接口和 `not_configured` 状态；接入 embedding provider 后再进入 `hybrid` 排序。

---

## 十七、实施顺序

### Phase 1：Schema 和索引 MVP

- [x] 创建 `rag.sqlite` 初始化代码。
- [x] 创建 MVP 核心表：config、documents、chunks、fts、assets、notes、knowledge_bases、knowledge_base_items。
- [x] 实现 MinerU 结果扫描。
- [x] 实现 Zotero metadata 和 notes 索引。
- [x] 实现 FTS5 keyword_search 和 chunk_read。

### Phase 2：知识库问答

- [x] 创建 knowledge_bases / knowledge_base_items。
- [x] 实现知识库 CRUD API 和按知识库限定检索。
- [x] 定义并实现统一 `retrieve` 返回 Evidence Pack。
- [x] 创建 `rag_chat_sessions` / `rag_chat_messages`。
- [x] 实现 OpenAI-compatible Function Calling AgentRun、显式状态机与异步任务入口；RAG 主链路不依赖 Codex runtime。
- [x] 统一加载并注入 `skills/agentic-rag/` bundle。
- [x] 保存最终回答的 verified sources、精简 tool trace、TaskPlan、EvidenceState、checkpoint 和事件流。
- [x] 实现 hard gate、逐 claim verifier、单次受控修复、取消、中断收敛与显式重启。

### Phase 3：文献矩阵

- [ ] 创建 matrix_fields、matrix_runs、matrix_cells。
- [ ] 接入现有 `knowledge.html` 矩阵区域。
- [ ] 支持单元格重跑和来源展示。

### Phase 4：向量与图表增强

- [ ] 接 embedding provider。
- [ ] 实现 semantic_search。
- [ ] 扩展 figure_read 到 OCR 或多模态理解。

### Phase 5：综述写作项目

- [ ] 创建 writing_projects、materials、outputs。
- [ ] 支持大纲、段落草稿和引用证据。

---

## 十八、验收标准

- 普通索引重建只清理派生索引表，可从 Zotero + MinerU 恢复且不删除知识库、会话或 Agent 历史；删除整个 `rag.sqlite` 属于显式清空全部 RAG 数据。
- 不修改 `zotero.sqlite` schema。
- 不重新调用 MinerU，也可以索引已有 PDF 解析结果。
- `keyword_search` 可以搜到 MinerU Markdown 正文。
- `chunk_read` 可以返回上下文窗口。
- `figure_read` 可以返回图片路径和关联 chunk。
- 对话消息、矩阵单元格、写作输出都保存 `sources_json`。
- 没有来源证据时，Agent 不应伪造引用。
