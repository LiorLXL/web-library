from __future__ import annotations

from pathlib import Path

from zotero_web_library.web import create_app


def test_source_index_contains_service_path_and_upload_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "src" / "zotero_web_library" / "templates" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "src" / "zotero_web_library" / "static" / "app.js").read_text(encoding="utf-8")
    app_css = (root / "src" / "zotero_web_library" / "static" / "app.css").read_text(encoding="utf-8")

    assert "<h1>网页文库</h1>" in index_html
    assert "无缝衔接您的 Zotero 资产" in index_html
    assert "本地只读模式" in index_html
    assert "副本编辑模式" in index_html
    assert "选择本地路径" in index_html
    assert "复制本地路径" in index_html
    assert "上传文件夹" in index_html
    assert "进入文库" in index_html
    assert "当前选择目录" in index_html
    assert "子目录" in index_html
    assert "data-upload-progress" in index_html
    assert "data-server-path-modal" in index_html
    assert "Standalone Zotero Web Library" not in index_html
    assert "Zotero 网页文库" not in index_html
    assert "连接只读模式" not in index_html
    assert "本地副本模式" not in index_html
    assert "class=\"library-list-link\"" not in index_html
    assert "/api/server-paths/roots" in app_js
    assert "/api/server-paths/list" in app_js
    assert "/api/sources/upload-folder" in app_js
    assert "SERVER_VIRTUAL_ROOT" in app_js
    assert "进入子目录" in app_js
    assert "data-server-path-use" not in app_js
    assert "webkitdirectory" in app_js
    assert "XMLHttpRequest" in app_js
    assert ".upload-progress-bar" in app_css
    assert ".library-enter-btn" in app_css
    assert ".path-entry-enter" in app_css


def test_frontend_contains_refined_interaction_hooks() -> None:
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "src" / "zotero_web_library" / "static" / "app.js").read_text(encoding="utf-8")
    app_css = (root / "src" / "zotero_web_library" / "static" / "app.css").read_text(encoding="utf-8")
    library_html = (root / "src" / "zotero_web_library" / "templates" / "library.html").read_text(encoding="utf-8")
    reader_html = (root / "src" / "zotero_web_library" / "templates" / "reader.html").read_text(encoding="utf-8")
    reader_js = (root / "src" / "zotero_web_library" / "static" / "reader.js").read_text(encoding="utf-8")
    reader_css = (root / "src" / "zotero_web_library" / "static" / "reader.css").read_text(encoding="utf-8")
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
    assert "function currentDetailItem" in app_js
    assert "function bulkActionState" in app_js
    assert "function renderBulkActionStates" in app_js
    assert "aria-disabled" in app_js
    assert "请点击任意条目后操作" in app_js
    assert "请勾选任意数量条目后操作" in app_js
    assert "请点击有可读PDF的条目后操作" in app_js
    assert "notifyFeatureInProgress" in app_js
    assert "data-selected-count" in app_js
    assert "data-bulk-action" in app_js
    assert "删除条目" in library_html
    assert "data-bulk-action=\"move-items\"" in library_html
    assert "附件编辑" in library_html
    assert "文献研读" in library_html
    assert "添加附件" not in library_html
    assert "data-bulk-action=\"edit-attachments\"" in library_html
    assert "data-bulk-action=\"read-paper\"" in library_html
    assert "data-attachment-editor-modal" in library_html
    assert "data-reader-pdf-picker-modal" in library_html
    assert "data-delete-items-modal" in library_html
    assert "data-move-items-modal" in library_html
    assert "data-delete-items-form" in app_js
    assert "data-move-items-form" in app_js
    assert "/items/delete" in app_js
    assert "/items/move" in app_js
    assert "state.attachmentEditorItemKey = item.key" in app_js
    assert "data-add-file-attachment-form" in app_js
    assert "data-add-url-attachment-form" in app_js
    assert "data-edit-attachment-name" in app_js
    assert "data-delete-selected-attachments" in app_js
    assert "/attachments/file" in app_js
    assert "/attachments/url" in app_js
    assert "function openReadPaper" in app_js
    assert "currentDetailItem()" in app_js
    assert "currentItemPdfAttachments" in app_js
    assert "data-reader-pdf-picker" in app_js
    assert "data-reader-pdf-picker-form" in app_js
    assert "/pdf-attachments" in app_js
    assert "文献研读仅支持勾选 1 条文献" not in app_js
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
    assert "title=\"文献研读\"" in library_html
    assert "button:hover ~ button" not in app_css
    assert ".form-action-btn" in app_css
    assert ".nav-action-btn" in app_css
    assert "class=\"nav-action-btn\"" in library_html
    assert "class=\"form-action-btn column-save-btn\"" in library_html
    assert "column-order-btn" in app_js
    assert ".column-order-btn" in app_css
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
    assert ".bulk-action-btn.is-disabled" in app_css
    assert ".bulk-action-btn[aria-disabled=\"true\"]" in app_css
    assert ".collection-menu" in app_css
    assert ".tree-action-btn" in app_css
    assert ".tree-row.manageable-root" in app_css
    assert ".bulk-modal-form" in app_css
    assert ".attachment-editor-card" in app_css
    assert ".attachment-add-grid" in app_css
    assert ".reader-picker-card" in app_css
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
    assert "data-reader-page" in reader_html
    assert "data-reader-layout" in reader_html
    assert "data-reader-outline" in reader_html
    assert "data-reader-splitter=\"left\"" in reader_html
    assert "data-reader-splitter=\"right\"" in reader_html
    assert "data-reader-annotation-toolbar" in reader_html
    assert "data-clear-annotation" in reader_html
    assert "data-reader-zoom-out" in reader_html
    assert "data-reader-zoom-in" in reader_html
    assert "data-reader-zoom-label" in reader_html
    assert "data-reader-page-input" in reader_html
    assert "data-reader-page-total" in reader_html
    assert "reader-outline-collapse-btn" in reader_html
    assert "reader-return-action" in reader_html
    assert "reader-title-block" in reader_html
    assert "reader-subtitle-row" in reader_html
    assert "data-reader-toolbar" in reader_html
    assert "nav-action-btn" in reader_html
    assert "toolbar toolbar" not in reader_html
    assert "vendor/pdfjs/pdf.min.js" in reader_html
    assert "reader.js" in reader_html
    assert "pdfjsLib" in reader_js
    assert "getOutline" in reader_js
    assert "renderTextLayer" in reader_js
    assert "devicePixelRatio" in reader_js
    assert "outputScale" in reader_js
    assert "IntersectionObserver" in reader_js
    assert "fitWidthScale" in reader_js
    assert "jumpToPage" in reader_js
    assert "buildPageCharacterModel" in reader_js
    assert "pointToCharacterOffset" in reader_js
    assert "selectionRangeToRects" in reader_js
    assert "selectionRangeToText" in reader_js
    assert "getClientRects" not in reader_js
    assert "selectionRectsForPage" not in reader_js
    assert "pointerdown" in reader_js
    assert "pointermove" in reader_js
    assert "pointerup" in reader_js
    assert "normalizedAnnotationBox" in reader_js
    assert "data-create-annotation" in reader_js
    assert "clearAnnotationsInSelection" in reader_js
    assert "/annotations/clear" in reader_js
    assert "/annotations" in reader_js
    assert "function updateReaderToolbarPosition" in reader_js
    assert "getBoundingClientRect()" in reader_js
    assert "--reader-toolbar-left" in reader_js
    assert "--reader-toolbar-top" in reader_js
    assert "convertToPdfPoint" in reader_js
    assert "convertToViewportRectangle" in reader_js
    assert "position: readerState.pendingSelection.position" in reader_js
    assert "itemAnnotations" not in reader_js
    assert ".reader-layout" in reader_css
    assert ".reader-toolbar" in reader_css
    assert "--reader-toolbar-left" in reader_css
    assert "--reader-toolbar-top" in reader_css
    assert "position: fixed" in reader_css
    assert "grid-template-areas: \"title return\"" in reader_css
    assert ".reader-subtitle-row" in reader_css
    assert ".reader-page-input" in reader_css
    assert ".reader-outline-collapse-btn" in reader_css
    assert ".reader-annotation-toolbar" in reader_css
    assert ".reader-annotation.highlight" in reader_css
    assert ".reader-annotation.underline" in reader_css
    assert ".reader-clear-btn" in reader_css
    assert ".reader-selection-layer" in reader_css
    assert ".reader-selection" in reader_css
    assert "opacity: 0.2" not in reader_css
    assert "z-index: 1" in reader_css
    assert "z-index: 2" in reader_css
    assert "z-index: 3" in reader_css
    assert (root / "src" / "zotero_web_library" / "static" / "vendor" / "pdfjs" / "pdf.min.js").exists()
    assert (root / "src" / "zotero_web_library" / "static" / "vendor" / "pdfjs" / "pdf.worker.min.js").exists()


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


def test_static_javascript_uses_browser_executable_mimetype() -> None:
    client = create_app().test_client()
    for path in ["/static/reader.js", "/static/vendor/pdfjs/pdf.min.js"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("application/javascript")
