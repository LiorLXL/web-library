from __future__ import annotations

import re
from pathlib import Path

import pytest

from zotero_web_library.agentic_rag_skill import (
    AGENTIC_RAG_SKILL_FILES,
    agentic_rag_skill_path,
    load_agentic_rag_skill_bundle,
)
from zotero_web_library.codex_agent.runner import agentic_rag_skill_path as codex_agentic_rag_skill_path
from zotero_web_library.rag.agent.prompts import build_system_prompt
from zotero_web_library.rag.agent.tools import TOOL_SCHEMAS


def test_agentic_rag_skill_bundle_contains_phase_1_contracts() -> None:
    bundle = load_agentic_rag_skill_bundle()

    assert bundle.startswith("# Injected Agentic RAG Skill Bundle")
    assert all(f"Skill source: {relative}" in bundle for relative in AGENTIC_RAG_SKILL_FILES)
    assert "query_lineage" in bundle
    assert "parent_context" in bundle
    assert "reranker_failed" in bundle
    assert "retrieval rank and reranker scores" in bundle
    assert "does not expose `read_matrix` or `compare_matrix`" in bundle


def test_function_calling_prompt_injects_real_skill_bundle() -> None:
    prompt = build_system_prompt(max_tool_iterations=5)

    assert "<agentic_rag_skill>" in prompt
    assert "Injected Agentic RAG Skill Bundle" in prompt
    assert "search_evidence(query, mode=\"hybrid\", top_k=8, filters={...})" in prompt
    assert "最多进行 5 轮模型调用" in prompt


def test_skill_loader_reports_missing_required_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skill_dir = tmp_path / "agentic-rag"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: agentic-rag\ndescription: test\n---\n", encoding="utf-8")
    monkeypatch.setenv("WEB_LIBRARY_AGENTIC_RAG_SKILL_DIR", str(skill_dir))

    with pytest.raises(FileNotFoundError, match="Agentic RAG skill 不完整") as exc_info:
        load_agentic_rag_skill_bundle()

    assert "references/tool-contract.md" in str(exc_info.value)


def test_codex_and_function_calling_runtimes_share_skill_path() -> None:
    assert codex_agentic_rag_skill_path() == agentic_rag_skill_path()
    assert agentic_rag_skill_path().is_file()


def test_search_evidence_schema_exposes_scoped_phase_1_filters() -> None:
    schema = next(item["function"] for item in TOOL_SCHEMAS if item["function"]["name"] == "search_evidence")
    filters = schema["parameters"]["properties"]["filters"]["properties"]

    assert {"year_from", "year_to", "authors", "venues", "item_keys", "chunk_types"} <= set(filters)
    assert {"abstract", "method", "results", "table", "figure_caption"} <= set(filters["chunk_types"]["items"]["enum"])


def test_skill_frontmatter_and_openai_interface_are_valid() -> None:
    content = agentic_rag_skill_path().read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert match is not None
    fields = {
        key.strip(): value.strip()
        for line in match.group(1).splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }

    assert set(fields) == {"name", "description"}
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    assert fields["name"] == "agentic-rag"
    assert 1 <= len(fields["description"]) <= 1024
    assert "<" not in fields["description"] and ">" not in fields["description"]

    interface = (agentic_rag_skill_path().parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert 'display_name: "Agentic RAG"' in interface
    assert "$agentic-rag" in interface
