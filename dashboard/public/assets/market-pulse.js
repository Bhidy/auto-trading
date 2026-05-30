/**
 * market-pulse.js — US Market Pulse Terminal Controller v3.
 * Restructured with dynamic Order Entries, range slider calculations, My Positions mapping,
 * and high-fidelity Revenue growth grids in English & Arabic LTR/RTL layouts.
 */
(function () {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';
    var activeSymbol = 'NVDA';
    var activeDetailTab = 'Overview';
    var activeListTab = 'Watchlist';
    var activeTopTab = 'Active';

    var detailChart = null;
    var sparklineChart = null;
    var sectorChart = null;
    var revenueChartInstance = null;
    var stockPriceDatabase = {};
    var priceTickInterval = null;
    var quotesRefreshInterval = null;
    var globalQuotesCache = {};

    // Curated data-feed universe — these are the symbols the system collects
    // daily bars for (CHART_CORE in scripts/collect_market_history.py, backfilled
    // ~2y into Supabase) and serves live via the Alpaca quote/chart endpoints.
    // Crypto pairs are intentionally excluded (handled by the Crypto Terminal).
    var watchlistSymbols = [
        'SPY', 'QQQ', 'DIA', 'IWM',
        'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AMD', 'NFLX', 'INTC',
        'XLK', 'XLE', 'XLF', 'XLV', 'XLY', 'XLI', 'XLU', 'XLP', 'XLB', 'XLRE', 'XLC',
        'TLT', 'GLD', 'SHY', 'BIL'
    ];
    var allSymbols = watchlistSymbols.slice();
    var sectorETFs = ['XLK', 'XLF', 'XLE', 'XLV', 'XLY', 'XLI', 'XLC', 'XLB', 'XLU', 'XLRE'];
    var portfolioHoldings = {};

    var companyNames = {
        AAPL: 'Apple Inc.', NVDA: 'NVIDIA Corporation', MSFT: 'Microsoft Corporation',
        GOOGL: 'Alphabet Inc.', AMZN: 'Amazon.com, Inc.', TSLA: 'Tesla, Inc.',
        META: 'Meta Platforms, Inc.', AMD: 'Advanced Micro Devices', NFLX: 'Netflix, Inc.',
        INTC: 'Intel Corporation', SPY: 'SPDR S&P 500 ETF', QQQ: 'Invesco QQQ Trust', DIA: 'SPDR Dow ETF',
        IWM: 'iShares Russell 2000 ETF',
        XLK: 'Technology Select Sector', XLE: 'Energy Select Sector', XLF: 'Financial Select Sector',
        XLV: 'Health Care Select Sector', XLY: 'Consumer Discretionary', XLI: 'Industrial Select Sector',
        XLU: 'Utilities Select Sector', XLP: 'Consumer Staples Select', XLB: 'Materials Select Sector',
        XLRE: 'Real Estate Select Sector', XLC: 'Communication Svcs Select',
        TLT: 'iShares 20+ Yr Treasury', GLD: 'SPDR Gold Shares',
        SHY: 'iShares 1-3 Yr Treasury', BIL: 'SPDR 1-3 Mo T-Bill ETF'
    };

    /* ─── Nav & Terminal Translations ─────────────────────────────────── */
    var NAV = {
        en: { nav_pf1: 'Self Improving Brain', nav_pf2: 'Capitol Shadow', nav_pf3: 'Cautious Sniper', nav_market_pulse: 'Market Pulse', nav_trading: 'Trading', nav_orders: 'Orders', nav_crypto: 'Crypto Terminal', nav_options: 'Options Lab', nav_screener: 'Screener', nav_history: 'Account History' },
        ar: { nav_pf1: 'الدماغ ذاتي التحسين', nav_pf2: 'ظل الكابيتول', nav_pf3: 'القناص الحذر', nav_market_pulse: 'نبض السوق', nav_trading: 'التداول', nav_orders: 'الأوامر', nav_crypto: 'محطة العملات الرقمية', nav_options: 'مختبر الخيارات', nav_screener: 'فلتر الأسهم', nav_history: 'سجل الحساب' }
    };

    var T = {
        en: {
            title_pulse: 'US Market Pulse', title_desc: 'Institutional Terminal Dashboard',
            lbl_sp500: 'S&P 500 Index', lbl_sp500_mini: 'S&P 500 (SPY) Sparkline',
            lbl_adv_dec: 'Advancers / Decliners', lbl_bullish_bias: 'Bullish Bias',
            lbl_val: 'Trading Value', lbl_vol: 'Trading Volume', lbl_shares: 'shares',
            search_placeholder: 'Search US Symbol (e.g. AAPL, NVDA, TSLA)',
            tab_wl: 'Watchlist', tab_portfolios: 'My Portfolios',
            title_scope: 'US Market Scope', scope_securities: 'Listed Securities',
            scope_val: 'Trading Value', scope_vol: 'Trading Volume',
            scope_adv: 'Advancers', scope_dec: 'Decliners',
            scope_desc: 'More listed US tech and growth equities advanced than declined.',
            stat_open: 'Open', stat_high: 'High', stat_low: 'Low', stat_close: 'Close', stat_vol: 'Volume',
            chart_title: '60-Day Technical Close Chart',
            pane_overview: 'Chart', pane_options: 'Options', pane_news: 'News',
            pane_financials_tab: 'Financials', pane_profile_tab: 'Specs',
            lbl_market_clock: 'Market Clock',
            lbl_realtime: 'Real-Time Feed via Alpaca API', tab_active: 'Most Active',
            tab_gainers: 'Top Gainers', tab_losers: 'Top Losers',
            title_news: 'Market News Feed', lbl_viewall: 'View All',
            empty_portfolio_state: 'Loading portfolio holdings from Alpaca...', lbl_l2_title: 'L2 Order Book',
            lbl_sectors: 'US Sector Performance', lbl_portfolios_overview: 'Live Portfolio Overview',
            loading: 'Loading live data...',
            lbl_key_fin: 'Key Financials',
            lbl_largecap: 'Large Cap',
            lbl_orderbook: 'Order Book',
            lbl_signals: 'Portfolio Signals',
            lbl_52week: '52 Week Range', lbl_dayrange: 'Day Range', lbl_spread: 'Spread'
        },
        ar: {
            title_pulse: 'نبض السوق الأمريكي', title_desc: 'لوحة معلومات المحطة المؤسسية',
            lbl_sp500: 'مؤشر إس آند بي 500', lbl_sp500_mini: 'مؤشر إس آند بي 500 (SPY)',
            lbl_adv_dec: 'الأسهم الصاعدة / الهابطة', lbl_bullish_bias: 'انحياز صعودي',
            lbl_val: 'قيمة التداول', lbl_vol: 'حجم التداول', lbl_shares: 'سهم',
            search_placeholder: 'ابحث عن رمز أمريكي (مثل AAPL, NVDA)',
            tab_wl: 'قائمة المراقبة', tab_portfolios: 'محافظي الاستثمارية',
            title_scope: 'نطاق السوق الأمريكي', scope_securities: 'الأوراق المالية المدرجة',
            scope_val: 'قيمة التداول', scope_vol: 'حجم التداول',
            scope_adv: 'الصاعدة', scope_dec: 'الهابطة',
            scope_desc: 'ارتفعت أوراق مالية أمريكية في قطاع التكنولوجيا والنمو أكثر مما تراجعت.',
            stat_open: 'افتتاح', stat_high: 'أعلى', stat_low: 'أدنى', stat_close: 'إغلاق', stat_vol: 'حجم',
            chart_title: 'مخطط الإغلاق الفني لمدة 60 يومًا',
            pane_overview: 'الرسم البياني', pane_options: 'عقود الخيارات', pane_news: 'الأخبار',
            pane_financials_tab: 'البيانات المالية', pane_profile_tab: 'المواصفات',
            lbl_market_clock: 'ساعة السوق',
            lbl_realtime: 'تغذية الأسعار الفورية عبر Alpaca', tab_active: 'الأكثر نشاطًا',
            tab_gainers: 'الأعلى ارتفاعًا', tab_losers: 'الأكثر انخفاضًا',
            title_news: 'تغذية أخبار السوق', lbl_viewall: 'عرض الكل',
            empty_portfolio_state: 'جاري تحميل بيانات المحفظة من Alpaca...', lbl_l2_title: 'كتاب الأوامر L2',
            lbl_sectors: 'أداء القطاعات الأمريكية', lbl_portfolios_overview: 'نظرة عامة على المحافظ',
            loading: 'جاري تحميل البيانات المباشرة...',
            lbl_key_fin: 'البيانات المالية الرئيسية',
            lbl_largecap: 'قيمة سوقية كبرى',
            lbl_orderbook: 'دفتر الأوامر',
            lbl_signals: 'إشارات المحفظة الذكية',
            lbl_52week: 'نطاق 52 أسبوعاً', lbl_dayrange: 'نطاق اليوم', lbl_spread: 'الفارق'
        }
    };

    function t(key) { return (T[lang] || T.en)[key] || key; }

    function applyTranslations(l) {
        var map = T[l] || T.en;
        var navMap = NAV[l] || NAV.en;
        document.querySelectorAll('[data-key]').forEach(function (el) {
            var k = el.dataset.key;
            if (map[k]) { el.tagName === 'INPUT' ? (el.placeholder = map[k]) : (el.innerHTML = map[k]); }
            else if (navMap[k]) { el.textContent = navMap[k]; }
        });
    }

    function applyNavLang(l) {
        var navMap = NAV[l] || NAV.en;
        document.querySelectorAll('[data-key]').forEach(function (el) {
            if (navMap[el.dataset.key]) el.textContent = navMap[el.dataset.key];
        });
    }

    /* ─── Chart.js CDN Check ─────────────────────────────────────────── */
    function checkChartLoaded(callback) {
        if (window.Chart) { callback(); }
        else { setTimeout(function () { checkChartLoaded(callback); }, 100); }
    }

    /* ─── Format Helpers ─────────────────────────────────────────────── */
    function fmtPrice(n) { return '$' + parseFloat(n).toFixed(2); }
    function fmtPct(n, forceSign) {
        var v = parseFloat(n) || 0;
        return (forceSign !== false && v >= 0 ? '+' : '') + v.toFixed(2) + '%';
    }
    function fmtVol(v) {
        v = parseInt(v) || 0;
        if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
        if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
        if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
        return String(v);
    }
    function fmtMoney(n) {
        n = parseFloat(n) || 0;
        if (Math.abs(n) >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
        if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
        if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
        return '$' + n.toFixed(2);
    }
    // A bid/ask is only shown when it forms a sane NBBO. The free IEX feed can
    // return a stale/crossed ask (e.g. a 7%+ spread on a liquid name); we never
    // surface that as if it were a real two-sided market.
    function plausibleQuote(db, ref) {
        if (!db || !db.bid || !db.ask || db.ask < db.bid) return false;
        var mid = ref || db.price || ((db.bid + db.ask) / 2);
        if (!mid) return false;
        return (db.ask - db.bid) <= mid * 0.02;
    }

    /* ─── Fetch Utilities ────────────────────────────────────────────── */
    async function apiFetch(url) {
        try {
            var r = await fetch(url, { cache: 'no-store' });
            if (!r.ok) throw new Error(r.status);
            return await r.json();
        } catch (e) {
            console.warn('API fetch error for', url, e.message);
            return null;
        }
    }

    /* ─── Load & Render SPY Sparkline ────────────────────────────────── */
    async function loadAndRenderSpySparkline() {
        var canvas = document.getElementById('spySparklineCanvas');
        if (!canvas) return;
        var spyBars = await apiFetch('/api/market/bars/SPY?timeframe=5Min&limit=78');
        var points, labels;
        if (spyBars && spyBars.length > 0) {
            points = spyBars.map(function (b) { return parseFloat(b.c); });
            labels = spyBars.map(function (b) { return b.t ? b.t.slice(11, 16) : ''; });
        } else {
            var ctxFallback = canvas.getContext('2d');
            if (ctxFallback) {
                ctxFallback.font = '10px Manrope';
                ctxFallback.fillStyle = getTheme() === 'dark' ? '#a39a92' : '#7a6b5e';
                ctxFallback.textAlign = 'center';
                ctxFallback.fillText('SPY intraday chart — market closed', canvas.width / 2, canvas.height / 2);
            }
            return;
        }
        var ctx = canvas.getContext('2d');
        if (sparklineChart) sparklineChart.destroy();
        var gradient = ctx.createLinearGradient(0, 0, 0, 90);
        gradient.addColorStop(0, 'rgba(229, 90, 31, 0.28)');
        gradient.addColorStop(1, 'rgba(229, 90, 31, 0.00)');
        sparklineChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{ data: points, borderColor: '#E55A1F', borderWidth: 2.5, fill: true, backgroundColor: gradient, tension: 0.3, pointRadius: 0 }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: {
                    callbacks: {
                        label: function(ctx) { return '$' + ctx.raw.toFixed(2); }
                    }
                }},
                scales: { x: { display: false }, y: { display: false } }
            }
        });

        // Update SPY % change in header
        if (points.length >= 2) {
            var first = points[0], last = points[points.length - 1];
            var pctChg = ((last - first) / first) * 100;
            var spyPctEl = document.getElementById('spyPctChange');
            if (spyPctEl) {
                spyPctEl.textContent = (pctChg >= 0 ? '+' : '') + pctChg.toFixed(2) + '%';
                spyPctEl.className = 'pf-num ' + (pctChg >= 0 ? 'pf-pos' : 'pf-neg');
            }
        }
    }

    /* ─── Load Real Quote Data for All Symbols ───────────────────────── */
    async function loadRealQuotes(symbols) {
        var data = await apiFetch('/api/market/quotes?symbols=' + (symbols || allSymbols).join(','));
        if (!data) return;
        Object.entries(data).forEach(function ([sym, q]) {
            stockPriceDatabase[sym] = {
                price: q.price || 0,
                changePct: q.changePct || 0,
                change: q.change || 0,
                open: q.open || q.price,
                high: q.high || q.price,
                low: q.low || q.price,
                close: q.close || q.price,
                volume: q.volume || 0,
                prev: q.price / (1 + (q.changePct || 0) / 100),
                bid: q.bid || 0,
                ask: q.ask || 0,
                bidSize: q.bidSize || 0,
                askSize: q.askSize || 0
            };
        });
    }

    /* ─── Load Sector Performance Heatmap (flicker-free in-place updates) ── */
    var _sectorsBuilt = false;
    async function loadAndRenderSectors() {
        var container = document.getElementById('sectorContainer');
        if (!container) return;
        if (!_sectorsBuilt) container.innerHTML = '<div style="color:var(--muted);font-size:0.78rem;padding:0.5rem;">' + t('loading') + '</div>';

        var data = await apiFetch('/api/market/sectors');
        if (!data) return;

        var sorted = Object.entries(data).sort(function (a, b) { return b[1].changePct - a[1].changePct; });
        var maxAbs = Math.max(...sorted.map(function (e) { return Math.abs(e[1].changePct); }), 1);

        // Build the row skeletons once; subsequent refreshes patch values in
        // place (no innerHTML clear) so the panel never blinks.
        if (!_sectorsBuilt) {
            container.innerHTML = '';
            sorted.forEach(function ([sym]) {
                var row = document.createElement('div');
                row.setAttribute('data-sym', sym);
                row.style.cssText = 'display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0;';
                row.innerHTML =
                    '<span class="mp-sec-name" style="font-family:var(--pf-ui);font-size:0.7rem;font-weight:700;color:var(--ink);min-width:105px;text-align:start;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></span>' +
                    '<div style="flex:1;height:12px;background:rgba(148,163,184,0.08);border-radius:4px;overflow:hidden;position:relative;"><div class="mp-sec-bar" style="height:100%;width:0%;border-radius:4px;transition:width 0.5s ease;"></div></div>' +
                    '<span class="mp-sec-pct pf-num" style="font-family:var(--pf-mono);font-size:0.7rem;font-weight:700;min-width:52px;text-align:end;"></span>';
                container.appendChild(row);
            });
            _sectorsBuilt = true;
        }

        sorted.forEach(function ([sym, sec]) {
            var row = container.querySelector('[data-sym="' + sym + '"]');
            if (!row) return;
            var pct = parseFloat(sec.changePct) || 0;
            var isPos = pct >= 0;
            row.querySelector('.mp-sec-name').textContent = sec.name || sym;
            var bar = row.querySelector('.mp-sec-bar');
            bar.style.width = Math.min(Math.abs(pct) / maxAbs * 100, 100) + '%';
            bar.style.background = isPos ? 'rgba(46,204,113,0.7)' : 'rgba(231,76,60,0.7)';
            var pe = row.querySelector('.mp-sec-pct');
            pe.textContent = (isPos ? '+' : '') + pct.toFixed(2) + '%';
            pe.className = 'mp-sec-pct pf-num ' + (isPos ? 'pf-pos' : 'pf-neg');
            container.appendChild(row); // reorder to match live ranking
        });

        // Real market-breadth insight derived from live sector data.
        var insightEl = document.getElementById('marketInsightsText');
        if (insightEl && sorted.length) {
            var pos = sorted.filter(function (e) { return e[1].changePct >= 0; }).length;
            var lead = sorted[0], lag = sorted[sorted.length - 1];
            var leadN = lead[1].name || lead[0], lagN = lag[1].name || lag[0];
            var leadP = (lead[1].changePct >= 0 ? '+' : '') + lead[1].changePct.toFixed(2) + '%';
            var lagP = lag[1].changePct.toFixed(2) + '%';
            insightEl.textContent = (lang === 'ar'
                ? (pos + ' من ' + sorted.length + ' قطاعات أمريكية مرتفعة اليوم. يتصدّر ' + leadN + ' (' + leadP + ') ويتراجع ' + lagN + ' (' + lagP + ').')
                : (pos + ' of ' + sorted.length + ' US sectors advancing today. ' + leadN + ' leads (' + leadP + ') while ' + lagN + ' lags (' + lagP + ').'));
        }
    }

    /* ─── Portfolio Signals — real engine output from P1 ─────────────── */
    async function loadPortfolioSignals() {
        var c = document.getElementById('portfolioSignalsContainer');
        if (!c) return;
        var data = await apiFetch('/api/portfolio/portfolio_1/details');
        var sigs = (data && data.signals && Array.isArray(data.signals.signals)) ? data.signals.signals : [];
        var actionable = sigs.filter(function (s) { return s.signal === 'BUY' || s.signal === 'SELL'; })
            .sort(function (a, b) { return Math.abs(b.score || 0) - Math.abs(a.score || 0); }).slice(0, 5);
        if (!actionable.length) actionable = sigs.slice().sort(function (a, b) { return Math.abs(b.score || 0) - Math.abs(a.score || 0); }).slice(0, 4);
        if (!actionable.length) {
            c.innerHTML = '<div style="color:var(--muted);font-size:0.75rem;padding:0.75rem 0.25rem;">' + (lang === 'ar' ? 'لا توجد إشارات نشطة من المحرك حالياً.' : 'No active engine signals right now.') + '</div>';
            return;
        }
        c.innerHTML = actionable.map(function (s) {
            var sc = s.score || 0, mag = Math.abs(sc);
            var conv = mag >= 0.7 ? 'high' : mag >= 0.4 ? 'med' : 'low';
            var convLabel = lang === 'ar'
                ? (conv === 'high' ? 'قناعة عالية' : conv === 'med' ? 'قناعة متوسطة' : 'قناعة منخفضة')
                : (conv === 'high' ? 'High Conviction' : conv === 'med' ? 'Medium Conviction' : 'Low Conviction');
            var sideCls = s.signal === 'BUY' ? 'pf-pos' : 'pf-neg';
            var sideTxt = s.signal === 'BUY' ? (lang === 'ar' ? 'شراء' : 'BUY') : (lang === 'ar' ? 'بيع' : 'SELL');
            var reason = (s.reasons && s.reasons[0]) ? String(s.reasons[0]) : '';
            return '<div class="ai-signal-card" style="cursor:pointer;" data-sym="' + s.symbol + '">' +
                '<div>' +
                    '<span style="font-family:var(--pf-mono); font-weight:800; font-size:0.75rem; color:var(--ink);">' + s.symbol + '</span>' +
                    '<span class="' + sideCls + '" style="font-size:0.62rem;font-weight:800;margin-inline-start:0.4rem;">' + sideTxt + ' · ' + sc.toFixed(2) + '</span>' +
                    '<p style="font-size:0.68rem; color:var(--muted); margin-top:0.35rem; line-height:1.45;">' + reason + '</p>' +
                '</div>' +
                '<span class="ai-badge ' + conv + '">' + convLabel + '</span>' +
            '</div>';
        }).join('');
        c.querySelectorAll('.ai-signal-card').forEach(function (card) {
            card.addEventListener('click', function () { var sym = card.getAttribute('data-sym'); if (sym) loadStockDetails(sym); });
        });
    }

    /* ─── Load Portfolio Overview Cards ──────────────────────────────── */
    async function loadAndRenderPortfolioCards() {
        var container = document.getElementById('portfolioCardsContainer');
        if (!container) return;
        container.innerHTML = '<div style="color:var(--muted);font-size:0.78rem;padding:0.5rem 0;">Loading live portfolio data...</div>';
        var data = await apiFetch('/api/portfolios/overview');
        if (!data || !Array.isArray(data)) return;

        container.innerHTML = '';
        data.forEach(function (pf) {
            var pctClass = pf.dayPnlPct >= 0 ? 'pf-pos' : 'pf-neg';
            var totalClass = pf.totalReturn >= 0 ? 'pf-pos' : 'pf-neg';
            var arrow = pf.dayPnlPct >= 0 ? '▲' : '▼';
            var card = document.createElement('a');
            card.href = '/portfolio-detail.html?id=' + pf.id;
            card.style.cssText = 'display:flex;flex-direction:column;gap:0.4rem;padding:0.85rem;background:var(--page);border:1px solid rgba(229,90,31,0.12);border-radius:var(--pf-radius-sm);cursor:pointer;text-decoration:none;transition:all 180ms;';
            card.addEventListener('mouseenter', function() { this.style.borderColor = 'var(--teal)'; this.style.background = 'var(--teal-soft)'; });
            card.addEventListener('mouseleave', function() { this.style.borderColor = 'rgba(229,90,31,0.12)'; this.style.background = 'var(--page)'; });
            card.innerHTML = `
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <span style="font-size:0.68rem;font-weight:800;text-transform:uppercase;color:var(--teal-dark);letter-spacing:0.04em;">${pf.label}</span>
                    <span style="display:inline-flex;align-items:center;gap:0.2rem;font-size:0.6rem;font-weight:700;padding:0.1rem 0.4rem;border-radius:99px;background:${pf.liveConnected ? 'rgba(34,197,94,0.1)' : 'rgba(148,163,184,0.1)'};color:${pf.liveConnected ? 'var(--pf-green)' : 'var(--muted)'};border:1px solid ${pf.liveConnected ? 'rgba(34,197,94,0.2)' : 'var(--line)'};">
                        <span style="width:4px;height:4px;border-radius:50%;background:currentColor;display:inline-block;"></span>
                        ${pf.liveConnected ? 'LIVE' : 'LOCAL'}
                    </span>
                </div>
                <div style="font-family:var(--pf-mono);font-size:1.1rem;font-weight:700;color:var(--ink);">${fmtMoney(pf.equity)}</div>
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <span class="pf-num ${pctClass}" style="font-size:0.72rem;font-weight:700;">${arrow} ${Math.abs(pf.dayPnlPct).toFixed(2)}% today</span>
                    <span class="pf-num ${totalClass}" style="font-size:0.68rem;font-weight:600;">${(pf.totalReturn >= 0 ? '+' : '') + pf.totalReturn.toFixed(2)}% total</span>
                </div>
                <div style="font-size:0.62rem;color:var(--muted);">${pf.positions} position${pf.positions !== 1 ? 's' : ''} · ${fmtMoney(pf.cash)} cash</div>
            `;
            container.appendChild(card);
        });

        data.forEach(function (pf) { portfolioHoldings[pf.id] = pf; });
    }

    // Reflects whether the active symbol is in the watchlist on the favorite
    // star (filled solar orange when present, original outline when not).
    function updateFavoriteStar() {
        var favBtn = document.getElementById('btnToggleFavorite');
        if (!favBtn) return;
        var inList = watchlistSymbols.indexOf(activeSymbol) !== -1;
        favBtn.classList.toggle('active', inList);
        favBtn.title = inList ? 'Remove from watchlist' : 'Add to watchlist';
    }

    /* ─── Stock Details Workspace Loader ────────────────────────────── */
    async function loadStockDetails(symbol) {
        activeSymbol = symbol.toUpperCase();
        updateFavoriteStar();

        var priceEl = document.getElementById('heroPrice');
        var chgEl = document.getElementById('heroPriceChg');
        if (priceEl) priceEl.textContent = '...';
        if (chgEl) chgEl.textContent = 'Loading...';

        try {
            var data = await apiFetch('/api/stock/' + activeSymbol + '/details');
            if (!data) throw new Error('No data');

            // Ensure a full live quote (OHLC / bid / ask / volume) from /api/market/quotes.
            // The /details endpoint carries no OHLC and (on the free tier) no bars,
            // so the quotes feed is the real source for the stat row.
            var qdb = stockPriceDatabase[activeSymbol];
            if (!qdb || qdb.open === undefined) {
                await loadRealQuotes([activeSymbol]);
                qdb = stockPriceDatabase[activeSymbol];
            }
            var profile = data.profile || {};

            document.getElementById('heroSymbol').textContent = data.symbol;
            document.getElementById('heroName').textContent = (profile.name || data.symbol)
                .replace(/\s+(Class [A-C] )?Common (Stock|Shares)$/i, '').trim() || data.symbol;
            var exEl = document.getElementById('heroExchange');
            if (exEl) exEl.textContent = profile.exchange || '';
            var subTxt = profile.sector || '';
            if (!subTxt && profile.asset_class) {
                subTxt = profile.asset_class === 'us_equity' ? 'US Equity'
                       : profile.asset_class === 'crypto' ? 'Crypto'
                       : String(profile.asset_class).replace(/_/g, ' ');
            }
            document.getElementById('heroSub').textContent = subTxt;

            var price = (qdb && qdb.price) ? qdb.price
                       : (data.quote && data.quote.price ? parseFloat(data.quote.price) : 0);
            var prevClose = (qdb && qdb.close) ? qdb.close
                       : (data.quote && data.quote.prev ? parseFloat(data.quote.prev) : price);
            var change = (qdb && qdb.change !== undefined) ? qdb.change : (price - prevClose);
            var changePct = (qdb && qdb.changePct !== undefined) ? qdb.changePct
                       : (prevClose > 0 ? (change / prevClose) * 100 : 0);

            document.getElementById('heroPrice').textContent = price ? fmtPrice(price) : '—';
            chgEl.className = 'mp-hero-price-chg pf-num ' + (change >= 0 ? 'pf-pos' : 'pf-neg');
            chgEl.textContent = price ? ((change >= 0 ? '▲ +' : '▼ ') + Math.abs(change).toFixed(2) + ' (' + Math.abs(changePct).toFixed(2) + '%)') : '';

            // Live stat row — real Alpaca quote fields only (no fabricated fallbacks).
            function setStat(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; }
            if (qdb && qdb.open !== undefined) {
                setStat('statOpen',  qdb.open  ? fmtPrice(qdb.open)  : '—');
                setStat('statHigh',  qdb.high  ? fmtPrice(qdb.high)  : '—');
                setStat('statLow',   qdb.low   ? fmtPrice(qdb.low)   : '—');
                setStat('statClose', qdb.close ? fmtPrice(qdb.close) : '—');
                setStat('statVolume', qdb.volume ? fmtVol(qdb.volume) : '—');
                var sane = plausibleQuote(qdb, price);
                setStat('statBid', sane ? fmtPrice(qdb.bid) : '—');
                setStat('statAsk', sane ? fmtPrice(qdb.ask) : '—');
                setStat('statSpread', sane ? '$' + (qdb.ask - qdb.bid).toFixed(2) : '—');
            } else {
                ['statOpen','statHigh','statLow','statClose','statVolume','statBid','statAsk','statSpread']
                    .forEach(function (id) { setStat(id, '—'); });
            }

            // Sync the order-form limit price with the live last price.
            var orderLimit = document.getElementById('orderLimitPriceInput');
            if (orderLimit && price) { orderLimit.value = price.toFixed(2); orderLimit.placeholder = price.toFixed(2); }

            // Day range (real) — from the quote's session high/low.
            var dayLow = (qdb && qdb.low) ? qdb.low : null;
            var dayHigh = (qdb && qdb.high) ? qdb.high : null;
            var drLabel = document.getElementById('dayRangeLabel');
            var drHandle = document.getElementById('dayRangeHandle');
            var drFill = document.getElementById('dayRangeFill');
            if (dayLow && dayHigh && dayHigh > dayLow) {
                if (drLabel) drLabel.textContent = '$' + dayLow.toFixed(2) + ' - $' + dayHigh.toFixed(2);
                var dp = Math.max(0, Math.min(100, ((price - dayLow) / (dayHigh - dayLow)) * 100));
                if (drHandle) drHandle.style.left = dp + '%';
                if (drFill) { drFill.style.left = '0%'; drFill.style.right = (100 - dp) + '%'; }
            } else if (drLabel) {
                drLabel.textContent = '—';
            }

            document.getElementById('l2TickerName').textContent = activeSymbol;
            renderOrderBook(price);
            renderKeyFinancials(activeSymbol, profile);
            renderPositionsTable();
            loadFiftyTwoWeekRange(activeSymbol);

            // Merge (never replace) so OHLC / bid / ask survive for live ticks.
            stockPriceDatabase[activeSymbol] = Object.assign(stockPriceDatabase[activeSymbol] || {}, { price: price, changePct: changePct, prev: prevClose });
            updateSelectedListStyles();

            if (window.loadChartForPeriod) loadChartForPeriod('1D');
        } catch (e) {
            console.error('Error loading stock details for ' + activeSymbol, e);
        }
    }

    /* ─── 52-Week Range — real, from 1Y daily bars (Supabase fallback) ──── */
    async function loadFiftyTwoWeekRange(symbol) {
        var block = document.getElementById('week52Block');
        var label = document.getElementById('week52Label');
        var fill = document.getElementById('week52Fill');
        var handle = document.getElementById('week52Handle');
        if (!label) return;

        var d = new Date(); d.setFullYear(d.getFullYear() - 1);
        var start = d.toISOString().slice(0, 10);

        var bars = await apiFetch('/api/market/bars/' + symbol + '?timeframe=1Day&limit=400&start=' + start);
        var lows = [], highs = [], lastClose = null;
        if (bars && bars.length) {
            bars.forEach(function (b) { lows.push(parseFloat(b.l)); highs.push(parseFloat(b.h)); lastClose = parseFloat(b.c); });
        } else {
            var rows = await apiFetch('/api/supabase/market?symbol=' + symbol + '&start=' + start + '&limit=400');
            if (rows && rows.length) {
                rows.forEach(function (r) { lows.push(parseFloat(r.low_price)); highs.push(parseFloat(r.high_price)); lastClose = parseFloat(r.close_price); });
            }
        }
        lows = lows.filter(isFinite); highs = highs.filter(isFinite);
        if (!lows.length || !highs.length) {
            // No real history available → hide the block (never show fabricated range).
            if (block) block.style.display = 'none';
            return;
        }
        if (block) block.style.display = '';
        var lo = Math.min.apply(null, lows), hi = Math.max.apply(null, highs);
        var cur = (stockPriceDatabase[symbol] && stockPriceDatabase[symbol].price) ? stockPriceDatabase[symbol].price : lastClose;
        label.textContent = '$' + lo.toFixed(2) + ' - $' + hi.toFixed(2);
        var pct = hi > lo ? Math.max(0, Math.min(100, ((cur - lo) / (hi - lo)) * 100)) : 50;
        if (handle) handle.style.left = pct + '%';
        if (fill) { fill.style.left = '0%'; fill.style.right = (100 - pct) + '%'; }
    }

    function renderKeyFinancials(symbol, profile) {
        var body = document.getElementById('keyFinancialsBody');
        if (!body) return;
        body.innerHTML = `
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:0.45rem 0.55rem; font-weight:600; color:var(--ink);">Exchange</td>
                <td style="padding:0.45rem 0.55rem; text-align:right; font-family:var(--pf-mono);" colspan="2">${profile.exchange || '—'}</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:0.45rem 0.55rem; font-weight:600; color:var(--ink);">Asset Class</td>
                <td style="padding:0.45rem 0.55rem; text-align:right; font-family:var(--pf-mono);" colspan="2">${profile.asset_class || '—'}</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:0.45rem 0.55rem; font-weight:600; color:var(--ink);">Tradable</td>
                <td style="padding:0.45rem 0.55rem; text-align:right; font-family:var(--pf-mono);" colspan="2">${profile.tradable === undefined ? '—' : (profile.tradable ? 'Yes' : 'No')}</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:0.45rem 0.55rem; font-weight:600; color:var(--ink);">Shortable</td>
                <td style="padding:0.45rem 0.55rem; text-align:right; font-family:var(--pf-mono);" colspan="2">${profile.shortable === undefined ? '—' : (profile.shortable ? 'Yes' : 'No')}</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                <td style="padding:0.45rem 0.55rem; font-weight:600; color:var(--ink);">Fractionable</td>
                <td style="padding:0.45rem 0.55rem; text-align:right; font-family:var(--pf-mono);" colspan="2">${profile.fractionable === undefined ? '—' : (profile.fractionable ? 'Yes' : 'No')}</td>
            </tr>
        `;
    }

    var positionsLoaded = false;

    function renderPositionsTable() {
        var body = document.getElementById('myPositionsBody');
        if (!body) return;

        if (positionsLoaded) {
            tickPriceUpdates();
            return;
        }

        body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:2rem;">Loading positions from Alpaca...</td></tr>';

        apiFetch('/api/portfolio/portfolio_1/details').then(function(data) {
            if (!data || !data.positions || !data.positions.length) {
                if (!positionsLoaded) body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:2rem;">No positions loaded.</td></tr>';
                return;
            }

            positionsLoaded = true;
            var totalMktVal = 0, totalPnl = 0, totalCost = 0;
            var cash = data.account ? data.account.cash : 0;
            var portfolioValue = data.account ? data.account.portfolio_value || data.account.equity : 0;
            var html = '';

            data.positions.forEach(function(p, idx) {
                var qty = p.quantity || 0;
                var avg = p.avgCost || 0;
                var sym = p.symbol;
                var price = stockPriceDatabase[sym] ? stockPriceDatabase[sym].price : (p.lastPrice || avg);
                var mktVal = qty * price;
                var costBasis = p.cost_basis || (qty * avg);
                var pnl = mktVal - costBasis;
                var pnlPct = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
                totalMktVal += mktVal;
                totalPnl += pnl;
                totalCost += costBasis;

                var sign = pnl >= 0 ? '▲' : '▼';
                var cls = pnl >= 0 ? 'pf-pos' : 'pf-neg';
                var hiddenCls = idx >= 10 ? ' pf-pos-extra' : '';
                html += '<tr class="' + hiddenCls + '">' +
                    '<td style="font-weight:800;font-family:var(--pf-mono);cursor:pointer;" onclick="document.dispatchEvent(new CustomEvent(\'mp:selectSymbol\',{detail:\'' + sym + '\'}))">' + sym + '</td>' +
                    '<td style="font-family:var(--pf-mono);">' + qty.toLocaleString() + '</td>' +
                    '<td style="font-family:var(--pf-mono);">$' + avg.toFixed(2) + '</td>' +
                    '<td class="mp-tick-target" style="font-family:var(--pf-mono);">$' + price.toFixed(2) + '</td>' +
                    '<td style="font-family:var(--pf-mono);">$' + mktVal.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) + '</td>' +
                    '<td class="' + cls + '" style="font-family:var(--pf-mono);font-weight:700;">' + sign + ' $' + Math.abs(pnl).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) + '</td>' +
                    '<td class="' + cls + '" style="font-family:var(--pf-mono);font-weight:700;">' + (pnl >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%</td>' +
                '</tr>';
            });

            body.innerHTML = html;

            // Show first 10, hide rest
            var extraRows = body.querySelectorAll('.pf-pos-extra');
            extraRows.forEach(function(r) { r.style.display = 'none'; });

            // Add "show more" row if more than 10
            if (data.positions.length > 10) {
                var showMoreRow = document.createElement('tr');
                showMoreRow.id = 'showMoreRow';
                showMoreRow.innerHTML = '<td colspan="7" style="text-align:center;color:var(--teal);cursor:pointer;font-weight:700;font-size:0.78rem;padding:0.65rem;">' +
                    ((lang === 'ar' ? 'عرض كل ' : 'Show all ') + data.positions.length + (lang === 'ar' ? ' صفقة' : ' positions') + ' ▾') +
                '</td>';
                showMoreRow.addEventListener('click', function() {
                    body.querySelectorAll('.pf-pos-extra').forEach(function(r) { r.style.display = ''; });
                    showMoreRow.style.display = 'none';
                });
                body.appendChild(showMoreRow);
            }

            var mktValSummary = document.getElementById('mktValSummary');
            if (mktValSummary) mktValSummary.textContent = fmtMoney(portfolioValue || totalMktVal + cash);

            var mktValChg = document.getElementById('mktValChg');
            if (mktValChg && totalCost > 0) {
                var totalPnlPct = (totalPnl / totalCost) * 100;
                mktValChg.textContent = (totalPnl >= 0 ? '▲ +' : '▼ ') + totalPnlPct.toFixed(2) + '%';
                mktValChg.className = totalPnl >= 0 ? 'pf-pos' : 'pf-neg';
            }

            var cashBalText = document.getElementById('cashBalText');
            if (cashBalText) cashBalText.textContent = fmtMoney(cash);

            var dayChgText = document.getElementById('dayChgText');
            if (dayChgText && data.account) {
                var dayPnl = data.account.day_pnl || 0;
                var dayPnlPct = data.account.day_pnl_pct || 0;
                dayChgText.innerHTML = (dayPnl >= 0 ? '▲ +' : '▼ ') + fmtMoney(Math.abs(dayPnl)) + ' (' + (dayPnl >= 0 ? '+' : '') + Math.abs(dayPnlPct).toFixed(2) + '%)';
                dayChgText.className = dayPnl >= 0 ? 'pf-pos' : 'pf-neg';
            }

            var bpVal = document.getElementById('buyingPowerVal');
            if (bpVal && data.account) bpVal.textContent = fmtMoney(data.account.buying_power || 0);
        }).catch(function() {
            if (!positionsLoaded) body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:2rem;">Could not load live positions.</td></tr>';
        });
    }

    function getTheme() {
        return (document.documentElement.dataset.theme === 'light') ? 'light' : 'dark';
    }

    function renderRevenueGrowthChart() {
        // Revenue growth chart replaced with live crypto ticker
        loadCryptoTicker();
    }

    async function loadCryptoTicker() {
        var panel = document.getElementById('cryptoTickerPanel');
        if (!panel) return;

        try {
            var btc = await apiFetch('/api/crypto/snapshot/BTC%2FUSD');
            var eth = await apiFetch('/api/crypto/snapshot/ETH%2FUSD');

            var items = [];
            if (btc && btc.snapshots && btc.snapshots['BTC/USD']) {
                var snap = btc.snapshots['BTC/USD'];
                var price = snap.latestTrade ? snap.latestTrade.p : (snap.latestQuote ? snap.latestQuote.ap : 0);
                var prev = snap.prevDailyBar ? snap.prevDailyBar.c : price;
                var chg = ((price - prev) / prev) * 100;
                items.push({ sym: 'BTC/USD', price: price, chg: chg });
            }
            if (eth && eth.snapshots && eth.snapshots['ETH/USD']) {
                var snap2 = eth.snapshots['ETH/USD'];
                var price2 = snap2.latestTrade ? snap2.latestTrade.p : (snap2.latestQuote ? snap2.latestQuote.ap : 0);
                var prev2 = snap2.prevDailyBar ? snap2.prevDailyBar.c : price2;
                var chg2 = ((price2 - prev2) / prev2) * 100;
                items.push({ sym: 'ETH/USD', price: price2, chg: chg2 });
            }

            if (items.length > 0) {
                panel.innerHTML = items.map(function(item) {
                    var cls = item.chg >= 0 ? 'pf-pos' : 'pf-neg';
                    var arrow = item.chg >= 0 ? '▲' : '▼';
                    return '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.4rem 0;border-bottom:1px solid var(--line);">' +
                        '<span style="font-family:var(--pf-mono);font-weight:700;font-size:0.75rem;color:var(--ink);">' + item.sym + '</span>' +
                        '<span style="font-family:var(--pf-mono);font-weight:700;font-size:0.8rem;color:var(--ink);">$' + Number(item.price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</span>' +
                        '<span class="pf-num ' + cls + '" style="font-size:0.7rem;font-weight:700;">' + arrow + ' ' + Math.abs(item.chg).toFixed(2) + '%</span>' +
                    '</div>';
                }).join('');
            } else {
                panel.innerHTML = '<div style="color:var(--muted);font-size:0.7rem;padding:0.5rem;">Crypto data unavailable.</div>';
            }
        } catch (e) {
            panel.innerHTML = '<div style="color:var(--muted);font-size:0.7rem;padding:0.5rem;">Crypto data unavailable.</div>';
        }
    }

    function renderDetailTabs(tab) {
        var contentPane = document.getElementById('detailsContentPane');
        if (!contentPane) return;
        contentPane.style.display = 'block';

        if (tab === 'Overview' || tab === 'Chart') {
            contentPane.style.display = 'none';
            return;
        }

        // Specs tab — only fields Alpaca actually returns (no fabricated fundamentals).
        var symbol = activeSymbol;
        if (tab === 'Profile' || tab === 'Specs') {
            contentPane.innerHTML = '<div style="color:var(--muted);padding:1rem;">' + (lang === 'ar' ? 'جارٍ التحميل…' : 'Loading…') + '</div>';
            apiFetch('/api/stock/' + symbol + '/details').then(function(data) {
                if (!data) { contentPane.innerHTML = '<div style="color:var(--muted);padding:1rem;">' + (lang === 'ar' ? 'تعذّر تحميل البيانات.' : 'Unable to load data.') + '</div>'; return; }
                var profile = data.profile || {};
                function ynOrDash(v) { return v === undefined || v === null ? '—' : (v ? (lang === 'ar' ? 'نعم' : 'Yes') : (lang === 'ar' ? 'لا' : 'No')); }
                function cell(label, val) {
                    return '<div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">' + label + ':</span> <strong style="color:var(--ink);">' + (val || '—') + '</strong></div>';
                }
                contentPane.innerHTML =
                    '<div style="font-size:0.72rem;font-weight:800;text-transform:uppercase;color:var(--ink);letter-spacing:0.04em;padding-bottom:0.45rem;border-bottom:1px solid var(--line);margin-bottom:0.85rem;">' +
                        (lang === 'ar' ? 'مواصفات الأصل — ' : 'Asset Specs — ') + symbol + '</div>' +
                    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.65rem 1.5rem;padding:0.25rem 0;">' +
                        cell(lang === 'ar' ? 'الاسم' : 'Name', profile.name) +
                        cell(lang === 'ar' ? 'البورصة' : 'Exchange', profile.exchange) +
                        cell(lang === 'ar' ? 'فئة الأصل' : 'Asset Class', profile.asset_class) +
                        cell(lang === 'ar' ? 'قابل للتداول' : 'Tradable', ynOrDash(profile.tradable)) +
                        cell(lang === 'ar' ? 'قابل للبيع على المكشوف' : 'Shortable', ynOrDash(profile.shortable)) +
                        cell(lang === 'ar' ? 'قابل للتجزئة' : 'Fractionable', ynOrDash(profile.fractionable)) +
                    '</div>' +
                    '<p style="color:var(--muted);margin:0.85rem 0 0;line-height:1.5;font-size:0.72rem;">' +
                        (lang === 'ar' ? 'البيانات الأساسية من Alpaca للتداول الورقي. لا تُعرض أي مقاييس مالية غير متوفرة من المصدر.' : 'Reference data from the Alpaca trading API. Metrics not provided by the source are intentionally omitted.') +
                    '</p>';
            });
        }
    }

    function loadOptionsChain(symbol) {
        var pane = document.getElementById('detailsContentPane');
        if (!pane) return;
        pane.style.display = 'block';
        pane.innerHTML = '<div style="color:var(--muted);padding:1rem;">Loading options chain...</div>';

        apiFetch('/api/options/chain/' + symbol + '?limit=6').then(function(data) {
            if (!data || !data.snapshots || Object.keys(data.snapshots).length === 0) {
                pane.innerHTML = '<div style="color:var(--muted);padding:1rem;font-size:0.78rem;">No options data available for ' + symbol + '. Options require supported underlying assets.</div>';
                return;
            }
            var snapshots = Object.entries(data.snapshots).slice(0, 6);
            var rows = snapshots.map(function([sym, snap]) {
                var p = snap.latestQuote ? (snap.latestQuote.ap || snap.latestQuote.bp || 0) : 0;
                var strike = sym.match(/\d{5,}/) ? sym.match(/\d{5,}/)[0] : '';
                var oType = sym.includes('C') && !sym.endsWith('C') ? 'CALL' : sym.includes('P') ? 'PUT' : '—';
                return `<div style="display:flex;justify-content:space-between;align-items:center;padding:0.45rem 0;border-bottom:1px solid var(--line);">
                    <span style="font-family:var(--pf-mono);font-size:0.72rem;font-weight:700;color:var(--ink);">${sym.slice(0,18)}</span>
                    <span class="pf-badge-neu" style="font-size:0.62rem;">${oType}</span>
                    <span style="font-family:var(--pf-mono);font-size:0.75rem;font-weight:700;color:var(--teal);">$${p.toFixed(2)}</span>
                </div>`;
            }).join('');
            pane.innerHTML = '<div style="font-size:0.72rem;color:var(--muted);margin-bottom:0.5rem;">Nearest Options · ' + symbol + '</div>' + rows;
        });
    }

    function showNewsForSymbol(symbol) {
        var pane = document.getElementById('detailsContentPane');
        if (!pane) return;
        pane.style.display = 'block';
        pane.innerHTML = '<div style="color:var(--muted);padding:1rem;">Loading news for ' + symbol + '...</div>';

        apiFetch('/api/market-news').then(function(data) {
            if (!data || !Array.isArray(data)) {
                pane.innerHTML = '<div style="color:var(--muted);padding:1rem;font-size:0.78rem;">No news feed available.</div>';
                return;
            }
            var related = data.filter(function(item) {
                return Array.isArray(item.symbols) && item.symbols.indexOf(symbol) >= 0;
            }).slice(0, 4);
            if (related.length === 0) related = data.slice(0, 3);

            var items = related.map(function(item) {
                var headline = item.headline || item.title || '';
                var source = item.source || 'Market News';
                var sentClass = 'sentiment-' + (item.sentiment || 'neutral').toLowerCase();
                var sentLabel = (item.sentiment || 'neutral').toUpperCase();
                return `<div style="border-bottom:1px solid var(--line);padding:0.65rem 0;">
                    <div style="display:flex;gap:0.35rem;margin-bottom:0.25rem;">
                        <span style="font-family:var(--pf-mono);font-size:0.58rem;font-weight:800;background:var(--teal-soft);color:var(--teal);padding:0.05rem 0.35rem;border-radius:3px;">${symbol}</span>
                        <span class="mp-news-sentiment ${sentClass}">${sentLabel}</span>
                    </div>
                    <div style="font-size:0.8rem;font-weight:700;line-height:1.35;color:var(--ink);">${headline}</div>
                    <div style="font-size:0.68rem;color:var(--muted);margin-top:0.35rem;">${source}</div>
                </div>`;
            }).join('');
            pane.innerHTML = items || '<div style="color:var(--muted);padding:1rem;font-size:0.78rem;">No news available.</div>';
        });
    }

    // ── Professional Candlestick Plugin for Chart.js 4.x ──
    var pluginsRegistered = false;
    function ensurePlugins() {
        if (pluginsRegistered || !window.Chart) return;
        Chart.register({
            id: 'candleWicks',
            afterDatasetDraw: function(chart, args) {
                if (args.index !== 0) return;
                var ctx = chart.ctx, meta = args.meta, yScale = chart.scales.y;
                var candles = chart.data.datasets[0]._candles;
                if (!candles) return;
                var isDark = getTheme() === 'dark';
                ctx.save();
                for (var i = 0; i < meta.data.length; i++) {
                    var el = meta.data[i], c = candles[i];
                    if (!c || !el) continue;
                    var x = el.x, bw = Math.min(el.width * 0.6, 6);
                    var yH = yScale.getPixelForValue(c.h), yL = yScale.getPixelForValue(c.l);
                    var yO = yScale.getPixelForValue(c.o), yC = yScale.getPixelForValue(c.c);
                    var isGreen = c.c >= c.o;
                    var bodyColor = isGreen ? '#22c55e' : '#ef4444';
                    var wickColor = isDark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)';

                    ctx.strokeStyle = wickColor;
                    ctx.lineWidth = 1;
                    ctx.beginPath(); ctx.moveTo(x, yH); ctx.lineTo(x, Math.min(yO, yC)); ctx.stroke();
                    ctx.beginPath(); ctx.moveTo(x, yL); ctx.lineTo(x, Math.max(yO, yC)); ctx.stroke();

                    var bodyTop = Math.min(yO, yC);
                    var bodyH = Math.max(1, Math.abs(yC - yO));
                    ctx.fillStyle = isGreen ? 'rgba(34,197,94,0.85)' : 'rgba(239,68,68,0.85)';
                    ctx.fillRect(x - bw / 2, bodyTop, bw, bodyH);
                    ctx.strokeStyle = bodyColor;
                    ctx.lineWidth = 0.5;
                    ctx.strokeRect(x - bw / 2, bodyTop, bw, bodyH);
                }
                ctx.restore();
            }
        });
        Chart.register({
            id: 'crosshair',
            afterDraw: function(chart) {
                if (chart.tooltip && chart.tooltip._active && chart.tooltip._active.length) {
                    var ctx = chart.ctx;
                    var activePoint = chart.tooltip._active[0];
                    var x = activePoint.element.x;
                    ctx.save();
                    ctx.beginPath();
                    ctx.setLineDash([3, 3]);
                    ctx.moveTo(x, chart.scales.y.top);
                    ctx.lineTo(x, chart.scales.y.bottom);
                    ctx.strokeStyle = 'rgba(229,90,31,0.35)';
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    ctx.setLineDash([]);
                    ctx.restore();
                }
            }
        });
        pluginsRegistered = true;
    }

    // Self-contained professional candlestick renderer (no Chart.js dependency).
    // Real price-range scaling, wicks + bodies, volume strip, crosshair + OHLC
    // tooltip, HiDPI-crisp. Replaces the former Chart.js bar hack that drew
    // flat columns from a $0 baseline.
    var _chartState = null;
    var _chartMouseBound = false;

    function renderWorkspaceChart(bars, chartType) {
        chartType = chartType || 'daily';
        var canvas = document.getElementById('stockDetailsChart');
        if (!canvas) return;
        if (detailChart) { try { detailChart.destroy(); } catch (e) {} detailChart = null; }

        var isIntraday = (chartType === 'intraday');
        var candles = (bars || []).map(function(b) {
            var c = parseFloat(b.c);
            return {
                t: b.t,
                o: parseFloat(b.o != null ? b.o : c),
                h: parseFloat(b.h != null ? b.h : c),
                l: parseFloat(b.l != null ? b.l : c),
                c: c,
                v: parseFloat(b.v || 0)
            };
        }).filter(function(c) { return isFinite(c.c) && isFinite(c.h) && isFinite(c.l) && isFinite(c.o); });
        if (!candles.length) return;

        // Multi-day intraday (e.g. 1W hourly) -> date labels, not HH:MM.
        var firstT = new Date(candles[0].t).getTime();
        var lastT = new Date(candles[candles.length - 1].t).getTime();
        var spanDays = (lastT - firstT) / 86400000;
        candles.forEach(function(c) {
            var dt = new Date(c.t);
            if (isIntraday && spanDays <= 1.5 && c.t && c.t.indexOf('T') >= 0) {
                c.label = c.t.slice(11, 16);
            } else {
                c.label = isNaN(dt.getTime())
                    ? (c.t ? c.t.slice(0, 10) : '')
                    : dt.toLocaleDateString(lang === 'ar' ? 'ar-EG' : 'en-US', { month: 'short', day: 'numeric' });
            }
        });

        _chartState = { candles: candles, hoverIdx: -1, geom: null };
        if (!_chartMouseBound) {
            canvas.addEventListener('mousemove', function(e) {
                if (!_chartState || !_chartState.geom) return;
                var rect = canvas.getBoundingClientRect();
                var g = _chartState.geom;
                var idx = Math.round((e.clientX - rect.left - g.plotX - g.step / 2) / g.step);
                idx = Math.max(0, Math.min(_chartState.candles.length - 1, idx));
                if (idx !== _chartState.hoverIdx) { _chartState.hoverIdx = idx; drawCandleChart(); }
            });
            canvas.addEventListener('mouseleave', function() {
                if (_chartState && _chartState.hoverIdx !== -1) { _chartState.hoverIdx = -1; drawCandleChart(); }
            });
            window.addEventListener('resize', function() { if (_chartState) drawCandleChart(); });
            _chartMouseBound = true;
        }
        drawCandleChart();
    }

    function drawCandleChart() {
        var canvas = document.getElementById('stockDetailsChart');
        if (!canvas || !_chartState || !_chartState.candles.length) return;
        var candles = _chartState.candles;
        var n = candles.length;

        var cssW = (canvas.parentElement && canvas.parentElement.clientWidth) || 600;
        var cssH = 320;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(cssW * dpr);
        canvas.height = Math.round(cssH * dpr);
        canvas.style.width = '100%';
        canvas.style.height = cssH + 'px';
        var ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);

        var isDark = getTheme() === 'dark';
        var grid = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(26,15,8,0.06)';
        var axisTxt = isDark ? '#A39A92' : '#7A6B5E';
        var inkTxt = isDark ? '#FFF1E8' : '#1A0F08';
        var up = '#16c784', down = '#ea3943';
        var rtl = (lang === 'ar');

        var padTop = 10, padBot = 26, padAxis = 56;
        var plotX = rtl ? 8 : padAxis;
        var plotW = cssW - padAxis - 8;
        var innerH = cssH - padTop - padBot;
        var volH = Math.round(innerH * 0.16);
        var priceH = innerH - volH - 6;
        var plotY = padTop;

        var lo = Infinity, hi = -Infinity, maxVol = 0;
        candles.forEach(function(c) { if (c.l < lo) lo = c.l; if (c.h > hi) hi = c.h; if (c.v > maxVol) maxVol = c.v; });
        var pad = (hi - lo) * 0.06 || (hi * 0.02) || 1;
        lo -= pad; hi += pad;
        var range = (hi - lo) || 1;
        function py(p) { return plotY + (1 - (p - lo) / range) * priceH; }
        var step = plotW / n;
        var bodyW = Math.max(1, Math.min(step * 0.7, 16));
        _chartState.geom = { plotX: plotX, plotW: plotW, step: step };

        ctx.font = '10px ui-monospace,Menlo,monospace';
        ctx.textBaseline = 'middle';
        var gl = 5;
        for (var i = 0; i <= gl; i++) {
            var p = lo + range * (i / gl);
            var yy = py(p);
            ctx.strokeStyle = grid; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(plotX, yy); ctx.lineTo(plotX + plotW, yy); ctx.stroke();
            ctx.fillStyle = axisTxt;
            ctx.textAlign = rtl ? 'left' : 'right';
            ctx.fillText('$' + p.toFixed(p >= 100 ? 0 : 2), rtl ? plotX + plotW + 4 : plotX - 6, yy);
        }

        var volTop = plotY + priceH + 6;
        for (var j = 0; j < n; j++) {
            var c = candles[j];
            var cx = plotX + step * j + step / 2;
            var col = c.c >= c.o ? up : down;
            ctx.strokeStyle = col; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(cx, py(c.h)); ctx.lineTo(cx, py(c.l)); ctx.stroke();
            var yO = py(c.o), yC = py(c.c);
            ctx.fillStyle = col;
            ctx.fillRect(cx - bodyW / 2, Math.min(yO, yC), bodyW, Math.max(1, Math.abs(yC - yO)));
            if (maxVol > 0) {
                var vh = (c.v / maxVol) * volH;
                ctx.fillStyle = c.c >= c.o ? 'rgba(22,199,132,0.3)' : 'rgba(234,57,67,0.3)';
                ctx.fillRect(cx - bodyW / 2, volTop + volH - vh, bodyW, vh);
            }
        }

        ctx.fillStyle = axisTxt; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        var xl = 6;
        for (var k = 0; k < xl; k++) {
            var idx = Math.round((n - 1) * (k / (xl - 1)));
            var cc = candles[idx]; if (!cc) continue;
            var lxx = plotX + step * idx + step / 2;
            ctx.fillText(cc.label, Math.max(plotX + 14, Math.min(plotX + plotW - 14, lxx)), plotY + priceH + volH + 10);
        }

        var hidx = _chartState.hoverIdx;
        if (hidx >= 0 && hidx < n) {
            var hc = candles[hidx];
            var hx = plotX + step * hidx + step / 2;
            ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.28)' : 'rgba(26,15,8,0.28)';
            ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(hx, plotY); ctx.lineTo(hx, plotY + priceH); ctx.stroke();
            ctx.setLineDash([]);
            var chg = hc.c - hc.o, chgPct = hc.o ? (chg / hc.o * 100) : 0;
            var tip = [hc.label, 'O ' + hc.o.toFixed(2), 'H ' + hc.h.toFixed(2),
                       'L ' + hc.l.toFixed(2), 'C ' + hc.c.toFixed(2),
                       (chg >= 0 ? '▲ ' : '▼ ') + chg.toFixed(2) + ' (' + chgPct.toFixed(2) + '%)'];
            var tw = 104, th = tip.length * 14 + 10;
            var tx = hx + (hx > plotX + plotW - tw - 12 ? -tw - 12 : 12);
            var ty = plotY + 4;
            ctx.fillStyle = isDark ? 'rgba(20,12,6,0.96)' : 'rgba(255,255,255,0.98)';
            ctx.strokeStyle = grid;
            ctx.fillRect(tx, ty, tw, th); ctx.strokeRect(tx, ty, tw, th);
            ctx.textAlign = 'left'; ctx.textBaseline = 'top';
            for (var m = 0; m < tip.length; m++) {
                ctx.fillStyle = m === 0 ? inkTxt : (m === tip.length - 1 ? (chg >= 0 ? up : down) : axisTxt);
                ctx.fillText(tip[m], tx + 8, ty + 6 + m * 14);
            }
        }
    }

    /* ─── Level 2 Order Book — Real NBBO from Alpaca ────────────────── */
    // Real NBBO only. Builds the skeleton once and patches values in place
    // (no flicker on the 5s tick). Synthetic spreads are never fabricated.
    var _obBuilt = false;
    function renderOrderBook(price) {
        var container = document.getElementById('l2OrderBookList');
        if (!container || !activeSymbol) return;

        var db = stockPriceDatabase[activeSymbol] || {};
        var bid = db.bid || 0, ask = db.ask || 0;
        var bidSize = db.bidSize || 0, askSize = db.askSize || 0;
        var hasReal = plausibleQuote(db, price || db.price);

        var spreadEl = document.getElementById('obSpreadVal');
        if (spreadEl) {
            if (hasReal) {
                var sp = ask - bid, spPct = bid > 0 ? (sp / bid) * 100 : 0;
                spreadEl.textContent = '$' + sp.toFixed(2) + ' (' + spPct.toFixed(2) + '%)';
            } else { spreadEl.textContent = '—'; }
        }

        if (!hasReal) {
            container.innerHTML = '<div style="color:var(--muted);font-size:0.72rem;padding:0.75rem 0.35rem;text-align:center;">' +
                (lang === 'ar' ? 'لا توجد بيانات NBBO مباشرة حالياً.' : 'Live NBBO quote unavailable right now.') + '</div>';
            _obBuilt = false;
            return;
        }

        if (!_obBuilt || !container.querySelector('.mp-l2-row')) {
            container.innerHTML =
                '<div style="display:grid; grid-template-columns:1.2fr 1.5fr 1.5fr 1.2fr; gap:0.15rem; text-align:center; padding:0.3rem 0.35rem; font-family:var(--pf-mono); font-size:0.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; border-bottom:1px solid var(--line); margin-bottom:0.25rem;"><span>BID SIZE</span><span>BID</span><span>ASK</span><span>ASK SIZE</span></div>' +
                '<div class="mp-l2-row" style="display:grid; grid-template-columns:1.2fr 1.5fr 1.5fr 1.2fr; gap:0.15rem; align-items:center; text-align:center; padding:0.4rem 0.35rem; border-radius:4px; font-family:var(--pf-mono); font-size:0.78rem; position:relative; overflow:hidden;">' +
                    '<span class="ob-bidsize" style="text-align:start; color:var(--muted); z-index:1; padding-inline-start:0.15rem; font-weight:700;"></span>' +
                    '<span class="ob-bid" style="text-align:end; color:#2ecc71; font-weight:700; z-index:1; padding-inline-end:0.45rem;"></span>' +
                    '<span class="ob-ask" style="text-align:start; color:#e74c3c; font-weight:700; z-index:1; padding-inline-start:0.45rem;"></span>' +
                    '<span class="ob-asksize" style="text-align:end; color:var(--muted); z-index:1; padding-inline-end:0.15rem; font-weight:700;"></span>' +
                    '<div class="ob-bidbar" style="position:absolute; top:0; bottom:0; left:0; background:rgba(46,204,113,0.08); z-index:0;"></div>' +
                    '<div class="ob-askbar" style="position:absolute; top:0; bottom:0; right:0; background:rgba(231,76,60,0.08); z-index:0;"></div>' +
                '</div>';
            _obBuilt = true;
        }
        var bidPct = Math.min(100, (bidSize / Math.max(bidSize, askSize, 1)) * 100);
        var askPct = Math.min(100, (askSize / Math.max(bidSize, askSize, 1)) * 100);
        container.querySelector('.ob-bidsize').textContent = bidSize;
        container.querySelector('.ob-bid').textContent = bid.toFixed(2);
        container.querySelector('.ob-ask').textContent = ask.toFixed(2);
        container.querySelector('.ob-asksize').textContent = askSize;
        container.querySelector('.ob-bidbar').style.width = (bidPct / 2.2) + '%';
        container.querySelector('.ob-askbar').style.width = (askPct / 2.2) + '%';
    }

    function getSvgSparkline(sym, isPos) {
        var stroke = isPos ? '#2ecc71' : '#e74c3c';
        var db = stockPriceDatabase[sym];
        if (!db || !db._sparkData) {
            return '<svg width="55" height="24" viewBox="0 0 55 24" style="display:block;"><line x1="0" y1="12" x2="55" y2="12" stroke="var(--line)" stroke-width="1"/></svg>';
        }
        var pts = db._sparkData;
        var min = Math.min.apply(null, pts);
        var max = Math.max.apply(null, pts);
        var range = max - min || 1;
        var h = 20;
        var path = '';
        for (var i = 0; i < pts.length; i++) {
            var x = (i / (pts.length - 1)) * 52 + 1;
            var y = h - ((pts[i] - min) / range) * (h - 4) + 2;
            path += (i === 0 ? 'M' : 'L') + ' ' + x.toFixed(1) + ' ' + y.toFixed(1);
        }
        return '<svg width="55" height="24" viewBox="0 0 55 24" style="display:block;">' +
            '<path d="' + path + '" fill="none" stroke="' + stroke + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</svg>';
    }

    /* ─── Sparkline Intraday Data Loader ──────────────────────────────── */
    async function loadSparklineData(symbols) {
        var syms = symbols || watchlistSymbols;
        var promises = syms.map(function(sym) {
            return apiFetch('/api/market/bars/' + sym + '?timeframe=5Min&limit=78')
                .then(function(bars) {
                    if (bars && bars.length > 0) {
                        var db = stockPriceDatabase[sym] || {};
                        db._sparkData = bars.map(function(b) { return parseFloat(b.c); });
                        stockPriceDatabase[sym] = db;
                    }
                })
                .catch(function() {});
        });
        await Promise.all(promises);
        // Patch sparklines in place (no full rebuild → no flicker on refresh).
        if (document.getElementById('watchlistContainer') && document.querySelector('#watchlistContainer .mp-list-item')) {
            updateWatchlistSparklines();
        } else {
            renderWatchlistPane();
        }
    }

    // In-place sparkline refresh — swaps only the SVG, never the whole row.
    function updateWatchlistSparklines() {
        var c = document.getElementById('watchlistContainer');
        if (!c || activeListTab !== 'Watchlist') return;
        c.querySelectorAll('.mp-list-item').forEach(function (row) {
            var symEl = row.querySelector('.mp-list-symbol');
            if (!symEl) return;
            var sym = symEl.textContent.trim().toUpperCase();
            var db = stockPriceDatabase[sym];
            var holder = row.querySelector('.mp-spark-holder');
            if (db && holder) holder.innerHTML = getSvgSparkline(sym, (db.changePct || 0) >= 0);
        });
    }

    /* ─── Watchlist & Tabbed Portfolios List ─────────────────────────── */
    function renderWatchlistPane() {
        var container = document.getElementById('watchlistContainer');
        if (!container) return;
        container.innerHTML = '';

        if (activeListTab === 'Watchlist') {
            watchlistSymbols.forEach(function (sym) {
                var db = stockPriceDatabase[sym] || { price: 0, changePct: 0 };
                var isPos = db.changePct >= 0;
                var cls = isPos ? 'pf-pos' : 'pf-neg';
                var sign = isPos ? '▲' : '▼';
                var selectedCls = sym === activeSymbol ? 'selected' : '';

                var row = document.createElement('div');
                row.className = 'mp-list-item ' + selectedCls;
                row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:0.55rem 0.65rem;';
                row.innerHTML = `
                    <div class="mp-list-info" style="flex:1; min-width:0;">
                        <span class="mp-list-symbol" style="display:block;">${sym}</span>
                        <span class="mp-list-name" style="display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:0.65rem;">${companyNames[sym] || sym}</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:0.55rem; justify-content:flex-end; flex-shrink:0;">
                        <span class="pf-num" style="font-size:0.76rem; font-weight:700; color:var(--ink);">${db.price ? '$' + db.price.toFixed(2) : '—'}</span>
                        <span class="pf-num ${cls}" style="font-size:0.68rem; font-weight:600; min-width:52px; text-align:end;">${sign} ${Math.abs(db.changePct).toFixed(2)}%</span>
                    </div>
                `;
                row.addEventListener('click', function () { loadStockDetails(sym); });
                container.appendChild(row);
            });
        } else {
            // Render custom portfolio cards inside list tab
            Object.values(portfolioHoldings).forEach(function (pf) {
                var pctClass = pf.dayPnlPct >= 0 ? 'pf-pos' : 'pf-neg';
                var arrow = pf.dayPnlPct >= 0 ? '▲' : '▼';
                var card = document.createElement('div');
                card.className = 'mp-list-item';
                card.style.padding = '0.55rem 0.75rem';
                card.innerHTML = `
                    <div class="mp-list-info" style="flex:1;">
                        <span class="mp-list-symbol" style="font-size:0.72rem; color:var(--teal); text-transform:uppercase;">${pf.label}</span>
                        <span class="mp-list-name" style="font-size:0.64rem;">${pf.positions} positions · ${pf.strategy}</span>
                    </div>
                    <div style="text-align:end;">
                        <div style="font-size:0.82rem; font-weight:700; color:var(--ink); font-family:var(--pf-mono);">${fmtMoney(pf.equity)}</div>
                        <span class="pf-num ${pctClass}" style="font-size:0.65rem; font-weight:700;">${arrow} ${Math.abs(pf.dayPnlPct).toFixed(2)}%</span>
                    </div>
                `;
                card.addEventListener('click', function() { window.location.href = '/portfolio-detail.html?id=' + pf.id; });
                container.appendChild(card);
            });
        }
    }

    /* ─── Top list Movers tabs ───────────────────────────────────────── */
    function renderTopLists() {
        var container = document.getElementById('topListContainer');
        if (!container) return;
        container.innerHTML = '';

        var entries = Object.entries(stockPriceDatabase).filter(function ([sym]) { return !sectorETFs.includes(sym); });
        var sorted = [];
        if (activeTopTab === 'Active') {
            sorted = entries.sort(function (a, b) { return (b[1].volume || 0) - (a[1].volume || 0); }).slice(0, 5);
        } else if (activeTopTab === 'Gainers') {
            sorted = entries.filter(function (e) { return e[1].changePct > 0; }).sort(function (a, b) { return b[1].changePct - a[1].changePct; }).slice(0, 5);
        } else {
            sorted = entries.filter(function (e) { return e[1].changePct < 0; }).sort(function (a, b) { return a[1].changePct - b[1].changePct; }).slice(0, 5);
        }
        if (sorted.length === 0) {
            sorted = entries.slice(0, 5);
        }

        sorted.forEach(function ([sym, q]) {
            var isPos = q.changePct >= 0;
            var sign = isPos ? '▲' : '▼';
            var itemEl = document.createElement('div');
            itemEl.className = 'mp-list-item';
            itemEl.style.padding = '0.45rem 0.65rem';
            itemEl.innerHTML = `
                <div class="mp-list-info" style="flex:1; min-width:0;">
                    <span class="mp-list-symbol" style="display:block;">${sym}</span>
                    <span class="mp-list-name" style="display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:0.65rem;">${companyNames[sym] || sym}</span>
                </div>
                <div style="display:flex;align-items:center;gap:0.75rem;flex-shrink:0;">
                    <span class="pf-num" style="font-size:0.78rem;font-weight:700;">$${q.price.toFixed(2)}</span>
                    <span class="pf-num ${isPos ? 'pf-pos' : 'pf-neg'}" style="font-size:0.72rem;font-weight:600;width:56px;text-align:right;">${sign} ${(q.changePct || 0).toFixed(2)}%</span>
                </div>
            `;
            itemEl.addEventListener('click', function () { loadStockDetails(sym); });
            container.appendChild(itemEl);
        });
    }

    /* ─── News & Catalysts feed with image thumbnails ────────────────── */
    var _newsKey = null;
    async function loadUSNews() {
        try {
            var container = document.getElementById('newsContainer');
            if (!container) return;
            var built = container.querySelector('.mp-news-card');
            if (!built) container.innerHTML = '<div style="color:var(--muted);font-size:0.78rem;padding:0.75rem;">' + t('loading') + '</div>';
            var data = await apiFetch('/api/market-news');
            if (!data || !Array.isArray(data)) return;
            // Skip the rebuild when the feed is unchanged → no periodic flicker.
            var key = data.slice(0, 6).map(function (i) { return i.id || i.headline || i.title || ''; }).join('|');
            if (built && key === _newsKey) return;
            _newsKey = key;
            container.innerHTML = '';

            data.slice(0, 6).forEach(function (item, idx) {
                var headline = item.headline || item.title || '';
                var source = item.source || 'Market News';
                var sentiment = item.sentiment || 'neutral';
                var sentClass = 'sentiment-' + sentiment.toLowerCase();
                var dateStr = '';
                if (item.created_at) {
                    var d = new Date(item.created_at);
                    var now = new Date();
                    var diffMs = now - d;
                    var diffMins = Math.floor(diffMs / 60000);
                    if (diffMins < 60) dateStr = diffMins + 'm ago';
                    else if (diffMins < 1440) dateStr = Math.floor(diffMins / 60) + 'h ago';
                    else dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                }
                var symbols = (item.symbols || []).slice(0, 1).join(', ');
                var imgUrl = (item.images && item.images.length > 0 && item.images[0].url) ? item.images[0].url : '';

                var card = document.createElement('a');
                card.className = 'mp-news-card';
                card.href = item.url || '#';
                card.target = '_blank';
                card.rel = 'noopener noreferrer';
                card.innerHTML = `
                    <div style="flex:1;">
                        <div style="display:flex;gap:0.3rem;margin-bottom:0.25rem;align-items:center;">
                            <span style="font-family:var(--pf-mono);font-size:0.58rem;font-weight:800;background:var(--teal-soft);color:var(--teal);padding:0.05rem 0.35rem;border-radius:3px;">${symbols || 'NEWS'}</span>
                            <span class="mp-news-sentiment ${sentClass}">${sentiment.toUpperCase()}</span>
                        </div>
                        <div class="mp-news-headline">${headline}</div>
                        <div class="mp-news-meta">
                            <span class="mp-news-source">${source}</span>
                            <span class="pf-num" style="font-size:0.65rem;">${dateStr}</span>
                        </div>
                    </div>
                    ${imgUrl ? `<img src="${imgUrl}" alt="thumb" style="width:68px; height:68px; border-radius:6px; object-fit:cover; border:1px solid var(--line); flex-shrink:0;">` : ''}
                `;
                container.appendChild(card);
            });
        } catch (e) { console.error('Error fetching market news:', e); }
    }

    /* ─── Market Clock ───────────────────────────────────────────────── */
    async function loadMarketClock() {
        try {
            var data = await apiFetch('/api/market/clock');
            if (!data) return;
            var badge = document.getElementById('marketClockBadge');
            var statusLabel = document.getElementById('marketStatusLabel');
            var clockTime = document.getElementById('marketClockTime');
            var clockZone = document.getElementById('marketClockZone');

            if (badge) {
                if (data.is_open) {
                    badge.className = 'mp-clock-badge mp-clock-open';
                    badge.innerHTML = '<span style="display:inline-block;width:5px;height:5px;background:#22c55e;border-radius:50%;animation:pulse-blink 1.2s infinite;"></span> MARKET OPEN';
                } else {
                    badge.className = 'mp-clock-badge mp-clock-closed';
                    badge.textContent = 'MARKET CLOSED';
                }
            }
            if (statusLabel) statusLabel.textContent = data.is_open ? 'OPEN' : 'CLOSED';
            if (data.timestamp && clockTime) {
                var ts = new Date(data.timestamp);
                clockTime.textContent = ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                if (clockZone) clockZone.textContent = 'US Eastern Time';
            }
            if (!data.is_open && data.next_open) {
                var nextOpen = new Date(data.next_open);
                var nextOpenEl = document.getElementById('nextOpenTime');
                if (nextOpenEl) { nextOpenEl.textContent = nextOpen.toLocaleString('en-US', { weekday: 'short', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }); }
            }
        } catch (e) { console.error('Market clock error:', e); }
    }

    /* ─── Update Ticker Ribbon with Live Data ────────────────────────── */
    async function updateTickerRibbon() {
        try {
            var data = await apiFetch('/api/market-indices');
            if (!data) return;
            var el = document.getElementById('marketTickerMarquee');
            if (!el) return;
            var extras = Object.entries(stockPriceDatabase).slice(0, 8);
            var allItems = Object.entries(data).concat(extras.map(function ([sym, q]) {
                return [sym, { price: q.price, change: q.change || 0, change_pct: q.changePct || 0 }];
            }));
            var html = '';
            for (var k = 0; k < 3; k++) {
                allItems.forEach(function ([sym, ind]) {
                    var pct = ind.change_pct || ind.change_pct === 0 ? ind.change_pct : (ind.changePct || 0);
                    var cls = pct >= 0 ? 'pf-pos' : 'pf-neg';
                    var arrow = pct >= 0 ? '▲' : '▼';
                    html += `<div class="pf-ticker-item"><span class="sym">${sym}</span> <span class="price pf-num">$${(ind.price || 0).toFixed(2)}</span> <span class="chg ${cls} pf-num">${arrow} ${(pct >= 0 ? '+' : '') + (Math.abs(pct) || 0).toFixed(2)}%</span></div>`;
                });
            }
            el.innerHTML = html;
        } catch (e) { console.warn('Ticker ribbon update failed:', e); }
    }

    /* ─── Market Header Widget (S&P 500 etc) ─────────────────────────── */
    async function updateHeaderWidget() {
        try {
            var data = await apiFetch('/api/market-indices');
            if (!data) return;
            var spy = data.SPY || {};
            var qqq = data.QQQ || {};

            var spyPriceEl = document.getElementById('spyHeaderPrice');
            var spyChgEl = document.getElementById('spyHeaderChg');
            var qqqPriceEl = document.getElementById('qqqHeaderPrice');
            var qqqChgEl = document.getElementById('qqqHeaderChg');

            if (spyPriceEl && spy.price) spyPriceEl.textContent = '$' + (spy.price || 0).toFixed(2);
            if (spyChgEl && spy.change_pct !== undefined) {
                var pct = spy.change_pct || 0;
                spyChgEl.textContent = (pct >= 0 ? '▲ +' : '▼ ') + Math.abs(pct).toFixed(2) + '%';
                spyChgEl.className = 'mp-header-meta pf-num ' + (pct >= 0 ? 'pf-pos' : 'pf-neg');
            }
            if (qqqPriceEl && qqq.price) qqqPriceEl.textContent = '$' + (qqq.price || 0).toFixed(2);
            if (qqqChgEl && qqq.change_pct !== undefined) {
                var qPct = qqq.change_pct || 0;
                qqqChgEl.textContent = (qPct >= 0 ? '▲ +' : '▼ ') + Math.abs(qPct).toFixed(2) + '%';
                qqqChgEl.className = 'mp-header-meta pf-num ' + (qPct >= 0 ? 'pf-pos' : 'pf-neg');
            }

            // Also update legacy S&P 500 header (for backward compat)
            var legacySpyPrice = document.getElementById('headerSpyPrice');
            var legacySpyChg = document.getElementById('headerSpyChg');
            if (legacySpyPrice && spy.price) legacySpyPrice.textContent = '$' + (spy.price || 0).toFixed(2);
            if (legacySpyChg && spy.change_pct !== undefined) {
                var lpct = spy.change_pct || 0;
                legacySpyChg.textContent = (lpct >= 0 ? '▲ +' : '▼ ') + Math.abs(lpct).toFixed(2) + '%';
                legacySpyChg.className = 'mp-header-meta pf-num ' + (lpct >= 0 ? 'pf-pos' : 'pf-neg');
            }
        } catch (e) { console.warn('Header widget update failed:', e); }
    }

    /* ─── Real-Time Price Polling from Alpaca API ────────────────────── */
    function runMicroTicks() {
        if (priceTickInterval) clearInterval(priceTickInterval);
        priceTickInterval = setInterval(function () {
            var symbols = Object.keys(stockPriceDatabase);
            if (symbols.length === 0) return;
            fetch('/api/market/quotes?symbols=' + symbols.join(','))
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    for (var sym in data) {
                        var q = data[sym];
                        if (!q || !q.price) continue;
                        var db = stockPriceDatabase[sym];
                        if (!db) continue;
                        db.price = q.price;
                        db.changePct = q.changePct || 0;
                        if (q.change !== undefined) db.change = q.change;
                        db.prev = (q.close) ? q.close : (q.price - (q.change || 0));
                        ['open','high','low','close','volume','bid','ask','bidSize','askSize'].forEach(function (k) {
                            if (q[k] !== undefined) db[k] = q[k];
                        });
                    }
                    if (activeSymbol && stockPriceDatabase[activeSymbol]) {
                        var db = stockPriceDatabase[activeSymbol];
                        var hEl = document.getElementById('heroPrice');
                        var cEl = document.getElementById('heroPriceChg');
                        if (hEl) hEl.textContent = fmtPrice(db.price);
                        if (cEl) {
                            cEl.className = 'mp-hero-price-chg pf-num ' + (db.changePct >= 0 ? 'pf-pos' : 'pf-neg');
                            cEl.textContent = (db.changePct >= 0 ? '▲ +' : '▼ ') + Math.abs(db.price - db.prev).toFixed(2) + ' (' + Math.abs(db.changePct).toFixed(2) + '%)';
                        }
                        // Live stat patches — real fields only. Prev Close = prior session close (not the live price).
                        function setS(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
                        if (db.high) setS('statHigh', fmtPrice(db.high));
                        if (db.low) setS('statLow', fmtPrice(db.low));
                        if (db.volume) setS('statVolume', fmtVol(db.volume));
                        if (db.close) setS('statClose', fmtPrice(db.close));
                        var saneT = plausibleQuote(db, db.price);
                        setS('statBid', saneT ? fmtPrice(db.bid) : '—');
                        setS('statAsk', saneT ? fmtPrice(db.ask) : '—');
                        setS('statSpread', saneT ? '$' + (db.ask - db.bid).toFixed(2) : '—');
                        renderOrderBook(db.price);
                    }
                    tickPriceUpdates();
                })
                .catch(function() {});
        }, 5000);
    }

    function tickPriceUpdates() {
        // Update watchlist prices in-place (no DOM rebuild)
        var wlContainer = document.getElementById('watchlistContainer');
        if (wlContainer && activeListTab === 'Watchlist') {
            var rows = wlContainer.querySelectorAll('.mp-list-item');
            rows.forEach(function(row) {
                var symEl = row.querySelector('.mp-list-symbol');
                var priceEl = row.querySelector('.pf-num');
                var pctEl = row.querySelectorAll('.pf-num')[1];
                if (!symEl) return;
                var sym = symEl.textContent.trim().toUpperCase();
                var db = stockPriceDatabase[sym];
                if (!db) return;
                if (priceEl) priceEl.textContent = '$' + db.price.toFixed(2);
                if (pctEl) {
                    var isPos = db.changePct >= 0;
                    pctEl.textContent = (isPos ? '▲ ' : '▼ ') + Math.abs(db.changePct).toFixed(2) + '%';
                    pctEl.className = 'pf-num ' + (isPos ? 'pf-pos' : 'pf-neg');
                }
            });
        }

        // Update top lists prices in-place (no DOM rebuild)
        var tlContainer = document.getElementById('topListContainer');
        if (tlContainer) {
            var items = tlContainer.querySelectorAll('.mp-list-item');
            items.forEach(function(item) {
                var badge = item.querySelector('.pf-sym-badge');
                var priceEl = item.querySelectorAll('.pf-num')[0];
                var pctEl = item.querySelectorAll('.pf-num')[1];
                if (!badge) return;
                var sym = badge.textContent.trim().toUpperCase();
                var db = stockPriceDatabase[sym];
                if (!db || !priceEl) return;
                priceEl.textContent = '$' + db.price.toFixed(2);
                if (pctEl) {
                    var isPos = db.changePct >= 0;
                    pctEl.textContent = (isPos ? '▲ ' : '▼ ') + Math.abs(db.changePct).toFixed(2) + '%';
                    pctEl.className = 'pf-num ' + (isPos ? 'pf-pos' : 'pf-neg') + ' mp-tick-cell';
                }
            });
        }

        // Update positions table prices in-place (no DOM rebuild)
        var posBody = document.getElementById('myPositionsBody');
        if (posBody) {
            var targets = posBody.querySelectorAll('.mp-tick-target');
            targets.forEach(function(td) {
                var tr = td.parentElement;
                if (!tr) return;
                var symCell = tr.cells[0];
                if (!symCell) return;
                var sym = symCell.textContent.trim().toUpperCase();
                var db = stockPriceDatabase[sym];
                if (db) td.textContent = '$' + db.price.toFixed(2);
            });
        }
    }

    function updateSelectedListStyles() {
        document.querySelectorAll('.mp-list-item').forEach(function(el) {
            var symEl = el.querySelector('.mp-list-symbol');
            if (symEl && symEl.textContent.toUpperCase() === activeSymbol) {
                el.classList.add('selected');
            } else {
                el.classList.remove('selected');
            }
        });
    }

    /* ─── Full Data Refresh ──────────────────────────────────────────── */
    async function refreshAllData() {
        await loadRealQuotes(allSymbols.concat(sectorETFs));
        tickPriceUpdates();
        await updateTickerRibbon();
        await updateHeaderWidget();
    }

    /* ─── Language Toggle ────────────────────────────────────────────── */
    function applyLang(l) {
        lang = l;
        localStorage.setItem('starta-lang', l);
        document.documentElement.lang = l;
        document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
        var btn = document.getElementById('langToggle');
        if (btn) btn.textContent = l === 'ar' ? 'EN' : 'AR';
        applyTranslations(l);
        applyNavLang(l);
        loadStockDetails(activeSymbol);
        loadUSNews();
        loadMarketClock();
        loadPortfolioSignals();
        loadAndRenderSectors();
    }

    /* ─── Order Form Increment/Decrement and Place Order logic ───────── */
    window.adjustQty = function(amount) {
        var input = document.getElementById('orderQtyInput');
        if (input) {
            var val = parseInt(input.value) || 0;
            input.value = Math.max(1, val + amount);
        }
    };

    window.toggleOrderMode = function(mode) {
        var tabBuy = document.getElementById('orderTabBuy');
        var tabSell = document.getElementById('orderTabSell');
        if (tabBuy && tabSell) {
            if (mode === 'Buy') {
                tabBuy.classList.add('active');
                tabSell.classList.remove('active');
                document.getElementById('placeOrderBtnText').textContent = lang === 'ar' ? 'أرسل أمر الشراء' : 'Place Buy Order';
                document.getElementById('placeTacticalOrderBtn').style.background = 'linear-gradient(135deg, #FF8A3D 0%, #E55A1F 100%)';
            } else {
                tabBuy.classList.remove('active');
                tabSell.classList.add('active');
                document.getElementById('placeOrderBtnText').textContent = lang === 'ar' ? 'أرسل أمر البيع' : 'Place Sell Order';
                document.getElementById('placeTacticalOrderBtn').style.background = '#e74c3c';
            }
        }
    };

    window.placeTacticalOrder = function() {
        var qty = parseInt(document.getElementById('orderQtyInput').value) || 0;
        var limit = parseFloat(document.getElementById('orderLimitPriceInput').value) || 0;
        var type = document.getElementById('orderTypeInput').value;
        var tif = document.getElementById('orderTifInput').value;
        var isBuy = document.getElementById('orderTabBuy').classList.contains('active');
        var side = isBuy ? 'buy' : 'sell';

        if (qty <= 0 || limit <= 0) {
            showToast(false, 'Please enter valid quantity and price.');
            return;
        }

        var btn = document.getElementById('placeTacticalOrderBtn');
        var btnText = document.getElementById('placeOrderBtnText');
        btn.disabled = true;
        btnText.textContent = lang === 'ar' ? 'جاري الإرسال...' : 'Placing Order...';

        fetch('/api/portfolio/portfolio_1/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: activeSymbol, qty: qty, side: side, type: type.toLowerCase(), price: type === 'Limit' ? limit : null, time_in_force: tif.toLowerCase() })
        })
        .then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.error || 'Order rejected'); return d; }); })
        .then(function(data) {
            showToast(true, (lang === 'ar' ? 'تم تنفيذ الأمر بنجاح' : 'Order Executed Successfully'),
                (lang === 'ar'
                    ? `${type} ${isBuy ? 'شراء' : 'بيع'} ${qty} سهم ${activeSymbol} بسعر $${limit.toFixed(2)} · الحالة: ${data.status}`
                    : `${type} ${side.toUpperCase()} ${qty} sh ${activeSymbol} @ $${limit.toFixed(2)} · Status: ${data.status}`));
            btn.disabled = false;
            btnText.textContent = isBuy ? (lang === 'ar' ? 'أرسل أمر الشراء' : 'Place Buy Order') : (lang === 'ar' ? 'أرسل أمر البيع' : 'Place Sell Order');
            renderPositionsTable();
        })
        .catch(function(err) {
            showToast(false, (lang === 'ar' ? 'فشل الأمر' : 'Order Failed'), err.message);
            btn.disabled = false;
            btnText.textContent = isBuy ? (lang === 'ar' ? 'أرسل أمر الشراء' : 'Place Buy Order') : (lang === 'ar' ? 'أرسل أمر البيع' : 'Place Sell Order');
        });
    };

    function showToast(success, title, body) {
        var toast = document.getElementById('orderConfirmToast');
        var toastTitle = document.getElementById('toastTitle');
        var toastBody = document.getElementById('toastBody');
        var iconSvg = toast.querySelector('svg');
        if (!toast || !toastTitle || !toastBody) return;
        toastTitle.textContent = title;
        toastBody.textContent = body;
        if (iconSvg) iconSvg.setAttribute('stroke', success ? '#2ecc71' : '#e74c3c');
        toast.style.display = 'block';
        setTimeout(function() { toast.style.display = 'none'; }, 4000);
    }

    /* ─── Bind All UI Controls ───────────────────────────────────────── */
    function bindControls() {
        var langBtn = document.getElementById('langToggle');
        if (langBtn) langBtn.addEventListener('click', function () { applyLang(lang === 'ar' ? 'en' : 'ar'); });

        // Watchlist tabs
        var tw = document.getElementById('tabWatchlist');
        var tp = document.getElementById('tabPortfolios');
        if (tw && tp) {
            tw.addEventListener('click', function () {
                this.classList.add('active'); tp.classList.remove('active');
                activeListTab = 'Watchlist'; renderWatchlistPane();
            });
            tp.addEventListener('click', function () {
                this.classList.add('active'); tw.classList.remove('active');
                activeListTab = 'Portfolios'; renderWatchlistPane();
            });
        }

        // Movers tabs
        ['Active', 'Gainers', 'Losers'].forEach(function (tab) {
            var btn = document.getElementById('tab' + tab);
            if (btn) btn.addEventListener('click', function () {
                ['tabActive', 'tabGainers', 'tabLosers'].forEach(function(id) {
                    var b = document.getElementById(id); if (b) b.classList.remove('active');
                });
                this.classList.add('active');
                activeTopTab = tab;
                renderTopLists();
            });
        });

        // Order Book / L2 toggle
        var obBtn = document.getElementById('tabOrderBookView');
        var l2Btn = document.getElementById('tabL2View');
        if (obBtn && l2Btn) {
            obBtn.addEventListener('click', function() { obBtn.classList.add('active'); l2Btn.classList.remove('active'); });
            l2Btn.addEventListener('click', function() { l2Btn.classList.add('active'); obBtn.classList.remove('active'); });
        }

        // Search
        var searchInput = document.getElementById('stockSearch');
        if (searchInput) {
            searchInput.addEventListener('keypress', function (e) {
                if (e.key === 'Enter') {
                    var q = this.value.trim().toUpperCase();
                    if (q.length > 0) { loadStockDetails(q); this.value = ''; }
                }
            });
        }

        // Add stock to watchlist (Toggle inline search input row)
        var addBtn = document.getElementById('btnAddStock');
        var searchRow = document.getElementById('watchlistSearchRow');
        var searchInputWl = document.getElementById('watchlistSearchInput');
        var cancelSearchBtn = document.getElementById('btnCancelWatchlistSearch');

        if (addBtn && searchRow && searchInputWl) {
            addBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                if (searchRow.style.display === 'none' || !searchRow.style.display) {
                    searchRow.style.display = 'flex';
                    searchInputWl.value = '';
                    searchInputWl.focus();
                } else {
                    searchRow.style.display = 'none';
                }
            });

            // Enter key listener on the inline input to submit & add the symbol
            searchInputWl.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    var q = searchInputWl.value.trim().toUpperCase();
                    if (q.length > 0) {
                        if (watchlistSymbols.indexOf(q) === -1) {
                            watchlistSymbols.push(q);
                            companyNames[q] = q;
                            loadRealQuotes([q]).then(function() {
                                renderWatchlistPane();
                                renderTopLists();
                            });
                        }
                        searchInputWl.value = '';
                        searchRow.style.display = 'none';
                    }
                }
            });

            // Cancel click handler to hide inline row
            if (cancelSearchBtn) {
                cancelSearchBtn.addEventListener('click', function() {
                    searchRow.style.display = 'none';
                });
            }
        }

        // Toggle favorite
        var favBtn = document.getElementById('btnToggleFavorite');
        if (favBtn) favBtn.addEventListener('click', function() {
            var idx = watchlistSymbols.indexOf(activeSymbol);
            if (idx === -1) {
                // Add the active symbol to the watchlist
                watchlistSymbols.push(activeSymbol);
                if (!companyNames[activeSymbol]) companyNames[activeSymbol] = activeSymbol;
                loadRealQuotes([activeSymbol]).then(function() {
                    renderWatchlistPane();
                    renderTopLists();
                });
            } else {
                // Remove it from the watchlist
                watchlistSymbols.splice(idx, 1);
                renderWatchlistPane();
            }
            updateFavoriteStar();
        });

        // Clear limit price
        var clrBtn = document.getElementById('btnClearLimit');
        if (clrBtn) clrBtn.addEventListener('click', function() {
            var inp = document.getElementById('orderLimitPriceInput');
            if (inp) inp.value = '';
        });

        // Expand financials
        var expBtn = document.getElementById('btnExpandFinancials');
        if (expBtn) expBtn.addEventListener('click', function() {
            var pane = document.getElementById('detailsContentPane');
            if (pane) {
                if (pane.style.display === 'block') { pane.style.display = 'none'; }
                else { pane.style.display = 'block'; renderDetailTabs('Financials'); }
            }
        });

        // Chart pane tabs
        var detailTabIds = ['tabOverview', 'tabOptions', 'tabNews', 'tabProfileTab'];
        detailTabIds.forEach(function(tabId) {
            var btn = document.getElementById(tabId);
            if (!btn) return;
            btn.addEventListener('click', function() {
                detailTabIds.forEach(function(id) {
                    var b = document.getElementById(id); if (b) b.classList.remove('active');
                });
                this.classList.add('active');

                var pane = document.getElementById('detailsContentPane');
                var chartPane = document.getElementById('chartOverviewPane');
                if (!pane) return;

                if (tabId === 'tabOverview') {
                    pane.style.display = 'none';
                    if (chartPane) chartPane.style.display = 'block';
                    activeDetailTab = 'Chart';
                } else {
                    if (chartPane) chartPane.style.display = 'none';
                    pane.style.display = 'block';
                    if (tabId === 'tabOptions') {
                        activeDetailTab = 'Options';
                        loadOptionsChain(activeSymbol);
                    } else if (tabId === 'tabNews') {
                        activeDetailTab = 'News';
                        showNewsForSymbol(activeSymbol);
                    } else if (tabId === 'tabProfileTab') {
                        activeDetailTab = 'Specs';
                        renderDetailTabs('Specs');
                    }
                }
            });
        });

    // Opens the live options-chain pane (used by the order panel's Options tab
    // and the global "Options Lab" nav via ?view=options). Reuses the working
    // chart-area Options pane — no dead-end navigation.
    window.openOptionsChain = function () {
        var optionsTab = document.getElementById('tabOptions');
        if (!optionsTab) return;
        optionsTab.click();
        optionsTab.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };

    // Compare button
    var cmpBtn = document.getElementById('btnCompare');
    if (cmpBtn) {
        cmpBtn.addEventListener('click', function() {
            loadStockDetails('SPY');
        });
    }

    // Period buttons
    var chartToggleEl = document.getElementById('chartPeriodToggles');
    if (chartToggleEl) {
        var periodBtns = chartToggleEl.querySelectorAll('[data-range]');
        periodBtns.forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                var range = this.getAttribute('data-range');
                loadChartForPeriod(range);
            });
        });
    }
} // <-- CLOSE bindControls() HERE!

/* ─── Full-screen professional chart (TradingView Advanced Chart) ──────
   The compact in-page candlestick canvas stays the default view. The
   expand icon opens a full-viewport overlay with TradingView's pro chart
   engine: drawing tools, 100+ studies, multi-timeframe — themed to match. */
var TV_EXCHANGE = {
    SPY: 'AMEX', DIA: 'AMEX', IWM: 'AMEX', GLD: 'AMEX', BIL: 'AMEX',
    XLK: 'AMEX', XLE: 'AMEX', XLF: 'AMEX', XLV: 'AMEX', XLY: 'AMEX', XLI: 'AMEX',
    XLU: 'AMEX', XLP: 'AMEX', XLB: 'AMEX', XLRE: 'AMEX', XLC: 'AMEX',
    QQQ: 'NASDAQ', TLT: 'NASDAQ', SHY: 'NASDAQ',
    NVDA: 'NASDAQ', AAPL: 'NASDAQ', MSFT: 'NASDAQ', GOOGL: 'NASDAQ', AMZN: 'NASDAQ',
    META: 'NASDAQ', TSLA: 'NASDAQ', AMD: 'NASDAQ', NFLX: 'NASDAQ', INTC: 'NASDAQ'
};
function tvSymbolFor(sym) {
    var ex = TV_EXCHANGE[sym];
    return ex ? ex + ':' + sym : sym;
}

var tvScriptPromise = null;
function loadTradingView() {
    if (window.TradingView && window.TradingView.widget) return Promise.resolve();
    if (tvScriptPromise) return tvScriptPromise;
    tvScriptPromise = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = 'https://s3.tradingview.com/tv.js';
        s.async = true;
        s.onload = function () { resolve(); };
        s.onerror = function () { tvScriptPromise = null; reject(new Error('TradingView failed to load')); };
        document.head.appendChild(s);
    });
    return tvScriptPromise;
}

var tvMountedSymbol = null;
function mountTradingViewWidget() {
    var mount = document.getElementById('tvChartContainer');
    if (!mount || !window.TradingView) return;
    mount.innerHTML = '';
    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    tvMountedSymbol = activeSymbol;
    new TradingView.widget({
        container_id: 'tvChartContainer',
        autosize: true,
        symbol: tvSymbolFor(activeSymbol),
        interval: 'D',
        timezone: 'America/New_York',
        theme: isDark ? 'dark' : 'light',
        style: '1',
        locale: (lang === 'ar' ? 'ar' : 'en'),
        toolbar_bg: isDark ? '#1A0F08' : '#FFFFFF',
        enable_publishing: false,
        hide_side_toolbar: false,
        allow_symbol_change: true,
        withdateranges: true,
        details: true,
        hotlist: false,
        calendar: false,
        studies: ['MASimple@tv-basicstudies', 'Volume@tv-basicstudies']
    });
}

function openFullChart() {
    var overlay = document.getElementById('fullChartOverlay');
    if (!overlay) return;
    var badge = document.getElementById('fullChartBadge');
    var name = document.getElementById('fullChartName');
    if (badge) badge.textContent = activeSymbol;
    if (name) name.textContent = companyNames[activeSymbol] || activeSymbol;
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    loadTradingView().then(function () {
        var mount = document.getElementById('tvChartContainer');
        // (Re)mount only when the symbol changed or nothing is mounted —
        // this preserves the user's drawings when re-opening the same symbol.
        if (tvMountedSymbol !== activeSymbol || !mount || !mount.hasChildNodes()) {
            mountTradingViewWidget();
        }
    }).catch(function () {
        var mount = document.getElementById('tvChartContainer');
        if (mount) mount.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;padding:2rem;text-align:center;color:var(--muted);font-size:0.9rem;">Professional chart is temporarily unavailable. Check your connection and try again.</div>';
    });
}

function closeFullChart() {
    var overlay = document.getElementById('fullChartOverlay');
    if (!overlay) return;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

function initFullChart() {
    var expandBtn = document.getElementById('btnExpandChart');
    var closeBtn = document.getElementById('btnCloseFullChart');
    if (expandBtn) expandBtn.addEventListener('click', openFullChart);
    if (closeBtn) closeBtn.addEventListener('click', closeFullChart);
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var overlay = document.getElementById('fullChartOverlay');
        if (overlay && overlay.classList.contains('open')) closeFullChart();
    });
    // Re-theme the pro chart live if the user toggles light/dark while open.
    document.addEventListener('starta:themechange', function () {
        var overlay = document.getElementById('fullChartOverlay');
        if (overlay && overlay.classList.contains('open') && window.TradingView) {
            mountTradingViewWidget();
        }
    });
}

var activePeriod = '1D';
var intradayRefreshTimer = null;

function loadChartForPeriod(range) {
    activePeriod = range;
    if (intradayRefreshTimer) { clearInterval(intradayRefreshTimer); intradayRefreshTimer = null; }

    var chartToggleEl = document.getElementById('chartPeriodToggles');
    if (chartToggleEl) {
        var periodBtns = chartToggleEl.querySelectorAll('[data-range]');
        periodBtns.forEach(function(b) { b.classList.remove('active'); });
        var activeBtn = chartToggleEl.querySelector('[data-range="' + range + '"]');
        if (activeBtn) activeBtn.classList.add('active');
    }

    // Free IEX tier: 1D=5Min intraday, 1W=1Hour, the rest=daily (1M shows one
    // candle per day, exactly as requested). Daily/hourly REQUIRE an explicit
    // start date or Alpaca returns a single bar.
    var cfgMap = {
        '1D': { tf: '5Min', days: 1,   intraday: true,  limit: 130 },
        '1W': { tf: '1Hour', days: 8,  intraday: true,  limit: 130 },
        '1M': { tf: '1Day', days: 35,  intraday: false, limit: 40 },
        '3M': { tf: '1Day', days: 95,  intraday: false, limit: 110 },
        '6M': { tf: '1Day', days: 190, intraday: false, limit: 210 },
        '1Y': { tf: '1Day', days: 372, intraday: false, limit: 400 }
    };
    var cf = cfgMap[range] || cfgMap['1M'];
    var startDate = '';
    if (range !== '1D') {
        var d = new Date(); d.setDate(d.getDate() - cf.days);
        startDate = d.toISOString().slice(0, 10);
    }
    var url = '/api/market/bars/' + activeSymbol + '?timeframe=' + cf.tf +
              '&limit=' + cf.limit + '&feed=iex' + (startDate ? ('&start=' + startDate) : '');

    apiFetch(url).then(function(bars) {
        if (bars && Array.isArray(bars) && bars.length > 0) {
            renderWorkspaceChart(bars, cf.intraday ? 'intraday' : 'daily');
            if (range === '1D' || range === '1W') {
                intradayRefreshTimer = setInterval(function() {
                    if (activePeriod !== range) { clearInterval(intradayRefreshTimer); intradayRefreshTimer = null; return; }
                    apiFetch(url).then(function(b) { if (b && b.length > 0) renderWorkspaceChart(b, cf.intraday ? 'intraday' : 'daily'); });
                }, 20000);
            }
        } else {
            supaDailyFallback(range, cf);
        }
    }).catch(function() { supaDailyFallback(range, cf); });
}

// Durable fallback: Supabase persisted daily history (accumulated by the bots).
function supaDailyFallback(range, cf) {
    var d = new Date(); d.setDate(d.getDate() - cf.days);
    var s = d.toISOString().slice(0, 10);
    apiFetch('/api/supabase/market?symbol=' + activeSymbol + '&start=' + s + '&limit=' + cf.limit).then(function(rows) {
        if (rows && rows.length > 0) {
            var bars = rows.map(function(r) {
                return { t: r.date, o: parseFloat(r.open_price), h: parseFloat(r.high_price), l: parseFloat(r.low_price), c: parseFloat(r.close_price), v: parseInt(r.volume || 0) };
            });
            renderWorkspaceChart(bars, 'daily');
        }
    }).catch(function() {});
}

// Expose for stock-switch reloads
window.loadChartForPeriod = loadChartForPeriod;

    /* ─── Initialization Bootstrap ───────────────────────────────────── */
    async function init() {
        if (lang === 'ar') {
            document.documentElement.lang = 'ar';
            document.documentElement.dir = 'rtl';
            var btn = document.getElementById('langToggle');
            if (btn) btn.textContent = 'EN';
        }
        applyTranslations(lang);
        applyNavLang(lang);
        bindControls();
        initFullChart();

        loadMarketClock();
        loadUSNews();

        await loadRealQuotes(allSymbols);

        renderWatchlistPane();
        renderTopLists();

        loadSparklineData(watchlistSymbols);

        checkChartLoaded(function () {
            loadAndRenderSpySparkline();
            loadStockDetails(activeSymbol);
        });

        loadAndRenderSectors();
        updateTickerRibbon();
        updateHeaderWidget();
        loadPortfolioSignals();

        runMicroTicks();

        if (quotesRefreshInterval) clearInterval(quotesRefreshInterval);
        quotesRefreshInterval = setInterval(function () {
            refreshAllData();
            loadAndRenderSectors();
            loadSparklineData(watchlistSymbols);
            loadMarketClock();
            loadPortfolioSignals();
        }, 30000);

        // Deep-link: /market-pulse?view=options opens the options-chain pane
        // (the global "Options Lab" nav routes here).
        try {
            if (new URLSearchParams(window.location.search).get('view') === 'options') {
                checkChartLoaded(function () { window.openOptionsChain(); });
            }
        } catch (e) { /* URLSearchParams unsupported — ignore */ }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
