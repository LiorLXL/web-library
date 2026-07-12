/* 综述写作前端逻辑（搬运自 guangming-ai-workbench，适配 web-library 文库路由）。
 * 自带 escapeHtml / renderMarkdown，不依赖外部 markdown 库。 */

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}

/* 轻量 markdown 渲染（代码块 / 标题 / 列表 / 加粗 / 行内代码 / 段落），无需外部库。 */
function renderMarkdown(source) {
  const text = String(source || "");
  const lines = text.split("\n");
  const blocks = [];
  let paragraph = [];
  let inCode = false;
  let codeBuffer = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${escapeHtml(paragraph.join(" ")).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</p>`);
    paragraph = [];
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (line.startsWith("```")) {
      if (!inCode) {
        flushParagraph();
        inCode = true;
        codeBuffer = [];
      } else {
        blocks.push(`<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
        inCode = false;
      }
      continue;
    }
    if (inCode) {
      codeBuffer.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      blocks.push(`<h${level}>${escapeHtml(heading[2])}</h${level}>`);
      continue;
    }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) {
      flushParagraph();
      blocks.push(`<ul><li>${escapeHtml(li[1]).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</li></ul>`);
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  if (inCode) blocks.push(`<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
  return blocks.join("\n");
}

(function () {
  const writingWorkbench = document.querySelector("[data-writing-workbench]");
  if (!writingWorkbench) return;

  const stageOrder = ["topic", "outline", "mapping", "draft"];
  const stageStrip = document.querySelector("[data-writing-stage-strip]");
  const stageUrl = stageStrip?.dataset.stageUrl || "";
  const stageNodes = Array.from(document.querySelectorAll("[data-writing-stage]"));
  const stagePanels = Array.from(document.querySelectorAll("[data-writing-stage-panel]"));
  const paperList = writingWorkbench.querySelector("[data-writing-paper-list]");
  const matrixPreview = writingWorkbench.querySelector("[data-writing-matrix-preview]");
  const sectionMap = writingWorkbench.querySelector("[data-writing-section-map]");
  const outlineEditor = writingWorkbench.querySelector("[data-writing-outline]");
  const outlinePreview = writingWorkbench.querySelector("[data-writing-outline-preview]");
  const draftEditor = writingWorkbench.querySelector("[data-writing-draft]");
  const draftPreview = writingWorkbench.querySelector("[data-writing-draft-preview]");
  const chatForm = writingWorkbench.querySelector("[data-writing-chat-form]");
  const chatWindow = writingWorkbench.querySelector("[data-writing-chat-window]");
  const quickRow = writingWorkbench.querySelector("[data-writing-quick-row]");
  const chatTextarea = chatForm?.querySelector("textarea");
  const chatSubmitButton = chatForm?.querySelector(".writing-chat-controls .send-btn");
  const compactButton = chatForm?.querySelector("[data-compact-writing-chat]");
  const kbSelect = writingWorkbench.querySelector("[data-writing-kb-select]");
  const matrixByPaper = JSON.parse(writingWorkbench.dataset.matrix || "{}");
  const knowledgeBases = JSON.parse(writingWorkbench.dataset.knowledgeBases || "[]");
  const papersByKb = JSON.parse(writingWorkbench.dataset.papersByKb || "{}");
  let currentKbId = "";
  let writingMapping = JSON.parse(writingWorkbench.dataset.writingMapping || '{"sections":[],"papers":[],"mappings":[]}');
  const writingLibraryId = writingWorkbench.dataset.libraryId || "";
  const writingTopicUrl = writingWorkbench.dataset.topicUrl || "";
  const splitStoreKey = "guangming-writing-split-width";
  let currentStage = writingWorkbench.dataset.currentStage || "topic";
  let writingPollTimer = null;

  const writingStagePrompts = {
    topic: {
      placeholder: "这个阶段主要和 AI 讨论综述主题。可以说：我想突出机器人操作、双臂协同或 VLA 泛化能力，也可以让 AI 判断当前文献够不够支撑主题。",
      quicks: [
        ["拟定主题", "请基于当前已选文献和文献矩阵，帮我拟定一个合适的文献综述主题，并说明为什么这个主题适合当前材料。"],
        ["比较主题方向", "请给我比较 3-4 个可选综述主题方向，说明每个方向的覆盖范围、风险和适合的写作角度。"],
        ["判断文献是否够", "请判断当前已选文献是否足够支撑一个完整综述主题；如果不够，请明确缺口，并给出可复制到文献检索页的完整检索要求。"],
        ["推荐矩阵字段", "请基于当前文献和拟定主题，判断是否需要新增文献矩阵字段；如果需要，请说明原因、字段名、判断依据和格式要求。"],
      ],
    },
    outline: {
      placeholder: "这个阶段主要打磨大纲。可以说明目标篇幅、课程报告或学术综述风格、希望突出的方法链路，以及你想采用的一二级结构。",
      quicks: [
        ["短篇大纲", "请基于当前主题、CSV 和已有大纲，生成一版短篇综述大纲，适合 3000-5000 字，包含一级和二级标题。"],
        ["中篇大纲", "请生成一版中篇综述大纲，适合 6000-9000 字，要求结构清晰、章节之间有递进关系，并说明每章写作重点。"],
        ["长篇大纲", "请生成一版长篇综述大纲，适合 10000 字以上，要求覆盖研究背景、方法分类、实验评估、应用场景、挑战与展望。"],
        ["课程报告大纲", "请按课程报告风格优化当前大纲，要求逻辑清楚、重点突出、篇幅可控，并给出每节建议字数。"],
        ["学术综述大纲", "请按正式学术综述风格优化当前大纲，突出分类体系、研究脉络、关键问题和未来方向。"],
      ],
    },
    mapping: {
      placeholder: "这个阶段主要核对每个章节该引用哪些论文。可以让 AI 分配文献、指出缺少证据的章节，或补写每篇论文在对应章节中的写作备注。",
      quicks: [
        ["分配文献", "请根据当前大纲、writing_sources.csv、文献矩阵，逐小节分配文献，并生成每篇文献在对应小节的写作内容备注、证据细节和缺失细节。"],
        ["检查缺口", "请检查当前小节-文献映射是否存在证据不足、章节空洞或文献过度集中的问题，并给出补充检索建议。"],
        ["生成写作备注", "请围绕当前小节-文献映射补强写作内容备注，尽量指出具体方法、实验细节、数据或仍需从资料补查的内容。"],
        ["优化引用布局", "请优化各小节引用布局，避免同一篇文献被过度使用，同时保证核心章节有足够代表性论文支撑。"],
      ],
    },
    draft: {
      placeholder: "这个阶段主要生成或修改本地 survey.md。可以说明要先写哪一节、目标字数、引用风格，或要求 AI 直接更新 Markdown 正文。",
      quicks: [
        ["开始撰写综述", "请基于当前主题、CSV、文献矩阵和大纲，开始撰写本地 survey.md。不要在聊天框输出完整正文，只说明写入了哪些部分。"],
        ["生成引言", "请先撰写 survey.md 的引言部分，要求说明研究背景、问题动机、综述范围和本文结构。"],
        ["生成相关工作", "请根据当前大纲和文献分配，撰写相关工作与方法分类部分，并使用数字引用格式。"],
        ["润色全文", "请检查并润色当前 survey.md，重点优化段落衔接、学术表达、引用位置和章节过渡。"],
        ["补参考文献", "请检查 survey.md 末尾参考文献列表，确保正文数字引用和参考文献条目一致。"],
      ],
    },
  };

  const updateWritingStageHelpers = () => {
    const config = writingStagePrompts[currentStage] || writingStagePrompts.topic;
    if (chatTextarea) chatTextarea.placeholder = config.placeholder;
    if (quickRow) {
      quickRow.innerHTML = config.quicks.map(([label, prompt]) => `
        <button type="button" data-writing-quick="${escapeAttribute(prompt)}">${escapeHtml(label)}</button>
      `).join("");
    }
  };

  const activePaperIds = () => Array.from(paperList?.querySelectorAll("input:checked") || []).map((input) => input.value);

  const setWritingStage = async (stage, persist = true) => {
    if (!stageOrder.includes(stage)) return;
    currentStage = stage;
    writingWorkbench.dataset.currentStage = stage;
    stageNodes.forEach((node) => node.classList.toggle("active", node.dataset.writingStage === stage));
    stagePanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.writingStagePanel === stage));
    updateWritingStageHelpers();
    // 切换到对应阶段时重新渲染面板预览
    if (stage === "outline") renderOutlinePreview();
    if (stage === "draft") renderDraftPreview();
    if (persist && stageUrl) {
      await fetch(stageUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ stage }),
      });
    }
  };

  const renderWritingMatrix = (paperId) => {
    if (!matrixPreview) return;
    const values = matrixByPaper[paperId] || {};
    const entries = Object.entries(values);
    if (!entries.length) {
      matrixPreview.innerHTML = '<div class="empty-state compact">该文献尚未生成文献矩阵。</div>';
      return;
    }
    matrixPreview.innerHTML = entries.map(([name, value]) => `
      <article class="reading-matrix-item">
        <span>${escapeHtml(name)}</span>
        <p>${escapeHtml(value || "尚未生成")}</p>
      </article>
    `).join("");
  };

  const paperTitleById = {};
  const rawPapers = JSON.parse(document.querySelector("[data-writing-workbench]")?.dataset.papers || "[]");
  rawPapers.forEach((paper) => { paperTitleById[paper.key] = paper.title; });
  // 服务端已把 papers 列表序列化到 data-papers，便于按知识库过滤渲染。
  const papersForKb = (kbId) => {
    const keys = (papersByKb[kbId] || []).slice();
    const seen = new Set();
    const out = [];
    keys.forEach((key) => {
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ key, title: paperTitleById[key] || key });
    });
    return out;
  };

  const renderPaperList = () => {
    if (!paperList) return;
    const selected = new Set(JSON.parse(writingWorkbench.dataset.selected || "[]"));
    if (!knowledgeBases.length) {
      paperList.innerHTML = '<div class="empty-state compact">还没有知识库，请先在"知识库"中创建。</div>';
      return;
    }
    if (!currentKbId) {
      paperList.innerHTML = '<div class="empty-state compact">请先选择一个知识库查看其文献。</div>';
      return;
    }
    const papers = papersForKb(currentKbId);
    if (!papers.length) {
      paperList.innerHTML = '<div class="empty-state compact">当前知识库下还没有文献条目。</div>';
      return;
    }
    paperList.innerHTML = papers.map((paper) => `
      <label class="writing-paper-row" data-writing-paper-row data-paper-id="${escapeAttribute(paper.key)}">
        <input type="checkbox" value="${escapeAttribute(paper.key)}" ${selected.has(paper.key) ? "checked" : ""}>
        <span>${escapeHtml(paper.title)}</span>
      </label>
    `).join("");
    const first = paperList.querySelector("input:checked") || paperList.querySelector("input");
    if (first) renderWritingMatrix(first.value);
  };


  const renderWritingKbSelect = () => {
    if (!kbSelect) return;
    kbSelect.value = currentKbId || "";
  };
  if (kbSelect) {
    kbSelect.addEventListener("change", () => {
      currentKbId = kbSelect.value || "";
      renderPaperList();
    });
  }


  const renderWritingSectionMap = (mapping) => {
    if (!sectionMap || !mapping) return;
    writingMapping = mapping;
    const sections = Array.isArray(mapping.sections) ? mapping.sections : [];
    const mappings = Array.isArray(mapping.mappings) ? mapping.mappings : [];
    if (!sections.length) {
      sectionMap.innerHTML = '<div class="empty-state compact">当前大纲还没有可识别章节。请先在第二阶段生成并保存大纲。</div>';
      return;
    }
    sectionMap.innerHTML = sections.map((section) => `
      <article class="writing-section-card" data-outline-section="${escapeAttribute(section.title || "")}">
        <div class="writing-section-title-row">
          <h3>${escapeHtml(section.title || "未命名章节")}</h3>
          <span>${mappings.filter((row) => row.section_id === section.section_id).length} 篇文献</span>
        </div>
        ${(() => {
          const rows = mappings.filter((row) => row.section_id === section.section_id);
          if (!rows.length) return '<div class="empty-state compact">本小节尚未分配文献。运行“分配文献”后会在这里生成小节级写作备注。</div>';
          return rows.map((row) => `
            <div class="writing-map-row is-mapped" data-map-id="${escapeAttribute(row.mapping_id || "")}" data-map-section-id="${escapeAttribute(row.section_id || "")}" data-map-paper-id="${escapeAttribute(row.paper_id || row.paper_key || "")}">
              <div class="writing-map-paper">
                <strong>${escapeHtml(row.paper_title || "")}</strong>
                <button class="icon-action-btn danger" type="button" data-delete-section-mapping title="移除该小节中的文献">×</button>
              </div>
              <label>
                <span>引用角色</span>
                <input data-map-field="citation_role" value="${escapeAttribute(row.citation_role || "")}" placeholder="核心证据 / 方法对比 / 实验支撑">
              </label>
              <label>
                <span>写作内容备注</span>
                <textarea data-map-field="writing_note" placeholder="这篇文献在本小节中具体写什么">${escapeHtml(row.writing_note || "")}</textarea>
              </label>
              <label>
                <span>证据细节</span>
                <textarea data-map-field="evidence_detail" placeholder="可写入正文的真实方法、实验、数据或论据细节">${escapeHtml(row.evidence_detail || "")}</textarea>
              </label>
              <label>
                <span>缺失细节</span>
                <textarea data-map-field="missing_detail" placeholder="仍需从 PDF 或资料补查的内容">${escapeHtml(row.missing_detail || "")}</textarea>
              </label>
            </div>
          `).join("");
        })()}
      </article>
    `).join("");
  };

  const saveWritingSelection = async (activePaperId = "") => {
    if (!paperList?.dataset.selectionUrl) return;
    const response = await fetch(paperList.dataset.selectionUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ paper_keys: activePaperIds(), active_paper_id: activePaperId }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "selection save failed");
  };

  paperList?.addEventListener("change", async (event) => {
    const input = event.target.closest("input[type='checkbox']");
    if (!input) return;
    try {
      await saveWritingSelection(input.value);
    } catch (error) {
      window.alert(error.message || "保存写作文献选择失败。");
    }
  });

  paperList?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-writing-paper-row]");
    if (!row) return;
    renderWritingMatrix(row.dataset.paperId);
  });

  try {
    renderWritingKbSelect();
    renderPaperList();
  } catch (error) {
    console.error("初始化知识库/文献列表失败", error);
  }

  stageNodes.forEach((node) => node.addEventListener("click", () => setWritingStage(node.dataset.writingStage)));
  document.querySelector("[data-writing-prev-stage]")?.addEventListener("click", () => {
    const index = Math.max(0, stageOrder.indexOf(currentStage) - 1);
    setWritingStage(stageOrder[index]);
  });
  document.querySelector("[data-writing-next-stage]")?.addEventListener("click", () => {
    const index = Math.min(stageOrder.length - 1, stageOrder.indexOf(currentStage) + 1);
    setWritingStage(stageOrder[index]);
  });

  const renderOutlinePreview = () => {
    if (!outlinePreview || !outlineEditor) return;
    outlinePreview.innerHTML = renderMarkdown(outlineEditor.value || "");
    outlinePreview.querySelectorAll("a").forEach((link) => {
      link.target = "_blank";
      link.rel = "noreferrer";
    });
  };

  const setOutlineMode = (mode) => {
    const preview = mode !== "edit";
    if (preview) renderOutlinePreview();
    if (outlineEditor) outlineEditor.hidden = preview;
    if (outlinePreview) outlinePreview.hidden = !preview;
  };

  document.querySelectorAll("[data-writing-outline-mode]").forEach((button) => {
    button.addEventListener("click", () => setOutlineMode(button.dataset.writingOutlineMode || "preview"));
  });

  document.querySelector("[data-save-writing-outline]")?.addEventListener("click", async () => {
    try {
      const response = await fetch(outlineEditor.dataset.outlineUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ text: outlineEditor.value }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "outline save failed");
      renderOutlinePreview();
      if (payload.mapping) renderWritingSectionMap(payload.mapping);
      window.alert("大纲已保存。");
    } catch (error) {
      window.alert(error.message || "保存大纲失败。");
    }
  });

  document.querySelector("[data-save-writing-mappings]")?.addEventListener("click", async (event) => {
    try {
      const mappings = [];
      writingWorkbench.querySelectorAll("[data-map-paper-id]").forEach((row) => {
        const paperId = row.dataset.mapPaperId;
        const sectionId = row.dataset.mapSectionId;
        if (!paperId || !sectionId) return;
        const valueFor = (field) => row.querySelector(`[data-map-field="${field}"]`)?.value.trim() || "";
        mappings.push({
          section_id: sectionId,
          paper_id: paperId,
          citation_role: valueFor("citation_role"),
          writing_note: valueFor("writing_note"),
          evidence_detail: valueFor("evidence_detail"),
          missing_detail: valueFor("missing_detail"),
        });
      });
      const response = await fetch(event.currentTarget.dataset.mappingsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ mappings }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "mapping save failed");
      if (payload.mapping) renderWritingSectionMap(payload.mapping);
      window.alert("内容核对已保存并同步小节-文献映射。");
    } catch (error) {
      window.alert(error.message || "保存内容核对失败。");
    }
  });

  sectionMap?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-section-mapping]");
    if (!button) return;
    button.closest("[data-map-paper-id]")?.remove();
  });

  const renderDraftPreview = () => {
    if (!draftPreview || !draftEditor) return;
    draftPreview.innerHTML = renderMarkdown(draftEditor.value || "");
    draftPreview.querySelectorAll("a").forEach((link) => {
      link.target = "_blank";
      link.rel = "noreferrer";
    });
  };

  document.querySelectorAll("[data-writing-draft-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      const preview = button.dataset.writingDraftMode === "preview";
      if (preview) renderDraftPreview();
      if (draftEditor) draftEditor.hidden = preview;
      if (draftPreview) draftPreview.hidden = !preview;
    });
  });

  document.querySelector("[data-save-writing-draft]")?.addEventListener("click", async () => {
    try {
      const response = await fetch(draftEditor.dataset.draftUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ text: draftEditor.value }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "draft save failed");
      window.alert("综述 Markdown 已保存。");
    } catch (error) {
      window.alert(error.message || "保存综述 Markdown 失败。");
    }
  });

  const hasWritingActions = (actions) => {
    if (!actions || typeof actions !== "object") return false;
    return ["topic_options", "search_prompts", "matrix_field_suggestions"].some((key) => Array.isArray(actions[key]) && actions[key].length);
  };

  const renderWritingActions = (actions) => {
    if (!hasWritingActions(actions)) return "";
    const topicItems = actions.topic_options || [];
    const topics = topicItems.length ? `
      <div class="writing-topic-choice-card">
        <div class="writing-topic-choice-head">
          <strong>选择综述主题</strong>
          <span>点击一个选项即可记录为当前主题</span>
        </div>
        <div class="writing-topic-choice-list">
          ${topicItems.map((item) => `
            <button type="button" class="writing-topic-option" data-select-writing-topic="${escapeAttribute(item.title || "")}">
              <span class="topic-option-id">${escapeHtml(item.id || "选")}</span>
              <span class="topic-option-main">
                <strong>${escapeHtml(item.title || "")}</strong>
                ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
              </span>
            </button>
          `).join("")}
        </div>
        <div class="writing-topic-custom">
          <input type="text" data-writing-custom-topic placeholder="或者输入你自己的主题">
          <button type="button" class="writing-action-btn" data-select-writing-topic-custom>采用其他主题</button>
        </div>
      </div>
    ` : "";
    const search = (actions.search_prompts || []).map((item) => `
      <button type="button" class="writing-action-btn primary" data-jump-writing-search="${escapeAttribute(item.request || "")}">
        跳转检索${item.label ? `：${escapeHtml(item.label)}` : ""}
      </button>
    `).join("");
    const matrixFields = actions.matrix_field_suggestions || [];
    const matrix = matrixFields.length ? `
      <button type="button" class="writing-action-btn matrix" data-jump-writing-matrix="${escapeAttribute(JSON.stringify(matrixFields))}">
        跳转文献矩阵：新增 ${matrixFields.length} 个字段
      </button>
    ` : "";
    const jumps = search || matrix ? `<div class="writing-jump-actions">${search}${matrix}</div>` : "";
    return `<div class="writing-action-panel">${jumps}${topics}</div>`;
  };

  const hydrateWritingActionPanels = () => {
    chatWindow?.querySelectorAll("[data-writing-actions]").forEach((panel) => {
      try {
        const actions = JSON.parse(panel.dataset.writingActions || "{}");
        panel.outerHTML = renderWritingActions(actions);
      } catch (_error) {
        panel.remove();
      }
    });
  };

  const renderWritingMessage = (message) => {
    if (message.role === "divider") return `<div class="chat-divider"><span>${escapeHtml(message.content || "新的对话")}</span></div>`;
    const isUser = message.role === "user";
    const content = isUser ? `<p>${escapeHtml(message.content || "")}</p>` : `<div class="markdown-body">${renderMarkdown(message.content || "")}</div>`;
    const actions = !isUser ? renderWritingActions(message.actions || {}) : "";
    return `
      <article class="chat-message ${isUser ? "user" : "assistant"}">
        <div class="chat-avatar">${isUser ? "我" : "光"}</div>
        <div class="chat-bubble">
          <div class="chat-meta">
            <span>${isUser ? "我的问题" : "综述写作"}</span>
            <time>${escapeHtml(message.created_at || "")}</time>
          </div>
          ${content}
          ${actions}
        </div>
      </article>
    `;
  };

  const renderWritingRunning = (task) => task ? `
    <article class="chat-message assistant running">
      <div class="chat-avatar">光</div>
      <div class="chat-bubble">
        <div class="chat-meta"><span>综述写作</span><time>${escapeHtml(task.started_at || "")}</time></div>
        <p>正在处理当前阶段任务。</p>
        ${task.total_sections ? `
          <div class="matrix-progress-head">
            <strong>${task.current_section ? `当前小节：${escapeHtml(task.current_section)}` : "正在生成小节-文献映射"}</strong>
            <span>${task.completed_sections || 0} / ${task.total_sections || 0}</span>
          </div>
          <div class="matrix-progress-bar"><span style="width:${Math.round(((task.completed_sections || 0) / (task.total_sections || 1)) * 100)}%"></span></div>
        ` : ""}
        <div class="chat-result-line loading-line"><span class="loading-dot"></span>写作中，请稍候</div>
        <div class="task-event-list">${Array.isArray(task.events) ? task.events.slice(-8).map((event) => `<div class="task-event-item">${escapeHtml(event.message || "")}</div>`).join("") : ""}</div>
      </div>
    </article>
  ` : "";

  const renderWritingChat = (messages, task = null) => {
    if (!chatWindow) return;
    if ((!messages || !messages.length) && !task) {
      chatWindow.innerHTML = '<div class="chat-empty"><strong>开始综述写作</strong><span>可以先从“帮我拟定一个合适的文献综述主题”开始。</span></div>';
      return;
    }
    chatWindow.innerHTML = [...(messages || []).map(renderWritingMessage), renderWritingRunning(task)].join("");
    hydrateWritingActionPanels();
    chatWindow.scrollTop = chatWindow.scrollHeight;
  };

  const setWritingBusy = (busy) => {
    if (chatSubmitButton) {
      chatSubmitButton.disabled = false;
      if (busy) {
        chatSubmitButton.type = "button";
        chatSubmitButton.classList.add("stop-send-btn");
        chatSubmitButton.setAttribute("data-stop-writing-chat", "");
        chatSubmitButton.innerHTML = '<span class="stop-icon"></span>';
      } else {
        chatSubmitButton.type = "submit";
        chatSubmitButton.classList.remove("stop-send-btn");
        chatSubmitButton.removeAttribute("data-stop-writing-chat");
        chatSubmitButton.textContent = "➤";
      }
    }
    if (chatTextarea) chatTextarea.readOnly = busy;
    if (compactButton) compactButton.disabled = busy;
  };

  const pollWritingStatus = async () => {
    try {
      const response = await fetch(chatForm.dataset.statusUrl, { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      console.log("[writing status]", {
        running: payload.running,
        outline_payload_len: (payload.outline || "").length,
        editor_len: (outlineEditor?.value || "").length,
        _debug: {
          outline_path: payload._debug_outline_path,
          exists: payload._debug_outline_exists,
          file_size: payload._debug_outline_len,
        }
      });
      renderWritingChat(payload.messages || [], payload.running ? payload.latest : null);

      // 无条件同步左侧面板——AI 可能在任务执行中途就写入了文件
      if (outlineEditor) {
        const nextOutline = payload.outline == null ? "" : String(payload.outline);
        if (outlineEditor.value !== nextOutline) {
          outlineEditor.value = nextOutline;
          console.log("[writing status] outline updated, new len:", nextOutline.length);
        }
      }
      if (draftEditor) {
        const nextDraft = payload.draft == null ? "" : String(payload.draft);
        if (draftEditor.value !== nextDraft) draftEditor.value = nextDraft;
      }
      if (payload.mapping) renderWritingSectionMap(payload.mapping);
      renderOutlinePreview();
      renderDraftPreview();

      if (!payload.running) {
        window.clearInterval(writingPollTimer);
        writingPollTimer = null;
        setWritingBusy(false);
      }
    } catch (err) {
      console.error("[writing status] poll failed:", err);
    }
  };

  const startWritingPolling = () => {
    if (writingPollTimer) return;
    pollWritingStatus();  // 立即执行一次，不等 timer 间隔
    writingPollTimer = window.setInterval(pollWritingStatus, 500);
  };

  chatForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = chatTextarea?.value.trim() || "";
    if (!question) {
      window.alert("请输入综述写作任务。");
      return;
    }
    setWritingBusy(true);
    try {
      const response = await fetch(chatForm.action, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ user_question: question, stage: currentStage }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "writing chat failed");
      if (chatTextarea) chatTextarea.value = "";
      renderWritingChat(payload.messages || [payload.user_message].filter(Boolean), {
        run_id: payload.run_id,
        status: "running",
        started_at: "",
      });
      startWritingPolling();
    } catch (error) {
      setWritingBusy(false);
      window.alert(error.message || "提交综述写作任务失败。");
    }
  });

  chatForm?.addEventListener("click", async (event) => {
    const stop = event.target.closest("[data-stop-writing-chat]");
    if (!stop) return;
    event.preventDefault();
    const response = await fetch(chatForm.dataset.stopUrl, { method: "POST", headers: { Accept: "application/json", "X-Requested-With": "fetch" } });
    const payload = await response.json();
    renderWritingChat(payload.messages || []);
    setWritingBusy(false);
    if (writingPollTimer) window.clearInterval(writingPollTimer);
    writingPollTimer = null;
  });

  chatWindow?.addEventListener("click", async (event) => {
    const searchButton = event.target.closest("[data-jump-writing-search]");
    if (searchButton) {
      const request = searchButton.dataset.jumpWritingSearch || "";
      if (writingLibraryId && request) {
        window.localStorage.setItem(`guangming-search-prefill:${writingLibraryId}`, JSON.stringify({ request, mode: "quick" }));
      }
      window.location.href = writingWorkbench.dataset.searchUrl || "/";
      return;
    }
    const matrixButton = event.target.closest("[data-jump-writing-matrix]");
    if (matrixButton) {
      try {
        const fields = JSON.parse(matrixButton.dataset.jumpWritingMatrix || "[]");
        if (writingLibraryId && fields.length) {
          window.localStorage.setItem(`guangming-matrix-field-drafts:${writingLibraryId}`, JSON.stringify({ fields, source: "综述写作建议" }));
        }
      } catch (_error) {
        // Ignore malformed action payloads.
      }
      window.location.href = writingWorkbench.dataset.libraryUrl || "/";
      return;
    }
    const topicButton = event.target.closest("[data-select-writing-topic]");
    const customButton = event.target.closest("[data-select-writing-topic-custom]");
    if (!topicButton && !customButton) return;
    const customInput = customButton?.closest(".writing-topic-custom")?.querySelector("[data-writing-custom-topic]");
    const topic = customButton ? customInput?.value : topicButton.dataset.selectWritingTopic;
    if (!topic?.trim() || !writingTopicUrl) return;
    try {
      const response = await fetch(writingTopicUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ topic: topic.trim() }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "topic save failed");
      const topicDisplay = writingWorkbench.querySelector("[data-writing-topic-display]");
      if (topicDisplay) {
        topicDisplay.textContent = `已选主题：${payload.topic}`;
        topicDisplay.classList.remove("is-empty");
      }
      renderWritingChat(payload.messages || []);
    } catch (error) {
      window.alert(error.message || "保存综述主题失败。");
    }
  });

  compactButton?.addEventListener("click", async () => {
    if (!window.confirm("确定要压缩当前综述写作对话记忆吗？压缩完成后会继续沿用当前线程。")) return;
    const originalText = compactButton.textContent;
    compactButton.disabled = true;
    compactButton.textContent = "压缩中...";
    try {
      const response = await fetch(chatForm.dataset.compactUrl, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "compact failed");
      if (writingPollTimer) window.clearInterval(writingPollTimer);
      writingPollTimer = null;
      setWritingBusy(false);
      renderWritingChat(payload.messages || []);
    } catch (error) {
      window.alert(error.message || "压缩综述写作对话记忆失败。");
    } finally {
      compactButton.disabled = false;
      compactButton.textContent = originalText || "压缩记忆";
    }
  });

  document.querySelector("[data-reset-writing-chat]")?.addEventListener("click", async () => {
    if (!window.confirm("确定要完全重置写作区吗？这将清空主题、大纲、章节映射和综述正文，重新开始。")) return;
    const response = await fetch(chatForm.dataset.resetUrl, { method: "POST", headers: { Accept: "application/json", "X-Requested-With": "fetch" } });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      window.alert(payload.error || "重置综述写作对话失败。");
      return;
    }
    // 完全重置后刷新页面以同步所有 UI 状态
    window.location.reload();
  });

  quickRow?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-writing-quick]");
    if (!button) return;
    if (chatTextarea) chatTextarea.value = button.dataset.writingQuick || "";
    chatTextarea?.focus();
  });

  updateWritingStageHelpers();
  renderWritingSectionMap(writingMapping);
  setOutlineMode("preview");
  hydrateWritingActionPanels();

  const savedWidth = window.localStorage.getItem(splitStoreKey);
  if (savedWidth) writingWorkbench.style.setProperty("--writing-left-width", `${savedWidth}px`);
  writingWorkbench.querySelector("[data-writing-resizer]")?.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const rect = writingWorkbench.getBoundingClientRect();
    writingWorkbench.classList.add("is-resizing");
    const onMove = (moveEvent) => {
      const width = Math.min(Math.max(360, moveEvent.clientX - rect.left), rect.width - 420);
      writingWorkbench.style.setProperty("--writing-left-width", `${Math.round(width)}px`);
      window.localStorage.setItem(splitStoreKey, String(Math.round(width)));
    };
    const onUp = () => {
      writingWorkbench.classList.remove("is-resizing");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });

  if (document.querySelector(".writing-chat-pane .chat-message.running")) {
    setWritingBusy(true);
    startWritingPolling();
  }
})();
