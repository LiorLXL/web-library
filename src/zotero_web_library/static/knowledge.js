const knowledgeState = {
  libraryId: "",
  knowledgeBases: [],
  activeId: "",
  activeBase: null,
  sidebarCollapsed: false,
  loading: false,
  message: "",
  indexBusy: false,
  embeddingStatus: null,
  embeddingBusy: false,
  deleteBusy: false,
  searchQuery: "",
  searchResults: [],
  searchBusy: false,
  chatLoading: false,
  chatBusy: false,
  chatCancelBusy: false,
  chatError: "",
  chatMessages: [],
  conversationId: "",
  activeRun: null,
  chatLastSequence: 0,
  chatPollTimer: null,
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

function resetKnowledgeConversation() {
  stopKnowledgeChatPolling();
  knowledgeState.chatLoading = false;
  knowledgeState.chatBusy = false;
  knowledgeState.chatCancelBusy = false;
  knowledgeState.chatError = "";
  knowledgeState.conversationId = "";
  knowledgeState.chatMessages = [];
  knowledgeState.activeRun = null;
  knowledgeState.chatLastSequence = 0;
}

function persistActiveKnowledgeBase() {
  if (knowledgeState.activeId) {
    localStorage.setItem(knowledgeStorageKey("activeKnowledgeBase"), knowledgeState.activeId);
  } else {
    localStorage.removeItem(knowledgeStorageKey("activeKnowledgeBase"));
  }
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
  const previousActiveId = knowledgeState.activeId;
  renderKnowledgeList();
  try {
    const data = await knowledgeJSON(knowledgeApi("/knowledge-bases"));
    knowledgeState.knowledgeBases = data.knowledge_bases || [];
    if (!keepActive || !knowledgeState.knowledgeBases.some((item) => item.knowledge_base_id === knowledgeState.activeId)) {
      knowledgeState.activeId = knowledgeState.knowledgeBases[0]?.knowledge_base_id || "";
    }
    persistActiveKnowledgeBase();
    if (knowledgeState.activeId !== previousActiveId) resetKnowledgeConversation();
    if (knowledgeState.activeId) await loadKnowledgeBaseDetail(knowledgeState.activeId);
    else {
      knowledgeState.activeBase = null;
      resetKnowledgeConversation();
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

async function loadEmbeddingStatus() {
  try {
    const data = await knowledgeJSON(knowledgeApi("/embeddings/status"));
    knowledgeState.embeddingStatus = data.status || null;
  } catch (error) {
    knowledgeState.embeddingStatus = { configured: false, error: error.message, statuses: [] };
  }
  renderKnowledgeSearchPanel();
}

async function loadKnowledgeBaseDetail(knowledgeBaseId) {
  const cleanId = String(knowledgeBaseId || "").trim();
  if (!cleanId) {
    knowledgeState.activeBase = null;
    knowledgeState.activeId = "";
    persistActiveKnowledgeBase();
    resetKnowledgeConversation();
    renderKnowledgeMatrix();
    return;
  }
  try {
    const data = await knowledgeJSON(knowledgeApi(`/knowledge-bases/${encodeURIComponent(cleanId)}`));
    if (knowledgeState.activeId !== cleanId) return;
    knowledgeState.activeBase = data.knowledge_base || null;
    knowledgeState.activeId = cleanId;
    persistActiveKnowledgeBase();
  } catch (error) {
    if (knowledgeState.activeId !== cleanId) return;
    knowledgeState.activeBase = null;
    setKnowledgeMessage(error.message);
  }
  renderKnowledgeList();
  renderKnowledgeMatrix();
  await Promise.all([loadKnowledgeConversation(cleanId), loadMatrixState()]);
}

async function loadKnowledgeConversation(knowledgeBaseId) {
  const cleanId = String(knowledgeBaseId || "").trim();
  if (!cleanId || cleanId !== knowledgeState.activeId) return;
  resetKnowledgeConversation();
  knowledgeState.chatLoading = true;
  renderKnowledgeChat();
  try {
    const query = new URLSearchParams({ knowledge_base_id: cleanId });
    const data = await knowledgeJSON(knowledgeApi(`/chat/history?${query.toString()}`));
    if (cleanId !== knowledgeState.activeId) return;
    knowledgeState.conversationId = data.conversation_id || "";
    knowledgeState.chatMessages = (data.messages || []).map((message) => ({
      role: message.role || "assistant",
      content: message.content || "",
      sources: message.sources || [],
      toolTrace: message.tool_trace || [],
      runId: message.run_id || "",
      turnIndex: message.turn_index || 0,
      agentTrace: message.agent_trace || [],
      agentState: message.agent_state || {},
      stopReason: message.stop_reason || "",
      runStatus: message.run_status || "",
    }));
    if (data.active_run?.run_id && data.active_run.status === "running") {
      knowledgeState.activeRun = normalizeKnowledgeAgentRun(data.active_run);
      knowledgeState.chatBusy = true;
      knowledgeState.chatLastSequence = lastKnowledgeRunSequence(knowledgeState.activeRun.events);
    }
  } catch (error) {
    if (cleanId !== knowledgeState.activeId) return;
    resetKnowledgeConversation();
    knowledgeState.chatError = `恢复知识库会话失败：${error.message}`;
  } finally {
    if (cleanId === knowledgeState.activeId) {
      knowledgeState.chatLoading = false;
      renderKnowledgeChat();
      if (knowledgeState.activeRun?.status === "running") startKnowledgeChatPolling();
    }
  }
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
    resetKnowledgeConversation();
    setKnowledgeMessage("知识库已创建。");
    await loadEmbeddingStatus();
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
    persistActiveKnowledgeBase();
    knowledgeState.searchQuery = "";
    knowledgeState.searchResults = [];
    resetKnowledgeConversation();
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
  if (knowledgeState.indexBusy || knowledgeState.embeddingBusy) return;
  const confirmed = window.confirm(
    "确认刷新文档索引？\n\n内容未变化的 chunk 会保留并复用现有 embedding；只有新增或正文发生变化的 chunk 才会生成新 embedding。",
  );
  if (!confirmed) return;
  knowledgeState.indexBusy = true;
  setKnowledgeMessage("正在刷新 RAG 索引...");
  const button = knowledgeQuery("[data-rag-index-library]");
  if (button) button.disabled = true;
  renderKnowledgeSearchPanel();
  try {
    const data = await knowledgeJSON(knowledgeApi("/index"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const status = data.status || {};
    const embeddingIndex = status.embedding_index || null;
    const embedded = Number(embeddingIndex?.embedded_chunks || 0);
    const embeddingNote = embeddingIndex?.ok === false
      ? `；embedding 补齐失败：${embeddingIndex.error || embeddingIndex.status || "未知错误"}`
      : embedded
        ? `，新增/更新 ${embedded} 个 embedding`
        : embeddingIndex?.status === "up_to_date"
          ? "，现有 embedding 已复用"
          : "";
    setKnowledgeMessage(`RAG 索引已刷新：${Number(status.total_documents || 0)} 份文档，${Number(status.total_chunks || 0)} 个 chunk${embeddingNote}。`);
    await loadKnowledgeBases({ keepActive: true });
    await loadEmbeddingStatus();
  } catch (error) {
    setKnowledgeMessage(error.message);
  } finally {
    knowledgeState.indexBusy = false;
    if (button) button.disabled = false;
    renderKnowledgeSearchPanel();
  }
}

async function rebuildEmbeddingIndex({ force = false } = {}) {
  if (knowledgeState.embeddingBusy || knowledgeState.indexBusy) return;
  const active = activeKnowledgeLibrary();
  if (!active) return;
  if (force && !window.confirm("确认强制重建当前知识库的语义索引？这会重新生成该知识库范围内的 chunk embedding。")) return;
  knowledgeState.embeddingBusy = true;
  setKnowledgeMessage(force ? "正在强制重建语义索引..." : "正在补齐语义索引...");
  const indexButton = knowledgeQuery("[data-rag-index-library]");
  if (indexButton) indexButton.disabled = true;
  renderKnowledgeSearchPanel();
  try {
    const data = await knowledgeJSON(knowledgeApi("/embeddings/index"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        knowledge_base_id: force ? knowledgeState.activeId : "",
        force,
        batch_size: 64,
      }),
    });
    setKnowledgeMessage(`语义索引完成：处理 ${Number(data.processed_chunks || 0)} 个 chunk，成功 ${Number(data.embedded_chunks || 0)} 个。`);
    await loadEmbeddingStatus();
  } catch (error) {
    setKnowledgeMessage(`语义索引中断：${error.message}。已完成批次已经保留，再次点击只会重试失败或未处理的 chunk。`);
    await loadEmbeddingStatus();
  } finally {
    knowledgeState.embeddingBusy = false;
    if (indexButton) indexButton.disabled = false;
    renderKnowledgeSearchPanel();
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
      const nextId = button.dataset.knowledgeItem || "";
      if (nextId !== knowledgeState.activeId) resetKnowledgeConversation();
      knowledgeState.activeId = nextId;
      persistActiveKnowledgeBase();
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
    ${renderEmbeddingStatusPanel(active)}
    <form class="knowledge-search-form" data-knowledge-search-form>
      <input name="query" value="${escapeKnowledgeHtml(knowledgeState.searchQuery)}" placeholder="在当前知识库中检索证据 chunk" ${disabled ? "disabled" : ""}>
      <button type="submit" class="form-action-btn" ${disabled ? "disabled" : ""}>${knowledgeState.searchBusy ? "检索中..." : "检索"}</button>
    </form>
    <div class="knowledge-search-results">
      ${results.length ? results.map(renderKnowledgeSearchResult).join("") : `<p class="inline-status-copy">${active ? "输入关键词后可预览当前知识库的 RAG 检索结果。" : "请先选择知识库。"}</p>`}
    </div>
  `;
  host.querySelector("[data-knowledge-search-form]")?.addEventListener("submit", submitKnowledgeSearch);
  host.querySelector("[data-embedding-index]")?.addEventListener("click", () => rebuildEmbeddingIndex({ force: false }));
  host.querySelector("[data-embedding-rebuild]")?.addEventListener("click", () => rebuildEmbeddingIndex({ force: true }));
}

function renderEmbeddingStatusPanel(active) {
  const status = knowledgeState.embeddingStatus || {};
  const rows = Array.isArray(status.statuses) ? status.statuses : [];
  const counts = new Map(rows.map((row) => [String(row.embedding_status || ""), Number(row.chunk_count || 0)]));
  const embedded = counts.get("embedded") || 0;
  const pending = (counts.get("pending") || 0) + (counts.get("stale") || 0);
  const failed = counts.get("failed") || 0;
  const notConfigured = counts.get("not_configured") || 0;
  const total = embedded + pending + failed + notConfigured;
  const config = status.config || {};
  const configured = Boolean(status.configured);
  const provider = config.provider || "";
  const model = config.model || "";
  const busy = knowledgeState.embeddingBusy || knowledgeState.indexBusy;
  const summary = configured
    ? `全库已生成 ${embedded}/${total} 个 chunk embedding`
    : "未配置 embedding，当前聊天仍会使用关键词检索";
  const detail = configured
    ? `${provider} / ${model}${failed ? ` / 失败 ${failed}` : ""}${pending ? ` / 待生成 ${pending}` : ""}`
    : "请到 API 配置页启用 Embedding 配置";
  return `
    <section class="knowledge-embedding-panel">
      <div>
        <strong>语义索引</strong>
        <span>${escapeKnowledgeHtml(summary)}</span>
        <small>${escapeKnowledgeHtml(detail)}</small>
      </div>
      <div class="knowledge-embedding-actions">
        <button type="button" class="ghost-btn small" data-embedding-index ${!active || !configured || busy ? "disabled" : ""}>${busy ? "处理中..." : "补齐全库语义索引"}</button>
        <button type="button" class="ghost-btn small" data-embedding-rebuild title="仅在更换模型或确认向量损坏时使用" ${!active || !configured || busy ? "disabled" : ""}>强制重建当前知识库</button>
      </div>
    </section>
  `;
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

function normalizeKnowledgeAgentRun(run) {
  return {
    ...(run || {}),
    events: Array.isArray(run?.events) ? run.events : [],
  };
}

function lastKnowledgeRunSequence(events) {
  return (Array.isArray(events) ? events : []).reduce(
    (latest, event) => Math.max(latest, Number(event?.sequence) || 0),
    0,
  );
}

function mergeKnowledgeRunEvents(current, incoming) {
  const merged = new Map();
  for (const event of [...(current || []), ...(incoming || [])]) {
    const key = event?.event_id || `${event?.sequence || 0}:${event?.event_type || "event"}`;
    merged.set(key, event);
  }
  return Array.from(merged.values()).sort((left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0));
}

function stopKnowledgeChatPolling() {
  if (knowledgeState.chatPollTimer) window.clearTimeout(knowledgeState.chatPollTimer);
  knowledgeState.chatPollTimer = null;
}

function startKnowledgeChatPolling() {
  stopKnowledgeChatPolling();
  if (!knowledgeState.activeRun?.run_id || knowledgeState.activeRun.status !== "running") return;
  knowledgeState.chatPollTimer = window.setTimeout(pollKnowledgeChatRun, 250);
}

async function pollKnowledgeChatRun() {
  const runId = knowledgeState.activeRun?.run_id;
  if (!runId) return;
  knowledgeState.chatPollTimer = null;
  try {
    const query = new URLSearchParams({ after_sequence: String(knowledgeState.chatLastSequence || 0) });
    const data = await knowledgeJSON(knowledgeApi(`/chat/runs/${encodeURIComponent(runId)}?${query.toString()}`));
    if (knowledgeState.activeRun?.run_id !== runId) return;
    const events = mergeKnowledgeRunEvents(knowledgeState.activeRun.events, data.events || []);
    knowledgeState.activeRun = normalizeKnowledgeAgentRun({ ...knowledgeState.activeRun, ...data, events });
    knowledgeState.chatLastSequence = lastKnowledgeRunSequence(events);
    knowledgeState.chatError = "";
    renderKnowledgeChat();
    if (data.status !== "running") {
      knowledgeState.chatBusy = false;
      knowledgeState.chatCancelBusy = false;
      stopKnowledgeChatPolling();
      await new Promise((resolve) => window.setTimeout(resolve, 160));
      if (knowledgeState.activeId) await loadKnowledgeConversation(knowledgeState.activeId);
      return;
    }
  } catch (error) {
    if (knowledgeState.activeRun?.run_id !== runId) return;
    knowledgeState.chatError = `运行状态更新失败，正在重试：${error.message}`;
    renderKnowledgeChat();
  }
  if (knowledgeState.activeRun?.run_id === runId && knowledgeState.activeRun.status === "running") {
    knowledgeState.chatPollTimer = window.setTimeout(pollKnowledgeChatRun, 900);
  }
}

async function cancelKnowledgeChat() {
  const runId = knowledgeState.activeRun?.run_id;
  if (!runId || knowledgeState.chatCancelBusy) return;
  knowledgeState.chatCancelBusy = true;
  knowledgeState.chatError = "";
  renderKnowledgeChat();
  try {
    const data = await knowledgeJSON(knowledgeApi(`/chat/runs/${encodeURIComponent(runId)}/cancel`), {
      method: "POST",
    });
    if (knowledgeState.activeRun?.run_id !== runId) return;
    if (data.run) {
      const events = mergeKnowledgeRunEvents(knowledgeState.activeRun.events, data.run.events || []);
      knowledgeState.activeRun = normalizeKnowledgeAgentRun({ ...knowledgeState.activeRun, ...data.run, events });
      knowledgeState.chatLastSequence = lastKnowledgeRunSequence(events);
    }
  } catch (error) {
    knowledgeState.chatCancelBusy = false;
    knowledgeState.chatError = `停止任务失败：${error.message}`;
  }
  renderKnowledgeChat();
}

async function restartKnowledgeChat(runId) {
  const cleanRunId = String(runId || "").trim();
  if (!cleanRunId || knowledgeState.chatBusy || knowledgeState.chatLoading) return;
  knowledgeState.chatBusy = true;
  knowledgeState.chatError = "";
  renderKnowledgeChat();
  try {
    const data = await knowledgeJSON(knowledgeApi(`/chat/runs/${encodeURIComponent(cleanRunId)}/restart`), {
      method: "POST",
    });
    knowledgeState.conversationId = data.conversation_id || knowledgeState.conversationId;
    const userMessage = data.user_message || {};
    if (userMessage.content && !knowledgeState.chatMessages.some((message) => message.runId === data.run_id && message.role === "user")) {
      knowledgeState.chatMessages.push({
        role: "user",
        content: userMessage.content,
        sources: [],
        runId: data.run_id || "",
        turnIndex: userMessage.turn_index || 0,
      });
    }
    knowledgeState.activeRun = normalizeKnowledgeAgentRun(data);
    knowledgeState.chatLastSequence = lastKnowledgeRunSequence(knowledgeState.activeRun.events);
    if (knowledgeState.activeRun.status === "running") {
      startKnowledgeChatPolling();
    } else {
      knowledgeState.chatBusy = false;
      await loadKnowledgeConversation(knowledgeState.activeId);
    }
  } catch (error) {
    knowledgeState.chatBusy = false;
    knowledgeState.chatError = `重新开始任务失败：${error.message}`;
  }
  renderKnowledgeChat();
}

function renderKnowledgeChat() {
  const host = knowledgeQuery("[data-knowledge-chat-messages]");
  const status = knowledgeQuery("[data-knowledge-chat-status]");
  const input = knowledgeQuery(".knowledge-chat-input");
  const sendButton = knowledgeQuery("[data-knowledge-placeholder-action=\"send\"]");
  const active = activeKnowledgeLibrary();
  if (host) {
    const messages = knowledgeState.chatMessages || [];
    const transcript = messages.map(renderKnowledgeChatMessage).join("");
    const activeRun = knowledgeState.activeRun?.status === "running"
      ? renderKnowledgeActiveRun(knowledgeState.activeRun)
      : "";
    host.innerHTML = transcript || activeRun
      ? `${transcript}${activeRun}`
      : `<div class="knowledge-chat-empty">
          <strong>${active ? "开始和知识库 Agent 对话" : "请先选择知识库"}</strong>
          <span>${active ? "可以围绕当前知识库、矩阵字段和 RAG 证据继续提问。" : "选择知识库后，可以基于其中的条目与证据向 Agent 提问。"}</span>
        </div>`;
    host.scrollTop = host.scrollHeight;
  }
  if (status) {
    status.textContent = knowledgeState.chatError || (knowledgeState.chatBusy
      ? knowledgeRunActivityLabel(knowledgeState.activeRun)
      : knowledgeState.chatLoading
        ? "正在恢复该知识库最近的会话..."
      : active
        ? "围绕当前知识库条目、矩阵字段与解析资产继续提问。"
        : "请先选择知识库。");
  }
  if (input) input.disabled = knowledgeState.chatBusy || knowledgeState.chatLoading || !active;
  if (sendButton) {
    sendButton.dataset.runAction = knowledgeState.chatBusy ? "cancel" : "send";
    sendButton.disabled = knowledgeState.chatLoading || !active || knowledgeState.chatCancelBusy;
    sendButton.textContent = knowledgeState.chatCancelBusy
      ? "停止中..."
      : knowledgeState.chatBusy
        ? "停止"
        : knowledgeState.chatLoading
          ? "恢复中..."
          : "发送任务";
  }
}

function renderKnowledgeChatMessage(message) {
  const roleLabel = message.role === "user" ? "你" : message.role === "error" ? "错误" : "Agent";
  const role = ["user", "assistant", "error"].includes(message.role) ? message.role : "assistant";
  const layoutRole = role === "user" ? "user" : "assistant";
  const avatarLabel = role === "user" ? "我" : "Agent";
  const sources = Array.isArray(message.sources) ? message.sources : [];
  const toolTrace = Array.isArray(message.toolTrace) ? message.toolTrace : [];
  const agentTrace = Array.isArray(message.agentTrace) ? message.agentTrace : [];
  const messageKey = knowledgeMessageKey(message);
  const restartAction = role === "assistant" && message.runStatus === "interrupted" && message.runId
    ? `<button class="knowledge-run-restart" type="button" data-restart-agent-run="${escapeKnowledgeHtml(message.runId)}">重新开始</button>`
    : "";
  return `
    <article class="chat-message knowledge-chat-message ${layoutRole}${role === "error" ? " error" : ""}">
      <div class="chat-avatar" aria-hidden="true">${avatarLabel}</div>
      <div class="chat-bubble">
        <div class="chat-meta knowledge-chat-message-heading"><span>${roleLabel}</span>${restartAction}</div>
        ${agentTrace.length ? renderKnowledgeAgentTrace(agentTrace, { running: false }) : toolTrace.length ? renderKnowledgeToolTrace(toolTrace) : ""}
        <div class="knowledge-chat-answer">${renderKnowledgeMarkdown(message.content || "", sources, messageKey)}</div>
        ${sources.length ? renderKnowledgeChatSources(sources, messageKey) : ""}
      </div>
    </article>
  `;
}

function renderKnowledgeActiveRun(run) {
  return `
    <article class="chat-message knowledge-chat-message assistant knowledge-active-run">
      <div class="chat-avatar" aria-hidden="true">Agent</div>
      <div class="chat-bubble">
        <div class="chat-meta knowledge-active-run-heading">
          <span>Agent</span>
          <span class="knowledge-run-badge"><i></i>${knowledgeState.chatCancelBusy ? "正在停止" : "运行中"}</span>
        </div>
        ${renderKnowledgeAgentTrace(run.events || [], { running: true })}
      </div>
    </article>
  `;
}

function knowledgeRunActivityLabel(run) {
  const events = Array.isArray(run?.events) ? run.events : [];
  const latest = [...events].reverse().find((event) => event?.summary && event.visibility !== "internal");
  return latest?.summary || "Agent 正在规划下一步...";
}

function renderKnowledgeAgentTrace(events, { running = false } = {}) {
  const visible = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (!event?.summary || event.visibility === "internal") continue;
    const previous = visible.at(-1);
    if (previous?.summary === event.summary && previous?.state === event.state) continue;
    visible.push(event);
  }
  const toolCount = visible.filter((event) => event?.payload?.tool).length;
  const duration = knowledgeTraceDuration(visible);
  const label = running
    ? `正在工作 · ${visible.length} 个步骤${toolCount ? ` · ${toolCount} 次工具调用` : ""}`
    : `运行过程 · ${visible.length} 个步骤${toolCount ? ` · ${toolCount} 次工具调用` : ""}${duration ? ` · ${duration}` : ""}`;
  return `
    <details class="knowledge-agent-trace"${running ? " open" : ""}>
      <summary><span class="knowledge-agent-trace-title">${running ? '<i class="knowledge-running-dot"></i>' : ""}${label}</span><span class="knowledge-trace-chevron">›</span></summary>
      <ol class="knowledge-agent-timeline">
        ${visible.length ? visible.map(renderKnowledgeAgentEvent).join("") : '<li class="knowledge-agent-event pending"><span class="knowledge-event-dot"></span><div><b>规划</b><p>正在建立任务计划...</p></div></li>'}
      </ol>
    </details>
  `;
}

function knowledgeTraceDuration(events) {
  const timestamps = (events || [])
    .map((event) => Date.parse(event?.created_at || ""))
    .filter((value) => Number.isFinite(value));
  if (timestamps.length < 2) return "";
  const milliseconds = Math.max(...timestamps) - Math.min(...timestamps);
  if (milliseconds < 1000) return `${milliseconds}ms`;
  return `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0)}s`;
}

function renderKnowledgeAgentEvent(event) {
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const state = String(event.state || "inspect");
  const tool = payload.tool ? ` · ${payload.tool}` : "";
  const hasDetails = event.visibility !== "summary" && Object.keys(payload).length > 0;
  return `
    <li class="knowledge-agent-event ${escapeKnowledgeHtml(event.status || "ok")}" data-state="${escapeKnowledgeHtml(state)}">
      <span class="knowledge-event-dot"></span>
      <div>
        <b>${escapeKnowledgeHtml(knowledgeAgentStateLabel(state))}${escapeKnowledgeHtml(tool)}</b>
        <p>${escapeKnowledgeHtml(event.summary || "")}</p>
        ${hasDetails ? `<details class="knowledge-event-details"><summary>查看调用详情</summary><pre>${escapeKnowledgeHtml(JSON.stringify(payload, null, 2))}</pre></details>` : ""}
      </div>
    </li>
  `;
}

function knowledgeAgentStateLabel(state) {
  return ({
    plan: "规划",
    retrieve: "检索",
    inspect: "检查",
    read: "深读",
    verify: "验证",
    answer: "回答",
    abstain: "停止",
  })[state] || "运行";
}

function renderKnowledgeToolTrace(toolTrace) {
  return `
    <details class="knowledge-tool-trace">
      <summary>检索步骤：${toolTrace.length} 次</summary>
      <ul>${toolTrace.slice(0, 5).map(renderKnowledgeToolTraceItem).join("")}</ul>
    </details>
  `;
}

function renderKnowledgeToolTraceItem(step) {
  const args = step.args || {};
  const bits = [step.tool || "tool"];
  if (args.mode) bits.push(args.mode);
  if (typeof step.result_count === "number") bits.push(`${step.result_count} 条`);
  if (step.error) bits.push(`错误：${step.error}`);
  return `<li>${escapeKnowledgeHtml(bits.join(" · "))}</li>`;
}

function knowledgeMessageKey(message) {
  const value = message.runId || `turn-${message.turnIndex || 0}`;
  return String(value).replace(/[^A-Za-z0-9_-]/g, "-") || "message";
}

function renderKnowledgeMarkdown(content, sources, messageKey) {
  let text = String(content || "").replaceAll("\r\n", "\n");
  const citations = [];
  for (const [index, source] of (sources || []).entries()) {
    const citation = String(source?.citation || "").trim();
    if (!citation) continue;
    const token = `@@KNOWLEDGE_CITATION_${index}@@`;
    text = text.split(citation).join(token);
    citations.push({ index, token });
  }
  const lines = escapeKnowledgeHtml(text).split("\n");
  const blocks = [];
  let paragraph = [];
  let list = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${renderKnowledgeInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    blocks.push(`<ul>${list.map((item) => `<li>${renderKnowledgeInlineMarkdown(item)}</li>`).join("")}</ul>`);
    list = [];
  };
  for (const line of lines) {
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(5, heading[1].length + 2);
      blocks.push(`<h${level}>${renderKnowledgeInlineMarkdown(heading[2])}</h${level}>`);
    } else if (bullet) {
      flushParagraph();
      list.push(bullet[1]);
    } else if (!line.trim()) {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  let html = blocks.join("") || "<p></p>";
  for (const { index, token } of citations) {
    html = html.replaceAll(
      token,
      `<a class="knowledge-citation-chip" href="#knowledge-source-${messageKey}-${index + 1}" title="跳转到证据 ${index + 1}">[${index + 1}]</a>`,
    );
  }
  return html;
}

function renderKnowledgeInlineMarkdown(value) {
  return String(value || "")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderKnowledgeChatSources(sources, messageKey) {
  return `
    <details class="knowledge-chat-sources">
      <summary>引用与证据 · ${sources.length}</summary>
      <ol>${sources.map((source, index) => renderKnowledgeChatSource(source, index, messageKey)).join("")}</ol>
    </details>
  `;
}

function renderKnowledgeChatSource(source, index, messageKey) {
  const title = source.title || source.item_key || "来源";
  const section = source.section_title ? ` · ${source.section_title}` : "";
  const citation = source.citation ? ` · ${source.citation}` : "";
  return `<li id="knowledge-source-${messageKey}-${index + 1}"><span>${index + 1}</span><div>${escapeKnowledgeHtml(title)}${escapeKnowledgeHtml(section)}<small>${escapeKnowledgeHtml(citation)}</small></div></li>`;
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
  if (!question || !knowledgeState.activeId || knowledgeState.chatBusy || knowledgeState.chatLoading) return;
  knowledgeState.chatMessages.push({ role: "user", content: question, sources: [], runId: "", turnIndex: 0 });
  knowledgeState.chatBusy = true;
  knowledgeState.chatError = "";
  if (input) input.value = "";
  renderKnowledgeChat();
  try {
    const payload = {
      question,
      knowledge_base_id: knowledgeState.activeId,
      response_mode: "async",
    };
    if (knowledgeState.conversationId) payload.conversation_id = knowledgeState.conversationId;
    const data = await knowledgeJSON(knowledgeApi("/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    knowledgeState.conversationId = data.conversation_id || knowledgeState.conversationId;
    const pendingUserMessage = knowledgeState.chatMessages.at(-1);
    if (pendingUserMessage?.role === "user") pendingUserMessage.runId = data.run_id || "";
    knowledgeState.activeRun = normalizeKnowledgeAgentRun(data);
    knowledgeState.chatLastSequence = lastKnowledgeRunSequence(knowledgeState.activeRun.events);
    if (knowledgeState.activeRun.status === "running") {
      startKnowledgeChatPolling();
    } else {
      knowledgeState.chatBusy = false;
      await new Promise((resolve) => window.setTimeout(resolve, 160));
      await loadKnowledgeConversation(knowledgeState.activeId);
    }
  } catch (error) {
    knowledgeState.chatMessages.push({ role: "error", content: error.message, sources: [] });
    knowledgeState.chatBusy = false;
    knowledgeState.chatError = error.message;
  }
  renderKnowledgeChat();
}

function handleKnowledgeChatAction() {
  if (knowledgeState.chatBusy) {
    cancelKnowledgeChat();
    return;
  }
  submitKnowledgeChat();
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
  knowledgeState.activeId = localStorage.getItem(knowledgeStorageKey("activeKnowledgeBase")) || "";
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
  knowledgeQuery("[data-knowledge-placeholder-action=\"send\"]")?.addEventListener("click", handleKnowledgeChatAction);
  knowledgeQuery("[data-knowledge-chat-messages]")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-restart-agent-run]");
    if (button) restartKnowledgeChat(button.dataset.restartAgentRun);
  });
  knowledgeQuery(".knowledge-chat-input")?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitKnowledgeChat();
  });
  setupMatrixFieldListEvents();
  applyKnowledgeSidebarState();
  setupKnowledgeSplitters();
  renderKnowledgeList();
  renderKnowledgeMatrix();
  renderKnowledgeChat();
  loadEmbeddingStatus();
  loadKnowledgeBases();
  loadMatrixState();
}

setupKnowledgePage();
