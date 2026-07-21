# Tool Contract

Agentic RAG can either receive a backend-generated Evidence Pack or call backend-controlled tools. The backend, not the agent, executes retrieval against the local library.

## Callable Agent Tools

The function-calling runtime exposes only these tools:

- `search_evidence(query, mode="hybrid", top_k=8, filters={...})`: searches the current session scope and returns concise evidence summaries. It uses backend `retrieve(..., include_context=False)` and does not return full text.
- `read_chunk_context(chunk_id, window_size=1)`: reads a target chunk, its parent section context, and nearby chunks. The backend verifies every returned object belongs to the current session scope before returning text.
- `list_scope_documents(limit=50)`: lists up to 100 scoped documents with title, authors, year, source types, document count, and full-text availability.

The agent never receives or controls `knowledge_base_id` or `item_keys` in tool schemas. Scope is bound to the chat session by the backend.

### `search_evidence` arguments

- `query`: required Chinese or English retrieval query.
- `mode`: `hybrid`, `keyword`, `semantic`, or `metadata`. Prefer `hybrid` for content questions, `metadata` for bibliographic facts, and `keyword` as a local degradation path.
- `top_k`: 1–20, default 8.
- `filters`: optional object with `year_from`, `year_to`, `authors`, `venues`, `item_keys`, and `chunk_types`.

Supported `chunk_types` include `abstract`, `method`, `results`, `table`, `figure_caption`, `references`, `paragraph`, `metadata`, and `note`. Filter `item_keys` are intersected with the session scope by the backend and can never expand it.

The result also reports backend `task_type`, `query_plan`, and `ranking_stages`. The backend may normalize, expand, or decompose the query automatically, so inspect lineage before issuing another query.

### `read_chunk_context` result

- `parent_context`: section-level text, `section_path`, `parent_chunk_id`, and the target chunk citation. Prefer this for coherent deep reading.
- `chunks`: the target and bounded neighboring chunks.

`parent_chunk_id` is provenance, not a citation marker. Cite the existing target chunk marker returned with `parent_context`.

## Retrieval Tools

- `retrieve`: Unified backend retrieval entry. It performs task classification, query planning, RRF fusion, optional reranking, diversity selection, and evidence construction.
- `metadata_search`: Searches Zotero-derived metadata chunks such as title, authors, year, venue, abstract, DOI, tags, and identifiers.
- `keyword_search`: Searches indexed full-text chunks with SQLite FTS5 and BM25 ranking.
- `semantic_search`: Embedding search. Treat `not_configured` as unavailable evidence, not as a failed answer.
- `chunk_read`: Reads the target chunk plus nearby chunks for local context.

## Evidence Pack Shape

Expected top-level fields:

- `query`: User question or extraction instruction.
- `mode`: Retrieval mode such as `auto`, `metadata`, `keyword`, `semantic`, or `hybrid`.
- `task_type`: `factual`, `summary`, `comparative`, `matrix`, `writing`, or `scope`.
- `query_plan`: Normalized query and generated query lineage.
- `knowledge_base_id`: Optional knowledge-base scope.
- `filters`: Applied structured filters.
- `results`: Ordered evidence entries.
- `tool_calls`: Backend retrieval calls already executed.
- `ranking_stages`: RRF, optional reranker, and diversity stage status.
- `warnings`: Structured retrieval degradation or insufficiency warnings.

Common result fields:

- `evidence_id`: Stable identifier within the current answer.
- `source_type`: `metadata`, `chunk`, `note`, `figure`, `citation`, or `writing_material`.
- `item_key`: Zotero item key.
- `attachment_key`: Zotero attachment key, if any.
- `doc_id`: RAG document id.
- `chunk_id`: RAG chunk id, if any.
- `title`, `authors_text`, `year`, `venue`: Human-readable source metadata.
- `section_title`, `section_path`, `parent_chunk_id`, `estimated_page`: Local source position when available.
- `text`: Evidence text available to reason over.
- `excerpt`: Short display excerpt.
- `score`: Retrieval ranking score, not factual confidence.
- `scores`: RRF, optional reranker, and diversity-selection scores. None are factual confidence.
- `query_lineage`: Queries and retrievers that contributed to this result.
- `selection_reason`: Such as `mmr` or `comparative_item_coverage`.
- `rank`: Evidence rank in the current pack.
- `citation`: Marker to cite this evidence.

## Warning Semantics

- `semantic_search_not_configured`: semantic evidence is unavailable; lexical results may still be valid.
- `semantic_search_failed`: semantic retrieval failed; continue with metadata/keyword results when present.
- `semantic_search_empty_scope`: the semantic branch had no allowed scoped items.
- `reranker_failed`: RRF results remain available and ordered without reranking.
- `keyword_no_match_used_scope_context`: the backend used low-precision scoped context fallback; deep-read and verify before claiming details.
- `no_evidence_found`: abstain or make a materially different scoped retrieval attempt.

## Boundaries

Do not ask for raw database access, local file paths, API keys, or full documents. Do not call unexposed tools such as `read_matrix`, `compare_matrix`, `figure_read`, or `table_read`. If the Evidence Pack is not enough, refine retrieval within the exposed contract or say the evidence is insufficient.
