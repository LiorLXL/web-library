from __future__ import annotations

from pathlib import Path


def test_frontend_contains_refined_interaction_hooks() -> None:
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "src" / "zotero_web_library" / "static" / "app.js").read_text(encoding="utf-8")
    app_css = (root / "src" / "zotero_web_library" / "static" / "app.css").read_text(encoding="utf-8")
    library_html = (root / "src" / "zotero_web_library" / "templates" / "library.html").read_text(encoding="utf-8")
    assert "data-current-tag-toggle" in app_js
    assert "data-shortcut-add-tag" in app_js
    assert "data-shortcut-form" in app_js
    assert "form-action-btn" in app_js
    assert "\"remark\", \"备注\"" in app_js
    assert "\"title_zh\", \"中文标题\"" in app_js
    assert "\"abstract_zh\", \"中文摘要\"" in app_js
    assert "tag-delete-btn" in app_js
    assert "tag-icon-btn" in app_js
    assert "function renderTagPopover" in app_js
    assert "function rerenderActiveTagPopover" in app_js
    assert "function renderStructuredCell" in app_js
    assert "function ratingLabelFromValues" in app_js
    assert "const RATING_STAR = \"⭐\"" in app_js
    assert "const RATING_CONTROL_STAR = \"⭐\"" in app_js
    assert "const ITEM_TYPE_META" in app_js
    assert "const ITEM_TYPE_ALIASES" in app_js
    assert "function normalizeItemTypeKey" in app_js
    assert "function itemTypeMeta" in app_js
    assert "function itemTypeLabel" in app_js
    assert "computerProgram" in app_js
    assert "webpage" in app_js
    assert "magazineArticle" in app_js
    assert "newspaperArticle" in app_js
    assert "webPage: \"webpage\"" in app_js
    assert "software: \"computerProgram\"" in app_js
    assert "data-edit-structured-cell" in app_js
    assert "data-save-structured-cell" in app_js
    assert "/structured-field" in app_js
    assert "selectedItemKeys: new Set()" in app_js
    assert "data-toggle-select-all" in app_js
    assert "data-row-select" in app_js
    assert "notifyFeatureInProgress" in app_js
    assert "data-selected-count" in app_js
    assert "data-bulk-action" in app_js
    assert "删除条目" in library_html
    assert "data-bulk-action=\"move-items\"" in library_html
    assert "附件编辑" in library_html
    assert "添加附件" not in library_html
    assert "data-bulk-action=\"edit-attachments\"" in library_html
    assert "data-attachment-editor-modal" in library_html
    assert "data-delete-items-modal" in library_html
    assert "data-move-items-modal" in library_html
    assert "data-delete-items-form" in app_js
    assert "data-move-items-form" in app_js
    assert "/items/delete" in app_js
    assert "/items/move" in app_js
    assert "keys.length !== 1" in app_js
    assert "data-add-file-attachment-form" in app_js
    assert "data-add-url-attachment-form" in app_js
    assert "data-edit-attachment-name" in app_js
    assert "data-delete-selected-attachments" in app_js
    assert "/attachments/file" in app_js
    assert "/attachments/url" in app_js
    assert "data-collection-menu" in app_js
    assert "data-rename-collection" in app_js
    assert "data-move-collection" in app_js
    assert "data-delete-collection" in app_js
    assert "data-create-child-collection" in app_js
    assert "key: \"__root\", name: \"根目录\"" in app_js
    assert "在根目录下新建文件夹" in app_js
    assert "manageable-root" in app_js
    assert "data-membership-form" not in app_js
    assert "data-create-collection-form" not in library_html
    assert "data-add-item-modal" in library_html
    assert "data-export-citation-modal" in library_html
    assert "data-import-identifier-form" in app_js
    assert "data-import-text-form" in app_js
    assert "/items/import-identifier" in app_js
    assert "/items/import-text" in app_js
    assert "/items/export-citations" in app_js
    assert "data-export-citation-form" in app_js
    assert "data-export-citation-format" in app_js
    assert "data-export-citation-error" in app_js
    assert "BibLaTeX" in app_js
    assert "CSL JSON" in app_js
    assert "selectedItemKeys()" in app_js
    assert "data-import-result-status" in app_js
    assert "条目已存在，已定位到已有条目" in app_js
    assert "currentRealCollectionKey" in app_js
    assert ".add-item-card" in app_css
    assert ".export-citation-card" in app_css
    assert ".import-results" in app_css
    assert ".floating-card .form-action-btn" in app_css
    assert "function renderTitleCell" in app_js
    assert "title-primary" in app_js
    assert "title-secondary" in app_js
    assert "data-add-tag-form" not in app_js
    assert "renderGlobalShortcutPanel" not in app_js
    assert "data-resize-column" in app_js
    assert "data-rating-item" in app_js
    assert "querySelectorAll(\"[data-open-columns]\")" in app_js
    assert "data-reading-popover" in app_js
    assert "class=\"reading-option" in app_js
    assert "data-semantic-filter=\"type\"" in library_html
    assert "type-badge" in app_js
    assert "normalizeHashTag" in app_js
    assert "attachment_badges" in app_js
    assert "笔记" in app_js
    assert "data-note-toggle" in app_js
    assert "function notePreview" in app_js
    assert "没有笔记" in app_js
    assert "路" not in app_js
    assert "data-manage-shortcuts" not in library_html
    assert "data-add-tag-form" not in library_html
    assert "data-shortcut-form" not in library_html
    assert "data-selected-count" in library_html
    assert "data-bulk-actions" in library_html
    assert "本地副本可编辑" not in library_html
    assert "本地副本" in library_html
    assert "topbar-meta" in library_html
    assert "添加条目" in library_html
    assert "删除条目" in library_html
    assert "移动条目" in library_html
    assert "附件编辑" in library_html
    assert "文献下载" in library_html
    assert "期刊&会议等级查询" in library_html
    assert "引用导出" in library_html
    assert "文献矩阵" in library_html
    assert "知识库问答" in library_html
    assert "button:hover ~ button" not in app_css
    assert ".form-action-btn" in app_css
    assert ".structured-cell-editor" in app_css
    assert ".structured-cell-actions .form-action-btn" in app_css
    assert ".structured-cell-editor input" in app_css
    assert ".structured-detail-form" in app_css
    assert ".shortcut-pill-toggle .tag-delete-btn" in app_css
    assert ".reading-option" in app_css
    assert ".type-badge" in app_css
    assert ".title-primary" in app_css
    assert ".title-secondary" in app_css
    assert ".title-text" in app_css
    assert ".type-group-academic" in app_css
    assert ".note-line" in app_css
    assert ".note-toggle-btn" in app_css
    assert ".item-table th > span:first-child" in app_css
    assert ".selection-col" in app_css
    assert ".selection-toggle-btn" in app_css
    assert ".row-checkbox" in app_css
    assert ".bulk-actions" in app_css
    assert ".bulk-action-btn" in app_css
    assert ".collection-menu" in app_css
    assert ".tree-action-btn" in app_css
    assert ".tree-row.manageable-root" in app_css
    assert ".bulk-modal-form" in app_css
    assert ".attachment-editor-card" in app_css
    assert ".attachment-add-grid" in app_css
    assert "input[type=\"file\"]::file-selector-button" in app_css
    assert ".bulk-modal-actions .form-action-btn" in app_css
    assert ".attachment-editor-actions .form-action-btn" in app_css
    assert ".table-stats" in app_css
    assert ".topbar-meta" in app_css
    assert "overflow-x: hidden" in app_css
    assert "grid-template-columns: minmax(72px, 110px) minmax(0, 1fr)" in app_css
    assert ".field-grid strong" in app_css
    assert ".detail-card p" in app_css
    assert ".attachment-line a" in app_css
    assert "overflow-wrap: anywhere" in app_css
    assert "data-toggle-plain-tags" in library_html
    assert "code_status" not in library_html


def test_translator_document_records_v1_boundaries() -> None:
    root = Path(__file__).resolve().parents[1]
    doc = (root / "docs" / "zotero-translators.md").read_text(encoding="utf-8")
    assert "Search translator" in doc
    assert "Web + Search translator" in doc
    assert "Import translator" in doc
    assert "Export translator" in doc
    assert "不直接执行 Zotero translator JS" in doc
    assert "BibLaTeX" in doc
    assert "Zotero RDF" in doc
    assert "RIS" in doc
    assert "BibTeX" in doc
