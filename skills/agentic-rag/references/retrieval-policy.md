# Retrieval Policy

Use the Evidence Pack according to task type.

## Factual Q&A

- Use metadata evidence for bibliographic facts.
- Use chunk evidence for content facts.
- If the answer needs page, section, method detail, or result detail and no chunk supports it, mark the answer as insufficient.

## Analytical Q&A

- Prefer multiple chunk sources from the same paper when summarizing a method.
- Prefer evidence from several papers when making field-level claims.
- Separate what the papers state from your synthesis.

## Comparison

- Compare only dimensions that have evidence for at least two papers.
- If a paper lacks evidence for a dimension, mark that cell as not found instead of inferring.

## Literature Matrix

- Fill the requested field only.
- Keep the cell concise.
- Attach citation markers inside the cell or alongside the cell value.
- Do not mix unsupported background knowledge into matrix cells.

## Review Writing

- Treat Evidence Pack entries as source material, not as final prose.
- Write synthesis in your own words, but keep citations attached to factual claims.
- Use user notes as reading/project context, not as paper evidence unless clearly marked.

## Insufficient Evidence

Say evidence is insufficient when:

- `results` is empty.
- Results are only metadata but the user asks for methods, experiments, limitations, or findings.
- Evidence does not mention the requested concept.
- Citations would be attached to claims not stated in the evidence.
