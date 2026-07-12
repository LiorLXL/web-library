// 单篇文献研读对话：异步任务 + 轮询 + 停止 + 图片粘贴/上传。
// 复用 reader.js 中的 readerState（libraryId / itemKey）。
(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
    })[char]);
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
  }

  // 轻量 markdown：代码块、加粗、行内代码、列表、段落。
  function renderMarkdown(source) {
    const text = String(source || "");
    const lines = text.split("\n");
    const blocks = [];
    let paragraph = [];
    let inCode = false;
    let codeBuffer = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      const content = paragraph.join(" ").trim();
      if (content) blocks.push(`<p>${inlineMd(escapeHtml(content))}</p>`);
      paragraph = [];
    };

    for (const rawLine of lines) {
      const line = rawLine.replace(/\s+$/, "");
      if (line.startsWith("```")) {
        if (!inCode) {
          flushParagraph();
          inCode = true;
          codeBuffer = [];
        } else {
          inCode = false;
          blocks.push(`<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`);
          codeBuffer = [];
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
      if (/^[#*>\-]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
        flushParagraph();
        if (/^#+\s+/.test(line)) {
          const level = line.match(/^#+/)[0].length;
          blocks.push(`<h${level}>${inlineMd(escapeHtml(line.replace(/^#+\s+/, "")))}</h${level}>`);
        } else if (/^>\s+/.test(line)) {
          blocks.push(`<blockquote>${inlineMd(escapeHtml(line.replace(/^>\s+/, "")))}</blockquote>`);
        } else {
          const item = inlineMd(escapeHtml(line.replace(/^(\d+\.|[-*])\s+/, "")));
          blocks.push(`<li>${item}</li>`);
        }
        continue;
      }
      paragraph.push(line);
    }
    flushParagraph();
    return blocks.join("\n");
  }

  function inlineMd(text) {
    return text
      .replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => `<a href="${escapeAttribute(href)}" target="_blank" rel="noreferrer">${label}</a>`);
  }

  const form = document.querySelector("[data-reading-chat-form]");
  if (!form) return;

  // 是否已选中某篇文献：由后端模板注入的 data-status-url 决定，
  // 不依赖 reader.js 内部的模块级 readerState。
  function readingChatReady() {
    return Boolean(form.dataset.statusUrl);
  }

  const chatWindow = document.querySelector("[data-reading-chat-window]");
  const textarea = form.querySelector("textarea");
  const submitButton = form.querySelector(".reading-chat-controls .send-btn");
  const screenshotButton = form.querySelector("[data-start-reading-screenshot]");
  const resetButton = form.querySelector("[data-reset-reading-chat]");
  const attachmentTray = form.querySelector("[data-reading-attachment-tray]");

  let pollTimer = null;
  let attachments = [];

  function scrollToBottom() {
    if (chatWindow) chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function renderMessage(message) {
    if (message.role === "divider") {
      return `<div class="chat-divider"><span>${escapeHtml(message.content || "新的对话")}</span></div>`;
    }
    const isUser = message.role === "user";
    const attachmentHtml = Array.isArray(message.attachments) && message.attachments.length
      ? `<div class="chat-attachment-row">${message.attachments
          .filter((a) => a.type === "image" && a.url)
          .map((a) => `<a class="chat-image-thumb" href="${escapeAttribute(a.url)}" target="_blank" title="查看截图"><img src="${escapeAttribute(a.url)}" alt="用户附加截图"></a>`)
          .join("")}</div>`
      : "";
    const body = isUser
      ? `${attachmentHtml}<p>${escapeHtml(message.content || "")}</p>`
      : `<div class="markdown-body">${renderMarkdown(message.content || "")}</div>`;
    return `
      <article class="chat-message ${isUser ? "user" : "assistant"}">
        <div class="chat-avatar">${isUser ? "我" : "读"}</div>
        <div class="chat-bubble">
          <div class="chat-meta">
            <span>${isUser ? "我的问题" : "文献研读"}</span>
            <time>${escapeHtml(message.created_at || "")}</time>
          </div>
          ${body}
        </div>
      </article>
    `;
  }

  function renderRunning(task) {
    if (!task) return "";
    const events = Array.isArray(task.events)
      ? task.events.slice(-6).map((e) => `<div class="task-event-item">${escapeHtml(e.message || "")}</div>`).join("")
      : "";
    return `
      <article class="chat-message assistant running">
        <div class="chat-avatar">读</div>
        <div class="chat-bubble">
          <div class="chat-meta">
            <span>文献研读</span>
            <time>${escapeHtml(task.started_at || "")}</time>
          </div>
          <p>正在围绕当前文献回答问题。</p>
          <div class="chat-result-line loading-line">
            <span class="loading-dot"></span>
            问答中，请稍候
          </div>
          <div class="task-event-list">${events}</div>
        </div>
      </article>
    `;
  }

  function renderChat(messages, task) {
    if (!chatWindow) return;
    if ((!messages || !messages.length) && !task) {
      chatWindow.innerHTML = `
        <div class="chat-empty">
          <strong>开始和这篇文献对话</strong>
          <span>可以问“这篇文献的核心贡献是什么？”、“实验设置怎么理解？”，或截图/粘贴一张图片辅助提问。</span>
        </div>`;
      return;
    }
    chatWindow.innerHTML = [
      ...(messages || []).map(renderMessage),
      task && task.status === "running" ? renderRunning(task) : "",
    ].join("");
    scrollToBottom();
  }

  function setBusy(busy) {
    if (submitButton) {
      submitButton.disabled = busy;
      if (busy) {
        submitButton.classList.add("stop-send-btn");
        submitButton.setAttribute("data-stop-reading-chat", "");
        submitButton.innerHTML = '<span class="stop-icon"></span>';
      } else {
        submitButton.classList.remove("stop-send-btn");
        submitButton.removeAttribute("data-stop-reading-chat");
        submitButton.textContent = "➤";
      }
    }
    if (textarea) textarea.readOnly = busy;
    if (screenshotButton) screenshotButton.disabled = busy;
    if (resetButton) resetButton.disabled = busy;
  }

  function renderAttachments() {
    if (!attachmentTray) return;
    attachmentTray.classList.toggle("is-active", attachments.length > 0);
    attachmentTray.innerHTML = attachments.map((a, index) => `
      <div class="reading-attachment-thumb">
        <img src="${escapeAttribute(a.previewUrl)}" alt="待发送截图">
        <button type="button" data-remove-reading-attachment="${index}" aria-label="删除截图">×</button>
      </div>
    `).join("");
  }

  function addAttachment(file) {
    if (!file || !String(file.type || "").startsWith("image/")) return;
    if (attachments.length >= 6) {
      window.alert("一次最多附加 6 张图片。");
      return;
    }
    attachments.push({ file, previewUrl: URL.createObjectURL(file) });
    renderAttachments();
  }

  function clearAttachments() {
    attachments.forEach((a) => URL.revokeObjectURL(a.previewUrl));
    attachments = [];
    renderAttachments();
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling() {
    if (pollTimer) return;
    const statusUrl = form.dataset.statusUrl;
    pollTimer = window.setInterval(async () => {
      try {
        const response = await fetch(statusUrl, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json();
        renderChat(payload.messages || [], payload.running ? payload.latest : null);
        if (!payload.running) {
          stopPolling();
          setBusy(false);
        }
      } catch (_err) {
        // 下一轮重试
      }
    }, 3000);
  }

  attachmentTray?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-reading-attachment]");
    if (!button) return;
    const index = Number(button.dataset.removeReadingAttachment);
    const [removed] = attachments.splice(index, 1);
    if (removed) URL.revokeObjectURL(removed.previewUrl);
    renderAttachments();
  });

  if (textarea) {
    textarea.addEventListener("paste", (event) => {
      const items = Array.from(event.clipboardData?.items || []);
      const images = items.filter((item) => String(item.type || "").startsWith("image/"));
      if (!images.length) return;
      event.preventDefault();
      images.forEach((item) => {
        const file = item.getAsFile();
        if (file) addAttachment(file);
      });
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!readingChatReady()) {
      window.alert("请先从文库中选择一篇 PDF 文献再开始对话。");
      return;
    }
    const question = (textarea?.value || "").trim();
    if (!question && !attachments.length) {
      window.alert("请输入文献研读问题，或先截图/粘贴一张图片。");
      return;
    }
    setBusy(true);
    try {
      const formData = new FormData();
      formData.append("user_question", question);
      attachments.forEach((a) => formData.append("images", a.file, a.file.name || `reading-image-${Date.now()}.png`));
      const runUrl = form.dataset.runUrl || form.action;
      const response = await fetch(runUrl, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "提交失败");
      if (textarea) textarea.value = "";
      clearAttachments();
      renderChat(payload.messages || [payload.user_message].filter(Boolean), {
        run_id: payload.run_id,
        status: "running",
        started_at: "",
        events: [{ message: "文献研读问答任务已提交。" }],
      });
      startPolling();
    } catch (error) {
      window.alert(error.message || "文献研读问答提交失败。");
      setBusy(false);
    }
  });

  form.addEventListener("click", async (event) => {
    const stopButton = event.target.closest("[data-stop-reading-chat]");
    if (!stopButton) return;
    event.preventDefault();
    stopButton.disabled = true;
    try {
      const response = await fetch(form.dataset.stopUrl, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "停止失败");
      stopPolling();
      setBusy(false);
      renderChat(payload.messages || []);
    } catch (error) {
      window.alert(error.message || "停止文献研读问答失败。");
      stopButton.disabled = false;
    }
  });

  resetButton?.addEventListener("click", async () => {
    if (!window.confirm("确定要重置当前文献的研读对话吗？这会开启新的对话线程，但保留历史分割线。")) return;
    try {
      const response = await fetch(form.dataset.resetUrl, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "重置失败");
      stopPolling();
      setBusy(false);
      renderChat(payload.messages || []);
    } catch (error) {
      window.alert(error.message || "重置文献研读对话失败。");
    }
  });

  screenshotButton?.addEventListener("click", () => {
    // 占位：可被 reader.js 的 PDF 截图流程接入（截图后通过
    // window.dispatchEvent(new CustomEvent("reading-attatachment", { detail: { file } })) 注入）。
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (file) addAttachment(file);
    });
    input.click();
  });

  document.addEventListener("reading-attachment", (event) => {
    if (event.detail && event.detail.file) addAttachment(event.detail.file);
  });

  // 进入页面时拉取历史 + 运行中状态。
  (async () => {
    if (!readingChatReady()) return;
    const statusUrl = form.dataset.statusUrl;
    if (!statusUrl) return;
    try {
      const response = await fetch(statusUrl, { cache: "no-store" });
      const payload = await response.json();
      renderChat(payload.messages || [], payload.running ? payload.latest : null);
      if (payload.running) {
        setBusy(true);
        startPolling();
      }
    } catch (_err) {
      // 忽略初始加载错误
    }
  })();
})();
