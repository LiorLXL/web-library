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
  apiConfig: null,
  apiConfigBusy: false,
  apiConfigMessage: "",
  apiConfigShowSecrets: false,
  apiConfigShowMineruSecret: false,
  apiConfigShowCodexSecrets: false,
  apiConfigCheckResults: {},
  apiConfigChecking: "",
  apiConfigCodexMessage: "",
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
  retrievalQuery: "",
  retrievalSources: new Set(["crossref", "arxiv", "pubmed", "semanticscholar", "datacite", "github", "huggingface", "zenodo"]),
  retrievalCandidates: [],
  retrievalSelectedKeys: new Set(),
  retrievalStats: null,
  retrievalSearchJobId: "",
  retrievalAiEvaluationSummary: null,
  retrievalAiEvaluationBusy: false,
  retrievalAiEvaluationStopRequested: false,
  retrievalAiScoringJobId: "",
  retrievalRunId: "",
  retrievalRuns: [],
  retrievalRunsBusy: false,
  retrievalRunsMessage: "",
  retrievalSummary: null,
  retrievalSummaryBusy: false,
  retrievalSummaryMessage: "",
  retrievalSourceInfo: {},
  retrievalSourcesBusy: false,
  retrievalSourcesChecking: false,
  retrievalSourcesMessage: "",
  retrievalModelStatus: null,
  retrievalModelStatusBusy: false,
  retrievalModelStatusMessage: "",
  retrievalReadiness: null,
  retrievalReadinessBusy: false,
  retrievalReadinessMessage: "",
  retrievalOnboarding: null,
  retrievalOnboardingBusy: false,
  retrievalOnboardingMessage: "",
  retrievalConfigBundleText: "",
  retrievalConfigBundleResult: null,
  retrievalConfigBundleBusy: false,
  retrievalConfigBundleMessage: "",
  retrievalSourceIntakeInput: "",
  retrievalSourceIntakeSampleUrl: false,
  retrievalSourceIntakeResult: null,
  retrievalSourceIntakeBusy: false,
  retrievalSourceIntakeMessage: "",
  retrievalFieldMapLabSource: "httpjson",
  retrievalFieldMapLabMode: "columns",
  retrievalFieldMapLabInput: "",
  retrievalFieldMapLabConfig: "",
  retrievalFieldMapLabUseAi: false,
  retrievalFieldMapLabResult: null,
  retrievalFieldMapLabBusy: false,
  retrievalFieldMapLabMessage: "",
  retrievalLocalPaths: "",
  retrievalLocalFieldMap: "",
  retrievalLocalPathsBusy: false,
  retrievalLocalPathsMessage: "",
  retrievalLocalPreview: null,
  retrievalLocalPreviewBusy: false,
  retrievalLocalPreviewMessage: "",
  retrievalHttpJsonConfig: "",
  retrievalHttpJsonTemplates: [],
  retrievalHttpJsonBusy: false,
  retrievalHttpJsonMessage: "",
  retrievalHttpJsonPreview: null,
  retrievalHttpJsonPreviewBusy: false,
  retrievalHttpJsonPreviewMessage: "",
  retrievalSqliteConfig: "",
  retrievalSqliteTemplates: [],
  retrievalSqliteBusy: false,
  retrievalSqliteMessage: "",
  retrievalSqlitePreview: null,
  retrievalSqlitePreviewBusy: false,
  retrievalSqlitePreviewMessage: "",
  retrievalManifestConfig: "",
  retrievalManifestTemplates: [],
  retrievalManifestBusy: false,
  retrievalManifestMessage: "",
  retrievalManifestPreview: null,
  retrievalManifestPreviewBusy: false,
  retrievalManifestPreviewMessage: "",
  retrievalBatchQueries: "",
  retrievalQueryPlan: null,
  retrievalQueryPlanBusy: false,
  retrievalQueryPlanJobId: "",
  retrievalQueryPlanUseAi: false,
  retrievalBatchJobs: [],
  retrievalBatchBusy: false,
  retrievalBatchMessage: "",
  simplePlanBatchJobId: "",
  simplePlanBatchLoadedJobId: "",
  simplePlanBatchCandidatesBusy: false,
  retrievalBatchMode: "quick",
  retrievalSimpleBatchLimit: 5,
  retrievalSimpleSourceLimits: {},
  citationExportFormat: "bibtex",
  citationExportMessage: "",
  citationExportBusy: false,
  pdfParseMessage: "",
  pdfParseBusy: false,
  pdfParseResult: null,
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
  readerPdfPickerItemKey: "",
  readerPdfPickerAttachments: [],
  readerPdfPickerSelectedKey: "",
  readerPdfPickerMessage: "",
  activeCollectionMenuKey: "",
  editingCollectionKey: "",
  editingCollectionName: "",
  movingCollectionKey: "",
  movingCollectionTargetKey: "",
  creatingCollectionParentKey: "",
  creatingCollectionName: "",
};

let retrievalBatchRefreshTimer = null;
let retrievalSearchPollTimer = null;
let retrievalAiEvaluationAbortController = null;
let retrievalAiScoringPollTimer = null;
let retrievalQueryPlanPollTimer = null;

function postJSON(url, payload, method = "POST", options = {}) {
  return fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: options.signal,
  }).then(async (response) => {
    const data = await parseJSONResponse(response);
    if (!response.ok || data.ok === false) throw new Error(data.error || data.message || "请求失败");
    return data;
  });
}

function safeRetrievalEndpoint(endpoint) {
  const cleanEndpoint = String(endpoint || "").trim();
  return Boolean(cleanEndpoint) && cleanEndpoint.startsWith("/retrieval/") && !cleanEndpoint.includes("://") && !cleanEndpoint.includes("..");
}

async function parseJSONResponse(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (error) {
    const summary = text.replace(/\s+/g, " ").trim().slice(0, 120);
    throw new Error(`请求返回了非 JSON 内容（HTTP ${response.status}）：${summary || response.statusText}`);
  }
}

function deleteJSON(url, payload = {}) {
  return postJSON(url, payload, "DELETE");
}

const API_CONFIG_SECRET_KEEP_VALUE = "__KEEP_SECRET__";

async function loadApiConfig(options = {}) {
  if (!state.libraryId) return;
  const includeSecrets = Boolean(options.includeSecrets);
  try {
    state.apiConfigBusy = true;
    state.apiConfigMessage = "";
    renderApiConfigPage();
    const suffix = includeSecrets ? "?include_secrets=1" : "";
    const response = await fetch(`/api/library/${state.libraryId}/api-config${suffix}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "API 配置加载失败");
    state.apiConfig = data.config || {};
  } catch (error) {
    state.apiConfigMessage = error.message;
  } finally {
    state.apiConfigBusy = false;
    renderApiConfigPage();
  }
}

function apiConfigSourceText(source) {
  if (source === "preference") return "页面配置";
  if (source === "environment") return "环境变量";
  if (source === "default") return "默认值";
  return "未配置";
}

function apiConfigTokenValue(service) {
  const entry = state.apiConfig?.code_sources?.[service] || {};
  return state.apiConfigShowSecrets ? String(entry.token || "") : "";
}

function apiConfigMineruKeyValue() {
  const entry = state.apiConfig?.mineru || {};
  return state.apiConfigShowMineruSecret ? String(entry.api_key || "") : "";
}

function apiConfigShouldIncludeSecrets() {
  return state.apiConfigShowSecrets || state.apiConfigShowMineruSecret || state.apiConfigShowCodexSecrets;
}

function apiConfigSecretPayload(formData, field, configured, source) {
  const value = String(formData.get(field) || "").trim();
  if (!state.apiConfigShowSecrets && !value && configured && source === "preference") {
    return API_CONFIG_SECRET_KEEP_VALUE;
  }
  return value;
}

function defaultCodexConfig(codex = {}) {
  return {
    model: String(codex.model || ""),
    base_url: String(codex.base_url || "https://api.openai.com/v1"),
    api_key: String(codex.api_key || ""),
    masked_api_key: String(codex.masked_api_key || ""),
    reasoning_effort_default: String(codex.reasoning_effort_default || "medium"),
    configured: Boolean(codex.configured),
    source: String(codex.source || (codex.configured ? "preference" : "none")),
  };
}

function ensureCodexConfigState() {
  if (!state.apiConfig) state.apiConfig = {};
  const codex = defaultCodexConfig(state.apiConfig.codex || {});
  state.apiConfig.codex = codex;
  return codex;
}

function syncCodexDraftFromForm(form = document.querySelector("[data-codex-config-form]")) {
  if (!form) return;
  const codex = ensureCodexConfigState();
  const formData = new FormData(form);
  codex.model = String(formData.get("codex_model") || "").trim();
  codex.base_url = String(formData.get("codex_base_url") || "").trim() || "https://api.openai.com/v1";
  codex.reasoning_effort_default = String(formData.get("codex_reasoning_effort_default") || "").trim() || "medium";
  const apiKey = String(formData.get("codex_api_key") || "").trim();
  if (state.apiConfigShowCodexSecrets || apiKey) codex.api_key = apiKey;
  state.apiConfig.codex = codex;
}

function serializeCodexConfigPayload() {
  syncCodexDraftFromForm();
  const codex = ensureCodexConfigState();
  const apiKey = String(codex.api_key || "").trim();
  return {
    model: codex.model,
    base_url: codex.base_url,
    reasoning_effort_default: codex.reasoning_effort_default,
    api_key: apiKey || (codex.configured && codex.source === "preference" ? API_CONFIG_SECRET_KEEP_VALUE : ""),
  };
}

function renderApiConfigCheck(service) {
  const result = state.apiConfigCheckResults[service] || null;
  if (state.apiConfigChecking === service) return `<p class="api-config-message">正在检查 ${escapeHtml(service)}...</p>`;
  if (!result) return "";
  const check = result.check || {};
  const ok = check.ok === true;
  const text = check.message || check.error || (ok ? "检查通过" : "检查失败");
  const detail = check.count != null ? `，返回 ${check.count} 条样本` : "";
  return `<p class="api-config-message ${ok ? "ok" : "failed"}">${escapeHtml(text + detail)}</p>`;
}

function renderApiConfigPage() {
  const host = document.querySelector("[data-api-config-panel]");
  if (!host) return;
  const config = state.apiConfig || {};
  const model = config.model || {};
  const github = config.code_sources?.github || {};
  const huggingface = config.code_sources?.huggingface || {};
  const zenodo = config.code_sources?.zenodo || {};
  const mineru = config.mineru || {};
  const codex = ensureCodexConfigState();
  const codexApiKeyValue = state.apiConfigShowCodexSecrets ? String(codex.api_key || "") : "";
  const codexApiKeyPlaceholder = codex.configured
    ? `${apiConfigSourceText(codex.source)}已配置 ${codex.masked_api_key || ""}`.trim()
    : "未配置";
  const apiKeyValue = state.apiConfigShowSecrets ? String(model.api_key || "") : "";
  const apiKeyPlaceholder = model.configured
    ? `${apiConfigSourceText(model.source)}已配置 ${model.masked_api_key || ""}`.trim()
    : "未配置";
  const mineruKeyPlaceholder = mineru.configured
    ? `${apiConfigSourceText(mineru.source)}已配置 ${mineru.masked_api_key || ""}`.trim()
    : "未配置";
  const serviceRows = [
    ["github", "GitHub Token", "github_token", github, "公开仓库搜索；可选，未填也能搜公开资源"],
    ["huggingface", "HuggingFace Token", "huggingface_token", huggingface, "Hub models / datasets；可选"],
    ["zenodo", "Zenodo Token", "zenodo_token", zenodo, "公开 records；可选"],
  ];
  host.innerHTML = `
    <section class="api-config-card">
      <div class="api-config-head">
        <div>
          <h2>模型 API</h2>
          <p>只填三项：模型名称、请求地址、API Key。请求地址可以填根地址，后端会自动补 /v1/chat/completions。</p>
        </div>
        <span class="api-status ${model.configured ? "ok" : "failed"}">${model.configured ? "已配置" : "未配置"}</span>
      </div>
      <form class="api-config-form" data-api-config-form>
        <label>
          <span>模型名称</span>
          <input name="model" value="${escapeHtml(model.model || "")}" placeholder="gpt-5.5">
        </label>
        <label>
          <span>请求地址</span>
          <input name="base_url" value="${escapeHtml(model.base_url || "")}" placeholder="https://ai-pixel.online">
          <em>实际请求：${escapeHtml(model.chat_url || "")}</em>
        </label>
        <label>
          <span>API Key</span>
          <input name="api_key" type="${state.apiConfigShowSecrets ? "text" : "password"}" value="${escapeHtml(apiKeyValue)}" placeholder="${escapeHtml(apiKeyPlaceholder)}">
          <em>来源：${escapeHtml(apiConfigSourceText(model.source))}</em>
        </label>
        <div class="api-config-actions">
          <button type="button" class="form-action-btn" data-save-api-config ${state.apiConfigBusy ? "disabled" : ""}>${state.apiConfigBusy ? "保存中..." : "保存配置"}</button>
          <button type="button" class="ghost-btn" data-toggle-api-config-secrets>${state.apiConfigShowSecrets ? "隐藏 key" : "显示 key"}</button>
          <button type="button" class="ghost-btn" data-check-api-config="model" ${state.apiConfigChecking ? "disabled" : ""}>检查模型</button>
        </div>
        ${state.apiConfigMessage ? `<p class="api-config-message">${escapeHtml(state.apiConfigMessage)}</p>` : ""}
        ${renderApiConfigCheck("model")}
      </form>
    </section>

    <section class="api-config-card">
      <div class="api-config-head">
        <div>
          <h2>MinerU PDF 解析</h2>
          <p>用于批量解析已勾选条目的 PDF。解析结果会保存到本地副本文库目录的 mineru-results/。</p>
        </div>
        <span class="api-status ${mineru.configured ? "ok" : "failed"}">${mineru.configured ? "已配置" : "未配置"}</span>
      </div>
      <form class="api-config-form" data-mineru-config-form>
        <div class="api-source-row">
          <div>
            <strong>MinerU API</strong>
            <span>填写 API Key 后，文库页可使用“PDF 解析”批量调用 MinerU。</span>
            <em>状态：${mineru.configured ? "已配置" : "未配置"}；来源：${escapeHtml(apiConfigSourceText(mineru.source))}${mineru.masked_api_key ? `；${escapeHtml(mineru.masked_api_key)}` : ""}</em>
          </div>
          <input name="mineru_api_key" type="${state.apiConfigShowMineruSecret ? "text" : "password"}" value="${escapeHtml(apiConfigMineruKeyValue())}" placeholder="${escapeHtml(mineruKeyPlaceholder)}">
        </div>
        <div class="api-source-row">
          <div>
            <strong>MinerU 请求地址</strong>
            <span>默认使用 MinerU API 地址；如果部署了兼容接口，可以在这里覆盖。</span>
            <em>来源：${escapeHtml(apiConfigSourceText(mineru.base_url_source))}</em>
          </div>
          <input name="mineru_base_url" value="${escapeHtml(mineru.base_url || "")}" placeholder="https://mineru.net/api/v4/file-urls/batch">
        </div>
        <div class="api-config-actions">
          <button type="button" class="form-action-btn" data-save-mineru-config ${state.apiConfigBusy ? "disabled" : ""}>${state.apiConfigBusy ? "保存中..." : "保存 MinerU 配置"}</button>
          <button type="button" class="ghost-btn" data-toggle-mineru-config-secret>${state.apiConfigShowMineruSecret ? "隐藏 key" : "显示 key"}</button>
        </div>
      </form>
    </section>

    <section class="api-config-card">
      <div class="api-config-head">
        <div>
          <h2>Codex 模型配置</h2>
          <p>用于后续接入 Codex 检索工作流。配置和 MinerU、模型 API 一样，统一保存在当前文库的 <code>api_config</code> 里。</p>
        </div>
        <span class="api-status ${codex.configured ? "ok" : "failed"}">${codex.configured ? "已配置" : "未配置"}</span>
      </div>
      <form class="api-config-form" data-codex-config-form>
        <div class="api-config-field-grid">
          <label>
            <span>模型名</span>
            <input name="codex_model" value="${escapeHtml(codex.model || "")}" placeholder="codex-mini-latest">
          </label>
          <label>
            <span>API 请求地址</span>
            <input name="codex_base_url" value="${escapeHtml(codex.base_url || "")}" placeholder="https://api.openai.com/v1">
          </label>
          <label>
            <span>API Key</span>
            <input name="codex_api_key" type="${state.apiConfigShowCodexSecrets ? "text" : "password"}" value="${escapeHtml(codexApiKeyValue)}" placeholder="${escapeHtml(codexApiKeyPlaceholder)}">
            <em>来源：${escapeHtml(apiConfigSourceText(codex.source))}</em>
          </label>
          <label>
            <span>Reasoning Effort</span>
            <select name="codex_reasoning_effort_default">
              ${["low", "medium", "high"].map((value) => `<option value="${value}" ${codex.reasoning_effort_default === value ? "selected" : ""}>${value}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="api-config-actions">
          <button type="button" class="form-action-btn" data-save-codex-config ${state.apiConfigBusy ? "disabled" : ""}>${state.apiConfigBusy ? "保存中..." : "保存 Codex 设置"}</button>
          <button type="button" class="ghost-btn" data-toggle-codex-config-secret>${state.apiConfigShowCodexSecrets ? "隐藏 key" : "显示 key"}</button>
        </div>
        <p class="api-config-message">当前只保留 Codex 基础模型配置，真实智能体工作流后续再接入。</p>
        ${state.apiConfigCodexMessage ? `<p class="api-config-message">${escapeHtml(state.apiConfigCodexMessage)}</p>` : ""}
      </form>
    </section>

    <section class="api-config-card">
      <div class="api-config-head">
        <div>
          <h2>代码 / 数据源 API</h2>
          <p>这些 token 都是可选项。未配置时检索公开资源，配置后通常有更高限流或可访问私有资源。</p>
        </div>
      </div>
      <div class="api-source-list">
        ${serviceRows.map(([service, label, field, entry, hint]) => `
          <div class="api-source-row">
            <div>
              <strong>${escapeHtml(label)}</strong>
              <span>${escapeHtml(hint)}</span>
              <em>状态：${entry.configured ? "已配置" : "未配置"}；来源：${escapeHtml(apiConfigSourceText(entry.source))}${entry.masked ? `；${escapeHtml(entry.masked)}` : ""}</em>
              ${renderApiConfigCheck(service)}
            </div>
            <input form="api-config-hidden-form" name="${escapeHtml(field)}" type="${state.apiConfigShowSecrets ? "text" : "password"}" value="${escapeHtml(apiConfigTokenValue(service))}" placeholder="${entry.configured ? "已配置，留空则保留" : "可选"}">
            <button type="button" class="ghost-btn" data-check-api-config="${escapeHtml(service)}" ${state.apiConfigChecking ? "disabled" : ""}>检查</button>
          </div>
        `).join("")}
      </div>
      <form id="api-config-hidden-form" data-api-config-hidden-form></form>
    </section>

  `;
}

async function saveApiConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const hiddenForm = document.querySelector("[data-api-config-hidden-form]");
  if (hiddenForm) {
    new FormData(hiddenForm).forEach((value, key) => formData.set(key, value));
  }
  const model = state.apiConfig?.model || {};
  const code = state.apiConfig?.code_sources || {};
  const payload = {
    model: {
      model: String(formData.get("model") || "").trim(),
      base_url: String(formData.get("base_url") || "").trim(),
      api_key: apiConfigSecretPayload(formData, "api_key", model.configured, model.source),
    },
    code_sources: {
      github_token: apiConfigSecretPayload(formData, "github_token", code.github?.configured, code.github?.source),
      huggingface_token: apiConfigSecretPayload(formData, "huggingface_token", code.huggingface?.configured, code.huggingface?.source),
      zenodo_token: apiConfigSecretPayload(formData, "zenodo_token", code.zenodo?.configured, code.zenodo?.source),
    },
  };
  try {
    state.apiConfigBusy = true;
    state.apiConfigMessage = "";
    renderApiConfigPage();
    const data = await postJSON(`/api/library/${state.libraryId}/api-config`, payload);
    state.apiConfig = data.config || {};
    state.apiConfigShowSecrets = false;
    state.apiConfigMessage = "配置已保存。";
  } catch (error) {
    state.apiConfigMessage = error.message;
  } finally {
    state.apiConfigBusy = false;
    renderApiConfigPage();
  }
}

async function saveMineruConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const mineru = state.apiConfig?.mineru || {};
  const payload = {
    mineru: {
      base_url: String(formData.get("mineru_base_url") || "").trim(),
      api_key: apiConfigSecretPayload(formData, "mineru_api_key", mineru.configured, mineru.source),
    },
  };
  try {
    state.apiConfigBusy = true;
    state.apiConfigMessage = "";
    const data = await postJSON(`/api/library/${state.libraryId}/api-config`, payload);
    state.apiConfig = data.config || {};
    state.apiConfigShowMineruSecret = false;
    state.apiConfigMessage = "MinerU 配置已保存。";
  } catch (error) {
    state.apiConfigMessage = error.message;
  } finally {
    state.apiConfigBusy = false;
    renderApiConfigPage();
  }
}

async function saveCodexConfig(event) {
  event.preventDefault();
  try {
    state.apiConfigBusy = true;
    state.apiConfigCodexMessage = "";
    syncCodexDraftFromForm(event.currentTarget);
    renderApiConfigPage();
    const data = await postJSON(`/api/library/${state.libraryId}/api-config`, {
      codex: serializeCodexConfigPayload(),
    });
    state.apiConfig = data.config || {};
    state.apiConfigShowCodexSecrets = false;
    state.apiConfigCodexMessage = "Codex 智能体设置已保存。";
  } catch (error) {
    state.apiConfigCodexMessage = error.message;
  } finally {
    state.apiConfigBusy = false;
    renderApiConfigPage();
  }
}

async function checkApiConfig(service) {
  if (!service) return;
  try {
    state.apiConfigChecking = service;
    renderApiConfigPage();
    const data = await postJSON(`/api/library/${state.libraryId}/api-config/check`, { service });
    state.apiConfigCheckResults = { ...state.apiConfigCheckResults, [service]: data };
  } catch (error) {
    state.apiConfigCheckResults = {
      ...state.apiConfigCheckResults,
      [service]: { check: { ok: false, error: error.message, message: error.message } },
    };
  } finally {
    state.apiConfigChecking = "";
    renderApiConfigPage();
  }
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

function currentDetailItem() {
  return state.selectedItem || null;
}

function currentItemPdfAttachments(item = currentDetailItem()) {
  return (item?.attachments || []).filter((attachment) => {
    const kind = String(attachment.kind || "").toLowerCase();
    const type = String(attachment.content_type || "").toLowerCase();
    const label = String(attachment.display_label || attachment.path || "").toLowerCase();
    return attachment.openable && (kind === "pdf" || type.includes("pdf") || label.endsWith(".pdf"));
  });
}

function bulkActionState(action) {
  const checkedCount = selectedItemKeys().length;
  const item = currentDetailItem();
  const editable = Boolean(state.library?.editable);
  const pdfCount = currentItemPdfAttachments(item).length;
  const checkedRequired = "请勾选任意数量条目后操作";
  const localCopyRequired = "只读源库不能执行此操作，请先创建本地副本";
  const pending = "功能待接入";
  switch (action) {
    case "add-item":
      return editable ? { enabled: true, title: "添加条目" } : { enabled: false, title: localCopyRequired };
    case "delete-items":
      if (!editable) return { enabled: false, title: localCopyRequired };
      return checkedCount ? { enabled: true, title: "删除已勾选条目" } : { enabled: false, title: checkedRequired };
    case "move-items":
      if (!editable) return { enabled: false, title: localCopyRequired };
      return checkedCount ? { enabled: true, title: "移动已勾选条目" } : { enabled: false, title: checkedRequired };
    case "edit-attachments":
      if (!editable) return { enabled: false, title: localCopyRequired };
      return item ? { enabled: true, title: "编辑当前条目的附件" } : { enabled: false, title: "请点击任意条目后操作" };
    case "read-paper":
      return item && pdfCount ? { enabled: true, title: "打开当前条目的 PDF" } : { enabled: false, title: "请点击有可读PDF的条目后操作" };
    case "parse-pdfs":
      if (!editable) return { enabled: false, title: localCopyRequired };
      return checkedCount ? { enabled: true, title: "用 MinerU 解析已勾选条目的 PDF" } : { enabled: false, title: checkedRequired };
    case "import-knowledge":
      return checkedCount ? { enabled: false, title: pending } : { enabled: false, title: checkedRequired };
    case "export-citation":
      return checkedCount ? { enabled: true, title: "导出已勾选条目引用" } : { enabled: false, title: checkedRequired };
    case "download-papers":
    case "query-rank":
      return checkedCount ? { enabled: false, title: pending } : { enabled: false, title: checkedRequired };
    default:
      return { enabled: false, title: pending };
  }
}

function renderBulkActionStates() {
  document.querySelectorAll("[data-bulk-action]").forEach((button) => {
    const status = bulkActionState(button.dataset.bulkAction);
    button.classList.toggle("is-disabled", !status.enabled);
    button.setAttribute("aria-disabled", status.enabled ? "false" : "true");
    button.title = status.title || "";
  });
}

function notifyFeatureInProgress(action) {
  const labels = new Map([
    ["add-item", "添加条目"],
    ["delete-items", "删除条目"],
    ["move-items", "移动条目"],
    ["edit-attachments", "附件编辑"],
    ["read-paper", "文献研读"],
    ["parse-pdfs", "PDF 解析"],
    ["download-papers", "文献下载"],
    ["query-rank", "期刊&会议等级查询"],
    ["import-knowledge", "导入知识库"],
    ["export-citation", "引用导出"],
  ]);
  console.info(`${labels.get(action) || "该功能"}开发中`);
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
  const evidence = importEvidenceMessage(summary.import_evidence);
  const parts = [];
  if (created) parts.push(`新建 ${created} 条`);
  if (existing) parts.push(`复用已有 ${existing} 条`);
  if (conflict) parts.push(`冲突 ${conflict} 条`);
  if (failed) parts.push(`失败 ${failed} 条`);
  if (!parts.length) return evidence || "没有导入条目。";
  const message = existing && !created && !conflict && !failed
    ? "条目已存在，已定位到已有条目。"
    : parts.join(" · ");
  return [message, evidence].filter(Boolean).join(" · ");
}

function importEvidenceMessage(evidence) {
  if (!evidence || typeof evidence !== "object") return "";
  const candidates = Number(evidence.candidate_count || 0);
  const recorded = Number(evidence.provenance_recorded_count || 0);
  if (!candidates && !recorded) return "";
  const reportReady = evidence.run_report_markdown_endpoint ? "，报告已就绪" : "";
  return `溯源记录 ${recorded}/${candidates} 条${reportReady}`;
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

function retrievalCandidateKey(candidate, index) {
  const identifiers = candidate.identifiers || candidate.item?.identifiers || {};
  return [
    candidate.candidate_id,
    candidate.source,
    candidate.external_id,
    identifiers.doi,
    identifiers.arxiv,
    identifiers.pmid,
    identifiers.isbn,
    candidate.title,
    index,
  ].filter(Boolean).join(":");
}

function normalizeRetrievalCandidates(candidates) {
  return (candidates || []).map((candidate, index) => ({
    ...candidate,
    client_key: candidate.client_key || retrievalCandidateKey(candidate, index),
  }));
}

function retrievalCandidateRuleConfidence(candidate) {
  const confidence = Number(candidate?.confidence);
  if (Number.isFinite(confidence) && confidence > 0) return confidence > 1 ? confidence / 100 : confidence;
  const evaluation = candidate?.ai_evaluation || {};
  const finalConfidence = Number(evaluation.final_confidence_score);
  if (Number.isFinite(finalConfidence) && finalConfidence > 0) return finalConfidence > 1 ? finalConfidence / 100 : finalConfidence;
  const sourceCount = Number(candidate?.source_count || (Array.isArray(candidate?.sources) ? candidate.sources.length : 0) || 0);
  return Math.min(0.95, 0.45 + sourceCount * 0.08);
}

function retrievalCandidateHasAiModelEvaluation(candidate) {
  const evaluation = candidate?.ai_evaluation || {};
  return evaluation.score_source === "ai_model" || evaluation.status === "evaluated";
}

function retrievalCandidateIsAiRecommended(candidate) {
  return retrievalCandidateHasAiModelEvaluation(candidate)
    && String(candidate?.ai_evaluation?.decision || "").toLowerCase() === "recommend";
}

function retrievalCandidateDecisionWeight(candidate) {
  const decision = String(candidate?.ai_evaluation?.decision || "review").toLowerCase();
  if (decision === "recommend") return 0;
  if (decision === "reject") return 2;
  return 1;
}

function retrievalCandidateAiConfidence(candidate) {
  const value = Number(candidate?.ai_evaluation?.final_confidence_score);
  if (!Number.isFinite(value)) return 0;
  return value > 1 ? value : value * 100;
}

function sortRetrievalCandidatesForAiProgress() {
  state.retrievalCandidates.sort((left, right) => {
    const leftAi = retrievalCandidateHasAiModelEvaluation(left);
    const rightAi = retrievalCandidateHasAiModelEvaluation(right);
    if (leftAi !== rightAi) return leftAi ? -1 : 1;
    if (leftAi && rightAi) {
      const decisionDiff = retrievalCandidateDecisionWeight(left) - retrievalCandidateDecisionWeight(right);
      if (decisionDiff) return decisionDiff;
      return retrievalCandidateAiConfidence(right) - retrievalCandidateAiConfidence(left);
    }
    return retrievalCandidateRuleConfidence(right) - retrievalCandidateRuleConfidence(left);
  });
  state.retrievalCandidates.forEach((candidate, index) => {
    candidate.rank = index + 1;
  });
}

function buildRetrievalAiProgressSummary(status = "evaluating", error = "") {
  const aiCandidates = state.retrievalCandidates.filter(retrievalCandidateHasAiModelEvaluation);
  const counts = { recommend: 0, review: 0, reject: 0 };
  aiCandidates.forEach((candidate) => {
    const decision = String(candidate.ai_evaluation?.decision || "review").toLowerCase();
    if (counts[decision] != null) counts[decision] += 1;
  });
  const failedCount = state.retrievalCandidates.filter((candidate) => candidate.ai_evaluation?.status === "fallback").length;
  const allEvaluated = aiCandidates.length >= state.retrievalCandidates.length;
  const scoreSource = aiCandidates.length && allEvaluated ? "ai_model" : (aiCandidates.length ? "mixed_ai_rules" : "deterministic_rules");
  return {
    requested: true,
    configured: state.retrievalModelStatus?.configured === true,
    provider: state.retrievalModelStatus?.provider || "",
    model: state.retrievalModelStatus?.model || "",
    score_source: scoreSource,
    score_framework: aiCandidates.length ? "ai_rubric_v1" : "metadata_rules_v1",
    status: allEvaluated && status !== "error" ? "evaluated" : status,
    candidate_count: state.retrievalCandidates.length,
    ai_evaluated_candidate_count: aiCandidates.length,
    skipped_candidate_count: Math.max(0, state.retrievalCandidates.length - aiCandidates.length),
    failed_batch_count: failedCount,
    auto_selected_count: aiCandidates.filter((candidate) => candidate.ai_evaluation?.auto_select === true).length,
    decision_counts: counts,
    error,
  };
}

function retrievalCreatorLine(candidate) {
  const creators = candidate.creators || candidate.item?.creators || [];
  const names = creators.map((creator) => {
    if (creator.name) return creator.name;
    return [creator.first_name || creator.firstName || "", creator.last_name || creator.lastName || ""].filter(Boolean).join(" ");
  }).filter(Boolean);
  return names.slice(0, 3).join("; ") + (names.length > 3 ? ` 等 ${names.length} 位` : "");
}

function renderRetrievalStats() {
  if (!state.retrievalStats) return "";
  return `<div class="retrieval-stats" data-retrieval-stats>
    ${Object.entries(state.retrievalStats).map(([source, stats]) => {
      const elapsed = Number(stats.elapsed_ms || 0);
      const timing = elapsed ? ` · ${elapsed}ms` : "";
      const label = stats.ok
        ? `${source} · ${stats.count || 0} 条${timing}`
        : `${source} · ${stats.error_kind || "失败"}${timing}`;
      const detail = stats.ok ? "" : (stats.action || stats.error || "该源本次检索失败");
      return `<span class="${stats.ok ? "ok" : "failed"}" title="${escapeHtml(detail)}">${escapeHtml(label)}</span>`;
    }).join("")}
  </div>`;
}

function renderRetrievalAiSummary() {
  const summary = state.retrievalAiEvaluationSummary;
  if (!summary) return "";
  const counts = summary.decision_counts || {};
  const parts = [
    `评分 ${retrievalEvaluationSourceLabel(summary)}`,
    `推荐 ${Number(counts.recommend || 0)}`,
    `复核 ${Number(counts.review || 0)}`,
    `不建议 ${Number(counts.reject || 0)}`,
    `默认勾选 ${Number(summary.auto_selected_count || 0)}`,
  ];
  if (summary.status === "partial") parts.push("部分 AI 完成");
  if (Number(summary.accepted_evaluation_count || 0)) parts.push(`AI ${Number(summary.accepted_evaluation_count || 0)} 条`);
  if (Number(summary.skipped_candidate_count || 0)) parts.push(`规则 ${Number(summary.skipped_candidate_count || 0)} 条`);
  if (Number(summary.failed_batch_count || 0)) parts.push(`失败批次 ${Number(summary.failed_batch_count || 0)}`);
  if (summary.status === "not_configured") parts.push("模型未配置");
  if (summary.score_framework === "ai_rubric_v1") parts.push("Rubric 评分");
  if (summary.error) parts.push(summary.error);
  return `<div class="retrieval-ai-summary">${parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("")}</div>`;
}

function retrievalEvaluationSourceLabel(evaluation) {
  const status = String(evaluation?.status || "");
  const source = String(evaluation?.score_source || "");
  if (source === "ai_model" || status === "evaluated") return "AI评分";
  if (source === "mixed_ai_rules" || status === "partial") return "AI部分评分";
  if (status === "not_configured") return "规则兜底";
  if (status === "fallback" || status === "error") return "规则兜底";
  if (status === "skipped") return "规则评分";
  return source === "deterministic_rules" ? "规则兜底" : "待评分";
}

function formatPercent(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "";
  const percent = number <= 1 ? number * 100 : number;
  return `${Math.round(Math.max(0, Math.min(100, percent)))}%`;
}

function renderRetrievalSummary() {
  if (state.retrievalSummaryBusy && !state.retrievalSummary) {
    return `<section class="retrieval-summary" data-retrieval-summary><p class="retrieval-history-message">统计加载中...</p></section>`;
  }
  const summary = state.retrievalSummary || null;
  if (!summary) {
    return state.retrievalSummaryMessage ? `<p class="retrieval-history-message">${escapeHtml(state.retrievalSummaryMessage)}</p>` : "";
  }
  const totals = summary.totals || {};
  const sources = Object.entries(summary.sources || {})
    .sort(([, left], [, right]) => Number(right.run_count || 0) - Number(left.run_count || 0))
    .slice(0, 5);
  return `<section class="retrieval-summary" data-retrieval-summary>
    <div class="retrieval-history-head">
      <div class="retrieval-summary-title">
        <strong>阶段统计</strong>
        <span>${escapeHtml(summary.latest_run_at ? `更新 ${formatRetrievalTime(summary.latest_run_at)}` : "暂无检索")}</span>
      </div>
      <div class="retrieval-report-actions">
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-summary data-report-format="markdown" title="下载阶段 Markdown 报告">MD</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-summary data-report-format="csv" title="下载阶段 CSV 报告">CSV</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-summary data-report-format="json" title="下载阶段 JSON 报告">JSON</button>
      </div>
    </div>
    ${state.retrievalSummaryMessage ? `<p class="retrieval-history-message">${escapeHtml(state.retrievalSummaryMessage)}</p>` : ""}
    <div class="retrieval-summary-grid">
      <span><strong>${Number(totals.run_count || 0)}</strong><em>检索批次</em></span>
      <span><strong>${Number(totals.candidate_count || 0)}</strong><em>候选条目</em></span>
      <span><strong>${Number(totals.imported_count || 0)}</strong><em>导入记录</em></span>
      <span><strong>${formatPercent(totals.import_rate)}</strong><em>导入率</em></span>
      <span><strong>${formatPercent(totals.source_success_rate)}</strong><em>源成功率</em></span>
    </div>
    ${sources.length ? `<div class="retrieval-summary-sources">
      ${sources.map(([source, item]) => {
        const failures = Number(item.failure_count || 0);
        const detail = failures ? `失败 ${failures} 次；${item.last_action || item.last_error || ""}` : "该源最近记录正常";
        return `<span class="${failures ? "failed" : "ok"}" title="${escapeHtml(detail)}">${escapeHtml(source)} · 成功 ${Number(item.success_count || 0)} / 失败 ${failures} · 平均 ${Number(item.elapsed_avg_ms || 0)}ms</span>`;
      }).join("")}
    </div>` : ""}
  </section>`;
}

function formatRetrievalTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || "");
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRateLimitSeconds(value) {
  const seconds = Number(value || 0);
  if (!seconds) return "";
  if (seconds >= 1) return `间隔 ${seconds.toFixed(seconds % 1 ? 1 : 0)}s`;
  return `间隔 ${Math.round(seconds * 1000)}ms`;
}

function retrievalAiDecisionLabel(decision) {
  if (decision === "recommend") return "推荐入库";
  if (decision === "reject") return "不建议";
  return "需要复核";
}

function retrievalAiRiskLabel(risk) {
  if (risk === "high") return "高风险";
  if (risk === "low") return "低风险";
  return "中风险";
}

function aiScoreValue(ai, key, legacyKey = "") {
  if (ai?.[key] != null) return ai[key];
  if (legacyKey && ai?.[legacyKey] != null) return ai[legacyKey];
  return null;
}

const SIMPLE_PLAN_SOURCE_LIMITS_BY_MODE = {
  quick: {
    default: 4,
    crossref: 5,
    arxiv: 5,
    pubmed: 5,
    semanticscholar: 5,
    datacite: 4,
    github: 2,
    huggingface: 2,
    zenodo: 3,
    localfile: 5,
    httpjson: 5,
    sqlite: 5,
    manifest: 5,
  },
  full: {
    default: 8,
    crossref: 10,
    arxiv: 10,
    pubmed: 10,
    semanticscholar: 10,
    datacite: 8,
    github: 5,
    huggingface: 5,
    zenodo: 6,
    localfile: 10,
    httpjson: 10,
    sqlite: 10,
    manifest: 10,
  },
};

function retrievalCandidateItemType(candidate) {
  const item = candidate.item || {};
  const fields = item.fields || {};
  const raw = candidate.item_type || item.item_type || item.itemType || fields.itemType || fields.item_type || candidate.type || "";
  const normalized = ITEM_TYPE_ALIASES[raw] || raw;
  return String(normalized || "").trim();
}

function retrievalCandidateTypeMeta(candidate) {
  const itemType = retrievalCandidateItemType(candidate);
  const source = String(candidate.source || "").toLowerCase();
  const meta = ITEM_TYPE_META[itemType] || {};
  let label = meta.labelZh || itemType || "资料";
  let group = meta.group || "other";
  if (["journalArticle", "conferencePaper", "preprint", "thesis"].includes(itemType)) {
    label = "论文";
    group = "paper";
  } else if (itemType === "computerProgram") {
    label = "代码/软件";
    group = "code";
  } else if (itemType === "dataset") {
    label = "数据集";
    group = "dataset";
  } else if (itemType === "report") {
    label = "报告";
    group = "report";
  } else if (source === "github") {
    label = "代码/软件";
    group = "code";
  } else if (source === "huggingface") {
    label = itemType === "dataset" ? "数据集" : "模型/代码";
    group = itemType === "dataset" ? "dataset" : "code";
  }
  return {
    itemType,
    label,
    group,
    zoteroLabel: meta.labelZh || itemType || "未识别",
  };
}

function retrievalShortText(value, limit = 140) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function renderRetrievalSourceHits(sources) {
  const unique = [...new Set((sources || []).filter(Boolean))];
  if (!unique.length) return "";
  const label = unique.length > 1 ? `多源命中：${unique.join(" / ")}` : `来源：${unique[0]}`;
  return `<span class="retrieval-source-hits">${escapeHtml(label)}</span>`;
}

function renderRetrievalZoteroPreview(candidate) {
  const item = candidate.item || {};
  const fields = item.fields || {};
  const identifiers = candidate.identifiers || item.identifiers || {};
  const typeMeta = retrievalCandidateTypeMeta(candidate);
  const rows = [
    ["资料类型", `${typeMeta.label} / Zotero: ${typeMeta.zoteroLabel}`],
    ["标题", fields.title || candidate.title],
    ["作者", retrievalCreatorLine(candidate)],
    ["DOI", fields.DOI || identifiers.doi || identifiers.DOI],
    ["摘要", fields.abstractNote || candidate.abstract],
    ["URL", fields.url || candidate.landing_url || candidate.url],
  ]
    .map(([label, value]) => [label, retrievalShortText(value, label === "摘要" ? 180 : 120)])
    .filter(([, value]) => value);
  if (!rows.length) return "";
  return `<details class="retrieval-zotero-preview">
    <summary>入库字段预览</summary>
    <span class="retrieval-zotero-preview-grid">
      ${rows.map(([label, value]) => `<span><strong>${escapeHtml(label)}</strong><em>${escapeHtml(value)}</em></span>`).join("")}
    </span>
  </details>`;
}

function renderCandidateAiEvaluation(candidate) {
  const ai = candidate.ai_evaluation || null;
  if (ai?.status === "evaluating") {
    return `<span class="retrieval-ai-row evaluating">
      <strong>AI评分中</strong>
      <em>正在根据主题和元数据逐条判断</em>
    </span>`;
  }
  if (!ai || !ai.decision) return "";
  const decision = String(ai.decision || "review");
  const reason = String(ai.reason || "").trim();
  const finalConfidence = aiScoreValue(ai, "final_confidence_score");
  const topicRelevance = aiScoreValue(ai, "topic_relevance_score", "relevance_score");
  const metadataQuality = aiScoreValue(ai, "metadata_quality_score", "quality_score");
  const sourceEvidence = aiScoreValue(ai, "source_evidence_score");
  const importRisk = aiScoreValue(ai, "import_risk_score");
  const scores = [
    finalConfidence != null ? `置信 ${formatPercent(finalConfidence)}` : "",
    topicRelevance != null ? `主题 ${formatPercent(topicRelevance)}` : "",
    metadataQuality != null ? `元数据 ${formatPercent(metadataQuality)}` : "",
    sourceEvidence != null ? `证据 ${formatPercent(sourceEvidence)}` : "",
    importRisk != null ? `导入风险 ${formatPercent(importRisk)}` : (ai.risk_level ? retrievalAiRiskLabel(ai.risk_level) : ""),
    ai.auto_select ? "已默认勾选" : "",
  ].filter(Boolean).join(" · ");
  return `<span class="retrieval-ai-row ${escapeHtml(decision)}">
    <strong>${escapeHtml(retrievalEvaluationSourceLabel(ai))}：${escapeHtml(retrievalAiDecisionLabel(decision))}</strong>
    ${scores ? `<em>${escapeHtml(scores)}</em>` : ""}
    ${reason ? `<small>${escapeHtml(reason)}</small>` : ""}
  </span>`;
}

function retrievalRunSourceBadges(run) {
  const stats = run.source_stats || {};
  const sources = Array.isArray(run.sources) && run.sources.length ? run.sources : Object.keys(stats);
  return sources.map((source) => {
    const item = stats[source] || {};
    const elapsed = Number(item.elapsed_ms || 0);
    const wait = Number(item.rate_limit_wait_ms || 0);
    const timing = elapsed ? ` · ${elapsed}ms` : "";
    const rateWait = wait ? ` · 等待 ${wait}ms` : "";
    const text = item.ok === false
      ? `${source}: ${item.error_kind || "失败"}${timing}${rateWait}`
      : `${source}: ${Number(item.count || 0)} 条${timing}${rateWait}`;
    const detail = item.ok === false ? (item.action || item.error || "") : "";
    return `<span class="${item.ok === false ? "failed" : "ok"}" title="${escapeHtml(detail)}">${escapeHtml(text)}</span>`;
  }).join("");
}

function renderRetrievalRuns() {
  const rows = (state.retrievalRuns || []).map((run) => {
    const query = run.query || "未命名检索";
    const candidateCount = Number(run.candidate_count || 0);
    const importedCount = Number(run.imported_count || 0);
    return `<div class="retrieval-history-row" data-retrieval-run-row="${escapeHtml(run.run_id || "")}">
      <div class="retrieval-history-main">
        <strong>${escapeHtml(query)}</strong>
        <span>${escapeHtml(formatRetrievalTime(run.created_at))}</span>
      </div>
      <div class="retrieval-history-counts">
        <span>候选 ${candidateCount}</span>
        <span>已导入 ${importedCount}</span>
      </div>
      <div class="retrieval-history-sources">${retrievalRunSourceBadges(run)}</div>
      <div class="retrieval-report-actions">
        <button type="button" class="mini-icon retrieval-report-btn" data-load-retrieval-run-candidates="${escapeHtml(run.run_id || "")}" title="恢复这次检索结果">恢复结果</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-report="${escapeHtml(run.run_id || "")}" data-report-format="markdown" title="下载 Markdown 报告">MD</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-report="${escapeHtml(run.run_id || "")}" data-report-format="csv" title="下载 CSV 报告">CSV</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-report="${escapeHtml(run.run_id || "")}" data-report-format="json" title="下载 JSON 报告">JSON</button>
      </div>
    </div>`;
  }).join("");
  return `<section class="retrieval-history" data-retrieval-runs>
    <div class="retrieval-history-head">
      <strong>最近检索</strong>
      <button type="button" class="mini-icon" data-refresh-retrieval-runs title="刷新最近检索">↻</button>
    </div>
    ${state.retrievalRunsMessage ? `<p class="retrieval-history-message">${escapeHtml(state.retrievalRunsMessage)}</p>` : ""}
    ${state.retrievalRunsBusy ? `<p class="retrieval-history-message">加载中...</p>` : rows || `<p class="retrieval-history-message">暂无检索记录</p>`}
  </section>`;
}

function renderRetrievalCandidates() {
  if (!state.retrievalCandidates.length) {
    if (!state.retrievalStats) return "";
    return `<div class="retrieval-empty" data-retrieval-empty>没有检索到候选条目</div>`;
  }
  return `<div class="retrieval-candidates" data-retrieval-candidates>
    ${state.retrievalCandidates.map((candidate) => {
      const identifiers = candidate.identifiers || {};
      const source = candidate.source || "source";
      const sources = Array.isArray(candidate.sources) && candidate.sources.length
        ? candidate.sources
        : [source, ...(candidate.also_seen_in || [])].filter(Boolean);
      const sourceLabel = sources.length > 1 ? `多源 ${sources.join(" / ")}` : source;
      const typeMeta = retrievalCandidateTypeMeta(candidate);
      const title = candidate.title || candidate.item?.fields?.title || "未命名候选";
      const year = candidate.year || "";
      const venue = candidate.venue || "";
      const creators = retrievalCreatorLine(candidate);
      const abstract = candidate.abstract || "";
      const confidenceLabel = candidate.confidence_label || "";
      const rankLabel = candidate.rank ? `#${candidate.rank}` : "";
      const duplicateHint = candidate.duplicate_hint || null;
      const similarityHint = candidate.similarity_hint || null;
      const duplicateMatches = (candidate.existing_matches || duplicateHint?.matches || [])
        .map((match) => match.title || match.key)
        .filter(Boolean)
        .slice(0, 2)
        .join(" / ");
      const similarityMatches = (candidate.weak_similarity_matches || similarityHint?.matches || [])
        .map((match) => match.title || match.key)
        .filter(Boolean)
        .slice(0, 2)
        .join(" / ");
      const rankReasons = (candidate.rank_reasons || candidate.evidence || []).slice(0, 4)
        .map((reason) => `<span>${escapeHtml(reason)}</span>`)
        .join("");
      const multiSourceBadge = sources.length > 1 ? `<span>多源命中 ${sources.length}</span>` : "";
      const badges = Object.entries(identifiers)
        .filter(([, value]) => value)
        .map(([key, value]) => `<span>${escapeHtml(key.toUpperCase())}: ${escapeHtml(value)}</span>`)
        .join("");
      return `<label class="retrieval-candidate">
        <input type="checkbox" data-retrieval-candidate-check="${escapeHtml(candidate.client_key)}" ${state.retrievalSelectedKeys.has(candidate.client_key) ? "checked" : ""}>
        <span class="retrieval-candidate-body">
          <span class="retrieval-title-row">
            <strong>${escapeHtml(title)}</strong>
            <span class="retrieval-title-tags">
              <span class="retrieval-type-pill ${escapeHtml(typeMeta.group)}">${escapeHtml(typeMeta.label)}</span>
              <em>${escapeHtml(sourceLabel)}</em>
            </span>
          </span>
          ${renderRetrievalSourceHits(sources)}
          ${rankLabel || confidenceLabel || rankReasons || multiSourceBadge ? `<span class="retrieval-rank-row">${rankLabel ? `<span>${escapeHtml(rankLabel)}</span>` : ""}${confidenceLabel ? `<span>${escapeHtml(confidenceLabel)}</span>` : ""}${multiSourceBadge}${rankReasons}</span>` : ""}
          ${duplicateHint ? `<span class="retrieval-duplicate ${escapeHtml(duplicateHint.status || "")}">${escapeHtml(duplicateHint.message || "文库已有匹配条目")}${duplicateMatches ? `：${escapeHtml(duplicateMatches)}` : ""}</span>` : ""}
          ${similarityHint ? `<span class="retrieval-similarity">${escapeHtml(similarityHint.message || "文库存在疑似相似条目")}${similarityMatches ? `：${escapeHtml(similarityMatches)}` : ""}</span>` : ""}
          ${renderCandidateAiEvaluation(candidate)}
          ${renderRetrievalZoteroPreview(candidate)}
          <span class="retrieval-meta">${escapeHtml([creators, year, venue].filter(Boolean).join(" · "))}</span>
          ${badges ? `<span class="retrieval-badges">${badges}</span>` : ""}
          ${abstract ? `<span class="retrieval-abstract">${escapeHtml(abstract.slice(0, 260))}${abstract.length > 260 ? "..." : ""}</span>` : ""}
        </span>
      </label>`;
    }).join("")}
  </div>`;
}

function selectedRetrievalCandidates() {
  return state.retrievalCandidates.filter((candidate) => state.retrievalSelectedKeys.has(candidate.client_key));
}

function setRetrievalCandidateSelection(mode) {
  state.retrievalSelectedKeys.clear();
  if (mode === "all") {
    state.retrievalCandidates.forEach((candidate) => {
      if (candidate.client_key) state.retrievalSelectedKeys.add(candidate.client_key);
    });
  } else if (mode === "ai") {
    state.retrievalCandidates.forEach((candidate) => {
      if (candidate.client_key && retrievalCandidateIsAiRecommended(candidate)) state.retrievalSelectedKeys.add(candidate.client_key);
    });
  }
  renderRetrievalPage();
}

function retrievalSourceSetupText(info) {
  const setup = info.setup || {};
  const configEnv = setup.config_env || "";
  const alternateEnv = setup.alternate_config_env || "";
  if (setup.config_mode === "preference_or_env" && configEnv) return `配置：面板或 ${configEnv}`;
  if (setup.config_mode === "required_any_env" && configEnv && alternateEnv) return `配置：${configEnv} 或 ${alternateEnv}`;
  if (setup.config_mode === "required_env" && configEnv) return `配置：${configEnv}`;
  if (setup.config_mode === "optional_env" && configEnv) return `可选：${configEnv}`;
  return "";
}

function retrievalSourceSetupTitle(info) {
  const setup = info.setup || {};
  const parts = [];
  const setupText = retrievalSourceSetupText(info);
  if (setupText) parts.push(setupText);
  if (setup.preference_api) parts.push(`文库配置 API：${setup.preference_api}`);
  if (setup.rate_limit_env) parts.push(`源级限流：${setup.rate_limit_env}`);
  if (setup.global_rate_limit_env) parts.push(`全局限流：${setup.global_rate_limit_env}`);
  (setup.notes || []).forEach((note) => {
    if (note) parts.push(note);
  });
  return parts.join("\n");
}

function renderRetrievalSourceOption(name, fallbackLabel) {
  const info = state.retrievalSourceInfo[name] || {};
  const label = info.label || fallbackLabel;
  const unavailable = info.available === false;
  const checked = !unavailable && state.retrievalSources.has(name);
  const health = info.health || null;
  const healthText = health ? (health.ok ? `健康 ${health.elapsed_ms || 0}ms` : `${health.error_kind || "异常"}：${health.action || health.error || ""}`) : "";
  const rateText = formatRateLimitSeconds(info.rate_limit_seconds);
  const note = info.rate_limit_note || "";
  const setupText = retrievalSourceSetupText(info);
  const setupTitle = retrievalSourceSetupTitle(info);
  const title = [note, setupTitle].filter(Boolean).join("\n");
  const status = [info.message || (state.retrievalSourcesBusy ? "检查中" : ""), rateText, healthText].filter(Boolean).join("；");
  const showSetup = Boolean(setupText && (unavailable || info.optional_config));
  return `<label class="${unavailable ? "unavailable" : ""} ${health && health.ok === false ? "warning" : ""}" title="${escapeHtml(title)}">
    <input type="checkbox" name="sources" value="${escapeHtml(name)}" ${checked ? "checked" : ""} ${unavailable ? "disabled" : ""}>
    <span>${escapeHtml(label)}</span>
    ${status ? `<em class="retrieval-source-status">${escapeHtml(status)}</em>` : ""}
    ${showSetup ? `<small class="retrieval-source-setup">${escapeHtml(setupText)}</small>` : ""}
  </label>`;
}

function retrievalReadinessStatusLabel(status) {
  return {
    ready: "Ready",
    warning: "Review",
    blocked: "Blocked",
    needs_sampling: "Sampling",
    good: "Good",
    empty: "Empty",
    poor: "Poor",
    error: "Error",
    skipped: "Skipped",
    missing: "Missing",
    active: "Active",
    failed_queries: "Failed",
    source_errors: "Src errors",
    incomplete: "Incomplete",
    source_gap: "Source gap",
    no_candidates: "No hits",
    low_sample: "Low sample",
    passed: "Passed",
  }[status] || "Review";
}

function renderRetrievalReadiness() {
  const readiness = state.retrievalReadiness;
  if (!readiness && !state.retrievalReadinessBusy && !state.retrievalReadinessMessage) return "";
  const summary = readiness?.summary || {};
  const status = readiness?.status || (state.retrievalReadinessBusy ? "warning" : "skipped");
  const entries = (readiness?.previews || [])
    .filter((entry) => entry.configured || entry.previewed || entry.status !== "skipped")
    .map((entry) => {
      const quality = entry.quality || {};
      const fieldMapSuggestion = entry.field_map_suggestion || {};
      const fieldMapCount = Number(fieldMapSuggestion.suggested_field_count || 0);
      const fieldMapDetail = fieldMapCount
        ? `map ${fieldMapCount}${fieldMapSuggestion.draft_available ? " / draft" : ""}`
        : (fieldMapSuggestion.status === "error" ? "map error" : "");
      const recommendations = (entry.recommendations || quality.recommendations || []).slice(0, 2).join(" / ");
      const applyDraft = fieldMapSuggestion.draft_available
        ? `<button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-readiness-field-map="${escapeHtml(entry.name || "")}" title="Apply field_map draft">Apply</button>`
        : "";
      const details = [
        `${Number(entry.sample_count || 0)} samples`,
        quality.score !== undefined ? `score ${quality.score}` : "",
        fieldMapDetail,
        recommendations,
      ].filter(Boolean).join(" / ");
      return `<span class="${escapeHtml(entry.status || "skipped")}" title="${escapeHtml(entry.message || recommendations || "")}">
        <strong>${escapeHtml(entry.label || entry.name || "Source")}</strong>
        <em>${escapeHtml(retrievalReadinessStatusLabel(entry.status))}${details ? ` / ${details}` : ""}</em>
        ${applyDraft}
      </span>`;
    }).join("");
  const message = state.retrievalReadinessMessage || readiness?.message || "";
  return `<section class="retrieval-readiness" data-retrieval-readiness>
    <div class="retrieval-readiness-head">
      <strong class="${escapeHtml(status)}">${escapeHtml(retrievalReadinessStatusLabel(status))}</strong>
      <span>${escapeHtml(message || "No readiness check has run yet.")}</span>
    </div>
    <div class="retrieval-readiness-grid">
      <span><strong>${Number(summary.available_source_count || 0)}</strong><em>available sources</em></span>
      <span><strong>${Number(summary.configured_internal_count || 0)}</strong><em>configured internal</em></span>
      <span><strong>${Number(summary.previewed_internal_count || 0)}</strong><em>previewed internal</em></span>
      <span><strong>${Number(summary.sample_count || 0)}</strong><em>samples</em></span>
    </div>
    <div class="retrieval-readiness-sources">${entries || `<p class="retrieval-history-message">No internal source configured.</p>`}</div>
  </section>`;
}

function retrievalSourceEvidenceStatus(item) {
  if (Number(item?.failure_count || 0)) return "source_errors";
  if (Number(item?.query_count || 0)) return "passed";
  if (item?.requested) return "missing";
  return "skipped";
}

function retrievalSourceEvidenceDiagnostic(item) {
  const errorKind = String(item?.latest_error_kind || "").trim();
  const diagnostic = String(item?.latest_diagnostic || "").trim();
  if (errorKind && diagnostic && errorKind !== diagnostic) return `${errorKind}: ${diagnostic}`;
  return errorKind || diagnostic || "";
}

function renderRetrievalOnboardingSourceEvidence(batch) {
  const evidence = Array.isArray(batch?.source_evidence) ? batch.source_evidence : [];
  if (!evidence.length) return "";
  const entries = evidence.map((item) => {
    const status = retrievalSourceEvidenceStatus(item);
    const diagnostic = retrievalSourceEvidenceDiagnostic(item);
    const detail = [
      `q ${Number(item.query_count || 0)}`,
      `ok ${Number(item.success_count || 0)}`,
      `fail ${Number(item.failure_count || 0)}`,
      `hits ${Number(item.candidate_count || 0)}`,
      `${Number(item.elapsed_ms || 0)}ms`,
    ].join(" / ");
    const title = [
      item.requested ? "requested" : "observed",
      detail,
      diagnostic,
    ].filter(Boolean).join("\n");
    return `<span class="${escapeHtml(status)}" title="${escapeHtml(title)}">
      <strong>${escapeHtml(item.source || "source")}</strong>
      <em>${escapeHtml(detail)}${diagnostic ? ` / ${escapeHtml(diagnostic)}` : ""}</em>
    </span>`;
  }).join("");
  return `<div class="retrieval-readiness-sources retrieval-source-evidence" data-retrieval-onboarding-source-evidence>${entries}</div>`;
}

function renderRetrievalOnboardingGates(onboarding) {
  const gates = Array.isArray(onboarding?.acceptance_gates) ? onboarding.acceptance_gates : [];
  if (!gates.length) return "";
  const entries = gates.map((gate) => {
    const status = gate.status || "warning";
    const evidence = gate.evidence || "";
    const message = gate.message || "";
    const artifacts = Array.isArray(gate.artifacts) ? gate.artifacts : [];
    const artifactButtons = artifacts.slice(0, 3).map((artifact) => {
      const endpoint = artifact.endpoint || "";
      if (!endpoint) return "";
      return `<button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-gate-artifact="${escapeHtml(endpoint)}" title="${escapeHtml(artifact.label || "Download artifact")}">${escapeHtml(artifact.label || "Artifact")}</button>`;
    }).join("");
    const title = [evidence, message].filter(Boolean).join("\n");
    return `<span class="${escapeHtml(status)}" title="${escapeHtml(title)}">
      <strong>${escapeHtml(gate.label || gate.name || "Gate")}</strong>
      <em>${escapeHtml(retrievalReadinessStatusLabel(status))}${evidence ? ` / ${escapeHtml(evidence)}` : ""}</em>
      ${artifactButtons}
    </span>`;
  }).join("");
  return `<div class="retrieval-readiness-sources retrieval-onboarding-gates" data-retrieval-onboarding-gates>${entries}</div>`;
}

function retrievalRemediationButtonHtml(remediation, scope) {
  const method = String(remediation?.method || "GET").trim().toUpperCase();
  const endpoint = String(remediation?.endpoint || "").trim();
  const label = String(remediation?.label || "").trim();
  const queryCount = Array.isArray(remediation?.queries) ? remediation.queries.length : 0;
  const canRunBatch = endpoint !== "/retrieval/batches" || queryCount > 0;
  if (method !== "POST" || !safeRetrievalEndpoint(endpoint) || !label || !canRunBatch) return "";
  return `<button type="button" class="mini-icon retrieval-report-btn" data-run-retrieval-remediation="${escapeHtml(scope)}" title="${escapeHtml(`${method} ${endpoint}`)}">${escapeHtml(label)}</button>`;
}

function renderRetrievalOnboarding() {
  const onboarding = state.retrievalOnboarding;
  if (!onboarding && !state.retrievalOnboardingBusy && !state.retrievalOnboardingMessage) return "";
  const summary = onboarding?.summary || {};
  const batch = onboarding?.batch_validation || {};
  const importReadiness = onboarding?.import_readiness || {};
  const status = onboarding?.status || (state.retrievalOnboardingBusy ? "warning" : "skipped");
  const message = state.retrievalOnboardingMessage || onboarding?.message || "";
  const batchStatus = batch.status || summary.batch_validation_status || "";
  const batchMessage = batch.message || summary.batch_validation_message || "";
  const latestJobId = batch.latest_job_id || "";
  const batchRemediation = batch.remediation || {};
  const batchRemediationButton = retrievalRemediationButtonHtml(batchRemediation, "onboarding");
  const queryCoverageLabel = summary.validation_query_source === "explicit" ? "query coverage" : "PLAN coverage";
  const configContextStatus = summary.batch_config_context_status || batch.config_context_status || "unknown";
  const configContextTitle = [
    `matched ${Number(summary.batch_config_matched_job_count || batch.config_matched_job_count || 0)}`,
    `mismatch ${Number(summary.batch_config_mismatch_job_count || batch.config_mismatch_job_count || 0)}`,
    `unknown ${Number(summary.batch_config_unknown_job_count || batch.config_unknown_job_count || 0)}`,
  ].join(" / ");
  const batchActions = latestJobId || batchRemediationButton
    ? `<div class="retrieval-local-config-actions retrieval-onboarding-actions">
        ${latestJobId ? `<button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-batch-report="${escapeHtml(latestJobId)}" data-report-format="markdown" title="Download latest batch validation report">Batch report</button>` : ""}
        ${latestJobId ? `<button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-batch-report="${escapeHtml(latestJobId)}" data-report-format="csv" data-report-scope="sources" title="Download latest batch source evidence CSV">Source CSV</button>` : ""}
        ${batchRemediationButton}
      </div>`
    : "";
  const recommendations = (onboarding?.recommendations || []).slice(0, 3)
    .map((item) => `<span class="${escapeHtml(status)}" title="${escapeHtml(item)}"><strong>Next</strong><em>${escapeHtml(item)}</em></span>`)
    .join("");
  return `<section class="retrieval-readiness retrieval-onboarding" data-retrieval-onboarding>
    <div class="retrieval-readiness-head">
      <strong class="${escapeHtml(status)}">${escapeHtml(retrievalReadinessStatusLabel(status))}</strong>
      <span>${escapeHtml(message || "No onboarding check has run yet.")}</span>
    </div>
    <div class="retrieval-readiness-grid">
      <span><strong>${escapeHtml(retrievalReadinessStatusLabel(batchStatus || "missing"))}</strong><em>batch validation</em></span>
      <span><strong>${Number(summary.batch_completed_queries || batch.completed_queries || 0)}/${Number(summary.batch_required_completed_queries || batch.required_completed_queries || 0)}</strong><em>query samples</em></span>
      <span title="${escapeHtml((summary.batch_missing_queries || batch.missing_queries || []).join("; "))}"><strong>${Number(summary.batch_covered_query_count || batch.covered_query_count || 0)}/${Number(summary.batch_required_query_count || batch.required_query_count || 0)}</strong><em>${escapeHtml(queryCoverageLabel)}</em></span>
      <span><strong>${escapeHtml(summary.validation_query_source || "query_plan")}</strong><em>query source</em></span>
      <span><strong>${escapeHtml(summary.query_plan_ai_status || "skipped")}</strong><em>AI PLAN</em></span>
      <span><strong>${Number(summary.batch_validated_source_count || batch.validated_source_count || 0)}/${Number(summary.batch_required_source_count || batch.required_source_count || 0)}</strong><em>source coverage</em></span>
      <span title="${escapeHtml(configContextTitle)}"><strong>${escapeHtml(configContextStatus)}</strong><em>config evidence</em></span>
      <span title="${escapeHtml(importReadiness.message || "")}"><strong>${Number(summary.import_readiness_ready_candidate_count || importReadiness.ready_candidate_count || 0)}/${Number(summary.import_readiness_checked_candidate_count || importReadiness.checked_candidate_count || 0)}</strong><em>import ready</em></span>
      <span><strong>${Number(summary.batch_failed_queries || batch.failed_queries || 0)}</strong><em>failed queries</em></span>
      <span><strong>${Number(summary.batch_source_error_count || batch.source_error_count || 0)}</strong><em>source errors</em></span>
    </div>
    ${batchMessage ? `<p class="retrieval-source-message">${escapeHtml(batchMessage)}</p>` : ""}
    ${batchActions}
    ${renderRetrievalOnboardingGates(onboarding)}
    ${renderRetrievalOnboardingSourceEvidence(batch)}
    <div class="retrieval-readiness-sources">${recommendations || `<p class="retrieval-history-message">No onboarding recommendations yet.</p>`}</div>
  </section>`;
}

function renderRetrievalConfigBundleImportResult(result) {
  if (!result) return "";
  const applied = Array.isArray(result.applied) ? result.applied : [];
  const skipped = Array.isArray(result.skipped) ? result.skipped : [];
  const actionText = result.dry_run ? "would apply" : "applied";
  const rows = [
    ...applied.map((item) => `<span class="ok"><em>${escapeHtml(item.source || "")}</em>${escapeHtml(item.action || actionText)}</span>`),
    ...skipped.map((item) => `<span class="warning"><em>${escapeHtml(item.source || "")}</em>${escapeHtml(item.reason || "skipped")}</span>`),
  ].join("");
  return `<div class="retrieval-local-preview retrieval-config-bundle-result" data-retrieval-config-bundle-result>
    <div class="retrieval-local-preview-head">
      <strong>${escapeHtml(result.dry_run ? "Dry-run result" : "Import result")}</strong>
      <span>${applied.length} ${escapeHtml(actionText)} / ${skipped.length} skipped</span>
      <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-config-bundle-result title="Download config bundle result CSV">CSV</button>
    </div>
    <div class="retrieval-local-preview-issues">${rows || `<span>No source changes</span>`}</div>
  </div>`;
}

function renderRetrievalConfigBundleImport() {
  return `<section class="retrieval-local-config retrieval-config-bundle" data-retrieval-config-bundle-import>
    <div class="retrieval-source-config-head">
      <div>
        <span class="retrieval-config-kicker">配置包</span>
        <h3>导入别人给你的源配置</h3>
        <p>如果队友已经整理好脱敏配置包，把 JSON 粘贴到这里，先 Dry run，再 Import。</p>
      </div>
    </div>
    <form data-retrieval-config-bundle-form>
      <label>
        <span>Config bundle JSON</span>
        <textarea name="bundle" rows="5" data-retrieval-config-bundle-input placeholder='{"schema":"web-library.retrieval-config-bundle/v1","sources":{}}'>${escapeHtml(state.retrievalConfigBundleText)}</textarea>
      </label>
      <div class="retrieval-local-config-actions">
        <button type="button" class="mini-icon retrieval-report-btn" data-dry-run-retrieval-config-bundle ${state.retrievalConfigBundleBusy ? "disabled" : ""} title="Preview config bundle import">${state.retrievalConfigBundleBusy ? "..." : "Dry run"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-import-retrieval-config-bundle ${state.retrievalConfigBundleBusy ? "disabled" : ""} title="Import config bundle">Import</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-config-bundle ${state.retrievalConfigBundleBusy ? "disabled" : ""} title="Clear config bundle draft">Clear</button>
      </div>
      ${state.retrievalConfigBundleMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalConfigBundleMessage)}</p>` : ""}
    </form>
    ${renderRetrievalConfigBundleImportResult(state.retrievalConfigBundleResult)}
  </section>`;
}

function retrievalSourceStatusText(name) {
  const info = state.retrievalSourceInfo[name] || {};
  if (state.retrievalSourcesBusy) return "检查中";
  if (info.available === false) return info.message || "未配置";
  if (info.available === true) return info.message || "可用";
  return "未检查";
}

function retrievalSourceStatusClass(name) {
  const info = state.retrievalSourceInfo[name] || {};
  if (info.available === false) return "blocked";
  if (info.available === true) return "ready";
  return "unknown";
}

function renderRetrievalSourceStatusBadge(name) {
  return `<span class="retrieval-source-config-status ${retrievalSourceStatusClass(name)}">${escapeHtml(retrievalSourceStatusText(name))}</span>`;
}

function renderRetrievalSourceConfigGuide() {
  const publicSources = [
    ["论文文献", "期刊论文、会议论文、跨库论文元数据", [
      ["crossref", "Crossref", "论文 DOI/期刊元数据"],
      ["semanticscholar", "Semantic Scholar", "论文补充和相似论文"],
      ["openalex", "OpenAlex", "开放学术图谱"],
    ]],
    ["预印本", "arXiv、bioRxiv、medRxiv 等预发表论文", [
      ["arxiv", "arXiv", "通用预印本"],
      ["biorxiv", "bioRxiv", "生命科学预印本"],
      ["medrxiv", "medRxiv", "医学预印本"],
    ]],
    ["领域库", "生命科学、天文物理等专业数据库", [
      ["pubmed", "PubMed", "生命科学和医学"],
      ["ads", "NASA ADS", "天文/物理"],
    ]],
    ["数据集 / 软件 / 代码对象", "带 DOI 或清单的研究数据、软件、代码产物", [
      ["datacite", "DataCite", "数据集、软件 DOI、报告"],
      ["manifest", "Manifest", "代码包、附件、对象清单"],
    ]],
    ["图书 / 其他资料", "图书、章节和非论文型资料", [
      ["openlibrary", "OpenLibrary", "图书元数据"],
    ]],
  ].map(([category, description, sources]) => `<article class="retrieval-public-source-category">
    <div>
      <strong>${escapeHtml(category)}</strong>
      <em>${escapeHtml(description)}</em>
    </div>
    <div>${sources.map(([name, label, hint]) => `<span>
      <strong>${escapeHtml(label)}</strong>
      <em>${escapeHtml(hint)}</em>
      ${renderRetrievalSourceStatusBadge(name)}
    </span>`).join("")}</div>
  </article>`).join("");
  const internalSources = [
    ["#source-localfile-config", "Local CSV/JSONL", "本地表格、导出的论文清单、实验记录表", "结构化文件", "路径 + field_map"],
    ["#source-httpjson-config", "HTTP JSON", "内部检索接口、代码仓库索引 API、第三方 JSON API", "接口服务", "url_template + items_path + field_map"],
    ["#source-sqlite-config", "SQLite", "本机数据库、代码/数据资产索引库、已有元数据表", "数据库", "path + query + field_map"],
    ["#source-manifest-config", "Manifest", "代码包、数据集对象、附件、PDF、对象 URL 清单", "对象清单", "manifest_path + items_path + field_map"],
  ].map(([href, title, useCase, typeLabel, required]) => `<a href="${href}">
    <strong>${escapeHtml(title)}</strong>
    <b>${escapeHtml(typeLabel)}</b>
    <span>${escapeHtml(useCase)}</span>
    <em>必填：${escapeHtml(required)}</em>
  </a>`).join("");
  return `<section class="retrieval-source-config-guide">
    <div class="retrieval-source-config-head">
      <div>
        <span class="retrieval-config-kicker">源配置说明</span>
        <h3>先判断你要接哪种源</h3>
        <p>这里按资料对象分类：论文、预印本、领域库、数据集/软件/代码对象、图书，以及本地/内部系统。</p>
      </div>
      <button type="button" class="mini-icon retrieval-report-btn" data-check-retrieval-sources title="刷新数据源状态">${state.retrievalSourcesChecking ? "..." : "刷新状态"}</button>
    </div>
    <div class="retrieval-config-steps">
      <span><strong>1. 选源类型</strong><em>看你的数据是文件、接口、数据库还是清单。</em></span>
      <span><strong>2. 填最少字段</strong><em>先让源能返回 title / doi / year 等元数据。</em></span>
      <span><strong>3. 保存并预览</strong><em>点保存配置，再用预览或检查确认映射正常。</em></span>
      <span><strong>4. 回到上方检索</strong><em>勾选该源，输入关键词开始检索。</em></span>
    </div>
    <div class="retrieval-public-sources">
      <strong>公共源按资料类型分类</strong>
      ${publicSources}
    </div>
    <div class="retrieval-internal-source-title">
      <strong>本地/内部异构源</strong>
      <em>用于接入比赛数据、代码索引、内部 API、数据库或对象清单。</em>
    </div>
    <div class="retrieval-config-source-links">${internalSources}</div>
  </section>`;
}

function renderRetrievalSourceConfigHeader(sourceName, title, description, requiredItems, nextStep) {
  return `<div class="retrieval-source-config-head">
    <div>
      <span class="retrieval-config-kicker">源配置</span>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(description)}</p>
    </div>
    ${renderRetrievalSourceStatusBadge(sourceName)}
  </div>
  <div class="retrieval-config-required">
    ${requiredItems.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
    ${nextStep ? `<em>${escapeHtml(nextStep)}</em>` : ""}
  </div>`;
}

function renderRetrievalSourceIntakeResult(result) {
  if (!result) return "";
  const candidates = Array.isArray(result.candidates) ? result.candidates : [];
  const suggestion = result.field_map_suggestion || {};
  const fieldMap = suggestion.field_map || {};
  const signals = result.signals || {};
  const validation = result.validation_queries || {};
  const targetSource = result.target_source || {};
  const validationPlan = result.validation_plan || {};
  const batchValidation = validationPlan.batch_validation || {};
  const batchRemediation = batchValidation.remediation || {};
  const batchRemediationButton = retrievalRemediationButtonHtml(batchRemediation, "source-intake");
  const candidateRows = candidates.slice(0, 4)
    .map((item) => `<span title="${escapeHtml((item.reasons || []).join("; "))}"><em>${escapeHtml(item.label || item.source_type || "")}</em>${Math.round(Number(item.score || 0) * 100)}% / ${escapeHtml(item.endpoint || "")}</span>`)
    .join("");
  const requiredRows = (candidates[0]?.required || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  const fieldRows = Object.entries(fieldMap)
    .map(([target, sourcePath]) => `<span><em>${escapeHtml(target)}</em>${escapeHtml(sourcePath)}</span>`)
    .join("");
  const validationRows = (validation.queries || []).slice(0, 5)
    .map((item) => `<span title="${escapeHtml(item.reason || "")}"><em>${escapeHtml(item.query || "")}</em>${Number(item.sample_count || 0)} sample</span>`)
    .join("");
  const intakeConfigContextTitle = [
    `matched ${Number(batchValidation.config_matched_job_count || 0)}`,
    `mismatch ${Number(batchValidation.config_mismatch_job_count || 0)}`,
    `unknown ${Number(batchValidation.config_unknown_job_count || 0)}`,
  ].join(" / ");
  const targetSourceRows = [
    targetSource.name ? `<span><em>target source</em>${escapeHtml(targetSource.name)}${targetSource.endpoint ? ` / ${escapeHtml(targetSource.endpoint)}` : ""}</span>` : "",
    validationPlan.minimum_queries ? `<span><em>minimum queries</em>${Number(validationPlan.minimum_queries || 0)}</span>` : "",
    validationPlan.query_count !== undefined ? `<span><em>draft queries</em>${Number(validationPlan.query_count || 0)}</span>` : "",
    batchValidation.status ? `<span title="${escapeHtml(batchValidation.message || "")}"><em>batch evidence</em>${escapeHtml(batchValidation.status || "")} / ${Number(batchValidation.completed_queries || 0)} of ${Number(batchValidation.required_completed_queries || 0)}</span>` : "",
    batchValidation.required_query_count ? `<span title="${escapeHtml((batchValidation.missing_queries || []).join("; "))}"><em>draft coverage</em>${Number(batchValidation.covered_query_count || 0)} of ${Number(batchValidation.required_query_count || 0)}</span>` : "",
    batchValidation.config_context_status ? `<span title="${escapeHtml(intakeConfigContextTitle)}"><em>config evidence</em>${escapeHtml(batchValidation.config_context_status || "")}</span>` : "",
    batchRemediation.label ? `<span title="${escapeHtml(`${batchRemediation.method || "GET"} ${batchRemediation.endpoint || ""}`)}"><em>next action</em>${escapeHtml(batchRemediation.label || "")}</span>` : "",
  ].filter(Boolean).join("");
  const validationGateRows = (validationPlan.gates || []).slice(0, 4)
    .map((gate) => `<span title="${escapeHtml(gate.evidence || "")}"><em>${escapeHtml(gate.label || gate.name || "")}</em>${escapeHtml(gate.status || "")}${gate.endpoint ? ` / ${escapeHtml(gate.endpoint)}` : ""}</span>`)
    .join("");
  const validationArtifactRows = (validationPlan.artifacts || []).slice(0, 5)
    .map((artifact) => `<span><em>${escapeHtml(artifact.label || "")}</em>${escapeHtml(artifact.endpoint || "")}</span>`)
    .join("");
  const signalRows = [
    signals.extension ? `ext .${signals.extension}` : "",
    signals.has_url ? "url" : "",
    signals.has_sql ? "sql" : "",
    signals.has_json_sample ? "json" : "",
    signals.items_path ? `items ${signals.items_path}` : "",
    signals.column_count ? `${signals.column_count} columns` : "",
    signals.sampled_path ? `sample ${signals.sampled_path}` : "",
    signals.sampled_url ? `url sample ${signals.sampled_url}` : "",
    signals.sampled_table ? `table ${signals.sampled_table}` : "",
    signals.sampling_error ? `sample error ${signals.sampling_error}` : "",
  ].filter(Boolean).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  return `<div class="retrieval-local-preview retrieval-source-intake-result" data-retrieval-source-intake-result>
    <div class="retrieval-local-preview-head">
      <strong>${escapeHtml(result.source_type || "source")} / ${escapeHtml(result.status || "")}</strong>
      <span>${Math.round(Number(result.confidence || 0) * 100)}% confidence</span>
    </div>
    ${candidateRows ? `<div class="retrieval-local-preview-fields">${candidateRows}</div>` : ""}
    ${signalRows ? `<div class="retrieval-local-preview-fields">${signalRows}</div>` : ""}
    ${requiredRows ? `<div class="retrieval-local-preview-issues">${requiredRows}</div>` : ""}
    <div class="retrieval-local-preview-mappings">${fieldRows || `<span class="unmapped">No field_map draft yet</span>`}</div>
    ${validationRows ? `<div class="retrieval-local-preview-fields">${validationRows}</div>` : ""}
    ${validationPlan.status ? `<div class="retrieval-local-preview-head"><strong>Validation plan / ${escapeHtml(validationPlan.status || "")}</strong><span>${escapeHtml(validationPlan.message || "")}</span></div>` : ""}
    ${batchRemediationButton ? `<div class="retrieval-local-config-actions retrieval-source-intake-actions">${batchRemediationButton}</div>` : ""}
    ${targetSourceRows ? `<div class="retrieval-local-preview-fields">${targetSourceRows}</div>` : ""}
    ${validationGateRows ? `<div class="retrieval-local-preview-fields">${validationGateRows}</div>` : ""}
    ${validationArtifactRows ? `<div class="retrieval-local-preview-fields">${validationArtifactRows}</div>` : ""}
  </div>`;
}

function renderRetrievalSourceIntake() {
  const draftAvailable = Boolean(state.retrievalSourceIntakeResult?.field_map_lab);
  const configDraft = state.retrievalSourceIntakeResult?.field_map_suggestion?.config_draft || {};
  const configDraftAvailable = Boolean(configDraft && Object.keys(configDraft).length);
  const validationQueryText = String(state.retrievalSourceIntakeResult?.validation_queries?.query_text || "").trim();
  const validationQueryAvailable = Boolean(validationQueryText);
  return `<section class="retrieval-local-config retrieval-source-intake" data-retrieval-source-intake>
    <div class="retrieval-source-config-head">
      <div>
        <span class="retrieval-config-kicker">快速识别</span>
        <h3>不知道怎么配时，先粘贴源信息</h3>
        <p>可以粘贴文件路径、接口 URL、SQL、CSV 表头或 JSON 样例，系统会判断适合放到哪类源配置。</p>
      </div>
    </div>
    <label>
      <span>源信息</span>
      <small>示例：C:\\data\\items.csv，https://api.example.test/search?q={query}，或 SELECT title, doi FROM records。</small>
      <textarea name="source_intake" rows="4" data-retrieval-source-intake-input placeholder="C:\\data\\items.csv or https://api.example.test/search?q={query} or SELECT title, doi FROM records">${escapeHtml(state.retrievalSourceIntakeInput)}</textarea>
    </label>
    <div class="retrieval-local-config-actions">
      <label>
        <span>真实请求采样</span>
        <input type="checkbox" data-retrieval-source-intake-sample-url ${state.retrievalSourceIntakeSampleUrl ? "checked" : ""} ${state.retrievalSourceIntakeBusy ? "disabled" : ""}>
      </label>
      <button type="button" class="mini-icon retrieval-report-btn" data-analyze-retrieval-source-intake ${state.retrievalSourceIntakeBusy ? "disabled" : ""} title="分析源信息">${state.retrievalSourceIntakeBusy ? "..." : "分析"}</button>
      <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-source-intake data-report-format="markdown" ${state.retrievalSourceIntakeBusy ? "disabled" : ""} title="下载源识别报告">报告</button>
      <button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-source-intake ${state.retrievalSourceIntakeBusy || !draftAvailable ? "disabled" : ""} title="把识别结果放入字段映射实验室">去映射</button>
      <button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-source-intake-config ${state.retrievalSourceIntakeBusy || !configDraftAvailable ? "disabled" : ""} title="把识别出的配置草稿写入目标源">套用配置</button>
      <button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-source-intake-queries ${state.retrievalSourceIntakeBusy || !validationQueryAvailable ? "disabled" : ""} title="把验证 query 放入批量检索">套用 query</button>
      <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-source-intake ${state.retrievalSourceIntakeBusy ? "disabled" : ""} title="清空源识别">清空</button>
    </div>
    ${state.retrievalSourceIntakeMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalSourceIntakeMessage)}</p>` : ""}
    ${renderRetrievalSourceIntakeResult(state.retrievalSourceIntakeResult)}
  </section>`;
}

function renderRetrievalFieldMapLabResult(result) {
  if (!result) return "";
  const fieldMap = result.field_map || {};
  const quality = result.quality || {};
  const ai = result.ai_enhancement || {};
  const suggestions = Array.isArray(result.suggestions) ? result.suggestions : [];
  const recommendations = Array.isArray(quality.recommendations) ? quality.recommendations : [];
  const fieldRows = Object.entries(fieldMap)
    .map(([target, sourcePath]) => `<span><em>${escapeHtml(target)}</em>${escapeHtml(sourcePath)}</span>`)
    .join("");
  const suggestionRows = suggestions.slice(0, 12)
    .map((item) => `<span title="${escapeHtml(item.reason || "")}"><em>${escapeHtml(item.target || "")}</em>${escapeHtml(item.source_path || "")}</span>`)
    .join("");
  const recommendationRows = recommendations.slice(0, 4).map((message) => `<span>${escapeHtml(message)}</span>`).join("");
  const aiStatus = ai.requested
    ? `<span title="${escapeHtml(ai.message || "")}">AI ${escapeHtml(ai.status || "requested")} - ${Number(ai.applied_field_count || 0)} applied</span>`
    : "";
  const score = Math.round(Number(quality.score || 0) * 100);
  return `<div class="retrieval-local-preview retrieval-field-map-lab-result" data-retrieval-field-map-lab-result>
    <div class="retrieval-local-preview-head">
      <strong>${escapeHtml(quality.status || "field_map")}${quality.status ? ` / ${score}%` : ""}</strong>
      <span>${Object.keys(fieldMap).length} fields / ${suggestions.length} suggestions</span>
    </div>
    <div class="retrieval-local-preview-mappings">${fieldRows || `<span class="unmapped">No field_map suggestions</span>`}</div>
    ${suggestionRows ? `<div class="retrieval-local-preview-fields">${suggestionRows}</div>` : ""}
    ${aiStatus ? `<div class="retrieval-local-preview-fields">${aiStatus}</div>` : ""}
    ${recommendationRows ? `<div class="retrieval-local-preview-issues">${recommendationRows}</div>` : ""}
  </div>`;
}

function renderRetrievalFieldMapLab() {
  const model = state.retrievalModelStatus || {};
  const health = model.health || {};
  const aiConfigured = model.configured === true;
  const aiStatusKnown = Boolean(model.provider || state.retrievalModelStatusMessage);
  const aiDisabled = state.retrievalFieldMapLabBusy || !aiConfigured;
  const healthChecked = health.checked === true;
  let aiStatusText = `AI Pixel off - set ${model.api_key_env || "AI_PIXEL_API_KEY"}`;
  if (state.retrievalModelStatusBusy || !aiStatusKnown) {
    aiStatusText = "AI Pixel checking";
  } else if (healthChecked && health.ok) {
    aiStatusText = `AI Pixel live - ${model.model || "model"} / ${Number(health.elapsed_ms || 0)} ms`;
  } else if (healthChecked) {
    aiStatusText = `AI Pixel check failed - ${health.error_kind || "error"}`;
  } else if (aiConfigured) {
    aiStatusText = `AI Pixel ready - ${model.model || "model"}`;
  }
  const aiStatusClass = aiConfigured && (!healthChecked || health.ok) ? "ok" : "warning";
  const aiStatusTitle = health.error || health.message || state.retrievalModelStatusMessage || model.base_url || "";
  const sourceOptions = [
    ["localfile", "Local CSV/JSONL"],
    ["httpjson", "HTTP JSON"],
    ["sqlite", "SQLite"],
    ["manifest", "Object Manifest"],
  ].map(([value, label]) => `<option value="${value}" ${state.retrievalFieldMapLabSource === value ? "selected" : ""}>${label}</option>`).join("");
  const modeOptions = [
    ["columns", "Columns"],
    ["samples", "JSON samples"],
  ].map(([value, label]) => `<option value="${value}" ${state.retrievalFieldMapLabMode === value ? "selected" : ""}>${label}</option>`).join("");
  const draftAvailable = Boolean(state.retrievalFieldMapLabResult?.config_draft && Object.keys(state.retrievalFieldMapLabResult.config_draft).length);
  const inputPlaceholder = state.retrievalFieldMapLabMode === "samples"
    ? '[{"paper_title":"AI4S Dataset","publication_year":"2026","doi":"10.6060/example"}]'
    : "paper_title, publication_year, doi, authors, object_url";
  return `<section class="retrieval-local-config retrieval-field-map-lab" data-retrieval-field-map-lab>
    <div class="retrieval-source-config-head">
      <div>
        <span class="retrieval-config-kicker">字段映射</span>
        <h3>字段名对不齐时，用这里生成 field_map</h3>
        <p>把源里的列名或 JSON 样例粘贴进来，生成 title、date、doi、authors 等 Zotero 字段映射。</p>
      </div>
    </div>
    <form data-retrieval-field-map-lab-form>
      <div class="retrieval-field-map-lab-controls">
        <label>
          <span>源类型</span>
          <select name="source_type" data-retrieval-field-map-lab-source>${sourceOptions}</select>
        </label>
        <label>
          <span>输入格式</span>
          <select name="input_mode" data-retrieval-field-map-lab-mode>${modeOptions}</select>
        </label>
        <label>
          <span>AI</span>
          <input type="checkbox" name="use_ai" data-retrieval-field-map-lab-ai ${state.retrievalFieldMapLabUseAi && aiConfigured ? "checked" : ""} ${aiDisabled ? "disabled" : ""}>
        </label>
      </div>
      <p class="retrieval-source-message ${aiStatusClass}" data-retrieval-model-status title="${escapeHtml(aiStatusTitle)}">${escapeHtml(aiStatusText)}</p>
      <label>
        <span>列名或 JSON 样例</span>
        <small>只需要粘贴少量样例；优先保证 title、date/year、doi、authors 能映射出来。</small>
        <textarea name="input" rows="4" data-retrieval-field-map-lab-input placeholder="${escapeHtml(inputPlaceholder)}">${escapeHtml(state.retrievalFieldMapLabInput)}</textarea>
      </label>
      <label>
        <span>可选：已有配置 JSON</span>
        <small>如果已经写了一部分配置，可粘贴进来让系统只补 field_map。</small>
        <textarea name="config" rows="4" data-retrieval-field-map-lab-config placeholder='{"label":"Draft source","field_map":{}}'>${escapeHtml(state.retrievalFieldMapLabConfig)}</textarea>
      </label>
      <div class="retrieval-local-config-actions">
        <button type="button" class="mini-icon retrieval-report-btn" data-check-retrieval-model-status ${state.retrievalModelStatusBusy || !aiConfigured ? "disabled" : ""} title="检查 AI Pixel 接口">检查 AI</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-suggest-retrieval-field-map-lab ${state.retrievalFieldMapLabBusy ? "disabled" : ""} title="建议 field_map">${state.retrievalFieldMapLabBusy ? "..." : "生成映射"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-field-map-report data-report-format="markdown" ${state.retrievalFieldMapLabBusy ? "disabled" : ""} title="下载字段映射报告">报告</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-field-map-lab ${state.retrievalFieldMapLabBusy || !draftAvailable ? "disabled" : ""} title="套用 field_map 草稿">套用草稿</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-field-map-lab ${state.retrievalFieldMapLabBusy ? "disabled" : ""} title="清空字段映射实验室">清空</button>
      </div>
      ${state.retrievalFieldMapLabMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalFieldMapLabMessage)}</p>` : ""}
    </form>
    ${renderRetrievalFieldMapLabResult(state.retrievalFieldMapLabResult)}
  </section>`;
}

function renderRetrievalLocalConfig() {
  const info = state.retrievalSourceInfo.localfile || {};
  const status = info.message || "";
  return `<form class="retrieval-local-config" data-retrieval-local-paths-form>
    <label>
      <span>Local CSV/JSONL 路径</span>
      <textarea name="paths" rows="2" data-retrieval-local-paths-input placeholder="C:\\data\\items.csv">${escapeHtml(state.retrievalLocalPaths)}</textarea>
    </label>
    <div class="retrieval-local-config-actions">
      <button type="submit" class="mini-icon retrieval-report-btn" ${state.retrievalLocalPathsBusy ? "disabled" : ""} title="保存本地检索路径">保存</button>
      <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-local-paths ${state.retrievalLocalPathsBusy ? "disabled" : ""} title="清空本地检索路径">清空</button>
      ${status ? `<em>${escapeHtml(status)}</em>` : ""}
    </div>
    ${state.retrievalLocalPathsMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalLocalPathsMessage)}</p>` : ""}
  </form>`;
}

function renderRetrievalLocalConfigWithPreview() {
  const info = state.retrievalSourceInfo.localfile || {};
  const status = info.message || "";
  return `<section class="retrieval-local-config retrieval-config-source" id="source-localfile-config">
    ${renderRetrievalSourceConfigHeader(
      "localfile",
      "Local CSV/JSONL",
      "适合已经在本机整理好的 CSV 或 JSONL 元数据文件。",
      ["paths：一个或多个本地文件路径", "field_map：把源字段映射到 title / date / doi / authors 等字段"],
      "保存后点“自动建议字段”或看预览；回到上方检索时勾选 Local。",
    )}
    <form data-retrieval-local-paths-form>
      <label>
        <span>1. 文件路径</span>
        <small>每行一个文件路径；支持 CSV 和 JSONL。</small>
        <textarea name="paths" rows="2" data-retrieval-local-paths-input placeholder="C:\\data\\items.csv">${escapeHtml(state.retrievalLocalPaths)}</textarea>
      </label>
      <label>
        <span>2. 字段映射 field_map</span>
        <small>左边是文库字段，右边是 CSV/JSONL 里的字段名。先不知道可点“自动建议字段”。</small>
        <textarea name="field_map" rows="4" data-retrieval-local-field-map-input placeholder='{"title":"paper_title","date":"publication_year","doi":"doi","authors":"authors"}'>${escapeHtml(state.retrievalLocalFieldMap)}</textarea>
      </label>
      <div class="retrieval-local-config-actions">
        <button type="submit" class="mini-icon retrieval-report-btn" ${state.retrievalLocalPathsBusy ? "disabled" : ""} title="保存本地源配置">保存配置</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-local-paths ${state.retrievalLocalPathsBusy ? "disabled" : ""} title="清空本地源配置">清空</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-suggest-retrieval-local-field-map ${state.retrievalLocalPreviewBusy ? "disabled" : ""} title="从样本自动建议 field_map">自动建议字段</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-configured-field-map="localfile" data-report-format="markdown" ${state.retrievalLocalPreviewBusy ? "disabled" : ""} title="下载本地源字段映射报告">字段报告</button>
        ${status ? `<em>${escapeHtml(status)}</em>` : ""}
      </div>
      ${state.retrievalLocalPathsMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalLocalPathsMessage)}</p>` : ""}
    </form>
    ${renderRetrievalLocalPreview()}
  </section>`;
}

function renderRetrievalHttpJsonConfig() {
  const info = state.retrievalSourceInfo.httpjson || {};
  const status = info.message || "";
  const templateButtons = (state.retrievalHttpJsonTemplates || [])
    .map((template) => `<button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-http-json-template="${escapeHtml(template.id || "")}" title="${escapeHtml(template.description || "Apply HTTP JSON template")}">${escapeHtml(template.label || template.id || "Template")}</button>`)
    .join("");
  const placeholder = `{
  "label": "Internal API",
  "url_template": "https://example.test/search?q={query}&limit={limit}&page={page}",
  "items_path": "results",
  "next_url_path": "links.next",
  "max_pages": 3,
  "auth": {
    "type": "bearer_env",
    "env": "INTERNAL_API_TOKEN"
  },
  "headers": {
    "X-Team": "\${ENV:INTERNAL_TEAM}"
  },
  "field_map": {
    "title": "title",
    "date": "year",
    "doi": "doi",
    "abstract": "abstract",
    "authors": "authors",
    "url": "url",
    "venue": "venue",
    "item_type": "item_type",
    "tags": "keywords",
    "external_id": "id"
  }
}`;
  return `<section class="retrieval-local-config retrieval-http-json-config retrieval-config-source" id="source-httpjson-config" data-retrieval-http-json-config>
    ${renderRetrievalSourceConfigHeader(
      "httpjson",
      "HTTP JSON",
      "适合内部检索接口、第三方 JSON API，或者任何能用 query 参数返回 JSON 列表的服务。",
      ["url_template：检索接口，必须包含 {query}", "items_path：结果列表在 JSON 里的位置", "field_map：把结果字段映射到文库字段"],
      "保存后点“预览样本”；确认能看到候选样本后，回到上方检索时勾选 HTTP。",
    )}
    <form data-retrieval-http-json-form>
      <label>
        <span>HTTP JSON 配置</span>
        <small>最少写 url_template、items_path、field_map；需要鉴权时再加 auth 或 headers。</small>
        <textarea name="config" rows="8" data-retrieval-http-json-input placeholder="${escapeHtml(placeholder)}">${escapeHtml(state.retrievalHttpJsonConfig)}</textarea>
      </label>
      <div class="retrieval-local-config-actions">
        <button type="submit" class="mini-icon retrieval-report-btn" ${state.retrievalHttpJsonBusy ? "disabled" : ""} title="保存 HTTP JSON 配置">保存配置</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-http-json ${state.retrievalHttpJsonBusy ? "disabled" : ""} title="清空 HTTP JSON 配置">清空</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-suggest-retrieval-http-json-field-map ${state.retrievalHttpJsonBusy ? "disabled" : ""} title="从真实样本自动建议 HTTP JSON field_map">${state.retrievalHttpJsonBusy ? "..." : "自动建议字段"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-configured-field-map="httpjson" data-report-format="markdown" ${state.retrievalHttpJsonBusy ? "disabled" : ""} title="下载 HTTP JSON 字段映射报告">字段报告</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-refresh-retrieval-http-json-preview ${state.retrievalHttpJsonPreviewBusy ? "disabled" : ""} title="预览 HTTP JSON 字段映射">${state.retrievalHttpJsonPreviewBusy ? "..." : "预览样本"}</button>
        ${status ? `<em>${escapeHtml(status)}</em>` : ""}
      </div>
      ${templateButtons ? `<div class="retrieval-local-config-actions retrieval-http-json-templates"><em>模板：</em>${templateButtons}</div>` : ""}
      ${state.retrievalHttpJsonMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalHttpJsonMessage)}</p>` : ""}
    </form>
    ${renderRetrievalHttpJsonPreview()}
  </section>`;
}

function renderRetrievalHttpJsonPreview() {
  const preview = state.retrievalHttpJsonPreview || {};
  const samples = preview.samples || [];
  const quality = preview.quality || {};
  const score = Number(quality.score || 0);
  const qualityLabel = quality.status ? `${quality.status} · ${Math.round(score * 100)}% coverage` : "";
  const coverage = (quality.fields || [])
    .map((field) => {
      const percent = Math.round(Number(field.coverage || 0) * 100);
      const issueClass = Number(field.missing_count || 0) ? (field.severity || "warning") : "ok";
      return `<span class="${escapeHtml(issueClass)}" title="${escapeHtml(field.message || "")}">${escapeHtml(field.label || field.field || "")} <em>${percent}%</em></span>`;
    })
    .join("");
  const recommendations = (quality.recommendations || [])
    .map((message) => `<span>${escapeHtml(message)}</span>`)
    .join("");
  return `<div class="retrieval-local-preview retrieval-http-json-preview" data-retrieval-http-json-preview>
    <div class="retrieval-local-preview-head">
      <strong>HTTP JSON mapping preview</strong>
      <span>${escapeHtml(preview.query ? `query: ${preview.query}` : "")}</span>
    </div>
    ${state.retrievalHttpJsonPreviewMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalHttpJsonPreviewMessage)}</p>` : ""}
    ${qualityLabel ? `<div class="retrieval-local-preview-quality ${escapeHtml(quality.status || "")}">
      <strong>${escapeHtml(qualityLabel)}</strong>
      ${coverage ? `<div>${coverage}</div>` : ""}
      ${recommendations ? `<small>${recommendations}</small>` : ""}
    </div>` : ""}
    ${samples.length ? `<div class="retrieval-local-preview-samples">
      ${samples.map((sample) => renderRetrievalLocalPreviewSample(sample)).join("")}
    </div>` : `<p class="retrieval-history-message">Save a valid HTTP JSON config, then preview how source results map into Zotero fields.</p>`}
  </div>`;
}

function renderRetrievalSqliteConfig() {
  const info = state.retrievalSourceInfo.sqlite || {};
  const status = info.message || "";
  const templateButtons = (state.retrievalSqliteTemplates || [])
    .map((template) => `<button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-sqlite-template="${escapeHtml(template.id || "")}" title="${escapeHtml(template.description || "Apply SQLite template")}">${escapeHtml(template.label || template.id || "Template")}</button>`)
    .join("");
  const placeholder = `{
  "label": "Internal SQLite",
  "path": "C:/data/retrieval.sqlite",
  "query": "SELECT id, title, year, doi, authors, abstract, keywords, url, venue, item_type FROM items WHERE title LIKE :like_query OR abstract LIKE :like_query LIMIT :limit",
  "field_map": {
    "title": "title",
    "date": "year",
    "doi": "doi",
    "abstract": "abstract",
    "authors": "authors",
    "url": "url",
    "venue": "venue",
    "item_type": "item_type",
    "tags": "keywords",
    "external_id": "id"
  }
}`;
  return `<section class="retrieval-local-config retrieval-sqlite-config retrieval-config-source" id="source-sqlite-config" data-retrieval-sqlite-config>
    ${renderRetrievalSourceConfigHeader(
      "sqlite",
      "SQLite",
      "适合本机 SQLite 数据库，尤其是已有结构化表、需要用 SQL 检索的元数据源。",
      ["path：SQLite 文件路径", "query：带 :like_query 或 :query 的 SQL", "field_map：把 SQL 返回列映射到文库字段"],
      "保存后点“预览样本”；确认 SQL 能返回样本后，回到上方检索时勾选 SQLite。",
    )}
    <form data-retrieval-sqlite-form>
      <label>
        <span>SQLite 配置</span>
        <small>SQL 返回列名要和 field_map 右侧一致；建议先 LIMIT :limit。</small>
        <textarea name="config" rows="8" data-retrieval-sqlite-input placeholder="${escapeHtml(placeholder)}">${escapeHtml(state.retrievalSqliteConfig)}</textarea>
      </label>
      <div class="retrieval-local-config-actions">
        <button type="submit" class="mini-icon retrieval-report-btn" ${state.retrievalSqliteBusy ? "disabled" : ""} title="保存 SQLite 配置">保存配置</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-sqlite ${state.retrievalSqliteBusy ? "disabled" : ""} title="清空 SQLite 配置">清空</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-suggest-retrieval-sqlite-field-map ${state.retrievalSqliteBusy ? "disabled" : ""} title="从真实行自动建议 SQLite field_map">${state.retrievalSqliteBusy ? "..." : "自动建议字段"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-configured-field-map="sqlite" data-report-format="markdown" ${state.retrievalSqliteBusy ? "disabled" : ""} title="下载 SQLite 字段映射报告">字段报告</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-refresh-retrieval-sqlite-preview ${state.retrievalSqlitePreviewBusy ? "disabled" : ""} title="预览 SQLite 字段映射">${state.retrievalSqlitePreviewBusy ? "..." : "预览样本"}</button>
        ${status ? `<em>${escapeHtml(status)}</em>` : ""}
      </div>
      ${templateButtons ? `<div class="retrieval-local-config-actions retrieval-sqlite-templates"><em>模板：</em>${templateButtons}</div>` : ""}
      ${state.retrievalSqliteMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalSqliteMessage)}</p>` : ""}
    </form>
    ${renderRetrievalSqlitePreview()}
  </section>`;
}

function renderRetrievalSqlitePreview() {
  const preview = state.retrievalSqlitePreview || {};
  const samples = preview.samples || [];
  const quality = preview.quality || {};
  const score = Number(quality.score || 0);
  const qualityLabel = quality.status ? `${quality.status} · ${Math.round(score * 100)}% coverage` : "";
  const coverage = (quality.fields || [])
    .map((field) => {
      const percent = Math.round(Number(field.coverage || 0) * 100);
      const issueClass = Number(field.missing_count || 0) ? (field.severity || "warning") : "ok";
      return `<span class="${escapeHtml(issueClass)}" title="${escapeHtml(field.message || "")}">${escapeHtml(field.label || field.field || "")} <em>${percent}%</em></span>`;
    })
    .join("");
  const recommendations = (quality.recommendations || [])
    .map((message) => `<span>${escapeHtml(message)}</span>`)
    .join("");
  return `<div class="retrieval-local-preview retrieval-sqlite-preview" data-retrieval-sqlite-preview>
    <div class="retrieval-local-preview-head">
      <strong>SQLite mapping preview</strong>
      <span>${escapeHtml(preview.query ? `query: ${preview.query}` : "")}</span>
    </div>
    ${state.retrievalSqlitePreviewMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalSqlitePreviewMessage)}</p>` : ""}
    ${qualityLabel ? `<div class="retrieval-local-preview-quality ${escapeHtml(quality.status || "")}">
      <strong>${escapeHtml(qualityLabel)}</strong>
      ${coverage ? `<div>${coverage}</div>` : ""}
      ${recommendations ? `<small>${recommendations}</small>` : ""}
    </div>` : ""}
    ${samples.length ? `<div class="retrieval-local-preview-samples">
      ${samples.map((sample) => renderRetrievalLocalPreviewSample(sample)).join("")}
    </div>` : `<p class="retrieval-history-message">Save a valid SQLite config, then preview how source rows map into Zotero fields.</p>`}
  </div>`;
}

function renderRetrievalManifestConfig() {
  const info = state.retrievalSourceInfo.manifest || {};
  const status = info.message || "";
  const templateButtons = (state.retrievalManifestTemplates || [])
    .map((template) => `<button type="button" class="mini-icon retrieval-report-btn" data-apply-retrieval-manifest-template="${escapeHtml(template.id || "")}" title="${escapeHtml(template.description || "Apply object manifest template")}">${escapeHtml(template.label || template.id || "Template")}</button>`)
    .join("");
  const placeholder = `{
  "label": "Object Manifest",
  "manifest_path": "C:/data/object-manifest.json",
  "items_path": "items",
  "field_map": {
    "title": "title",
    "date": "year",
    "doi": "doi",
    "abstract": "abstract",
    "authors": "authors",
    "url": "object_url",
    "pdf_url": "pdf_url",
    "venue": "venue",
    "item_type": "item_type",
    "tags": "keywords",
    "external_id": "id"
  }
}`;
  return `<section class="retrieval-local-config retrieval-manifest-config retrieval-config-source" id="source-manifest-config" data-retrieval-manifest-config>
    ${renderRetrievalSourceConfigHeader(
      "manifest",
      "Object Manifest",
      "适合对象清单、附件清单、数据集索引这类 JSON manifest。",
      ["manifest_path：清单文件路径", "items_path：条目数组在清单里的位置", "field_map：把清单字段映射到文库字段"],
      "保存后点“预览样本”；确认能看到对象样本后，回到上方检索时勾选 Manifest。",
    )}
    <form data-retrieval-manifest-form>
      <label>
        <span>Object Manifest 配置</span>
        <small>Manifest 通常用于把对象 URL、PDF URL、数据集文件等一起保存进文库条目。</small>
        <textarea name="config" rows="8" data-retrieval-manifest-input placeholder="${escapeHtml(placeholder)}">${escapeHtml(state.retrievalManifestConfig)}</textarea>
      </label>
      <div class="retrieval-local-config-actions">
        <button type="submit" class="mini-icon retrieval-report-btn" ${state.retrievalManifestBusy ? "disabled" : ""} title="保存 Object Manifest 配置">保存配置</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-clear-retrieval-manifest ${state.retrievalManifestBusy ? "disabled" : ""} title="清空 Object Manifest 配置">清空</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-suggest-retrieval-manifest-field-map ${state.retrievalManifestBusy ? "disabled" : ""} title="从真实对象自动建议 manifest field_map">${state.retrievalManifestBusy ? "..." : "自动建议字段"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-configured-field-map="manifest" data-report-format="markdown" ${state.retrievalManifestBusy ? "disabled" : ""} title="下载 Object Manifest 字段映射报告">字段报告</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-refresh-retrieval-manifest-preview ${state.retrievalManifestPreviewBusy ? "disabled" : ""} title="预览 Object Manifest 字段映射">${state.retrievalManifestPreviewBusy ? "..." : "预览样本"}</button>
        ${status ? `<em>${escapeHtml(status)}</em>` : ""}
      </div>
      ${templateButtons ? `<div class="retrieval-local-config-actions retrieval-manifest-templates"><em>模板：</em>${templateButtons}</div>` : ""}
      ${state.retrievalManifestMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalManifestMessage)}</p>` : ""}
    </form>
    ${renderRetrievalManifestPreview()}
  </section>`;
}

function renderRetrievalManifestPreview() {
  const preview = state.retrievalManifestPreview || {};
  const samples = preview.samples || [];
  const quality = preview.quality || {};
  const score = Number(quality.score || 0);
  const qualityLabel = quality.status ? `${quality.status} · ${Math.round(score * 100)}% coverage` : "";
  const coverage = (quality.fields || [])
    .map((field) => {
      const percent = Math.round(Number(field.coverage || 0) * 100);
      const issueClass = Number(field.missing_count || 0) ? (field.severity || "warning") : "ok";
      return `<span class="${escapeHtml(issueClass)}" title="${escapeHtml(field.message || "")}">${escapeHtml(field.label || field.field || "")} <em>${percent}%</em></span>`;
    })
    .join("");
  const recommendations = (quality.recommendations || [])
    .map((message) => `<span>${escapeHtml(message)}</span>`)
    .join("");
  return `<div class="retrieval-local-preview retrieval-manifest-preview" data-retrieval-manifest-preview>
    <div class="retrieval-local-preview-head">
      <strong>Object manifest mapping preview</strong>
      <span>${escapeHtml(preview.query ? `query: ${preview.query}` : "")}</span>
    </div>
    ${state.retrievalManifestPreviewMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalManifestPreviewMessage)}</p>` : ""}
    ${qualityLabel ? `<div class="retrieval-local-preview-quality ${escapeHtml(quality.status || "")}">
      <strong>${escapeHtml(qualityLabel)}</strong>
      ${coverage ? `<div>${coverage}</div>` : ""}
      ${recommendations ? `<small>${recommendations}</small>` : ""}
    </div>` : ""}
    ${samples.length ? `<div class="retrieval-local-preview-samples">
      ${samples.map((sample) => renderRetrievalLocalPreviewSample(sample)).join("")}
    </div>` : `<p class="retrieval-history-message">Save a valid object manifest config, then preview how source objects map into Zotero fields.</p>`}
  </div>`;
}

function renderRetrievalLocalPreview() {
  const preview = state.retrievalLocalPreview || {};
  const files = preview.files || [];
  return `<div class="retrieval-local-preview" data-retrieval-local-preview>
    <div class="retrieval-local-preview-head">
      <strong>Local field mapping preview</strong>
      <button type="button" class="mini-icon retrieval-report-btn" data-refresh-retrieval-local-preview ${state.retrievalLocalPreviewBusy ? "disabled" : ""} title="Preview local field mapping">${state.retrievalLocalPreviewBusy ? "..." : "Preview"}</button>
    </div>
    ${state.retrievalLocalPreviewMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalLocalPreviewMessage)}</p>` : ""}
    ${files.length ? `<div class="retrieval-local-preview-files">
      ${files.map((file) => renderRetrievalLocalPreviewFile(file)).join("")}
    </div>` : `<p class="retrieval-history-message">Save a valid local CSV/JSONL path, then preview how source columns map into Zotero fields.</p>`}
  </div>`;
}

function renderRetrievalLocalPreviewFile(file) {
  const rowText = `${file.truncated ? ">=" : ""}${file.row_count || 0} rows`;
  const quality = file.quality || {};
  const fieldMapSuggestion = file.field_map_suggestion || {};
  const fieldMapCount = Number(fieldMapSuggestion.suggested_field_count || 0);
  const fieldMapText = fieldMapCount ? `map ${fieldMapCount} / config` : "";
  const score = Number(quality.score || 0);
  const qualityLabel = quality.status ? `${quality.status} · ${Math.round(score * 100)}% coverage` : "";
  const coverage = (quality.fields || [])
    .map((field) => {
      const percent = Math.round(Number(field.coverage || 0) * 100);
      const issueClass = Number(field.missing_count || 0) ? (field.severity || "warning") : "ok";
      return `<span class="${escapeHtml(issueClass)}" title="${escapeHtml(field.message || "")}">${escapeHtml(field.label || field.field || "")} <em>${percent}%</em></span>`;
    })
    .join("");
  const recommendations = (quality.recommendations || [])
    .map((message) => `<span>${escapeHtml(message)}</span>`)
    .join("");
  const mappings = (file.mappings || [])
    .map((mapping) => `<span class="${mapping.target ? "" : "unmapped"}">${escapeHtml(mapping.column)} <em>${escapeHtml(mapping.label || "unmapped")}</em></span>`)
    .join("");
  const samples = (file.samples || []).map((sample) => renderRetrievalLocalPreviewSample(sample)).join("");
  return `<article class="retrieval-local-preview-file">
    <div class="retrieval-local-preview-file-head">
      <strong>${escapeHtml(file.name || file.path || "local file")}</strong>
      <span>${escapeHtml([file.format, rowText, fieldMapText].filter(Boolean).join(" / "))}</span>
    </div>
    <div class="retrieval-local-preview-quality ${escapeHtml(quality.status || "")}">
      <strong>${escapeHtml(qualityLabel || "coverage pending")}</strong>
      ${coverage ? `<div>${coverage}</div>` : ""}
      ${recommendations ? `<small>${recommendations}</small>` : ""}
    </div>
    <div class="retrieval-local-preview-mappings">${mappings || `<span class="unmapped">No columns</span>`}</div>
    <div class="retrieval-local-preview-samples">${samples || `<p class="retrieval-history-message">No sample rows.</p>`}</div>
  </article>`;
}

function renderRetrievalLocalPreviewSample(sample) {
  const item = sample.item || {};
  const fields = item.fields || {};
  const identifiers = item.identifiers || {};
  const quality = sample.quality || {};
  const issues = (quality.issues || [])
    .map((issue) => `<span class="${escapeHtml(issue.severity || "warning")}">${escapeHtml(issue.message || issue.label || "")}</span>`)
    .join("");
  const creators = (item.creators || []).map((creator) => [creator.first_name, creator.last_name].filter(Boolean).join(" ")).filter(Boolean).join(" / ");
  const tags = (item.tags || []).join(", ");
  const fieldSummary = ["title", "date", "publicationTitle", "DOI", "url"]
    .map((key) => fields[key] ? `<span><em>${escapeHtml(key)}</em>${escapeHtml(fields[key])}</span>` : "")
    .join("");
  const identifierSummary = Object.entries(identifiers)
    .map(([key, value]) => `<span><em>${escapeHtml(key)}</em>${escapeHtml(value)}</span>`)
    .join("");
  return `<div class="retrieval-local-preview-sample">
    <div class="retrieval-local-preview-sample-head">
      <strong>#${escapeHtml(sample.row || "")} ${escapeHtml(fields.title || sample.title || "Untitled")}</strong>
      <em>${escapeHtml([item.item_type || "item", quality.status ? `${quality.status} ${Math.round(Number(quality.score || 0) * 100)}%` : ""].filter(Boolean).join(" / "))}</em>
    </div>
    <div class="retrieval-local-preview-fields">${fieldSummary}${identifierSummary}</div>
    ${issues ? `<div class="retrieval-local-preview-issues">${issues}</div>` : ""}
    ${(creators || tags) ? `<small>${escapeHtml([creators, tags].filter(Boolean).join(" / "))}</small>` : ""}
  </div>`;
}

function retrievalBatchIsActive(job) {
  return ["queued", "running"].includes(String(job?.status || ""));
}

function retrievalBackgroundJobIsActive(job) {
  return ["queued", "running", "canceling"].includes(String(job?.status || ""));
}

function retrievalBackgroundJobIsTerminal(job) {
  return ["completed", "partial", "canceled", "failed"].includes(String(job?.status || ""));
}

function formatRetrievalEta(seconds) {
  const value = Number(seconds || 0);
  if (!value) return "";
  if (value < 60) return `ETA ${Math.max(1, Math.round(value))}s`;
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  if (minutes < 60) return `ETA ${minutes}m${remainder ? ` ${remainder}s` : ""}`;
  const hours = Math.floor(minutes / 60);
  const minuteRemainder = minutes % 60;
  return `ETA ${hours}h${minuteRemainder ? ` ${minuteRemainder}m` : ""}`;
}

function renderRetrievalBatchPanel() {
  const rows = (state.retrievalBatchJobs || []).map((job) => renderRetrievalBatchRow(job)).join("");
  const aiConfigured = state.retrievalModelStatus?.configured === true;
  const aiDisabled = !aiConfigured || state.retrievalQueryPlanBusy || state.retrievalBatchBusy;
  return `<section class="retrieval-batch" data-retrieval-batches>
    <div class="retrieval-history-head">
      <strong>Batch retrieval</strong>
      <button type="button" class="mini-icon" data-refresh-retrieval-batches title="Refresh batch jobs">${state.retrievalBatchBusy ? "..." : "Refresh"}</button>
    </div>
    <form class="retrieval-batch-form" data-retrieval-batch-form>
      <textarea name="queries" rows="3" data-retrieval-batch-queries placeholder="One query per line">${escapeHtml(state.retrievalBatchQueries)}</textarea>
      <div class="retrieval-local-config-actions">
        <label class="retrieval-inline-toggle" title="${aiConfigured ? "Use AI Pixel to refine PLAN queries" : "Set AI_PIXEL_API_KEY to enable AI PLAN"}">
          <input type="checkbox" data-retrieval-query-plan-ai ${state.retrievalQueryPlanUseAi && aiConfigured ? "checked" : ""} ${aiDisabled ? "disabled" : ""}>
          <span>AI</span>
        </label>
        <button type="button" class="mini-icon retrieval-report-btn" data-draft-retrieval-batch-queries ${state.retrievalBatchBusy || state.retrievalQueryPlanBusy ? "disabled" : ""} title="Draft validation queries from configured source previews">${state.retrievalQueryPlanBusy ? "..." : "PLAN"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-query-plan data-report-format="markdown" ${state.retrievalQueryPlanBusy ? "disabled" : ""} title="Download query plan report">PLAN RPT</button>
        <button type="submit" class="mini-icon retrieval-report-btn" ${state.retrievalBatchBusy ? "disabled" : ""} title="Start batch retrieval">Start batch</button>
      </div>
    </form>
    ${state.retrievalBatchMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalBatchMessage)}</p>` : ""}
    <div class="retrieval-batch-list">${state.retrievalBatchBusy && !rows ? `<p class="retrieval-history-message">Loading...</p>` : rows || `<p class="retrieval-history-message">No batch jobs yet.</p>`}</div>
  </section>`;
}

function renderRetrievalBatchRow(job) {
  const total = Number(job.total_queries || 0);
  const completed = Number(job.completed_queries || 0);
  const failed = Number(job.failed_queries || 0);
  const candidates = Number(job.total_candidates || 0);
  const percent = total ? Math.round((completed / total) * 100) : 0;
  const queries = (job.queries || []).slice(0, 3).join(" / ");
  const active = retrievalBatchIsActive(job);
  const paused = String(job.status || "") === "paused";
  const remaining = Number(job.remaining_queries || 0);
  const eta = formatRetrievalEta(job.eta_seconds);
  const timing = [remaining ? `${remaining} remaining` : "", eta].filter(Boolean).join(" / ");
  const canRetryFailed = failed > 0 && !active && !paused;
  const actions = [
    job.job_id ? `<button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-batch-report="${escapeHtml(job.job_id || "")}" data-report-format="markdown" ${state.retrievalBatchBusy ? "disabled" : ""} title="Download batch retrieval report">Report</button>` : "",
    job.job_id ? `<button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-batch-report="${escapeHtml(job.job_id || "")}" data-report-format="csv" data-report-scope="sources" ${state.retrievalBatchBusy ? "disabled" : ""} title="Download source evidence CSV">SRC CSV</button>` : "",
    active ? `<button type="button" class="mini-icon retrieval-report-btn" data-pause-retrieval-batch="${escapeHtml(job.job_id || "")}" ${state.retrievalBatchBusy ? "disabled" : ""} title="Pause batch retrieval">Pause</button>` : "",
    paused ? `<button type="button" class="mini-icon retrieval-report-btn" data-resume-retrieval-batch="${escapeHtml(job.job_id || "")}" ${state.retrievalBatchBusy ? "disabled" : ""} title="Resume batch retrieval">Resume</button>` : "",
    (active || paused) ? `<button type="button" class="mini-icon retrieval-report-btn" data-cancel-retrieval-batch="${escapeHtml(job.job_id || "")}" ${state.retrievalBatchBusy ? "disabled" : ""} title="Cancel batch retrieval">Cancel</button>` : "",
    canRetryFailed ? `<button type="button" class="mini-icon retrieval-report-btn" data-retry-retrieval-batch="${escapeHtml(job.job_id || "")}" ${state.retrievalBatchBusy ? "disabled" : ""} title="Retry failed queries">Retry failed</button>` : "",
  ].filter(Boolean).join("");
  return `<article class="retrieval-batch-row ${active ? "active" : ""}" data-retrieval-batch-row="${escapeHtml(job.job_id || "")}">
    <div class="retrieval-batch-main">
      <strong>${escapeHtml(queries || job.job_id || "batch job")}</strong>
      <span>${escapeHtml(job.status || "queued")} / ${completed}/${total} queries / ${candidates} candidates${failed ? ` / ${failed} failed` : ""}</span>
      ${timing ? `<span>${escapeHtml(timing)}</span>` : ""}
    </div>
    ${actions ? `<div class="retrieval-batch-actions">${actions}</div>` : ""}
    <div class="retrieval-batch-progress"><span style="width:${percent}%"></span></div>
    ${(job.items || []).length ? `<div class="retrieval-batch-items">
      ${job.items.map((item) => `<span class="${escapeHtml(item.status || "")}" title="${escapeHtml(item.error || item.run_id || "")}">${escapeHtml(item.query || "")}${item.run_id ? ` / ${escapeHtml(item.run_id)}` : ""}</span>`).join("")}
    </div>` : ""}
  </article>`;
}

const SIMPLE_RETRIEVAL_SOURCE_CATEGORIES = [
  {
    title: "论文文献",
    tag: "Paper",
    description: "期刊、会议、论文 DOI 和学术图谱。",
    defaultOpen: true,
    sources: [
      ["crossref", "Crossref", "论文 DOI"],
      ["semanticscholar", "Semantic Scholar", "论文补充"],
      ["openalex", "OpenAlex", "开放学术图谱"],
    ],
  },
  {
    title: "预印本",
    tag: "Preprint",
    description: "arXiv、bioRxiv、medRxiv 等预发表论文。",
    defaultOpen: true,
    sources: [
      ["arxiv", "arXiv", "通用预印本"],
      ["biorxiv", "bioRxiv", "生命科学预印本"],
      ["medrxiv", "medRxiv", "医学预印本"],
    ],
  },
  {
    title: "领域数据库",
    tag: "Domain",
    description: "生命科学、天文物理等专业来源。",
    defaultOpen: true,
    sources: [
      ["pubmed", "PubMed", "生命科学/医学"],
      ["ads", "NASA ADS", "天文/物理"],
    ],
  },
  {
    title: "数据集 / 软件 / 代码对象",
    tag: "Data & Code",
    description: "数据集 DOI、软件 DOI、代码包和对象清单。",
    defaultOpen: true,
    sources: [
      ["datacite", "DataCite", "数据/软件 DOI"],
      ["github", "GitHub", "代码仓库"],
      ["huggingface", "HuggingFace", "模型/数据集"],
      ["zenodo", "Zenodo", "软件/数据/报告 DOI"],
      ["manifest", "Manifest", "代码包/对象清单"],
    ],
  },
  {
    title: "本地 / 内部系统",
    tag: "Internal",
    description: "本地文件、内部 API、SQLite 元数据表。",
    defaultOpen: false,
    sources: [
      ["localfile", "Local", "本地 CSV/JSONL"],
      ["httpjson", "HTTP", "内部接口"],
      ["sqlite", "SQLite", "本地库"],
    ],
  },
  {
    title: "图书 / 其他资料",
    tag: "Books",
    description: "图书、章节或其他非论文资料。",
    defaultOpen: false,
    sources: [
      ["openlibrary", "OpenLibrary", "图书元数据"],
    ],
  },
];

function renderSimpleRetrievalSourceOption(name, fallbackLabel, hint) {
  const info = state.retrievalSourceInfo[name] || {};
  const label = info.label || fallbackLabel;
  const unavailable = info.available === false;
  const checked = !unavailable && state.retrievalSources.has(name);
  const health = info.health || null;
  const healthText = health ? (health.ok ? `健康 ${health.elapsed_ms || 0}ms` : `${health.error_kind || "异常"}：${health.action || health.error || ""}`) : "";
  const rateText = formatRateLimitSeconds(info.rate_limit_seconds);
  const setupText = retrievalSourceSetupText(info);
  const detail = [info.message || "", rateText, healthText, setupText].filter(Boolean).join("；");
  const classes = [
    "simple-source-option",
    unavailable ? "unavailable" : "",
    health && health.ok === false ? "warning" : "",
  ].filter(Boolean).join(" ");
  return `<label class="${classes}" title="${escapeHtml(detail)}">
    <input type="checkbox" name="sources" value="${escapeHtml(name)}" ${checked ? "checked" : ""} ${unavailable ? "disabled" : ""}>
    <span>
      <strong>${escapeHtml(label)}</strong>
      <em>${escapeHtml(detail || hint || "可检索")}</em>
    </span>
  </label>`;
}

function renderSimpleRetrievalSourceGroup(options) {
  return `<div class="simple-source-grid">
    ${options.map(([name, label, hint]) => renderSimpleRetrievalSourceOption(name, label, hint)).join("")}
  </div>`;
}

function renderSimpleRetrievalSourceCategory(category) {
  const body = `<article class="simple-source-category">
    <div class="simple-source-category-head">
      <div>
        <strong>${escapeHtml(category.title)}</strong>
        <span>${escapeHtml(category.description)}</span>
      </div>
      <em>${escapeHtml(category.tag)}</em>
    </div>
    ${renderSimpleRetrievalSourceGroup(category.sources)}
  </article>`;
  if (category.defaultOpen) return body;
  return `<details class="simple-source-category collapsed">
    <summary>
      <span>${escapeHtml(category.title)}</span>
      <em>${escapeHtml(category.description)}</em>
    </summary>
    ${renderSimpleRetrievalSourceGroup(category.sources)}
  </details>`;
}

function currentSimplePlanBatchJob() {
  const jobId = String(state.simplePlanBatchJobId || "").trim();
  if (!jobId) return null;
  return (state.retrievalBatchJobs || []).find((job) => String(job.job_id || "") === jobId) || null;
}

function simplePlanRecommendedSources() {
  const selected = new Set(currentRetrievalSourceSelection());
  const recommended = [];
  const queries = Array.isArray(state.retrievalQueryPlan?.queries) ? state.retrievalQueryPlan.queries : [];
  queries.forEach((item) => {
    (item.sources || []).forEach((source) => {
      const cleanSource = String(source || "").trim().toLowerCase();
      if (cleanSource && selected.has(cleanSource) && !recommended.includes(cleanSource)) {
        recommended.push(cleanSource);
      }
    });
  });
  return recommended;
}

function simplePlanBatchSourceSelection() {
  const recommended = simplePlanRecommendedSources();
  const selected = currentRetrievalSourceSelection();
  const sourceNames = recommended.length ? recommended : selected;
  return {
    recommended: recommended.length > 0,
    selected: sourceNames,
    unavailable: unavailableRetrievalSources(sourceNames),
    available: availableRetrievalSources(sourceNames),
  };
}

function currentSimpleBatchLimit() {
  const value = Number(state.retrievalSimpleBatchLimit || 5);
  return Math.max(1, Math.min(Number.isFinite(value) ? Math.round(value) : 5, 20));
}

function currentSimpleBatchLimitFromInput(value) {
  const numeric = Number(value || 5);
  return Math.max(1, Math.min(Number.isFinite(numeric) ? Math.round(numeric) : 5, 20));
}

function currentSimpleBatchMode() {
  return state.retrievalBatchMode === "full" ? "full" : "quick";
}

function defaultSimpleSourceLimit(source) {
  const mode = currentSimpleBatchMode();
  const table = SIMPLE_PLAN_SOURCE_LIMITS_BY_MODE[mode] || SIMPLE_PLAN_SOURCE_LIMITS_BY_MODE.quick;
  const key = String(source || "").trim().toLowerCase();
  return currentSimpleBatchLimitFromInput(table[key] || table.default || state.retrievalSimpleBatchLimit || 5);
}

function currentSimpleSourceLimit(source) {
  const limits = state.retrievalSimpleSourceLimits || {};
  const key = String(source || "").trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(limits, key)) return currentSimpleBatchLimitFromInput(limits[key]);
  return defaultSimpleSourceLimit(key);
}

function simplePlanBatchSourceLimits(sources) {
  const limits = {};
  (sources || []).forEach((source) => {
    const key = String(source || "").trim().toLowerCase();
    if (key) limits[key] = currentSimpleSourceLimit(key);
  });
  return limits;
}

function renderSimplePlanSourceLimits() {
  const sourceSelection = simplePlanBatchSourceSelection();
  const sources = sourceSelection.selected;
  if (!sources.length) return "";
  const mode = currentSimpleBatchMode();
  return `<div class="simple-plan-source-limits">
    <div>
      <strong>每个源取多少条</strong>
      <span>数量越小越快；论文源可稍大，代码/模型/数据源建议小一点。</span>
    </div>
    <div class="simple-plan-mode-toggle" aria-label="计划检索模式">
      <button type="button" data-simple-batch-mode="quick" class="${mode === "quick" ? "active" : ""}">快速模式</button>
      <button type="button" data-simple-batch-mode="full" class="${mode === "full" ? "active" : ""}">全量模式</button>
      <span>${mode === "quick" ? "默认减少 GitHub/HuggingFace/Zenodo 数量，适合演示和快速判断。" : "每源取更多候选，覆盖更全但会更慢。"}</span>
    </div>
    <div class="simple-plan-source-limit-grid">
      ${sources.map((source) => {
        const unavailable = unavailableRetrievalSources([source]).length > 0;
        return `<label class="${unavailable ? "unavailable" : ""}">
          <span>${escapeHtml(retrievalSourceLabel(source))}</span>
          <input type="number" min="1" max="20" step="1" data-simple-source-limit="${escapeHtml(source)}" value="${currentSimpleSourceLimit(source)}" ${unavailable ? "disabled" : ""}>
        </label>`;
      }).join("")}
    </div>
  </div>`;
}

function renderSimplePlanBatchStatus() {
  const job = currentSimplePlanBatchJob();
  if (!job) return "";
  const total = Number(job.total_queries || 0);
  const completed = Number(job.completed_queries || 0);
  const failed = Number(job.failed_queries || 0);
  const candidates = Number(job.total_candidates || 0);
  const percent = total ? Math.max(0, Math.min(100, Math.round((completed / total) * 100))) : 0;
  const status = String(job.status || "queued");
  const active = retrievalBatchIsActive(job);
  const eta = formatRetrievalEta(job.eta_seconds);
  const statusText = active
    ? `正在按计划检索：${completed}/${total}`
    : status === "completed"
      ? `批量检索完成：${completed}/${total}`
      : `批量检索${status}：${completed}/${total}`;
  const note = active
    ? "页面会自动刷新进度；完成后会把合并候选显示到下方候选结果。"
    : "批量结果已进入下方候选结果；如果没有显示，可重新加载。";
  const loadButton = !active && candidates
    ? `<button type="button" class="mini-icon retrieval-report-btn" data-load-simple-batch-candidates="${escapeHtml(job.job_id || "")}" ${state.simplePlanBatchCandidatesBusy ? "disabled" : ""}>${state.simplePlanBatchCandidatesBusy ? "加载中..." : "查看批量结果"}</button>`
    : "";
  const items = (job.items || []).slice(0, 5).map((item) => {
    const itemStatus = String(item.status || "");
    const itemCandidateCount = Number(item.candidate_count || 0);
    const suffix = [
      itemStatus || "queued",
      itemCandidateCount ? `${itemCandidateCount} 条候选` : "",
      item.error ? "有错误" : "",
    ].filter(Boolean).join(" / ");
    return `<span class="${escapeHtml(itemStatus)}" title="${escapeHtml(item.error || item.run_id || "")}">
      <strong>${escapeHtml(item.query || "")}</strong>
      <em>${escapeHtml(suffix)}</em>
    </span>`;
  }).join("");
  return `<div class="simple-plan-batch-status" data-simple-plan-batch-status>
    <div class="simple-plan-batch-status-head">
      <div>
        <strong>${escapeHtml(statusText)}</strong>
        <span>${candidates} 条候选${failed ? `，${failed} 条失败` : ""}${eta ? `，${eta}` : ""}</span>
      </div>
      ${loadButton}
    </div>
    <div class="retrieval-batch-progress" aria-hidden="true"><span style="width:${percent}%"></span></div>
    <p>${escapeHtml(note)}</p>
    ${items ? `<div class="simple-plan-batch-items">${items}</div>` : ""}
  </div>`;
}

function renderSimpleAiQueryPlan() {
  const plan = state.retrievalQueryPlan || null;
  const queries = Array.isArray(plan?.queries) ? plan.queries : [];
  const aiConfigured = state.retrievalModelStatus?.configured === true;
  const batchJob = currentSimplePlanBatchJob();
  const batchActive = retrievalBatchIsActive(batchJob);
  const batchButtonDisabled = state.retrievalBatchBusy || state.simplePlanBatchCandidatesBusy || batchActive;
  const batchButtonText = batchActive ? "批量检索中..." : "按计划批量检索";
  const statusText = queries.length
    ? `${queries.length} 条检索词已准备好，确认后按计划批量检索。`
    : aiConfigured
      ? "AI 会先拆解主题，再批量检索。"
      : "模型未配置，当前只能生成规则计划草案。";
  if (!queries.length && !batchJob && !state.retrievalBatchMessage) return "";
  return `<section class="simple-ai-plan ${queries.length ? "has-plan" : "empty"}">
    <div class="simple-ai-plan-head">
      <div>
        <strong>${queries.length ? "AI 检索计划" : "深度检索状态"}</strong>
        <span>${escapeHtml(statusText)}</span>
      </div>
      <div class="simple-result-tools">
        ${queries.length ? `<button type="button" class="mini-icon retrieval-report-btn" data-simple-plan-batch ${batchButtonDisabled ? "disabled" : ""} title="按计划批量检索">${batchButtonText}</button>` : ""}
      </div>
    </div>
    ${state.retrievalBatchMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalBatchMessage)}</p>` : ""}
    ${renderSimplePlanBatchStatus()}
    ${queries.length ? `<details class="simple-plan-settings">
      <summary>检索数量设置</summary>
      ${renderSimplePlanSourceLimits()}
    </details>` : ""}
    ${queries.length ? `<div class="simple-ai-plan-list">
      ${queries.map((item, index) => `<article>
        <em>${index + 1}</em>
        <div>
          <strong title="${escapeHtml(item.query || "")}">${escapeHtml(item.query || "")}</strong>
          <div class="simple-ai-plan-meta">
            ${item.intent ? `<small>意图：${escapeHtml(item.intent)}</small>` : ""}
            ${(item.sources || []).length ? `<small>源：${escapeHtml((item.sources || []).join(" / "))}</small>` : ""}
          </div>
          <span title="${escapeHtml(item.model_reason || item.reason || "")}">${escapeHtml(item.model_reason || item.reason || "覆盖不同数据源表达方式")}</span>
        </div>
      </article>`).join("")}
    </div>` : `<div class="simple-result-placeholder">输入左侧主题后，先拆解检索词；确认 query 和源后按计划批量检索。</div>`}
  </section>`;
}

function renderSimpleRetrievalMain() {
  const selectedCount = selectedRetrievalCandidates().length;
  const candidateCount = state.retrievalCandidates.length;
  const aiRecommendedCount = state.retrievalCandidates.filter(retrievalCandidateIsAiRecommended).length;
  const aiSummarySource = String(state.retrievalAiEvaluationSummary?.score_source || "");
  const recommendationLabel = "AI 推荐";
  const candidateHtml = renderRetrievalCandidates();
  const selectedSourceNames = uniqueRetrievalSources([...state.retrievalSources]);
  const selectedSourcePreview = selectedSourceNames.slice(0, 4).map(retrievalSourceLabel).join(" / ");
  const selectedSourceSummary = selectedSourceNames.length
    ? `已选 ${selectedSourceNames.length} 个源${selectedSourcePreview ? `：${selectedSourcePreview}${selectedSourceNames.length > 4 ? " ..." : ""}` : ""}`
    : "未选择数据源";
  const aiConfigured = state.retrievalModelStatus?.configured === true;
  const aiPlanButtonText = state.retrievalQueryPlanBusy ? "拆解中..." : "AI 深度检索";
  const hasAiScoring = ["ai_model", "mixed_ai_rules"].includes(aiSummarySource);
  const aiScoreButtonText = state.retrievalAiEvaluationBusy
    ? "AI 排序中..."
    : hasAiScoring ? "重新 AI 排序" : "AI 推荐排序";
  return `
    <section class="simple-retrieval-workbench">
      <form class="add-item-form simple-search-form simple-search-composer retrieval-search-form" data-retrieval-search-form>
        <section class="simple-retrieval-guide" aria-label="三步使用流程" hidden></section>
        <div class="simple-composer-head">
          <div>
            <strong>检索</strong>
          </div>
          <span class="simple-composer-status">${escapeHtml(aiConfigured ? "AI 已配置" : "模型未配置")}</span>
        </div>
        <label class="simple-query-box simple-composer-query">
          <span>主题 / 关键词</span>
          <input name="query" data-retrieval-query-input value="${escapeHtml(state.retrievalQuery)}" placeholder="例如 speculative decoding LLM inference acceleration">
        </label>
        <div class="simple-composer-actions">
          <button type="submit" class="form-action-btn" ${state.addItemBusy ? "disabled" : ""}>${state.addItemBusy ? "检索中..." : "快速检索"}</button>
          <button type="button" class="form-action-btn secondary-action" data-simple-ai-query-plan ${state.retrievalQueryPlanBusy ? "disabled" : ""}>${aiPlanButtonText}</button>
          <span>${escapeHtml(selectedSourceSummary)}</span>
        </div>
        ${renderSimpleAiQueryPlan()}
        <details class="simple-source-drawer">
          <summary>
            <strong>数据源</strong>
            <span>${escapeHtml(selectedSourceSummary)}</span>
          </summary>
          <div class="simple-source-head">
            <div>
              <strong>选择检索源</strong>
            </div>
            <button type="button" class="mini-icon" data-check-retrieval-sources title="刷新数据源状态">${state.retrievalSourcesChecking ? "..." : "↻"}</button>
          </div>
          <div class="simple-source-categories">
            ${SIMPLE_RETRIEVAL_SOURCE_CATEGORIES.map(renderSimpleRetrievalSourceCategory).join("")}
          </div>
          ${state.retrievalSourcesMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalSourcesMessage)}</p>` : ""}
        </details>
      </form>

      <section class="simple-results-panel simple-candidate-board" aria-label="检索结果">
        <div class="simple-results-head">
          <div>
          <strong>候选结果</strong>
          <span>勾选后点击导入所选。</span>
          </div>
          ${candidateCount ? `<div class="simple-result-tools">
            <button type="button" class="mini-icon retrieval-report-btn" data-score-retrieval-candidates-ai ${state.retrievalAiEvaluationBusy || !aiConfigured ? "disabled" : ""}>${aiScoreButtonText}</button>
            ${state.retrievalAiEvaluationBusy ? `<button type="button" class="mini-icon retrieval-report-btn danger" data-stop-retrieval-ai-scoring>停止评分</button>` : ""}
            <button type="button" class="mini-icon retrieval-report-btn" data-select-retrieval-candidates="ai" ${aiRecommendedCount ? "" : "disabled"}>全选${recommendationLabel}${aiRecommendedCount ? ` (${aiRecommendedCount})` : ""}</button>
            <button type="button" class="mini-icon retrieval-report-btn" data-select-retrieval-candidates="all">全选候选</button>
            <button type="button" class="mini-icon retrieval-report-btn" data-select-retrieval-candidates="none">清空选择</button>
          </div>` : ""}
        </div>
        ${renderRetrievalStats()}
        ${renderRetrievalAiSummary()}
        ${candidateHtml || `<div class="simple-result-placeholder">直接检索或计划检索完成后，这里会显示候选条目和推荐判断。</div>`}
        <div class="retrieval-actions simple-import-actions">
          <span>已选择 ${selectedCount} 条</span>
          <button type="button" class="form-action-btn" data-import-retrieval-selected ${state.addItemBusy || !selectedCount ? "disabled" : ""}>${state.addItemBusy ? "导入中..." : "导入所选"}</button>
        </div>
      </section>

      <details class="simple-report-drawer">
        <summary>报告和检查</summary>
        <section class="simple-report-bar" aria-label="常用报告">
          <div>
            <strong>常用检查和报告</strong>
            <span>报告基于最近检索记录；更完整的记录在高级区。</span>
          </div>
          <button type="button" class="mini-icon retrieval-report-btn" data-refresh-retrieval-runs title="刷新最近检索">刷新记录</button>
          <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-summary data-report-format="markdown" title="下载阶段 Markdown 汇总">下载汇总</button>
          <button type="button" class="mini-icon retrieval-report-btn" data-check-retrieval-readiness title="检查内部源是否可交接">${state.retrievalReadinessBusy ? "检查中..." : "检查数据源"}</button>
        </section>
      </details>
    </section>
  `;
}

function renderRetrievalPanel() {
  const selectedCount = selectedRetrievalCandidates().length;
  const sourceOptions = [
    ["crossref", "Crossref"],
    ["arxiv", "arXiv"],
    ["pubmed", "PubMed"],
    ["biorxiv", "bioRxiv"],
    ["medrxiv", "medRxiv"],
    ["semanticscholar", "Semantic Scholar"],
    ["datacite", "DataCite"],
    ["github", "GitHub"],
    ["huggingface", "HuggingFace"],
    ["zenodo", "Zenodo"],
    ["openlibrary", "OpenLibrary"],
    ["ads", "NASA ADS"],
    ["localfile", "Local CSV/JSONL"],
    ["httpjson", "HTTP JSON"],
    ["sqlite", "SQLite"],
    ["manifest", "Object Manifest"],
    ["openalex", "OpenAlex"],
  ].map(([name, label]) => renderRetrievalSourceOption(name, label)).join("");
  return `
    <form class="add-item-form retrieval-search-form" data-retrieval-search-form>
      <label>
        <span>关键词</span>
        <input name="query" data-retrieval-query-input value="${escapeHtml(state.retrievalQuery)}" placeholder="例如 vision language action robot manipulation">
      </label>
      <div class="retrieval-source-row">
        ${sourceOptions}
        <button type="button" class="mini-icon" data-check-retrieval-sources title="检查数据源健康">${state.retrievalSourcesChecking ? "..." : "↻"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-setup-retrieval-rehearsal title="Generate and configure rehearsal internal sources">DEMO KIT</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-validate-retrieval-rehearsal title="Generate rehearsal sources and start validation batch">${state.retrievalBatchBusy ? "..." : "DEMO RUN"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-source-setup data-report-format="markdown" title="下载源配置 Markdown 报告">SETUP</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-check-retrieval-readiness title="Run internal source readiness preflight">${state.retrievalReadinessBusy ? "..." : "READY"}</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-readiness data-report-format="markdown" title="Download readiness Markdown report">RPT</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-tuning data-report-format="markdown" title="下载限流调优 Markdown 报告">TUNE</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-check-retrieval-onboarding title="Check onboarding handoff status">${state.retrievalOnboardingBusy ? "..." : "ONB CHECK"}</button>
        <button type="button" class="mini-icon retrieval-report-btn"
          data-download-retrieval-onboarding data-report-format="markdown"
          title="下载多源检索接入验收报告">ONB</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-onboarding-package title="Download onboarding handoff ZIP">ONB ZIP</button>
        <button type="button" class="mini-icon retrieval-report-btn" data-download-retrieval-config-bundle title="下载脱敏检索源配置包">CFG</button>
      </div>
      ${state.retrievalSourcesMessage ? `<p class="retrieval-source-message">${escapeHtml(state.retrievalSourcesMessage)}</p>` : ""}
      <button type="submit" class="form-action-btn" ${state.addItemBusy ? "disabled" : ""}>${state.addItemBusy ? "检索中..." : "检索候选"}</button>
    </form>
    ${renderRetrievalReadiness()}
    ${renderRetrievalOnboarding()}
    ${renderRetrievalConfigBundleImport()}
    ${renderRetrievalSourceIntake()}
    ${renderRetrievalFieldMapLab()}
    ${renderRetrievalLocalConfigWithPreview()}
    ${renderRetrievalHttpJsonConfig()}
    ${renderRetrievalSqliteConfig()}
    ${renderRetrievalManifestConfig()}
    ${renderRetrievalStats()}
    ${renderRetrievalCandidates()}
    <div class="retrieval-actions">
      <span>已选择 ${selectedCount} 条</span>
      <button type="button" class="form-action-btn" data-import-retrieval-selected ${state.addItemBusy || !selectedCount ? "disabled" : ""}>${state.addItemBusy ? "导入中..." : "导入所选"}</button>
    </div>
    ${renderRetrievalBatchPanel()}
    ${renderRetrievalSummary()}
    ${renderRetrievalRuns()}
  `;
}

function renderAddItemModal() {
  const panel = document.querySelector("[data-add-item-modal]");
  if (!panel) {
    renderRetrievalPage();
    return;
  }
  if (!["identifier", "text"].includes(state.addItemMode)) state.addItemMode = "identifier";
  const isIdentifier = state.addItemMode === "identifier";
  const isText = state.addItemMode === "text";
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
        <button type="button" class="${isText ? "active" : ""}" data-add-item-mode="text">引用文本</button>
      </div>
      ${isIdentifier ? `
        <form class="add-item-form" data-import-identifier-form>
          <label>
            <span>ISBN / DOI / PMID / arXiv ID / ADS Bibcode</span>
            <input name="identifier" data-import-identifier-input placeholder="例如 10.1038/s41586-024-... 或 2406.09246">
          </label>
          <button type="submit" class="form-action-btn" ${state.addItemBusy ? "disabled" : ""}>${state.addItemBusy ? "导入中..." : "导入条目"}</button>
        </form>
      ` : isText ? `
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
      ` : ""}
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
  panel.querySelector("[data-retrieval-search-form]")?.addEventListener("submit", submitRetrievalSearch);
  panel.querySelector("[data-retrieval-local-paths-form]")?.addEventListener("submit", saveRetrievalLocalPaths);
  panel.querySelector("[data-clear-retrieval-local-paths]")?.addEventListener("click", clearRetrievalLocalPaths);
  panel.querySelector("[data-suggest-retrieval-local-field-map]")?.addEventListener("click", () => suggestRetrievalLocalFieldMap());
  panel.querySelectorAll("[data-download-retrieval-configured-field-map]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalConfiguredFieldMapReport(button.dataset.downloadRetrievalConfiguredFieldMap, button.dataset.reportFormat));
  });
  panel.querySelector("[data-refresh-retrieval-local-preview]")?.addEventListener("click", () => loadRetrievalLocalPreview());
  panel.querySelectorAll("[data-apply-retrieval-readiness-field-map]").forEach((button) => {
    button.addEventListener("click", () => applyRetrievalReadinessFieldMapSuggestionToConfig(button.dataset.applyRetrievalReadinessFieldMap));
  });
  panel.querySelector("[data-retrieval-http-json-form]")?.addEventListener("submit", saveRetrievalHttpJsonConfig);
  panel.querySelector("[data-clear-retrieval-http-json]")?.addEventListener("click", clearRetrievalHttpJsonConfig);
  panel.querySelector("[data-suggest-retrieval-http-json-field-map]")?.addEventListener("click", () => suggestRetrievalHttpJsonFieldMap());
  panel.querySelector("[data-refresh-retrieval-http-json-preview]")?.addEventListener("click", () => loadRetrievalHttpJsonPreview());
  panel.querySelectorAll("[data-apply-retrieval-http-json-template]").forEach((button) => {
    button.addEventListener("click", () => applyRetrievalHttpJsonTemplate(button.dataset.applyRetrievalHttpJsonTemplate));
  });
  panel.querySelector("[data-retrieval-sqlite-form]")?.addEventListener("submit", saveRetrievalSqliteConfig);
  panel.querySelector("[data-clear-retrieval-sqlite]")?.addEventListener("click", clearRetrievalSqliteConfig);
  panel.querySelector("[data-suggest-retrieval-sqlite-field-map]")?.addEventListener("click", () => suggestRetrievalSqliteFieldMap());
  panel.querySelector("[data-refresh-retrieval-sqlite-preview]")?.addEventListener("click", () => loadRetrievalSqlitePreview());
  panel.querySelectorAll("[data-apply-retrieval-sqlite-template]").forEach((button) => {
    button.addEventListener("click", () => applyRetrievalSqliteTemplate(button.dataset.applyRetrievalSqliteTemplate));
  });
  panel.querySelector("[data-retrieval-manifest-form]")?.addEventListener("submit", saveRetrievalManifestConfig);
  panel.querySelector("[data-clear-retrieval-manifest]")?.addEventListener("click", clearRetrievalManifestConfig);
  panel.querySelector("[data-suggest-retrieval-manifest-field-map]")?.addEventListener("click", () => suggestRetrievalManifestFieldMap());
  panel.querySelector("[data-refresh-retrieval-manifest-preview]")?.addEventListener("click", () => loadRetrievalManifestPreview());
  panel.querySelectorAll("[data-apply-retrieval-manifest-template]").forEach((button) => {
    button.addEventListener("click", () => applyRetrievalManifestTemplate(button.dataset.applyRetrievalManifestTemplate));
  });
  panel.querySelector("[data-retrieval-batch-form]")?.addEventListener("submit", submitRetrievalBatch);
  panel.querySelector("[data-draft-retrieval-batch-queries]")?.addEventListener("click", draftRetrievalBatchQueries);
  panel.querySelector("[data-retrieval-query-plan-ai]")?.addEventListener("change", (event) => {
    state.retrievalQueryPlanUseAi = Boolean(event.currentTarget.checked);
    state.retrievalQueryPlan = null;
    renderAddItemModal();
  });
  panel.querySelectorAll("[data-download-retrieval-query-plan]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalQueryPlanReport(button.dataset.reportFormat));
  });
  panel.querySelector("[data-refresh-retrieval-batches]")?.addEventListener("click", () => loadRetrievalBatchJobs());
  panel.querySelectorAll("[data-pause-retrieval-batch]").forEach((button) => button.addEventListener("click", () => pauseRetrievalBatch(button.dataset.pauseRetrievalBatch)));
  panel.querySelectorAll("[data-resume-retrieval-batch]").forEach((button) => button.addEventListener("click", () => resumeRetrievalBatch(button.dataset.resumeRetrievalBatch)));
  panel.querySelectorAll("[data-cancel-retrieval-batch]").forEach((button) => button.addEventListener("click", () => cancelRetrievalBatch(button.dataset.cancelRetrievalBatch)));
  panel.querySelectorAll("[data-retry-retrieval-batch]").forEach((button) => button.addEventListener("click", () => retryRetrievalBatchFailures(button.dataset.retryRetrievalBatch)));
  panel.querySelectorAll("[data-download-retrieval-batch-report]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalBatchReport(
      button.dataset.downloadRetrievalBatchReport,
      button.dataset.reportFormat,
      button.dataset.reportScope,
    ));
  });
  panel.querySelectorAll("[data-run-retrieval-remediation]").forEach((button) => {
    button.addEventListener("click", () => runRetrievalBatchRemediation(button.dataset.runRetrievalRemediation));
  });
  panel.querySelector("[data-import-retrieval-selected]")?.addEventListener("click", submitRetrievalImport);
  panel.querySelector("[data-refresh-retrieval-runs]")?.addEventListener("click", () => loadRetrievalRuns());
  panel.querySelector("[data-check-retrieval-sources]")?.addEventListener("click", () => loadRetrievalSources({ check: true }));
  panel.querySelector("[data-setup-retrieval-rehearsal]")?.addEventListener("click", setupRetrievalRehearsalKit);
  panel.querySelector("[data-validate-retrieval-rehearsal]")?.addEventListener("click", validateRetrievalRehearsalRun);
  panel.querySelector("[data-check-retrieval-readiness]")?.addEventListener("click", () => loadRetrievalReadiness());
  panel.querySelectorAll("[data-download-retrieval-report]").forEach((button) => button.addEventListener("click", () => downloadRetrievalReport(button.dataset.downloadRetrievalReport, button.dataset.reportFormat)));
  panel.querySelectorAll("[data-download-retrieval-summary]").forEach((button) => button.addEventListener("click", () => downloadRetrievalSummaryReport(button.dataset.reportFormat)));
  panel.querySelectorAll("[data-download-retrieval-source-setup]").forEach((button) => button.addEventListener("click", () => downloadRetrievalSourceSetupReport(button.dataset.reportFormat)));
  panel.querySelectorAll("[data-download-retrieval-readiness]").forEach((button) => button.addEventListener("click", () => downloadRetrievalReadinessReport(button.dataset.reportFormat)));
  panel.querySelectorAll("[data-download-retrieval-tuning]").forEach((button) => button.addEventListener("click", () => downloadRetrievalTuningReport(button.dataset.reportFormat)));
  panel.querySelector("[data-check-retrieval-onboarding]")?.addEventListener("click", () => loadRetrievalOnboarding());
  panel.querySelectorAll("[data-download-retrieval-onboarding]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalOnboardingReport(button.dataset.reportFormat));
  });
  panel.querySelector("[data-download-retrieval-onboarding-package]")?.addEventListener("click", downloadRetrievalOnboardingPackage);
  panel.querySelectorAll("[data-download-retrieval-gate-artifact]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalGateArtifact(button.dataset.downloadRetrievalGateArtifact));
  });
  panel.querySelectorAll("[data-download-retrieval-config-bundle]").forEach((button) => button.addEventListener("click", () => downloadRetrievalConfigBundle()));
  panel.querySelector("[data-retrieval-config-bundle-input]")?.addEventListener("input", (event) => {
    state.retrievalConfigBundleText = event.currentTarget.value;
    state.retrievalConfigBundleResult = null;
  });
  panel.querySelector("[data-dry-run-retrieval-config-bundle]")?.addEventListener("click", () => dryRunRetrievalConfigBundleImport());
  panel.querySelector("[data-import-retrieval-config-bundle]")?.addEventListener("click", () => importRetrievalConfigBundle());
  panel.querySelector("[data-clear-retrieval-config-bundle]")?.addEventListener("click", clearRetrievalConfigBundleDraft);
  panel.querySelector("[data-download-retrieval-config-bundle-result]")?.addEventListener("click", downloadRetrievalConfigBundleResultCsv);
  panel.querySelector("[data-retrieval-source-intake-input]")?.addEventListener("input", (event) => {
    state.retrievalSourceIntakeInput = event.currentTarget.value;
    state.retrievalSourceIntakeResult = null;
  });
  panel.querySelector("[data-retrieval-source-intake-sample-url]")?.addEventListener("change", (event) => {
    state.retrievalSourceIntakeSampleUrl = Boolean(event.currentTarget.checked);
    state.retrievalSourceIntakeResult = null;
    renderAddItemModal();
  });
  panel.querySelector("[data-analyze-retrieval-source-intake]")?.addEventListener("click", analyzeRetrievalSourceIntake);
  panel.querySelectorAll("[data-download-retrieval-source-intake]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalSourceIntakeReport(button.dataset.reportFormat));
  });
  panel.querySelector("[data-apply-retrieval-source-intake]")?.addEventListener("click", applyRetrievalSourceIntakeToFieldMapLab);
  panel.querySelector("[data-apply-retrieval-source-intake-config]")?.addEventListener("click", applyRetrievalSourceIntakeToConfig);
  panel.querySelector("[data-apply-retrieval-source-intake-queries]")?.addEventListener("click", applyRetrievalSourceIntakeQueriesToBatch);
  panel.querySelector("[data-clear-retrieval-source-intake]")?.addEventListener("click", clearRetrievalSourceIntake);
  panel.querySelector("[data-retrieval-field-map-lab-source]")?.addEventListener("change", (event) => {
    state.retrievalFieldMapLabSource = event.currentTarget.value;
    state.retrievalFieldMapLabResult = null;
    renderAddItemModal();
  });
  panel.querySelector("[data-retrieval-field-map-lab-mode]")?.addEventListener("change", (event) => {
    state.retrievalFieldMapLabMode = event.currentTarget.value;
    state.retrievalFieldMapLabResult = null;
    renderAddItemModal();
  });
  panel.querySelector("[data-retrieval-field-map-lab-ai]")?.addEventListener("change", (event) => {
    state.retrievalFieldMapLabUseAi = Boolean(event.currentTarget.checked);
    state.retrievalFieldMapLabResult = null;
    renderAddItemModal();
  });
  panel.querySelector("[data-check-retrieval-model-status]")?.addEventListener("click", () => loadRetrievalModelStatus({ check: true }));
  panel.querySelector("[data-retrieval-field-map-lab-input]")?.addEventListener("input", (event) => {
    state.retrievalFieldMapLabInput = event.currentTarget.value;
    state.retrievalFieldMapLabResult = null;
  });
  panel.querySelector("[data-retrieval-field-map-lab-config]")?.addEventListener("input", (event) => {
    state.retrievalFieldMapLabConfig = event.currentTarget.value;
    state.retrievalFieldMapLabResult = null;
  });
  panel.querySelector("[data-suggest-retrieval-field-map-lab]")?.addEventListener("click", () => suggestRetrievalFieldMapLab());
  panel.querySelectorAll("[data-download-retrieval-field-map-report]").forEach((button) => {
    button.addEventListener("click", () => downloadRetrievalFieldMapReport(button.dataset.reportFormat));
  });
  panel.querySelector("[data-apply-retrieval-field-map-lab]")?.addEventListener("click", applyRetrievalFieldMapLabDraft);
  panel.querySelector("[data-clear-retrieval-field-map-lab]")?.addEventListener("click", clearRetrievalFieldMapLab);
  panel.querySelectorAll("[data-retrieval-candidate-check]").forEach((input) => input.addEventListener("change", (event) => {
    const key = event.currentTarget.dataset.retrievalCandidateCheck;
    if (event.currentTarget.checked) state.retrievalSelectedKeys.add(key);
    else state.retrievalSelectedKeys.delete(key);
    renderAddItemModal();
  }));
  panel.querySelectorAll("[data-import-select-item]").forEach((button) => button.addEventListener("click", () => {
    const item = state.items.find((value) => value.key === button.dataset.importSelectItem);
    if (item) {
      state.selectedItem = item;
      renderTable();
      renderDetail();
    }
  }));
}

function renderRetrievalPage() {
  const host = document.querySelector("[data-retrieval-page-panel]");
  if (!host) return;
  host.innerHTML = `
    ${renderSimpleRetrievalMain()}
    ${state.addItemMessage ? `<p class="import-message" data-import-message>${escapeHtml(state.addItemMessage)}</p>` : ""}
    ${renderAddItemResults()}
    <details class="retrieval-advanced">
      <summary>
        <span>高级设置</span>
        <em>先看源配置说明，再按 Local、HTTP、SQLite 或 Manifest 填对应配置。</em>
      </summary>
      <div class="retrieval-advanced-body">
        ${renderRetrievalSourceConfigGuide()}
        <details class="retrieval-advanced-section" open>
          <summary>
            <span>1. 配置新数据源</span>
            <em>先用快速识别和字段映射辅助，再填写实际源配置。</em>
          </summary>
          <div class="retrieval-advanced-section-body">
            ${renderRetrievalSourceIntake()}
            ${renderRetrievalFieldMapLab()}
            ${renderRetrievalLocalConfigWithPreview()}
            ${renderRetrievalHttpJsonConfig()}
            ${renderRetrievalSqliteConfig()}
            ${renderRetrievalManifestConfig()}
          </div>
        </details>
        <details class="retrieval-advanced-section">
          <summary>
            <span>2. 验证和交接</span>
            <em>配置完成后跑 READY、Batch 和 ONB，确认源能稳定检索。</em>
          </summary>
          <div class="retrieval-advanced-section-body">
            ${renderRetrievalReadiness()}
            ${renderRetrievalOnboarding()}
            ${renderRetrievalBatchPanel()}
          </div>
        </details>
        <details class="retrieval-advanced-section">
          <summary>
            <span>3. 配置包和历史报告</span>
            <em>用于导入队友配置、下载阶段报告、查看最近检索记录。</em>
          </summary>
          <div class="retrieval-advanced-section-body">
            ${renderRetrievalConfigBundleImport()}
            ${renderRetrievalSummary()}
            ${renderRetrievalRuns()}
          </div>
        </details>
      </div>
    </details>
  `;
  bindRetrievalPageEvents(host);
}

function delegatedRetrievalSubmitEvent(event) {
  const form = event.target;
  return {
    currentTarget: form,
    target: form,
    submitter: event.submitter,
    preventDefault: () => event.preventDefault(),
    stopPropagation: () => event.stopPropagation(),
  };
}

function bindRetrievalPageEvents(host) {
  if (host.dataset.retrievalEventsBound) return;
  host.dataset.retrievalEventsBound = "1";
  host.addEventListener("submit", (event) => {
    if (!event.target.matches("form")) return;
    const delegatedEvent = delegatedRetrievalSubmitEvent(event);
    if (event.target.matches("[data-retrieval-search-form]")) submitRetrievalSearch(delegatedEvent);
    else if (event.target.matches("[data-retrieval-local-paths-form]")) saveRetrievalLocalPaths(delegatedEvent);
    else if (event.target.matches("[data-retrieval-http-json-form]")) saveRetrievalHttpJsonConfig(delegatedEvent);
    else if (event.target.matches("[data-retrieval-sqlite-form]")) saveRetrievalSqliteConfig(delegatedEvent);
    else if (event.target.matches("[data-retrieval-manifest-form]")) saveRetrievalManifestConfig(delegatedEvent);
    else if (event.target.matches("[data-retrieval-batch-form]")) submitRetrievalBatch(delegatedEvent);
  });
  host.addEventListener("input", (event) => {
    if (event.target.matches("[data-retrieval-query-input]")) {
      const nextQuery = String(event.target.value || "").trim();
      if (nextQuery !== state.retrievalQuery) {
        state.retrievalQuery = nextQuery;
        state.retrievalQueryPlan = null;
        state.retrievalBatchQueries = "";
        state.simplePlanBatchJobId = "";
        state.simplePlanBatchLoadedJobId = "";
      }
    } else if (event.target.matches("[data-simple-batch-limit]")) {
      state.retrievalSimpleBatchLimit = currentSimpleBatchLimitFromInput(event.target.value);
    } else if (event.target.matches("[data-simple-source-limit]")) {
      const source = String(event.target.dataset.simpleSourceLimit || "").trim().toLowerCase();
      if (source) {
        state.retrievalSimpleSourceLimits = {
          ...(state.retrievalSimpleSourceLimits || {}),
          [source]: currentSimpleBatchLimitFromInput(event.target.value),
        };
      }
    } else if (event.target.matches("[data-retrieval-config-bundle-input]")) {
      state.retrievalConfigBundleText = event.target.value;
      state.retrievalConfigBundleResult = null;
    } else if (event.target.matches("[data-retrieval-source-intake-input]")) {
      state.retrievalSourceIntakeInput = event.target.value;
      state.retrievalSourceIntakeResult = null;
    } else if (event.target.matches("[data-retrieval-field-map-lab-input]")) {
      state.retrievalFieldMapLabInput = event.target.value;
      state.retrievalFieldMapLabResult = null;
    } else if (event.target.matches("[data-retrieval-field-map-lab-config]")) {
      state.retrievalFieldMapLabConfig = event.target.value;
      state.retrievalFieldMapLabResult = null;
    }
  });
  host.addEventListener("change", (event) => {
    if (event.target.matches("[data-retrieval-query-plan-ai]")) {
      state.retrievalQueryPlanUseAi = Boolean(event.target.checked);
      state.retrievalQueryPlan = null;
      renderRetrievalPage();
    } else if (event.target.matches("[data-retrieval-source-intake-sample-url]")) {
      state.retrievalSourceIntakeSampleUrl = Boolean(event.target.checked);
      state.retrievalSourceIntakeResult = null;
      renderRetrievalPage();
    } else if (event.target.matches("[data-retrieval-field-map-lab-source]")) {
      state.retrievalFieldMapLabSource = event.target.value;
      state.retrievalFieldMapLabResult = null;
      renderRetrievalPage();
    } else if (event.target.matches("[data-retrieval-field-map-lab-mode]")) {
      state.retrievalFieldMapLabMode = event.target.value;
      state.retrievalFieldMapLabResult = null;
      renderRetrievalPage();
    } else if (event.target.matches("[data-retrieval-field-map-lab-ai]")) {
      state.retrievalFieldMapLabUseAi = Boolean(event.target.checked);
      state.retrievalFieldMapLabResult = null;
      renderRetrievalPage();
    } else if (event.target.matches("[data-retrieval-candidate-check]")) {
      const key = event.target.dataset.retrievalCandidateCheck;
      if (event.target.checked) state.retrievalSelectedKeys.add(key);
      else state.retrievalSelectedKeys.delete(key);
      renderRetrievalPage();
    }
  });
  host.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || !host.contains(button)) return;
    if (button.matches("[data-clear-retrieval-local-paths]")) clearRetrievalLocalPaths();
    else if (button.matches("[data-suggest-retrieval-local-field-map]")) suggestRetrievalLocalFieldMap();
    else if (button.matches("[data-refresh-retrieval-local-preview]")) loadRetrievalLocalPreview();
    else if (button.matches("[data-retrieval-config-bundle-input]")) return;
    else if (button.matches("[data-clear-retrieval-http-json]")) clearRetrievalHttpJsonConfig();
    else if (button.matches("[data-suggest-retrieval-http-json-field-map]")) suggestRetrievalHttpJsonFieldMap();
    else if (button.matches("[data-refresh-retrieval-http-json-preview]")) loadRetrievalHttpJsonPreview();
    else if (button.matches("[data-clear-retrieval-sqlite]")) clearRetrievalSqliteConfig();
    else if (button.matches("[data-suggest-retrieval-sqlite-field-map]")) suggestRetrievalSqliteFieldMap();
    else if (button.matches("[data-refresh-retrieval-sqlite-preview]")) loadRetrievalSqlitePreview();
    else if (button.matches("[data-clear-retrieval-manifest]")) clearRetrievalManifestConfig();
    else if (button.matches("[data-suggest-retrieval-manifest-field-map]")) suggestRetrievalManifestFieldMap();
    else if (button.matches("[data-refresh-retrieval-manifest-preview]")) loadRetrievalManifestPreview();
    else if (button.matches("[data-simple-ai-query-plan]")) {
      const queryInput = document.querySelector("[data-retrieval-query-input]");
      state.retrievalQuery = String(queryInput?.value || state.retrievalQuery || "").trim();
      state.retrievalQueryPlanUseAi = true;
      draftRetrievalBatchQueries({ limit: 5 });
    }
    else if (button.matches("[data-simple-plan-batch]")) submitSimpleRetrievalPlanBatch();
    else if (button.matches("[data-score-retrieval-candidates-ai]")) scoreRetrievalCandidatesWithAi();
    else if (button.matches("[data-stop-retrieval-ai-scoring]")) stopRetrievalAiScoring();
    else if (button.matches("[data-simple-batch-mode]")) {
      state.retrievalBatchMode = button.dataset.simpleBatchMode === "full" ? "full" : "quick";
      state.retrievalSimpleSourceLimits = {};
      state.retrievalBatchMessage = state.retrievalBatchMode === "full"
        ? "已切换到全量模式：每源候选更多，检索会更慢。"
        : "已切换到快速模式：代码/模型/数据源默认取更少候选。";
      renderRetrievalPage();
    }
    else if (button.matches("[data-load-simple-batch-candidates]")) loadSimplePlanBatchCandidates(button.dataset.loadSimpleBatchCandidates);
    else if (button.matches("[data-draft-retrieval-batch-queries]")) draftRetrievalBatchQueries();
    else if (button.matches("[data-refresh-retrieval-batches]")) loadRetrievalBatchJobs();
    else if (button.matches("[data-select-retrieval-candidates]")) setRetrievalCandidateSelection(button.dataset.selectRetrievalCandidates);
    else if (button.matches("[data-import-retrieval-selected]")) submitRetrievalImport();
    else if (button.matches("[data-refresh-retrieval-runs]")) loadRetrievalRuns();
    else if (button.matches("[data-load-retrieval-run-candidates]")) loadRetrievalRunCandidates(button.dataset.loadRetrievalRunCandidates);
    else if (button.matches("[data-check-retrieval-sources]")) loadRetrievalSources({ check: true });
    else if (button.matches("[data-setup-retrieval-rehearsal]")) setupRetrievalRehearsalKit();
    else if (button.matches("[data-validate-retrieval-rehearsal]")) validateRetrievalRehearsalRun();
    else if (button.matches("[data-check-retrieval-readiness]")) loadRetrievalReadiness();
    else if (button.matches("[data-check-retrieval-onboarding]")) loadRetrievalOnboarding();
    else if (button.matches("[data-download-retrieval-onboarding-package]")) downloadRetrievalOnboardingPackage();
    else if (button.matches("[data-dry-run-retrieval-config-bundle]")) dryRunRetrievalConfigBundleImport();
    else if (button.matches("[data-import-retrieval-config-bundle]")) importRetrievalConfigBundle();
    else if (button.matches("[data-clear-retrieval-config-bundle]")) clearRetrievalConfigBundleDraft();
    else if (button.matches("[data-download-retrieval-config-bundle-result]")) downloadRetrievalConfigBundleResultCsv();
    else if (button.matches("[data-analyze-retrieval-source-intake]")) analyzeRetrievalSourceIntake();
    else if (button.matches("[data-apply-retrieval-source-intake]")) applyRetrievalSourceIntakeToFieldMapLab();
    else if (button.matches("[data-apply-retrieval-source-intake-config]")) applyRetrievalSourceIntakeToConfig();
    else if (button.matches("[data-apply-retrieval-source-intake-queries]")) applyRetrievalSourceIntakeQueriesToBatch();
    else if (button.matches("[data-clear-retrieval-source-intake]")) clearRetrievalSourceIntake();
    else if (button.matches("[data-check-retrieval-model-status]")) loadRetrievalModelStatus({ check: true });
    else if (button.matches("[data-suggest-retrieval-field-map-lab]")) suggestRetrievalFieldMapLab();
    else if (button.matches("[data-apply-retrieval-field-map-lab]")) applyRetrievalFieldMapLabDraft();
    else if (button.matches("[data-clear-retrieval-field-map-lab]")) clearRetrievalFieldMapLab();
    else if (button.matches("[data-download-retrieval-configured-field-map]")) downloadRetrievalConfiguredFieldMapReport(button.dataset.downloadRetrievalConfiguredFieldMap, button.dataset.reportFormat);
    else if (button.matches("[data-apply-retrieval-readiness-field-map]")) applyRetrievalReadinessFieldMapSuggestionToConfig(button.dataset.applyRetrievalReadinessFieldMap);
    else if (button.matches("[data-apply-retrieval-http-json-template]")) applyRetrievalHttpJsonTemplate(button.dataset.applyRetrievalHttpJsonTemplate);
    else if (button.matches("[data-apply-retrieval-sqlite-template]")) applyRetrievalSqliteTemplate(button.dataset.applyRetrievalSqliteTemplate);
    else if (button.matches("[data-apply-retrieval-manifest-template]")) applyRetrievalManifestTemplate(button.dataset.applyRetrievalManifestTemplate);
    else if (button.matches("[data-download-retrieval-query-plan]")) downloadRetrievalQueryPlanReport(button.dataset.reportFormat);
    else if (button.matches("[data-pause-retrieval-batch]")) pauseRetrievalBatch(button.dataset.pauseRetrievalBatch);
    else if (button.matches("[data-resume-retrieval-batch]")) resumeRetrievalBatch(button.dataset.resumeRetrievalBatch);
    else if (button.matches("[data-cancel-retrieval-batch]")) cancelRetrievalBatch(button.dataset.cancelRetrievalBatch);
    else if (button.matches("[data-retry-retrieval-batch]")) retryRetrievalBatchFailures(button.dataset.retryRetrievalBatch);
    else if (button.matches("[data-download-retrieval-batch-report]")) downloadRetrievalBatchReport(button.dataset.downloadRetrievalBatchReport, button.dataset.reportFormat, button.dataset.reportScope);
    else if (button.matches("[data-run-retrieval-remediation]")) runRetrievalBatchRemediation(button.dataset.runRetrievalRemediation);
    else if (button.matches("[data-download-retrieval-report]")) downloadRetrievalReport(button.dataset.downloadRetrievalReport, button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-summary]")) downloadRetrievalSummaryReport(button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-source-setup]")) downloadRetrievalSourceSetupReport(button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-readiness]")) downloadRetrievalReadinessReport(button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-tuning]")) downloadRetrievalTuningReport(button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-onboarding]")) downloadRetrievalOnboardingReport(button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-gate-artifact]")) downloadRetrievalGateArtifact(button.dataset.downloadRetrievalGateArtifact);
    else if (button.matches("[data-download-retrieval-config-bundle]")) downloadRetrievalConfigBundle();
    else if (button.matches("[data-download-retrieval-source-intake]")) downloadRetrievalSourceIntakeReport(button.dataset.reportFormat);
    else if (button.matches("[data-download-retrieval-field-map-report]")) downloadRetrievalFieldMapReport(button.dataset.reportFormat);
    else if (button.matches("[data-import-select-item]")) {
      const item = state.items.find((value) => value.key === button.dataset.importSelectItem);
      if (item) state.selectedItem = item;
    }
  });
}

function openAddItemModal() {
  if (!state.library?.editable) {
    window.alert("只读源库不能添加条目。请先创建本地副本。");
    return;
  }
  state.addItemMessage = "";
  state.addItemResults = [];
  if (!["identifier", "text"].includes(state.addItemMode)) state.addItemMode = "identifier";
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

async function submitRetrievalSearch(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const query = String(formData.get("query") || "").trim();
  const selectedSources = uniqueRetrievalSources(formData.getAll("sources").map((value) => String(value)));
  const unavailableSources = unavailableRetrievalSources(selectedSources);
  const focusedUnavailableSources = unavailableRetrievalSources([...state.retrievalSources]);
  const sources = availableRetrievalSources(selectedSources);
  state.retrievalQuery = query;
  if (!query) {
    state.addItemMessage = "检索词不能为空。";
    renderAddItemModal();
    return;
  }
  if (!selectedSources.length) {
    state.addItemMessage = focusedUnavailableSources.length
      ? unavailableRetrievalSourceMessage(focusedUnavailableSources)
      : "请至少选择一个数据源。";
    renderAddItemModal();
    return;
  }
  state.retrievalSources = new Set(selectedSources);
  if (unavailableSources.length) {
    state.addItemMessage = unavailableRetrievalSourceMessage(unavailableSources);
    renderAddItemModal();
    return;
  }
  if (!sources.length) {
    state.addItemMessage = "请至少选择一个可用数据源。";
    renderAddItemModal();
    return;
  }
  try {
    state.addItemBusy = true;
    state.addItemMessage = "快速检索已提交后台，切换页面也会继续运行。";
    state.addItemResults = [];
    state.retrievalSearchJobId = "";
    state.retrievalAiScoringJobId = "";
    state.retrievalAiEvaluationBusy = false;
    state.retrievalAiEvaluationStopRequested = false;
    state.retrievalQueryPlanJobId = "";
    state.retrievalQueryPlanBusy = false;
    state.retrievalQueryPlan = null;
    state.retrievalBatchQueries = "";
    if (retrievalAiScoringPollTimer) {
      clearTimeout(retrievalAiScoringPollTimer);
      retrievalAiScoringPollTimer = null;
    }
    if (retrievalQueryPlanPollTimer) {
      clearTimeout(retrievalQueryPlanPollTimer);
      retrievalQueryPlanPollTimer = null;
    }
    if (retrievalSearchPollTimer) {
      clearTimeout(retrievalSearchPollTimer);
      retrievalSearchPollTimer = null;
    }
    renderAddItemModal();
    const result = await postJSON(`/api/library/${state.libraryId}/retrieval/search/jobs`, { query, sources, limit: 10, use_ai_evaluation: false });
    applyRetrievalSearchJob(result.job || null);
    scheduleRetrievalSearchPoll(state.retrievalSearchJobId);
    renderAddItemModal();
  } catch (error) {
    state.addItemMessage = error.message;
    state.retrievalCandidates = [];
    state.retrievalSelectedKeys = new Set();
    state.retrievalStats = null;
    state.retrievalAiEvaluationSummary = null;
    state.retrievalRunId = "";
  } finally {
    if (!state.retrievalSearchJobId) state.addItemBusy = false;
    renderAddItemModal();
  }
}

function applyRetrievalSearchJob(job) {
  if (!job) return false;
  const jobQuery = String(job.query || "");
  if (jobQuery && state.retrievalQuery && jobQuery !== state.retrievalQuery && state.retrievalCandidates.length) return false;
  state.retrievalSearchJobId = String(job.job_id || state.retrievalSearchJobId || "");
  state.addItemBusy = retrievalBackgroundJobIsActive(job);
  const result = job.result && typeof job.result === "object" ? job.result : null;
  if (result) {
    state.retrievalCandidates = normalizeRetrievalCandidates(result.candidates || []);
    state.retrievalSelectedKeys = new Set(
      state.retrievalCandidates
        .filter((candidate) => candidate.ai_evaluation?.auto_select === true)
        .map((candidate) => candidate.client_key)
        .filter(Boolean)
    );
    state.retrievalStats = result.source_stats || {};
    state.retrievalAiEvaluationSummary = result.ai_evaluation_summary || null;
    state.retrievalRunId = result.run_id || "";
  }
  const status = String(job.status || "");
  const candidateCount = Number(job.candidate_count || state.retrievalCandidates.length || 0);
  if (status === "queued") {
    state.addItemMessage = "快速检索已进入后台队列。";
  } else if (status === "running") {
    state.addItemMessage = "后台快速检索中，切换页面也会继续运行。";
  } else if (status === "failed") {
    state.addItemBusy = false;
    state.addItemMessage = `快速检索失败：${job.error || "后台任务异常"}`;
  } else if (status === "canceled") {
    state.addItemBusy = false;
    state.addItemMessage = "快速检索已取消。";
  } else if (status === "completed") {
    state.addItemBusy = false;
    state.addItemMessage = `检索到 ${candidateCount} 条候选。需要更省事的排序时，可点击“AI 推荐排序”。`;
    loadRetrievalRuns({ silent: true });
    loadRetrievalSummary({ silent: true });
  }
  return true;
}

async function loadRetrievalSearchJob(jobId, options = {}) {
  const cleanJobId = String(jobId || "").trim();
  if (!state.libraryId || !cleanJobId) return;
  if (!state.retrievalSearchJobId || cleanJobId !== state.retrievalSearchJobId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/search/jobs/${encodeURIComponent(cleanJobId)}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载快速检索任务失败。");
    const applied = applyRetrievalSearchJob(data.job || null);
    if (!applied) {
      if (retrievalSearchPollTimer) clearTimeout(retrievalSearchPollTimer);
      retrievalSearchPollTimer = null;
      return;
    }
    if (retrievalBackgroundJobIsActive(data.job)) {
      scheduleRetrievalSearchPoll(cleanJobId);
    } else if (retrievalSearchPollTimer) {
      clearTimeout(retrievalSearchPollTimer);
      retrievalSearchPollTimer = null;
    }
  } catch (error) {
    if (!options.silent) state.addItemMessage = error.message;
    state.addItemBusy = false;
  } finally {
    renderAddItemModal();
  }
}

function scheduleRetrievalSearchPoll(jobId) {
  const cleanJobId = String(jobId || "").trim();
  if (retrievalSearchPollTimer) clearTimeout(retrievalSearchPollTimer);
  retrievalSearchPollTimer = null;
  if (!cleanJobId) return;
  retrievalSearchPollTimer = setTimeout(() => {
    loadRetrievalSearchJob(cleanJobId, { silent: true });
  }, 1200);
}

async function loadLatestRetrievalSearchJob(options = {}) {
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/search/jobs/latest`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载最近快速检索任务失败。");
    const job = data.job || null;
    if (!job) return;
    const shouldRestore = retrievalBackgroundJobIsActive(job) || !state.retrievalCandidates.length || String(job.query || "") === String(state.retrievalQuery || "");
    const applied = shouldRestore ? applyRetrievalSearchJob(job) : false;
    if (applied && retrievalBackgroundJobIsActive(job)) scheduleRetrievalSearchPoll(job.job_id);
  } catch (error) {
    if (!options.silent) state.addItemMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

async function scoreRetrievalCandidatesWithAi() {
  const query = String(document.querySelector("[data-retrieval-query-input]")?.value || state.retrievalQuery || "").trim();
  state.retrievalQuery = query;
  if (!query) {
    state.addItemMessage = "请输入检索词后再进行 AI 推荐排序。";
    renderAddItemModal();
    return;
  }
  if (!state.retrievalCandidates.length) {
    state.addItemMessage = "没有可评分的候选。请先检索。";
    renderAddItemModal();
    return;
  }
  if (state.retrievalModelStatus?.configured !== true) {
    state.addItemMessage = "模型未配置，无法进行 AI 推荐排序。";
    renderAddItemModal();
    return;
  }
  try {
    state.retrievalAiEvaluationBusy = true;
    state.retrievalAiEvaluationStopRequested = false;
    state.addItemMessage = `AI 推荐排序已提交后台：按规则置信度从高到低逐条评分，共 ${state.retrievalCandidates.length} 条。`;
    state.retrievalAiEvaluationSummary = buildRetrievalAiProgressSummary("evaluating");
    sortRetrievalCandidatesForAiProgress();
    renderAddItemModal();
    const result = await postJSON(`/api/library/${state.libraryId}/retrieval/ai-scoring-jobs`, {
      query,
      candidates: state.retrievalCandidates,
    });
    applyRetrievalAiScoringJob(result.job || null);
    scheduleRetrievalAiScoringPoll(state.retrievalAiScoringJobId);
    renderAddItemModal();
  } catch (error) {
    state.addItemMessage = `AI 推荐排序失败：${error.message}`;
    state.retrievalAiEvaluationBusy = false;
    state.retrievalAiEvaluationStopRequested = false;
    renderAddItemModal();
  }
}

function applyRetrievalAiScoringJob(job) {
  if (!job) return false;
  const jobQuery = String(job.query || "");
  if (jobQuery && state.retrievalQuery && jobQuery !== state.retrievalQuery && state.retrievalCandidates.length) return false;
  state.retrievalAiScoringJobId = String(job.job_id || state.retrievalAiScoringJobId || "");
  const candidates = Array.isArray(job.candidates) ? normalizeRetrievalCandidates(job.candidates) : [];
  if (candidates.length) {
    state.retrievalCandidates = candidates;
    const candidateKeys = new Set(candidates.map((candidate) => candidate.client_key).filter(Boolean));
    const selectedKeys = new Set([...state.retrievalSelectedKeys].filter((key) => candidateKeys.has(key)));
    candidates
      .filter((candidate) => candidate.ai_evaluation?.auto_select === true && retrievalCandidateHasAiModelEvaluation(candidate))
      .map((candidate) => candidate.client_key)
      .filter(Boolean)
      .forEach((key) => selectedKeys.add(key));
    state.retrievalSelectedKeys = selectedKeys;
  }
  state.retrievalAiEvaluationSummary = job.summary || buildRetrievalAiProgressSummary(retrievalBackgroundJobIsTerminal(job) ? "partial" : "evaluating", job.error || "");
  state.retrievalAiEvaluationBusy = retrievalBackgroundJobIsActive(job);
  state.retrievalAiEvaluationStopRequested = String(job.status || "") === "canceling";
  const total = Number(job.total_count || candidates.length || 0);
  const completed = Number(job.completed_count || state.retrievalAiEvaluationSummary?.processed_candidate_count || 0);
  const aiCompleted = Number(job.ai_completed_count || state.retrievalAiEvaluationSummary?.ai_evaluated_candidate_count || 0);
  const failed = Number(job.failed_count || state.retrievalAiEvaluationSummary?.failed_batch_count || 0);
  const autoSelected = Number(state.retrievalAiEvaluationSummary?.auto_selected_count || 0);
  const status = String(job.status || "");
  if (status === "queued") {
    state.addItemMessage = `AI 推荐排序已进入后台队列，共 ${total} 条。`;
  } else if (status === "running") {
    state.addItemMessage = `后台 AI 推荐排序中：已处理 ${completed}/${total} 条，AI 已评分 ${aiCompleted} 条${failed ? `，失败 ${failed} 条` : ""}。`;
  } else if (status === "canceling") {
    state.addItemMessage = `正在停止 AI 推荐排序：已处理 ${completed}/${total} 条。`;
  } else if (status === "canceled") {
    state.addItemMessage = `AI 推荐排序已停止：已处理 ${completed}/${total} 条，默认勾选 ${autoSelected} 条真实 AI 推荐。`;
  } else if (status === "failed") {
    state.addItemMessage = `AI 推荐排序失败：${job.error || "后台任务异常"}`;
  } else if (status === "partial") {
    state.addItemMessage = `AI 推荐排序部分完成：已处理 ${completed}/${total} 条，AI 已评分 ${aiCompleted} 条，默认勾选 ${autoSelected} 条真实 AI 推荐。`;
  } else if (status === "completed") {
    state.addItemMessage = `AI 推荐排序完成：已逐条评分 ${aiCompleted} 条，默认勾选 ${autoSelected} 条真实 AI 推荐。`;
  }
  sortRetrievalCandidatesForAiProgress();
  return true;
}

async function loadRetrievalAiScoringJob(jobId, options = {}) {
  const cleanJobId = String(jobId || "").trim();
  if (!state.libraryId || !cleanJobId) return;
  if (!state.retrievalAiScoringJobId || cleanJobId !== state.retrievalAiScoringJobId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/ai-scoring-jobs/${encodeURIComponent(cleanJobId)}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 AI 推荐排序任务失败。");
    const applied = applyRetrievalAiScoringJob(data.job || null);
    if (!applied) {
      if (retrievalAiScoringPollTimer) clearTimeout(retrievalAiScoringPollTimer);
      retrievalAiScoringPollTimer = null;
      return;
    }
    if (retrievalBackgroundJobIsActive(data.job)) {
      scheduleRetrievalAiScoringPoll(cleanJobId);
    } else if (retrievalAiScoringPollTimer) {
      clearTimeout(retrievalAiScoringPollTimer);
      retrievalAiScoringPollTimer = null;
    }
  } catch (error) {
    if (!options.silent) state.addItemMessage = error.message;
    state.retrievalAiEvaluationBusy = false;
  } finally {
    renderAddItemModal();
  }
}

function scheduleRetrievalAiScoringPoll(jobId) {
  const cleanJobId = String(jobId || "").trim();
  if (retrievalAiScoringPollTimer) clearTimeout(retrievalAiScoringPollTimer);
  retrievalAiScoringPollTimer = null;
  if (!cleanJobId) return;
  retrievalAiScoringPollTimer = setTimeout(() => {
    loadRetrievalAiScoringJob(cleanJobId, { silent: true });
  }, 1500);
}

async function loadLatestRetrievalAiScoringJob(options = {}) {
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/ai-scoring-jobs/latest`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载最近 AI 推荐排序任务失败。");
    const job = data.job || null;
    if (!job) return;
    const shouldRestore = retrievalBackgroundJobIsActive(job) || !state.retrievalCandidates.length || String(job.query || "") === String(state.retrievalQuery || "");
    const applied = shouldRestore ? applyRetrievalAiScoringJob(job) : false;
    if (applied && retrievalBackgroundJobIsActive(job)) scheduleRetrievalAiScoringPoll(job.job_id);
  } catch (error) {
    if (!options.silent) state.addItemMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

async function stopRetrievalAiScoring() {
  if (!state.retrievalAiEvaluationBusy || !state.retrievalAiScoringJobId) return;
  state.retrievalAiEvaluationStopRequested = true;
  state.addItemMessage = "正在停止 AI 推荐排序...";
  renderAddItemModal();
  try {
    const result = await postJSON(`/api/library/${state.libraryId}/retrieval/ai-scoring-jobs/${encodeURIComponent(state.retrievalAiScoringJobId)}/cancel`, {});
    applyRetrievalAiScoringJob(result.job || null);
    scheduleRetrievalAiScoringPoll(state.retrievalAiScoringJobId);
  } catch (error) {
    state.addItemMessage = `停止 AI 推荐排序失败：${error.message}`;
    renderAddItemModal();
  }
}

async function submitRetrievalImport() {
  const candidates = selectedRetrievalCandidates();
  if (!candidates.length) {
    state.addItemMessage = "请先勾选候选条目。";
    renderAddItemModal();
    return;
  }
  try {
    state.addItemBusy = true;
    state.addItemMessage = "";
    renderAddItemModal();
    const candidateIds = candidates.map((candidate) => candidate.candidate_id).filter(Boolean);
    const payload = {
      collection_key: currentRealCollectionKey(),
      run_id: state.retrievalRunId,
      ...(candidateIds.length === candidates.length ? { candidate_ids: candidateIds } : { candidates }),
    };
    const summary = await postJSON(`/api/library/${state.libraryId}/retrieval/import`, payload);
    state.retrievalSelectedKeys = new Set();
    await finishImport(summary);
    await loadRetrievalRuns({ silent: true });
    await loadRetrievalSummary({ silent: true });
  } catch (error) {
    state.addItemMessage = error.message;
    state.addItemResults = [];
    renderAddItemModal();
  } finally {
    state.addItemBusy = false;
    renderAddItemModal();
  }
}

function uniqueRetrievalSources(sources) {
  return [...new Set((sources || []).map((source) => String(source || "").trim()).filter(Boolean))];
}

function unavailableRetrievalSources(sources) {
  return uniqueRetrievalSources(sources).filter((source) => state.retrievalSourceInfo[source]?.available === false);
}

function availableRetrievalSources(sources) {
  return uniqueRetrievalSources(sources).filter((source) => !unavailableRetrievalSources([source]).length);
}

function retrievalSourceLabel(name) {
  return state.retrievalSourceInfo[name]?.label || name;
}

function unavailableRetrievalSourceMessage(sources) {
  const labels = unavailableRetrievalSources(sources).map(retrievalSourceLabel).join(", ");
  return `所选数据源暂不可用：${labels}。请先保存配置或刷新数据源状态后再开始检索。`;
}

function currentRetrievalSourceSelection() {
  const checked = [...document.querySelectorAll("[data-retrieval-search-form] input[name='sources']:checked")]
    .map((input) => String(input.value || "").trim())
    .filter(Boolean);
  return uniqueRetrievalSources(checked.length ? checked : [...state.retrievalSources]);
}

function currentRetrievalBatchQueriesText() {
  const input = document.querySelector("[data-retrieval-batch-queries]");
  const text = String(input?.value || state.retrievalBatchQueries || "").trim();
  if (input) state.retrievalBatchQueries = String(input.value || "");
  return text;
}

function applyRetrievalOnboardingQueryParams(params) {
  const requiredQueries = currentRetrievalBatchQueriesText();
  if (requiredQueries) params.set("required_queries", requiredQueries);
  if (state.retrievalQueryPlanUseAi && state.retrievalModelStatus?.configured === true) params.set("use_ai", "1");
}

async function draftRetrievalBatchQueries(options = {}) {
  if (!state.libraryId) return;
  const seedQuery = String(document.querySelector("[data-retrieval-query-input]")?.value || state.retrievalQuery || "").trim();
  state.retrievalQuery = seedQuery;
  if (!seedQuery) {
    state.retrievalBatchMessage = "请输入检索词后再生成计划。";
    state.retrievalQueryPlan = null;
    state.retrievalBatchQueries = "";
    renderAddItemModal();
    return;
  }
  const queryLimit = Math.max(1, Math.min(Number(options.limit || 5), 10));
  const sampleSize = Math.max(1, Math.min(Number(options.sampleSize || 5), 5));
  try {
    state.retrievalQueryPlanBusy = true;
    state.retrievalBatchMessage = "";
    state.simplePlanBatchJobId = "";
    renderAddItemModal();
    const result = await postJSON(`/api/library/${state.libraryId}/retrieval/query-plan/jobs`, {
      seed_query: seedQuery,
      sample_size: sampleSize,
      limit: queryLimit,
      sources: currentRetrievalSourceSelection(),
      use_ai: state.retrievalQueryPlanUseAi && state.retrievalModelStatus?.configured === true,
    });
    applyRetrievalQueryPlanJob(result.job || null);
    scheduleRetrievalQueryPlanPoll(state.retrievalQueryPlanJobId);
    renderAddItemModal();
  } catch (error) {
    state.retrievalBatchMessage = error.message;
    state.retrievalQueryPlanBusy = false;
    renderAddItemModal();
  }
}

function applyRetrievalQueryPlanJob(job) {
  if (!job) return;
  state.retrievalQueryPlanJobId = String(job.job_id || state.retrievalQueryPlanJobId || "");
  state.retrievalQueryPlanBusy = retrievalBackgroundJobIsActive(job);
  const status = String(job.status || "");
  if (job.plan && typeof job.plan === "object") {
    const plan = job.plan || {};
    state.retrievalQueryPlan = plan;
    state.retrievalBatchQueries = String(plan.query_text || "").trim();
  }
  const queryCount = Number(job.query_count || state.retrievalQueryPlan?.query_count || 0);
  if (status === "queued") {
    state.retrievalBatchMessage = "AI 检索计划已进入后台队列。";
  } else if (status === "running") {
    state.retrievalBatchMessage = "AI 正在后台拆解检索词，切换页面也会继续运行。";
  } else if (status === "failed") {
    state.retrievalBatchMessage = `AI 检索计划生成失败：${job.error || "后台任务异常"}`;
  } else if (status === "completed") {
    state.retrievalBatchMessage = `${job.message || state.retrievalQueryPlan?.message || "AI 检索计划已生成。"} ${queryCount} 条检索词可确认。`;
  } else if (status === "canceled") {
    state.retrievalBatchMessage = "AI 检索计划已取消。";
  }
}

async function loadRetrievalQueryPlanJob(jobId, options = {}) {
  const cleanJobId = String(jobId || "").trim();
  if (!state.libraryId || !cleanJobId) return;
  if (!state.retrievalQueryPlanJobId || cleanJobId !== state.retrievalQueryPlanJobId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/query-plan/jobs/${encodeURIComponent(cleanJobId)}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 AI 检索计划任务失败。");
    applyRetrievalQueryPlanJob(data.job || null);
    if (retrievalBackgroundJobIsActive(data.job)) {
      scheduleRetrievalQueryPlanPoll(cleanJobId);
    } else if (retrievalQueryPlanPollTimer) {
      clearTimeout(retrievalQueryPlanPollTimer);
      retrievalQueryPlanPollTimer = null;
    }
  } catch (error) {
    if (!options.silent) state.retrievalBatchMessage = error.message;
    state.retrievalQueryPlanBusy = false;
  } finally {
    renderAddItemModal();
  }
}

function scheduleRetrievalQueryPlanPoll(jobId) {
  const cleanJobId = String(jobId || "").trim();
  if (retrievalQueryPlanPollTimer) clearTimeout(retrievalQueryPlanPollTimer);
  retrievalQueryPlanPollTimer = null;
  if (!cleanJobId) return;
  retrievalQueryPlanPollTimer = setTimeout(() => {
    loadRetrievalQueryPlanJob(cleanJobId, { silent: true });
  }, 1200);
}

async function loadLatestRetrievalQueryPlanJob(options = {}) {
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/query-plan/jobs/latest`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载最近 AI 检索计划任务失败。");
    const job = data.job || null;
    if (!job) return;
    const sameQuery = String(job.seed_query || "") === String(state.retrievalQuery || "");
    if (retrievalBackgroundJobIsActive(job) || sameQuery || !state.retrievalQueryPlan) applyRetrievalQueryPlanJob(job);
    if (retrievalBackgroundJobIsActive(job)) scheduleRetrievalQueryPlanPoll(job.job_id);
  } catch (error) {
    if (!options.silent) state.retrievalBatchMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

async function submitSimpleRetrievalPlanBatch() {
  const queries = String(state.retrievalBatchQueries || state.retrievalQueryPlan?.query_text || "").trim();
  const sourceSelection = simplePlanBatchSourceSelection();
  const unavailableSources = sourceSelection.unavailable;
  const sources = sourceSelection.available;
  const sourceLimits = simplePlanBatchSourceLimits(sources);
  if (!queries) {
    state.retrievalBatchMessage = "请先生成检索计划。";
    renderAddItemModal();
    return;
  }
  if (unavailableSources.length) {
    state.retrievalBatchMessage = unavailableRetrievalSourceMessage(unavailableSources);
    renderAddItemModal();
    return;
  }
  if (!sources.length) {
    state.retrievalBatchMessage = "没有可用数据源，请先勾选或配置至少一个数据源。";
    renderAddItemModal();
    return;
  }
  const activeJob = currentSimplePlanBatchJob();
  if (retrievalBatchIsActive(activeJob)) {
    state.retrievalBatchMessage = `批量检索正在运行：${activeJob.completed_queries || 0}/${activeJob.total_queries || 0}`;
    await loadRetrievalBatchJobs({ silent: true });
    return;
  }
  try {
    state.retrievalBatchBusy = true;
    state.retrievalBatchMessage = `正在创建计划检索任务（${currentSimpleBatchMode() === "full" ? "全量模式" : "快速模式"}）...`;
    state.simplePlanBatchLoadedJobId = "";
    state.retrievalCandidates = [];
    state.retrievalSelectedKeys = new Set();
    state.retrievalRunId = "";
    renderAddItemModal();
    const batchLimit = Math.max(currentSimpleBatchLimit(), ...Object.values(sourceLimits));
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/batches`, {
      queries,
      sources,
      limit: batchLimit,
      source_limits: sourceLimits,
    });
    state.simplePlanBatchJobId = data.job.job_id || "";
    state.retrievalBatchJobs = [data.job, ...state.retrievalBatchJobs.filter((job) => job.job_id !== data.job.job_id)];
    const sourceNote = sourceSelection.recommended ? `使用计划推荐源：${sources.join(" / ")}` : `使用已勾选源：${sources.join(" / ")}`;
    const limitNote = Object.entries(sourceLimits).map(([source, limit]) => `${retrievalSourceLabel(source)} ${limit}`).join(" / ");
    state.retrievalBatchMessage = `已按计划创建批量检索（${currentSimpleBatchMode() === "full" ? "全量模式" : "快速模式"}）：${data.job.completed_queries || 0}/${data.job.total_queries || 0}，${sourceNote}，每源数量：${limitNote || batchLimit}，完成后会显示到下方候选结果。`;
    await loadRetrievalBatchJobs({ silent: true });
    await loadRetrievalRuns({ silent: true });
    await loadRetrievalSummary({ silent: true });
  } catch (error) {
    state.retrievalBatchMessage = error.message;
  } finally {
    state.retrievalBatchBusy = false;
    renderAddItemModal();
  }
}

async function loadSimplePlanBatchCandidates(jobId, options = {}) {
  const cleanJobId = String(jobId || "").trim();
  if (!state.libraryId || !cleanJobId) return;
  const silent = Boolean(options.silent);
  try {
    state.simplePlanBatchCandidatesBusy = true;
    if (!silent) state.retrievalBatchMessage = "正在加载计划检索候选和 AI 推荐...";
    renderAddItemModal();
    const params = new URLSearchParams({ limit: "120", use_ai_evaluation: "0" });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/batches/${encodeURIComponent(cleanJobId)}/candidates?${params.toString()}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载计划检索候选失败。");
    state.retrievalCandidates = normalizeRetrievalCandidates(data.candidates || []);
    state.retrievalSelectedKeys = new Set(
      state.retrievalCandidates
        .filter((candidate) => candidate.ai_evaluation?.auto_select === true)
        .map((candidate) => candidate.client_key)
        .filter(Boolean)
    );
    state.retrievalStats = data.source_stats || {};
    state.retrievalAiEvaluationSummary = data.ai_evaluation_summary || null;
    state.retrievalRunId = "";
    state.simplePlanBatchLoadedJobId = cleanJobId;
    const aiRecommended = state.retrievalCandidates.filter((candidate) => {
      return String(candidate.ai_evaluation?.decision || "").toLowerCase() === "recommend";
    }).length;
    state.retrievalBatchMessage = `已显示计划检索结果：${state.retrievalCandidates.length} 条候选，推荐 ${aiRecommended} 条；需要更省事的排序时，可点击“AI 推荐排序”。`;
  } catch (error) {
    state.retrievalBatchMessage = error.message;
  } finally {
    state.simplePlanBatchCandidatesBusy = false;
    renderAddItemModal();
  }
}

async function downloadRetrievalQueryPlanReport(format = "markdown") {
  const cleanFormat = String(format || "markdown").trim();
  if (!state.libraryId) return;
  const queryInput = document.querySelector("[data-retrieval-query-input]");
  const seedQuery = String(queryInput?.value || state.retrievalQuery || "robot").trim() || "robot";
  try {
    const params = new URLSearchParams({
      format: cleanFormat,
      seed_query: seedQuery,
      sample_size: "5",
      limit: "5",
    });
    if (state.retrievalQueryPlanUseAi && state.retrievalModelStatus?.configured === true) params.set("use_ai", "1");
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/query-plan/report?${params.toString()}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "Download query plan report failed.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-query-plan.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalBatchMessage = error.message;
    renderAddItemModal();
  }
}

async function submitRetrievalBatch(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const queries = String(new FormData(form).get("queries") || "").trim();
  const selectedSources = currentRetrievalSourceSelection();
  const unavailableSources = unavailableRetrievalSources(selectedSources);
  const sources = availableRetrievalSources(selectedSources);
  state.retrievalBatchQueries = queries;
  if (!queries) {
    state.retrievalBatchMessage = "Add at least one query.";
    renderAddItemModal();
    return;
  }
  if (!selectedSources.length) {
    state.retrievalBatchMessage = "Select at least one source.";
    renderAddItemModal();
    return;
  }
  if (unavailableSources.length) {
    state.retrievalBatchMessage = unavailableRetrievalSourceMessage(unavailableSources);
    renderAddItemModal();
    return;
  }
  if (!sources.length) {
    state.retrievalBatchMessage = "Select at least one available source.";
    renderAddItemModal();
    return;
  }
  try {
    state.retrievalBatchBusy = true;
    state.retrievalBatchMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/batches`, { queries, sources, limit: 10 });
    state.retrievalBatchQueries = "";
    state.retrievalBatchJobs = [data.job, ...state.retrievalBatchJobs.filter((job) => job.job_id !== data.job.job_id)];
    state.retrievalBatchMessage = `Batch ${data.job.status || "queued"}: ${data.job.completed_queries || 0}/${data.job.total_queries || 0}`;
    await loadRetrievalBatchJobs({ silent: true });
    await loadRetrievalRuns({ silent: true });
    await loadRetrievalSummary({ silent: true });
  } catch (error) {
    state.retrievalBatchMessage = error.message;
  } finally {
    state.retrievalBatchBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalBatchJobs(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalBatchBusy = true;
    if (!silent) state.retrievalBatchMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/batches`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "Failed to load batch jobs");
    state.retrievalBatchJobs = data.jobs || [];
    scheduleRetrievalBatchRefresh();
    const simpleJob = currentSimplePlanBatchJob();
    if (
      simpleJob &&
      String(simpleJob.status || "") === "completed" &&
      state.simplePlanBatchLoadedJobId !== String(simpleJob.job_id || "") &&
      !state.simplePlanBatchCandidatesBusy
    ) {
      await loadSimplePlanBatchCandidates(simpleJob.job_id, { silent: true });
    }
  } catch (error) {
    state.retrievalBatchMessage = error.message;
  } finally {
    state.retrievalBatchBusy = false;
    renderAddItemModal();
  }
}

async function updateRetrievalBatchJob(jobId, action, message) {
  const cleanJobId = String(jobId || "").trim();
  if (!cleanJobId) return;
  try {
    state.retrievalBatchBusy = true;
    state.retrievalBatchMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/batches/${encodeURIComponent(cleanJobId)}/${action}`, {});
    state.retrievalBatchJobs = [data.job, ...state.retrievalBatchJobs.filter((job) => job.job_id !== data.job.job_id)];
    state.retrievalBatchMessage = message;
    await loadRetrievalBatchJobs({ silent: true });
    await loadRetrievalRuns({ silent: true });
    await loadRetrievalSummary({ silent: true });
  } catch (error) {
    state.retrievalBatchMessage = error.message;
  } finally {
    state.retrievalBatchBusy = false;
    renderAddItemModal();
  }
}

async function cancelRetrievalBatch(jobId) {
  await updateRetrievalBatchJob(jobId, "cancel", "Batch cancellation requested.");
}

async function pauseRetrievalBatch(jobId) {
  await updateRetrievalBatchJob(jobId, "pause", "Batch paused.");
}

async function resumeRetrievalBatch(jobId) {
  await updateRetrievalBatchJob(jobId, "resume", "Batch resumed.");
}

async function retryRetrievalBatchFailures(jobId) {
  await updateRetrievalBatchJob(jobId, "retry-failed", "Retrying failed queries.");
}

function retrievalRemediationFromScope(scope) {
  if (scope === "source-intake") {
    return state.retrievalSourceIntakeResult?.validation_plan?.batch_validation?.remediation || {};
  }
  return state.retrievalOnboarding?.batch_validation?.remediation || {};
}

function retrievalRemediationPayload(remediation) {
  const queries = (Array.isArray(remediation?.queries) ? remediation.queries : [])
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const sources = (Array.isArray(remediation?.sources) ? remediation.sources : [])
    .map((item) => String(item || "").trim().toLowerCase())
    .filter(Boolean);
  return {
    queries: queries.join("\n"),
    sources,
    limit: 10,
  };
}

function setRetrievalRemediationMessage(scope, message) {
  if (scope === "source-intake") {
    state.retrievalSourceIntakeMessage = message;
  } else {
    state.retrievalOnboardingMessage = message;
  }
  state.retrievalBatchMessage = message;
}

async function runRetrievalBatchRemediation(scope) {
  const remediation = retrievalRemediationFromScope(scope);
  const method = String(remediation?.method || "GET").trim().toUpperCase();
  const endpoint = String(remediation?.endpoint || "").trim();
  const label = String(remediation?.label || "Run validation batch").trim();
  if (method !== "POST") {
    if (endpoint) await downloadRetrievalGateArtifact(endpoint);
    return;
  }
  if (!safeRetrievalEndpoint(endpoint)) {
    setRetrievalRemediationMessage(scope, "Unsupported remediation endpoint.");
    renderAddItemModal();
    return;
  }
  const payload = endpoint === "/retrieval/batches" ? retrievalRemediationPayload(remediation) : {};
  if (endpoint === "/retrieval/batches" && !payload.queries) {
    setRetrievalRemediationMessage(scope, "No remediation queries available; use PLAN or Source intake queries first.");
    renderAddItemModal();
    return;
  }
  try {
    state.retrievalBatchBusy = true;
    setRetrievalRemediationMessage(scope, "");
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}${endpoint}`, payload);
    if (data.job) {
      state.retrievalBatchJobs = [data.job, ...state.retrievalBatchJobs.filter((job) => job.job_id !== data.job.job_id)];
      setRetrievalRemediationMessage(scope, `${label}: batch ${data.job.status || "queued"} ${data.job.completed_queries || 0}/${data.job.total_queries || 0}`);
    } else {
      setRetrievalRemediationMessage(scope, `${label}: requested.`);
    }
    await loadRetrievalBatchJobs({ silent: true });
    await loadRetrievalRuns({ silent: true });
    await loadRetrievalSummary({ silent: true });
    if (scope === "onboarding") await loadRetrievalOnboarding();
  } catch (error) {
    setRetrievalRemediationMessage(scope, error.message);
  } finally {
    state.retrievalBatchBusy = false;
    renderAddItemModal();
  }
}

async function downloadRetrievalBatchReport(jobId, format = "markdown", scope = "queries") {
  const cleanJobId = String(jobId || "").trim();
  const cleanFormat = String(format || "markdown").trim();
  const cleanScope = String(scope || "queries").trim();
  if (!state.libraryId || !cleanJobId) return;
  try {
    const params = new URLSearchParams({ format: cleanFormat, scope: cleanScope });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/batches/${encodeURIComponent(cleanJobId)}/report?${params.toString()}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "Failed to download batch report");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `${cleanJobId}-report.md`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalBatchMessage = error.message;
    renderAddItemModal();
  }
}

function scheduleRetrievalBatchRefresh() {
  if (retrievalBatchRefreshTimer) window.clearTimeout(retrievalBatchRefreshTimer);
  retrievalBatchRefreshTimer = null;
  const hasActive = (state.retrievalBatchJobs || []).some((job) => retrievalBatchIsActive(job));
  if (!hasActive) return;
  retrievalBatchRefreshTimer = window.setTimeout(() => {
    loadRetrievalBatchJobs({ silent: true });
    loadRetrievalRuns({ silent: true });
    loadRetrievalSummary({ silent: true });
    loadRetrievalOnboarding({ silent: true });
  }, 2000);
}

async function loadRetrievalRuns(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalRunsBusy = true;
    if (!silent) state.retrievalRunsMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/runs`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载检索记录失败");
    state.retrievalRuns = data.runs || [];
    state.retrievalRunsMessage = "";
  } catch (error) {
    state.retrievalRunsMessage = error.message;
  } finally {
    state.retrievalRunsBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalRunCandidates(runId, options = {}) {
  const cleanRunId = String(runId || "").trim();
  if (!state.libraryId || !cleanRunId) return;
  const silent = Boolean(options.silent);
  try {
    if (!silent) state.addItemMessage = "正在恢复检索结果...";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/runs/${encodeURIComponent(cleanRunId)}/report?format=json`);
    const report = await parseJSONResponse(response);
    if (!response.ok) throw new Error(report.error || "恢复检索结果失败");
    const run = report.run || {};
    const candidates = (report.candidates || [])
      .map((item) => (item && typeof item.payload === "object" && item.payload ? item.payload : item))
      .filter((item) => item && typeof item === "object");
    state.retrievalRunId = String(run.run_id || cleanRunId);
    state.retrievalQuery = String(run.query || state.retrievalQuery || "");
    state.retrievalStats = run.source_stats || null;
    state.retrievalCandidates = normalizeRetrievalCandidates(candidates);
    state.retrievalSelectedKeys = new Set();
    state.retrievalAiEvaluationSummary = run.ai_evaluation_summary || null;
    if (!silent) state.addItemMessage = `已恢复检索结果：${state.retrievalCandidates.length} 条候选。`;
  } catch (error) {
    if (!silent) state.addItemMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

async function loadRetrievalSummary(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalSummaryBusy = true;
    if (!silent) state.retrievalSummaryMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/summary`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载阶段统计失败");
    state.retrievalSummary = data.summary || null;
    state.retrievalSummaryMessage = "";
  } catch (error) {
    state.retrievalSummaryMessage = error.message;
  } finally {
    state.retrievalSummaryBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalSources(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  const check = Boolean(options.check);
  try {
    state.retrievalSourcesBusy = true;
    state.retrievalSourcesChecking = check;
    if (!silent) state.retrievalSourcesMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/sources${check ? "?check=1" : ""}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载数据源状态失败");
    const info = {};
    (data.sources || []).forEach((source) => {
      if (source.name) info[source.name] = source;
    });
    state.retrievalSourceInfo = info;
    Object.entries(info).forEach(([name, source]) => {
      if (source.available === false) state.retrievalSources.delete(name);
    });
    state.retrievalSourcesMessage = "";
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
  } finally {
    state.retrievalSourcesBusy = false;
    state.retrievalSourcesChecking = false;
    renderAddItemModal();
  }
}

async function setupRetrievalRehearsalKit() {
  if (!state.libraryId) return;
  const confirmed = window.confirm("Generate rehearsal CSV, SQLite and Object Manifest sources and replace current internal source configs?");
  if (!confirmed) return;
  try {
    state.retrievalSourcesBusy = true;
    state.retrievalSourcesMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/rehearsal/setup`, { replace_existing: true });
    const query = data.kit?.queries?.[0] || "robot catalyst";
    state.retrievalQuery = query;
    ["localfile", "sqlite", "manifest"].forEach((source) => state.retrievalSources.add(source));
    state.retrievalSourcesMessage = `${data.message || "Rehearsal kit configured."} Query: ${query}`;
    await loadRetrievalLocalPaths({ silent: true });
    await loadRetrievalSqliteConfig({ silent: true });
    await loadRetrievalManifestConfig({ silent: true });
    await loadRetrievalSources({ silent: true });
    await loadRetrievalReadiness({ silent: true });
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
  } finally {
    state.retrievalSourcesBusy = false;
    renderAddItemModal();
  }
}

async function validateRetrievalRehearsalRun() {
  if (!state.libraryId) return;
  const confirmed = window.confirm("Generate rehearsal sources, replace current internal source configs and start the 3-query PLAN validation batch?");
  if (!confirmed) return;
  try {
    state.retrievalSourcesBusy = true;
    state.retrievalBatchBusy = true;
    state.retrievalReadinessBusy = true;
    state.retrievalOnboardingBusy = true;
    state.retrievalSourcesMessage = "";
    state.retrievalBatchMessage = "";
    state.retrievalReadinessMessage = "";
    state.retrievalOnboardingMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/rehearsal/validate`, {
      replace_existing: true,
      sample_size: 2,
      limit: 5,
    });
    const validationSummary = data.validation_summary || {};
    const queries = Array.isArray(data.queries) ? data.queries : (data.kit?.queries || []);
    const query = queries[0] || "robot catalyst";
    const job = data.job || {};
    state.retrievalQuery = query;
    state.retrievalBatchQueries = queries.join("\n");
    ["localfile", "sqlite", "manifest"].forEach((source) => state.retrievalSources.add(source));
    if (data.readiness) {
      state.retrievalReadiness = data.readiness;
      state.retrievalReadinessMessage = data.readiness.message || "";
      const info = {};
      (data.readiness.sources || []).forEach((source) => {
        if (source.name) info[source.name] = source;
      });
      if (Object.keys(info).length) state.retrievalSourceInfo = info;
    }
    if (data.onboarding) {
      state.retrievalOnboarding = data.onboarding;
      state.retrievalOnboardingMessage = data.onboarding.message || "";
    }
    if (job.job_id) {
      state.retrievalBatchJobs = [job, ...state.retrievalBatchJobs.filter((item) => item.job_id !== job.job_id)];
      state.retrievalBatchMessage = `Rehearsal batch ${job.status || "queued"}: ${job.completed_queries || 0}/${job.total_queries || 0}`;
    }
    state.retrievalSourcesMessage = validationSummary.status
      ? `Rehearsal ${validationSummary.status}: ${validationSummary.completed_queries || 0}/${validationSummary.total_queries || 0} queries, ${validationSummary.total_candidates || 0} candidates, ${validationSummary.artifact_count || 0} artifacts.`
      : (data.message || "Rehearsal validation started.");
    await loadRetrievalLocalPaths({ silent: true });
    await loadRetrievalSqliteConfig({ silent: true });
    await loadRetrievalManifestConfig({ silent: true });
    await loadRetrievalSources({ silent: true });
    await loadRetrievalBatchJobs({ silent: true });
    await loadRetrievalRuns({ silent: true });
    await loadRetrievalSummary({ silent: true });
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
    state.retrievalBatchMessage = error.message;
  } finally {
    state.retrievalSourcesBusy = false;
    state.retrievalBatchBusy = false;
    state.retrievalReadinessBusy = false;
    state.retrievalOnboardingBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalModelStatus(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  const check = Boolean(options.check);
  try {
    state.retrievalModelStatusBusy = true;
    if (!silent) state.retrievalModelStatusMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/model-status${check ? "?check=1" : ""}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "Failed to load model status.");
    state.retrievalModelStatus = data.model || null;
    state.retrievalModelStatusMessage = "";
    if (state.retrievalModelStatus?.configured !== true) {
      state.retrievalFieldMapLabUseAi = false;
      state.retrievalQueryPlanUseAi = false;
    }
  } catch (error) {
    state.retrievalModelStatus = null;
    state.retrievalFieldMapLabUseAi = false;
    state.retrievalQueryPlanUseAi = false;
    state.retrievalModelStatusMessage = error.message;
  } finally {
    state.retrievalModelStatusBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalReadiness(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  const queryInput = document.querySelector("[data-retrieval-query-input]");
  const query = String(queryInput?.value || state.retrievalQuery || "robot").trim() || "robot";
  state.retrievalQuery = query;
  try {
    state.retrievalReadinessBusy = true;
    if (!silent) state.retrievalReadinessMessage = "";
    renderAddItemModal();
    const params = new URLSearchParams({ query, sample_size: "2" });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/readiness?${params.toString()}`);
    const data = await parseJSONResponse(response);
    const readiness = data.readiness || null;
    state.retrievalReadiness = readiness;
    state.retrievalReadinessMessage = readiness?.message || "";
    const info = {};
    (readiness?.sources || []).forEach((source) => {
      if (source.name) info[source.name] = source;
    });
    if (Object.keys(info).length) state.retrievalSourceInfo = info;
  } catch (error) {
    state.retrievalReadinessMessage = error.message;
  } finally {
    state.retrievalReadinessBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalOnboarding(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  const queryInput = document.querySelector("[data-retrieval-query-input]");
  const query = String(queryInput?.value || state.retrievalQuery || "robot").trim() || "robot";
  state.retrievalQuery = query;
  try {
    state.retrievalOnboardingBusy = true;
    if (!silent) state.retrievalOnboardingMessage = "";
    renderAddItemModal();
    const params = new URLSearchParams({ query, sample_size: "2" });
    applyRetrievalOnboardingQueryParams(params);
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/onboarding?${params.toString()}`);
    const data = await parseJSONResponse(response);
    const onboarding = data.onboarding || null;
    state.retrievalOnboarding = onboarding;
    state.retrievalOnboardingMessage = onboarding?.message || "";
    if (onboarding?.readiness) {
      state.retrievalReadiness = onboarding.readiness;
      state.retrievalReadinessMessage = onboarding.readiness.message || state.retrievalReadinessMessage;
    }
    const info = {};
    (onboarding?.readiness?.sources || []).forEach((source) => {
      if (source.name) info[source.name] = source;
    });
    if (Object.keys(info).length) state.retrievalSourceInfo = info;
  } catch (error) {
    state.retrievalOnboardingMessage = error.message;
  } finally {
    state.retrievalOnboardingBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalLocalPaths(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalLocalPathsBusy = true;
    if (!silent) state.retrievalLocalPathsMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/local-files`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载本地路径失败");
    state.retrievalLocalPaths = (data.paths || []).join("\n");
    state.retrievalLocalFieldMap = data.field_map && Object.keys(data.field_map).length
      ? JSON.stringify(data.field_map, null, 2)
      : "";
    const status = data.status || {};
    state.retrievalLocalPathsMessage = status.message || "";
    if (status.available) await loadRetrievalLocalPreview({ silent: true });
    else {
      state.retrievalLocalPreview = null;
      state.retrievalLocalPreviewMessage = "";
    }
  } catch (error) {
    state.retrievalLocalPathsMessage = error.message;
  } finally {
    state.retrievalLocalPathsBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalLocalPreview(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalLocalPreviewBusy = true;
    if (!silent) state.retrievalLocalPreviewMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/local-files/preview?sample_size=2`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "Local preview failed");
    state.retrievalLocalPreview = data.preview || null;
    state.retrievalLocalPreviewMessage = "";
  } catch (error) {
    state.retrievalLocalPreview = null;
    state.retrievalLocalPreviewMessage = silent ? "" : error.message;
  } finally {
    state.retrievalLocalPreviewBusy = false;
    renderAddItemModal();
  }
}

function suggestedLocalFieldMapFromPreview(preview) {
  const fieldMap = {};
  (preview?.files || []).forEach((file) => {
    const suggestion = file.field_map_suggestion || {};
    Object.entries(suggestion.field_map || {}).forEach(([target, sourcePath]) => {
      if (!fieldMap[target]) fieldMap[target] = sourcePath;
    });
  });
  return fieldMap;
}

async function suggestRetrievalLocalFieldMap() {
  if (!state.libraryId) return;
  try {
    state.retrievalLocalPreviewBusy = true;
    state.retrievalLocalPathsMessage = "";
    renderAddItemModal();
    let fieldMap = {};
    let apiError = null;
    try {
      const response = await fetch(`/api/library/${state.libraryId}/retrieval/local-files/field-map/suggest?sample_size=3`);
      const data = await parseJSONResponse(response);
      if (!data.ok) throw new Error(data.error || "Local field_map suggestion failed");
      fieldMap = data.suggestion?.field_map || {};
    } catch (error) {
      apiError = error;
    }
    if (!Object.keys(fieldMap).length) {
      if (!state.retrievalLocalPreview) {
        await loadRetrievalLocalPreview({ silent: true });
      }
      fieldMap = suggestedLocalFieldMapFromPreview(state.retrievalLocalPreview);
    }
    const count = Object.keys(fieldMap).length;
    if (!count) throw apiError || new Error("Local field_map suggestion is empty");
    state.retrievalLocalFieldMap = JSON.stringify(fieldMap, null, 2);
    state.retrievalLocalPathsMessage = `Suggested ${count} local field_map entries. Review and save.`;
  } catch (error) {
    state.retrievalLocalPathsMessage = error.message;
  } finally {
    state.retrievalLocalPreviewBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalHttpJsonConfig(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalHttpJsonBusy = true;
    if (!silent) state.retrievalHttpJsonMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/http-json`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 HTTP JSON 配置失败");
    state.retrievalHttpJsonConfig = data.config || "";
    const summary = data.summary || {};
    state.retrievalHttpJsonMessage = summary.configured
      ? `${summary.label || "HTTP JSON"} configured via ${data.source || "preference"}.`
      : "";
  } catch (error) {
    state.retrievalHttpJsonMessage = error.message;
  } finally {
    state.retrievalHttpJsonBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalHttpJsonTemplates(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    if (!silent) state.retrievalHttpJsonMessage = "";
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/http-json/templates`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 HTTP JSON 模板失败");
    state.retrievalHttpJsonTemplates = data.templates || [];
  } catch (error) {
    if (!silent) state.retrievalHttpJsonMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

function applyRetrievalHttpJsonTemplate(templateId) {
  const template = (state.retrievalHttpJsonTemplates || []).find((item) => String(item.id || "") === String(templateId || ""));
  if (!template) return;
  state.retrievalHttpJsonConfig = JSON.stringify(template.config || {}, null, 2);
  state.retrievalHttpJsonPreview = null;
  state.retrievalHttpJsonPreviewMessage = "";
  state.retrievalHttpJsonMessage = `${template.label || "Template"} template applied. Save to enable it.`;
  renderAddItemModal();
}

async function loadRetrievalHttpJsonPreview(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalHttpJsonPreviewBusy = true;
    if (!silent) state.retrievalHttpJsonPreviewMessage = "";
    renderAddItemModal();
    const query = String(state.retrievalQuery || "robot").trim() || "robot";
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/http-json/preview?sample_size=2&query=${encodeURIComponent(query)}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "HTTP JSON preview failed");
    state.retrievalHttpJsonPreview = data.preview || null;
    state.retrievalHttpJsonPreviewMessage = "";
  } catch (error) {
    state.retrievalHttpJsonPreview = null;
    state.retrievalHttpJsonPreviewMessage = silent ? "" : error.message;
  } finally {
    state.retrievalHttpJsonPreviewBusy = false;
    renderAddItemModal();
  }
}

async function saveRetrievalHttpJsonConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const config = String(new FormData(form).get("config") || "");
  try {
    state.retrievalHttpJsonBusy = true;
    state.retrievalHttpJsonConfig = config;
    state.retrievalHttpJsonMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/http-json`, { config });
    state.retrievalHttpJsonConfig = data.config || "";
    state.retrievalHttpJsonMessage = data.summary?.configured ? "HTTP JSON config saved." : "HTTP JSON config cleared.";
    state.retrievalHttpJsonPreview = null;
    state.retrievalHttpJsonPreviewMessage = "";
    if (data.summary?.configured) state.retrievalSources.add("httpjson");
    else state.retrievalSources.delete("httpjson");
    if (data.summary?.configured) await loadRetrievalHttpJsonPreview({ silent: false });
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalHttpJsonMessage = error.message;
  } finally {
    state.retrievalHttpJsonBusy = false;
    renderAddItemModal();
  }
}

async function clearRetrievalHttpJsonConfig() {
  try {
    state.retrievalHttpJsonBusy = true;
    state.retrievalHttpJsonMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/http-json`, { config: "" });
    state.retrievalHttpJsonConfig = data.config || "";
    state.retrievalHttpJsonMessage = "HTTP JSON config cleared.";
    state.retrievalHttpJsonPreview = null;
    state.retrievalHttpJsonPreviewMessage = "";
    state.retrievalSources.delete("httpjson");
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalHttpJsonMessage = error.message;
  } finally {
    state.retrievalHttpJsonBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalSqliteConfig(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalSqliteBusy = true;
    if (!silent) state.retrievalSqliteMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/sqlite`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 SQLite 配置失败");
    state.retrievalSqliteConfig = data.config || "";
    const summary = data.summary || {};
    state.retrievalSqliteMessage = summary.configured
      ? `${summary.label || "SQLite"} configured via ${data.source || "preference"}.`
      : "";
  } catch (error) {
    state.retrievalSqliteMessage = error.message;
  } finally {
    state.retrievalSqliteBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalSqliteTemplates(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    if (!silent) state.retrievalSqliteMessage = "";
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/sqlite/templates`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 SQLite 模板失败");
    state.retrievalSqliteTemplates = data.templates || [];
  } catch (error) {
    if (!silent) state.retrievalSqliteMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

function applyRetrievalSqliteTemplate(templateId) {
  const template = (state.retrievalSqliteTemplates || []).find((item) => String(item.id || "") === String(templateId || ""));
  if (!template) return;
  state.retrievalSqliteConfig = JSON.stringify(template.config || {}, null, 2);
  state.retrievalSqlitePreview = null;
  state.retrievalSqlitePreviewMessage = "";
  state.retrievalSqliteMessage = `${template.label || "Template"} template applied. Save to enable it.`;
  renderAddItemModal();
}

async function loadRetrievalSqlitePreview(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalSqlitePreviewBusy = true;
    if (!silent) state.retrievalSqlitePreviewMessage = "";
    renderAddItemModal();
    const query = String(state.retrievalQuery || "robot").trim() || "robot";
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/sqlite/preview?sample_size=2&query=${encodeURIComponent(query)}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "SQLite preview failed");
    state.retrievalSqlitePreview = data.preview || null;
    state.retrievalSqlitePreviewMessage = "";
  } catch (error) {
    state.retrievalSqlitePreview = null;
    state.retrievalSqlitePreviewMessage = silent ? "" : error.message;
  } finally {
    state.retrievalSqlitePreviewBusy = false;
    renderAddItemModal();
  }
}

async function saveRetrievalSqliteConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const config = String(new FormData(form).get("config") || "");
  try {
    state.retrievalSqliteBusy = true;
    state.retrievalSqliteConfig = config;
    state.retrievalSqliteMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/sqlite`, { config });
    state.retrievalSqliteConfig = data.config || "";
    state.retrievalSqliteMessage = data.summary?.configured ? "SQLite config saved." : "SQLite config cleared.";
    state.retrievalSqlitePreview = null;
    state.retrievalSqlitePreviewMessage = "";
    if (data.summary?.configured) state.retrievalSources.add("sqlite");
    else state.retrievalSources.delete("sqlite");
    if (data.summary?.configured) await loadRetrievalSqlitePreview({ silent: false });
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalSqliteMessage = error.message;
  } finally {
    state.retrievalSqliteBusy = false;
    renderAddItemModal();
  }
}

async function clearRetrievalSqliteConfig() {
  try {
    state.retrievalSqliteBusy = true;
    state.retrievalSqliteMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/sqlite`, { config: "" });
    state.retrievalSqliteConfig = data.config || "";
    state.retrievalSqliteMessage = "SQLite config cleared.";
    state.retrievalSqlitePreview = null;
    state.retrievalSqlitePreviewMessage = "";
    state.retrievalSources.delete("sqlite");
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalSqliteMessage = error.message;
  } finally {
    state.retrievalSqliteBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalManifestConfig(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalManifestBusy = true;
    if (!silent) state.retrievalManifestMessage = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/manifest`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 Object Manifest 配置失败");
    state.retrievalManifestConfig = data.config || "";
    const summary = data.summary || {};
    state.retrievalManifestMessage = summary.configured
      ? `${summary.label || "Object Manifest"} configured via ${data.source || "preference"}.`
      : "";
  } catch (error) {
    state.retrievalManifestMessage = error.message;
  } finally {
    state.retrievalManifestBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalManifestTemplates(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    if (!silent) state.retrievalManifestMessage = "";
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/manifest/templates`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "加载 Object Manifest 模板失败");
    state.retrievalManifestTemplates = data.templates || [];
  } catch (error) {
    if (!silent) state.retrievalManifestMessage = error.message;
  } finally {
    renderAddItemModal();
  }
}

function applyRetrievalManifestTemplate(templateId) {
  const template = (state.retrievalManifestTemplates || []).find((item) => String(item.id || "") === String(templateId || ""));
  if (!template) return;
  state.retrievalManifestConfig = JSON.stringify(template.config || {}, null, 2);
  state.retrievalManifestPreview = null;
  state.retrievalManifestPreviewMessage = "";
  state.retrievalManifestMessage = `${template.label || "Template"} template applied. Save to enable it.`;
  renderAddItemModal();
}

function retrievalFieldMapSuggestionMessage(suggestion, draftApplied) {
  const fieldMap = suggestion?.field_map || {};
  const count = Object.keys(fieldMap).length;
  const sampleCount = Number(suggestion?.sample_count || 0);
  if (draftApplied) {
    return `Suggested ${count} field_map entries from ${sampleCount} samples. Review and save.`;
  }
  const inlineMap = count ? ` field_map: ${JSON.stringify(fieldMap)}` : "";
  return `${suggestion?.message || "Suggestion generated, but no editable config draft was returned."}${inlineMap}`;
}

function applyRetrievalFieldMapSuggestionToConfig(sourceKey, suggestion) {
  const draft = suggestion?.config_draft || {};
  const draftApplied = suggestion?.draft_available !== false && Object.keys(draft).length > 0;
  const message = retrievalFieldMapSuggestionMessage(suggestion, draftApplied);
  const configText = draftApplied ? JSON.stringify(draft, null, 2) : "";
  if (sourceKey === "localfile") {
    if (draftApplied && Array.isArray(draft.paths)) state.retrievalLocalPaths = draft.paths.join("\n");
    if (draftApplied) state.retrievalLocalFieldMap = JSON.stringify(draft.field_map || {}, null, 2);
    state.retrievalLocalPreview = null;
    state.retrievalLocalPreviewMessage = "";
    state.retrievalLocalPathsMessage = message;
  } else if (sourceKey === "httpjson") {
    if (draftApplied) state.retrievalHttpJsonConfig = configText;
    state.retrievalHttpJsonPreview = null;
    state.retrievalHttpJsonPreviewMessage = "";
    state.retrievalHttpJsonMessage = message;
  } else if (sourceKey === "sqlite") {
    if (draftApplied) state.retrievalSqliteConfig = configText;
    state.retrievalSqlitePreview = null;
    state.retrievalSqlitePreviewMessage = "";
    state.retrievalSqliteMessage = message;
  } else if (sourceKey === "manifest") {
    if (draftApplied) state.retrievalManifestConfig = configText;
    state.retrievalManifestPreview = null;
    state.retrievalManifestPreviewMessage = "";
    state.retrievalManifestMessage = message;
  }
}

async function analyzeRetrievalSourceIntake() {
  if (!state.libraryId) return;
  const input = String(state.retrievalSourceIntakeInput || "").trim();
  if (!input) {
    state.retrievalSourceIntakeMessage = "Paste a path, URL, SQL query, columns or JSON sample.";
    renderAddItemModal();
    return;
  }
  state.retrievalSourceIntakeInput = input;
  try {
    state.retrievalSourceIntakeBusy = true;
    state.retrievalSourceIntakeMessage = "";
    state.retrievalSourceIntakeResult = null;
    renderAddItemModal();
    const data = await postJSON(
      `/api/library/${state.libraryId}/retrieval/source-intake`,
      { input, sample_url: state.retrievalSourceIntakeSampleUrl },
    );
    state.retrievalSourceIntakeResult = data.intake || null;
    const result = state.retrievalSourceIntakeResult || {};
    state.retrievalSourceIntakeMessage = result.message || "Source intake analyzed.";
  } catch (error) {
    state.retrievalSourceIntakeResult = null;
    state.retrievalSourceIntakeMessage = error.message;
  } finally {
    state.retrievalSourceIntakeBusy = false;
    renderAddItemModal();
  }
}

async function downloadRetrievalSourceIntakeReport(format = "markdown") {
  if (!state.libraryId) return;
  const cleanFormat = String(format || "markdown").trim();
  const input = String(document.querySelector("[data-retrieval-source-intake-input]")?.value || state.retrievalSourceIntakeInput || "").trim();
  if (!input) {
    state.retrievalSourceIntakeMessage = "Paste a path, URL, SQL query, columns or JSON sample.";
    renderAddItemModal();
    return;
  }
  try {
    state.retrievalSourceIntakeBusy = true;
    state.retrievalSourceIntakeMessage = "";
    renderAddItemModal();
    const response = await fetch(
      `/api/library/${state.libraryId}/retrieval/source-intake/report?format=${encodeURIComponent(cleanFormat)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input, sample_url: state.retrievalSourceIntakeSampleUrl }),
      },
    );
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "Download source intake report failed.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-source-intake-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    state.retrievalSourceIntakeMessage = "Source intake report downloaded.";
  } catch (error) {
    state.retrievalSourceIntakeMessage = error.message;
  } finally {
    state.retrievalSourceIntakeBusy = false;
    renderAddItemModal();
  }
}

function applyRetrievalSourceIntakeToFieldMapLab() {
  const lab = state.retrievalSourceIntakeResult?.field_map_lab || {};
  if (!lab.source_type) return;
  state.retrievalFieldMapLabSource = lab.source_type;
  state.retrievalFieldMapLabMode = lab.input_mode || "columns";
  state.retrievalFieldMapLabInput = lab.input || state.retrievalSourceIntakeInput || "";
  state.retrievalFieldMapLabConfig = lab.config || "";
  state.retrievalFieldMapLabResult = state.retrievalSourceIntakeResult?.field_map_suggestion || null;
  state.retrievalFieldMapLabMessage = "Intake draft loaded. Review and apply or save the target source config.";
  renderAddItemModal();
}

function applyRetrievalSourceIntakeToConfig() {
  const result = state.retrievalSourceIntakeResult || {};
  const sourceType = result.source_type || result.field_map_lab?.source_type;
  const suggestion = result.field_map_suggestion || {};
  if (!sourceType || !Object.keys(suggestion.config_draft || {}).length) {
    state.retrievalSourceIntakeMessage = "No config draft available from intake yet.";
    renderAddItemModal();
    return;
  }
  applyRetrievalFieldMapSuggestionToConfig(sourceType, suggestion);
  state.retrievalSourceIntakeMessage = "Intake config draft applied. Review and save the target source config.";
  renderAddItemModal();
}

function retrievalSourceNameFromIntake(sourceType) {
  return {
    local: "localfile",
    local_file: "localfile",
    localfile: "localfile",
    http: "httpjson",
    http_json: "httpjson",
    httpjson: "httpjson",
    rest: "httpjson",
    sqlite: "sqlite",
    sqlite3: "sqlite",
    manifest: "manifest",
    object_manifest: "manifest",
    objectmanifest: "manifest",
  }[String(sourceType || "").trim().toLowerCase()] || "";
}

function retrievalTargetSourceNameFromIntake(result) {
  const targetName = String(result?.target_source?.name || "").trim();
  return targetName || retrievalSourceNameFromIntake(result?.source_type || result?.field_map_lab?.source_type);
}

function applyRetrievalSourceIntakeQueriesToBatch() {
  const result = state.retrievalSourceIntakeResult || {};
  const validation = state.retrievalSourceIntakeResult?.validation_queries || {};
  const queryText = String(validation.query_text || "").trim();
  if (!queryText) {
    state.retrievalSourceIntakeMessage = "No intake validation query draft available yet.";
    renderAddItemModal();
    return;
  }
  state.retrievalBatchQueries = queryText;
  const sourceName = retrievalTargetSourceNameFromIntake(result);
  if (sourceName) state.retrievalSources = new Set([sourceName]);
  const queryCount = Number(validation.query_count || queryText.split(/\n+/).filter(Boolean).length);
  const sourceNote = sourceName ? ` Target source ${sourceName} is focused by default.` : "";
  state.retrievalSourceIntakeMessage = `Loaded ${queryCount} intake validation queries into the batch form.${sourceNote} Save the source config before starting the batch.`;
  state.retrievalBatchMessage = sourceName
    ? `Review intake validation queries for ${sourceName}; only this target source is selected by default.`
    : "Review intake validation queries, select sources, then start batch retrieval.";
  renderAddItemModal();
}

function clearRetrievalSourceIntake() {
  state.retrievalSourceIntakeInput = "";
  state.retrievalSourceIntakeSampleUrl = false;
  state.retrievalSourceIntakeResult = null;
  state.retrievalSourceIntakeMessage = "";
  renderAddItemModal();
}

function syncRetrievalFieldMapLabFormState() {
  const source = document.querySelector("[data-retrieval-field-map-lab-source]");
  const mode = document.querySelector("[data-retrieval-field-map-lab-mode]");
  const useAi = document.querySelector("[data-retrieval-field-map-lab-ai]");
  const input = document.querySelector("[data-retrieval-field-map-lab-input]");
  const config = document.querySelector("[data-retrieval-field-map-lab-config]");
  if (source) state.retrievalFieldMapLabSource = source.value;
  if (mode) state.retrievalFieldMapLabMode = mode.value;
  if (useAi) state.retrievalFieldMapLabUseAi = Boolean(useAi.checked);
  if (input) state.retrievalFieldMapLabInput = input.value;
  if (config) state.retrievalFieldMapLabConfig = config.value;
}

function retrievalFieldMapLabConfigObject() {
  const text = String(state.retrievalFieldMapLabConfig || "").trim();
  if (!text) return {};
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Optional config JSON must be an object.");
  return parsed;
}

function retrievalFieldMapLabColumns(text) {
  return String(text || "")
    .split(/[\n,\t;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function valueAtDotPath(value, path) {
  if (!path) return undefined;
  return String(path).split(".").filter(Boolean).reduce((current, key) => {
    if (current && typeof current === "object") return current[key];
    return undefined;
  }, value);
}

function retrievalFieldMapLabSamples(text, config) {
  const cleanText = String(text || "").trim();
  if (!cleanText) throw new Error("Paste JSON samples first.");
  const parsed = JSON.parse(cleanText);
  const configuredItems = valueAtDotPath(parsed, config?.items_path || "");
  if (Array.isArray(configuredItems)) return configuredItems;
  if (Array.isArray(parsed)) return parsed;
  if (Array.isArray(parsed?.samples)) return parsed.samples;
  if (Array.isArray(parsed?.items)) return parsed.items;
  if (Array.isArray(parsed?.results)) return parsed.results;
  if (Array.isArray(parsed?.records)) return parsed.records;
  if (Array.isArray(parsed?.data?.records)) return parsed.data.records;
  if (Array.isArray(parsed?.data?.items)) return parsed.data.items;
  return [parsed];
}

function retrievalFieldMapLabPayload() {
  syncRetrievalFieldMapLabFormState();
  const config = retrievalFieldMapLabConfigObject();
  const payload = {
    source_type: state.retrievalFieldMapLabSource,
  };
  if (state.retrievalFieldMapLabUseAi && state.retrievalModelStatus?.configured === true) payload.use_ai = true;
  if (Object.keys(config).length) payload.config = config;
  if (state.retrievalFieldMapLabMode === "samples") {
    payload.samples = retrievalFieldMapLabSamples(state.retrievalFieldMapLabInput, config);
  } else {
    const columns = retrievalFieldMapLabColumns(state.retrievalFieldMapLabInput);
    if (!columns.length) throw new Error("Enter at least one source column.");
    payload.columns = columns;
  }
  return payload;
}

async function suggestRetrievalFieldMapLab() {
  if (!state.libraryId) return;
  try {
    state.retrievalFieldMapLabBusy = true;
    state.retrievalFieldMapLabResult = null;
    state.retrievalFieldMapLabMessage = "";
    renderAddItemModal();
    const payload = retrievalFieldMapLabPayload();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/field-map/suggest`, payload);
    if (state.retrievalFieldMapLabSource === "localfile" && Object.keys(data.field_map || {}).length && !Object.keys(data.config_draft || {}).length) {
      data.config_draft = { field_map: data.field_map };
    }
    if (Object.keys(data.config_draft || {}).length) data.draft_available = true;
    state.retrievalFieldMapLabResult = data;
    const ai = data.ai_enhancement || {};
    const aiMessage = ai.requested ? ` AI: ${ai.status || "requested"}.` : "";
    state.retrievalFieldMapLabMessage = `Suggested ${Object.keys(data.field_map || {}).length} field_map entries.${aiMessage}`;
  } catch (error) {
    state.retrievalFieldMapLabResult = null;
    state.retrievalFieldMapLabMessage = error.message;
  } finally {
    state.retrievalFieldMapLabBusy = false;
    renderAddItemModal();
  }
}

async function downloadRetrievalFieldMapReport(format = "markdown") {
  if (!state.libraryId) return;
  const cleanFormat = String(format || "markdown").trim();
  let payload = {};
  try {
    payload = retrievalFieldMapLabPayload();
  } catch (error) {
    state.retrievalFieldMapLabMessage = error.message;
    renderAddItemModal();
    return;
  }
  try {
    state.retrievalFieldMapLabBusy = true;
    state.retrievalFieldMapLabMessage = "";
    renderAddItemModal();
    const response = await fetch(
      `/api/library/${state.libraryId}/retrieval/field-map/report?format=${encodeURIComponent(cleanFormat)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "Download field map report failed.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-field-map-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    state.retrievalFieldMapLabMessage = "Field map report downloaded.";
  } catch (error) {
    state.retrievalFieldMapLabMessage = error.message;
  } finally {
    state.retrievalFieldMapLabBusy = false;
    renderAddItemModal();
  }
}

const configuredFieldMapReportSources = {
  localfile: {
    endpoint: "local-files",
    busyKey: "retrievalLocalPreviewBusy",
    messageKey: "retrievalLocalPathsMessage",
    label: "Local field_map",
    includeQuery: false,
  },
  httpjson: {
    endpoint: "http-json",
    busyKey: "retrievalHttpJsonBusy",
    messageKey: "retrievalHttpJsonMessage",
    label: "HTTP JSON field_map",
    includeQuery: true,
  },
  sqlite: {
    endpoint: "sqlite",
    busyKey: "retrievalSqliteBusy",
    messageKey: "retrievalSqliteMessage",
    label: "SQLite field_map",
    includeQuery: true,
  },
  manifest: {
    endpoint: "manifest",
    busyKey: "retrievalManifestBusy",
    messageKey: "retrievalManifestMessage",
    label: "Object Manifest field_map",
    includeQuery: false,
  },
};

async function downloadRetrievalConfiguredFieldMapReport(sourceKey, format = "markdown") {
  if (!state.libraryId) return;
  const source = configuredFieldMapReportSources[String(sourceKey || "")];
  if (!source) return;
  const cleanFormat = String(format || "markdown").trim();
  const params = new URLSearchParams({ sample_size: "3", format: cleanFormat });
  if (source.includeQuery) params.set("query", String(state.retrievalQuery || "robot").trim() || "robot");
  try {
    state[source.busyKey] = true;
    state[source.messageKey] = "";
    renderAddItemModal();
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/${source.endpoint}/field-map/report?${params.toString()}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || `Download ${source.label} report failed.`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-${source.endpoint}-field-map-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    state[source.messageKey] = `${source.label} report downloaded.`;
  } catch (error) {
    state[source.messageKey] = error.message;
  } finally {
    state[source.busyKey] = false;
    renderAddItemModal();
  }
}

function applyRetrievalFieldMapLabDraft() {
  if (!state.retrievalFieldMapLabResult) return;
  applyRetrievalFieldMapSuggestionToConfig(state.retrievalFieldMapLabSource, state.retrievalFieldMapLabResult);
  state.retrievalFieldMapLabMessage = "Draft applied. Review and save the target source config.";
  renderAddItemModal();
}

function clearRetrievalFieldMapLab() {
  state.retrievalFieldMapLabInput = "";
  state.retrievalFieldMapLabConfig = "";
  state.retrievalFieldMapLabResult = null;
  state.retrievalFieldMapLabMessage = "";
  renderAddItemModal();
}

function applyRetrievalReadinessFieldMapSuggestionToConfig(sourceKey) {
  const normalizedSource = String(sourceKey || "").trim();
  const entry = (state.retrievalReadiness?.previews || []).find((item) => item?.name === normalizedSource);
  if (!entry?.field_map_suggestion) return;
  applyRetrievalFieldMapSuggestionToConfig(normalizedSource, entry.field_map_suggestion);
  renderAddItemModal();
}

async function suggestRetrievalHttpJsonFieldMap() {
  if (!state.libraryId) return;
  const query = String(state.retrievalQuery || "robot").trim() || "robot";
  try {
    state.retrievalHttpJsonBusy = true;
    state.retrievalHttpJsonMessage = "";
    renderAddItemModal();
    const params = new URLSearchParams({ sample_size: "3", query });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/http-json/field-map/suggest?${params.toString()}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "HTTP JSON field_map suggestion failed");
    applyRetrievalFieldMapSuggestionToConfig("httpjson", data.suggestion || {});
  } catch (error) {
    state.retrievalHttpJsonMessage = error.message;
  } finally {
    state.retrievalHttpJsonBusy = false;
    renderAddItemModal();
  }
}

async function suggestRetrievalSqliteFieldMap() {
  if (!state.libraryId) return;
  const query = String(state.retrievalQuery || "robot").trim() || "robot";
  try {
    state.retrievalSqliteBusy = true;
    state.retrievalSqliteMessage = "";
    renderAddItemModal();
    const params = new URLSearchParams({ sample_size: "3", query });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/sqlite/field-map/suggest?${params.toString()}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "SQLite field_map suggestion failed");
    applyRetrievalFieldMapSuggestionToConfig("sqlite", data.suggestion || {});
  } catch (error) {
    state.retrievalSqliteMessage = error.message;
  } finally {
    state.retrievalSqliteBusy = false;
    renderAddItemModal();
  }
}

async function suggestRetrievalManifestFieldMap() {
  if (!state.libraryId) return;
  try {
    state.retrievalManifestBusy = true;
    state.retrievalManifestMessage = "";
    renderAddItemModal();
    const params = new URLSearchParams({ sample_size: "3" });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/manifest/field-map/suggest?${params.toString()}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "Object Manifest field_map suggestion failed");
    applyRetrievalFieldMapSuggestionToConfig("manifest", data.suggestion || {});
  } catch (error) {
    state.retrievalManifestMessage = error.message;
  } finally {
    state.retrievalManifestBusy = false;
    renderAddItemModal();
  }
}

async function loadRetrievalManifestPreview(options = {}) {
  if (!state.libraryId) return;
  const silent = Boolean(options.silent);
  try {
    state.retrievalManifestPreviewBusy = true;
    if (!silent) state.retrievalManifestPreviewMessage = "";
    renderAddItemModal();
    const query = String(state.retrievalQuery || "robot").trim() || "robot";
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/manifest/preview?sample_size=2&query=${encodeURIComponent(query)}`);
    const data = await parseJSONResponse(response);
    if (!data.ok) throw new Error(data.error || "Object Manifest preview failed");
    state.retrievalManifestPreview = data.preview || null;
    state.retrievalManifestPreviewMessage = "";
  } catch (error) {
    state.retrievalManifestPreview = null;
    state.retrievalManifestPreviewMessage = silent ? "" : error.message;
  } finally {
    state.retrievalManifestPreviewBusy = false;
    renderAddItemModal();
  }
}

async function saveRetrievalManifestConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const config = String(new FormData(form).get("config") || "");
  try {
    state.retrievalManifestBusy = true;
    state.retrievalManifestConfig = config;
    state.retrievalManifestMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/manifest`, { config });
    state.retrievalManifestConfig = data.config || "";
    state.retrievalManifestMessage = data.summary?.configured ? "Object Manifest config saved." : "Object Manifest config cleared.";
    state.retrievalManifestPreview = null;
    state.retrievalManifestPreviewMessage = "";
    if (data.summary?.configured) state.retrievalSources.add("manifest");
    else state.retrievalSources.delete("manifest");
    if (data.summary?.configured) await loadRetrievalManifestPreview({ silent: false });
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalManifestMessage = error.message;
  } finally {
    state.retrievalManifestBusy = false;
    renderAddItemModal();
  }
}

async function clearRetrievalManifestConfig() {
  try {
    state.retrievalManifestBusy = true;
    state.retrievalManifestMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/manifest`, { config: "" });
    state.retrievalManifestConfig = data.config || "";
    state.retrievalManifestMessage = "Object Manifest config cleared.";
    state.retrievalManifestPreview = null;
    state.retrievalManifestPreviewMessage = "";
    state.retrievalSources.delete("manifest");
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalManifestMessage = error.message;
  } finally {
    state.retrievalManifestBusy = false;
    renderAddItemModal();
  }
}

async function saveRetrievalLocalPaths(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const paths = String(new FormData(form).get("paths") || "");
  const fieldMap = String(new FormData(form).get("field_map") || "");
  try {
    state.retrievalLocalPathsBusy = true;
    state.retrievalLocalPaths = paths;
    state.retrievalLocalFieldMap = fieldMap;
    state.retrievalLocalPathsMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/local-files`, { paths, field_map_text: fieldMap });
    state.retrievalLocalPaths = (data.paths || []).join("\n");
    state.retrievalLocalFieldMap = data.field_map && Object.keys(data.field_map).length
      ? JSON.stringify(data.field_map, null, 2)
      : "";
    state.retrievalLocalPathsMessage = data.status?.message || "已保存本地路径。";
    if (data.status?.available) state.retrievalSources.add("localfile");
    if (data.status?.available) await loadRetrievalLocalPreview({ silent: true });
    else {
      state.retrievalLocalPreview = null;
      state.retrievalLocalPreviewMessage = "";
    }
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalLocalPathsMessage = error.message;
  } finally {
    state.retrievalLocalPathsBusy = false;
    renderAddItemModal();
  }
}

async function clearRetrievalLocalPaths() {
  try {
    state.retrievalLocalPathsBusy = true;
    state.retrievalLocalPathsMessage = "";
    renderAddItemModal();
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/local-files`, { paths: [] });
    state.retrievalLocalPaths = "";
    state.retrievalLocalFieldMap = "";
    state.retrievalLocalPathsMessage = data.status?.message || "已清空本地路径。";
    state.retrievalLocalPreview = null;
    state.retrievalLocalPreviewMessage = "";
    state.retrievalSources.delete("localfile");
    await loadRetrievalSources({ silent: true });
  } catch (error) {
    state.retrievalLocalPathsMessage = error.message;
  } finally {
    state.retrievalLocalPathsBusy = false;
    renderAddItemModal();
  }
}

async function downloadRetrievalReport(runId, format = "markdown") {
  const cleanRunId = String(runId || "").trim();
  const cleanFormat = String(format || "markdown").trim();
  if (!cleanRunId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/runs/${encodeURIComponent(cleanRunId)}/report?format=${encodeURIComponent(cleanFormat)}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "下载检索报告失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `${cleanRunId}-report.md`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalRunsMessage = error.message;
    renderAddItemModal();
  }
}

async function downloadRetrievalSummaryReport(format = "markdown") {
  const cleanFormat = String(format || "markdown").trim();
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/summary/report?format=${encodeURIComponent(cleanFormat)}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "下载阶段统计报告失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-summary-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalSummaryMessage = error.message;
    renderAddItemModal();
  }
}

async function downloadRetrievalSourceSetupReport(format = "markdown") {
  const cleanFormat = String(format || "markdown").trim();
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/sources/report?format=${encodeURIComponent(cleanFormat)}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "下载源配置报告失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-source-setup-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
    renderAddItemModal();
  }
}

async function downloadRetrievalReadinessReport(format = "markdown") {
  const cleanFormat = String(format || "markdown").trim();
  if (!state.libraryId) return;
  const queryInput = document.querySelector("[data-retrieval-query-input]");
  const query = String(queryInput?.value || state.retrievalQuery || "robot").trim() || "robot";
  try {
    const params = new URLSearchParams({ format: cleanFormat, query, sample_size: "2" });
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/readiness/report?${params.toString()}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "Download readiness report failed.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-readiness-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalReadinessMessage = error.message;
    renderAddItemModal();
  }
}

async function downloadRetrievalTuningReport(format = "markdown") {
  const cleanFormat = String(format || "markdown").trim();
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/tuning/report?format=${encodeURIComponent(cleanFormat)}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "下载限流调优报告失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || `retrieval-tuning-report.${cleanFormat === "csv" ? "csv" : cleanFormat === "json" ? "json" : "md"}`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
    renderAddItemModal();
  }
}

async function downloadRetrievalConfigBundle() {
  if (!state.libraryId) return;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/config-bundle/download`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "下载检索源配置包失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || "retrieval-config-bundle.json";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
    renderAddItemModal();
  }
}

function currentRetrievalConfigBundleText() {
  return String(document.querySelector("[data-retrieval-config-bundle-input]")?.value ?? state.retrievalConfigBundleText ?? "");
}

function retrievalConfigBundlePayloadFromText(text) {
  const cleanText = String(text || "").trim();
  if (!cleanText) throw new Error("Paste a config bundle JSON first.");
  const parsed = JSON.parse(cleanText);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Config bundle must be a JSON object.");
  const bundle = parsed && typeof parsed === "object" && parsed.bundle && typeof parsed.bundle === "object" ? parsed.bundle : parsed;
  return { bundle };
}

function retrievalConfigBundleResultMessage(result) {
  const applied = Array.isArray(result?.applied) ? result.applied.length : 0;
  const skipped = Array.isArray(result?.skipped) ? result.skipped.length : 0;
  return result?.dry_run
    ? `Dry-run checked: ${applied} would apply, ${skipped} skipped.`
    : `Config bundle imported: ${applied} applied, ${skipped} skipped.`;
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function retrievalConfigBundleResultCsv(result) {
  const headerLine = "result,source,status,action,reason,configured,dry_run,bundle_schema";
  const headers = headerLine.split(",");
  const applied = Array.isArray(result?.applied) ? result.applied : [];
  const skipped = Array.isArray(result?.skipped) ? result.skipped : [];
  const schema = result?.bundle_schema || "";
  const dryRun = result?.dry_run ? "true" : "false";
  const rows = [
    ...applied.map((item) => ({
      result: result?.dry_run ? "would_apply" : "applied",
      source: item.source || "",
      status: "applied",
      action: item.action || (result?.dry_run ? "would_apply" : "applied"),
      reason: "",
      configured: item.configured === undefined ? "" : String(Boolean(item.configured)),
      dry_run: dryRun,
      bundle_schema: schema,
    })),
    ...skipped.map((item) => ({
      result: "skipped",
      source: item.source || "",
      status: "skipped",
      action: "",
      reason: item.reason || "skipped",
      configured: "",
      dry_run: dryRun,
      bundle_schema: schema,
    })),
  ];
  return [
    headerLine,
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n") + "\n";
}

function downloadTextFile(filename, content, type = "text/plain;charset=utf-8") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadRetrievalConfigBundleResultCsv() {
  const result = state.retrievalConfigBundleResult;
  if (!result) return;
  const filename = result.dry_run
    ? "retrieval-config-bundle-dry-run.csv"
    : "retrieval-config-bundle-import-result.csv";
  downloadTextFile(filename, retrievalConfigBundleResultCsv(result), "text/csv;charset=utf-8");
}

async function refreshRetrievalConfigViewsAfterBundleImport() {
  state.retrievalReadiness = null;
  state.retrievalReadinessMessage = "";
  state.retrievalOnboarding = null;
  state.retrievalOnboardingMessage = "";
  await loadRetrievalSources({ silent: true });
  await loadRetrievalLocalPaths({ silent: true });
  await loadRetrievalHttpJsonConfig({ silent: true });
  await loadRetrievalSqliteConfig({ silent: true });
  await loadRetrievalManifestConfig({ silent: true });
}

async function dryRunRetrievalConfigBundleImport() {
  if (!state.libraryId) return;
  const text = currentRetrievalConfigBundleText();
  try {
    state.retrievalConfigBundleBusy = true;
    state.retrievalConfigBundleText = text;
    state.retrievalConfigBundleResult = null;
    state.retrievalConfigBundleMessage = "";
    renderAddItemModal();
    const payload = retrievalConfigBundlePayloadFromText(text);
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/config-bundle?dry_run=1`, payload);
    state.retrievalConfigBundleResult = data;
    state.retrievalConfigBundleMessage = retrievalConfigBundleResultMessage(data);
  } catch (error) {
    state.retrievalConfigBundleResult = null;
    state.retrievalConfigBundleMessage = error.message;
  } finally {
    state.retrievalConfigBundleBusy = false;
    renderAddItemModal();
  }
}

async function importRetrievalConfigBundle() {
  if (!state.libraryId) return;
  const text = currentRetrievalConfigBundleText();
  try {
    state.retrievalConfigBundleBusy = true;
    state.retrievalConfigBundleText = text;
    state.retrievalConfigBundleMessage = "";
    renderAddItemModal();
    const payload = retrievalConfigBundlePayloadFromText(text);
    const data = await postJSON(`/api/library/${state.libraryId}/retrieval/config-bundle`, payload);
    state.retrievalConfigBundleResult = data;
    state.retrievalConfigBundleMessage = retrievalConfigBundleResultMessage(data);
    await refreshRetrievalConfigViewsAfterBundleImport();
  } catch (error) {
    state.retrievalConfigBundleResult = null;
    state.retrievalConfigBundleMessage = error.message;
  } finally {
    state.retrievalConfigBundleBusy = false;
    renderAddItemModal();
  }
}

function clearRetrievalConfigBundleDraft() {
  state.retrievalConfigBundleText = "";
  state.retrievalConfigBundleResult = null;
  state.retrievalConfigBundleMessage = "";
  renderAddItemModal();
}

function retrievalGateArtifactFallbackFilename(endpoint) {
  const text = String(endpoint || "");
  if (text.includes("/onboarding/package")) return "retrieval-onboarding-package.zip";
  if (text.includes("/config-bundle/download")) return "retrieval-config-bundle.json";
  if (text.includes("/readiness/report")) return "retrieval-readiness-report.md";
  if (text.includes("/query-plan/report")) return "retrieval-query-plan.md";
  if (text.includes("/tuning/report")) return "retrieval-tuning-report.md";
  if (text.includes("/onboarding/report")) return "retrieval-onboarding-report.md";
  if (text.includes("scope=sources")) return "retrieval-batch-report-sources.csv";
  if (text.includes("/batches/")) return "retrieval-batch-report.md";
  return "retrieval-artifact.dat";
}

async function downloadRetrievalGateArtifact(endpoint) {
  const cleanEndpoint = String(endpoint || "").trim();
  if (!state.libraryId || !cleanEndpoint) return;
  if (!safeRetrievalEndpoint(cleanEndpoint)) {
    state.retrievalOnboardingMessage = "Unsupported onboarding artifact endpoint.";
    renderAddItemModal();
    return;
  }
  try {
    const response = await fetch(`/api/library/${state.libraryId}${cleanEndpoint}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "Download onboarding artifact failed");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || retrievalGateArtifactFallbackFilename(cleanEndpoint);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalOnboardingMessage = error.message;
    renderAddItemModal();
  }
}

function downloadRetrievalOnboardingPackage() {
  const query = String(document.querySelector("[data-retrieval-query-input]")?.value || state.retrievalQuery || "robot").trim() || "robot";
  const params = new URLSearchParams({ query, sample_size: "2" });
  applyRetrievalOnboardingQueryParams(params);
  const endpoint = `/retrieval/onboarding/package?${params.toString()}`;
  downloadRetrievalGateArtifact(endpoint);
}

async function downloadRetrievalOnboardingReport(format = "markdown") {
  if (!state.libraryId) return;
  const params = new URLSearchParams({ format: format || "markdown", query: state.retrievalQuery || "robot" });
  applyRetrievalOnboardingQueryParams(params);
  try {
    const response = await fetch(`/api/library/${state.libraryId}/retrieval/onboarding/report?${params.toString()}`);
    if (!response.ok) {
      const data = await parseJSONResponse(response);
      throw new Error(data.error || "下载接入验收报告失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] || "retrieval-onboarding-report.md";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    state.retrievalSourcesMessage = error.message;
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
  if (!bulkActionState("export-citation").enabled) return;
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

function renderPdfParseModal() {
  const panel = document.querySelector("[data-pdf-parse-modal]");
  if (!panel) return;
  const selectedCount = selectedItemKeys().length;
  const result = state.pdfParseResult || null;
  const resultRows = (result?.results || []).map((item) => {
    const attachmentRows = (item.attachments || []).map((attachment) => {
      const path = attachment.markdown_path || attachment.json_path || "";
      const status = attachment.status === "parsed" ? "已解析" : "失败";
      return `<li><strong>${escapeHtml(attachment.attachment_key || "-")}</strong> ${escapeHtml(status)} ${path ? `<small>${escapeHtml(path)}</small>` : ""}${attachment.error ? `<small>${escapeHtml(attachment.error)}</small>` : ""}</li>`;
    }).join("");
    return `<div class="import-result-row">
      <strong>${escapeHtml(item.item_key || "-")}</strong>
      <span>${escapeHtml(item.status || "")}</span>
      ${item.error ? `<small>${escapeHtml(item.error)}</small>` : ""}
      ${attachmentRows ? `<ul>${attachmentRows}</ul>` : ""}
    </div>`;
  }).join("");
  panel.innerHTML = `
    <section class="floating-card export-citation-card" data-pdf-parse-card>
      <div class="pane-head">
        <div>
          <h2>PDF 解析</h2>
          <p>已选择 ${selectedCount} 条文献，将解析其中可打开的 PDF 附件。</p>
        </div>
        <button type="button" class="icon-btn" data-close-pdf-parse>×</button>
      </div>
      <div class="bulk-modal-form">
        <p class="muted">需要先在 API 配置页填写 MinerU API Key。解析结果会保存到本地副本文库的 mineru-results/ 目录。</p>
        <div class="bulk-modal-actions">
          <button type="button" class="form-action-btn" data-submit-pdf-parse ${state.pdfParseBusy || !selectedCount ? "disabled" : ""}>${state.pdfParseBusy ? "解析中..." : "开始解析"}</button>
          <button type="button" class="ghost-btn" data-close-pdf-parse>取消</button>
        </div>
      </div>
      ${state.pdfParseMessage ? `<p class="import-message">${escapeHtml(state.pdfParseMessage)}</p>` : ""}
      ${result ? `
        <div class="import-results">
          <p>PDF ${Number(result.parsed_count || 0)} 个解析成功，${Number(result.failed_count || 0)} 个失败。结果目录：${escapeHtml(result.result_dir || "")}</p>
          ${resultRows}
        </div>
      ` : ""}
    </section>
  `;
  panel.querySelectorAll("[data-close-pdf-parse]").forEach((button) => button.addEventListener("click", closePdfParseModal));
  panel.querySelector("[data-submit-pdf-parse]")?.addEventListener("click", submitPdfParse);
}

function openPdfParseModal() {
  if (!bulkActionState("parse-pdfs").enabled) return;
  state.pdfParseMessage = "";
  state.pdfParseResult = null;
  document.querySelector("[data-pdf-parse-modal]").hidden = false;
  renderPdfParseModal();
}

function closePdfParseModal() {
  const panel = document.querySelector("[data-pdf-parse-modal]");
  if (panel) panel.hidden = true;
}

async function submitPdfParse() {
  const keys = selectedItemKeys();
  if (!keys.length) return;
  try {
    state.pdfParseBusy = true;
    state.pdfParseMessage = "";
    state.pdfParseResult = null;
    renderPdfParseModal();
    const data = await postJSON(`/api/library/${state.libraryId}/items/parse-pdfs`, { item_keys: keys });
    state.pdfParseResult = data;
    state.pdfParseMessage = "PDF 解析完成。";
  } catch (error) {
    state.pdfParseMessage = error.message;
  } finally {
    state.pdfParseBusy = false;
    renderPdfParseModal();
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
  if (!bulkActionState("delete-items").enabled) return;
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
  if (!bulkActionState("move-items").enabled) return;
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
  if (!bulkActionState("edit-attachments").enabled) return;
  const item = currentDetailItem();
  if (!item?.key) return;
  state.attachmentEditorItemKey = item.key;
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

function readerUrl(itemKey, attachmentKey) {
  const params = new URLSearchParams({ item_key: itemKey, attachment_key: attachmentKey });
  return `/library/${state.libraryId}/reader?${params.toString()}`;
}

function closeReaderPdfPickerModal() {
  const panel = document.querySelector("[data-reader-pdf-picker-modal]");
  if (panel) panel.hidden = true;
}

function renderReaderPdfPickerModal() {
  const panel = document.querySelector("[data-reader-pdf-picker-modal]");
  if (!panel) return;
  const item = state.items.find((value) => value.key === state.readerPdfPickerItemKey);
  const attachments = state.readerPdfPickerAttachments || [];
  panel.innerHTML = `
    <section class="floating-card reader-picker-card" data-reader-pdf-picker>
      <div class="pane-head">
        <div>
          <h2>选择 PDF</h2>
          <p>${escapeHtml(item?.title || state.readerPdfPickerItemKey)} · ${attachments.length} 个可打开 PDF</p>
        </div>
        <button type="button" class="icon-btn" data-close-reader-pdf-picker>×</button>
      </div>
      <form class="bulk-modal-form" data-reader-pdf-picker-form>
        <div class="reader-picker-list">
          ${attachments.map((attachment, index) => {
            const checked = (state.readerPdfPickerSelectedKey || attachments[0]?.key) === attachment.key;
            return `
              <label class="choice-row reader-picker-option">
                <input type="radio" name="attachment_key" value="${escapeHtml(attachment.key)}" ${checked ? "checked" : ""}>
                <span>
                  <strong>${escapeHtml(attachment.display_label || attachment.path || `PDF ${index + 1}`)}</strong>
                  <small>${escapeHtml(attachment.path || attachment.content_type || attachment.key)}</small>
                </span>
              </label>
            `;
          }).join("")}
        </div>
        ${state.readerPdfPickerMessage ? `<p class="import-message">${escapeHtml(state.readerPdfPickerMessage)}</p>` : ""}
        <div class="bulk-modal-actions">
          <button type="button" class="ghost-btn" data-close-reader-pdf-picker>取消</button>
          <button type="submit" class="form-action-btn">进入研读</button>
        </div>
      </form>
    </section>
  `;
  panel.querySelectorAll("[data-close-reader-pdf-picker]").forEach((button) => button.addEventListener("click", closeReaderPdfPickerModal));
  panel.querySelector("[data-reader-pdf-picker-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const attachmentKey = String(new FormData(event.currentTarget).get("attachment_key") || "").trim();
    if (!attachmentKey) {
      state.readerPdfPickerMessage = "请选择一个 PDF。";
      renderReaderPdfPickerModal();
      return;
    }
    window.location.href = readerUrl(state.readerPdfPickerItemKey, attachmentKey);
  });
}

async function openReadPaper() {
  if (!bulkActionState("read-paper").enabled) return;
  const item = currentDetailItem();
  if (!item?.key) return;
  const itemKey = item.key;
  try {
    const response = await fetch(`/api/library/${state.libraryId}/items/${itemKey}/pdf-attachments`);
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || "读取 PDF 附件失败");
    const attachments = data.attachments || [];
    if (!attachments.length) return;
    if (attachments.length === 1) {
      window.location.href = readerUrl(itemKey, attachments[0].key);
      return;
    }
    state.readerPdfPickerItemKey = itemKey;
    state.readerPdfPickerAttachments = attachments;
    state.readerPdfPickerSelectedKey = attachments[0].key;
    state.readerPdfPickerMessage = "";
    document.querySelector("[data-reader-pdf-picker-modal]").hidden = false;
    renderReaderPdfPickerModal();
  } catch (error) {
    state.readerPdfPickerItemKey = itemKey;
    state.readerPdfPickerAttachments = [];
    state.readerPdfPickerMessage = error.message || "打开文献研读失败。";
    document.querySelector("[data-reader-pdf-picker-modal]").hidden = false;
    renderReaderPdfPickerModal();
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
      const button = event.submitter || form.querySelector("button[type=\"submit\"]");
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
  setupServerPathPicker();
  setupFolderUpload();
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

const sourcePathPicker = {
  modal: null,
  input: null,
  currentPath: "",
  parentPath: "",
};
const SERVER_VIRTUAL_ROOT = "__server_root__";

function setupServerPathPicker() {
  const modal = document.querySelector("[data-server-path-modal]");
  if (!modal) return;
  sourcePathPicker.modal = modal;
  document.querySelectorAll("[data-open-server-path-picker]").forEach((button) => {
    button.addEventListener("click", () => openServerPathPicker(button));
  });
  modal.querySelector("[data-close-server-path-picker]")?.addEventListener("click", closeServerPathPicker);
  modal.querySelector("[data-server-path-up]")?.addEventListener("click", () => {
    if (sourcePathPicker.parentPath) loadServerPath(sourcePathPicker.parentPath);
  });
  modal.querySelector("[data-use-server-path]")?.addEventListener("click", () => {
    useServerPath(sourcePathPicker.currentPath);
  });
  modal.querySelector("[data-server-path-browser]")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-server-path-open]");
    if (!button) return;
    loadServerPath(button.dataset.serverPathOpen || "");
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeServerPathPicker();
  });
}

async function openServerPathPicker(button) {
  const input = document.querySelector(button.dataset.pathPickerTarget || "");
  if (!input || !sourcePathPicker.modal) return;
  sourcePathPicker.input = input;
  sourcePathPicker.modal.hidden = false;
  const initialPath = input.value.trim();
  if (initialPath) {
    try {
      await loadServerPath(initialPath);
      return;
    } catch (error) {
      setServerPathMessage(error.message);
    }
  }
  await loadServerPathRoots();
}

function closeServerPathPicker() {
  if (sourcePathPicker.modal) sourcePathPicker.modal.hidden = true;
  sourcePathPicker.input = null;
  sourcePathPicker.currentPath = "";
  sourcePathPicker.parentPath = "";
}

function useServerPath(path) {
  if (!sourcePathPicker.input || !path || path === SERVER_VIRTUAL_ROOT) return;
  sourcePathPicker.input.value = path;
  closeServerPathPicker();
}

async function loadServerPathRoots() {
  const response = await fetch("/api/server-paths/roots");
  const data = await parseJSONResponse(response);
  if (!response.ok || data.ok === false) throw new Error(data.error || "无法读取服务路径根目录");
  sourcePathPicker.currentPath = SERVER_VIRTUAL_ROOT;
  sourcePathPicker.parentPath = "";
  renderServerPathBrowser({
    title: "服务器根目录",
    containsSqlite: false,
    children: data.roots || [],
    isRootList: true,
  });
}

async function loadServerPath(path) {
  const response = await fetch(`/api/server-paths/list?path=${encodeURIComponent(path)}`);
  const data = await parseJSONResponse(response);
  if (!response.ok || data.ok === false) throw new Error(data.error || "无法读取服务目录");
  sourcePathPicker.currentPath = data.path || "";
  sourcePathPicker.parentPath = data.parent || "";
  renderServerPathBrowser({
    title: data.label || data.path || "",
    containsSqlite: Boolean(data.contains_sqlite),
    children: data.children || [],
    isRootList: Boolean(data.is_virtual_root),
  });
}

function renderServerPathBrowser({ title, containsSqlite, children, isRootList }) {
  const modal = sourcePathPicker.modal;
  if (!modal) return;
  modal.querySelector("[data-server-path-current]").textContent = title;
  modal.querySelector("[data-server-path-up]").disabled = !sourcePathPicker.parentPath;
  modal.querySelector("[data-use-server-path]").disabled = isRootList || !sourcePathPicker.currentPath || !containsSqlite;
  setServerPathMessage(containsSqlite ? "当前选择目录包含 zotero.sqlite，可以使用。" : "当前选择目录不含 zotero.sqlite。请进入下方包含 zotero.sqlite 的子目录。");
  const browser = modal.querySelector("[data-server-path-browser]");
  if (!browser) return;
  if (!children.length) {
    browser.innerHTML = `<div class="empty-state">没有可浏览的子目录。</div>`;
    return;
  }
  browser.innerHTML = children.map((child) => `
    <div class="path-entry">
      <div class="path-entry-main">
        <strong>${escapeHtml(child.label || child.name || child.path)}</strong>
        <span>${child.contains_sqlite ? "包含 zotero.sqlite" : escapeHtml(child.path)}</span>
      </div>
      <button type="button" class="path-entry-enter" data-server-path-open="${escapeHtml(child.path)}">进入子目录</button>
    </div>
  `).join("");
}

function setServerPathMessage(message) {
  const node = sourcePathPicker.modal?.querySelector("[data-server-path-message]");
  if (node) node.textContent = message || "";
}

function setupFolderUpload() {
  const probe = document.createElement("input");
  const supported = "webkitdirectory" in probe;
  document.querySelectorAll("[data-source-form][data-mode=\"local-copy\"]").forEach((form) => {
    const button = form.querySelector("[data-upload-folder]");
    const input = form.querySelector("[data-upload-folder-input]");
    const unsupported = form.querySelector("[data-folder-upload-unsupported]");
    if (!button || !input) return;
    if (!supported) {
      button.disabled = true;
      unsupported.hidden = false;
      return;
    }
    button.addEventListener("click", () => {
      input.value = "";
      input.click();
    });
    input.addEventListener("change", async () => {
      if (!input.files || !input.files.length) return;
      await uploadFolderCopy(form, Array.from(input.files));
    });
  });
}

async function uploadFolderCopy(form, files) {
  const uploadButton = form.querySelector("[data-upload-folder]");
  const submitButton = form.querySelector("button[type=\"submit\"]");
  const controls = [uploadButton, submitButton].filter(Boolean);
  controls.forEach((button) => { button.disabled = true; });
  setUploadProgress(form, 0, "准备上传...");
  try {
    const data = await sendFolderUpload(form, files);
    window.location.href = `/library/${data.library.library_id}`;
  } catch (error) {
    setUploadProgress(form, 0, error.message || "上传失败");
    window.alert(error.message || "上传失败");
  } finally {
    controls.forEach((button) => { button.disabled = false; });
  }
}

function sendFolderUpload(form, files) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    const name = String(new FormData(form).get("name") || "").trim();
    if (name) formData.append("name", name);
    files.forEach((file) => {
      formData.append("files", file, file.webkitRelativePath || file.name);
    });
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sources/upload-folder");
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        setUploadProgress(form, 0, "正在上传...");
        return;
      }
      const percent = Math.round((event.loaded / event.total) * 100);
      setUploadProgress(form, percent, `正在上传 ${percent}% · ${formatBytes(event.loaded)} / ${formatBytes(event.total)}`);
    };
    xhr.onload = () => {
      let data = null;
      const responseText = xhr.responseText || "";
      try {
        data = JSON.parse(responseText || "{}");
      } catch (error) {
        const summary = responseText.replace(/\s+/g, " ").trim().slice(0, 120);
        reject(new Error(`上传接口返回了非 JSON 内容（HTTP ${xhr.status}）：${summary || xhr.statusText || "无响应正文"}`));
        return;
      }
      if (xhr.status >= 400 || data.ok === false) {
        reject(new Error(data.error || `上传失败（HTTP ${xhr.status}）`));
        return;
      }
      setUploadProgress(form, 100, "上传完成，正在进入文库...");
      resolve(data);
    };
    xhr.onerror = () => reject(new Error("上传中断，请重试。"));
    xhr.send(formData);
  });
}

function setUploadProgress(form, percent, status) {
  const wrapper = form.querySelector("[data-upload-progress]");
  const bar = form.querySelector("[data-upload-progress-bar]");
  const text = form.querySelector("[data-upload-progress-status]");
  if (!wrapper || !bar || !text) return;
  wrapper.hidden = false;
  bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  text.textContent = status || "";
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
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
  renderBulkActionStates();
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
      <button class="column-order-btn" type="button" data-col-up="${index}" title="上移">↑</button>
      <button class="column-order-btn" type="button" data-col-down="${index}" title="下移">↓</button>
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
  const response = await fetch(`/api/library/${state.libraryId}/state`);
  const data = await parseJSONResponse(response);
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
  const unsynced = document.querySelector("[data-unsynced]");
  if (unsynced) unsynced.textContent = `未同步 ${data.library.unsynced_count || 0}`;
  applyFilters();
  renderDetail();
  rerenderActiveTagPopover();
}

async function loadRetrievalWorkspaceData() {
  await loadRetrievalRuns({ silent: true });
  if (!state.retrievalCandidates.length && state.retrievalRuns[0]?.run_id) {
    await loadRetrievalRunCandidates(state.retrievalRuns[0].run_id, { silent: true });
  }
  await loadLatestRetrievalSearchJob({ silent: true });
  await loadRetrievalSummary({ silent: true });
  await loadRetrievalSources({ silent: true });
  await loadRetrievalModelStatus({ silent: true });
  await loadRetrievalLocalPaths({ silent: true });
  await loadRetrievalHttpJsonTemplates({ silent: true });
  await loadRetrievalHttpJsonConfig({ silent: true });
  await loadRetrievalSqliteTemplates({ silent: true });
  await loadRetrievalSqliteConfig({ silent: true });
  await loadRetrievalManifestTemplates({ silent: true });
  await loadRetrievalManifestConfig({ silent: true });
  await loadRetrievalBatchJobs({ silent: true });
  await loadLatestRetrievalQueryPlanJob({ silent: true });
  await loadLatestRetrievalAiScoringJob({ silent: true });
}

function setupRetrievalPage() {
  const root = document.querySelector("[data-retrieval-page]");
  if (!root) return;
  state.libraryId = root.dataset.libraryId;
  state.addItemMode = "retrieval";
  loadState()
    .then(() => {
      renderRetrievalPage();
      return loadRetrievalWorkspaceData();
    })
    .catch((error) => window.alert(error.message));
}

function setupApiConfigPage() {
  const root = document.querySelector("[data-api-config-page]");
  if (!root) return;
  state.libraryId = root.dataset.libraryId;
  const host = document.querySelector("[data-api-config-panel]");
  host?.addEventListener("submit", (event) => {
    if (event.target.matches("[data-api-config-form]")) saveApiConfig(event);
    else if (event.target.matches("[data-mineru-config-form]")) saveMineruConfig(event);
    else if (event.target.matches("[data-codex-config-form]")) saveCodexConfig(event);
  });
  host?.addEventListener("input", (event) => {
    if (event.target.closest("[data-codex-config-form]")) syncCodexDraftFromForm();
  });
  host?.addEventListener("change", (event) => {
    if (event.target.closest("[data-codex-config-form]")) syncCodexDraftFromForm();
  });
  host?.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || !host.contains(button)) return;
    if (button.matches("[data-save-api-config]")) {
      const form = button.closest("[data-api-config-form]") || host.querySelector("[data-api-config-form]");
      if (form) saveApiConfig({ preventDefault: () => {}, currentTarget: form });
    } else if (button.matches("[data-save-mineru-config]")) {
      const form = button.closest("[data-mineru-config-form]");
      if (form) saveMineruConfig({ preventDefault: () => {}, currentTarget: form });
    } else if (button.matches("[data-save-codex-config]")) {
      const form = button.closest("[data-codex-config-form]");
      if (form) saveCodexConfig({ preventDefault: () => {}, currentTarget: form });
    } else if (button.matches("[data-toggle-api-config-secrets]")) {
      state.apiConfigShowSecrets = !state.apiConfigShowSecrets;
      loadApiConfig({ includeSecrets: apiConfigShouldIncludeSecrets() });
    } else if (button.matches("[data-toggle-mineru-config-secret]")) {
      state.apiConfigShowMineruSecret = !state.apiConfigShowMineruSecret;
      loadApiConfig({ includeSecrets: apiConfigShouldIncludeSecrets() });
    } else if (button.matches("[data-toggle-codex-config-secret]")) {
      state.apiConfigShowCodexSecrets = !state.apiConfigShowCodexSecrets;
      loadApiConfig({ includeSecrets: apiConfigShouldIncludeSecrets() });
    } else if (button.matches("[data-check-api-config]")) {
      checkApiConfig(button.dataset.checkApiConfig);
    }
  });
  loadApiConfig({ includeSecrets: false }).catch((error) => {
    state.apiConfigMessage = error.message;
    renderApiConfigPage();
  });
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
    const action = button.dataset.bulkAction;
    if (!bulkActionState(action).enabled) return;
    if (action === "add-item") openAddItemModal();
    else if (action === "delete-items") openDeleteItemsModal();
    else if (action === "move-items") openMoveItemsModal();
    else if (action === "edit-attachments") openAttachmentEditorModal();
    else if (action === "read-paper") openReadPaper();
    else if (action === "parse-pdfs") openPdfParseModal();
    else if (action === "export-citation") openCitationExportModal();
    else notifyFeatureInProgress(action);
  }));
  setupColumnsPanel();
  loadState().catch((error) => window.alert(error.message));
}

setupSourceForms();
setupLibraryPage();
setupRetrievalPage();
setupApiConfigPage();
