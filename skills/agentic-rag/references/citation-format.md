# Citation Format

Agentic RAG citation markers are internal evidence markers. They are not final bibliography strings.

## Marker Forms

- Metadata: `[<item_key>:metadata]`
- Chunk: `[<item_key>:<chunk_id>]`
- Note: `[<item_key>:note:<note_id>]`
- Figure or table: `[<item_key>:figure:<asset_id>]`
- Citation record: `[<item_key>:citation:<citation_id>]`

`parent_chunk_id` is never a citation marker. Parent section text returned by `read_chunk_context` keeps the target chunk's supplied citation.

## Rules

- Preserve markers exactly as provided in the Evidence Pack.
- Place markers next to the claim they support.
- Use multiple markers when a claim synthesizes multiple sources.
- Do not create new markers.
- Do not cite evidence that does not support the claim.
- Cite a `table` or `figure_caption` text chunk with its supplied chunk marker. Use a figure/table marker only when an actual figure/table evidence object provides it.
- Do not infer image pixels, chart values, layout, or trends from a caption-only chunk.
- If the user requests formal references, say that final bibliography formatting should be generated from Zotero citation export, not from these internal markers.

## Examples

Supported concise answer:

```text
The method uses action chunking to improve robust manipulation across longer-horizon actions [ITEM0001:chunk-abc123].
```

Insufficient evidence answer:

```text
The current Evidence Pack does not include experimental results for this claim, so I cannot verify it from the selected knowledge base.
```
