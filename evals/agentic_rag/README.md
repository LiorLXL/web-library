# Agentic RAG 离线评测

本目录是 Phase 0 的确定性评测入口。默认评测不读取真实 Zotero 文库、不请求外部模型，也不需要 API Key。

## 文件

- `eval-case.schema.json`：评测集 JSON Schema。
- `smoke-v1.json`：20 条最小烟雾评测用例。
- `synthetic-corpus-v1.json`：8 篇合成 VLA 论文和 4 个知识库作用域。
- `reports/baseline-retrieval-v1.json`：机器可读基线。
- `reports/baseline-retrieval-v1.md`：人类可读基线。

合成语料只用于回归测试，不声明其中数值或论文内容是真实研究事实。

## 校验评测资产

```powershell
uv run python -m zotero_web_library.rag_eval_cli validate `
  --suite evals/agentic_rag/smoke-v1.json `
  --corpus evals/agentic_rag/synthetic-corpus-v1.json
```

## 运行确定性检索基线

```powershell
uv run python -m zotero_web_library.rag_eval_cli run `
  --suite evals/agentic_rag/smoke-v1.json `
  --synthetic-corpus evals/agentic_rag/synthetic-corpus-v1.json `
  --target retrieve `
  --output-dir evals/agentic_rag/reports `
  --report-stem baseline-retrieval-v1
```

只要存在未通过或运行错误，命令就返回退出码 `2`，可直接用于 CI。探索新用例、不希望失败退出时可加 `--allow-failures`。

## 运行完整 Agent 评测

完整 Agent 评测会真实调用模型。配置通过环境变量传入，API Key 不会写进报告：

```powershell
$env:RAG_EVAL_MODEL="your-model"
$env:RAG_EVAL_BASE_URL="https://api.openai.com/v1"
$env:RAG_EVAL_API_KEY="your-key"

uv run python -m zotero_web_library.rag_eval_cli run `
  --suite evals/agentic_rag/smoke-v1.json `
  --synthetic-corpus evals/agentic_rag/synthetic-corpus-v1.json `
  --target agent `
  --output-dir evals/agentic_rag/reports `
  --report-stem baseline-agent-v1
```

`retrieve` 报告中的 `answer` 和 `usage` 为空，但始终保存 sources、tool trace、warnings 和 latency；`agent` 报告会同时保存 answer、sources、tool trace、usage 和 latency。

## 对真实文库评测

为真实文库单独建立用例文件，在 `scope.knowledge_base_name` 中使用该文库已有知识库名称，然后运行：

```powershell
uv run python -m zotero_web_library.rag_eval_cli run `
  --suite path/to/private-suite.json `
  --library-id your-library-id `
  --target retrieve `
  --output-dir path/to/private-reports
```

真实文库用例和报告可能包含文献标题、item key、问题与模型回答，默认不应提交到公共仓库。

## 当前断言能力

每条用例可以声明：

- 最少/最多结果数。
- 最少覆盖文献数。
- 必须召回、任意召回、禁止召回或允许范围内的 item key。
- 必须出现或禁止出现的 warning。
- 必须命中的 section title。
- Agent 回答必须包含的文本。

Iteration 0.2 会在此基础上增加 Recall@K、MRR、nDCG 和 item coverage 等聚合检索指标。
