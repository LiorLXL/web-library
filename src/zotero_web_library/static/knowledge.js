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
  matrixFields: [
    { id: "source-1", name: "元数据", rule: "Zotero title / authors / year / venue / abstract" },
    { id: "source-2", name: "笔记", rule: "Zotero notes indexed as note chunks" },
    { id: "source-3", name: "PDF 解析", rule: "MinerU markdown chunks and image assets" },
  ],
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

function activeKnowledgeItems() {
  return activeKnowledgeLibrary()?.items || [];
}

function knowledgeApi(path) {
  return `/api/library/${knowledgeState.libraryId}/rag${path}`;
}

function setKnowledgeMessage(message) {
  knowledgeState.message = message || "";
  renderKnowledgeStatus();
}

function renderKnowledgeStatus() {
  const status = knowledgeQuery("[data-reading-matrix-status]");
  if (!status) return;
  const active = activeKnowledgeLibrary();
  const count = active ? Number(active.item_count || active.items?.length || 0) : 0;
  const chunks = active ? Number(active.chunk_count || 0) : 0;
  const docs = active ? Number(active.document_count || 0) : 0;
  const baseText = active
    ? `当前知识库包含 ${count} 条文献、${docs} 份索引文档、${chunks} 个 chunk。`
    : "还没有选择知识库。";
  status.innerHTML = `<span>${escapeKnowledgeHtml(knowledgeState.message || baseText)}</span>`;
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
  host.innerHTML = knowledgeState.matrixFields
    .map(
      (field) => `
    <article class="matrix-field-card" data-field-id="${field.id}">
      <label>
        <span>索引源</span>
        <input value="${escapeKnowledgeHtml(field.name)}" readonly>
      </label>
      <label>
        <span>当前用途</span>
        <textarea readonly>${escapeKnowledgeHtml(field.rule)}</textarea>
      </label>
    </article>
  `,
    )
    .join("");
}

function renderKnowledgeMatrix() {
  const active = activeKnowledgeLibrary();
  const items = activeKnowledgeItems();
  const title = knowledgeQuery("[data-knowledge-current-title]");
  const head = knowledgeQuery("[data-knowledge-matrix-head]");
  const body = knowledgeQuery("[data-knowledge-matrix-body]");
  if (title) title.textContent = active ? `${active.name} · 文献与索引状态` : "选择或新建知识库后查看条目";
  renderKnowledgeStatus();
  renderMatrixFields();
  renderKnowledgeSearchPanel();
  renderKnowledgeChat();
  updateKnowledgeDeleteButton();
  if (!head || !body) return;
  head.innerHTML = `
    <tr>
      <th>文献</th>
      <th>年份</th>
      <th>来源</th>
      <th>索引文档</th>
      <th>Chunks</th>
    </tr>
  `;
  if (!active) {
    body.innerHTML = `<tr><td colspan="5">暂无知识库。</td></tr>`;
    return;
  }
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5">这个知识库还没有条目。可从文库页勾选文献后点击“导入知识库”。</td></tr>`;
    return;
  }
  body.innerHTML = items
    .map(
      (item) => `
    <tr>
      <td><strong>${escapeKnowledgeHtml(item.title || item.item_key)}</strong><small>${escapeKnowledgeHtml(item.item_key || "")}</small></td>
      <td>${escapeKnowledgeHtml(item.year || "-")}</td>
      <td>${escapeKnowledgeHtml(item.venue || "-")}</td>
      <td>${Number(item.document_count || 0)}</td>
      <td>${Number(item.chunk_count || 0)}</td>
    </tr>
  `,
    )
    .join("");
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

function notifyKnowledgePlaceholder(action) {
  const labels = {
    "add-field": "新增字段",
    "recommend-fields": "AI 推荐字段",
    "save-fields": "保存字段",
    "run-matrix": "运行文献矩阵",
    compress: "压缩记忆",
    "delete-field": "删除字段",
  };
  window.alert(`${labels[action] || "该功能"}将在文献矩阵阶段接入。`);
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
  knowledgeQuery("[data-add-matrix-field]")?.addEventListener("click", () => notifyKnowledgePlaceholder("add-field"));
  knowledgeQuery("[data-recommend-matrix-fields]")?.addEventListener("click", () => notifyKnowledgePlaceholder("recommend-fields"));
  knowledgeQuery("[data-save-matrix-fields]")?.addEventListener("click", () => notifyKnowledgePlaceholder("save-fields"));
  knowledgeQuery("[data-run-reading-matrix]")?.addEventListener("click", () => notifyKnowledgePlaceholder("run-matrix"));
  knowledgeQuery("[data-knowledge-placeholder-action=\"create\"]")?.addEventListener("click", createKnowledgeBaseFromPrompt);
  knowledgeQuery("[data-delete-knowledge-base]")?.addEventListener("click", deleteActiveKnowledgeBase);
  knowledgeQuery("[data-knowledge-placeholder-action=\"compress\"]")?.addEventListener("click", () => notifyKnowledgePlaceholder("compress"));
  knowledgeQuery("[data-knowledge-placeholder-action=\"send\"]")?.addEventListener("click", submitKnowledgeChat);
  knowledgeQuery(".knowledge-chat-input")?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitKnowledgeChat();
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-knowledge-placeholder-action=\"delete-field\"]");
    if (button) notifyKnowledgePlaceholder("delete-field");
  });
  applyKnowledgeSidebarState();
  setupKnowledgeSplitters();
  renderKnowledgeList();
  renderKnowledgeMatrix();
  renderKnowledgeChat();
  loadKnowledgeBases();
}

setupKnowledgePage();
