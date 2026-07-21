from __future__ import annotations

import re
from dataclasses import dataclass


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"[ \t]+")
FIGURE_CAPTION_RE = re.compile(r"^(?:fig(?:ure)?\.?|图|图表)\s*\d+[\s:：.、-]", re.IGNORECASE)
TABLE_LINE_RE = re.compile(r"^\s*\|?.*\|.*\|?\s*$")

SECTION_TYPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("abstract", re.compile(r"^(?:abstract|summary|摘要|概要)$", re.IGNORECASE)),
    (
        "method",
        re.compile(
            r"(?:method(?:s|ology)?|approach|materials?\s+and\s+methods?|implementation|方法|模型|技术路线)",
            re.IGNORECASE,
        ),
    ),
    (
        "results",
        re.compile(
            r"(?:experiment(?:s|al)?|evaluation|results?|discussion|ablation|实验|评估|结果|消融)",
            re.IGNORECASE,
        ),
    ),
    ("references", re.compile(r"^(?:references?|bibliography|参考文献)$", re.IGNORECASE)),
)


@dataclass
class TextChunk:
    chunk_type: str
    content: str
    section_title: str = ""
    section_path: str = ""
    section_level: int = 0
    estimated_page: int | None = None


def clean_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    compact: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            if not blank_seen and compact:
                compact.append("")
            blank_seen = True
            continue
        compact.append(line)
        blank_seen = False
    return "\n".join(compact).strip()


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", str(value or ""))
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|table|section|article)>", "\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return clean_text(text)


def chunk_markdown(text: str, *, max_chars: int = 2600) -> list[TextChunk]:
    clean = clean_text(text)
    if not clean:
        return []
    chunks: list[TextChunk] = []
    section_title = ""
    section_level = 0
    heading_stack: dict[int, str] = {}
    buffer: list[str] = []
    buffer_type = ""

    def current_path() -> str:
        return " > ".join(heading_stack[level] for level in sorted(heading_stack))

    def flush(chunk_type: str = "") -> None:
        nonlocal buffer, buffer_type
        content = clean_text("\n".join(buffer))
        buffer = []
        resolved_type = chunk_type or buffer_type or _section_chunk_type(section_title)
        buffer_type = ""
        if content:
            for part in _split_block(content, max_chars=max_chars):
                chunks.append(
                    TextChunk(
                        chunk_type=resolved_type,
                        content=part,
                        section_title=section_title,
                        section_path=current_path(),
                        section_level=section_level,
                    )
                )

    for raw_line in clean.split("\n"):
        line = raw_line.strip()
        heading = HEADING_RE.match(line)
        if heading:
            flush()
            section_level = len(heading.group(1))
            section_title = heading.group(2).strip()
            for level in [value for value in heading_stack if value >= section_level]:
                heading_stack.pop(level, None)
            heading_stack[section_level] = section_title
            chunks.append(
                TextChunk(
                    chunk_type="heading",
                    content=section_title,
                    section_title=section_title,
                    section_path=current_path(),
                    section_level=section_level,
                )
            )
            continue
        if not line:
            flush()
            continue

        line_type = _line_chunk_type(line, section_title=section_title)
        if buffer and line_type != buffer_type:
            flush()
        buffer_type = line_type
        buffer.append(line)
        if sum(len(part) + 1 for part in buffer) >= max_chars:
            flush()
    flush()
    return chunks


def _section_chunk_type(section_title: str) -> str:
    title = str(section_title or "").strip()
    for chunk_type, pattern in SECTION_TYPE_PATTERNS:
        if pattern.search(title):
            return chunk_type
    return "paragraph"


def _line_chunk_type(line: str, *, section_title: str) -> str:
    if FIGURE_CAPTION_RE.match(line):
        return "figure_caption"
    if TABLE_LINE_RE.match(line):
        return "table"
    return _section_chunk_type(section_title)


def _split_block(content: str, *, max_chars: int) -> list[str]:
    limit = max(200, int(max_chars or 2600))
    if len(content) <= limit:
        return [content]
    parts: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining.strip())
            break
        split_at = max(remaining.rfind("\n", 0, limit), remaining.rfind("。", 0, limit), remaining.rfind(". ", 0, limit))
        if split_at < limit // 2:
            split_at = limit
        else:
            split_at += 1
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return [part for part in parts if part]


def chunk_plain_text(text: str, *, chunk_type: str = "paragraph", max_chars: int = 2200) -> list[TextChunk]:
    clean = clean_text(text)
    if not clean:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", clean) if part.strip()]
    chunks: list[TextChunk] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs or [clean]:
        if current and current_len + len(paragraph) > max_chars:
            chunks.append(TextChunk(chunk_type=chunk_type, content=clean_text("\n\n".join(current))))
            current = []
            current_len = 0
        if len(paragraph) > max_chars:
            if current:
                chunks.append(TextChunk(chunk_type=chunk_type, content=clean_text("\n\n".join(current))))
                current = []
                current_len = 0
            for start in range(0, len(paragraph), max_chars):
                chunks.append(TextChunk(chunk_type=chunk_type, content=paragraph[start : start + max_chars].strip()))
            continue
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append(TextChunk(chunk_type=chunk_type, content=clean_text("\n\n".join(current))))
    return [chunk for chunk in chunks if chunk.content]
