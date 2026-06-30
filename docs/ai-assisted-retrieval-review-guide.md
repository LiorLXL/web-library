# AI 辅助多源异构检索 PR 评审说明

## 本次 PR 做了什么

这次新增的是一个完整的“AI 辅助多源异构检索闭环”：

1. 先在 API 配置页保存模型 API 和可选代码/数据源 token。
2. 在多源检索页输入关键词。
3. 可以直接检索，也可以让 AI 生成检索计划后批量检索。
4. 检索结果统一进入候选区，由 AI 基于元数据给出推荐、复核或不建议。
5. 用户最终手动勾选，再导入到现有 Zotero 文库格式。

AI 不直接入库，只辅助生成 query、排序和默认勾选。

## 新增功能清单

- API 配置页：`/library/<library_id>/api-config`
- 模型配置：模型名称、请求地址、API Key
- 代码/数据源 token：GitHub、HuggingFace、Zenodo，均为可选
- 新增异构数据源：
  - 论文/预印本：Crossref、arXiv、PubMed、Semantic Scholar、DataCite 等
  - 代码/模型：GitHub、HuggingFace
  - 数据集/软件/报告：Zenodo、DataCite、HuggingFace
  - 本地/内部源：Local CSV/JSONL、HTTP JSON、SQLite、Manifest
- AI 检索计划：
  - 核心概念
  - 方法别名
  - benchmark/evaluation query
  - dataset/code/model query
  - 中英文直译或常见别名
- 候选 AI 判断：
  - `recommend`
  - `review`
  - `reject`
  - 相关性分数、质量分数、风险等级、理由、缺失字段
- 检索结果页：
  - 显示资料类型：论文、代码/软件、数据集、报告
  - 显示多源命中
  - 显示 AI 判断
  - 导入前显示 Zotero 字段预览
- 计划检索性能控制：
  - 快速模式：代码/模型/数据源默认取更少候选
  - 全量模式：每源取更多候选，覆盖更全但更慢
  - 每个源都可以手动调整候选数量
  - 同一进程内短 TTL 缓存相同 query/source/limit 组合
  - GitHub/HuggingFace/Zenodo 使用更短源级超时
  - 候选 AI 判断按小批次请求，避免候选过多时单次 payload 过大

## 推荐评审路径

1. 打开 API 配置页，保存模型配置。
2. 打开多源检索页。
3. 输入 `speculative decoding`。
4. 先点“生成计划”，检查 query 是否包含概念扩展，而不是只出现 `paper/code/dataset` 后缀。
5. 保持快速模式，检查每个源数量是否可调。
6. 点“按计划批量检索”。
7. 观察候选区是否展示：
   - 资料类型
   - 来源或多源命中
   - AI 推荐理由
   - 入库字段预览
8. 点“全选 AI 推荐”，再点“导入所选”。
9. 下载汇总报告，检查证据链。

## 演示截图

API 配置页：

![API 配置页](screenshots/api-config.png)

多源检索页：

![多源检索页](screenshots/multi-source-retrieval.png)

候选结果区：

![候选结果区](screenshots/retrieval-candidates.png)

## 直接检索和计划检索的区别

- 直接检索：只用输入框里的关键词跑一次，速度最快，适合快速查一个明确词。
- 计划检索：先生成多条相关 query，再批量跑多个源，覆盖面更广，适合汇报“多源异构检索能力”。

两者的结果都会进入同一个候选区，导入逻辑一致。

## 测试命令

```powershell
node --check src/zotero_web_library/static/app.js
.venv\Scripts\python.exe -m pytest
git diff --check
```

## 约束说明

- API Key 当前保存到本地 `app.sqlite`，适合本地演示，不适合多人公网部署。
- GitHub、HuggingFace、Zenodo token 可选，未配置时检索公开资源。
- AI 评估只发送候选元数据，不发送 provider raw JSON。
- AI 判断只影响排序和默认勾选，最终是否入库仍由用户决定。

## 建议 PR 描述

```markdown
## Summary

新增 AI 辅助多源异构检索闭环：API 配置页、GitHub/HuggingFace/Zenodo 数据源、AI 检索计划、候选 AI 判断、批量检索候选汇总，以及导入前人工确认。

## 使用流程

1. 在 API 配置页填写模型名称、请求地址、API Key。
2. 进入多源检索页，输入关键词。
3. 选择直接检索，或先生成 AI 检索计划再批量检索。
4. 在候选区查看资料类型、来源命中、AI 判断、入库字段预览。
5. 点击“全选 AI 推荐”或手动勾选，再导入所选。

## 截图

- API 配置页：`docs/screenshots/api-config.png`
- 多源检索页：`docs/screenshots/multi-source-retrieval.png`
- 候选结果区：`docs/screenshots/retrieval-candidates.png`

## 验证

- `node --check src/zotero_web_library/static/app.js`
- `.venv\Scripts\python.exe -m pytest`
- `git diff --check`
```
