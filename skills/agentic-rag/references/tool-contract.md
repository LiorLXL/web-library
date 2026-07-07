# Tool Contract

Agentic RAG receives a backend-generated Evidence Pack. The backend, not the agent, executes retrieval against the local library.

## Retrieval Tools

- `retrieve`: Unified backend retrieval entry. It may combine metadata, keyword, semantic, and chunk context reads.
- `metadata_search`: Searches Zotero-derived metadata chunks such as title, authors, year, venue, abstract, DOI, tags, and identifiers.
- `keyword_search`: Searches indexed full-text chunks with SQLite FTS5 and BM25 ranking.
- `semantic_search`: Reserved for embedding search. Treat `not_configured` as unavailable evidence, not as a failed answer.
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
