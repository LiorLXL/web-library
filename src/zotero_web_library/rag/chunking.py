from __future__ import annotations

import re
from dataclasses import dataclass


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"[ \t]+")


@dataclass
class TextChunk:
    chunk_type: str
    content: str
    section_title: str = ""
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
    buffer: list[str] = []

    def flush(chunk_type: str = "paragraph") -> None:
        nonlocal buffer
        content = clean_text("\n".join(buffer))
        buffer = []
        if content:
            chunks.append(
                TextChunk(
                    chunk_type=chunk_type,
                    content=content,
                    section_title=section_title,
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
            chunks.append(
                TextChunk(
                    chunk_type="heading",
                    content=section_title,
                    section_title=section_title,
                    section_level=section_level,
                )
            )
            continue
        if not line:
            flush()
            continue
        buffer.append(line)
        if sum(len(part) + 1 for part in buffer) >= max_chars:
            flush()
    flush()
    return chunks


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
