from __future__ import annotations

import os
from pathlib import Path


AGENTIC_RAG_SKILL_FILES = (
    "SKILL.md",
    "references/tool-contract.md",
    "references/retrieval-policy.md",
    "references/citation-format.md",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def agentic_rag_skill_dir() -> Path:
    override = os.environ.get("WEB_LIBRARY_AGENTIC_RAG_SKILL_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repository_root() / "skills" / "agentic-rag"


def agentic_rag_skill_path() -> Path:
    return agentic_rag_skill_dir() / "SKILL.md"


def load_agentic_rag_skill_bundle() -> str:
    root = agentic_rag_skill_dir()
    missing = [relative for relative in AGENTIC_RAG_SKILL_FILES if not (root / relative).is_file()]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(f"Agentic RAG skill 不完整，缺少文件：{joined}（目录：{root}）")

    sections: list[str] = []
    for relative in AGENTIC_RAG_SKILL_FILES:
        content = (root / relative).read_text(encoding="utf-8")
        if relative == "SKILL.md":
            content = _strip_frontmatter(content)
        sections.append(f"## Skill source: {relative}\n\n{content.strip()}")
    return "# Injected Agentic RAG Skill Bundle\n\n" + "\n\n".join(sections)


def _strip_frontmatter(content: str) -> str:
    text = str(content or "")
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip()
    return text
