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

    var watchlistSymbols = ['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META'];
    var allSymbols = ['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'AMD', 'NFLX', 'INTC', 'SPY', 'QQQ', 'DIA'];
    var sectorETFs = ['XLK', 'XLF', 'XLE', 'XLV', 'XLY', 'XLI', 'XLC', 'XLB', 'XLU', 'XLRE'];
    var portfolioHoldings = {}; 

    var companyNames = {
        AAPL: 'Apple Inc.', NVDA: 'NVIDIA Corporation', MSFT: 'Microsoft Corporation',
        GOOGL: 'Alphabet Inc.', AMZN: 'Amazon.com, Inc.', TSLA: 'Tesla, Inc.',
        META: 'Meta Platforms, Inc.', AMD: 'Advanced Micro Devices', NFLX: 'Netflix, Inc.',
        INTC: 'Intel Corporation', SPY: 'SPDR S&P 500 ETF', QQQ: 'Invesco QQQ Trust', DIA: 'SPDR Dow ETF'
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
            pane_financials_tab: 'Financials', pane_profile_tab: 'Profile',
            lbl_realtime: 'Real-Time Feed via Alpaca API', tab_active: 'Most Active',
            tab_gainers: 'Top Gainers', tab_losers: 'Top Losers',
            title_news: 'Market News Feed', lbl_viewall: 'View All',
            empty_portfolio_state: 'Loading portfolio holdings from Alpaca...', lbl_l2_title: 'L2 Order Book',
            lbl_sectors: 'US Sector Performance', lbl_portfolios_overview: 'Live Portfolio Overview',
            loading: 'Loading live data...',
            lbl_key_fin: 'Key Financials',
            lbl_largecap: 'Large Cap',
            lbl_orderbook: 'Order Book',
            lbl_signals: 'Portfolio Signals'
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
            pane_financials_tab: 'البيانات المالية', pane_profile_tab: 'ملف الشركة',
            lbl_realtime: 'تغذية الأسعار الفورية عبر Alpaca', tab_active: 'الأكثر نشاطًا',
            tab_gainers: 'الأعلى ارتفاعًا', tab_losers: 'الأكثر انخفاضًا',
            title_news: 'تغذية أخبار السوق', lbl_viewall: 'عرض الكل',
            empty_portfolio_state: 'جاري تحميل بيانات المحفظة من Alpaca...', lbl_l2_title: 'كتاب الأوامر L2',
            lbl_sectors: 'أداء القطاعات الأمريكية', lbl_portfolios_overview: 'نظرة عامة على المحافظ',
            loading: 'جاري تحميل البيانات المباشرة...',
            lbl_key_fin: 'البيانات المالية الرئيسية',
            lbl_largecap: 'قيمة سوقية كبرى',
            lbl_orderbook: 'دفتر الأوامر',
            lbl_signals: 'إشارات المحفظة الذكية'
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

    /* ─── Load Sector Performance Heatmap ───────────────────────────── */
    async function loadAndRenderSectors() {
        var container = document.getElementById('sectorContainer');
        if (!container) return;
        container.innerHTML = '<div style="color:var(--muted);font-size:0.78rem;padding:0.5rem;">' + t('loading') + '</div>';

        var data = await apiFetch('/api/market/sectors');
        if (!data) return;

        var sorted = Object.entries(data).sort(function (a, b) { return b[1].changePct - a[1].changePct; });
        var maxAbs = Math.max(...sorted.map(function (e) { return Math.abs(e[1].changePct); }), 1);

        container.innerHTML = '';
        sorted.forEach(function ([sym, sec]) {
            var pct = parseFloat(sec.changePct) || 0;
            var isPos = pct >= 0;
            var barWidth = Math.min(Math.abs(pct) / maxAbs * 100, 100);
            var barColor = isPos ? 'rgba(46,204,113,0.7)' : 'rgba(231,76,60,0.7)';
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0;';
            row.innerHTML = `
                <span style="font-family:var(--pf-ui);font-size:0.7rem;font-weight:700;color:var(--ink);min-width:105px;text-align:start;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${sec.name || sym}</span>
                <div style="flex:1;height:12px;background:rgba(148,163,184,0.08);border-radius:4px;overflow:hidden;position:relative;">
                    <div style="height:100%;width:${barWidth}%;background:${barColor};border-radius:4px;transition:width 0.5s ease;"></div>
                </div>
                <span style="font-family:var(--pf-mono);font-size:0.7rem;font-weight:700;min-width:52px;text-align:end;" class="${isPos ? 'pf-pos' : 'pf-neg'}">${(isPos ? '+' : '') + pct.toFixed(2) + '%'}</span>
            `;
            container.appendChild(row);
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

    /* ─── Stock Details Workspace Loader ────────────────────────────── */
    async function loadStockDetails(symbol) {
        activeSymbol = symbol.toUpperCase();

        var priceEl = document.getElementById('heroPrice');
        var chgEl = document.getElementById('heroPriceChg');
        if (priceEl) priceEl.textContent = '...';
        if (chgEl) chgEl.textContent = 'Loading...';

        try {
            var data = await apiFetch('/api/stock/' + activeSymbol + '/details');
            if (!data) throw new Error('No data');

            document.getElementById('heroSymbol').textContent = data.symbol;
            document.getElementById('heroName').textContent = data.profile.name;
            document.getElementById('heroSub').textContent = (data.profile.sector || '') + (data.profile.CEO ? ' · CEO: ' + data.profile.CEO : '');

            var price = data.quote ? parseFloat(data.quote.price) : 150.0;
            var bars = data.bars || [];
            var prev = price;
            if (bars.length >= 2) {
                prev = parseFloat(bars[bars.length - 2].c);
            }
            var change = price - prev;
            var changePct = prev > 0 ? (change / prev) * 100 : 0;

            document.getElementById('heroPrice').textContent = fmtPrice(price);
            chgEl.className = 'mp-hero-price-chg pf-num ' + (change >= 0 ? 'pf-pos' : 'pf-neg');
            chgEl.textContent = (change >= 0 ? '▲ +' : '▼ ') + Math.abs(change).toFixed(2) + ' (' + Math.abs(changePct).toFixed(2) + '%)';

            if (bars.length > 0) {
                var lastBar = bars[bars.length - 1];
                document.getElementById('statOpen').textContent = fmtPrice(lastBar.o);
                document.getElementById('statHigh').textContent = fmtPrice(lastBar.h);
                document.getElementById('statLow').textContent = fmtPrice(lastBar.l);
                document.getElementById('statClose').textContent = fmtPrice(lastBar.c);
                document.getElementById('statVolume').textContent = fmtVol(lastBar.v);
            } else {
                document.getElementById('statOpen').textContent = fmtPrice(price);
                document.getElementById('statHigh').textContent = fmtPrice(price);
                document.getElementById('statLow').textContent = fmtPrice(price);
                document.getElementById('statClose').textContent = fmtPrice(price);
                document.getElementById('statVolume').textContent = '—';
            }

            // Sync with Tactical Order Entry Form Limit input
            var orderLimit = document.getElementById('orderLimitPriceInput');
            if (orderLimit) {
                orderLimit.value = price.toFixed(2);
                orderLimit.placeholder = price.toFixed(2);
            }

            // Update Key Stats Bar
            if (document.getElementById('statAvgVolume')) document.getElementById('statAvgVolume').textContent = data.profile.avgVol || '48.2M';
            if (document.getElementById('statMarketCap')) document.getElementById('statMarketCap').textContent = data.profile.cap || '2.70T';
            if (document.getElementById('statPE')) document.getElementById('statPE').textContent = data.profile.pe || '72.45';

            // Day range label updates
            var dayLow = price * 0.98, dayHigh = price * 1.02;
            if (bars.length > 0) {
                dayLow = lastBar.l; dayHigh = lastBar.h;
            }
            if (document.getElementById('dayRangeLabel')) {
                document.getElementById('dayRangeLabel').textContent = '$' + dayLow.toFixed(2) + ' - $' + dayHigh.toFixed(2);
            }
            if (document.getElementById('dayRangeHandle')) {
                var dayPercent = ((price - dayLow) / (dayHigh - dayLow)) * 100;
                document.getElementById('dayRangeHandle').style.left = Math.min(100, Math.max(0, dayPercent)) + '%';
            }

            document.getElementById('l2TickerName').textContent = activeSymbol;
            renderOrderBook(price);
            renderKeyFinancials(activeSymbol, data.profile);
            renderPositionsTable();
            renderRevenueGrowthChart();

            if (bars.length > 0) { renderWorkspaceChart(bars); }

            stockPriceDatabase[activeSymbol] = { price: price, changePct: changePct, prev: prev };
            updateSelectedListStyles();
        } catch (e) {
            console.error('Error loading stock details for ' + activeSymbol, e);
        }
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

        // Fetch stock details if we have a profile cached from loadStockDetails
        var symbol = activeSymbol;
        if (tab === 'Financials' || tab === 'Profile') {
            apiFetch('/api/stock/' + symbol + '/details').then(function(data) {
                if (!data) { contentPane.innerHTML = '<div style="color:var(--muted);padding:1rem;">Unable to load data.</div>'; return; }
                var profile = data.profile || {};
                if (tab === 'Financials') {
                    contentPane.innerHTML = `
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.65rem 1.25rem;padding:0.5rem 0;">
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Market Cap:</span> <strong style="color:var(--ink);">${profile.cap || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">P/E (TTM):</span> <strong style="color:var(--ink);">${profile.pe || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Beta (5Y):</span> <strong style="color:var(--ink);">${profile.beta || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Dividend Yield:</span> <strong style="color:var(--ink);">${profile.yield || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">EPS (TTM):</span> <strong style="color:var(--ink);">${profile.eps || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Revenue:</span> <strong style="color:var(--ink);">${profile.rev || '—'}</strong></div>
                        </div>
                    `;
                } else if (tab === 'Profile') {
                    contentPane.innerHTML = `
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.65rem 1.25rem;padding:0.5rem 0;">
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">CEO:</span> <strong style="color:var(--ink);">${profile.CEO || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Sector:</span> <strong style="color:var(--ink);">${profile.sector || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Market Cap:</span> <strong style="color:var(--ink);">${profile.cap || '—'}</strong></div>
                            <div><span style="color:var(--muted);font-weight:600;font-size:0.8rem;">Employees:</span> <strong style="color:var(--ink);">${profile.employees || '—'}</strong></div>
                        </div>
                        <p style="color:var(--muted);margin:0.5rem 0 0;line-height:1.55;font-size:0.82rem;">${profile.desc || 'No description available.'}</p>
                    `;
                }
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

    function renderWorkspaceChart(bars) {
        var canvas = document.getElementById('stockDetailsChart');
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        if (detailChart) detailChart.destroy();

        var labels = bars.map(function (b) {
            var date = new Date(b.t);
            if (bars.length < 100 && b.t && b.t.includes('T')) {
                return b.t.slice(11, 16);
            }
            return isNaN(date.getTime()) ? b.t : date.toLocaleDateString(lang === 'ar' ? 'ar-EG' : 'en-US', { month: 'short', day: 'numeric' });
        });
        var points = bars.map(function (b) { return parseFloat(b.c); });
        var volumes = bars.map(function (b) { return parseFloat(b.v || 0); });

        var isDark = getTheme() === 'dark';
        var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(26,15,8,0.06)';
        var inkColor = isDark ? '#FFF1E8' : '#1A0F08';

        var gradient = ctx.createLinearGradient(0, 0, 0, 300);
        gradient.addColorStop(0, 'rgba(229,90,31,0.22)');
        gradient.addColorStop(1, 'rgba(229,90,31,0.00)');

        detailChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: activeSymbol + ' Price',
                    data: points,
                    borderColor: '#E55A1F',
                    backgroundColor: gradient,
                    borderWidth: 2.2,
                    fill: true,
                    tension: 0.25,
                    pointRadius: points.length > 80 ? 0 : 1.5,
                    pointHoverRadius: 6,
                    pointHoverBackgroundColor: '#E55A1F',
                    pointHoverBorderColor: '#FFFFFF',
                    yAxisID: 'y'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: isDark ? '#1A0F08' : '#FFFFFF',
                        borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(26,15,8,0.07)',
                        borderWidth: 1,
                        titleColor: isDark ? '#FFF1E8' : '#1A0F08',
                        bodyColor: isDark ? '#A39A92' : '#7A6B5E',
                        padding: 10,
                        callbacks: {
                            label: function(ctx) { return activeSymbol + ': $' + ctx.raw.toFixed(2); }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: gridColor },
                        ticks: { color: '#7A6B5E', font: { size: 9 }, maxTicksLimit: 8, maxRotation: 0 }
                    },
                    y: {
                        position: lang === 'ar' ? 'right' : 'left',
                        grid: { color: gridColor },
                        ticks: { color: '#7A6B5E', font: { size: 9 }, callback: function(v) { return '$' + v.toFixed(1); } }
                    }
                }
            }
        });
    }

    /* ─── Level 2 Order Book — Real NBBO from Alpaca ────────────────── */
    function renderOrderBook(price) {
        var container = document.getElementById('l2OrderBookList');
        if (!container || !activeSymbol) return;

        var db = stockPriceDatabase[activeSymbol];
        if (!db) return;

        container.innerHTML = '';
        var bid = db.bid || (price - 0.05);
        var ask = db.ask || (price + 0.05);
        var bidSize = db.bidSize || 0;
        var askSize = db.askSize || 0;
        var spread = (ask - bid).toFixed(2);

        var headerRow = document.createElement('div');
        headerRow.style.cssText = 'display:grid; grid-template-columns:1.2fr 1.5fr 1.5fr 1.2fr; gap:0.15rem; text-align:center; padding:0.3rem 0.35rem; font-family:var(--pf-mono); font-size:0.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; border-bottom:1px solid var(--line); margin-bottom:0.25rem;';
        headerRow.innerHTML = '<span>BID SIZE</span><span>BID</span><span>ASK</span><span>ASK SIZE</span>';
        container.appendChild(headerRow);

        var row = document.createElement('div');
        row.className = 'mp-l2-row';
        row.style.cssText = 'display:grid; grid-template-columns:1.2fr 1.5fr 1.5fr 1.2fr; gap:0.15rem; align-items:center; text-align:center; padding:0.4rem 0.35rem; border-radius:4px; font-family:var(--pf-mono); font-size:0.78rem; position:relative; overflow:hidden; margin-bottom:0.15rem;';
        var bidPct = Math.min(100, (bidSize / Math.max(bidSize, askSize, 1)) * 100);
        var askPct = Math.min(100, (askSize / Math.max(bidSize, askSize, 1)) * 100);
        row.innerHTML =
            '<span style="text-align:start; color:var(--muted); z-index:1; padding-inline-start:0.15rem; font-weight:700;">' + bidSize + '</span>' +
            '<span style="text-align:end; color:#2ecc71; font-weight:700; z-index:1; padding-inline-end:0.45rem;">' + bid.toFixed(2) + '</span>' +
            '<span style="text-align:start; color:#e74c3c; font-weight:700; z-index:1; padding-inline-start:0.45rem;">' + ask.toFixed(2) + '</span>' +
            '<span style="text-align:end; color:var(--muted); z-index:1; padding-inline-end:0.15rem; font-weight:700;">' + askSize + '</span>' +
            '<div style="position:absolute; top:0; bottom:0; left:0; width:' + (bidPct / 2.2) + '%; background:rgba(46,204,113,0.08); z-index:0;"></div>' +
            '<div style="position:absolute; top:0; bottom:0; right:0; width:' + (askPct / 2.2) + '%; background:rgba(231,76,60,0.08); z-index:0;"></div>';
        container.appendChild(row);

        var spreadRow = document.createElement('div');
        spreadRow.style.cssText = 'text-align:center; font-family:var(--pf-mono); font-size:0.7rem; color:var(--muted); padding:0.3rem 0; border-top:1px dashed var(--line); margin-top:0.25rem;';
        spreadRow.textContent = 'SPREAD: $' + spread + ' | NBBO LIVE';
        container.appendChild(spreadRow);
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
        renderWatchlistPane();
    }

    /* ─── Watchlist & Tabbed Portfolios List ─────────────────────────── */
    function renderWatchlistPane() {
        var container = document.getElementById('watchlistContainer');
        if (!container) return;
        container.innerHTML = '';

        if (activeListTab === 'Watchlist') {
            watchlistSymbols.forEach(function (sym) {
                var db = stockPriceDatabase[sym] || { price: 150.0, changePct: 0 };
                var isPos = db.changePct >= 0;
                var cls = isPos ? 'pf-pos' : 'pf-neg';
                var sign = isPos ? '▲' : '▼';
                var selectedCls = sym === activeSymbol ? 'selected' : '';

                var row = document.createElement('div');
                row.className = 'mp-list-item ' + selectedCls;
                row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:0.55rem 0.65rem;';
                row.innerHTML = `
                    <div class="mp-list-info" style="width:75px; flex-shrink:0;">
                        <span class="mp-list-symbol">${sym}</span>
                        <span class="mp-list-name">${companyNames[sym] || sym}</span>
                    </div>
                    <div style="flex:1; display:flex; justify-content:center; align-items:center; min-width:55px; opacity:0.8;">
                        ${getSvgSparkline(sym, isPos)}
                    </div>
                    <div style="display:flex; align-items:center; gap:0.6rem; justify-content:flex-end; width:110px; flex-shrink:0;">
                        <span class="pf-num" style="font-size:0.85rem; font-weight:700; color:var(--ink);">$${db.price.toFixed(2)}</span>
                        <span class="pf-num ${cls}" style="font-size:0.75rem; font-weight:600; width:52px; text-align:end;">${sign} ${Math.abs(db.changePct).toFixed(2)}%</span>
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
                <div style="display:flex;align-items:center;gap:0.55rem;min-width:0;">
                    <span class="pf-sym-badge" style="font-size:0.62rem;padding:0.1rem 0.35rem;border-radius:4px;flex-shrink:0;">${sym}</span>
                    <span style="font-size:0.72rem;font-weight:600;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${companyNames[sym] || sym}</span>
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
    async function loadUSNews() {
        try {
            var container = document.getElementById('newsContainer');
            if (!container) return;
            container.innerHTML = '<div style="color:var(--muted);font-size:0.78rem;padding:0.75rem;">' + t('loading') + '</div>';
            var data = await apiFetch('/api/market-news');
            if (!data || !Array.isArray(data)) return;
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
                        db.prev = q.price - (q.change || 0);
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
                        var scEl = document.getElementById('statClose');
                        if (scEl) scEl.textContent = fmtPrice(db.price);
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

        // Add stock to watchlist
        var addBtn = document.getElementById('btnAddStock');
        if (addBtn) addBtn.addEventListener('click', function() {
            var q = (searchInput && searchInput.value.trim().toUpperCase()) || '';
            if (!q) q = prompt(lang === 'ar' ? 'أدخل رمز السهم للإضافة:' : 'Enter symbol to add to watchlist:');
            if (q && q.length > 0) {
                q = q.toUpperCase();
                if (watchlistSymbols.indexOf(q) === -1) {
                    watchlistSymbols.push(q);
                    companyNames[q] = q;
                    loadRealQuotes([q]).then(function() { renderWatchlistPane(); renderTopLists(); });
                }
            }
        });

        // Watchlist settings = clear watchlist and open add
        var wsBtn = document.getElementById('btnWatchlistSettings');
        if (wsBtn) wsBtn.addEventListener('click', function() {
            var q = prompt(lang === 'ar' ? 'أضف رمزًا أو اتركه فارغًا لإعادة التعيين:' : 'Add symbol or leave empty to reset:');
            if (q && q.trim().length > 0) {
                var sym = q.trim().toUpperCase();
                if (watchlistSymbols.indexOf(sym) === -1) { watchlistSymbols.push(sym); companyNames[sym] = sym; }
                loadRealQuotes([sym]).then(function() { renderWatchlistPane(); });
            }
        });

        // Toggle favorite
        var favBtn = document.getElementById('btnToggleFavorite');
        if (favBtn) favBtn.addEventListener('click', function() {
            this.classList.toggle('active');
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
        var detailTabIds = ['tabOverview', 'tabOptions', 'tabNews', 'tabFinancialsTab', 'tabProfileTab'];
        detailTabIds.forEach(function(tabId) {
            var btn = document.getElementById(tabId);
            if (!btn) return;
            btn.addEventListener('click', function() {
                detailTabIds.forEach(function(id) {
                    var b = document.getElementById(id); if (b) b.classList.remove('active');
                });
                this.classList.add('active');

                var pane = document.getElementById('detailsContentPane');
                if (!pane) return;

                if (tabId === 'tabOverview') {
                    pane.style.display = 'none';
                    activeDetailTab = 'Chart';
                } else if (tabId === 'tabOptions') {
                    activeDetailTab = 'Options';
                    loadOptionsChain(activeSymbol);
                } else if (tabId === 'tabNews') {
                    activeDetailTab = 'News';
                    showNewsForSymbol(activeSymbol);
                } else if (tabId === 'tabFinancialsTab') {
                    activeDetailTab = 'Financials';
                    renderDetailTabs('Financials');
                } else if (tabId === 'tabProfileTab') {
                    activeDetailTab = 'Profile';
                    renderDetailTabs('Profile');
                }
            });
        });

        // Period buttons
        var chartToggleEl = document.getElementById('chartPeriodToggles');
        if (chartToggleEl) {
            var periodBtns = chartToggleEl.querySelectorAll('[data-range]');
            periodBtns.forEach(function(btn) {
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    periodBtns.forEach(function(b) { b.classList.remove('active'); });
                    this.classList.add('active');
                    var range = this.getAttribute('data-range');
                    var timeframe = '1Day', limit = 30;
                    if (range === '1D') { timeframe = '5Min'; limit = 78; }
                    else if (range === '5D') { timeframe = '30Min'; limit = 65; }

                    apiFetch('/api/market/bars/' + activeSymbol + '?limit=' + limit + '&timeframe=' + timeframe).then(function(bars) {
                        if (bars && Array.isArray(bars) && bars.length > 0) {
                            renderWorkspaceChart(bars);
                        }
                    });
                });
            });
        }

        // Compare button
        var cmpBtn = document.getElementById('btnCompare');
        if (cmpBtn) cmpBtn.addEventListener('click', function() {
            loadStockDetails('SPY');
        });
    }

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

        runMicroTicks();

        if (quotesRefreshInterval) clearInterval(quotesRefreshInterval);
        quotesRefreshInterval = setInterval(function () {
            refreshAllData();
            loadAndRenderSectors();
            loadSparklineData(watchlistSymbols);
            loadMarketClock();
        }, 30000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
