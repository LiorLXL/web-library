from __future__ import annotations

from pathlib import Path

import pytest

import zotero_web_library.codex_agent.writing as agent_writing
import zotero_web_library.writing as writing
from zotero_web_library.sources import create_local_copy


def test_ensure_writing_files_starts_with_empty_selection(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)

    state = writing.ensure_writing_files(library)

    assert state["selected_paper_keys"] == []
    csv_text = writing.load_writing_csv(library)
    csv_lines = [line for line in csv_text.splitlines() if line.strip()]
    assert len(csv_lines) == 1
    assert "paper_key" in csv_lines[0]
    assert "ITEM0001" not in csv_text


def test_frontend_requires_explicit_knowledge_base_selection() -> None:
    root = Path(__file__).resolve().parents[1]
    writing_html = (root / "src" / "zotero_web_library" / "templates" / "writing.html").read_text(encoding="utf-8")
    writing_js = (root / "src" / "zotero_web_library" / "static" / "writing.js").read_text(encoding="utf-8")

    assert "请选择知识库" in writing_html
    assert 'let currentKbId = "";' in writing_js


def test_writing_prompt_uses_absolute_paths_and_current_writing_dir(
    zotero_fixture: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEB_LIBRARY_DATA_DIR", str(tmp_path / "app-data"))
    library = create_local_copy(zotero_fixture)
    writing.ensure_writing_files(library)

    writing_dir = str(writing.writing_dir_path(library).resolve())
    csv_path = str(writing.writing_sources_path(library).resolve())
    outline_path = str(writing.writing_outline_path(library).resolve())
    survey_path = str(writing.writing_survey_path(library).resolve())
    mapping_path = str(writing.writing_section_mappings_path(library).resolve())

    prompt = agent_writing.build_writing_prompt_v2(
        stage="outline",
        user_question="Generate an outline",
        writing_dir=writing_dir,
        csv_path=csv_path,
        outline_path=outline_path,
        survey_path=survey_path,
        mapping_path=mapping_path,
        selected_topic="test topic",
        include_context=True,
        outline_changed=False,
        draft_changed=False,
    )

    assert writing_dir in prompt
    assert csv_path in prompt
    assert outline_path in prompt
    assert mapping_path not in prompt
    assert survey_path not in prompt
    assert "libraries/" not in prompt

    legacy_prompt = agent_writing.build_writing_prompt(
        stage="mapping",
        user_question="Map papers to sections",
        writing_dir=writing_dir,
        csv_path=csv_path,
        outline_path=outline_path,
        survey_path=survey_path,
        mapping_path=mapping_path,
        selected_topic="test topic",
        include_context=True,
        outline_changed=False,
        draft_changed=False,
        library_id=str(library.get("library_id") or ""),
    )

    assert writing_dir in legacy_prompt
    assert csv_path in legacy_prompt
    assert outline_path in legacy_prompt
    assert mapping_path in legacy_prompt
    assert "libraries/" not in legacy_prompt


def test_parse_outline_sections_supports_markdown_hierarchy_without_title_card() -> None:
    sections = writing.parse_outline_sections(
        "\n".join(
            [
                "# Review Title",
                "",
                "## Background",
                "## Methods",
                "### Policy Learning",
                "### Data Curation",
                "## Conclusion",
            ]
        )
    )

    assert [section["title"] for section in sections] == [
        "Background",
        "Policy Learning",
        "Data Curation",
        "Conclusion",
    ]


def test_parse_outline_sections_supports_chinese_outline_styles() -> None:
    sections = writing.parse_outline_sections(
        "\n".join(
            [
                "# 综述标题",
                "",
                "## 一、研究背景",
                "### （一）问题定义",
                "### （二）研究意义",
                "## 二、方法分类",
            ]
        )
    )

    assert [section["title"] for section in sections] == [
        "（一）问题定义",
        "（二）研究意义",
        "二、方法分类",
    ]
