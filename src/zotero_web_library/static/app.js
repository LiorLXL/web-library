const ALL_COLUMNS = [
  ["title", "标题"],
  ["remark", "备注"],
  ["title_zh", "中文标题"],
  ["abstract_zh", "中文摘要"],
  ["creators", "作者"],
  ["year", "年份"],
  ["venue", "来源"],
  ["rating", "评分"],
  ["nested", "#标签"],
  ["venue_rank", "期刊等级"],
  ["reading_status", "阅读"],
  ["plain", "普通标签"],
  ["collections", "文件夹"],
];

const DEFAULT_COLUMNS = ["title", "creators", "year", "venue", "rating", "nested", "venue_rank", "reading_status", "collections"];
const READ_TAGS = new Set(["/done", "done", "已读", "read"]);
const READING_TAGS = new Set(["/reading", "reading", "在读"]);
const RATING_STAR = "⭐";
const RATING_CONTROL_STAR = "⭐";
const ITEM_TYPE_META = {
  journalArticle: { labelZh: "期刊", group: "academic", color: "#0f766e" },
  conferencePaper: { labelZh: "会议", group: "academic", color: "#0ea5a4" },
  thesis: { labelZh: "学位", group: "academic", color: "#0891b2" },
  preprint: { labelZh: "预印", group: "academic", color: "#2563eb" },
  book: { labelZh: "图书", group: "academic", color: "#1d4ed8" },
  bookSection: { labelZh: "章节", group: "academic", color: "#3b82f6" },
  report: { labelZh: "报告", group: "academic", color: "#14b8a6" },
  encyclopediaArticle: { labelZh: "百科", group: "academic", color: "#22c55e" },
  dictionaryEntry: { labelZh: "词典", group: "academic", color: "#16a34a" },
  standard: { labelZh: "标准", group: "academic", color: "#06b6d4" },
  dataset: { labelZh: "数据集", group: "academic", color: "#0ea5e9" },
  webpage: { labelZh: "网页", group: "media", color: "#0f6f91" },
  blogPost: { labelZh: "博客", group: "media", color: "#0369a1" },
  forumPost: { labelZh: "论坛", group: "media", color: "#0284c7" },
  document: { labelZh: "文档", group: "media", color: "#0b7295" },
  magazineArticle: { labelZh: "杂志", group: "media", color: "#075985" },
  newspaperArticle: { labelZh: "报纸", group: "media", color: "#0369a1" },
  audioRecording: { labelZh: "音频", group: "media", color: "#0891b2" },
  videoRecording: { labelZh: "视频", group: "media", color: "#0ea5e9" },
  film: { labelZh: "电影", group: "media", color: "#38bdf8" },
  podcast: { labelZh: "播客", group: "media", color: "#06b6d4" },
  radioBroadcast: { labelZh: "广播", group: "media", color: "#0284c7" },
  tvBroadcast: { labelZh: "电视", group: "media", color: "#38bdf8" },
  bill: { labelZh: "法案", group: "legal", color: "#a16207" },
  statute: { labelZh: "法规", group: "legal", color: "#b45309" },
  case: { labelZh: "案例", group: "legal", color: "#c2410c" },
  hearing: { labelZh: "听证", group: "legal", color: "#d97706" },
  manuscript: { labelZh: "手稿", group: "other", color: "#7c3aed" },
  letter: { labelZh: "信件", group: "other", color: "#9333ea" },
  artwork: { labelZh: "艺术", group: "other", color: "#c026d3" },
  map: { labelZh: "地图", group: "other", color: "#a855f7" },
  patent: { labelZh: "专利", group: "other", color: "#db2777" },
  interview: { labelZh: "访谈", group: "other", color: "#e11d48" },
  presentation: { labelZh: "演示", group: "other", color: "#be185d" },
  email: { labelZh: "邮件", group: "other", color: "#ec4899" },
  instantMessage: { labelZh: "私信", group: "other", color: "#d946ef" },
  computerProgram: { labelZh: "软件", group: "other", color: "#8b5cf6" },
};
const ITEM_TYPE_ALIASES = {
  webPage: "webpage",
  software: "computerProgram",
};

const state = {
  libraryId: "",
  library: null,
  items: [],
  collections: [],
  tagShortcuts: [],
  filteredItems: [],
  selectedItem: null,
  selectedItemKeys: new Set(),
  selectedCollectionKey: "",
  selectedTags: new Map(),
  columns: [],
  columnDraft: [],
  columnWidths: {},
  search: "",
  plainCollapsed: true,
  activePopoverItemKey: "",
  editingStructuredCell: null,
  structuredCellDraft: "",
  detailStructuredEditing: false,
  detailStructuredDraft: { remark: "", title_zh: "", abstract_zh: "" },
  expandedNotes: new Set(),
  addItemMode: "identifier",
  addItemMessage: "",
  addItemResults: [],
  addItemBusy: false,
  citationExportFormat: "bibtex",
  citationExportMessage: "",
  citationExportBusy: false,
  deleteItemsMode: "trash",
  deleteItemsMessage: "",
  deleteItemsBusy: false,
  deleteItemsPermanentConfirmed: false,
  moveItemsTargetKey: "",
  moveItemsMessage: "",
  moveItemsBusy: false,
  attachmentEditorItemKey: "",
  attachmentEditorMessage: "",
  attachmentEditorBusy: false,
  selectedAttachmentKeys: new Set(),
  editingAttachmentKey: "",
  editingAttachmentTitle: "",
  activeCollectionMenuKey: "",
  editingCollectionKey: "",
  editingCollectionName: "",
  movingCollectionKey: "",
  movingCollectionTargetKey: "",
  creatingCollectionParentKey: "",
  creatingCollectionName: "",
};

function postJSON(url, payload, method = "POST") {
  return fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(async (response) => {
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
    return data;
  });
}

function deleteJSON(url, payload = {}) {
  return postJSON(url, payload, "DELETE");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function tagColor(tag) {
  let hash = 0;
  for (let i = 0; i < tag.length; i += 1) hash = ((hash << 5) - hash + tag.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 72% 42%)`;
}

function normalizeHashTag(tag) {
  const value = String(tag || "").trim().replace(/\s+/g, " ");
  if (!value) return "";
  if (value.startsWith("#") || value.startsWith("/")) return value;
  return `#${value}`;
}

function displayHashTag(tag) {
  const value = String(tag || "").trim();
  return value.startsWith("#") ? value.slice(1) : value;
}

function textOf(values) {
  return (values || []).join(" / ");
}

function ratingNumberFromValues(values) {
  const current = textOf(values || []);
  const stars = [...current].filter((char) => ["★", "⭐", "🌟"].includes(char)).length;
  return stars || Number(current.replace(/\D/g, "")) || 0;
}

function ratingLabelFromValues(values) {
  const count = ratingNumberFromValues(values);
  return count ? RATING_STAR.repeat(count) : "";
}

function readingStatus(item) {
  const values = (item.semantic?.reading_status || []).map((value) => String(value).toLowerCase());
  if (values.some((value) => READ_TAGS.has(value))) return { key: "read", label: "已读", tag: "/done" };
  if (values.some((value) => READING_TAGS.has(value))) return { key: "reading", label: "在读", tag: "/reading" };
  return { key: "unread", label: "未读", tag: "" };
}

function normalizeItemTypeKey(typeKey) {
  const value = String(typeKey || "").trim();
  if (!value) return "";
  return ITEM_TYPE_ALIASES[value] || value;
}

function itemTypeMeta(typeKey) {
  const raw = String(typeKey || "").trim();
  const normalized = normalizeItemTypeKey(raw);
  if (!normalized) return { labelZh: "未知", group: "other", color: "#64748b", raw: "", key: "" };
  const meta = ITEM_TYPE_META[normalized];
  if (meta) return { ...meta, raw: raw || normalized, key: normalized };
  return { labelZh: raw || normalized, group: "other", color: "#64748b", raw: raw || normalized, key: normalized };
}

function itemTypeLabel(typeKey) {
  return itemTypeMeta(typeKey).labelZh;
}

function isItemChecked(itemKey) {
  return state.selectedItemKeys.has(String(itemKey || ""));
}

function toggleItemChecked(itemKey, checked) {
  const key = String(itemKey || "");
  if (!key) return;
  if (checked) state.selectedItemKeys.add(key);
  else state.selectedItemKeys.delete(key);
}

function filteredItemKeys() {
  return state.filteredItems.map((item) => String(item.key || "")).filter(Boolean);
}

function filteredSelectedCount() {
  return filteredItemKeys().filter((key) => state.selectedItemKeys.has(key)).length;
}

function totalSelectedCount() {
  return state.selectedItemKeys.size;
}

function isAllFilteredSelected() {
  const keys = filteredItemKeys();
  return keys.length > 0 && keys.every((key) => state.selectedItemKeys.has(key));
}

function selectAllFilteredItems() {
  filteredItemKeys().forEach((key) => state.selectedItemKeys.add(key));
}

function clearFilteredSelection() {
  filteredItemKeys().forEach((key) => state.selectedItemKeys.delete(key));
}

function selectedItemKeys() {
  return [...state.selectedItemKeys].filter(Boolean);
}

function notifyFeatureInProgress(action) {
  const labels = new Map([
    ["add-item", "添加条目"],
    ["delete-items", "删除条目"],
    ["move-items", "移动条目"],
    ["edit-attachments", "附件编辑"],
    ["download-papers", "文献下载"],
    ["query-rank", "期刊&会议等级查询"],
    ["export-citation", "引用导出"],
    ["paper-matrix", "文献矩阵"],
    ["knowledge-qa", "知识库问答"],
  ]);
  window.alert(`${labels.get(action) || "该功能"}开发中`);
}

function currentRealCollectionKey() {
  const key = String(state.selectedCollectionKey || "");
  if (!key || key.startsWith("__")) return "";
  return key;
}

function importResultMessage(summary) {
  const created = Number(summary.created_count || 0);
  const existing = Number(summary.existing_count || 0);
  const conflict = Number(summary.conflict_count || 0);
  const failed = Number(summary.failed_count || 0);
  const parts = [];
  if (created) parts.push(`新建 ${created} 条`);
  if (existing) parts.push(`复用已有 ${existing} 条`);
  if (conflict) parts.push(`冲突 ${conflict} 条`);
  if (failed) parts.push(`失败 ${failed} 条`);
  if (!parts.length) return "没有导入条目。";
  if (existing && !created && !conflict && !failed) return "条目已存在，已定位到已有条目。";
  return parts.join(" · ");
}

function renderAddItemResults() {
  if (!state.addItemResults.length) return "";
  return `<div class="import-results" data-import-results>
    ${state.addItemResults.map((result) => {
      const statusLabel = { created: "已新建", existing: "已存在", conflict: "重复冲突", failed: "失败" }[result.status] || result.status;
      const title = result.title || result.item_key || "未命名条目";
      const candidates = (result.candidates || []).map((candidate) => `<button type="button" class="import-candidate" data-import-select-item="${escapeHtml(candidate.key)}">${escapeHtml(candidate.title || candidate.key)}</button>`).join("");
      return `<div class="import-result ${result.status}" data-import-result-status="${escapeHtml(result.status || "")}">
        <strong>${escapeHtml(statusLabel)}</strong>
        <span>${escapeHtml(title)}</span>
        ${candidates ? `<div class="import-candidates">${candidates}</div>` : ""}
      </div>`;
    }).join("")}
  </div>`;
}

function renderAddItemModal() {
  const panel = document.querySelector("[data-add-item-modal]");
  if (!panel) return;
  const isIdentifier = state.addItemMode === "identifier";
  panel.innerHTML = `
    <section class="floating-card add-item-card" data-add-item-card>
      <div class="pane-head">
        <div>
          <h2>添加条目</h2>
          <p>${currentRealCollectionKey() ? "导入后会加入当前文件夹" : "当前不是实际文件夹，导入后不加入文件夹"}</p>
        </div>
        <button type="button" class="icon-btn" data-close-add-item>×</button>
      </div>
      <div class="add-item-tabs">
        <button type="button" class="${isIdentifier ? "active" : ""}" data-add-item-mode="identifier">标识符</button>
        <button type="button" class="${!isIdentifier ? "active" : ""}" data-add-item-mode="text">引用文本</button>
      </div>
      ${isIdentifier ? `
        <form class="add-item-form" data-import-identifier-form>
          <label>
            <span>ISBN / DOI / PMID / arXiv ID / ADS Bibcode</span>
            <input name="identifier" data-import-identifier-input placeholder="例如 10.1038/s41586-024-... 或 2406.09246">
          </label>
          <button type="submit" class="form-action-btn" ${state.addItemBusy ? "disabled" : ""}>${state.addItemBusy ? "导入中..." : "导入条目"}</button>
        </form>
      ` : `
        <form class="add-item-form" data-import-text-form>
          <label>
            <span>格式</span>
            <select name="format" data-import-text-format>
              <option value="auto">自动识别</option>
              <option value="ris">RIS</option>
              <option value="bibtex">BibTeX</option>
              <option value="csl_json">CSL JSON</option>
              <option value="pubmed_xml">PubMed XML</option>
            </select>
          </label>
          <label>
            <span>引用文本</span>
            <textarea name="text" rows="10" data-import-text-input placeholder="粘贴 RIS、BibTeX、CSL JSON 或 PubMed XML"></textarea>
          </label>
          <button type="submit" class="form-action-btn" ${state.addItemBusy ? "disabled" : ""}>${state.addItemBusy ? "导入中..." : "导入引用文本"}</button>
        </form>
      `}
      ${state.addItemMessage ? `<p class="import-message" data-import-message>${escapeHtml(state.addItemMessage)}</p>` : ""}
      ${renderAddItemResults()}
    </section>
  `;
  panel.querySelectorAll("[data-add-item-mode]").forEach((button) => button.addEventListener("click", () => {
    state.addItemMode = button.dataset.addItemMode;
    state.addItemMessage = "";
    state.addItemResults = [];
    renderAddItemModal();
  }));
  panel.querySelector("[data-close-add-item]")?.addEventListener("click", closeAddItemModal);
  panel.querySelector("[data-import-identifier-form]")?.addEventListener("submit", submitIdentifierImport);
  panel.querySelector("[data-import-text-form]")?.addEventListener("submit", submitTextImport);
  panel.querySelectorAll("[data-import-select-item]").forEach((button) => button.addEventListener("click", () => {
    const item = state.items.find((value) => value.key === button.dataset.importSelectItem);
    if (item) {
      state.selectedItem = item;
      renderTable();
      renderDetail();
    }
  }));
}

function openAddItemModal() {
  if (!state.library?.editable) {
    window.alert("只读源库不能添加条目。请先创建本地副本。");
    return;
  }
  state.addItemMessage = "";
  state.addItemResults = [];
  document.querySelector("[data-add-item-modal]").hidden = false;
  renderAddItemModal();
}

function closeAddItemModal() {
  const panel = document.querySelector("[data-add-item-modal]");
  if (panel) panel.hidden = true;
}

async function finishImport(summary) {
  state.addItemMessage = importResultMessage(summary);
  state.addItemResults = summary.results || [];
  const targetKey = (state.addItemResults.find((result) => result.item_key)?.item_key) || "";
  await loadState();
  if (targetKey) {
    state.selectedItem = state.items.find((item) => item.key === targetKey) || state.selectedItem;
    renderTable();
    renderDetail();
  }
  renderAddItemModal();
}

async function submitIdentifierImport(event) {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  payload.collection_key = currentRealCollectionKey();
  try {
    state.addItemBusy = true;
    renderAddItemModal();
    const summary = await postJSON(`/api/library/${state.libraryId}/items/import-identifier`, payload);
    await finishImport(summary);
  } catch (error) {
    state.addItemMessage = error.message;
    state.addItemResults = [];
    renderAddItemModal();
  } finally {
    state.addItemBusy = false;
    renderAddItemModal();
  }
}

async function submitTextImport(event) {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  payload.collection_key = currentRealCollectionKey();
  try {
    state.addItemBusy = true;
    renderAddItemModal();
    const summary = await postJSON(`/api/library/${state.libraryId}/items/import-text`, payload);
    await finishImport(summary);
  } catch (error) {
    state.addItemMessage = error.message;
    state.addItemResults = [];
    renderAddItemModal();
  } finally {
    state.addItemBusy = false;
    renderAddItemModal();
  }
}

function renderCitationExportModal() {
  const panel = document.querySelector("[data-export-citation-modal]");
  if (!panel) return;
  const selectedCount = selectedItemKeys().length;
  panel.innerHTML = `
    <section class="floating-card export-citation-card" data-export-citation-card>
      <div class="pane-head">
        <div>
          <h2>引用导出</h2>
          <p>已选择 ${selectedCount} 条文献</p>
        </div>
        <button type="button" class="icon-btn" data-close-export-citation>×</button>
      </div>
      <form class="export-citation-form" data-export-citation-form>
        <label>
          <span>导出格式</span>
          <select name="format" data-export-citation-format>
            <option value="bibtex" ${state.citationExportFormat === "bibtex" ? "selected" : ""}>BibTeX</option>
            <option value="biblatex" ${state.citationExportFormat === "biblatex" ? "selected" : ""}>BibLaTeX</option>
            <option value="ris" ${state.citationExportFormat === "ris" ? "selected" : ""}>RIS</option>
            <option value="csl_json" ${state.citationExportFormat === "csl_json" ? "selected" : ""}>CSL JSON</option>
            <option value="csv" ${state.citationExportFormat === "csv" ? "selected" : ""}>CSV</option>
          </select>
        </label>
        <button type="submit" class="form-action-btn" ${state.citationExportBusy ? "disabled" : ""}>${state.citationExportBusy ? "导出中..." : "下载"}</button>
      </form>
      ${state.citationExportMessage ? `<p class="export-citation-message" data-export-citation-error>${escapeHtml(state.citationExportMessage)}</p>` : ""}
    </section>
  `;
  panel.querySelector("[data-close-export-citation]")?.addEventListener("click", closeCitationExportModal);
  panel.querySelector("[data-export-citation-format]")?.addEventListener("change", (event) => {
    state.citationExportFormat = event.target.value;
  });
  panel.querySelector("[data-export-citation-form]")?.addEventListener("submit", submitCitationExport);
}

function openCitationExportModal() {
  if (!selectedItemKeys().length) {
    window.alert("请先勾选要导出的条目。");
    return;
  }
  state.citationExportMessage = "";
  document.querySelector("[data-export-citation-modal]").hidden = false;
  renderCitationExportModal();
}

function closeCitationExportModal() {
  const panel = document.querySelector("[data-export-citation-modal]");
  if (panel) panel.hidden = true;
}

function filenameFromDisposition(headerValue) {
  const match = String(headerValue || "").match(/filename="?([^";]+)"?/i);
  return match ? match[1] : `zotero-web-library.${state.citationExportFormat}`;
}

async function submitCitationExport(event) {
  event.preventDefault();
  const formData = Object.fromEntries(new FormData(event.currentTarget).entries());
  state.citationExportFormat = formData.format || state.citationExportFormat;
  try {
    state.citationExportBusy = true;
    state.citationExportMessage = "";
    renderCitationExportModal();
    const response = await fetch(`/api/library/${state.libraryId}/items/export-citations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_keys: selectedItemKeys(), format: state.citationExportFormat }),
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "引用导出失败");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filenameFromDisposition(response.headers.get("Content-Disposition"));
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    closeCitationExportModal();
  } catch (error) {
    state.citationExportMessage = error.message;
    renderCitationExportModal();
  } finally {
    state.citationExportBusy = false;
    renderCitationExportModal();
  }
}

function renderDeleteItemsModal() {
  const panel = document.querySelector("[data-delete-items-modal]");
  if (!panel) return;
  const selectedCount = selectedItemKeys().length;
  const isPermanent = state.deleteItemsMode === "permanent";
  panel.innerHTML = `
    <section class="floating-card delete-items-card" data-delete-items-card>
      <div class="pane-head">
        <div>
          <h2>删除条目</h2>
          <p>已选择 ${selectedCount} 条文献</p>
        </div>
        <button type="button" class="icon-btn" data-close-delete-items>×</button>
      </div>
      <form class="bulk-modal-form" data-delete-items-form>
        <label class="choice-row">
          <input type="radio" name="mode" value="trash" ${state.deleteItemsMode === "trash" ? "checked" : ""}>
          <span><strong>移入回收站</strong><small>保留条目数据，可在回收站查看。</small></span>
        </label>
        <label class="choice-row danger-choice">
          <input type="radio" name="mode" value="permanent" ${isPermanent ? "checked" : ""}>
          <span><strong>永久删除</strong><small>删除本地副本 SQLite 记录，并删除相关 storage/ 附件文件夹。</small></span>
        </label>
        ${isPermanent ? `
          <label class="confirm-row">
            <input type="checkbox" data-confirm-permanent-delete ${state.deleteItemsPermanentConfirmed ? "checked" : ""}>
            <span>我确认永久删除所选条目及其本地附件文件夹。</span>
          </label>
        ` : ""}
        <div class="bulk-modal-actions">
          <button type="submit" class="danger-btn" ${state.deleteItemsBusy || (isPermanent && !state.deleteItemsPermanentConfirmed) ? "disabled" : ""}>${state.deleteItemsBusy ? "删除中..." : "确认删除"}</button>
          <button type="button" class="ghost-btn" data-close-delete-items>取消</button>
        </div>
      </form>
      ${state.deleteItemsMessage ? `<p class="import-message" data-delete-items-error>${escapeHtml(state.deleteItemsMessage)}</p>` : ""}
    </section>
  `;
  panel.querySelectorAll("[data-close-delete-items]").forEach((button) => button.addEventListener("click", closeDeleteItemsModal));
  panel.querySelectorAll("input[name='mode']").forEach((input) => input.addEventListener("change", () => {
    state.deleteItemsMode = input.value;
    state.deleteItemsPermanentConfirmed = false;
    state.deleteItemsMessage = "";
    renderDeleteItemsModal();
  }));
  panel.querySelector("[data-confirm-permanent-delete]")?.addEventListener("change", (event) => {
    state.deleteItemsPermanentConfirmed = event.target.checked;
    renderDeleteItemsModal();
  });
  panel.querySelector("[data-delete-items-form]")?.addEventListener("submit", submitDeleteItems);
}

function openDeleteItemsModal() {
  if (!selectedItemKeys().length) {
    window.alert("请先勾选要删除的条目。");
    return;
  }
  if (!state.library?.editable) {
    window.alert("只读源库不能删除条目。请先创建本地副本。");
    return;
  }
  state.deleteItemsMode = "trash";
  state.deleteItemsMessage = "";
  state.deleteItemsPermanentConfirmed = false;
  document.querySelector("[data-delete-items-modal]").hidden = false;
  renderDeleteItemsModal();
}

function closeDeleteItemsModal() {
  const panel = document.querySelector("[data-delete-items-modal]");
  if (panel) panel.hidden = true;
}

async function submitDeleteItems(event) {
  event.preventDefault();
  const keys = selectedItemKeys();
  if (!keys.length) return;
  try {
    state.deleteItemsBusy = true;
    state.deleteItemsMessage = "";
    renderDeleteItemsModal();
    const result = await postJSON(`/api/library/${state.libraryId}/items/delete`, { item_keys: keys, mode: state.deleteItemsMode });
    (result.item_keys || keys).forEach((key) => state.selectedItemKeys.delete(key));
    if (state.selectedItem && (result.item_keys || keys).includes(state.selectedItem.key)) state.selectedItem = null;
    closeDeleteItemsModal();
    await loadState();
  } catch (error) {
    state.deleteItemsMessage = error.message;
    renderDeleteItemsModal();
  } finally {
    state.deleteItemsBusy = false;
    renderDeleteItemsModal();
  }
}

function renderMoveItemsModal() {
  const panel = document.querySelector("[data-move-items-modal]");
  if (!panel) return;
  const selectedCount = selectedItemKeys().length;
  const options = collectionSelectOptions({ includeRoot: false, selectedKey: state.moveItemsTargetKey });
  panel.innerHTML = `
    <section class="floating-card move-items-card" data-move-items-card>
      <div class="pane-head">
        <div>
          <h2>移动条目</h2>
          <p>已选择 ${selectedCount} 条文献。移动后只保留目标文件夹归属。</p>
        </div>
        <button type="button" class="icon-btn" data-close-move-items>×</button>
      </div>
      <form class="bulk-modal-form" data-move-items-form>
        <label>
          <span>目标文件夹</span>
          <select name="target_collection_key" data-move-items-target>
            ${options || `<option value="">暂无可用文件夹</option>`}
          </select>
        </label>
        <div class="bulk-modal-actions">
          <button type="submit" class="form-action-btn" ${state.moveItemsBusy || !state.moveItemsTargetKey ? "disabled" : ""}>${state.moveItemsBusy ? "移动中..." : "确认移动"}</button>
          <button type="button" class="ghost-btn" data-close-move-items>取消</button>
        </div>
      </form>
      ${state.moveItemsMessage ? `<p class="import-message" data-move-items-error>${escapeHtml(state.moveItemsMessage)}</p>` : ""}
    </section>
  `;
  panel.querySelectorAll("[data-close-move-items]").forEach((button) => button.addEventListener("click", closeMoveItemsModal));
  panel.querySelector("[data-move-items-target]")?.addEventListener("change", (event) => {
    state.moveItemsTargetKey = event.target.value;
    renderMoveItemsModal();
  });
  panel.querySelector("[data-move-items-form]")?.addEventListener("submit", submitMoveItems);
}

function openMoveItemsModal() {
  if (!selectedItemKeys().length) {
    window.alert("请先勾选要移动的条目。");
    return;
  }
  if (!state.library?.editable) {
    window.alert("只读源库不能移动条目。请先创建本地副本。");
    return;
  }
  state.moveItemsTargetKey = currentRealCollectionKey() || sortedCollections()[0]?.key || "";
  state.moveItemsMessage = "";
  document.querySelector("[data-move-items-modal]").hidden = false;
  renderMoveItemsModal();
}

function closeMoveItemsModal() {
  const panel = document.querySelector("[data-move-items-modal]");
  if (panel) panel.hidden = true;
}

async function submitMoveItems(event) {
  event.preventDefault();
  const keys = selectedItemKeys();
  const target = String(new FormData(event.currentTarget).get("target_collection_key") || state.moveItemsTargetKey || "").trim();
  if (!keys.length || !target) return;
  try {
    state.moveItemsBusy = true;
    state.moveItemsMessage = "";
    state.moveItemsTargetKey = target;
    renderMoveItemsModal();
    await postJSON(`/api/library/${state.libraryId}/items/move`, { item_keys: keys, target_collection_key: target });
    closeMoveItemsModal();
    await loadState();
  } catch (error) {
    state.moveItemsMessage = error.message;
    renderMoveItemsModal();
  } finally {
    state.moveItemsBusy = false;
    renderMoveItemsModal();
  }
}

function currentAttachmentEditorItem() {
  return state.items.find((item) => item.key === state.attachmentEditorItemKey) || null;
}

function renderAttachmentEditorModal() {
  const panel = document.querySelector("[data-attachment-editor-modal]");
  if (!panel) return;
  const item = currentAttachmentEditorItem();
  if (!item) {
    panel.innerHTML = "";
    return;
  }
  const attachments = item.attachments || [];
  panel.innerHTML = `
    <section class="floating-card attachment-editor-card" data-attachment-editor-card>
      <div class="pane-head">
        <div>
          <h2>附件编辑</h2>
          <p>${escapeHtml(item.title || item.key)} · ${attachments.length} 个附件</p>
        </div>
        <button type="button" class="icon-btn" data-close-attachment-editor>×</button>
      </div>
      <div class="attachment-editor-list" data-attachment-editor-list>
        ${attachments.map((attachment) => {
          const checked = state.selectedAttachmentKeys.has(attachment.key);
          const editing = state.editingAttachmentKey === attachment.key;
          const title = attachment.display_label || attachment.path || attachment.key;
          return `
            <div class="attachment-editor-row" data-attachment-editor-row="${escapeHtml(attachment.key)}">
              <input type="checkbox" data-select-attachment="${escapeHtml(attachment.key)}" ${checked ? "checked" : ""} aria-label="选择附件">
              <span class="attachment-badge ${attachmentBadgeClass(attachment.kind, attachment.status === "missing")}">${escapeHtml(attachment.kind || "file")}</span>
              <div class="attachment-editor-main">
                ${editing ? `
                  <input class="attachment-rename-input" data-attachment-rename-input value="${escapeHtml(state.editingAttachmentTitle || title)}">
                ` : `
                  ${attachment.openable ? `<a href="/api/library/${state.libraryId}/attachments/${attachment.key}" target="_blank">${escapeHtml(title)}</a>` : `<strong>${escapeHtml(title)}</strong>`}
                  <small>${escapeHtml(attachment.status === "missing" ? "缺失" : attachment.path || attachment.content_type || "")}</small>
                `}
              </div>
              <div class="attachment-editor-actions">
                ${editing ? `
                  <button type="button" class="form-action-btn" data-save-attachment-rename="${escapeHtml(attachment.key)}">保存</button>
                  <button type="button" class="ghost-inline-btn" data-cancel-attachment-rename>取消</button>
                ` : `
                  <button type="button" class="ghost-inline-btn" data-edit-attachment-name="${escapeHtml(attachment.key)}">重命名</button>
                `}
              </div>
            </div>
          `;
        }).join("") || `<p class="muted">当前条目还没有附件。</p>`}
      </div>
      <div class="attachment-editor-toolbar">
        <button type="button" class="danger-btn" data-delete-selected-attachments ${state.selectedAttachmentKeys.size ? "" : "disabled"}>删除所选附件</button>
      </div>
      <div class="attachment-add-grid">
        <form class="attachment-add-form" data-add-file-attachment-form>
          <h3>上传本地文件</h3>
          <input type="file" name="file" data-file-attachment-input>
          <button type="submit" class="form-action-btn" ${state.attachmentEditorBusy ? "disabled" : ""}>上传附件</button>
        </form>
        <form class="attachment-add-form" data-add-url-attachment-form>
          <h3>添加网页链接</h3>
          <input name="url" placeholder="https://example.com">
          <input name="title" placeholder="链接标题（可选）">
          <button type="submit" class="form-action-btn" ${state.attachmentEditorBusy ? "disabled" : ""}>添加链接</button>
        </form>
      </div>
      ${state.attachmentEditorMessage ? `<p class="import-message" data-attachment-editor-message>${escapeHtml(state.attachmentEditorMessage)}</p>` : ""}
    </section>
  `;
  panel.querySelector("[data-close-attachment-editor]")?.addEventListener("click", closeAttachmentEditorModal);
  panel.querySelectorAll("[data-select-attachment]").forEach((input) => input.addEventListener("change", () => {
    if (input.checked) state.selectedAttachmentKeys.add(input.dataset.selectAttachment);
    else state.selectedAttachmentKeys.delete(input.dataset.selectAttachment);
    renderAttachmentEditorModal();
  }));
  panel.querySelectorAll("[data-edit-attachment-name]").forEach((button) => button.addEventListener("click", () => {
    const attachment = attachments.find((value) => value.key === button.dataset.editAttachmentName);
    state.editingAttachmentKey = button.dataset.editAttachmentName;
    state.editingAttachmentTitle = attachment?.display_label || attachment?.path || "";
    renderAttachmentEditorModal();
  }));
  panel.querySelectorAll("[data-cancel-attachment-rename]").forEach((button) => button.addEventListener("click", () => {
    state.editingAttachmentKey = "";
    state.editingAttachmentTitle = "";
    renderAttachmentEditorModal();
  }));
  panel.querySelectorAll("[data-save-attachment-rename]").forEach((button) => button.addEventListener("click", async () => {
    const row = button.closest("[data-attachment-editor-row]");
    const title = row?.querySelector("[data-attachment-rename-input]")?.value || "";
    await renameAttachment(button.dataset.saveAttachmentRename, title);
  }));
  panel.querySelector("[data-delete-selected-attachments]")?.addEventListener("click", deleteSelectedAttachments);
  panel.querySelector("[data-add-file-attachment-form]")?.addEventListener("submit", submitFileAttachment);
  panel.querySelector("[data-add-url-attachment-form]")?.addEventListener("submit", submitUrlAttachment);
}

function openAttachmentEditorModal() {
  const keys = selectedItemKeys();
  if (keys.length !== 1) {
    window.alert("附件编辑仅支持勾选一个条目。");
    return;
  }
  if (!state.library?.editable) {
    window.alert("只读源库不能编辑附件。请先创建本地副本。");
    return;
  }
  state.attachmentEditorItemKey = keys[0];
  state.attachmentEditorMessage = "";
  state.selectedAttachmentKeys = new Set();
  state.editingAttachmentKey = "";
  state.editingAttachmentTitle = "";
  document.querySelector("[data-attachment-editor-modal]").hidden = false;
  renderAttachmentEditorModal();
}

function closeAttachmentEditorModal() {
  const panel = document.querySelector("[data-attachment-editor-modal]");
  if (panel) panel.hidden = true;
}

async function refreshAfterAttachmentChange(message = "") {
  state.attachmentEditorMessage = message;
  await loadState();
  state.selectedAttachmentKeys = new Set([...state.selectedAttachmentKeys].filter((key) => {
    const item = currentAttachmentEditorItem();
    return (item?.attachments || []).some((attachment) => attachment.key === key);
  }));
  renderAttachmentEditorModal();
}

async function renameAttachment(attachmentKey, title) {
  const value = String(title || "").trim();
  if (!value) {
    state.attachmentEditorMessage = "附件名称不能为空。";
    renderAttachmentEditorModal();
    return;
  }
  try {
    state.attachmentEditorBusy = true;
    await postJSON(`/api/library/${state.libraryId}/attachments/${attachmentKey}`, { title: value }, "PATCH");
    state.editingAttachmentKey = "";
    state.editingAttachmentTitle = "";
    await refreshAfterAttachmentChange("附件已重命名。");
  } catch (error) {
    state.attachmentEditorMessage = error.message;
    renderAttachmentEditorModal();
  } finally {
    state.attachmentEditorBusy = false;
    renderAttachmentEditorModal();
  }
}

async function deleteSelectedAttachments() {
  const keys = [...state.selectedAttachmentKeys];
  if (!keys.length) return;
  if (!window.confirm(`确认删除 ${keys.length} 个附件？\n会删除本地副本中的附件记录和对应 storage 文件夹。`)) return;
  try {
    state.attachmentEditorBusy = true;
    await deleteJSON(`/api/library/${state.libraryId}/attachments/${keys[0]}`, { attachment_keys: keys });
    state.selectedAttachmentKeys = new Set();
    await refreshAfterAttachmentChange("附件已删除。");
  } catch (error) {
    state.attachmentEditorMessage = error.message;
    renderAttachmentEditorModal();
  } finally {
    state.attachmentEditorBusy = false;
    renderAttachmentEditorModal();
  }
}

async function submitFileAttachment(event) {
  event.preventDefault();
  const item = currentAttachmentEditorItem();
  const file = event.currentTarget.querySelector("[data-file-attachment-input]")?.files?.[0];
  if (!item || !file) {
    state.attachmentEditorMessage = "请选择要上传的文件。";
    renderAttachmentEditorModal();
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  try {
    state.attachmentEditorBusy = true;
    renderAttachmentEditorModal();
    const response = await fetch(`/api/library/${state.libraryId}/items/${item.key}/attachments/file`, { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || "上传附件失败");
    await refreshAfterAttachmentChange("附件已上传。");
  } catch (error) {
    state.attachmentEditorMessage = error.message;
    renderAttachmentEditorModal();
  } finally {
    state.attachmentEditorBusy = false;
    renderAttachmentEditorModal();
  }
}

async function submitUrlAttachment(event) {
  event.preventDefault();
  const item = currentAttachmentEditorItem();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  if (!item) return;
  try {
    state.attachmentEditorBusy = true;
    renderAttachmentEditorModal();
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/attachments/url`, payload);
    await refreshAfterAttachmentChange("链接附件已添加。");
  } catch (error) {
    state.attachmentEditorMessage = error.message;
    renderAttachmentEditorModal();
  } finally {
    state.attachmentEditorBusy = false;
    renderAttachmentEditorModal();
  }
}

function itemValue(item, key) {
  const structured = item.structured || {};
  switch (key) {
    case "title": return item.title || "未命名文献";
    case "remark": return structured.remark || "";
    case "title_zh": return structured.title_zh || "";
    case "abstract_zh": return structured.abstract_zh || "";
    case "creators": return item.creators_display || "";
    case "year": return item.year || "";
    case "venue": return item.venue || item.type || "";
    case "rating": return ratingLabelFromValues(item.semantic.rating);
    case "nested": return textOf(item.semantic.nested);
    case "venue_rank": return textOf(item.semantic.venue_rank);
    case "reading_status": return readingStatus(item).label;
    case "plain": return textOf(item.semantic.plain);
    case "collections": return textOf((item.collections || []).map((collection) => collection.name));
    default: return "";
  }
}

function structuredLabel(key) {
  return new Map([
    ["remark", "备注"],
    ["title_zh", "中文标题"],
    ["abstract_zh", "中文摘要"],
  ]).get(key) || key;
}

function isStructuredField(key) {
  return ["remark", "title_zh", "abstract_zh"].includes(key);
}

function isStructuredCellEditing(itemKey, field) {
  return state.editingStructuredCell?.itemKey === itemKey && state.editingStructuredCell?.field === field;
}

function notePreview(note) {
  const plain = String(note?.note || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  const expanded = state.expandedNotes.has(String(note?.item_id || note?.key || ""));
  if (expanded || plain.length <= 20) return { text: plain, truncated: false };
  return { text: `${plain.slice(0, 20)}...`, truncated: true };
}

function toggleNoteExpanded(note) {
  const key = String(note?.item_id || note?.key || "");
  if (!key) return;
  if (state.expandedNotes.has(key)) state.expandedNotes.delete(key);
  else state.expandedNotes.add(key);
  renderDetail();
}

function beginStructuredCellEdit(item, field) {
  state.editingStructuredCell = { itemKey: item.key, field };
  state.structuredCellDraft = item.structured?.[field] || "";
  renderTable();
}

function cancelStructuredCellEdit() {
  state.editingStructuredCell = null;
  state.structuredCellDraft = "";
  renderTable();
}

async function saveStructuredField(itemKey, field, value) {
  await postJSON(`/api/library/${state.libraryId}/items/${itemKey}/structured-field`, { field, value }, "PATCH");
  state.editingStructuredCell = null;
  state.structuredCellDraft = "";
  await loadState();
}

function setupSourceForms() {
  document.querySelectorAll("[data-source-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(form).entries());
      const mode = form.dataset.mode;
      const url = mode === "local-copy" ? "/api/sources/local-copy" : "/api/sources/read-only";
      const button = form.querySelector("button");
      const oldText = button.textContent;
      button.textContent = "处理中...";
      button.disabled = true;
      try {
        const data = await postJSON(url, payload);
        window.location.href = `/library/${data.library.library_id}`;
      } catch (error) {
        window.alert(error.message);
      } finally {
        button.textContent = oldText;
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll("[data-delete-source]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      const id = button.dataset.deleteSource;
      if (!window.confirm(button.dataset.confirm || "确认删除这个配置？")) return;
      try {
        await deleteJSON(`/api/sources/${id}?confirm=1`);
        window.location.reload();
      } catch (error) {
        window.alert(error.message);
      }
    });
  });
}

function sortedCollections() {
  const byParent = new Map();
  state.collections.forEach((collection) => {
    const parent = collection.parent_id || "";
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent).push(collection);
  });
  byParent.forEach((list) => list.sort((a, b) => a.name.localeCompare(b.name, "zh-Hans-CN")));
  const result = [];
  function visit(parent, depth) {
    (byParent.get(parent) || []).forEach((collection) => {
      result.push({ ...collection, depth });
      visit(collection.collection_id, depth + 1);
    });
  }
  visit("", 0);
  return result;
}

function collectionMoveOptions(excludeKey = "") {
  const excluded = new Set();
  if (excludeKey) {
    const target = state.collections.find((collection) => collection.key === excludeKey);
    if (target) {
      excluded.add(target.collection_id);
      let changed = true;
      while (changed) {
        changed = false;
        state.collections.forEach((collection) => {
          if (collection.parent_id && excluded.has(collection.parent_id) && !excluded.has(collection.collection_id)) {
            excluded.add(collection.collection_id);
            changed = true;
          }
        });
      }
    }
  }
  return sortedCollections().filter((collection) => !excluded.has(collection.collection_id));
}

function collectionSelectOptions({ includeRoot = true, excludeKey = "", selectedKey = "" } = {}) {
  const root = includeRoot ? `<option value="" ${!selectedKey ? "selected" : ""}>根目录</option>` : "";
  return root + collectionMoveOptions(excludeKey).map((collection) => {
    const indent = "　".repeat(collection.depth || 0);
    return `<option value="${escapeHtml(collection.key)}" ${selectedKey === collection.key ? "selected" : ""}>${indent}${escapeHtml(collection.name)}</option>`;
  }).join("");
}

function renderCollectionInlinePanel(collection) {
  if (!state.library?.editable) return "";
  const isRoot = collection.key === "__root";
  const isActive = state.activeCollectionMenuKey === collection.key;
  const isEditing = state.editingCollectionKey === collection.key;
  const isMoving = state.movingCollectionKey === collection.key;
  const isCreating = state.creatingCollectionParentKey === collection.key;
  if (!isActive && !isEditing && !isMoving && !isCreating) return "";
  return `
    <div class="collection-inline-panel" data-collection-inline-panel="${escapeHtml(collection.key)}" style="--depth:${collection.depth || 0}">
      ${isActive ? `
        <div class="collection-menu" data-collection-menu-panel>
          ${isRoot ? "" : `
            <button type="button" data-rename-collection="${escapeHtml(collection.key)}">重命名</button>
            <button type="button" data-move-collection="${escapeHtml(collection.key)}">移动到</button>
            <button type="button" data-delete-collection="${escapeHtml(collection.key)}">删除</button>
          `}
          <button type="button" data-create-child-collection="${escapeHtml(collection.key)}">${isRoot ? "在根目录下新建文件夹" : "当前目录下新建文件夹"}</button>
        </div>
      ` : ""}
      ${isEditing ? `
        <form class="collection-inline-form" data-rename-collection-form="${escapeHtml(collection.key)}">
          <input name="name" value="${escapeHtml(state.editingCollectionName || collection.name)}" placeholder="文件夹名称">
          <button type="submit" class="form-action-btn">保存</button>
          <button type="button" class="ghost-inline-btn" data-cancel-collection-edit>取消</button>
        </form>
      ` : ""}
      ${isMoving ? `
        <form class="collection-inline-form" data-move-collection-form="${escapeHtml(collection.key)}">
          <select name="parent_key">${collectionSelectOptions({ includeRoot: true, excludeKey: collection.key, selectedKey: state.movingCollectionTargetKey })}</select>
          <button type="submit" class="form-action-btn">移动</button>
          <button type="button" class="ghost-inline-btn" data-cancel-collection-edit>取消</button>
        </form>
      ` : ""}
      ${isCreating ? `
        <form class="collection-inline-form" data-create-child-collection-form="${escapeHtml(collection.key)}">
          <input name="name" value="${escapeHtml(state.creatingCollectionName)}" placeholder="新文件夹名称">
          <button type="submit" class="form-action-btn">新建</button>
          <button type="button" class="ghost-inline-btn" data-cancel-collection-edit>取消</button>
        </form>
      ` : ""}
    </div>
  `;
}

function clearCollectionInlineState() {
  state.activeCollectionMenuKey = "";
  state.editingCollectionKey = "";
  state.editingCollectionName = "";
  state.movingCollectionKey = "";
  state.movingCollectionTargetKey = "";
  state.creatingCollectionParentKey = "";
  state.creatingCollectionName = "";
}

function renderTree() {
  const tree = document.querySelector("[data-tree]");
  if (!tree) return;
  const countsByCollection = new Map();
  state.items.forEach((item) => {
    (item.collections || []).forEach((collection) => {
      countsByCollection.set(collection.key, (countsByCollection.get(collection.key) || 0) + 1);
    });
  });
  const nodes = [
    { key: "", name: "全部条目", depth: 0, count: state.items.length, virtual: true },
    { key: "__recent", name: "最近添加", depth: 0, count: state.items.length, virtual: true },
    { key: "__unfiled", name: "未分类条目", depth: 0, count: state.items.filter((item) => !item.collections.length).length, virtual: true },
    { key: "__trash", name: "回收站", depth: 0, count: state.items.filter((item) => item.deleted).length, virtual: true },
    { key: "__root", name: "根目录", depth: 0, count: sortedCollections().filter((collection) => !collection.parent_id).length, virtual: true, manageableRoot: true },
    ...sortedCollections().map((collection) => ({ ...collection, count: countsByCollection.get(collection.key) || 0, virtual: false })),
  ];
  tree.innerHTML = nodes.map((node) => `
    <div class="tree-row ${state.selectedCollectionKey === node.key ? "active" : ""} ${node.virtual ? "virtual" : ""} ${node.manageableRoot ? "manageable-root" : ""}" style="--depth:${node.depth || 0}">
      <button class="tree-node" ${node.manageableRoot ? "data-root-tree-node" : `data-tree-key="${node.key}"`}>
        <span class="label">${escapeHtml(node.name)}</span><span class="tree-count">${node.count}</span>
      </button>
      ${(!node.virtual || node.manageableRoot) && state.library?.editable ? `<button type="button" class="tree-action-btn" data-collection-menu="${escapeHtml(node.key)}" title="${node.manageableRoot ? "在根目录下新建文件夹" : "管理文件夹"}">✎</button>` : ""}
    </div>
    ${(!node.virtual || node.manageableRoot) ? renderCollectionInlinePanel(node) : ""}
  `).join("");
  tree.querySelectorAll("[data-tree-key]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedCollectionKey = button.dataset.treeKey;
      clearCollectionInlineState();
      applyFilters();
    });
  });
  tree.querySelectorAll("[data-collection-menu]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    const key = button.dataset.collectionMenu;
    clearCollectionInlineState();
    state.activeCollectionMenuKey = key;
    renderTree();
  }));
  tree.querySelectorAll("[data-rename-collection]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.renameCollection;
    const collection = state.collections.find((value) => value.key === key);
    clearCollectionInlineState();
    state.editingCollectionKey = key;
    state.editingCollectionName = collection?.name || "";
    renderTree();
  }));
  tree.querySelectorAll("[data-move-collection]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.moveCollection;
    const collection = state.collections.find((value) => value.key === key);
    clearCollectionInlineState();
    state.movingCollectionKey = key;
    state.movingCollectionTargetKey = state.collections.find((value) => value.collection_id === collection?.parent_id)?.key || "";
    renderTree();
  }));
  tree.querySelectorAll("[data-create-child-collection]").forEach((button) => button.addEventListener("click", () => {
    clearCollectionInlineState();
    const parentKey = button.dataset.createChildCollection;
    state.creatingCollectionParentKey = parentKey === "__root" ? "__root" : parentKey;
    state.creatingCollectionName = "";
    renderTree();
  }));
  tree.querySelectorAll("[data-delete-collection]").forEach((button) => button.addEventListener("click", async () => {
    const collection = state.collections.find((value) => value.key === button.dataset.deleteCollection);
    if (!collection) return;
    if (!window.confirm(`删除文件夹“${collection.name}”？\n只会删除文件夹结构和条目归属，不会删除条目或附件。`)) return;
    await deleteJSON(`/api/library/${state.libraryId}/collections/${collection.key}`);
    if (state.selectedCollectionKey === collection.key) state.selectedCollectionKey = "";
    clearCollectionInlineState();
    await loadState();
  }));
  tree.querySelectorAll("[data-cancel-collection-edit]").forEach((button) => button.addEventListener("click", () => {
    clearCollectionInlineState();
    renderTree();
  }));
  tree.querySelectorAll("[data-rename-collection-form]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = form.dataset.renameCollectionForm;
    const name = String(new FormData(form).get("name") || "").trim();
    if (!name) return;
    await postJSON(`/api/library/${state.libraryId}/collections/${key}`, { name }, "PATCH");
    clearCollectionInlineState();
    await loadState();
  }));
  tree.querySelectorAll("[data-move-collection-form]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = form.dataset.moveCollectionForm;
    const parentKey = String(new FormData(form).get("parent_key") || "").trim();
    await postJSON(`/api/library/${state.libraryId}/collections/${key}`, { parent_key: parentKey }, "PATCH");
    clearCollectionInlineState();
    await loadState();
  }));
  tree.querySelectorAll("[data-create-child-collection-form]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const parentKey = form.dataset.createChildCollectionForm === "__root" ? "" : form.dataset.createChildCollectionForm;
    const name = String(new FormData(form).get("name") || "").trim();
    if (!name) return;
    await postJSON(`/api/library/${state.libraryId}/collections`, { name, parent_key: parentKey });
    clearCollectionInlineState();
    await loadState();
  }));
}

function renderTagFilters() {
  const buckets = ["rating", "type", "nested", "venue_rank", "reading_status", "plain"];
  buckets.forEach((bucket) => {
    const host = document.querySelector(`[data-semantic-filter="${bucket}"]`);
    if (!host) return;
    if (bucket === "plain" && state.plainCollapsed) {
      host.innerHTML = "";
      return;
    }
    const counts = new Map();
    state.items.forEach((item) => {
      if (bucket === "type") {
        const typeKey = normalizeItemTypeKey(item.type);
        if (typeKey) counts.set(typeKey, (counts.get(typeKey) || 0) + 1);
        return;
      }
      if (bucket === "reading_status") {
        const label = readingStatus(item).label;
        counts.set(label, (counts.get(label) || 0) + 1);
        return;
      }
      (item.semantic[bucket] || []).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1));
    });
    let entries = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"));
    const search = document.querySelector("[data-tag-search]")?.value?.trim().toLowerCase() || "";
    if (bucket === "plain" && search) entries = entries.filter(([tag]) => tag.toLowerCase().includes(search));
    host.innerHTML = entries.slice(0, bucket === "plain" ? 80 : 60).map(([tag, count]) => {
      const selected = state.selectedTags.get(bucket)?.has(tag);
      const color = bucket === "nested" || bucket === "plain"
        ? `style="--tag-color:${tagColor(tag)}"`
        : (bucket === "type" ? `style="--tag-color:${itemTypeMeta(tag).color}"` : "");
      const label = bucket === "nested"
        ? displayHashTag(tag)
        : (bucket === "rating" ? ratingLabelFromValues([tag]) : (bucket === "type" ? itemTypeLabel(tag) : tag));
      return `<button class="tag-chip ${selected ? "active" : ""}" ${color} data-bucket="${bucket}" data-tag="${escapeHtml(tag)}">${escapeHtml(label)} ${count}</button>`;
    }).join("") || `<span class="muted">暂无</span>`;
    host.querySelectorAll("[data-tag]").forEach((button) => {
      button.addEventListener("click", () => {
        const set = state.selectedTags.get(bucket) || new Set();
        if (set.has(button.dataset.tag)) set.delete(button.dataset.tag);
        else set.add(button.dataset.tag);
        state.selectedTags.set(bucket, set);
        applyFilters();
      });
    });
  });
}

function setupPlainToggle() {
  const toggle = document.querySelector("[data-toggle-plain-tags]");
  if (!toggle) return;
  toggle.textContent = state.plainCollapsed ? "▶ 普通标签" : "▼ 普通标签";
  document.querySelector("[data-plain-tags-body]").hidden = state.plainCollapsed;
}

function matchesSelectedTags(item) {
  for (const [bucket, tags] of state.selectedTags.entries()) {
    if (!tags.size) continue;
    const values = bucket === "reading_status"
      ? new Set([readingStatus(item).label])
      : (bucket === "type" ? new Set([normalizeItemTypeKey(item.type)].filter(Boolean)) : new Set(item.semantic[bucket] || []));
    for (const tag of tags) {
      if (!values.has(tag)) return false;
    }
  }
  return true;
}

function applyFilters() {
  const query = state.search.toLowerCase();
  state.filteredItems = state.items.filter((item) => {
    if (state.selectedCollectionKey === "__unfiled" && item.collections.length) return false;
    if (state.selectedCollectionKey === "__trash" && !item.deleted) return false;
    if (state.selectedCollectionKey && !state.selectedCollectionKey.startsWith("__")) {
      if (!item.collections.some((collection) => collection.key === state.selectedCollectionKey)) return false;
    }
    if (!matchesSelectedTags(item)) return false;
    if (query) {
      const haystack = [
        item.title,
        item.creators_full_display,
        item.creators_display,
        item.venue,
        item.type,
        normalizeItemTypeKey(item.type),
        itemTypeLabel(item.type),
        item.tags.join(" "),
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
  renderTree();
  setupPlainToggle();
  renderTagFilters();
  renderTable();
}

function attachmentBadgeClass(label, missing = false) {
  if (missing) return "missing";
  return String(label || "file").toLowerCase().replace(/[^a-z]/g, "") || "file";
}

function renderTitleCell(item) {
  const typeMeta = itemTypeMeta(item.type);
  const badges = (item.attachment_badges || []).map((badge) => {
    const cls = attachmentBadgeClass(badge.label, badge.missing);
    const title = badge.missing ? "附件文件缺失" : "";
    return `<span class="attachment-badge ${cls}" title="${title}">${escapeHtml(badge.label)} ${badge.count}</span>`;
  }).join("");
  return `
    <div class="title-stack">
      <div class="title-primary">
        <span class="type-badge type-group-${typeMeta.group}" style="--type-color:${typeMeta.color}" title="${escapeHtml(typeMeta.raw || typeMeta.labelZh)}">${escapeHtml(typeMeta.labelZh)}</span>
        <span class="title-text">${escapeHtml(item.title || "未命名文献")}</span>
      </div>
      ${badges ? `<div class="title-secondary">${badges}</div>` : ""}
    </div>
  `;
}

function ratingCount(item) {
  return ratingNumberFromValues(item.semantic?.rating || []);
}

function paintRating(host, value) {
  host.querySelectorAll("[data-rating]").forEach((button) => {
    button.classList.toggle("lit", Number(button.dataset.rating) <= value);
  });
}

function renderRatingCell(item) {
  const count = ratingCount(item);
  if (!state.library?.editable) return `<span class="rating-readonly">${RATING_CONTROL_STAR.repeat(count) || "-"}</span>`;
  return `<div class="rating-control" data-rating-item="${item.key}" data-current-rating="${count}">
    ${[1, 2, 3, 4, 5].map((value) => `<button type="button" data-rating="${value}" class="${value <= count ? "lit" : ""}">${RATING_CONTROL_STAR}</button>`).join("")}
  </div>`;
}

function renderNestedCell(item) {
  const tags = item.semantic.nested || [];
  if (!state.library?.editable) {
    return tags.map((tag) => `<span class="colored-tag" style="--tag-color:${tagColor(tag)}" title="${escapeHtml(tag)}">${escapeHtml(displayHashTag(tag))}</span>`).join(" ");
  }
  const chips = tags.map((tag) => `
    <button class="colored-tag tag-cell-chip" type="button" data-tag-popover="${item.key}" data-focus-tag="${escapeHtml(tag)}" style="--tag-color:${tagColor(tag)}" title="${escapeHtml(tag)}">
      ${escapeHtml(displayHashTag(tag))}
    </button>`).join("");
  const add = `<button class="add-tag-chip" type="button" data-tag-popover="${item.key}">+ 标签</button>`;
  return `${chips}${add}`;
}

function renderReadingCell(item) {
  const status = readingStatus(item);
  const editable = Boolean(state.library?.editable);
  return `<button class="reading-chip ${status.key}" type="button" ${editable ? `data-reading-popover="${item.key}"` : "disabled"}>${status.label}</button>`;
}

function renderStructuredCell(item, field) {
  const value = item.structured?.[field] || "";
  const editable = Boolean(state.library?.editable);
  if (!editable) {
    return `<div class="structured-preview" title="${escapeHtml(value)}">${escapeHtml(value || "-")}</div>`;
  }
  if (isStructuredCellEditing(item.key, field)) {
    const isLongText = field !== "title_zh";
    const input = isLongText
      ? `<textarea data-structured-cell-input="${field}" rows="${field === "abstract_zh" ? "4" : "3"}">${escapeHtml(state.structuredCellDraft)}</textarea>`
      : `<input data-structured-cell-input="${field}" value="${escapeHtml(state.structuredCellDraft)}">`;
    return `
      <div class="structured-cell-editor" data-structured-cell-editor="${item.key}:${field}">
        ${input}
        <div class="structured-cell-actions">
          <button type="button" class="form-action-btn" data-save-structured-cell="${item.key}" data-structured-field="${field}">保存</button>
          <button type="button" class="ghost-inline-btn" data-cancel-structured-cell>取消</button>
        </div>
      </div>
    `;
  }
  return `
    <div class="structured-cell-display">
      <div class="structured-preview" title="${escapeHtml(value)}">${escapeHtml(value || "-")}</div>
      <button type="button" class="mini-icon structured-edit-btn" data-edit-structured-cell="${item.key}" data-structured-field="${field}" title="编辑${structuredLabel(field)}">✎</button>
    </div>
  `;
}

function renderTableCell(item, key) {
  if (key === "title") return renderTitleCell(item);
  if (isStructuredField(key)) return renderStructuredCell(item, key);
  if (key === "rating") return renderRatingCell(item);
  if (key === "nested") return renderNestedCell(item);
  if (key === "reading_status") return renderReadingCell(item);
  if (key === "plain") {
    return (item.semantic[key] || []).map((tag) => `<span class="colored-tag" style="--tag-color:${tagColor(tag)}">${escapeHtml(tag)}</span>`).join(" ");
  }
  return escapeHtml(itemValue(item, key));
}

function renderTable() {
  const head = document.querySelector("[data-table-head]");
  const body = document.querySelector("[data-table-body]");
  if (!head || !body) return;
  const labels = new Map(ALL_COLUMNS);
  const columns = (state.columns.length ? state.columns : DEFAULT_COLUMNS).filter((key) => labels.has(key));
  const allFilteredSelected = isAllFilteredSelected();
  head.innerHTML = `<tr>
    <th class="selection-col selection-head-cell">
      <button type="button" class="selection-toggle-btn ${allFilteredSelected ? "active" : ""}" data-toggle-select-all title="${allFilteredSelected ? "取消全选当前筛选结果" : "全选当前筛选结果"}">
        ${allFilteredSelected ? "☒" : "☐"}
      </button>
    </th>${columns.map((key) => `
    <th data-column-key="${key}" style="${state.columnWidths[key] ? `width:${state.columnWidths[key]}px` : ""}">
      <span>${labels.get(key) || key}</span><span class="resize-handle" data-resize-column="${key}"></span>
    </th>`).join("")}</tr>`;
  body.innerHTML = state.filteredItems.map((item) => `
    <tr data-item-key="${item.key}" class="${state.selectedItem?.key === item.key ? "selected" : ""}">
      <td class="selection-col selection-cell">
        <input type="checkbox" class="row-checkbox" data-row-select="${item.key}" ${isItemChecked(item.key) ? "checked" : ""} aria-label="选择条目">
      </td>
      ${columns.map((key) => `<td class="${key === "title" ? "title-cell" : ""}" style="${state.columnWidths[key] ? `width:${state.columnWidths[key]}px` : ""}">${renderTableCell(item, key)}</td>`).join("")}
    </tr>
  `).join("");
  head.querySelector("[data-toggle-select-all]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    if (isAllFilteredSelected()) clearFilteredSelection();
    else selectAllFilteredItems();
    renderTable();
  });
  body.querySelectorAll("[data-row-select]").forEach((input) => input.addEventListener("click", (event) => {
    event.stopPropagation();
  }));
  body.querySelectorAll("[data-row-select]").forEach((input) => input.addEventListener("change", (event) => {
    toggleItemChecked(input.dataset.rowSelect, event.target.checked);
    renderTable();
  }));
  body.querySelectorAll("[data-item-key]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("button") || event.target.closest("input")) return;
      state.selectedItem = state.items.find((item) => item.key === row.dataset.itemKey) || null;
      renderTable();
      renderDetail();
    });
  });
  body.querySelectorAll("[data-tag-popover]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    state.activePopoverItemKey = button.dataset.tagPopover;
    renderTagPopover(button);
  }));
  body.querySelectorAll("[data-reading-popover]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    renderReadingPopover(button);
  }));
  body.querySelectorAll("[data-edit-structured-cell]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    const item = state.items.find((value) => value.key === button.dataset.editStructuredCell);
    if (!item) return;
    beginStructuredCellEdit(item, button.dataset.structuredField);
  }));
  body.querySelectorAll("[data-cancel-structured-cell]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    cancelStructuredCellEdit();
  }));
  body.querySelectorAll("[data-save-structured-cell]").forEach((button) => button.addEventListener("click", async (event) => {
    event.stopPropagation();
    const editor = button.closest("[data-structured-cell-editor]");
    const input = editor?.querySelector("[data-structured-cell-input]");
    await saveStructuredField(button.dataset.saveStructuredCell, button.dataset.structuredField, input?.value || "");
  }));
  body.querySelectorAll("[data-structured-cell-input]").forEach((input) => input.addEventListener("click", (event) => event.stopPropagation()));
  body.querySelectorAll("[data-rating-item]").forEach((host) => {
    const current = Number(host.dataset.currentRating || 0);
    host.querySelectorAll("button").forEach((button) => {
      button.addEventListener("mouseenter", () => paintRating(host, Number(button.dataset.rating)));
      button.addEventListener("click", async (event) => {
        event.stopPropagation();
        await postJSON(`/api/library/${state.libraryId}/items/${host.dataset.ratingItem}/rating`, { rating: Number(button.dataset.rating) }, "PATCH");
        await loadState();
      });
    });
    host.addEventListener("mouseleave", () => paintRating(host, current));
  });
  setupColumnResize();
  document.querySelector("[data-visible-count]").textContent = String(state.filteredItems.length);
  document.querySelector("[data-total-count]").textContent = String(state.items.length);
  document.querySelector("[data-selected-count]").textContent = String(totalSelectedCount());
}

function setupColumnResize() {
  document.querySelectorAll("[data-resize-column]").forEach((handle) => {
    handle.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const key = handle.dataset.resizeColumn;
      const th = handle.closest("th");
      const startX = event.clientX;
      const startWidth = th.getBoundingClientRect().width;
      const onMove = (moveEvent) => {
        state.columnWidths[key] = Math.max(60, Math.round(startWidth + moveEvent.clientX - startX));
        renderTable();
      };
      const onUp = async () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        await postJSON(`/api/library/${state.libraryId}/preferences/column-widths`, { widths: state.columnWidths });
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

function positionPanel(panel, anchor, width = 360) {
  const rect = anchor.getBoundingClientRect();
  panel.style.left = `${Math.max(12, Math.min(window.innerWidth - width - 12, rect.left))}px`;
  panel.style.top = `${rect.bottom + 8}px`;
}

function rerenderActiveTagPopover() {
  const panel = document.querySelector("[data-tag-popover-panel]");
  if (!panel) return;
  const anchor = state.activePopoverItemKey ? document.querySelector(`[data-tag-popover="${state.activePopoverItemKey}"]`) : null;
  if (!anchor) {
    panel.remove();
    state.activePopoverItemKey = "";
    return;
  }
  renderTagPopover(anchor);
}

function renderTagPopover(anchor) {
  if (!state.library?.editable) return;
  const item = state.items.find((value) => value.key === state.activePopoverItemKey);
  if (!item) return;
  const currentTags = (item.semantic?.nested || []).map((tag) => normalizeHashTag(tag)).filter(Boolean);
  const currentTagSet = new Set(currentTags);
  const availableShortcuts = state.tagShortcuts
    .map((shortcut) => normalizeHashTag(shortcut.tag))
    .filter((tag, index, values) => tag && values.indexOf(tag) === index && !currentTagSet.has(tag));
  let panel = document.querySelector("[data-tag-popover-panel]");
  if (!panel) {
    panel = document.createElement("div");
    panel.className = "tag-popover";
    panel.dataset.tagPopoverPanel = "1";
    document.body.appendChild(panel);
  }
  positionPanel(panel, anchor, 420);
  panel.innerHTML = `
    <div class="popover-head">
      <strong>快捷标签</strong>
      <button type="button" class="tag-icon-btn" data-close-popover>×</button>
    </div>
    <section class="popover-section">
      <h4>当前条目标签</h4>
      <div class="shortcut-grid" data-current-tag-list>
        ${currentTags.map((tag) => `
          <label class="shortcut-pill shortcut-pill-toggle" style="--tag-color:${tagColor(tag)}" title="${escapeHtml(tag)}">
            <input type="checkbox" data-current-tag-toggle="${escapeHtml(tag)}" checked>
            <span>${escapeHtml(displayHashTag(tag))}</span>
          </label>
        `).join("") || `<span class="muted">当前条目还没有 # 标签</span>`}
      </div>
    </section>
    <section class="popover-section">
      <h4>快捷标签</h4>
      <div class="shortcut-grid" data-shortcut-list>
        ${availableShortcuts.map((tag) => `
          <label class="shortcut-pill shortcut-pill-toggle" style="--tag-color:${tagColor(tag)}" title="${escapeHtml(tag)}">
            <input type="checkbox" data-shortcut-add-tag="${escapeHtml(tag)}">
            <span>${escapeHtml(displayHashTag(tag))}</span>
            <button type="button" class="tag-delete-btn" data-delete-shortcut="${escapeHtml(tag)}" title="从快捷标签删除">×</button>
          </label>
        `).join("") || `<span class="muted">没有可添加的快捷标签</span>`}
      </div>
      <form class="inline-form" data-shortcut-form>
        <input name="tag" placeholder="新增标签，例如 VLA/端到端">
        <button type="submit" class="form-action-btn">添加</button>
      </form>
    </section>
  `;
  panel.querySelector("[data-close-popover]").addEventListener("click", () => {
    panel.remove();
    state.activePopoverItemKey = "";
  });
  panel.querySelectorAll("[data-current-tag-toggle]").forEach((input) => input.addEventListener("change", async () => {
    const tag = normalizeHashTag(input.dataset.currentTagToggle);
    await deleteJSON(`/api/library/${state.libraryId}/items/${item.key}/tags`, { tag });
    await loadState();
    rerenderActiveTagPopover();
  }));
  panel.querySelectorAll("[data-shortcut-add-tag]").forEach((input) => input.addEventListener("change", async () => {
    const tag = normalizeHashTag(input.dataset.shortcutAddTag);
    if (!input.checked) return;
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/tags`, { tag });
    await loadState();
    rerenderActiveTagPopover();
  }));
  panel.querySelectorAll("[data-delete-shortcut]").forEach((button) => button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    await deleteJSON(`/api/library/${state.libraryId}/tag-shortcuts`, { tag: normalizeHashTag(button.dataset.deleteShortcut) });
    await loadState();
    rerenderActiveTagPopover();
  }));
  panel.querySelector("[data-shortcut-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const tag = normalizeHashTag(new FormData(event.currentTarget).get("tag"));
    if (!tag || tag === "#") return;
    await postJSON(`/api/library/${state.libraryId}/tag-shortcuts`, { tag });
    await loadState();
    rerenderActiveTagPopover();
  });
}

function renderReadingPopover(anchor) {
  const item = state.items.find((value) => value.key === anchor.dataset.readingPopover);
  if (!item) return;
  let panel = document.querySelector("[data-reading-popover-panel]");
  if (!panel) {
    panel = document.createElement("div");
    panel.className = "reading-popover";
    panel.dataset.readingPopoverPanel = "1";
    document.body.appendChild(panel);
  }
  positionPanel(panel, anchor, 180);
  const current = readingStatus(item).key;
  const options = [
    ["unread", "未读"],
    ["reading", "在读"],
    ["read", "已读"],
  ];
  panel.innerHTML = options.map(([key, label]) => `<button type="button" class="reading-option ${key} ${key === current ? "active" : ""}" data-reading-status="${key}">${label}</button>`).join("");
  panel.querySelectorAll("[data-reading-status]").forEach((button) => button.addEventListener("click", async () => {
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/reading-status`, { status: button.dataset.readingStatus }, "PATCH");
    panel.remove();
    await loadState();
  }));
}

function renderDetail() {
  const detail = document.querySelector("[data-detail]");
  const type = document.querySelector("[data-detail-type]");
  const item = state.selectedItem;
  if (!detail || !type) return;
  if (!item) {
    type.textContent = "未选择";
    detail.className = "detail-empty";
    detail.textContent = "从中间表格选择一篇文献。";
    return;
  }
  type.textContent = itemTypeLabel(item.type);
  const editable = Boolean(state.library?.editable);
  const structured = item.structured || {};
  const detailDraft = state.detailStructuredDraft;
  detail.className = "detail-scroll";
  detail.innerHTML = `
    <section class="detail-card">
      <h3>${escapeHtml(item.title)}</h3>
      <p class="muted">${escapeHtml(item.creators_full_display || item.creators_display)} / ${escapeHtml(item.year)} / ${escapeHtml(item.venue || itemTypeLabel(item.type))}</p>
      <p>${escapeHtml(item.fields.abstractNote || "暂无摘要")}</p>
    </section>
    <section class="detail-card">
      <h3>语义标签</h3>
      <div class="field-grid">
        <span>评分</span><strong>${escapeHtml(ratingLabelFromValues(item.semantic.rating) || "-")}</strong>
        <span>#标签</span><strong>${(item.semantic.nested || []).map((tag) => `<span class="colored-tag" style="--tag-color:${tagColor(tag)}" title="${escapeHtml(tag)}">${escapeHtml(displayHashTag(tag))}</span>`).join(" ") || "-"}</strong>
        <span>阅读状态</span><strong><span class="reading-chip ${readingStatus(item).key}">${readingStatus(item).label}</span></strong>
        <span>期刊等级</span><strong>${escapeHtml(textOf(item.semantic.venue_rank) || "-")}</strong>
        <span>普通标签</span><strong>${escapeHtml(textOf(item.semantic.plain) || "-")}</strong>
      </div>
      ${editable ? `<p class="muted">请在条目表格的 #标签 弹层里管理当前条目和快捷标签。</p>` : `<p class="muted">只读连接模式不能修改标签。</p>`}
    </section>
    <section class="detail-card">
      <div class="detail-card-head">
        <h3>结构化字段</h3>
        ${editable ? `<button type="button" class="ghost-btn" data-toggle-structured-detail>${state.detailStructuredEditing ? "取消编辑" : "编辑结构化字段"}</button>` : ""}
      </div>
      ${state.detailStructuredEditing ? `
      <form class="structured-detail-form" data-structured-detail-form>
        <label class="structured-detail-row">
          <span>备注</span>
          <textarea name="remark" rows="4">${escapeHtml(detailDraft.remark || "")}</textarea>
        </label>
        <label class="structured-detail-row">
          <span>中文标题</span>
          <input name="title_zh" value="${escapeHtml(detailDraft.title_zh || "")}">
        </label>
        <label class="structured-detail-row">
          <span>中文摘要</span>
          <textarea name="abstract_zh" rows="6">${escapeHtml(detailDraft.abstract_zh || "")}</textarea>
        </label>
        <div class="structured-detail-actions">
          <button type="submit" class="form-action-btn">保存</button>
        </div>
      </form>` : `
      <div class="field-grid structured-field-grid">
        <span>备注</span><strong>${escapeHtml(structured.remark || "-")}</strong>
        <span>中文标题</span><strong>${escapeHtml(structured.title_zh || "-")}</strong>
        <span>中文摘要</span><strong>${escapeHtml(structured.abstract_zh || "-")}</strong>
      </div>`}
    </section>
    <section class="detail-card">
      <h3>附件与笔记</h3>
      ${(item.attachments || []).map((attachment) => `
        <p class="attachment-line">
          ${attachment.openable ? `<a href="/api/library/${state.libraryId}/attachments/${attachment.key}" target="_blank">${escapeHtml(attachment.display_label)}</a>` : `<span class="muted" title="附件文件缺失或不可直接打开">${escapeHtml(attachment.display_label)}</span>`}
          <span class="attachment-badge ${attachmentBadgeClass(attachment.kind, attachment.status === "missing")}">${escapeHtml(attachment.kind)} ${attachment.status === "missing" ? "缺失" : escapeHtml(attachment.status)}</span>
        </p>
      `).join("") || `<p class="muted">没有文件附件</p>`}
      ${(item.notes || []).map((note) => {
        const preview = notePreview(note);
        return `
          <p class="note-line">
            <strong>笔记</strong> ${escapeHtml(preview.text || "-")}
            ${preview.truncated || state.expandedNotes.has(String(note.item_id || note.key || "")) ? `<button type="button" class="note-toggle-btn" data-note-toggle="${escapeHtml(String(note.item_id || note.key || ""))}" title="${state.expandedNotes.has(String(note.item_id || note.key || "")) ? "收起" : "展开"}">${state.expandedNotes.has(String(note.item_id || note.key || "")) ? "⌃" : "⌄"}</button>` : ""}
          </p>
        `;
      }).join("") || `<p class="muted">没有笔记</p>`}
    </section>
    <section class="detail-card">
      <h3>所在文件夹</h3>
      <div class="field-grid">
        <span>当前</span><strong>${escapeHtml(textOf((item.collections || []).map((collection) => collection.name)) || "未分类")}</strong>
      </div>
      <p class="muted">文件夹归属请在条目表批量选择后使用“移动条目”。</p>
    </section>
    <section class="detail-card">
      <h3>原生字段</h3>
      <div class="field-grid">${Object.entries(item.fields).map(([key, value]) => `<span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong>`).join("")}</div>
      ${editable ? `
      <form class="inline-form" data-edit-field-form>
        <select name="field">
          <option value="title">title</option>
          <option value="publicationTitle">publicationTitle</option>
          <option value="date">date</option>
          <option value="DOI">DOI</option>
          <option value="url">url</option>
          <option value="abstractNote">abstractNote</option>
          <option value="extra">extra</option>
        </select>
        <input name="value" placeholder="新值">
        <button type="submit" class="form-action-btn">保存</button>
      </form>` : ""}
    </section>
  `;
  detail.querySelector("[data-edit-field-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/field`, payload, "PATCH");
    await loadState();
  });
  detail.querySelectorAll("[data-note-toggle]").forEach((button) => button.addEventListener("click", () => {
    const note = (item.notes || []).find((value) => String(value.item_id || value.key || "") === button.dataset.noteToggle);
    if (!note) return;
    toggleNoteExpanded(note);
  }));
  detail.querySelector("[data-toggle-structured-detail]")?.addEventListener("click", () => {
    if (state.detailStructuredEditing) {
      state.detailStructuredEditing = false;
    } else {
      state.detailStructuredDraft = {
        remark: structured.remark || "",
        title_zh: structured.title_zh || "",
        abstract_zh: structured.abstract_zh || "",
      };
      state.detailStructuredEditing = true;
    }
    renderDetail();
  });
  detail.querySelector("[data-structured-detail-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    state.detailStructuredDraft = {
      remark: String(payload.remark || ""),
      title_zh: String(payload.title_zh || ""),
      abstract_zh: String(payload.abstract_zh || ""),
    };
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/structured-field`, { field: "remark", value: state.detailStructuredDraft.remark }, "PATCH");
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/structured-field`, { field: "title_zh", value: state.detailStructuredDraft.title_zh }, "PATCH");
    await postJSON(`/api/library/${state.libraryId}/items/${item.key}/structured-field`, { field: "abstract_zh", value: state.detailStructuredDraft.abstract_zh }, "PATCH");
    state.detailStructuredEditing = false;
    await loadState();
  });
}

function setupColumnsPanel() {
  document.querySelectorAll("[data-open-columns]").forEach((button) => button.addEventListener("click", () => {
    const active = new Set(state.columns);
    state.columnDraft = [...state.columns, ...ALL_COLUMNS.map(([key]) => key).filter((key) => !active.has(key))];
    renderColumnPanel();
    document.querySelector("[data-column-panel]").hidden = false;
  }));
  document.querySelector("[data-close-columns]")?.addEventListener("click", () => {
    document.querySelector("[data-column-panel]").hidden = true;
  });
  document.querySelector("[data-save-columns]")?.addEventListener("click", async () => {
    const columns = [...document.querySelectorAll("[data-column-check]")]
      .filter((input) => input.checked)
      .map((input) => input.value);
    await postJSON(`/api/library/${state.libraryId}/preferences/columns`, { columns });
    state.columns = columns;
    document.querySelector("[data-column-panel]").hidden = true;
    renderTable();
  });
}

function renderColumnPanel() {
  const host = document.querySelector("[data-column-list]");
  const active = new Set(state.columns);
  const ordered = state.columnDraft.length ? state.columnDraft : [...state.columns, ...ALL_COLUMNS.map(([key]) => key).filter((key) => !active.has(key))];
  const labels = new Map(ALL_COLUMNS);
  host.innerHTML = ordered.map((key, index) => `
    <label class="column-row">
      <input type="checkbox" data-column-check value="${key}" ${active.has(key) ? "checked" : ""}>
      <span>${labels.get(key) || key}</span>
      <button type="button" data-col-up="${index}">↑</button>
      <button type="button" data-col-down="${index}">↓</button>
    </label>
  `).join("");
  function move(index, delta) {
    const checked = new Map([...host.querySelectorAll("[data-column-check]")].map((input) => [input.value, input.checked]));
    const keys = [...host.querySelectorAll("[data-column-check]")].map((input) => input.value);
    const next = index + delta;
    if (next < 0 || next >= keys.length) return;
    [keys[index], keys[next]] = [keys[next], keys[index]];
    state.columnDraft = keys;
    state.columns = keys.filter((key) => checked.get(key));
    renderColumnPanel();
  }
  host.querySelectorAll("[data-col-up]").forEach((button) => button.addEventListener("click", () => move(Number(button.dataset.colUp), -1)));
  host.querySelectorAll("[data-col-down]").forEach((button) => button.addEventListener("click", () => move(Number(button.dataset.colDown), 1)));
}

async function loadState() {
  const data = await fetch(`/api/library/${state.libraryId}/state`).then((response) => response.json());
  if (!data.ok) throw new Error(data.error || "加载失败");
  state.library = data.library;
  state.items = data.items || [];
  const validKeys = new Set(state.items.map((item) => String(item.key || "")).filter(Boolean));
  state.selectedItemKeys = new Set([...state.selectedItemKeys].filter((key) => validKeys.has(key)));
  state.collections = data.collections || [];
  if (state.selectedCollectionKey && !state.selectedCollectionKey.startsWith("__") && !state.collections.some((collection) => collection.key === state.selectedCollectionKey)) {
    state.selectedCollectionKey = "";
  }
  state.tagShortcuts = data.tag_shortcuts || [];
  state.columns = (data.library.columns || DEFAULT_COLUMNS).filter((key) => new Map(ALL_COLUMNS).has(key));
  state.columnWidths = data.library.column_widths || {};
  state.plainCollapsed = data.library.plain_tags_collapsed !== false;
  if (state.selectedItem) state.selectedItem = state.items.find((item) => item.key === state.selectedItem.key) || null;
  if (state.selectedItem && state.detailStructuredEditing) {
    state.detailStructuredDraft = {
      remark: state.selectedItem.structured?.remark || "",
      title_zh: state.selectedItem.structured?.title_zh || "",
      abstract_zh: state.selectedItem.structured?.abstract_zh || "",
    };
  }
  if (state.attachmentEditorItemKey && !state.items.some((item) => item.key === state.attachmentEditorItemKey)) {
    state.attachmentEditorItemKey = "";
    state.selectedAttachmentKeys = new Set();
  }
  document.querySelector("[data-unsynced]").textContent = `未同步 ${data.library.unsynced_count || 0}`;
  applyFilters();
  renderDetail();
  rerenderActiveTagPopover();
}

function setupLibraryPage() {
  const root = document.querySelector("[data-library-page]");
  if (!root) return;
  state.libraryId = root.dataset.libraryId;
  document.querySelector("[data-table-search]")?.addEventListener("input", (event) => {
    state.search = event.target.value;
    applyFilters();
  });
  document.querySelector("[data-tag-search]")?.addEventListener("input", renderTagFilters);
  document.querySelector("[data-toggle-plain-tags]")?.addEventListener("click", async () => {
    state.plainCollapsed = !state.plainCollapsed;
    await postJSON(`/api/library/${state.libraryId}/preferences/plain-tags`, { collapsed: state.plainCollapsed });
    applyFilters();
  });
  document.querySelectorAll("[data-bulk-action]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.bulkAction === "add-item") openAddItemModal();
    else if (button.dataset.bulkAction === "delete-items") openDeleteItemsModal();
    else if (button.dataset.bulkAction === "move-items") openMoveItemsModal();
    else if (button.dataset.bulkAction === "edit-attachments") openAttachmentEditorModal();
    else if (button.dataset.bulkAction === "export-citation") openCitationExportModal();
    else notifyFeatureInProgress(button.dataset.bulkAction);
  }));
  setupColumnsPanel();
  loadState().catch((error) => window.alert(error.message));
}

setupSourceForms();
setupLibraryPage();
