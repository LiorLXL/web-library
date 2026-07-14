---
name: agentic-rag
description: Grounded library-internal Agentic RAG workflow for Zotero Web Library. Use when answering questions, generating literature matrix cells, or drafting review text from backend RAG tools or a provided Evidence Pack built from Zotero metadata, MinerU PDF chunks, notes, citations, figures, HTML, or writing materials. Enforce citation-backed answers and evidence insufficiency rules.
---

# Agentic RAG

## Core Rule

Answer from the active prompt's retrieved evidence, whether it arrives through tool calls or as an Evidence Pack. Do not invent papers, page numbers, experimental results, citations, or claims that are not supported by the provided evidence.

If evidence is missing or too weak, say that the current library evidence is insufficient and name the missing evidence type.

## Workflow

1. Read the user task and identify the output type: factual answer, analytical answer, comparison, matrix cell, or review-writing draft.
2. Inspect available evidence before drafting. If tools are available, use `search_evidence` for concise retrieval, `read_chunk_context` only when full local context is needed, and `list_scope_documents` to understand the current scope.
3. Use only evidence entries whose `source_type`, `item_key`, `chunk_id`, `note_id`, or `citation` fields support the claim.
4. Preserve citation markers from the Evidence Pack beside the claims they support.
5. Separate paper evidence, user notes, and model synthesis.
6. Keep uncertainty visible when sources disagree or the evidence is incomplete.

## Evidence Use

- Prefer chunk evidence for method details, results, limitations, ablations, definitions, and quotations.
- Prefer metadata evidence for title, authors, year, venue, DOI, tags, and bibliography facts.
- Prefer note evidence only for the user's own interpretation, reading status, or project-specific judgment.
- Use figure evidence only for visible figure/table/caption facts included in the Evidence Pack.
- Do not cite a source just because it is top-ranked; cite it only when its text supports the sentence.

## Output Rules

- For direct Q&A, answer concisely and include citations inline.
- For comparisons, group claims by paper or dimension and keep citations attached to each row or bullet.
- For matrix cells, return the requested cell value plus its citations; do not add unrelated narrative.
- For review writing, label synthesis as synthesis and retain citations on factual claims.
- If no evidence is found, return an evidence-insufficient answer instead of a general knowledge answer.

## References

Load these only when needed:

- `references/tool-contract.md`: Callable Agentic RAG tools, Evidence Pack fields, and internal retrieval-tool meanings.
- `references/retrieval-policy.md`: Task-specific retrieval and evidence selection policy.
- `references/citation-format.md`: Citation marker format and citation behavior.
