(function () {
  var KEY = "speaked-theme";

  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function storedTheme() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : "";
    } catch (err) {
      return "";
    }
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function syncToggle() {
    var button = document.querySelector("[data-theme-toggle]");
    if (!button) return;
    var next = currentTheme() === "dark" ? "light" : "dark";
    var label = next === "dark" ? "Switch to dark mode" : "Switch to light mode";
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    button.setAttribute("aria-pressed", currentTheme() === "dark" ? "true" : "false");
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
    var meta = document.querySelector('meta[name="theme-color"]:not([media])');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#1a1a2e" : "#f8fafc");
    syncToggle();
    document.dispatchEvent(new CustomEvent("speaked-themechange", { detail: { theme: theme } }));
  }

  applyTheme(storedTheme() || systemTheme());

  function bindToggle() {
    var button = document.querySelector("[data-theme-toggle]");
    if (!button || button.getAttribute("data-bound") === "1") return;
    button.setAttribute("data-bound", "1");
    syncToggle();
    button.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch (err) {}
      applyTheme(next);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindToggle);
  } else {
    bindToggle();
  }

  var media = window.matchMedia("(prefers-color-scheme: dark)");
  if (media.addEventListener) {
    media.addEventListener("change", function () {
      if (storedTheme()) return;
      applyTheme(systemTheme());
    });
  }
})();
