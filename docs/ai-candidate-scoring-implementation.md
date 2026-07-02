# AI 候选评分功能实现说明

本文维护多源异构检索候选区的 AI 评分实现，重点说明“有模型 API 时如何评分、没模型 API 时如何降级、前后端字段如何约定”。

## 1. 功能目标

检索结果不会直接入库，而是先进入候选区。系统对每条候选资料做结构化判断：

1. 是否推荐进入人工确认流程。
2. 主题是否贴合用户 query。
3. 元数据是否足够完整，能否安全映射到 Zotero。
4. 来源证据是否可追踪。
5. 导入风险是否偏高。

最终入库仍由用户手动确认，AI 或规则评分只影响候选排序、展示和默认勾选。

## 2. 配置入口

模型配置入口：

- 页面：`/library/<library_id>/api-config`
- 后端接口：`GET/POST /api/library/<library_id>/api-config`
- 状态接口：`GET /api/library/<library_id>/retrieval/model-status`

配置优先级：

1. 页面保存到本地 `app.sqlite` 的模型配置。
2. 环境变量 `AI_PIXEL_API_KEY`、`AI_PIXEL_MODEL`、`AI_PIXEL_BASE_URL` 等。
3. 默认模型名和默认请求地址。

只有 API Key 存在时，`retrieval_model_status()` 才会返回 `configured: true`，候选评分才会走模型 API。

## 3. 评分流程

入口函数：

- `evaluate_retrieval_candidates_with_ai()` in `src/zotero_web_library/web.py`
- `POST /api/library/<library_id>/retrieval/ai-scoring-jobs`：当前 UI 使用的后台评分任务入口。
- `GET /api/library/<library_id>/retrieval/ai-scoring-jobs/latest`：页面重新进入后恢复最近评分任务。
- `POST /api/library/<library_id>/retrieval/ai-scoring-jobs/<job_id>/cancel`：停止后台评分队列。

流程：

1. 检索 provider 返回候选资料。
2. 后端把候选压缩成安全元数据，不发送 provider 的 `raw` 原始响应。
3. 如果用户关闭 AI 评估、没有模型 API Key、或模型调用失败，则走规则兜底。
4. 如果模型可用，则由后台评分 job 按规则置信度从高到低逐条把候选发给模型；前端只负责启动、轮询和取消任务。
5. 模型按统一 rubric 返回 JSON。
6. 后端只做字段校验、分数夹取、未知 candidate_id 拒收、缺失候选 fallback；单条失败不会覆盖其他候选已经成功的 AI 分数。
7. 后台每评完一条就更新 job candidates；前端轮询后刷新候选区，展示评分来源、推荐决策、五个评分维度和中文理由。
8. 用户中断时，后端 job 进入取消流程；已完成的 `ai_model` 评分保留，未评分候选保留规则结果或失败兜底。页面切走不会中断后台评分，重新进入后通过 latest job 恢复。

## 4. 发送给模型的元数据

每条候选只发送这些字段：

```json
{
  "candidate_id": "candidate-1",
  "title": "Speculative Decoding for Scientific Models",
  "authors": ["Ada Lovelace"],
  "year": "2026",
  "abstract": "Speculative decoding speeds up model inference.",
  "source": "crossref",
  "sources": ["crossref", "datacite"],
  "source_count": 2,
  "multi_source": true,
  "doi": "10.1000/spec",
  "pmid": "",
  "arxiv": "",
  "isbn": "",
  "url": "https://doi.org/10.1000/spec",
  "item_type": "journalArticle"
}
```

不会发送：

- provider 原始响应 `raw`
- API key / token
- 本地数据库路径
- 任何用户密钥

## 5. AI Rubric

当前评分框架标识：

```text
ai_rubric_v1
```

模型必须输出 0-100 的整数分。除 `import_risk_score` 外，分数越高越好。

| 字段 | 含义 |
| --- | --- |
| `topic_relevance_score` | 主题相关度：query 与标题、摘要、资料类型的语义匹配程度。 |
| `metadata_quality_score` | 元数据质量：标题、作者、年份、摘要、标识符、URL 是否足够完整。 |
| `source_evidence_score` | 来源证据强度：DOI/PMID/arXiv/ISBN/URL、来源名、多源命中是否可追踪。 |
| `import_risk_score` | 导入风险：重复、噪声、缺字段、来源不清等风险；越高风险越大。 |
| `final_confidence_score` | 最终推荐置信度：模型综合判断，不要求按固定公式计算。 |

分档：

| 分数 | 解释 |
| ---: | --- |
| 90-100 | 非常强，几乎可以直接推荐进入人工确认。 |
| 75-89 | 较强，推荐但仍需要用户确认。 |
| 55-74 | 中等，需要复核。 |
| 30-54 | 较弱，不建议优先导入。 |
| 0-29 | 明显无关或信息严重不足。 |

约束：

- 只能基于给定元数据判断，不能编造 DOI、作者、摘要或来源。
- 标题缺失，或标识符和 URL 都缺失时，`final_confidence_score` 不应高于 60。
- 标题/摘要与 query 语义不匹配时，即使元数据完整，也应降低最终置信度。
- 信息不完整或不确定性较大时，优先给 `review`。

## 6. 模型输出格式

模型应返回严格 JSON：

```json
{
  "evaluations": [
    {
      "candidate_id": "candidate-1",
      "decision": "recommend",
      "topic_relevance_score": 92,
      "metadata_quality_score": 88,
      "source_evidence_score": 86,
      "import_risk_score": 14,
      "final_confidence_score": 90,
      "risk_level": "low",
      "reason": "标题和摘要与 query 高度相关，且有 DOI 和稳定来源。",
      "missing_fields": []
    }
  ]
}
```

`decision` 只能是：

- `recommend`
- `review`
- `reject`

`risk_level` 只能是：

- `low`
- `medium`
- `high`

## 7. 后端校验与自动勾选

模型返回后，后端通过 `normalized_ai_evaluation()` 做归一化：

- 所有分数夹到 0-100。
- 兼容旧字段 `relevance_score` / `quality_score`，但新实现优先使用 rubric 字段。
- 不认识的 `decision` 归为 `review`。
- 不认识的 `risk_level` 归为 `medium`。
- 未命中的 `candidate_id` 不会写入候选。
- 模型漏评的候选会单条走规则 fallback。

自动勾选仍由后端保守判断：

```text
decision == recommend
final_confidence_score >= 75
import_risk_score <= 40
risk_level != high
不缺 title
不缺 identifier_or_url
```

这个规则不是重新替 AI 打分，而是防止模型高估风险条目后被默认选中。

## 8. 规则兜底

规则兜底框架标识：

```text
metadata_rules_v1
```

触发场景：

- 用户关闭 AI 评估。
- 未配置模型 API Key。
- 模型接口失败。
- 模型没有返回某条候选的有效 evaluation。

兜底评分由 `deterministic_candidate_evaluation()` 生成，主要依据：

- query 词是否命中标题/摘要。
- 是否多源命中。
- 是否有 DOI/PMID/arXiv/ISBN。
- 是否有标题、作者、摘要、URL。
- 是否疑似重复或缺关键字段。

前端会显示为“规则兜底”“规则评分”或汇总层面的“AI部分评分”，不会把模型失败的候选显示成“AI评分”。

## 9. 前端展示

候选卡片展示：

- `AI评分：推荐入库`，模型 API 正常时。
- `AI评分中`，该候选正在逐条评分时。
- `AI部分评分`，部分候选已完成 AI 评分、部分仍为规则或失败兜底时。
- `规则兜底：需要复核`，模型未配置或失败时。
- 置信、主题、元数据、证据、导入风险五个维度。
- 模型或规则给出的 reason。

候选区汇总条展示：

- 评分来源。
- 推荐 / 复核 / 不建议数量。
- 默认勾选数量。
- 模型未配置或错误信息。

“全选 AI 推荐”只选择真实 `ai_model` 评分且 decision 为 `recommend` 的候选；规则评分或 fallback 候选不会被这个按钮选中。

## 10. 涉及文件

- `src/zotero_web_library/web.py`
  - AI rubric prompt
  - 候选元数据压缩
  - 模型调用、归一化、fallback、排序和自动勾选
- `src/zotero_web_library/retrieval/providers.py`
  - 模型配置、状态、健康检查和 OpenAI-compatible chat 调用
- `src/zotero_web_library/static/app.js`
  - 候选评分展示
  - 评分来源文案
  - 候选区推荐选择按钮
- `tests/test_retrieval.py`
  - 模型元数据请求、未知 candidate_id 拒收、分批评分、部分批次失败保留、手动评分上限、搜索 API 评分契约测试

## 11. 验证命令

```powershell
node --check src\zotero_web_library\static\app.js
git diff --check
.venv\Scripts\python.exe -m pytest
```

当前验证结果：

```text
201 passed
```
