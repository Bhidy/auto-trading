(function () {
    "use strict";

    var STORAGE_KEY = "theme";
    var DEFAULT_THEME = "dark";

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
}());
