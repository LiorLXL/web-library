const readerState = {
  libraryId: "",
  library: null,
  itemKey: "",
  attachmentKey: "",
  pdfDoc: null,
  pageLabels: [],
  pages: [],
  annotations: [],
  selectedColor: "#ffd400",
  pendingSelection: null,
  scaleMode: "fit-width",
  customScale: 1,
  scale: 1,
  currentPageIndex: 0,
  pageObserver: null,
  visibleObserver: null,
  resizeTimer: 0,
  dragSelection: null,
  lastSelectionClick: { time: 0, pageIndex: -1, offset: -1, count: 0 },
};

const READER_STORAGE_PREFIX = "zotero-web-reader";
const MIN_SCALE = 0.5;
const MAX_SCALE = 2.5;
const ZOOM_STEP = 0.1;

function qs(selector) {
  return document.querySelector(selector);
}

async function readerJSON(url, options = {}) {
  const response = await fetch(url, options);
  const data = await parseReaderJSONResponse(response);
  if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
  return data;
}

async function parseReaderJSONResponse(response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (error) {
    const summary = text.replace(/\s+/g, " ").trim().slice(0, 120);
    throw new Error(`请求返回了非 JSON 内容（HTTP ${response.status}）：${summary || response.statusText}`);
  }
}

function readerStorageKey(name) {
  return `${READER_STORAGE_PREFIX}:${readerState.libraryId}:${name}`;
}

function clampScale(value) {
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, Number(value) || 1));
}

function setReaderStatus(title, subtitle) {
  const titleNode = qs("[data-reader-title]");
  const subtitleNode = qs("[data-reader-subtitle]");
  if (titleNode) titleNode.textContent = title;
  if (subtitleNode) subtitleNode.textContent = subtitle;
}

function updateReaderToolbarPosition() {
  const panel = qs(".reader-pdf-panel");
  const toolbar = qs("[data-reader-toolbar]");
  if (!panel || !toolbar) return;
  const box = panel.getBoundingClientRect();
  const center = box.left + box.width / 2;
  const top = box.top + 20;
  document.documentElement.style.setProperty("--reader-toolbar-left", `${Math.round(center)}px`);
  document.documentElement.style.setProperty("--reader-toolbar-top", `${Math.round(top)}px`);
}

function loadReaderPreferences() {
  const outlineWidth = localStorage.getItem(readerStorageKey("outlineWidth"));
  const agentWidth = localStorage.getItem(readerStorageKey("agentWidth"));
  const outlineCollapsed = localStorage.getItem(readerStorageKey("outlineCollapsed")) === "true";
  readerState.scaleMode = localStorage.getItem(readerStorageKey("scaleMode")) || "fit-width";
  readerState.customScale = clampScale(localStorage.getItem(readerStorageKey("customScale")) || 1);
  if (outlineWidth) document.documentElement.style.setProperty("--reader-outline-width", `${outlineWidth}px`);
  if (agentWidth) document.documentElement.style.setProperty("--reader-agent-width", `${agentWidth}px`);
  setOutlineCollapsed(outlineCollapsed);
}

function saveZoomPreferences() {
  localStorage.setItem(readerStorageKey("scaleMode"), readerState.scaleMode);
  localStorage.setItem(readerStorageKey("customScale"), String(readerState.customScale));
}

function setOutlineCollapsed(collapsed) {
  qs("[data-reader-layout]")?.classList.toggle("outline-collapsed", collapsed);
  const toggle = qs("[data-toggle-reader-outline]");
  if (toggle) {
    toggle.textContent = collapsed ? "▶" : "◀";
    toggle.title = collapsed ? "展开目录" : "折叠目录";
    toggle.setAttribute("aria-label", toggle.title);
  }
  window.requestAnimationFrame(updateReaderToolbarPosition);
}

function updateToolbar() {
  const zoomLabel = qs("[data-reader-zoom-label]");
  const pageInput = qs("[data-reader-page-input]");
  const total = qs("[data-reader-page-total]");
  if (zoomLabel) zoomLabel.textContent = `${Math.round(readerState.scale * 100)}%`;
  if (pageInput) pageInput.value = String(readerState.currentPageIndex + 1);
  if (total) total.textContent = String(readerState.pdfDoc?.numPages || 0);
}

function fitWidthScale() {
  const scroll = qs("[data-reader-pdf-scroll]");
  const widest = Math.max(...readerState.pages.map((page) => page.baseWidth), 1);
  const availableWidth = Math.max(360, (scroll?.clientWidth || 800) - 96);
  return clampScale(availableWidth / widest);
}

function resolveScale() {
  readerState.scale = readerState.scaleMode === "fit-width" ? fitWidthScale() : readerState.customScale;
  updateToolbar();
}

function setupReaderSplitters() {
  document.querySelectorAll("[data-reader-splitter]").forEach((splitter) => {
    splitter.addEventListener("pointerdown", (event) => {
      const side = splitter.dataset.readerSplitter;
      const startX = event.clientX;
      const currentOutline = Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--reader-outline-width"), 10) || 280;
      const currentAgent = Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--reader-agent-width"), 10) || 340;
      splitter.setPointerCapture(event.pointerId);

      function onMove(moveEvent) {
        const delta = moveEvent.clientX - startX;
        if (side === "left") {
          const width = Math.max(180, Math.min(520, currentOutline + delta));
          document.documentElement.style.setProperty("--reader-outline-width", `${width}px`);
          localStorage.setItem(readerStorageKey("outlineWidth"), String(width));
        } else {
          const width = Math.max(240, Math.min(560, currentAgent - delta));
          document.documentElement.style.setProperty("--reader-agent-width", `${width}px`);
          localStorage.setItem(readerStorageKey("agentWidth"), String(width));
        }
        updateReaderToolbarPosition();
        queueScaleRefresh();
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

function setupOutlineToggle() {
  qs("[data-toggle-reader-outline]")?.addEventListener("click", () => {
    const layout = qs("[data-reader-layout]");
    const collapsed = !layout?.classList.contains("outline-collapsed");
    setOutlineCollapsed(collapsed);
    localStorage.setItem(readerStorageKey("outlineCollapsed"), String(collapsed));
    queueScaleRefresh();
  });
}

function setupZoomToolbar() {
  qs("[data-reader-zoom-out]")?.addEventListener("click", () => setCustomScale(readerState.scale - ZOOM_STEP));
  qs("[data-reader-zoom-in]")?.addEventListener("click", () => setCustomScale(readerState.scale + ZOOM_STEP));
  qs("[data-reader-fit-width]")?.addEventListener("click", () => {
    readerState.scaleMode = "fit-width";
    saveZoomPreferences();
    rerenderWithCurrentScale();
  });
  qs("[data-reader-page-input]")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const pageNumber = Number.parseInt(event.currentTarget.value, 10);
    if (!Number.isFinite(pageNumber)) {
      updateToolbar();
      return;
    }
    jumpToPage(pageNumber - 1);
  });
  window.addEventListener("resize", () => {
    updateReaderToolbarPosition();
    queueScaleRefresh();
  });
}

function setCustomScale(scale) {
  readerState.scaleMode = "custom";
  readerState.customScale = clampScale(scale);
  saveZoomPreferences();
  rerenderWithCurrentScale();
}

function queueScaleRefresh() {
  updateReaderToolbarPosition();
  window.clearTimeout(readerState.resizeTimer);
  readerState.resizeTimer = window.setTimeout(() => {
    updateReaderToolbarPosition();
    if (readerState.scaleMode === "fit-width") rerenderWithCurrentScale();
  }, 120);
}

async function loadReaderContext() {
  const data = await readerJSON(`/api/library/${readerState.libraryId}/state`);
  readerState.library = data.library || null;
  const item = (data.items || []).find((value) => value.key === readerState.itemKey);
  const attachment = item?.attachments?.find((value) => value.key === readerState.attachmentKey);
  const editableText = readerState.library?.editable ? "可保存高亮和下划线" : "只读源库：可查看标注，不能新增";
  setReaderStatus(item?.title || "文献研读", attachment?.display_label ? `${attachment.display_label} · ${editableText}` : editableText);
}

function pageLabel(pageIndex) {
  return readerState.pageLabels[pageIndex] || String(pageIndex + 1);
}

async function loadPdf() {
  if (!readerState.attachmentKey) {
    setReaderStatus("文献研读", "请从文库中勾选一篇带 PDF 的条目打开。");
    updateToolbar();
    return;
  }
  qs("[data-reader-empty]")?.setAttribute("hidden", "");
  const scroll = qs("[data-reader-pdf-scroll]");
  if (scroll) scroll.hidden = false;
  pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.js";
  readerState.pdfDoc = await pdfjsLib.getDocument(`/api/library/${readerState.libraryId}/attachments/${readerState.attachmentKey}`).promise;
  try {
    readerState.pageLabels = (await readerState.pdfDoc.getPageLabels()) || [];
  } catch {
    readerState.pageLabels = [];
  }
  await preparePageContainers();
  await renderOutline();
  await loadAnnotations();
  setupPageObservers();
  updateToolbar();
  updateReaderToolbarPosition();
}

async function preparePageContainers() {
  const host = qs("[data-reader-pdf-pages]");
  if (!host || !readerState.pdfDoc) return;
  host.innerHTML = "";
  readerState.pages = [];
  const pageRecords = [];
  for (let pageNumber = 1; pageNumber <= readerState.pdfDoc.numPages; pageNumber += 1) {
    const pdfPage = await readerState.pdfDoc.getPage(pageNumber);
    const baseViewport = pdfPage.getViewport({ scale: 1 });
    pageRecords.push({
      pageNumber,
      pageIndex: pageNumber - 1,
      pdfPage,
      baseWidth: baseViewport.width,
      baseHeight: baseViewport.height,
      pageEl: null,
      annotationLayer: null,
      selectionLayer: null,
      viewport: null,
      chars: [],
      rendered: false,
      rendering: false,
      visible: false,
    });
  }
  readerState.pages = pageRecords;
  resolveScale();
  readerState.pages.forEach((record) => {
    const pageEl = document.createElement("article");
    pageEl.className = "reader-page";
    pageEl.dataset.pageIndex = String(record.pageIndex);
    record.pageEl = pageEl;
    host.appendChild(pageEl);
    sizePageContainer(record);
  });
}

function sizePageContainer(record) {
  if (!record.pageEl) return;
  const width = record.baseWidth * readerState.scale;
  const height = record.baseHeight * readerState.scale;
  record.pageEl.style.width = `${width}px`;
  record.pageEl.style.height = `${height}px`;
  record.viewport = record.pdfPage.getViewport({ scale: readerState.scale });
}

function setupPageObservers() {
  const scroll = qs("[data-reader-pdf-scroll]");
  if (!scroll) return;
  readerState.pageObserver?.disconnect();
  readerState.visibleObserver?.disconnect();
  readerState.pageObserver = new IntersectionObserver(handleRenderIntersections, {
    root: scroll,
    rootMargin: "900px 0px",
    threshold: 0.01,
  });
  readerState.visibleObserver = new IntersectionObserver(handleVisibleIntersections, {
    root: scroll,
    threshold: [0, 0.2, 0.5, 0.8, 1],
  });
  readerState.pages.forEach((record) => {
    if (record.pageEl) {
      readerState.pageObserver.observe(record.pageEl);
      readerState.visibleObserver.observe(record.pageEl);
    }
  });
}

function handleRenderIntersections(entries) {
  entries.forEach((entry) => {
    const record = pageRecordFromElement(entry.target);
    if (!record) return;
    if (entry.isIntersecting) {
      record.visible = true;
      renderPage(record.pageIndex);
    } else {
      record.visible = false;
      unloadPage(record);
    }
  });
}

function handleVisibleIntersections(entries) {
  let best = { ratio: 0, pageIndex: readerState.currentPageIndex };
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const pageIndex = Number(entry.target.dataset.pageIndex);
    if (entry.intersectionRatio >= best.ratio) best = { ratio: entry.intersectionRatio, pageIndex };
  });
  if (best.pageIndex !== readerState.currentPageIndex) {
    readerState.currentPageIndex = best.pageIndex;
    updateToolbar();
  }
}

function pageRecordFromElement(element) {
  const pageIndex = Number(element?.dataset?.pageIndex);
  return readerState.pages[pageIndex] || null;
}

async function renderPage(pageIndex) {
  const record = readerState.pages[pageIndex];
  if (!record || record.rendered || record.rendering || !record.pageEl || !record.viewport) return;
  record.rendering = true;
  record.pageEl.innerHTML = "";
  const viewport = record.viewport;
  const outputScale = window.devicePixelRatio || 1;
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  record.pageEl.appendChild(canvas);

  const annotationLayer = document.createElement("div");
  annotationLayer.className = "reader-annotation-layer";
  record.annotationLayer = annotationLayer;
  record.pageEl.appendChild(annotationLayer);

  const selectionLayer = document.createElement("div");
  selectionLayer.className = "reader-selection-layer";
  record.selectionLayer = selectionLayer;
  record.pageEl.appendChild(selectionLayer);

  const textLayer = document.createElement("div");
  textLayer.className = "textLayer";
  record.pageEl.appendChild(textLayer);

  await record.pdfPage.render({
    canvasContext: context,
    viewport,
    transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null,
  }).promise;
  const textContent = await record.pdfPage.getTextContent();
  record.chars = buildPageCharacterModel(textContent, viewport);
  await pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: textLayer,
    viewport,
    textDivs: [],
  }).promise;
  record.rendered = true;
  record.rendering = false;
  renderAnnotationsForPage(pageIndex);
}

function unloadPage(record) {
  if (!record?.pageEl || !record.rendered) return;
  const scroll = qs("[data-reader-pdf-scroll]");
  if (!scroll) return;
  const pageBox = record.pageEl.getBoundingClientRect();
  const scrollBox = scroll.getBoundingClientRect();
  const farAway = pageBox.bottom < scrollBox.top - 1600 || pageBox.top > scrollBox.bottom + 1600;
  if (!farAway) return;
  record.pageEl.innerHTML = "";
  record.annotationLayer = null;
  record.selectionLayer = null;
  record.chars = [];
  record.rendered = false;
  record.rendering = false;
}

async function rerenderWithCurrentScale() {
  if (!readerState.pdfDoc || !readerState.pages.length) return;
  const current = readerState.currentPageIndex;
  resolveScale();
  readerState.pages.forEach((record) => {
    sizePageContainer(record);
    record.pageEl.innerHTML = "";
    record.annotationLayer = null;
    record.selectionLayer = null;
    record.chars = [];
    record.rendered = false;
    record.rendering = false;
  });
  jumpToPage(current, "auto");
  readerState.pages.forEach((record) => {
    const pageBox = record.pageEl.getBoundingClientRect();
    const scrollBox = qs("[data-reader-pdf-scroll]").getBoundingClientRect();
    if (pageBox.bottom > scrollBox.top - 900 && pageBox.top < scrollBox.bottom + 900) renderPage(record.pageIndex);
  });
  updateToolbar();
  updateReaderToolbarPosition();
}

function jumpToPage(pageIndex, behavior = "smooth") {
  if (!readerState.pages.length) return;
  const clamped = Math.max(0, Math.min(readerState.pages.length - 1, pageIndex));
  readerState.currentPageIndex = clamped;
  readerState.pages[clamped]?.pageEl?.scrollIntoView({ behavior, block: "start" });
  renderPage(clamped);
  updateToolbar();
}

async function destinationPageIndex(dest) {
  if (!readerState.pdfDoc || !dest) return null;
  const destination = typeof dest === "string" ? await readerState.pdfDoc.getDestination(dest) : dest;
  if (!destination || !destination[0]) return null;
  try {
    return await readerState.pdfDoc.getPageIndex(destination[0]);
  } catch {
    if (Number.isInteger(destination[0])) return Math.max(0, destination[0] - 1);
    return null;
  }
}

async function renderOutline() {
  const host = qs("[data-reader-outline]");
  if (!host || !readerState.pdfDoc) return;
  const outline = await readerState.pdfDoc.getOutline();
  if (!outline || !outline.length) {
    host.innerHTML = `<p class="reader-outline-empty">暂无目录</p>`;
    return;
  }
  host.innerHTML = "";

  function renderNodes(nodes, parent) {
    nodes.forEach((node, index) => {
      const row = document.createElement("div");
      row.className = "reader-outline-node";
      const children = node.items || [];
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "reader-outline-toggle";
      toggle.textContent = children.length ? "▾" : "";
      const link = document.createElement("button");
      link.type = "button";
      link.className = "reader-outline-link";
      link.textContent = node.title || `目录 ${index + 1}`;
      row.append(toggle, link);
      parent.appendChild(row);
      let childBox = null;
      if (children.length) {
        childBox = document.createElement("div");
        childBox.className = "reader-outline-children";
        row.appendChild(childBox);
        renderNodes(children, childBox);
        toggle.addEventListener("click", () => {
          childBox.classList.toggle("collapsed");
          toggle.textContent = childBox.classList.contains("collapsed") ? "▸" : "▾";
        });
      }
      link.addEventListener("click", async () => {
        const pageIndex = await destinationPageIndex(node.dest);
        if (pageIndex !== null) jumpToPage(pageIndex);
      });
    });
  }

  renderNodes(outline, host);
}

async function loadAnnotations() {
  const data = await readerJSON(`/api/library/${readerState.libraryId}/attachments/${readerState.attachmentKey}/annotations`);
  readerState.annotations = data.annotations || [];
  readerState.pages.forEach((_, pageIndex) => renderAnnotationsForPage(pageIndex));
}

function rectToViewportBox(viewport, rect) {
  const converted = viewport.convertToViewportRectangle(rect);
  const left = Math.min(converted[0], converted[2]);
  const top = Math.min(converted[1], converted[3]);
  const width = Math.abs(converted[2] - converted[0]);
  const height = Math.abs(converted[3] - converted[1]);
  return { left, top, width, height };
}

function normalizedAnnotationBox(box, type) {
  const height = Math.max(2, box.height);
  const insetY = Math.min(2, height * 0.12);
  const highlightHeight = Math.max(3, height - insetY * 2);
  if (type === "underline") {
    return {
      left: box.left,
      top: box.top + insetY + highlightHeight - 2,
      width: box.width,
      height: 2,
    };
  }
  return {
    left: box.left,
    top: box.top + insetY,
    width: box.width,
    height: highlightHeight,
  };
}

function renderAnnotationsForPage(pageIndex) {
  const record = readerState.pages[pageIndex];
  if (!record?.annotationLayer || !record.viewport) return;
  record.annotationLayer.innerHTML = "";
  readerState.annotations
    .filter((annotation) => Number(annotation.position?.pageIndex) === pageIndex)
    .forEach((annotation) => {
      (annotation.position?.rects || []).forEach((rect) => {
        if (!Array.isArray(rect) || rect.length !== 4) return;
        const box = normalizedAnnotationBox(rectToViewportBox(record.viewport, rect), annotation.type);
        const marker = document.createElement("div");
        marker.className = `reader-annotation ${annotation.type === "underline" ? "underline" : "highlight"}`;
        marker.style.setProperty("--annotation-color", annotation.color || "#ffd400");
        marker.style.left = `${box.left}px`;
        marker.style.top = `${box.top}px`;
        marker.style.width = `${box.width}px`;
        marker.style.height = `${box.height}px`;
        marker.title = annotation.text || "";
        record.annotationLayer.appendChild(marker);
      });
    });
}

function roundPdfCoord(value) {
  return Math.round(Number(value) * 1000) / 1000;
}

function viewportRectToPdfRect(viewport, rect) {
  const p1 = viewport.convertToPdfPoint(rect.left, rect.top);
  const p2 = viewport.convertToPdfPoint(rect.right, rect.bottom);
  return [
    roundPdfCoord(Math.min(p1[0], p2[0])),
    roundPdfCoord(Math.min(p1[1], p2[1])),
    roundPdfCoord(Math.max(p1[0], p2[0])),
    roundPdfCoord(Math.max(p1[1], p2[1])),
  ];
}

function buildPageCharacterModel(textContent, viewport) {
  const chars = [];
  (textContent.items || []).forEach((item) => {
    const text = Array.from(item.str || "");
    if (!text.length) return;
    const transform = pdfjsLib.Util.transform(viewport.transform, item.transform);
    const startX = transform[4];
    const baselineY = transform[5];
    const fontHeight = Math.max(4, Math.hypot(transform[2], transform[3]) || Math.abs(item.height || 0) * viewport.scale || 10);
    const itemWidth = Math.max(1, Math.abs(item.width || 0) * viewport.scale || Math.hypot(transform[0], transform[1]) * text.length);
    const charWidth = itemWidth / text.length;
    const top = baselineY - fontHeight;
    const bottom = baselineY + Math.max(1.5, fontHeight * 0.18);
    text.forEach((value, index) => {
      const left = startX + charWidth * index;
      const right = startX + charWidth * (index + 1);
      const viewportRect = {
        left: Math.min(left, right),
        top: Math.min(top, bottom),
        right: Math.max(left, right),
        bottom: Math.max(top, bottom),
      };
      chars.push({
        value,
        index: chars.length,
        lineId: -1,
        viewportRect,
        rect: viewportRectToPdfRect(viewport, viewportRect),
      });
    });
  });
  assignCharacterLines(chars);
  return chars;
}

function assignCharacterLines(chars) {
  const rows = [];
  [...chars]
    .sort((a, b) => ((a.viewportRect.top + a.viewportRect.bottom) / 2) - ((b.viewportRect.top + b.viewportRect.bottom) / 2))
    .forEach((char) => {
      const center = (char.viewportRect.top + char.viewportRect.bottom) / 2;
      const height = Math.max(1, char.viewportRect.bottom - char.viewportRect.top);
      let row = rows.find((candidate) => Math.abs(candidate.center - center) <= Math.max(candidate.height, height) * 0.48);
      if (!row) {
        row = { id: rows.length, center, height, chars: [] };
        rows.push(row);
      }
      row.chars.push(char);
      row.center = (row.center * (row.chars.length - 1) + center) / row.chars.length;
      row.height = Math.max(row.height, height);
    });
  rows.sort((a, b) => a.center - b.center).forEach((row, index) => {
    row.chars.forEach((char) => {
      char.lineId = index;
    });
  });
}

function pageRecordFromPointer(event) {
  const pageEl = event.target?.closest?.(".reader-page");
  return pageRecordFromElement(pageEl);
}

function eventToViewportPoint(event, record) {
  const pageBox = record.pageEl.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(record.viewport.width, event.clientX - pageBox.left)),
    y: Math.max(0, Math.min(record.viewport.height, event.clientY - pageBox.top)),
  };
}

function pointToCharacterOffset(record, point) {
  if (!record?.chars?.length) return null;
  const rows = [];
  record.chars.forEach((char) => {
    let row = rows.find((candidate) => candidate.lineId === char.lineId);
    if (!row) {
      row = { lineId: char.lineId, chars: [], top: Infinity, bottom: -Infinity };
      rows.push(row);
    }
    row.chars.push(char);
    row.top = Math.min(row.top, char.viewportRect.top);
    row.bottom = Math.max(row.bottom, char.viewportRect.bottom);
  });
  rows.sort((a, b) => a.top - b.top);
  let row = rows.find((candidate) => point.y >= candidate.top - 3 && point.y <= candidate.bottom + 3);
  if (!row) {
    row = rows.reduce((best, candidate) => {
      const center = (candidate.top + candidate.bottom) / 2;
      const distance = Math.abs(point.y - center);
      return !best || distance < best.distance ? { ...candidate, distance } : best;
    }, null);
  }
  const rowChars = [...(row?.chars || [])].sort((a, b) => a.viewportRect.left - b.viewportRect.left);
  if (!rowChars.length) return null;
  if (point.x <= rowChars[0].viewportRect.left) return rowChars[0].index;
  const last = rowChars[rowChars.length - 1];
  if (point.x >= last.viewportRect.right) return last.index + 1;
  const hit = rowChars.find((char) => point.x >= char.viewportRect.left && point.x <= char.viewportRect.right);
  if (hit) {
    const midpoint = (hit.viewportRect.left + hit.viewportRect.right) / 2;
    return point.x < midpoint ? hit.index : hit.index + 1;
  }
  const nearest = rowChars.reduce((best, char) => {
    const center = (char.viewportRect.left + char.viewportRect.right) / 2;
    const distance = Math.abs(point.x - center);
    return !best || distance < best.distance ? { char, distance } : best;
  }, null)?.char;
  if (!nearest) return null;
  return point.x < (nearest.viewportRect.left + nearest.viewportRect.right) / 2 ? nearest.index : nearest.index + 1;
}

function normalizeSelectionOffsets(anchorOffset, headOffset) {
  const start = Math.min(anchorOffset, headOffset);
  const end = Math.max(anchorOffset, headOffset);
  return { start, end };
}

function selectionRangeToChars(record, startOffset, endOffset) {
  const { start, end } = normalizeSelectionOffsets(startOffset, endOffset);
  return record.chars.filter((char) => char.index >= start && char.index < end);
}

function selectionRangeToRects(record, startOffset, endOffset) {
  const selected = selectionRangeToChars(record, startOffset, endOffset).filter((char) => !/^\s$/.test(char.value));
  if (!selected.length) return [];
  const rows = [];
  selected.forEach((char) => {
    let row = rows.find((candidate) => candidate.lineId === char.lineId);
    if (!row) {
      row = { lineId: char.lineId, chars: [] };
      rows.push(row);
    }
    row.chars.push(char);
  });
  return rows
    .sort((a, b) => a.lineId - b.lineId)
    .map((row) => {
      const rects = row.chars.map((char) => char.rect);
      return [
        roundPdfCoord(Math.min(...rects.map((rect) => rect[0]))),
        roundPdfCoord(Math.min(...rects.map((rect) => rect[1]))),
        roundPdfCoord(Math.max(...rects.map((rect) => rect[2]))),
        roundPdfCoord(Math.max(...rects.map((rect) => rect[3]))),
      ];
    })
    .filter((rect) => rect[2] - rect[0] >= 0.5 && rect[3] - rect[1] >= 0.5);
}

function selectionRangeToText(record, startOffset, endOffset) {
  const selected = selectionRangeToChars(record, startOffset, endOffset);
  let text = "";
  selected.forEach((char, index) => {
    if (index > 0 && selected[index - 1].lineId !== char.lineId && !text.endsWith("\n")) text += "\n";
    text += char.value;
  });
  return text.replace(/[ \t]+\n/g, "\n").trim();
}

function expandSelectionToWord(record, offset) {
  if (!record?.chars?.length) return null;
  const index = Math.max(0, Math.min(record.chars.length - 1, offset >= record.chars.length ? offset - 1 : offset));
  const boundary = /[\s,.;:!?()[\]{}"'“”‘’<>，。；：！？（）【】《》]/;
  let start = index;
  let end = index + 1;
  while (start > 0 && record.chars[start - 1].lineId === record.chars[index].lineId && !boundary.test(record.chars[start - 1].value)) start -= 1;
  while (end < record.chars.length && record.chars[end].lineId === record.chars[index].lineId && !boundary.test(record.chars[end].value)) end += 1;
  return start === end ? null : { start, end };
}

function expandSelectionToLine(record, offset) {
  if (!record?.chars?.length) return null;
  const index = Math.max(0, Math.min(record.chars.length - 1, offset >= record.chars.length ? offset - 1 : offset));
  const lineId = record.chars[index].lineId;
  const lineChars = record.chars.filter((char) => char.lineId === lineId);
  if (!lineChars.length) return null;
  return { start: lineChars[0].index, end: lineChars[lineChars.length - 1].index + 1 };
}

function renderTemporarySelection(record, rects) {
  readerState.pages.forEach((page) => {
    if (page.selectionLayer) page.selectionLayer.innerHTML = "";
  });
  if (!record?.selectionLayer || !record.viewport) return;
  rects.forEach((rect) => {
    const box = normalizedAnnotationBox(rectToViewportBox(record.viewport, rect), "highlight");
    const marker = document.createElement("div");
    marker.className = "reader-selection";
    marker.style.left = `${box.left}px`;
    marker.style.top = `${box.top}px`;
    marker.style.width = `${box.width}px`;
    marker.style.height = `${box.height}px`;
    record.selectionLayer.appendChild(marker);
  });
}

function selectionClientBox(record, rects) {
  const pageBox = record.pageEl.getBoundingClientRect();
  const boxes = rects.map((rect) => rectToViewportBox(record.viewport, rect));
  return {
    left: pageBox.left + Math.min(...boxes.map((box) => box.left)),
    top: pageBox.top + Math.min(...boxes.map((box) => box.top)),
    right: pageBox.left + Math.max(...boxes.map((box) => box.left + box.width)),
    bottom: pageBox.top + Math.max(...boxes.map((box) => box.top + box.height)),
  };
}

function finishCharacterSelection(record, startOffset, endOffset) {
  const rects = selectionRangeToRects(record, startOffset, endOffset);
  const text = selectionRangeToText(record, startOffset, endOffset);
  if (!rects.length || !text) {
    hideAnnotationToolbar();
    return;
  }
  readerState.pendingSelection = {
    pageIndex: record.pageIndex,
    text,
    rects,
    position: { pageIndex: record.pageIndex, rects },
  };
  renderTemporarySelection(record, rects);
  showAnnotationToolbar(selectionClientBox(record, rects));
}

function handleReaderPointerDown(event) {
  if (event.button !== 0) return;
  const record = pageRecordFromPointer(event);
  if (!record?.chars?.length || !record.viewport) return;
  const offset = pointToCharacterOffset(record, eventToViewportPoint(event, record));
  if (offset === null) return;
  event.preventDefault();
  window.getSelection()?.removeAllRanges();
  const now = Date.now();
  const previous = readerState.lastSelectionClick;
  const clickCount =
    now - previous.time < 450 && previous.pageIndex === record.pageIndex && Math.abs(previous.offset - offset) <= 2
      ? previous.count + 1
      : 1;
  readerState.lastSelectionClick = { time: now, pageIndex: record.pageIndex, offset, count: clickCount };
  if (clickCount >= 3) {
    const line = expandSelectionToLine(record, offset);
    if (line) finishCharacterSelection(record, line.start, line.end);
    return;
  }
  if (clickCount === 2) {
    const word = expandSelectionToWord(record, offset);
    if (word) finishCharacterSelection(record, word.start, word.end);
    return;
  }
  hideAnnotationToolbar();
  readerState.dragSelection = { pointerId: event.pointerId, record, anchorOffset: offset, headOffset: offset };
  record.pageEl.setPointerCapture(event.pointerId);
}

function handleReaderPointerMove(event) {
  const drag = readerState.dragSelection;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const offset = pointToCharacterOffset(drag.record, eventToViewportPoint(event, drag.record));
  if (offset === null) return;
  drag.headOffset = offset;
  const rects = selectionRangeToRects(drag.record, drag.anchorOffset, drag.headOffset);
  renderTemporarySelection(drag.record, rects);
}

function handleReaderPointerUp(event) {
  const drag = readerState.dragSelection;
  if (!drag || drag.pointerId !== event.pointerId) return;
  readerState.dragSelection = null;
  try {
    drag.record.pageEl.releasePointerCapture(event.pointerId);
  } catch {
    // Pointer capture may already be released by the browser.
  }
  finishCharacterSelection(drag.record, drag.anchorOffset, drag.headOffset);
}

function showAnnotationToolbar(rangeBox) {
  const toolbar = qs("[data-reader-annotation-toolbar]");
  if (!toolbar) return;
  toolbar.hidden = false;
  const left = Math.min(window.innerWidth - toolbar.offsetWidth - 12, Math.max(12, rangeBox.left));
  const top = Math.max(12, rangeBox.top - toolbar.offsetHeight - 10);
  toolbar.style.left = `${left}px`;
  toolbar.style.top = `${top}px`;
}

function hideAnnotationToolbar() {
  readerState.pendingSelection = null;
  readerState.dragSelection = null;
  readerState.pages.forEach((page) => {
    if (page.selectionLayer) page.selectionLayer.innerHTML = "";
  });
  const toolbar = qs("[data-reader-annotation-toolbar]");
  if (toolbar) toolbar.hidden = true;
}

function setupAnnotationToolbar() {
  document.querySelectorAll("[data-reader-color]").forEach((button) => {
    button.addEventListener("click", () => {
      readerState.selectedColor = button.dataset.readerColor || "#ffd400";
      document.querySelectorAll("[data-reader-color]").forEach((item) => item.classList.toggle("active", item === button));
    });
  });
  document.querySelectorAll("[data-create-annotation]").forEach((button) => {
    button.addEventListener("click", async () => {
      await createAnnotation(button.dataset.createAnnotation || "highlight");
    });
  });
  qs("[data-clear-annotation]")?.addEventListener("click", clearAnnotationsInSelection);
  const scroll = qs("[data-reader-pdf-scroll]");
  scroll?.addEventListener("pointerdown", handleReaderPointerDown);
  scroll?.addEventListener("pointermove", handleReaderPointerMove);
  scroll?.addEventListener("pointerup", handleReaderPointerUp);
  scroll?.addEventListener("pointercancel", handleReaderPointerUp);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideAnnotationToolbar();
  });
}

async function createAnnotation(type) {
  if (!readerState.pendingSelection) return;
  if (!readerState.library?.editable) {
    window.alert("只读源库不能保存新标注。请先创建本地副本。");
    window.getSelection()?.removeAllRanges();
    hideAnnotationToolbar();
    return;
  }
  const payload = {
    type,
    text: readerState.pendingSelection.text,
    color: readerState.selectedColor,
    page_index: readerState.pendingSelection.pageIndex,
    page_label: pageLabel(readerState.pendingSelection.pageIndex),
    rects: readerState.pendingSelection.rects,
    position: readerState.pendingSelection.position,
  };
  await readerJSON(`/api/library/${readerState.libraryId}/attachments/${readerState.attachmentKey}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  window.getSelection()?.removeAllRanges();
  hideAnnotationToolbar();
  await loadAnnotations();
}

async function clearAnnotationsInSelection() {
  if (!readerState.pendingSelection) return;
  if (!readerState.library?.editable) {
    window.alert("只读源库不能清除标注。请先创建本地副本。");
    window.getSelection()?.removeAllRanges();
    hideAnnotationToolbar();
    return;
  }
  await readerJSON(`/api/library/${readerState.libraryId}/attachments/${readerState.attachmentKey}/annotations/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ position: readerState.pendingSelection.position }),
  });
  window.getSelection()?.removeAllRanges();
  hideAnnotationToolbar();
  await loadAnnotations();
}

async function setupReaderPage() {
  const root = qs("[data-reader-page]");
  if (!root) return;
  window.__zoteroReaderBooted = true;
  readerState.libraryId = root.dataset.libraryId || "";
  const params = new URLSearchParams(window.location.search);
  readerState.itemKey = params.get("item_key") || "";
  readerState.attachmentKey = params.get("attachment_key") || "";

  // 进入研读页时若 URL 未带文献参数，则恢复上一次打开的 PDF（按文库分别记忆），
  // 这样切走再切回仍能保留 PDF 与对话。
  if (!readerState.itemKey || !readerState.attachmentKey) {
    const lastItem = localStorage.getItem(readerStorageKey("lastItemKey"));
    const lastAttachment = localStorage.getItem(readerStorageKey("lastAttachmentKey"));
    if (lastItem && lastAttachment) {
      const next = new URL(window.location.href);
      next.searchParams.set("item_key", lastItem);
      next.searchParams.set("attachment_key", lastAttachment);
      window.location.replace(next.toString());
      return;
    }
  } else {
    // 记录本次打开的文献，供下次恢复。
    localStorage.setItem(readerStorageKey("lastItemKey"), readerState.itemKey);
    localStorage.setItem(readerStorageKey("lastAttachmentKey"), readerState.attachmentKey);
  }
  loadReaderPreferences();
  setupReaderSplitters();
  setupOutlineToggle();
  setupZoomToolbar();
  setupAnnotationToolbar();
  try {
    if (readerState.itemKey) await loadReaderContext();
    await loadPdf();
  } catch (error) {
    setReaderStatus("文献研读", error.message || "PDF 加载失败");
    const empty = qs("[data-reader-empty]");
    if (empty) {
      empty.hidden = false;
      empty.textContent = error.message || "PDF 加载失败";
    }
  }
}

setupReaderPage();
