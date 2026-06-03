(function () {
    "use strict";

    var STORAGE_KEY = "theme";
    // First-load default honors the OS preference; falls back to light. A stored
    // choice always wins over this (see storedTheme).
    var DEFAULT_THEME = (function () {
        try {
            return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        } catch (_) { return "light"; }
    })();

    function normalize(theme) {
        return theme === "light" || theme === "dark" ? theme : DEFAULT_THEME;
    }

    function storedTheme() {
        try {
            return normalize(window.localStorage.getItem(STORAGE_KEY));
        } catch (_) {
            return DEFAULT_THEME;
        }
    }

    function syncControls(theme) {
        document.querySelectorAll("[data-theme-toggle], #themeToggle").forEach(function (button) {
            var darkIcon = button.querySelector(".dark-icon");
            var lightIcon = button.querySelector(".light-icon");
            if (darkIcon) darkIcon.style.opacity = theme === "light" ? "0" : "1";
            if (lightIcon) lightIcon.style.opacity = theme === "light" ? "1" : "0";
            button.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
        });
    }

    function applyTheme(theme, persist) {
        var resolved = normalize(theme);
        document.documentElement.setAttribute("data-theme", resolved);
        document.documentElement.style.colorScheme = resolved;
        if (persist) {
            try {
                window.localStorage.setItem(STORAGE_KEY, resolved);
            } catch (_) {}
        }
        syncControls(resolved);
        document.dispatchEvent(new CustomEvent("starta:themechange", { detail: { theme: resolved } }));
        return resolved;
    }

    function bindControls() {
        syncControls(normalize(document.documentElement.getAttribute("data-theme")));
        document.querySelectorAll("[data-theme-toggle], #themeToggle").forEach(function (button) {
            if (button.dataset.themeBound === "true") return;
            button.dataset.themeBound = "true";
            button.addEventListener("click", function () {
                var current = normalize(document.documentElement.getAttribute("data-theme"));
                applyTheme(current === "dark" ? "light" : "dark", true);
            });
        });
    }

    window.StartaTheme = {
        apply: function (theme) { return applyTheme(theme, true); },
        current: function () { return normalize(document.documentElement.getAttribute("data-theme")); }
    };

    applyTheme(storedTheme(), false);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindControls);
    } else {
        bindControls();
    }
    window.addEventListener("storage", function (event) {
        if (event.key === STORAGE_KEY) applyTheme(event.newValue, false);
    });

    // ── Chart.js global tooltip defaults — applied to every chart on every page ──
    // Per-instance overrides in individual charts still take precedence (Chart.js
    // merges options in the order: defaults → scale-type → per-instance).
    function applyChartDefaults() {
        if (typeof Chart === "undefined") return;
        var isDark = normalize(document.documentElement.getAttribute("data-theme")) === "dark";
        var tt = Chart.defaults.plugins.tooltip;
        tt.backgroundColor    = isDark ? "#1a0f08" : "#ffffff";
        tt.borderColor        = isDark ? "rgba(255,255,255,0.10)" : "rgba(26,15,8,0.09)";
        tt.borderWidth        = 1;
        tt.cornerRadius       = 10;
        tt.padding            = { top: 9, bottom: 9, left: 13, right: 15 };
        tt.titleColor         = isDark ? "#fff1e8" : "#1a0f08";
        tt.bodyColor          = isDark ? "#a39a92" : "#7a6b5e";
        tt.titleFont          = { family: "Manrope", size: 11, weight: "700" };
        tt.bodyFont           = { family: "IBM Plex Mono", size: 11 };
        tt.multiKeyBackground = "transparent";
    }
    // Apply once all scripts are loaded, then again on every theme toggle
    window.addEventListener("load", applyChartDefaults);
    document.addEventListener("starta:themechange", applyChartDefaults);
}());
