const knowledgeState = {
  libraryId: "",
  knowledgeBases: [],
  activeId: "",
  activeBase: null,
  sidebarCollapsed: false,
  loading: false,
  message: "",
  indexBusy: false,
  deleteBusy: false,
  searchQuery: "",
  searchResults: [],
  searchBusy: false,
  chatBusy: false,
  chatMessages: [],
  matrixFields: [],
  matrixItems: [],
  matrixRunning: false,
  matrixLatest: null,
  matrixPollTimer: null,
};

function knowledgeQuery(selector) {
  return document.querySelector(selector);
}

function knowledgeStorageKey(name) {
  const libraryId = document.body.dataset.libraryId || "default";
  return `knowledge-workbench:${libraryId}:${name}`;
}

function escapeKnowledgeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function knowledgeJSON(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`请求 ${url} 返回了非 JSON 内容（HTTP ${response.status}）：${text.slice(0, 120)}`);
  }
  if (!response.ok || data.ok === false) throw new Error(data.error || data.message || "请求失败");
  return data;
}

function activeKnowledgeLibrary() {
  return knowledgeState.activeBase || knowledgeState.knowledgeBases.find((entry) => entry.knowledge_base_id === knowledgeState.activeId) || null;
}

function knowledgeApi(path) {
  return `/api/library/${knowledgeState.libraryId}/rag${path}`;
}

function matrixApi(path) {
  const kb = knowledgeState.activeId || "";
  return `/api/library/${knowledgeState.libraryId}/matrix${path}?knowledge_base_id=${encodeURIComponent(kb)}`;
}

function setKnowledgeMessage(message) {
  knowledgeState.message = message || "";
  renderKnowledgeStatus();
}

function renderKnowledgeStatus() {
  const status = knowledgeQuery("[data-reading-matrix-status]");
  if (!status) return;
  const latest = knowledgeState.matrixLatest;
  let html = "";

  if (knowledgeState.matrixRunning && latest) {
    const done =
      (latest.completed || 0) + (latest.failed || 0) + (latest.skipped_no_pdf || 0) + (latest.skipped_existing || 0);
    html += `<span>文献矩阵运行中：进度 ${done}/${latest.total || 0}（完成 ${latest.completed || 0} · 失败 ${latest.failed || 0} · 无PDF ${latest.skipped_no_pdf || 0} · 跳过 ${latest.skipped_existing || 0}）。</span>`;
  } else if (knowledgeState.message) {
    html += `<span>${escapeKnowledgeHtml(knowledgeState.message)}</span>`;
  } else if (!knowledgeState.matrixRunning && latest) {
    if (latest.status === "failed") {
      html += `<span>文献矩阵任务失败：${escapeKnowledgeHtml(latest.error || "未知错误，请检查 API 配置或本地 PDF 是否存在。")}</span>`;
    } else if (latest.status === "success") {
      html += `<span>文献矩阵已完成：成功 ${latest.completed || 0} · 失败 ${latest.failed || 0} · 无PDF ${latest.skipped_no_pdf || 0} · 跳过 ${latest.skipped_existing || 0}。</span>`;
    }
  }

  const events = (latest && Array.isArray(latest.events)) ? latest.events : [];
  if (events.length) {
    const lines = events.map((e) => {
      const kind = escapeKnowledgeHtml(e.kind || "info");
      const msg = escapeKnowledgeHtml(e.message || "");
      return `<div class="matrix-event matrix-event-${kind}">${msg}</div>`;
    }).join("");
    html += `<div class="matrix-event-log" data-reading-matrix-events>${lines}</div>`;
  }

  if (!html) {
    const enabledCount = knowledgeState.matrixFields.filter((field) => field.enabled).length;
    html = `<span>文献矩阵共 ${knowledgeState.matrixFields.length} 个字段（启用 ${enabledCount} 个）。勾选矩阵表格中的文献后点“运行”批量生成。</span>`;
  }

  status.innerHTML = html;
  const logEl = status.querySelector("[data-reading-matrix-events]");
  if (logEl) logEl.scrollTop = logEl.scrollHeight;
}

async function loadKnowledgeBases({ keepActive = true } = {}) {
  knowledgeState.loading = true;
  renderKnowledgeList();
  try {
    const data = await knowledgeJSON(knowledgeApi("/knowledge-bases"));
    knowledgeState.knowledgeBases = data.knowledge_bases || [];
    if (!keepActive || !knowledgeState.knowledgeBases.some((item) => item.knowledge_base_id === knowledgeState.activeId)) {
      knowledgeState.activeId = knowledgeState.knowledgeBases[0]?.knowledge_base_id || "";
    }
    if (knowledgeState.activeId) await loadKnowledgeBaseDetail(knowledgeState.activeId);
    else {
      knowledgeState.activeBase = null;
      renderKnowledgeList();
      renderKnowledgeMatrix();
    }
  } catch (error) {
    setKnowledgeMessage(error.message);
  } finally {
    knowledgeState.loading = false;
    renderKnowledgeList();
    renderKnowledgeMatrix();
  }
}

async function loadKnowledgeBaseDetail(knowledgeBaseId) {
  const cleanId = String(knowledgeBaseId || "").trim();
  if (!cleanId) {
    knowledgeState.activeBase = null;
    renderKnowledgeMatrix();
    return;
  }
  try {
    const data = await knowledgeJSON(knowledgeApi(`/knowledge-bases/${encodeURIComponent(cleanId)}`));
  knowledgeState.activeBase = data.knowledge_base || null;
  knowledgeState.activeId = cleanId;
  } catch (error) {
    knowledgeState.activeBase = null;
    setKnowledgeMessage(error.message);
  }
  renderKnowledgeList();
  renderKnowledgeMatrix();
  loadMatrixState();
}

async function createKnowledgeBaseFromPrompt() {
  const name = window.prompt("新知识库名称");
  if (!String(name || "").trim()) return;
  try {
    const data = await knowledgeJSON(knowledgeApi("/knowledge-bases"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: String(name).trim(), item_keys: [] }),
    });
    knowledgeState.activeId = data.knowledge_base?.knowledge_base_id || "";
    setKnowledgeMessage("知识库已创建。");
    await loadKnowledgeBases({ keepActive: true });
  } catch (error) {
    setKnowledgeMessage(error.message);
  }
}

function updateKnowledgeDeleteButton() {
  const button = knowledgeQuery("[data-delete-knowledge-base]");
  if (!button) return;
  const active = activeKnowledgeLibrary();
  const disabled = !active || knowledgeState.deleteBusy;
  button.disabled = disabled;
  button.title = active ? `删除知识库：${active.name || active.knowledge_base_id}` : "请先选择知识库";
  button.textContent = knowledgeState.deleteBusy ? "删除中..." : "删除知识库";
}

async function deleteActiveKnowledgeBase() {
  const active = activeKnowledgeLibrary();
  if (!active || knowledgeState.deleteBusy) return;
  const name = active.name || active.knowledge_base_id;
  const ok = window.confirm(`确认删除知识库“${name}”？\n\n只会删除知识库定义和条目关联，不会删除 Zotero 文献、PDF 解析结果或 RAG 索引。`);
  if (!ok) return;
  const deletedId = active.knowledge_base_id;
  try {
    knowledgeState.deleteBusy = true;
    updateKnowledgeDeleteButton();
    await knowledgeJSON(knowledgeApi(`/knowledge-bases/${encodeURIComponent(deletedId)}`), { method: "DELETE" });
    knowledgeState.activeId = "";
    knowledgeState.activeBase = null;
    knowledgeState.searchQuery = "";
    knowledgeState.searchResults = [];
    setKnowledgeMessage(`知识库“${name}”已删除。`);
    await loadKnowledgeBases({ keepActive: false });
  } catch (error) {
    setKnowledgeMessage(error.message);
  } finally {
    knowledgeState.deleteBusy = false;
    updateKnowledgeDeleteButton();
    renderKnowledgeList();
    renderKnowledgeMatrix();
  }
}

async function refreshRagIndex() {
  if (knowledgeState.indexBusy) return;
  knowledgeState.indexBusy = true;
  setKnowledgeMessage("正在刷新 RAG 索引...");
  const button = knowledgeQuery("[data-rag-index-library]");
  if (button) button.disabled = true;
  try {
    const data = await knowledgeJSON(knowledgeApi("/index"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const status = data.status || {};
    setKnowledgeMessage(`RAG 索引已刷新：${Number(status.total_documents || 0)} 份文档，${Number(status.total_chunks || 0)} 个 chunk。`);
    await loadKnowledgeBases({ keepActive: true });
  } catch (error) {
    setKnowledgeMessage(error.message);
  } finally {
    knowledgeState.indexBusy = false;
    if (button) button.disabled = false;
  }
}

function applyKnowledgeSidebarState() {
  const workbench = knowledgeQuery("[data-knowledge-workbench]");
  const button = knowledgeQuery("[data-toggle-knowledge-sidebar]");
  workbench?.classList.toggle("sidebar-collapsed", knowledgeState.sidebarCollapsed);
  if (button) {
    button.textContent = knowledgeState.sidebarCollapsed ? "▶" : "◀";
    button.title = knowledgeState.sidebarCollapsed ? "展开列表" : "折叠列表";
    button.setAttribute("aria-label", button.title);
  }
}

function setupKnowledgeSplitters() {
  document.querySelectorAll("[data-knowledge-splitter]").forEach((splitter) => {
    splitter.addEventListener("pointerdown", (event) => {
      const side = splitter.dataset.knowledgeSplitter;
      const startX = event.clientX;
      const currentSidebar = Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--knowledge-sidebar-width"), 10) || 280;
      const currentChat = Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--knowledge-chat-width"), 10) || 340;
      splitter.setPointerCapture(event.pointerId);
      function onMove(moveEvent) {
        const delta = moveEvent.clientX - startX;
        if (side === "left") {
          const width = Math.max(180, Math.min(420, currentSidebar + delta));
          document.documentElement.style.setProperty("--knowledge-sidebar-width", `${width}px`);
          localStorage.setItem(knowledgeStorageKey("sidebarWidth"), String(width));
        } else {
          const width = Math.max(260, Math.min(520, currentChat - delta));
          document.documentElement.style.setProperty("--knowledge-chat-width", `${width}px`);
          localStorage.setItem(knowledgeStorageKey("chatWidth"), String(width));
        }
      }
      function onUp() {
        splitter.removeEventListener("pointermove", onMove);
        splitter.removeEventListener("pointerup", onUp);
      }
      splitter.addEventListener("pointermove", onMove);
      splitter.addEventListener("pointerup", onUp);
    });
  });
}

function renderKnowledgeList() {
  const host = knowledgeQuery("[data-knowledge-list]");
  if (!host) return;
  if (knowledgeState.loading && !knowledgeState.knowledgeBases.length) {
    host.innerHTML = `<p class="inline-status-copy">知识库加载中...</p>`;
    return;
  }
  if (!knowledgeState.knowledgeBases.length) {
    host.innerHTML = `<p class="inline-status-copy">还没有知识库。可从文库页勾选条目后导入，或点击新建知识库。</p>`;
    return;
  }
  host.innerHTML = knowledgeState.knowledgeBases
    .map(
      (item) => `
    <button type="button" class="compact-list-item ${item.knowledge_base_id === knowledgeState.activeId ? "active" : ""}" data-knowledge-item="${escapeKnowledgeHtml(item.knowledge_base_id)}">
      <span class="compact-list-text">
        <strong>${escapeKnowledgeHtml(item.name)}</strong>
        <small>${Number(item.item_count || 0)} 条文献 · ${Number(item.chunk_count || 0)} chunks · ${String(item.updated_at || "").slice(0, 10)}</small>
      </span>
      <span class="compact-list-actions">
        <span class="compact-icon-btn">打开</span>
      </span>
    </button>
  `,
    )
    .join("");
  host.querySelectorAll("[data-knowledge-item]").forEach((button) =>
    button.addEventListener("click", () => {
      knowledgeState.activeId = button.dataset.knowledgeItem || "";
      knowledgeState.searchResults = [];
      loadKnowledgeBaseDetail(knowledgeState.activeId);
    }),
  );
}

function renderMatrixFields() {
  const host = knowledgeQuery("[data-matrix-field-list]");
  if (!host) return;
  if (!knowledgeState.matrixFields.length) {
    host.innerHTML = `<article class="matrix-field-empty">还没有字段，点击“新增字段”或“AI 推荐字段”添加。</article>`;
    return;
  }
  host.innerHTML = knowledgeState.matrixFields
    .map(
      (field, index) => `
    <article class="matrix-field-card" data-field-index="${index}">
      <label>
        <span>字段名</span>
        <input type="text" value="${escapeKnowledgeHtml(field.name)}" data-field-name>
      </label>
      <label>
        <span>判断依据与格式要求</span>
        <textarea data-field-rule>${escapeKnowledgeHtml(field.rule)}</textarea>
      </label>
      <button type="button" class="icon-action-btn danger" data-remove-field title="删除字段">×</button>
    </article>
  `,
    )
    .join("");
}

function enabledMatrixFields() {
  return knowledgeState.matrixFields;
}

const matrixColumnWidths = {};

function renderKnowledgeMatrixTable() {
  const head = knowledgeQuery("[data-knowledge-matrix-head]");
  const body = knowledgeQuery("[data-knowledge-matrix-body]");
  if (!head || !body) return;
  const cols = enabledMatrixFields();
  head.innerHTML = `
    <tr>
      <th class="col-select" data-col-key="col-select"><input type="checkbox" data-select-all><span class="col-resizer" data-col-resize></span></th>
      <th class="col-title" data-col-key="col-title">名称<span class="col-resizer" data-col-resize></span></th>
      ${cols.map((field) => `<th class="col-field" data-col-key="col-field-${field.field_id}" title="${escapeKnowledgeHtml(field.rule)}">${escapeKnowledgeHtml(field.name)}<span class="col-resizer" data-col-resize></span></th>`).join("")}
      <th class="col-pdf" data-col-key="col-pdf">PDF<span class="col-resizer" data-col-resize></span></th>
    </tr>`;
  head.querySelectorAll("th[data-col-key]").forEach((th) => {
    const key = th.getAttribute("data-col-key");
    if (matrixColumnWidths[key]) th.style.width = matrixColumnWidths[key];
  });
  head.querySelectorAll("[data-col-resize]").forEach((handle) => {
    handle.addEventListener("mousedown", onMatrixColResizeStart);
  });
  const items = knowledgeState.matrixItems || [];
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="${cols.length + 3}">当前知识库还没有导入的文献条目。</td></tr>`;
    return;
  }
  body.innerHTML = items
    .map((item) => {
      const cells = cols
        .map((field) => {
          const value = (item.values && item.values[field.field_id]) || {};
          const text = value.value || "—";
          return `<td class="col-field" title="${escapeKnowledgeHtml(text)}">${escapeKnowledgeHtml(text)}</td>`;
        })
        .join("");
      return `
    <tr data-item-key="${escapeKnowledgeHtml(item.key)}">
      <td class="col-select"><input type="checkbox" data-item-select></td>
      <td class="col-title">
        <div class="matrix-item-title">${escapeKnowledgeHtml(item.title)}</div>
        <div class="matrix-item-meta">${escapeKnowledgeHtml([item.creators_display, item.year, item.venue].filter(Boolean).join(" · "))}</div>
      </td>
      ${cells}
      <td class="col-pdf">${item.has_pdf ? "有" : "无"}</td>
    </tr>`;
    })
    .join("");
  const selectAll = head.querySelector("[data-select-all]");
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      body.querySelectorAll("[data-item-select]").forEach((box) => {
        box.checked = selectAll.checked;
      });
    });
  }
}

function onMatrixColResizeStart(event) {
  event.preventDefault();
  const handle = event.currentTarget;
  const th = handle.closest("th");
  if (!th) return;
  const startX = event.clientX;
  const startWidth = th.getBoundingClientRect().width;
  th.classList.add("resizing");
  document.body.classList.add("col-resizing");

  function onMove(ev) {
    const dx = ev.clientX - startX;
    const newWidth = Math.max(64, startWidth + dx);
    th.style.width = `${newWidth}px`;
  }

  function onUp() {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    th.classList.remove("resizing");
    document.body.classList.remove("col-resizing");
    const key = th.getAttribute("data-col-key");
    if (key) matrixColumnWidths[key] = th.style.width;
  }

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function renderKnowledgeMatrix() {
  const active = activeKnowledgeLibrary();
  const title = knowledgeQuery("[data-knowledge-current-title]");
  if (title) title.textContent = active ? `${active.name} · 文献矩阵字段与矩阵表格` : "选择或新建知识库后查看条目";
  renderKnowledgeStatus();
  renderMatrixFields();
  renderKnowledgeMatrixTable();
  renderKnowledgeSearchPanel();
  renderKnowledgeChat();
  updateKnowledgeDeleteButton();
}

function renderKnowledgeSearchPanel() {
  const host = knowledgeQuery("[data-knowledge-search-panel]");
  if (!host) return;
  const active = activeKnowledgeLibrary();
  const disabled = !active || knowledgeState.searchBusy;
  const results = knowledgeState.searchResults || [];
  host.innerHTML = `
    <form class="knowledge-search-form" data-knowledge-search-form>
      <input name="query" value="${escapeKnowledgeHtml(knowledgeState.searchQuery)}" placeholder="在当前知识库中检索证据 chunk" ${disabled ? "disabled" : ""}>
      <button type="submit" class="form-action-btn" ${disabled ? "disabled" : ""}>${knowledgeState.searchBusy ? "检索中..." : "检索"}</button>
    </form>
    <div class="knowledge-search-results">
      ${results.length ? results.map(renderKnowledgeSearchResult).join("") : `<p class="inline-status-copy">${active ? "输入关键词后可预览当前知识库的 RAG 检索结果。" : "请先选择知识库。"}</p>`}
    </div>
  `;
  host.querySelector("[data-knowledge-search-form]")?.addEventListener("submit", submitKnowledgeSearch);
}

function renderKnowledgeSearchResult(result) {
  const source = result.source || {};
  return `
    <article class="knowledge-search-result">
      <strong>${escapeKnowledgeHtml(source.title || result.item_key || "未命名文献")}</strong>
      <p>${escapeKnowledgeHtml(result.snippet || result.excerpt || "")}</p>
      <small>${escapeKnowledgeHtml(source.source_type || result.chunk_type || "")} · ${escapeKnowledgeHtml(source.section_title || result.section_title || "")} · ${escapeKnowledgeHtml(result.chunk_id || "")}</small>
    </article>
  `;
}

function renderKnowledgeChat() {
  const host = knowledgeQuery("[data-knowledge-chat-messages]");
  const status = knowledgeQuery("[data-knowledge-chat-status]");
  const input = knowledgeQuery(".knowledge-chat-input");
  const sendButton = knowledgeQuery("[data-knowledge-placeholder-action=\"send\"]");
  if (host) {
    const messages = knowledgeState.chatMessages || [];
    host.innerHTML = messages.length
      ? messages.map(renderKnowledgeChatMessage).join("")
      : `<p class="inline-status-copy">选择知识库后，可基于 RAG 证据向 Agent 提问。</p>`;
    host.scrollTop = host.scrollHeight;
  }
  const active = activeKnowledgeLibrary();
  if (status) {
    status.textContent = knowledgeState.chatBusy
      ? "Agent 正在检索证据并生成回答..."
      : active
        ? "围绕当前知识库条目、矩阵字段与解析资产继续提问。"
        : "请先选择知识库。";
  }
  if (input) input.disabled = knowledgeState.chatBusy || !active;
  if (sendButton) {
    sendButton.disabled = knowledgeState.chatBusy || !active;
    sendButton.textContent = knowledgeState.chatBusy ? "生成中..." : "发送任务";
  }
}

function renderKnowledgeChatMessage(message) {
  const roleLabel = message.role === "user" ? "你" : message.role === "error" ? "错误" : "Agent";
  const sources = Array.isArray(message.sources) ? message.sources : [];
  return `
    <article class="knowledge-chat-message ${escapeKnowledgeHtml(message.role || "assistant")}">
      <strong>${roleLabel}</strong>
      <p>${escapeKnowledgeHtml(message.content || "")}</p>
      ${sources.length ? `<ul class="knowledge-chat-sources">${sources.slice(0, 5).map(renderKnowledgeChatSource).join("")}</ul>` : ""}
    </article>
  `;
}

function renderKnowledgeChatSource(source) {
  const title = source.title || source.item_key || "来源";
  const section = source.section_title ? ` · ${source.section_title}` : "";
  const citation = source.citation ? ` · ${source.citation}` : "";
  return `<li>${escapeKnowledgeHtml(title)}${escapeKnowledgeHtml(section)}${escapeKnowledgeHtml(citation)}</li>`;
}

async function submitKnowledgeSearch(event) {
  event?.preventDefault();
  const form = event?.currentTarget;
  const query = form ? String(new FormData(form).get("query") || "").trim() : String(knowledgeState.searchQuery || "").trim();
  if (!query || !knowledgeState.activeId) return;
  knowledgeState.searchQuery = query;
  knowledgeState.searchBusy = true;
  renderKnowledgeSearchPanel();
  try {
    const data = await knowledgeJSON(knowledgeApi("/tools/keyword_search"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, knowledge_base_id: knowledgeState.activeId, top_k: 8 }),
    });
    knowledgeState.searchResults = data.results || [];
    setKnowledgeMessage(`检索完成：找到 ${knowledgeState.searchResults.length} 条候选证据。`);
  } catch (error) {
    knowledgeState.searchResults = [];
    setKnowledgeMessage(error.message);
  } finally {
    knowledgeState.searchBusy = false;
    renderKnowledgeSearchPanel();
  }
}

async function submitKnowledgeChat() {
  const input = knowledgeQuery(".knowledge-chat-input");
  const question = String(input?.value || "").trim();
  if (!question || !knowledgeState.activeId || knowledgeState.chatBusy) return;
  knowledgeState.chatMessages.push({ role: "user", content: question, sources: [] });
  knowledgeState.chatBusy = true;
  if (input) input.value = "";
  renderKnowledgeChat();
  try {
    const data = await knowledgeJSON(knowledgeApi("/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        knowledge_base_id: knowledgeState.activeId,
        mode: "auto",
        top_k: 8,
        include_context: true,
      }),
    });
    knowledgeState.chatMessages.push({
      role: "assistant",
      content: data.answer || "Agent 没有返回文本。",
      sources: data.sources || [],
    });
    const sourceCount = Array.isArray(data.sources) ? data.sources.length : 0;
    setKnowledgeMessage(`Agent 回答完成：引用 ${sourceCount} 条证据。`);
  } catch (error) {
    knowledgeState.chatMessages.push({ role: "error", content: error.message, sources: [] });
    setKnowledgeMessage(error.message);
  } finally {
    knowledgeState.chatBusy = false;
    renderKnowledgeChat();
  }
}

function selectedMatrixItemKeys() {
  const body = knowledgeQuery("[data-knowledge-matrix-body]");
  if (!body) return [];
  return Array.from(body.querySelectorAll("tr[data-item-key] [data-item-select]:checked")).map(
    (box) => box.closest("tr").dataset.itemKey,
  );
}

function updateMatrixRunButtons() {
  const runBtn = knowledgeQuery("[data-run-reading-matrix]");
  const stopBtn = knowledgeQuery("[data-stop-reading-matrix]");
  if (runBtn) runBtn.disabled = knowledgeState.matrixRunning;
  if (stopBtn) stopBtn.hidden = !knowledgeState.matrixRunning;
}

function setupMatrixFieldListEvents() {
  const host = knowledgeQuery("[data-matrix-field-list]");
  if (!host) return;
  host.addEventListener("input", (event) => {
    const row = event.target.closest("[data-field-index]");
    if (!row) return;
    const index = Number(row.dataset.fieldIndex);
    if (event.target.matches("[data-field-name]")) {
      knowledgeState.matrixFields[index].name = event.target.value;
    } else if (event.target.matches("[data-field-rule]")) {
      knowledgeState.matrixFields[index].rule = event.target.value;
    }
  });
  host.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-field]");
    if (!button) return;
    const row = event.target.closest("[data-field-index]");
    if (!row) return;
    knowledgeState.matrixFields.splice(Number(row.dataset.fieldIndex), 1);
    renderMatrixFields();
  });
}

function addMatrixField() {
  knowledgeState.matrixFields.push({ field_id: "", name: "新字段", rule: "", enabled: true });
  renderMatrixFields();
}

async function saveMatrixFields() {
  if (!knowledgeState.activeId) {
    window.alert("请先在左侧选择或新建知识库。");
    return;
  }
  try {
    const data = await knowledgeJSON(matrixApi("/fields"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ fields: knowledgeState.matrixFields }),
    });
    knowledgeState.matrixFields = data.fields || knowledgeState.matrixFields;
    renderMatrixFields();
    renderKnowledgeMatrixTable();
    setKnowledgeMessage("文献矩阵字段已保存。");
  } catch (error) {
    setKnowledgeMessage(error.message);
  }
}

async function recommendMatrixFields() {
  if (!knowledgeState.activeId) {
    window.alert("请先在左侧选择或新建知识库。");
    return;
  }
  if (!window.confirm("AI 将基于文库论文推荐 3-6 个矩阵字段，并追加到当前字段列表（不会自动保存，记得点“保存字段”）。继续？")) return;
  const btn = knowledgeQuery("[data-recommend-matrix-fields]");
  if (btn) btn.disabled = true;
  setKnowledgeMessage("AI 正在推荐字段，请稍候...");
  try {
    const data = await knowledgeJSON(matrixApi("/recommend-fields"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ item_keys: selectedMatrixItemKeys() }),
    });
    const recommended = (data.fields || []).map((field) => ({
      field_id: "",
      name: field.name,
      rule: field.rule,
      enabled: true,
    }));
    knowledgeState.matrixFields = knowledgeState.matrixFields.concat(recommended);
    renderMatrixFields();
    setKnowledgeMessage(`已推荐 ${recommended.length} 个字段，请检查后点击“保存字段”。`);
  } catch (error) {
    setKnowledgeMessage(error.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function stopMatrixPolling() {
  if (knowledgeState.matrixPollTimer) {
    window.clearInterval(knowledgeState.matrixPollTimer);
    knowledgeState.matrixPollTimer = null;
  }
}

function startMatrixPolling() {
  if (knowledgeState.matrixPollTimer) return;
  knowledgeState.matrixPollTimer = window.setInterval(async () => {
    try {
      const data = await knowledgeJSON(matrixApi("/status"));
      knowledgeState.matrixRunning = data.running;
      knowledgeState.matrixLatest = data.latest;
      knowledgeState.matrixItems = data.items || knowledgeState.matrixItems;
      renderKnowledgeMatrixTable();
      renderKnowledgeStatus();
      updateMatrixRunButtons();
      if (!data.running) {
        stopMatrixPolling();
        knowledgeState.matrixFields = data.fields || knowledgeState.matrixFields;
        renderMatrixFields();
        renderKnowledgeMatrixTable();
        const latest = knowledgeState.matrixLatest || {};
        setKnowledgeMessage(
          latest.status === "success"
            ? `文献矩阵任务完成：成功 ${latest.completed || 0} · 失败 ${latest.failed || 0} · 无PDF ${latest.skipped_no_pdf || 0} · 跳过 ${latest.skipped_existing || 0}。`
            : latest.status === "failed"
              ? `文献矩阵任务失败：${latest.error || "未知错误，请检查 API 配置或本地 PDF。"}`
              : "文献矩阵任务已停止。",
        );
      }
    } catch (_err) {
      // 下一轮重试
    }
  }, 3000);
}

async function runMatrix() {
  if (!knowledgeState.activeId) {
    window.alert("请先在左侧选择或新建知识库。");
    return;
  }
  const keys = selectedMatrixItemKeys();
  if (!keys.length) {
    window.alert("请在矩阵表格中勾选至少一篇文献。");
    return;
  }
  try {
    const data = await knowledgeJSON(matrixApi("/run"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ item_keys: keys, mode: "skip_existing" }),
    });
    knowledgeState.matrixRunning = true;
    knowledgeState.matrixLatest = data.latest || knowledgeState.matrixLatest;
    renderKnowledgeStatus();
    updateMatrixRunButtons();
    startMatrixPolling();
  } catch (error) {
    setKnowledgeMessage(error.message);
  }
}

async function stopMatrix() {
  try {
    await knowledgeJSON(matrixApi("/stop"), { method: "POST", headers: { Accept: "application/json" } });
    stopMatrixPolling();
    knowledgeState.matrixRunning = false;
    updateMatrixRunButtons();
    setKnowledgeMessage("已发送停止信号，文献矩阵将很快停止。");
  } catch (error) {
    setKnowledgeMessage(error.message);
  }
}

async function loadMatrixState() {
  if (!knowledgeState.activeId) {
    knowledgeState.matrixFields = [];
    knowledgeState.matrixItems = [];
    knowledgeState.matrixRunning = false;
    knowledgeState.matrixLatest = null;
    renderMatrixFields();
    renderKnowledgeMatrixTable();
    renderKnowledgeStatus();
    updateMatrixRunButtons();
    return;
  }
  try {
    const data = await knowledgeJSON(matrixApi(""));
    knowledgeState.matrixFields = data.fields || [];
    knowledgeState.matrixItems = data.items || [];
    knowledgeState.matrixRunning = data.running;
    knowledgeState.matrixLatest = data.latest;
    renderMatrixFields();
    renderKnowledgeMatrixTable();
    renderKnowledgeStatus();
    updateMatrixRunButtons();
    if (data.running) startMatrixPolling();
  } catch (error) {
    setKnowledgeMessage(error.message);
  }
}

function setupKnowledgePage() {
  if (!document.querySelector("[data-knowledge-page]")) return;
  knowledgeState.libraryId = document.body.dataset.libraryId || "";
  const sidebarWidth = Number.parseInt(localStorage.getItem(knowledgeStorageKey("sidebarWidth")) || "", 10);
  const chatWidth = Number.parseInt(localStorage.getItem(knowledgeStorageKey("chatWidth")) || "", 10);
  if (sidebarWidth) document.documentElement.style.setProperty("--knowledge-sidebar-width", `${sidebarWidth}px`);
  if (chatWidth) document.documentElement.style.setProperty("--knowledge-chat-width", `${chatWidth}px`);
  knowledgeState.sidebarCollapsed = localStorage.getItem(knowledgeStorageKey("sidebarCollapsed")) === "true";
  knowledgeQuery("[data-toggle-knowledge-sidebar]")?.addEventListener("click", () => {
    knowledgeState.sidebarCollapsed = !knowledgeState.sidebarCollapsed;
    localStorage.setItem(knowledgeStorageKey("sidebarCollapsed"), String(knowledgeState.sidebarCollapsed));
    applyKnowledgeSidebarState();
  });
  knowledgeQuery("[data-rag-index-library]")?.addEventListener("click", refreshRagIndex);
  knowledgeQuery("[data-add-matrix-field]")?.addEventListener("click", addMatrixField);
  knowledgeQuery("[data-recommend-matrix-fields]")?.addEventListener("click", recommendMatrixFields);
  knowledgeQuery("[data-save-matrix-fields]")?.addEventListener("click", saveMatrixFields);
  knowledgeQuery("[data-run-reading-matrix]")?.addEventListener("click", runMatrix);
  knowledgeQuery("[data-stop-reading-matrix]")?.addEventListener("click", stopMatrix);
  knowledgeQuery("[data-knowledge-placeholder-action=\"create\"]")?.addEventListener("click", createKnowledgeBaseFromPrompt);
  knowledgeQuery("[data-delete-knowledge-base]")?.addEventListener("click", deleteActiveKnowledgeBase);
  knowledgeQuery("[data-knowledge-placeholder-action=\"compress\"]")?.addEventListener("click", () => {
    window.alert("压缩记忆功能将在后续接入。");
  });
  knowledgeQuery("[data-knowledge-placeholder-action=\"send\"]")?.addEventListener("click", submitKnowledgeChat);
  knowledgeQuery(".knowledge-chat-input")?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitKnowledgeChat();
  });
  setupMatrixFieldListEvents();
  applyKnowledgeSidebarState();
  setupKnowledgeSplitters();
  renderKnowledgeList();
  renderKnowledgeMatrix();
  renderKnowledgeChat();
  loadKnowledgeBases();
  loadMatrixState();
}

setupKnowledgePage();
