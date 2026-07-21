# 语义检索

状态：实现说明  
日期：2026-07-18

## 范围

语义检索是在现有 Agentic RAG MVP 上增加的检索增强层，不改变当前核心约束：

- RAG 数据仍然按文库存放在 `app-data/libraries/<library_id>/rag.sqlite`。
- 不修改 Zotero 原生 schema。
- `rag_embeddings` 是可重建的派生索引；整个 `rag.sqlite` 还包含知识库、会话和 Agent 历史，不能把删除数据库当作普通索引刷新。
- 知识库作用域必须在向量检索前由后端强制执行。
- 如果同时传入 `knowledge_base_id` 和 `item_keys`，实际检索范围取两者交集。
- 未配置 embedding 时，metadata/keyword 检索和知识库问答仍然可用。

## 存储设计

当前第一版使用 SQLite BLOB 保存向量：

- `rag_embeddings` 每个 `chunk_id` 保存一条 embedding。
- `rag_chunks.embedding_status` 记录 `not_configured`、`pending`、`embedded` 或 `failed`。
- `rag_embeddings.content_hash` 必须和 `rag_chunks.content_hash` 一致；不一致时视为过期，需要重建。
- `rag_embeddings.content_version` 必须和 `rag_chunks.content_version` 一致；当前版本为 `structured-parent-v1`。
- `rag_chunks.embedding_model` 保存 `<provider>:<model>`，用于判断模型切换后的增量重建。
- `rag_config.schema_version`、`chunk_content_version` 和 `index_status.requires_reindex` 用于识别旧索引迁移。

权威文本、元数据、来源信息和知识库成员关系仍然以 `rag.sqlite` 中的 RAG 表为准。`rag_embeddings` 只是派生向量索引，可以删除后重建。

## Provider 抽象

Provider 抽象位于 `src/zotero_web_library/rag/embeddings.py`。

当前实现：

- `deterministic`：本地 hash 向量 provider，用于测试和离线开发。
- `openai`：使用项目已有 `openai` Python 依赖调用 OpenAI embeddings API。

向量存储边界刻意保持很小。后续如果要接 FAISS，只需要替换或补充 vector store 实现，不应该影响 RAG 工具、Evidence Pack、知识库作用域和 `/rag/chat` 主流程。

## 触发时机

embedding 生成和 chunk 写入是分离的：

1. `insert_chunks()` 写入 `rag_chunks` 和 FTS 行，并按 `chunk_id + provider + model + content_hash + content_version` 查找可复用向量。
2. 完全匹配的旧 embedding 会恢复为 `embedded`；只有新增、正文变化、模型变化或内容版本变化的 chunk 标记为 `pending`。
3. `index_library()` 和 `index_mineru_results()` 在普通 RAG 索引完成后，会调用 `embed_missing_chunks()` 补齐全部 pending chunk；请求按 `batch_size` 分批发送，但还会受 provider 安全上限约束（OpenAI-compatible 当前最多 10 条/批），该值不再限制一次操作的总处理量。
4. 每个成功批次立即提交到 SQLite；中途 provider 失败只标记当前失败批次，之前成功的向量保留，后续批次维持 pending。再次补齐不会重做成功批次。
5. 调用方也可以显式触发 embedding 补齐：

```http
POST /api/library/<library_id>/rag/embeddings/index
```

这个接口支持：

- `force`
- `knowledge_base_id`
- `item_keys`
- `batch_size`

如果未配置 embedding，RAG 索引、keyword 检索和 `/rag/chat` 仍然正常工作。

## API

新增接口：

```http
GET  /api/library/<library_id>/rag/embeddings/status
POST /api/library/<library_id>/rag/embeddings/index
POST /api/library/<library_id>/rag/tools/semantic_search
```

`semantic_search` 的返回结构尽量和 `keyword_search` 对齐，并增加：

- `semantic_score`
- `provider`
- `model`
- `status`

## 前端操作

### 1. 配置 embedding

进入当前文库的“API 配置”页面，找到“Embedding 配置”：

1. 勾选“启用语义检索”。
2. Provider 选择 `openai`。
3. Embedding 模型建议先填写 `text-embedding-3-small`。
4. API 请求地址默认使用 `https://api.openai.com/v1`。
5. 填写 API Key。
6. Batch Size 可先保持 `64`。
7. 维度可以留空，由 provider 返回结果自动确定。
8. 点击“保存 Embedding 配置”。

保存后，回到“知识库”页面刷新 RAG 索引或补齐语义索引。

### 2. 查看和补齐语义索引

进入“知识库”页面后，中间检索区会显示“语义索引”状态：

- 未配置 embedding 时，会提示当前聊天仍使用关键词检索。
- 已配置后，会显示已生成的 chunk embedding 数量、provider/model、待生成数量和失败数量。
- “补齐全库语义索引”会一次处理文库内全部缺失或过期的 chunk，不再每次最多处理 64 个；各知识库共享这些向量，不重复生成。
- “强制重建当前库”会在当前知识库范围内重新生成全部 embedding，仅在更换模型或确认向量损坏时使用。

顶部“刷新文档索引”负责重新扫描 metadata、notes、MinerU chunks 和 FTS 索引。操作前会明确确认；内容未变化的 chunk 复用已有 embedding，只为新增或变化的 chunk 调用 provider，并在刷新后补齐全部 pending chunk。文档刷新与 embedding 生成互斥，避免两个操作并发改写索引状态。

### 3. 使用知识库问答

右侧“智能体对话”仍然调用 `/rag/chat`。后端 `retrieve(mode="auto")` 会自动判断：

- 未配置 embedding：metadata + keyword 检索。
- 已配置 embedding：metadata + keyword + semantic 混合检索。

因此前端问答入口不需要切换按钮；只要语义索引已配置并生成，问答会自动使用混合检索。

## 混合检索

`retrieve()` 已支持真实语义检索：

- `mode="semantic"`：只跑语义检索。
- `mode="hybrid"`：metadata + keyword + semantic。
- `mode="auto"`：默认 metadata + keyword；只有 embedding 已配置时才加入 semantic。

`hybrid` / `auto` 中的 semantic 是可降级分支：如果 Embedding provider 在查询阶段不可用、配置错误或请求失败，检索会保留 metadata + keyword 结果，并在 Evidence Pack 中返回 `semantic_search_failed` warning，而不是让整个 Agent 工具调用变成 `tool_failed`。`mode="semantic"` 也会以结构化失败状态返回，便于上层决定是否换策略。

hybrid 排序按 `chunk_id` 去重，并组合 rank 风格分数：

1. 先识别 `factual`、`summary`、`comparative`、`matrix`、`writing` 或 `scope` 任务类型。
2. 规范化中英文问题，并为复杂问题生成最多 4 个带 `query_id` / `parent_query_id` 的查询。
3. 每个查询分别执行允许的 metadata、keyword 和 semantic 分支。
4. 使用标准 Reciprocal Rank Fusion：每次命中的贡献为 `1 / (60 + rank)`。
5. 可选执行 cross-encoder reranker；未配置或失败时保留 RRF 顺序。
6. 最后执行多样性选择；比较任务优先保证不同 `item_key` 的覆盖。

Evidence Pack 保留原有 `score` 字段，并增加：

- `query_plan`：规范化问题、任务类型和子查询 lineage。
- `ranking_stages`：RRF、reranker 和 diversity 的状态。
- `scores.rrf_score`、可选 `scores.reranker_score` 和 `scores.selection_score`。
- 每条结果的 `query_lineage` 和 `selection_reason`。

## 结构化 chunk 与父级上下文

MinerU Markdown 会保留完整标题路径，例如 `Paper > Method > Experiments`，并把正文标记为：

- `abstract`
- `method`
- `results`
- `table`
- `figure_caption`
- `references`
- `paragraph`

FTS 和向量索引继续使用较小的 `rag_chunks` 做召回；每个子 chunk 通过 `parent_chunk_id` 指向 `rag_chunk_parents` 中的章节上下文。`retrieve(include_context=True)` 和 `read_chunk_context` 命中子块后优先返回父级章节文本，从而兼顾召回精度和回答上下文完整性。

旧数据库会自动补齐新字段，但旧 chunk 会保留 `legacy-v1` 标记。`GET /api/library/<library_id>/rag/index/status` 返回 `requires_reindex=true` 时，使用知识库页面的“刷新文档索引”或调用索引接口重建；只有内容版本不一致的 Embedding 会进入待重建状态，完全匹配的向量继续复用。

## Metadata filters

`retrieve`、`keyword_search`、`semantic_search` 和 Agent 的 `search_evidence` 都接受同一种过滤器：

```json
{
  "filters": {
    "year_from": 2022,
    "year_to": 2026,
    "authors": ["Kim"],
    "venues": ["ICRA"],
    "item_keys": ["ITEM0001"],
    "chunk_types": ["method", "results"]
  }
}
```

`item_keys` filter 永远和会话快照/知识库后端作用域取交集，不能借此扩大范围。作者和 venue 当前使用 SQLite 子串匹配，年份使用闭区间过滤。

## 可选 cross-encoder reranker

默认不启用 reranker，也不增加新 Python 依赖。若已有兼容 HTTP rerank 服务，可设置：

```text
WEB_LIBRARY_RERANKER_URL=http://127.0.0.1:8080/rerank
WEB_LIBRARY_RERANKER_MODEL=bge-reranker-v2-m3
WEB_LIBRARY_RERANKER_API_KEY=
WEB_LIBRARY_RERANKER_TIMEOUT=12
```

请求体为 `{"model":"...","query":"...","documents":["..."]}`；响应可使用 `scores` 数组，或包含 `index` 与 `score`/`relevance_score` 的 `results` 数组。超时、响应格式错误或服务故障会产生 `reranker_failed` warning，并继续使用本地 RRF 结果。

## 后续 FAISS 替换点

如果文库规模变大，SQLite 扫描向量开始变慢，可以增加 FAISS 作为第二个 vector store：

```text
app-data/libraries/<library_id>/rag-assets/faiss/
```

推荐架构：

- FAISS 只保存 dense vectors 和内部整数 id。
- `rag.sqlite` 继续保存 chunk 元数据、来源真值、知识库 scope 和 id 映射。
- FAISS 索引允许删除重建，因为 `rag.sqlite` 仍然是权威数据源。
