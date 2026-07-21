# Retrieval Policy

Use the Evidence Pack according to task type. Do not repeat the same tool with identical arguments; change query, mode, filters, target item, or chunk type when refining.

## Mode and Filter Selection

- Start content questions with `hybrid`; use `keyword` when semantic retrieval is unavailable or when exact terminology matters.
- Use `metadata` for title, author, year, venue, DOI, tags, and scope discovery.
- Use `chunk_types=["abstract"]` for contribution/overview questions, `method` for implementation details, and `results` for experiments or findings.
- Use year, author, or venue filters only when requested or required by the task. Treat multiple values in one filter as alternatives.
- Inspect backend query lineage before manually producing synonyms that were already searched.

## Factual Q&A

- Use metadata evidence for bibliographic facts.
- Use chunk evidence for content facts.
- If the answer needs page, section, method detail, or result detail and no chunk supports it, mark the answer as insufficient.
- Deep-read the parent context when a concise result does not contain the complete supporting statement.

## Analytical Q&A

- Prefer multiple chunk sources from the same paper when summarizing a method.
- Prefer evidence from several papers when making field-level claims.
- Separate what the papers state from your synthesis.
- Prefer `abstract`, `method`, and `results` chunks according to the requested dimension instead of treating all chunks equally.

## Comparison

- Compare only dimensions that have evidence for at least two papers.
- If a paper lacks evidence for a dimension, mark that cell as not found instead of inferring.
- Inspect `list_scope_documents` when the expected papers are unclear.
- Require multiple `item_key` values in comparative evidence when the scope contains multiple relevant papers. If one paper dominates, refine by target `item_keys` or chunk type.
- Do not interpret `comparative_item_coverage` as proof that the selected passages support the same dimension; verify their text.

## Literature Matrix

- Fill the requested field only.
- Keep the cell concise.
- Attach citation markers inside the cell or alongside the cell value.
- Do not mix unsupported background knowledge into matrix cells.
- Use this policy only when evidence for the requested cell is supplied through current tools or an Evidence Pack. Do not claim access to stored matrix cells.

## Review Writing

- Treat Evidence Pack entries as source material, not as final prose.
- Write synthesis in your own words, but keep citations attached to factual claims.
- Use user notes as reading/project context, not as paper evidence unless clearly marked.

## Degradation and Refinement

- Continue with lexical evidence after `semantic_search_failed` or `semantic_search_not_configured` when that evidence directly supports the claim.
- Continue with RRF order after `reranker_failed`; do not describe the failure as missing paper evidence.
- Treat `keyword_no_match_used_scope_context` as a prompt to deep-read, not as proof of relevance.
- After a tool failure, change strategy only when the warning affects evidence needed by the task.
- Stop after evidence is sufficient, no new scoped retrieval path remains, or the runtime budget requires an answer/abstention.

## Insufficient Evidence

Say evidence is insufficient when:

- `results` is empty.
- Results are only metadata but the user asks for methods, experiments, limitations, or findings.
- Evidence does not mention the requested concept.
- Citations would be attached to claims not stated in the evidence.
- A comparison has evidence for only one side and the missing side cannot be retrieved from scope.
- A table or figure-caption chunk does not contain the visual fact the user asks about.
