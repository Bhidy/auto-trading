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

    // ── ATFmt — the ONE shared formatter for money, percentages and market time ──
    // Every signed money/percent change on every page goes through here so a loss
    // can never render as a positive amount (audit 2026-10-23 D1/D15/D17) and every
    // market timestamp is US Eastern, labelled "ET" (D2/D6/D19).
    var ET_ZONE = "America/New_York";
    // Mirrors the committed files in /assets/logos/*.svg — keep in sync when adding logos.
    var LOCAL_LOGOS = "AAPL AMD AMZN AVAX_USD BIL BTC_USD CSCO DIA DOGE_USD DOT_USD EOG ETH_USD GLD GOOGL HD INTC INTU IWM LINK_USD LTC_USD MEDP META MPC MS MSFT NFLX NVDA PANW PG PH QQQ SHIB_USD SHY SPY T TER TLT TSLA UNI_USD VLO WMT XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY".split(" ");

    function toNum(n) { var v = typeof n === "number" ? n : parseFloat(n); return isFinite(v) ? v : null; }
    function grouped(n, d) {
        return Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    }
    // Parse an API timestamp as an absolute instant. A zone-less ISO datetime from
    // the broker is UTC; an ISO date alone (YYYY-MM-DD) is a session date.
    function toDate(v) {
        if (v instanceof Date) return v;
        if (typeof v === "number") return new Date(v < 1e12 ? v * 1000 : v);
        var s = String(v || "");
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) s += "Z";
        return new Date(s);
    }
    function etParts(v) {
        var d = toDate(v);
        if (isNaN(d.getTime())) return null;
        var out = {};
        new Intl.DateTimeFormat("en-US", {
            timeZone: ET_ZONE, hourCycle: "h23", year: "numeric", month: "2-digit",
            day: "2-digit", hour: "2-digit", minute: "2-digit"
        }).formatToParts(d).forEach(function (p) { out[p.type] = p.value; });
        return { date: out.year + "-" + out.month + "-" + out.day, minutes: parseInt(out.hour, 10) * 60 + parseInt(out.minute, 10) };
    }

    window.ATFmt = {
        ET_ZONE: ET_ZONE,
        /** "$1,234.56" / "-$1,234.56" — unsigned positives, minus before the $. */
        money: function (n, d) {
            var v = toNum(n); d = d === undefined ? 2 : d;
            if (v === null) return "—";
            return (v < 0 ? "-$" : "$") + grouped(v, d);
        },
        /** "+$156.60" / "-$156.60" / "$0.00" — for any P&L or change amount. */
        signedMoney: function (n, d) {
            var v = toNum(n); d = d === undefined ? 2 : d;
            if (v === null) return "—";
            var r = grouped(v, d);
            if (parseFloat(r.replace(/,/g, "")) === 0) return "$" + r;
            return (v > 0 ? "+$" : "-$") + r;
        },
        /** "+1.23%" / "-1.86%" / "0.00%". */
        signedPct: function (n, d) {
            var v = toNum(n); d = d === undefined ? 2 : d;
            if (v === null) return "—";
            var r = grouped(v, d);
            if (parseFloat(r.replace(/,/g, "")) === 0) return r + "%";
            return (v > 0 ? "+" : "-") + r + "%";
        },
        /** Numbers keep LTR order inside Arabic (RTL) text: "-0.85%" never becomes "0.85%-". */
        ltr: function (s) { return '<bdi dir="ltr" class="at-num">' + s + "</bdi>"; },
        /** "pf-pos" / "pf-neg" / "" — colour matches the sign shown; an exact zero
            (after rounding to `d` decimals, default 2) or missing value is neutral (N11). */
        signClass: function (n, d) {
            var v = toNum(n);
            if (v === null) return "";
            var p = Math.pow(10, typeof d === "number" ? d : 2);
            var r = Math.round(v * p) / p;
            return r > 0 ? "pf-pos" : (r < 0 ? "pf-neg" : "");
        },
        toDate: toDate,
        /** "14:35" in New York time (24h). */
        etTime: function (v, withSeconds) {
            var d = toDate(v);
            if (isNaN(d.getTime())) return "—";
            var o = { timeZone: ET_ZONE, hourCycle: "h23", hour: "2-digit", minute: "2-digit" };
            if (withSeconds) o.second = "2-digit";
            return d.toLocaleTimeString("en-GB", o);
        },
        /** "Oct 22" in New York time. */
        etDate: function (v, opts) {
            var d = toDate(v);
            if (isNaN(d.getTime())) return "—";
            var o = Object.assign({ timeZone: ET_ZONE, month: "short", day: "numeric" }, opts || {});
            return d.toLocaleDateString("en-US", o);
        },
        /** { date: "YYYY-MM-DD", minutes: minutes-since-midnight } in New York time. */
        etParts: etParts,
        /**
         * Keep only the most recent US regular session (09:30–16:00 ET) from an
         * intraday bar series, so a "1D" view never silently spans two sessions.
         * Falls back to the whole last ET date if it has no regular-hours bars.
         */
        lastSession: function (bars, key) {
            key = key || "t";
            if (!bars || !bars.length) return bars || [];
            var tagged = bars.map(function (b) { return { b: b, p: etParts(b[key]) }; }).filter(function (x) { return x.p; });
            if (!tagged.length) return bars;
            var rth = tagged.filter(function (x) { return x.p.minutes >= 570 && x.p.minutes < 960; });
            // Latest date that actually traded regular hours (pre-market bars of a
            // new day must not replace yesterday's full session).
            var day = (rth.length ? rth : tagged)[(rth.length ? rth : tagged).length - 1].p.date;
            return (rth.length ? rth : tagged).filter(function (x) { return x.p.date === day; }).map(function (x) { return x.b; });
        },
        /** ISO start (UTC) 5 calendar days back — enough to always contain the last session. */
        intradayStart: function () {
            return new Date(Date.now() - 5 * 86400000).toISOString().slice(0, 10);
        },
        /** True when /assets/logos/{file}.svg exists — so unknown tickers go straight
            to the CDN instead of producing a guaranteed local 404 (audit D13). */
        hasLocalLogo: function (file) { return LOCAL_LOGOS.indexOf(String(file || "").toUpperCase()) !== -1; },
        /** Signal-engine reasons: the momentum factor is a 1M/3M/6M composite — say so. */
        reason: function (s) {
            return String(s == null ? "" : s).replace(/\b(Positive|Negative) momentum \(/g, "$1 composite momentum (");
        }
    };

    // ── PAPER tag in the shared header (audit N7): every page states, next to the
    // wordmark, that these are paper (simulated-money) accounts.
    function addPaperTag() {
        document.querySelectorAll(".site-nav a.brand, nav a.brand").forEach(function (brand) {
            if (brand.querySelector(".at-paper-tag")) return;
            var tag = document.createElement("span");
            tag.className = "at-paper-tag";
            tag.textContent = "Paper";
            tag.setAttribute("title", "Paper trading — simulated money, not real capital");
            tag.setAttribute("aria-label", "Paper trading account");
            brand.appendChild(tag);
        });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addPaperTag);
    else addPaperTag();

    // ── Logo fallback (D13): when a ticker logo is missing locally AND on the CDN,
    // swap the broken <img> for a brand-styled initials tile instead of a 404 glyph.
    // Capture phase on document sees every <img> error (error events don't bubble).
    function isLogoSrc(src) { return /\/assets\/logos\/|img\.logo\.dev/.test(src || ""); }
    function initialsTile(img) {
        var fromSrc = ((img.currentSrc || img.src || "").match(/(?:\/logos\/|\/ticker\/)([A-Za-z0-9._-]+?)(?:\.svg|\.png|\?|$)/) || [])[1] || "";
        var sym = (img.getAttribute("alt") || img.dataset.sym || fromSrc.split(/[_-]/)[0]).toUpperCase().replace(/[^A-Z0-9]/g, "");
        var tile = document.createElement("span");
        // Declared size first: a broken image's live box is the alt-text box, not its slot.
        var w = parseInt(img.getAttribute("width"), 10) || parseInt(img.style.width, 10) || img.width || 28;
        tile.className = "at-logo-fallback";
        tile.setAttribute("role", "img");
        tile.setAttribute("aria-label", sym || "logo");
        tile.textContent = sym.slice(0, w >= 40 ? 4 : 3) || "•";
        tile.style.width = w + "px";
        tile.style.height = w + "px";
        tile.style.fontSize = Math.max(7, Math.round(w * (tile.textContent.length > 2 ? 0.28 : 0.36))) + "px";
        if (img.id) tile.id = img.id;
        var cs = img.getAttribute("style");
        if (cs && /margin|vertical-align|flex-shrink/.test(cs)) {
            ["margin-right", "margin-left", "margin-inline-end", "margin-inline-start", "vertical-align"].forEach(function (p) {
                var m = img.style.getPropertyValue(p);
                if (m) tile.style.setProperty(p, m);
            });
        }
        return tile;
    }
    document.addEventListener("error", function (e) {
        var img = e.target;
        if (!img || img.tagName !== "IMG" || !isLogoSrc(img.currentSrc || img.src)) return;
        // An element-level onerror still pending means the CDN step has not run yet.
        if (typeof img.onerror === "function") return;
        if (img.id) {
            // Persistent element (e.g. a hero logo reused across symbols): hide, and
            // show a sibling tile instead of replacing the node scripts hold a ref to.
            img.style.display = "none";
            var prev = img.nextElementSibling;
            if (prev && prev.classList.contains("at-logo-fallback")) prev.remove();
            var t = initialsTile(img);
            t.removeAttribute("id");
            t.dataset.for = img.id;
            img.insertAdjacentElement("afterend", t);
            img.addEventListener("load", function onLoad() {
                var s = img.nextElementSibling;
                if (s && s.dataset.for === img.id) s.remove();
            }, { once: true });
            return;
        }
        if (img.parentNode) img.parentNode.replaceChild(initialsTile(img), img);
    }, true);
}());
