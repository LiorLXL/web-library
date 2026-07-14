# Tool Contract

Agentic RAG can either receive a backend-generated Evidence Pack or call backend-controlled tools. The backend, not the agent, executes retrieval against the local library.

## Callable Agent Tools

The function-calling runtime exposes only these tools:

- `search_evidence(query, mode="hybrid", top_k=8)`: searches the current session scope and returns concise evidence summaries. It uses backend `retrieve(..., include_context=False)` and does not return full text.
- `read_chunk_context(chunk_id, window_size=1)`: reads a target chunk plus nearby chunks. The backend verifies every returned chunk belongs to the current session scope before returning text.
- `list_scope_documents(limit=50)`: lists up to 100 scoped documents with title, authors, year, source types, document count, and full-text availability.

The agent never receives or controls `knowledge_base_id` or `item_keys` in tool schemas. Scope is bound to the chat session by the backend.

## Retrieval Tools

- `retrieve`: Unified backend retrieval entry. It may combine metadata, keyword, semantic, and chunk context reads.
- `metadata_search`: Searches Zotero-derived metadata chunks such as title, authors, year, venue, abstract, DOI, tags, and identifiers.
- `keyword_search`: Searches indexed full-text chunks with SQLite FTS5 and BM25 ranking.
- `semantic_search`: Embedding search. Treat `not_configured` as unavailable evidence, not as a failed answer.
- `chunk_read`: Reads the target chunk plus nearby chunks for local context.

## Evidence Pack Shape

Expected top-level fields:

- `query`: User question or extraction instruction.
- `mode`: Retrieval mode such as `auto`, `metadata`, `keyword`, `semantic`, or `hybrid`.
- `knowledge_base_id`: Optional knowledge-base scope.
- `results`: Ordered evidence entries.
- `tool_calls`: Backend retrieval calls already executed.
- `warnings`: Retrieval warnings such as `no_evidence_found` or `semantic_search_not_configured`.

Common result fields:

- `evidence_id`: Stable identifier within the current answer.
- `source_type`: `metadata`, `chunk`, `note`, `figure`, `citation`, or `writing_material`.
- `item_key`: Zotero item key.
- `attachment_key`: Zotero attachment key, if any.
- `doc_id`: RAG document id.
- `chunk_id`: RAG chunk id, if any.
- `title`, `authors_text`, `year`, `venue`: Human-readable source metadata.
- `section_title`, `estimated_page`: Local source position when available.
- `text`: Evidence text available to reason over.
- `excerpt`: Short display excerpt.
- `score`: Retrieval ranking score, not factual confidence.
- `rank`: Evidence rank in the current pack.
- `citation`: Marker to cite this evidence.

## Boundaries

Do not ask for raw database access, local file paths, API keys, or full documents. If the Evidence Pack is not enough, request more retrieval or say the evidence is insufficient.
