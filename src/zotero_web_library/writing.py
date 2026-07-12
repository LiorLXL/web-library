"""综述写作 (writing) 的本地存储、文献矩阵与导出。

AI 对话编排在 ``codex_agent.writing``（避免循环 import）。本模块只负责：
- 每文库本地文件：writing_state.json / outline.md / writing_section_mappings.json / survey.md / writing_sources.csv
- 文献矩阵值读取（聚合该文库下各知识库的矩阵结果，作为写作 CSV 与 mapping 的来源）
- 大纲叶子小节解析、章节-文献映射归一化与写入
- Markdown / CSV 导出
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .paths import app_data_dir, libraries_dir
from .utils import new_key, now_iso
from .zotero_adapter import ZoteroRepository

WRITING_STAGES = ["topic", "outline", "mapping", "draft"]
WRITING_STAGE_LABELS = {
    "topic": "拟定主题",
    "outline": "大纲生成",
    "mapping": "内容核对",
    "draft": "综述生成",
}

DEFAULT_MATRIX_FIELDS = [
    {"field_id": "research_question", "name": "研究问题", "rule": "概括论文试图解决的核心问题。"},
    {"field_id": "method", "name": "方法", "rule": "简述论文采用的方法/模型/框架。"},
    {"field_id": "dataset", "name": "数据/实验", "rule": "说明使用的数据集或实验设置。"},
    {"field_id": "result", "name": "主要结果", "rule": "列出关键结果或指标。"},
    {"field_id": "limitation", "name": "局限", "rule": "指出论文的不足或开放问题。"},
]


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def normalize_writing_stage(value: str | None) -> str:
    return value if value in WRITING_STAGES else WRITING_STAGES[0]


def _writing_dir(library: dict[str, Any]) -> Path:
    path = libraries_dir() / str(library.get("library_id", "library")) / "writing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def codex_config_for(library: dict[str, Any]) -> dict[str, Any]:
    """延迟导入 web 的 Codex 配置构造，避免循环依赖。"""
    from .web import api_config_codex_for_library

    return api_config_codex_for_library(str(library.get("library_id")))


# --------------------------------------------------------------------------- #
# relative paths
# --------------------------------------------------------------------------- #
def writing_sources_relative_path(library_id: str) -> str:
    return f"libraries/{library_id}/writing/writing_sources.csv"


def writing_outline_relative_path(library_id: str) -> str:
    return f"libraries/{library_id}/writing/outline.md"


def writing_survey_relative_path(library_id: str) -> str:
    return f"libraries/{library_id}/writing/survey.md"


def writing_section_mappings_relative_path(library_id: str) -> str:
    return f"libraries/{library_id}/writing/writing_section_mappings.json"


def writing_dir_path(library: dict[str, Any]) -> Path:
    return _writing_dir(library)


def writing_sources_path(library: dict[str, Any]) -> Path:
    return _writing_dir(library) / "writing_sources.csv"


def writing_outline_path(library: dict[str, Any]) -> Path:
    return _writing_dir(library) / "outline.md"


def writing_survey_path(library: dict[str, Any]) -> Path:
    return _writing_dir(library) / "survey.md"


def writing_section_mappings_path(library: dict[str, Any]) -> Path:
    return _writing_dir(library) / "writing_section_mappings.json"


# --------------------------------------------------------------------------- #
# writing state
# --------------------------------------------------------------------------- #
def load_writing_state(library: dict[str, Any]) -> dict[str, Any]:
    state = _read_json(_writing_dir(library) / "writing_state.json", {})
    state.setdefault("stage", "topic")
    state.setdefault("topic", "")
    state.setdefault("selected_paper_keys", [])
    return state


def save_writing_state(library: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = now_iso()
    _write_json(_writing_dir(library) / "writing_state.json", state)
    return state


# --------------------------------------------------------------------------- #
# outline
# --------------------------------------------------------------------------- #
def load_outline(library: dict[str, Any]) -> str:
    path = _writing_dir(library) / "outline.md"
    return path.read_text(encoding="utf-8") if path.exists() else default_writing_outline()


def save_outline(library: dict[str, Any], text: str) -> None:
    (_writing_dir(library) / "outline.md").write_text(text or "", encoding="utf-8")


def default_writing_outline() -> str:
    return "\n".join(
        [
            "# 综述标题",
            "",
            "## 1. 研究背景",
            "- 说明研究主题、问题来源和综述意义。",
            "",
            "## 2. 相关工作脉络",
            "- 按任务、方法或时间线组织已有文献。",
            "",
            "## 3. 方法与系统分析",
            "- 比较代表论文的方法思路、实验设置和核心结论。",
            "",
            "## 4. 挑战与展望",
            "- 总结现有不足，提出未来研究方向。",
        ]
    )


def outline_number_prefix(title: str) -> str:
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[\.、]\s+|\s+)", title.strip())
    return match.group(1) if match else ""


def parse_outline_sections(outline_text: str) -> list[dict[str, Any]]:
    raw_sections: list[dict[str, Any]] = []
    for line in (outline_text or "").splitlines():
        stripped = line.strip()
        title = ""
        heading_level = 0
        if stripped.startswith("#"):
            heading_level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
        elif re.match(r"^\d+(?:\.\d+)*[\.、\s]+", stripped):
            title = stripped
        if not title:
            continue
        slug = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]+", "_", title).strip("_").lower() or f"section-{len(raw_sections) + 1}"
        raw_sections.append(
            {
                "section_id": slug,
                "title": title,
                "order": len(raw_sections) + 1,
                "heading_level": heading_level,
                "number_prefix": outline_number_prefix(title),
            }
        )
    leaf_sections: list[dict[str, Any]] = []
    for index, section in enumerate(raw_sections):
        number_prefix = section.get("number_prefix") or ""
        has_child = False
        for later in raw_sections[index + 1 :]:
            later_number = later.get("number_prefix") or ""
            if number_prefix and later_number.startswith(f"{number_prefix}."):
                has_child = True
                break
        if not has_child:
            leaf_sections.append(section)
    return leaf_sections


# --------------------------------------------------------------------------- #
# survey (draft)
# --------------------------------------------------------------------------- #
def outline_number_prefix(title: str) -> str:
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[\.、．)\]）]?\s+|\s+)", title.strip())
    return match.group(1) if match else ""


def _outline_section_level(title: str, heading_level: int) -> tuple[int, str]:
    stripped = title.strip()
    if heading_level > 0:
        return heading_level, "markdown"
    number_prefix = outline_number_prefix(stripped)
    if number_prefix:
        return number_prefix.count(".") + 1, "arabic"
    if re.match(r"^[一二三四五六七八九十百千]+[、.．]\s*", stripped):
        return 1, "zh_root"
    if re.match(r"^[（(][一二三四五六七八九十百千0-9]+[)）]\s*", stripped):
        return 2, "bracketed"
    return 0, ""


def _has_child_section(raw_sections: list[dict[str, Any]], index: int) -> bool:
    section = raw_sections[index]
    current_number = str(section.get("number_prefix") or "")
    current_level = int(section.get("outline_level") or 0)
    current_kind = str(section.get("outline_kind") or "")
    current_heading_level = int(section.get("heading_level") or 0)

    for later in raw_sections[index + 1 :]:
        later_heading_level = int(later.get("heading_level") or 0)
        later_level = int(later.get("outline_level") or 0)
        later_kind = str(later.get("outline_kind") or "")
        later_number = str(later.get("number_prefix") or "")

        if current_number:
            if later_number.startswith(f"{current_number}."):
                return True
            continue

        if current_heading_level > 0:
            if later_heading_level <= 0:
                continue
            if later_heading_level <= current_heading_level:
                return False
            return True

        if current_level > 0:
            if later_level <= 0:
                continue
            if current_kind in {"zh_root", "bracketed"} and later_kind and later_kind != current_kind:
                if later_level <= current_level:
                    return False
                return True
            if later_level <= current_level:
                return False
            return True

    return False


def parse_outline_sections(outline_text: str) -> list[dict[str, Any]]:
    raw_sections: list[dict[str, Any]] = []
    for line in (outline_text or "").splitlines():
        stripped = line.strip()
        title = ""
        heading_level = 0
        if stripped.startswith("#"):
            heading_level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
        elif re.match(r"^\d+(?:\.\d+)*[\.、．)\]）]?\s+", stripped):
            title = stripped
        elif re.match(r"^[一二三四五六七八九十百千]+[、.．]\s*", stripped):
            title = stripped
        elif re.match(r"^[（(][一二三四五六七八九十百千0-9]+[)）]\s*", stripped):
            title = stripped
        if not title:
            continue
        outline_level, outline_kind = _outline_section_level(title, heading_level)
        slug = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]+", "_", title).strip("_").lower() or f"section-{len(raw_sections) + 1}"
        raw_sections.append(
            {
                "section_id": slug,
                "title": title,
                "order": len(raw_sections) + 1,
                "heading_level": heading_level,
                "number_prefix": outline_number_prefix(title),
                "outline_level": outline_level,
                "outline_kind": outline_kind,
            }
        )
    has_nested_markdown = any(int(section.get("heading_level") or 0) >= 2 for section in raw_sections)
    leaf_sections: list[dict[str, Any]] = []
    for index, section in enumerate(raw_sections):
        if has_nested_markdown and int(section.get("heading_level") or 0) == 1:
            continue
        if not _has_child_section(raw_sections, index):
            leaf_sections.append(
                {
                    "section_id": section["section_id"],
                    "title": section["title"],
                    "order": section["order"],
                    "heading_level": section["heading_level"],
                    "number_prefix": section["number_prefix"],
                }
            )
    return leaf_sections


def load_survey(library: dict[str, Any]) -> str:
    path = _writing_dir(library) / "survey.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_survey(library: dict[str, Any], text: str) -> None:
    (_writing_dir(library) / "survey.md").write_text(text or "", encoding="utf-8")


# --------------------------------------------------------------------------- #
# section mappings (list form)
# --------------------------------------------------------------------------- #
def load_mappings(library: dict[str, Any]) -> dict[str, Any]:
    return _read_json(
        _writing_dir(library) / "writing_section_mappings.json",
        {"sections": [], "papers": [], "mappings": []},
    )


def save_mappings(library: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "sections": data.get("sections", []),
        "papers": data.get("papers", []),
        "mappings": data.get("mappings", []),
        "updated_at": now_iso(),
    }
    _write_json(_writing_dir(library) / "writing_section_mappings.json", payload)
    return payload


def normalize_section_mapping(
    library: dict[str, Any],
    section: dict[str, Any],
    value: dict[str, Any],
    *,
    paper_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    paper_key = str(value.get("paper_key") or value.get("paper_id") or "").strip()
    if paper_key not in paper_lookup:
        return None
    section_id = str(section.get("section_id") or "").strip()
    paper = paper_lookup[paper_key]
    return {
        "mapping_id": f"{section_id}__{paper_key}",
        "section_id": section_id,
        "section_title": str(section.get("title") or ""),
        "section_order": int(section.get("order") or 0),
        "paper_id": paper_key,
        "paper_key": paper_key,
        "paper_title": str(paper.get("title") or value.get("paper_title") or ""),
        "citation_role": str(value.get("citation_role") or "辅助证据").strip(),
        "writing_note": str(value.get("writing_note") or "").strip(),
        "evidence_detail": str(value.get("evidence_detail") or "").strip(),
        "missing_detail": str(value.get("missing_detail") or "").strip(),
        "updated_at": now_iso(),
    }


def replace_section_mappings(library: dict[str, Any], section: dict[str, Any], raw_mappings: Any) -> list[dict[str, Any]]:
    sections = parse_outline_sections(load_outline(library))
    valid_section_ids = {item["section_id"] for item in sections}
    section_id = str(section.get("section_id") or "")
    if section_id not in valid_section_ids:
        return load_mappings(library).get("mappings", [])
    papers = paper_list(library)
    paper_lookup = {str(p.get("key")): p for p in papers}
    new_rows: list[dict[str, Any]] = []
    if isinstance(raw_mappings, list):
        for value in raw_mappings:
            if not isinstance(value, dict):
                continue
            normalized = normalize_section_mapping(library, section, value, paper_lookup=paper_lookup)
            if normalized:
                new_rows.append(normalized)
    existing = [row for row in load_mappings(library).get("mappings", []) if row.get("section_id") != section_id]
    merged = [*existing, *new_rows]
    merged.sort(key=lambda row: (int(row.get("section_order") or 0), str(row.get("paper_title") or "")))
    save_mappings(
        library,
        {
            "sections": sections,
            "papers": [{"paper_id": str(p.get("key")), "title": str(p.get("title") or "")} for p in papers],
            "mappings": merged,
        },
    )
    return merged


def writing_mapping_payload(library: dict[str, Any]) -> dict[str, Any]:
    state = load_writing_state(library)
    papers = [{"paper_id": str(p.get("key")), "title": str(p.get("title") or "")} for p in selected_writing_papers(library)]
    return {
        "sections": parse_outline_sections(load_outline(library)),
        "papers": papers,
        "mappings": load_mappings(library).get("mappings", []),
        "state": state,
    }


# --------------------------------------------------------------------------- #
# papers + matrix
# --------------------------------------------------------------------------- #
def _creator_display(item: dict[str, Any]) -> str:
    creators = item.get("creators") if isinstance(item.get("creators"), list) else []
    names = [str(c.get("name") or "").strip() for c in creators if isinstance(c, dict) and str(c.get("name") or "").strip()]
    return " / ".join(names)


def paper_list(library: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        items = ZoteroRepository(library).items()
    except Exception:  # noqa: BLE001
        return []
    papers: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("itemType") or "")
        if item_type in {"attachment", "note", "annotation"}:
            continue
        papers.append(
            {
                "key": str(item.get("key") or ""),
                "title": str(item.get("title") or "未命名文献"),
                "authors": _creator_display(item),
                "year": str(item.get("year") or ""),
                "venue": str(item.get("venue") or ""),
            }
        )
    return papers


def _matrix_root_for_library(library: dict[str, Any]) -> Path:
    library_id = str(library.get("library_id") or "library")
    safe_lib = re.sub(r"[^A-Za-z0-9_]", "_", library_id)
    return app_data_dir() / "libraries" / safe_lib / "matrix"


def _matrix_kb_fields_files(library: dict[str, Any]) -> list[Path]:
    """收集该文库所有知识库下的 fields.json 路径。"""
    root = _matrix_root_for_library(library)
    if not root.exists():
        return []
    result: list[Path] = []
    for kb_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        fields_path = kb_dir / "fields.json"
        if fields_path.exists():
            result.append(fields_path)
    return result


def matrix_fields_for_library(library: dict[str, Any]) -> list[dict[str, Any]]:
    """从该文库所有知识库的 fields.json 中聚合字段定义；找不到时回退到默认字段。"""
    seen: dict[str, dict[str, Any]] = {}
    for path in _matrix_kb_fields_files(library):
        fields_list: Any = _read_json(path, [])
        if not isinstance(fields_list, list):
            continue
        for entry in fields_list:
            if not isinstance(entry, dict):
                continue
            fid = str(entry.get("field_id") or "")
            name = str(entry.get("name") or "")
            if not fid or not name:
                continue
            if fid not in seen:
                seen[fid] = {
                    "field_id": fid,
                    "name": name,
                    "rule": str(entry.get("rule") or ""),
                }
    if seen:
        return list(seen.values())
    return list(DEFAULT_MATRIX_FIELDS)


def _matrix_dir(library_id: str, kb_id: str) -> Path:
    safe_lib = re.sub(r"[^A-Za-z0-9_]", "_", str(library_id or "library"))
    safe_kb = re.sub(r"[^A-Za-z0-9_]", "_", str(kb_id or "kb"))
    return app_data_dir() / "libraries" / safe_lib / "matrix" / safe_kb


def _matrix_item_path(library_id: str, kb_id: str, item_key: str) -> Path:
    safe_item = re.sub(r"[^A-Za-z0-9_]", "_", str(item_key or "item"))
    return _matrix_dir(library_id, kb_id) / "items" / f"{safe_item}.json"


def _matrix_field_name_map(library: dict[str, Any]) -> dict[str, str]:
    """构建 field_id -> 显示名 的映射（从所有知识库 fields.json 聚合）。"""
    name_map: dict[str, str] = {}
    for path in _matrix_kb_fields_files(library):
        fields_list: Any = _read_json(path, [])
        if not isinstance(fields_list, list):
            continue
        for entry in fields_list:
            if not isinstance(entry, dict):
                continue
            fid = str(entry.get("field_id") or "")
            display_name = str(entry.get("name") or "")
            if fid and display_name:
                name_map.setdefault(fid, display_name)
    # 补充默认字段的映射
    for d in DEFAULT_MATRIX_FIELDS:
        name_map.setdefault(d["field_id"], d["name"])
    return name_map


def reading_matrix_values(library: dict[str, Any], item_key: str) -> dict[str, str]:
    """聚合该文库下所有知识库中某文献的矩阵字段值，返回 {显示名: 值}。"""
    result: dict[str, str] = {}
    matrix_root = _matrix_root_for_library(library)
    if not matrix_root.exists():
        return result
    name_map = _matrix_field_name_map(library)
    for kb_dir in sorted(p for p in matrix_root.iterdir() if p.is_dir()):
        path = kb_dir / "items" / f"{re.sub(r'[^A-Za-z0-9_]', '_', str(item_key))}.json"
        if not path.exists():
            continue
        data = _read_json(path, {})
        # 兼容两种格式：旧格式用 "fields"，新格式用 "values"
        fields = data.get("values") if isinstance(data.get("values"), dict) else data.get("fields")
        if not isinstance(fields, dict):
            continue
        for fid, value in fields.items():
            text = value.get("value") if isinstance(value, dict) else str(value)
            if text:
                display_name = name_map.get(fid, fid)
                result[display_name] = str(text)
    return result


def matrix_by_paper(library: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for paper in paper_list(library):
        key = str(paper.get("key"))
        out[key] = reading_matrix_values(library, key)
    return out


def selected_writing_papers(library: dict[str, Any]) -> list[dict[str, Any]]:
    state = load_writing_state(library)
    selected_ids = set(state.get("selected_paper_keys") or [])
    return [paper for paper in paper_list(library) if paper.get("key") in selected_ids]


def selected_writing_paper_context(library: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paper in selected_writing_papers(library):
        key = str(paper.get("key") or "")
        rows.append(
            {
                "paper_id": key,
                "paper_key": key,
                "title": str(paper.get("title") or ""),
                "authors": paper.get("authors") or "",
                "year": paper.get("year") or "",
                "venue": paper.get("venue") or "",
                "matrix": reading_matrix_values(library, key),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# writing_sources.csv
# --------------------------------------------------------------------------- #
def load_writing_csv(library: dict[str, Any]) -> str:
    path = _writing_dir(library) / "writing_sources.csv"
    if not path.exists():
        refresh_writing_csv(library)
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def refresh_writing_csv(library: dict[str, Any]) -> str:
    state = load_writing_state(library)
    selected = set(state.get("selected_paper_keys") or [])
    matrix_fields = matrix_fields_for_library(library)
    base_fields = ["paper_key", "title", "authors", "year", "venue"]
    matrix_columns = [f"matrix_{field['name']}" for field in matrix_fields]
    output_fields = [*base_fields, *matrix_columns]
    rows: list[dict[str, str]] = []
    for paper in paper_list(library):
        key = str(paper.get("key"))
        if key not in selected:
            continue
        values = reading_matrix_values(library, key)
        row = {
            "paper_key": key,
            "title": str(paper.get("title") or ""),
            "authors": paper.get("authors") or "",
            "year": paper.get("year") or "",
            "venue": paper.get("venue") or "",
        }
        for field in matrix_fields:
            row[f"matrix_{field['name']}"] = values.get(field["name"], "")
        rows.append(row)

    path = _writing_dir(library) / "writing_sources.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)
    csv_text = path.read_text(encoding="utf-8-sig")
    state["csv_hash"] = text_hash(csv_text)
    state["updated_at"] = now_iso()
    save_writing_state(library, state)
    return writing_sources_relative_path(str(library.get("library_id", "library")))


# --------------------------------------------------------------------------- #
# ensure files
# --------------------------------------------------------------------------- #
def ensure_writing_files(library: dict[str, Any]) -> dict[str, Any]:
    state_path = _writing_dir(library) / "writing_state.json"
    state = load_writing_state(library)
    if not state_path.exists():
        state = {
            "stage": "topic",
            "selected_paper_keys": [],
            "topic": "",
            "csv_hash": "",
            "outline_hash": "",
            "draft_hash": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        save_writing_state(library, state)

    outline_path = _writing_dir(library) / "outline.md"
    if not outline_path.exists():
        outline_path.write_text(default_writing_outline(), encoding="utf-8")

    survey_path = _writing_dir(library) / "survey.md"
    if not survey_path.exists():
        survey_path.write_text("# 综述草稿\n\n请在右侧对话中让光牍生成或修改综述正文。\n", encoding="utf-8")

    mappings_path = _writing_dir(library) / "writing_section_mappings.json"
    if not mappings_path.exists():
        _write_json(mappings_path, {"sections": [], "papers": [], "mappings": []})

    refresh_writing_csv(library)
    return load_writing_state(library)


# --------------------------------------------------------------------------- #
# chat messages / chat state (persisted)
# --------------------------------------------------------------------------- #
def load_writing_chat(library: dict[str, Any]) -> list[dict[str, Any]]:
    return _read_json(_writing_dir(library) / "writing_chat.json", [])


def append_writing_chat_message(library: dict[str, Any], message: dict[str, Any]) -> None:
    messages = load_writing_chat(library)
    messages.append(message)
    _write_json(_writing_dir(library) / "writing_chat.json", messages[-200:])


def load_writing_chat_state(library: dict[str, Any]) -> dict[str, Any]:
    return _read_json(_writing_dir(library) / "writing_chat_state.json", {})


def save_writing_chat_state(library: dict[str, Any], state: dict[str, Any]) -> None:
    _write_json(_writing_dir(library) / "writing_chat_state.json", state)


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def build_markdown_export(library: dict[str, Any]) -> str:
    state = load_writing_state(library)
    outline = load_outline(library)
    survey = load_survey(library)
    papers = paper_list(library)
    parts = [f"# 综述：{state.get('topic') or '未命名主题'}", ""]
    if outline.strip():
        parts.append("## 大纲")
        parts.append(outline.strip())
        parts.append("")
    if survey.strip():
        parts.append(survey.strip())
        parts.append("")
    if papers:
        parts.append("## 参考文献")
        for index, paper in enumerate(papers, start=1):
            parts.append(f"[{index}] {paper['title']}（{paper.get('authors','')}，{paper.get('year','')}，{paper.get('venue','')}）")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def build_csv_export(library: dict[str, Any]) -> str:
    mappings = load_mappings(library)
    papers_by_key = {p["paper_id"]: p for p in mappings.get("papers", [])}
    rows = ["section,paper_key,paper_title,citation_role,writing_note,evidence_detail,missing_detail"]
    for sec in mappings.get("sections", []):
        for entry in mappings.get("mappings", []):
            if entry.get("section_id") != sec.get("section_id"):
                continue
            paper = papers_by_key.get(entry.get("paper_key"), {})
            rows.append(
                ",".join(
                    _csv_cell(value)
                    for value in [
                        sec.get("title", ""),
                        entry.get("paper_key", ""),
                        paper.get("title", ""),
                        entry.get("citation_role", ""),
                        entry.get("writing_note", ""),
                        entry.get("evidence_detail", ""),
                        entry.get("missing_detail", ""),
                    ]
                )
            )
    return "\n".join(rows) + "\n"


def _csv_cell(value: str) -> str:
    text = str(value or "").replace('"', '""')
    if any(ch in text for ch in [",", '"', "\n"]):
        return f'"{text}"'
    return text
