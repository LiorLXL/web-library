# Agentic RAG 评测报告：agentic-rag-smoke-v1

- 运行 ID：`eval-c4818cdcb84a`
- 目标：`retrieve`
- 开始时间：`2026-07-14T04:17:47+00:00`
- 总用时：224.601 ms
- 通过率：20/20 (100.0%)
- P95 单例延迟：18.381 ms

## 用例结果

| Case | 类型 | 模式 | 状态 | 结果数 | 延迟(ms) |
|---|---|---|---|---:|---:|
| `action-chunking-purpose` | factual | keyword | passed | 4 | 8.749 |
| `action-sequence-mechanism` | summary | hybrid | passed | 8 | 15.258 |
| `diffusion-action-expert` | factual | hybrid | passed | 8 | 19.188 |
| `self-generated-reasoning` | factual | keyword | passed | 1 | 4.448 |
| `hamster-hierarchy` | summary | hybrid | passed | 8 | 14.784 |
| `xvla-soft-prompt` | summary | hybrid | passed | 8 | 16.617 |
| `smolvla-efficiency` | factual | keyword | passed | 1 | 4.573 |
| `rt2-web-transfer` | summary | hybrid | passed | 8 | 18.381 |
| `dexcap-portable-mocap` | factual | keyword | passed | 1 | 4.515 |
| `survey-open-challenges` | summary | hybrid | passed | 8 | 15.825 |
| `compare-long-horizon-methods` | comparative | hybrid | passed | 10 | 15.129 |
| `libero-benchmark` | factual | keyword | passed | 1 | 4.484 |
| `smolvla-semantic-paraphrase` | factual | semantic | passed | 8 | 8.694 |
| `rt2-co-finetuning` | factual | hybrid | passed | 8 | 14.746 |
| `xvla-zero-shot-transfer` | factual | semantic | passed | 8 | 7.574 |
| `dexcap-capture-hardware` | factual | hybrid | passed | 8 | 16.889 |
| `metadata-title-smolvla` | factual | metadata | passed | 1 | 4.718 |
| `negative-metadata-no-match` | negative | metadata | passed | 0 | 4.872 |
| `scope-blocks-diffusion-paper` | scope | keyword | passed | 4 | 8.366 |
| `empty-knowledge-base` | negative | hybrid | passed | 0 | 14.099 |
