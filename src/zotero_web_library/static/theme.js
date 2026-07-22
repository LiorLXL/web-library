(() => {
  "use strict";

  const THEME_STORAGE_KEY = "guangming-theme";
  const LIGHT_THEME = "light";
  const DARK_THEME = "dark";
  const root = document.documentElement;
  let transitionTimer = 0;

  function normalizeTheme(value) {
    return value === DARK_THEME ? DARK_THEME : LIGHT_THEME;
  }

  function currentTheme() {
    return normalizeTheme(root.dataset.theme);
  }

  function storedTheme() {
    try {
      return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
    } catch (_error) {
      return LIGHT_THEME;
    }
  }

  function storeTheme(theme) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (_error) {
      // The theme remains active for this page when storage is unavailable.
    }
  }

  function updateToggle(button, theme) {
    const isDark = theme === DARK_THEME;
    const targetLabel = isDark ? "切换到浅色模式" : "切换到深色模式";
    button.dataset.themeCurrent = theme;
    button.setAttribute("aria-label", targetLabel);
    button.setAttribute("aria-pressed", String(isDark));
    button.setAttribute("title", targetLabel);

    const icon = button.querySelector("[data-theme-toggle-icon]");
    if (icon) icon.textContent = isDark ? "☀" : "☾";
    const label = button.querySelector("[data-theme-toggle-label]");
    if (label) label.textContent = isDark ? "浅色模式" : "深色模式";
  }

  function updateToggles(theme) {
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => updateToggle(button, theme));
  }

  function applyTheme(value, { persist = false, notify = false, animate = false } = {}) {
    const theme = normalizeTheme(value);
    if (animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      root.classList.add("theme-is-transitioning");
      window.clearTimeout(transitionTimer);
      transitionTimer = window.setTimeout(() => root.classList.remove("theme-is-transitioning"), 220);
    }
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    updateToggles(theme);
    if (persist) storeTheme(theme);
    if (notify) {
      window.dispatchEvent(new CustomEvent("guangming:themechange", { detail: { theme } }));
    }
    return theme;
  }

  function toggleTheme() {
    return applyTheme(currentTheme() === DARK_THEME ? LIGHT_THEME : DARK_THEME, {
      persist: true,
      notify: true,
      animate: true,
    });
  }

  function setupThemeControls() {
    applyTheme(root.dataset.theme || storedTheme());
    document.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-theme-toggle]");
      if (!toggle) return;
      toggleTheme();
    });
    window.addEventListener("storage", (event) => {
      if (event.key === THEME_STORAGE_KEY) applyTheme(event.newValue, { notify: true, animate: true });
    });
  }

  window.GuangmingTheme = Object.freeze({
    apply: (theme) => applyTheme(theme, { persist: true, notify: true, animate: true }),
    current: currentTheme,
    toggle: toggleTheme,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupThemeControls, { once: true });
  } else {
    setupThemeControls();
  }
})();
