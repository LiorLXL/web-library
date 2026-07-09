# 语义检索

状态：实现说明  
日期：2026-07-08

## 范围

语义检索是在现有 Agentic RAG MVP 上增加的检索增强层，不改变当前核心约束：

- RAG 数据仍然按文库存放在 `app-data/libraries/<library_id>/rag.sqlite`。
- 不修改 Zotero 原生 schema。
- `rag.sqlite` 仍然是可删除、可重建的派生索引。
- 知识库作用域必须在向量检索前由后端强制执行。
- 如果同时传入 `knowledge_base_id` 和 `item_keys`，实际检索范围取两者交集。
- 未配置 embedding 时，metadata/keyword 检索和知识库问答仍然可用。

## 存储设计

当前第一版使用 SQLite BLOB 保存向量：

- `rag_embeddings` 每个 `chunk_id` 保存一条 embedding。
- `rag_chunks.embedding_status` 记录 `not_configured`、`pending`、`embedded` 或 `failed`。
- `rag_embeddings.content_hash` 必须和 `rag_chunks.content_hash` 一致；不一致时视为过期，需要重建。
- `rag_chunks.embedding_model` 保存 `<provider>:<model>`，用于判断模型切换后的增量重建。

权威文本、元数据、来源信息和知识库成员关系仍然以 `rag.sqlite` 中的 RAG 表为准。`rag_embeddings` 只是派生向量索引，可以删除后重建。

## Provider 抽象

Provider 抽象位于 `src/zotero_web_library/rag/embeddings.py`。

当前实现：

- `deterministic`：本地 hash 向量 provider，用于测试和离线开发。
- `openai`：使用项目已有 `openai` Python 依赖调用 OpenAI embeddings API。

向量存储边界刻意保持很小。后续如果要接 FAISS，只需要替换或补充 vector store 实现，不应该影响 RAG 工具、Evidence Pack、知识库作用域和 `/rag/chat` 主流程。

## 触发时机

embedding 生成和 chunk 写入是分离的：

1. `insert_chunks()` 只写入 `rag_chunks` 和 FTS 行。
2. 如果当前文库已配置 embedding，新 chunk 会被标记为 `pending`。
3. `index_library()` 和 `index_mineru_results()` 在普通 RAG 索引完成后，会执行一次有 batch 限制的 `embed_missing_chunks()`。
4. 调用方也可以显式触发 embedding 补齐：

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
- “补齐语义索引”会只处理缺失或过期的 chunk。
- “强制重建”会在当前知识库范围内重新生成 embedding。

顶部“刷新 RAG 索引”仍然负责重建 metadata、notes、MinerU chunks 和 FTS 索引；如果 embedding 已启用，刷新后会自动补齐一批 pending chunks。

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

hybrid 排序按 `chunk_id` 去重，并组合 rank 风格分数：

- keyword rank 权重：`0.55`
- semantic rank 权重：`0.35`
- metadata rank 权重：`0.10`

Evidence Pack 保留原有 `score` 字段，保证前端和 Codex prompt 兼容；同时新增 `scores` 对象保存各路分数组件。

## 后续 FAISS 替换点

如果文库规模变大，SQLite 扫描向量开始变慢，可以增加 FAISS 作为第二个 vector store：

```text
app-data/libraries/<library_id>/rag-assets/faiss/
```

推荐架构：

- FAISS 只保存 dense vectors 和内部整数 id。
- `rag.sqlite` 继续保存 chunk 元数据、来源真值、知识库 scope 和 id 映射。
- FAISS 索引允许删除重建，因为 `rag.sqlite` 仍然是权威数据源。
