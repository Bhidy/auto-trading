/**
 * portfolio-detail.js — RiseWealth Ultra-Premium Trading Terminal Dashboard Controller.
 * Overhauls the standard dashboard into a high-density, institutional Eikon/Bloomberg-grade interface.
 */
(function () {
    'use strict';

    // Parse portfolio ID from URL query parameters (e.g. ?id=portfolio_1)
    var params = new URLSearchParams(window.location.search);
    var pfId = params.get('id') || 'portfolio_1';
    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';

    /* ─── Nav translations ────────────────────────────────────────────── */
    var NAV = {
        en: { nav_all: 'All Portfolios', nav_pf1: 'Self Improving Brain', nav_pf2: 'Capitol Shadow', nav_pf3: 'Cautious Sniper', nav_market_pulse: 'Market Pulse', nav_trading: 'Trading', nav_orders: 'Orders', nav_crypto: 'Crypto Terminal', nav_options: 'Options Lab', nav_screener: 'Screener', nav_history: 'Account History' },
        ar: { nav_all: 'جميع المحافظ', nav_pf1: 'الدماغ ذاتي التحسين', nav_pf2: 'ظل الكابيتول', nav_pf3: 'القناص الحذر', nav_market_pulse: 'نبض السوق', nav_trading: 'التداول', nav_orders: 'الأوامر', nav_crypto: 'محطة العملات الرقمية', nav_options: 'مختبر الخيارات', nav_screener: 'فلتر الأسهم', nav_history: 'سجل الحساب' }
    };
    function applyNavLang(l) {
        var map = NAV[l] || NAV.en;
        document.querySelectorAll('[data-key]').forEach(function(el) {
            if (map[el.dataset.key]) el.textContent = map[el.dataset.key];
        });
    }

    var portfolio, metrics, detailCache = null;
    var perfChart = null, allocChart = null;
    var chartPeriod = 'All', chartMode = 'index';
    var holdingsTab = 'overview';
    var contribTab  = 'gainers';
    var intelTab    = 'overview'; // hub tab: overview | attribution | risk | quality
    var holdingsViewMode = 'table'; // 'table' or 'chart'
    var tabChartInst = null; // Chart.js instance for holdings tab

    // Selected stock chart and sidebar states
    var selectedSymbol = null; // first holding — used to highlight the active row

    // Premium stock metadata fetched live from Alpaca API
    var STOCK_PROFILES = {};

    function getStockProfile(symbol, callback) {
        if (STOCK_PROFILES[symbol]) { callback(STOCK_PROFILES[symbol]); return; }
        fetch('/api/stock/' + symbol + '/details')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var p = data.profile || {};
                var info = { name: p.name || symbol, exchange: p.exchange, asset_class: p.asset_class, tradable: p.tradable, shortable: p.shortable, fractionable: p.fractionable };
                STOCK_PROFILES[symbol] = info;
                callback(info);
            })
            .catch(function() {
                var info = { name: symbol };
                STOCK_PROFILES[symbol] = info;
                callback(info);
            });
    }

    /* ─── Translations Dictionary ───────────────────────────────────────── */
    var T = {
        en: {
            totalValue: 'Net Asset Value (Equity)', todayPL: "Today's P/L",
            totalGain: 'Total Profit', totalReturn: 'Total Return',
            cashBal: 'Cash Balance', invested: 'Total Cost Basis',
            dividends: 'Buying Power', vsEgx: 'System Status',
            outperform: 'Active', underperform: 'Halted',
            perfTitle: 'Historical Net Asset Value', bestDay: 'Starting Capital',
            worstDay: 'Gross Exposure', maxDD: 'Short Exposure', recovery: 'Halt Status',
            winRate: 'Win Rate Today', positiveDays: 'Today Trades',
            assetAlloc: 'Holding Allocation', sectorAlloc: 'Sector Diversification',
            beta: 'System Alpha/Beta',
            holdings: 'Positions Holdings Matrix', overview: 'Overview', performance: 'Performance',
            allocation: 'Allocation', dividendTab: 'Executed Trades',
            symbol: 'Symbol', company: 'Company Name', qty: 'Shares',
            avgCost: 'Avg Price', lastPrice: 'Last Price', mktValue: 'Market Value',
            weight: 'Weight %', dayChange: 'Day Change', totalPL: 'Unrealized Gain',
            totalRet: 'Total Return %', action: 'Action',
            topContrib: 'Performance Contributors', gainers: 'Gainers', losers: 'Losers',
            riskMetrics: 'Institutional Risk Guardrails', volatility: 'Volatility (Ann.)',
            sharpe: 'Sharpe Ratio', sortino: 'Sortino Ratio',
            maxDrawdown: 'Max Daily Drawdown', recentTx: 'Recent Executions',
            addTx: 'Add Order', noPortfolio: 'Portfolio dashboard loading...',
            back: '← Back to Overview Dashboard',
            sharpeLabel: 'Rolling Sharpe', volatilityLabel: 'Asset Volatility',
            betaLabel: 'Beta vs SPY', sortinoLabel: 'Rolling Sortino',
            maxDDLabel: 'Max Drawdown Cap',
            buy: 'BUY', sell: 'SELL'
        },
        ar: {
            totalValue: 'صافي القيمة السوقية (Equity)', todayPL: 'أرباح/خسائر اليوم',
            totalGain: 'إجمالي الأرباح الكلية', totalReturn: 'العائد التراكمي %',
            cashBal: 'الرصيد النقدي المتوفر', invested: 'إجمالي التكلفة الكلية',
            dividends: 'القوة الشرائية المتاحة', vsEgx: 'حالة النظام الآلي',
            outperform: 'نشط ويعمل', underperform: 'متوقف مؤقتاً',
            perfTitle: 'المنحنى التاريخي للمحفظة', bestDay: 'رأس المال المبدئي',
            worstDay: 'التعرض الإجمالي للسوق', maxDD: 'البيع على المكشوف', recovery: 'حالة الإيقاف الطارئ',
            winRate: 'معدل نجاح اليوم', positiveDays: 'صفقات اليوم المنفذة',
            assetAlloc: 'توزيع أوزان الأسهم', sectorAlloc: 'التنويع حسب القطاعات',
            beta: 'ألفا / بيتا المحفظة',
            holdings: 'مصفوفة المراكز والصفقات النشطة', overview: 'نظرة عامة', performance: 'الأداء والنمو',
            allocation: 'التوزيع والوزن', dividendTab: 'الصفقات المنفذة',
            symbol: 'الرمز', company: 'اسم الشركة', qty: 'الأسهم',
            avgCost: 'متوسط الشراء', lastPrice: 'آخر سعر', mktValue: 'القيمة السوقية',
            weight: 'الوزن %', dayChange: 'تغيير اليوم', totalPL: 'ربح/خسارة غير محقق',
            totalRet: 'العائد الإجمالي %', action: 'الإجراءات',
            topContrib: 'مساهمو الأداء والمكاسب', gainers: 'الرابحون', losers: 'الخاسرون',
            riskMetrics: 'مصدات حماية المخاطر المؤسسية', volatility: 'معدل التقلب السنوي',
            sharpe: 'نسبة شارب', sortino: 'نسبة سورتينو',
            maxDrawdown: 'التراجع الأقصى المسموح', recentTx: 'الصفقات الأخيرة',
            addTx: 'تنفيذ صفقة', noPortfolio: 'لوحة التحكم قيد التحميل المباشر...',
            back: '← العودة إلى لوحة التحكم الرئيسية',
            sharpeLabel: 'نسبة شارب المتداولة', volatilityLabel: 'تذبذب الأصول السنوي',
            betaLabel: 'معامل بيتا مقابل SPY', sortinoLabel: 'نسبة سورتينو للمخاطر',
            maxDDLabel: 'سقف التراجع الأقصى',
            buy: 'شراء', sell: 'بيع'
        }
    };

    function t(key) { return (T[lang] || T.en)[key] || key; }
    function fmt(n, d) { return PFStore.fmt(n, d === undefined ? 2 : d); }
    function pct(n, forceSign) {
        var sign = (forceSign !== false && n >= 0) ? '+' : '';
        return sign + fmt(n, 2) + '%';
    }

    function money(n) { return fmt(Math.abs(n), 2); }
    function escHtml(s) { return String(s).replace(/[&<>"']/g, function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }

    /* ─── Initialize Dashboard Async ────────────────────────────────── */
    function init() {
        PFStore.loadPortfolio(pfId)
            .then(function (p) {
                portfolio = p;
                metrics = PFStore.computeMetrics(portfolio);
                
                detailCache = PFStore.serverCache[pfId] || null;

                if (metrics.holdings && metrics.holdings.length > 0) {
                    selectedSymbol = metrics.holdings[0].symbol;
                } else {
                    selectedSymbol = 'NVDA';
                }

                document.title = portfolio.name + ' | Workstation';
                
                updateTickerRibbon();
                setInterval(updateTickerRibbon, 8000);

                renderHeader();
                renderBody();

                startLiveEngine();
            })
            .catch(function (err) {
                console.error('Error rendering details:', err);
                renderNotFound();
            });
    }

    /* ─── Ultra-resilient live engine (whole page + chart) ─────────────────
       One overlap-guarded scheduler. Each segment is isolated so a single
       failure can never cascade or kill the loop. Last-good data is kept on
       error (no blanking). Visibility- and connectivity-aware. */
    var LIVE_INTERVAL = 30000;
    var _liveTimer = null, _tickInFlight = false, _liveFailures = 0;

    function safeSegment(name, fn) {
        try { fn(); }
        catch (e) { console.warn('[live] segment "' + name + '" failed:', e && e.message); }
    }

    function liveTick() {
        if (_tickInFlight) return;            // overlap guard
        if (document.hidden) return;          // pause when tab hidden
        _tickInFlight = true;
        PFStore.loadPortfolio(pfId)
            .then(function (p) {
                // loadPortfolio never rejects — it returns a degraded localStorage
                // fallback on server failure. Only adopt data that computes a valid
                // metrics object; otherwise keep last-good (never-fail).
                var m = p ? PFStore.computeMetrics(p) : null;
                if (m && typeof m.totalValue === 'number') {
                    portfolio = p;
                    metrics = m;
                    detailCache = PFStore.serverCache[pfId] || null;
                    _liveFailures = 0;
                    setLiveState(true);
                } else {
                    _liveFailures++;
                    console.warn('[live] data refresh degraded (keeping last-good)');
                    if (_liveFailures >= 2) setLiveState(false);
                }
            })
            .catch(function (e) {
                _liveFailures++;
                console.warn('[live] data refresh failed (keeping last-good):', e && e.message);
                if (_liveFailures >= 2) setLiveState(false);
            })
            .then(function () {
                // Segment-isolated UI patches (run with whatever data we have)
                safeSegment('header', renderHeader);
                safeSegment('chart', initChart);
                safeSegment('sidebar', renderSidebar);
                safeSegment('intel', renderIntelligence);
                _tickInFlight = false;
            });
    }

    function setLiveState(ok) {
        var pill = document.getElementById('benchLivePill');
        if (!pill) return;
        pill.classList.toggle('is-reconnecting', !ok);
        if (!ok) {
            var ts = document.getElementById('benchLiveTs');
            if (ts) ts.textContent = lang === 'ar' ? 'إعادة الاتصال…' : 'Reconnecting…';
        }
    }

    function startLiveEngine() {
        if (_liveTimer) clearInterval(_liveTimer);
        _liveTimer = setInterval(liveTick, LIVE_INTERVAL);
        // Immediate refresh when the user returns to the tab
        document.addEventListener('visibilitychange', function () { if (!document.hidden) liveTick(); });
        // Immediate refresh on reconnect
        window.addEventListener('online', function () { setLiveState(true); liveTick(); });
        window.addEventListener('offline', function () { setLiveState(false); });
    }

    // Kept for compatibility (manual partial refresh of header/holdings/orders)
    function refreshLiveData() {
        safeSegment('header', renderHeader);
        var hRoot = document.getElementById('pf-detail-holdings-root');
        if (hRoot) safeSegment('holdings', function () { renderHoldingsTable(hRoot); });
        var ordersEl = document.getElementById('pfDetailOrders');
        if (ordersEl) safeSegment('orders', function () { renderOrdersWidget(ordersEl); });
    }

    function renderNotFound() {
        document.getElementById('pfDashBody').innerHTML =
            '<div class="pf-empty"><p>' + t('noPortfolio') + '</p>' +
            '<a href="/portfolio.html" class="pf-btn pf-btn--primary" style="margin-top:1rem;">' + t('back') + '</a></div>';
    }

    /* ─── Header Strip ────────────────────────────────────────────────── */
    function renderHeader() {
        if (!metrics) return; // never render with degraded/null state
        var todayClass  = metrics.todayGain  >= 0 ? 'pf-pos' : 'pf-neg';
        var gainClass   = metrics.totalGain  >= 0 ? 'pf-pos' : 'pf-neg';
        var retClass    = metrics.totalReturn >= 0 ? 'pf-pos' : 'pf-neg';
        
        var isServer = portfolio.isServer || false;
        var isAgg = portfolio.isAggregated || false;
        var statusLabel = isAgg ? (lang === 'ar' ? '3 محافظ مدمجة' : '3 Combined') :
                          (portfolio.halted) ? t('underperform') : t('outperform');
        var statusClass = isAgg ? 'pf-pos' : (portfolio.halted) ? 'pf-neg' : 'pf-pos';
        var statusSub = isAgg ? (lang === 'ar' ? 'عرض مجمع للقراءة فقط' : 'Read-only Aggregate View') :
                        isServer ? 'Algorithmic Mode' : 'Sandbox Mode';

        // Fetch live account values or local fallback
        var buyingPower = detailCache ? detailCache.account.buying_power : metrics.cashBalance * 2;
        var formattedBp = '$' + fmt(buyingPower);

        var kpis = [
            kpi(t('totalValue'),  '$' + fmt(metrics.totalValue), null),
            kpi(t('todayPL'),     (metrics.todayGain >= 0 ? '+$' : '-$') + fmt(Math.abs(metrics.todayGain)), pct(metrics.todayPct), todayClass),
            kpi(t('totalGain'),   (metrics.totalGain >= 0 ? '+$' : '-$') + fmt(Math.abs(metrics.totalGain)), null, gainClass),
            kpi(t('totalReturn'), pct(metrics.totalReturn), null, retClass),
            kpi(t('cashBal'),     '$' + fmt(metrics.cashBalance), null),
            kpi(t('invested'),    '$' + fmt(metrics.invested), null),
            kpi(t('dividends'),   formattedBp, null)
        ];
        if (!isAgg) kpis.push(kpi(t('vsEgx'), statusLabel, statusSub, statusClass));

        document.getElementById('pfDashHeader').innerHTML =
            '<div class="pf-dash-header-inner">' +
                '<div class="pf-selector-wrap">' +
                    '<select class="pf-selector" id="pfSelector">' +
                    PFStore.getAll().map(function(p){
                        var displayName = (lang === 'ar' && p.nameAr) ? p.nameAr : p.name;
                        var selected = p.id === pfId ? ' selected' : '';
                        return '<option value="' + p.id + '"' + selected + '>' + escHtml(displayName) + '</option>';
                    }).join('') +
                    '</select>' +
                '</div>' +
                '<div class="pf-kpi-strip">' + kpis.join('') + '</div>' +
                '<button class="pf-btn pf-btn--primary pf-btn--sm" id="addTxBtn" style="flex-shrink:0;">+ ' + t('addTx') + '</button>' +
            '</div>';

        document.getElementById('pfSelector').addEventListener('change', function() {
            window.location.href = '/portfolio-detail.html?id=' + this.value;
        });
        document.getElementById('addTxBtn').addEventListener('click', openOrderModal);
    }

    function kpi(label, value, sub, cls) {
        return '<div class="pf-kpi">' +
            '<div class="pf-kpi__label">' + label + '</div>' +
            '<div class="pf-kpi__value pf-num' + (cls ? ' ' + cls : '') + '">' + escHtml(String(value)) + '</div>' +
            (sub ? '<div class="pf-kpi__sub' + (cls ? ' ' + cls : '') + '">' + escHtml(String(sub)) + '</div>' : '') +
        '</div>';
    }

    /* ─── Body Layout (Restructured Multi-Pane Terminal Grid) ─────────── */
    function renderBody() {
        var body = document.getElementById('pfDashBody');
        if (!body) return;

        // Emergency Lock/Halt Banner
        var haltBanner = '';
        if (portfolio.halted) {
            haltBanner = `<div class="pf-halt-banner-premium" style="background:rgba(239,68,68,0.1); border:1px solid #ef4444; border-radius:var(--pf-radius); padding:1rem 1.5rem; margin-bottom:1.25rem; display:flex; align-items:center; gap:1rem; color:#ef4444;">
                <div style="font-size:1.8rem; line-height:1; font-weight:900;">!</div>
                <div>
                    <h4 style="margin:0 0 0.2rem; font-weight:800; text-transform:uppercase;">SYSTEM LOCKDOWN & HALTED</h4>
                    <p style="margin:0; font-size:0.85rem; opacity:0.85;">Emergency Stop Safety Guardrail Breached: ${escHtml(portfolio.haltReason || 'Safety threshold breached.')}</p>
                </div>
            </div>`;
        }

        body.innerHTML =
            haltBanner +
            '<!-- Tier 1: Full-Width Benchmark Chart -->' +
            '<div class="pf-card pf-chart-card" id="chartCard" style="margin-bottom:1.25rem;"></div>' +
            '<!-- Tier 2: Holdings Terminal + Compact Sidebar -->' +
            '<div class="pf-terminal-layout">' +
                '<div class="pf-terminal-main">' +
                    '<div id="holdingsSection" class="pf-holdings-section" style="margin-bottom:0;"></div>' +
                '</div>' +
                '<div id="terminalSidebar" class="pf-terminal-side"></div>' +
            '</div>' +
            '<!-- Tier 3: Intelligence Hub (tabbed) -->' +
            '<div id="pfIntelHub" class="pf-intel-hub"></div>';

        renderChartCard();
        renderHoldings(holdingsTab);
        renderSidebar();
        renderIntelligence();
    }

    /* ─── Navigation Market Ribbon ────────────────────────────────────── */
    function updateTickerRibbon() {
        PFStore.loadMarketIndices().then(function (indices) {
            var el = document.getElementById('marketTickerMarquee');
            if (!el) return;
            var itemsHtml = '';
            // Triple clone the indices for seamless looping marquee scroll
            for (var k = 0; k < 3; k++) {
                Object.entries(indices).forEach(function ([sym, ind]) {
                    var cls = ind.change_pct >= 0 ? 'pf-pos' : 'pf-neg';
                    var arrow = ind.change_pct >= 0 ? '▲' : '▼';
                    var sign = ind.change_pct >= 0 ? '+' : '';
                    itemsHtml += '<div class="pf-ticker-item">' +
                        '<span class="sym">' + sym + '</span>' +
                        '<span class="price pf-num">$' + fmt(ind.price) + '</span>' +
                        '<span class="chg ' + cls + ' pf-num">' + arrow + ' ' + sign + fmt(ind.change_pct, 2) + '%</span>' +
                        '</div>';
                });
            }
            el.innerHTML = itemsHtml;
        }).catch(function(err) {
            console.warn('Ticker update failed:', err);
        });
    }

    /* ─── Benchmark Comparison Module — "Portfolio vs S&P 500" ─────────────
       Normalized (rebased-to-100) performance comparison. Replaces the old
       raw-dollar NAV chart. Real data only: Supabase system-of-record first,
       Alpaca fallback. Race-safe + last-good caching → never blanks. */

    var BENCH_PERIODS = ['1D', '1W', '1M', '3M', '6M', 'YTD', 'All'];
    var BENCH_MODES = [
        { id: 'index',    en: 'Growth Index', ar: 'مؤشر النمو' },
        { id: 'return',   en: 'Return %',     ar: 'العائد %' },
        { id: 'drawdown', en: 'Drawdown',     ar: 'التراجع' }
    ];

    function bl(en, ar) { return lang === 'ar' ? ar : en; }

    /* ── Pure math (no DOM, reusable, null-safe) ─────────────────────────── */
    function bmNormalize(values, base) {
        if (!base || base <= 0) return values.map(function () { return 100; });
        return values.map(function (v) { return (v / base) * 100; });
    }
    function bmDailyReturns(values) {
        var out = [];
        for (var i = 1; i < values.length; i++) {
            var prev = values[i - 1];
            out.push(prev > 0 ? (values[i] / prev - 1) : 0);
        }
        return out;
    }
    function bmMean(a) { return a.length ? a.reduce(function (s, v) { return s + v; }, 0) / a.length : 0; }
    function bmStd(a) {
        if (a.length < 2) return 0;
        var m = bmMean(a);
        var variance = a.reduce(function (s, x) { return s + Math.pow(x - m, 2); }, 0) / (a.length - 1);
        return Math.sqrt(variance);
    }
    // Minimum daily observations before annualized risk ratios are meaningful
    // (a shorter window produces small-sample artifacts, e.g. an inflated Sharpe).
    var BM_MIN_RISK_OBS = 20;
    function bmSharpe(equityVals, intraday) {
        if (intraday || !equityVals || equityVals.length < BM_MIN_RISK_OBS + 1) return null;
        var r = bmDailyReturns(equityVals);
        var sd = bmStd(r);
        if (!sd) return null;
        return (bmMean(r) / sd) * Math.sqrt(252);
    }
    function bmBeta(pDaily, spyDaily) {
        var n = Math.min(pDaily.length, spyDaily.length);
        if (n < BM_MIN_RISK_OBS) return null;
        var pm = bmMean(pDaily.slice(0, n)), sm = bmMean(spyDaily.slice(0, n));
        var cov = 0, varS = 0;
        for (var i = 0; i < n; i++) {
            cov  += (pDaily[i] - pm) * (spyDaily[i] - sm);
            varS += Math.pow(spyDaily[i] - sm, 2);
        }
        if (!varS) return null;
        return cov / varS;
    }
    function bmMaxDrawdown(indexSeries) {
        if (!indexSeries || !indexSeries.length) return 0;
        var peak = indexSeries[0], mdd = 0;
        indexSeries.forEach(function (v) {
            if (v > peak) peak = v;
            var dd = peak > 0 ? (v / peak - 1) * 100 : 0;
            if (dd < mdd) mdd = dd;
        });
        return mdd;
    }
    function bmBestWorst(equityRows) {
        var best = null, worst = null;
        equityRows.forEach(function (r) {
            var e = parseFloat(r.equity);
            if (!isFinite(e)) return;
            if (!best  || e > best.value)  best  = { value: e, date: (r.date || '').slice(0, 10) };
            if (!worst || e < worst.value) worst = { value: e, date: (r.date || '').slice(0, 10) };
        });
        return { best: best, worst: worst };
    }
    function bmPeriodToStartDate(p) {
        var d = new Date();
        if (p === '1W') d.setDate(d.getDate() - 7);
        else if (p === '1M') d.setMonth(d.getMonth() - 1);
        else if (p === '3M') d.setMonth(d.getMonth() - 3);
        else if (p === '6M') d.setMonth(d.getMonth() - 6);
        else if (p === 'YTD') { d.setMonth(0); d.setDate(1); }
        else d.setFullYear(d.getFullYear() - 2);
        return d.toISOString().slice(0, 10);
    }
    function bmLabel(raw, intraday) {
        if (intraday) {
            var dt = new Date(raw.replace('T', ' ').replace('Z', ''));
            return dt.toLocaleTimeString(lang === 'ar' ? 'ar-EG' : 'en-GB', { hour: '2-digit', minute: '2-digit' });
        }
        var parts = raw.slice(0, 10).split('-');
        var dt2 = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        var longP = (chartPeriod === 'All' || chartPeriod === 'YTD' || chartPeriod === '6M');
        return dt2.toLocaleDateString(lang === 'ar' ? 'ar-EG' : 'en-GB', longP ? { day: '2-digit', month: 'short', year: '2-digit' } : { day: '2-digit', month: 'short' });
    }
    function bmSummaryDate(raw) {
        if (!raw) return '';
        var parts = raw.slice(0, 10).split('-');
        var dt = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        return dt.toLocaleDateString(lang === 'ar' ? 'ar-EG' : 'en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    /* ── Data fetchers (self-catching → never reject) ────────────────────── */
    function bmFetchEquity(period) {
        var intraday = period === '1D';
        function viaAlpaca() {
            return PFStore.loadEquityHistory(pfId, period)
                .then(function (d) { return (d && d.history) ? d.history : []; })
                .catch(function () { return []; });
        }
        if (intraday) return viaAlpaca();
        var start = bmPeriodToStartDate(period);
        return fetch('/api/supabase/equity?portfolio_id=' + pfId + '&start=' + start, { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (rows) { return (rows && rows.length >= 3) ? rows : viaAlpaca(); })
            .catch(viaAlpaca);
    }
    function bmSpyMapFromSupabase(rows) {
        var m = {};
        (rows || []).forEach(function (b) { if (b.date) m[b.date.slice(0, 10)] = parseFloat(b.close_price); });
        return m;
    }
    function bmSpyMapFromAlpaca(bars, intraday) {
        var m = {};
        (bars || []).forEach(function (b) {
            var k = intraday ? (b.t || '').slice(0, 16) : (b.t || '').slice(0, 10);
            if (k) m[k] = b.c;
        });
        return m;
    }
    function bmFetchSpy(period, startDate, endDate, intraday) {
        if (intraday) {
            var iurl = '/api/market/bars/SPY?timeframe=5Min&limit=78&start=' + encodeURIComponent(startDate + 'T13:30:00Z') + '&end=' + encodeURIComponent(startDate + 'T21:00:00Z');
            return fetch(iurl).then(function (r) { return r.ok ? r.json() : []; })
                .then(function (bars) { return bmSpyMapFromAlpaca(bars, true); })
                .catch(function () { return {}; });
        }
        function viaAlpaca() {
            var aurl = '/api/market/bars/SPY?timeframe=1Day&limit=400&start=' + encodeURIComponent(startDate) + '&end=' + encodeURIComponent(endDate);
            return fetch(aurl).then(function (r) { return r.ok ? r.json() : []; })
                .then(function (bars) { return bmSpyMapFromAlpaca(bars, false); })
                .catch(function () { return {}; });
        }
        return fetch('/api/supabase/market?symbol=SPY&start=' + startDate, { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (rows) { return (rows && rows.length >= 3) ? bmSpyMapFromSupabase(rows) : viaAlpaca(); })
            .catch(viaAlpaca);
    }
    function bmAlignSpyIndex(equityRows, spyMap, intraday) {
        var spyFirst = null, last = null;
        var aligned = equityRows.map(function (h) {
            var raw = h.date || '';
            var k = intraday ? raw.slice(0, 16) : raw.slice(0, 10);
            var c = spyMap[k];
            if (c && spyFirst === null) spyFirst = c;
            if (c) last = c;
            return last;
        });
        if (spyFirst === null) return null;
        return aligned.map(function (c) { var v = (c === null ? spyFirst : c); return (v / spyFirst) * 100; });
    }

    /* ── Reusable component builders (HTML-string components) ─────────────── */
    function ChartControls() {
        var periods = BENCH_PERIODS.map(function (p) {
            var lbl = p === 'All' ? 'ALL' : p;
            return '<button class="pf-period-btn' + (p === chartPeriod ? ' active' : '') + '" data-period="' + p + '">' + lbl + '</button>';
        }).join('');
        var modes = BENCH_MODES.map(function (m) {
            return '<button class="pf-mode-btn' + (m.id === chartMode ? ' active' : '') + '" data-mode="' + m.id + '">' + bl(m.en, m.ar) + '</button>';
        }).join('');
        return '<div class="pf-bench-controls">' +
            '<div class="pf-period-strip">' + periods + '</div>' +
            '<div class="pf-mode-strip">' + modes + '</div>' +
        '</div>';
    }
    function PerformanceKpiCard(label, valueId, accentTone) {
        return '<div class="pf-bench-kpi' + (accentTone ? ' is-' + accentTone : '') + '">' +
            '<div class="pf-bench-kpi__label">' + label + '</div>' +
            '<div class="pf-bench-kpi__value pf-num" id="' + valueId + '">—</div>' +
        '</div>';
    }
    function ChartLegend() {
        return '<div class="pf-bench-legend">' +
            '<span class="pf-bench-leg"><span class="pf-bench-swatch pf-bench-swatch--pf"></span>' + bl('Portfolio', 'المحفظة') + '</span>' +
            '<span class="pf-bench-leg"><span class="pf-bench-swatch pf-bench-swatch--spy"></span>S&amp;P 500</span>' +
        '</div>';
    }
    function InsightBadge() {
        return '<div class="pf-bench-insight" id="benchInsight">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="4"/></svg>' +
            '<span id="benchInsightText">' + bl('Computing benchmark comparison…', 'جارٍ حساب المقارنة المعيارية…') + '</span>' +
        '</div>';
    }
    function MetricSummaryItem(label, valueId, sub) {
        return '<div class="pf-bench-sumitem">' +
            '<div class="pf-bench-sumitem__label">' + label + '</div>' +
            '<div class="pf-bench-sumitem__value pf-num" id="' + valueId + '">—</div>' +
            '<div class="pf-bench-sumitem__sub" id="' + valueId + 'Sub">' + (sub || '') + '</div>' +
        '</div>';
    }
    function MetricSummaryRow() {
        return '<div class="pf-bench-summary">' +
            MetricSummaryItem(bl('Starting Capital', 'رأس المال المبدئي'), 'sumStart') +
            MetricSummaryItem(bl('Current NAV', 'صافي القيمة الحالية'), 'sumNav') +
            MetricSummaryItem(bl('Best Value', 'أعلى قيمة'), 'sumBest') +
            MetricSummaryItem(bl('Worst Value', 'أدنى قيمة'), 'sumWorst') +
            MetricSummaryItem(bl('Risk / Return Snapshot', 'لقطة المخاطر / العائد'), 'sumRisk') +
        '</div>';
    }
    function LivePill() {
        return '<div class="pf-live-pill" id="benchLivePill" title="' + bl('Auto-updating live', 'تحديث تلقائي مباشر') + '">' +
            '<span class="pf-live-dot"></span><span id="benchLiveTs">' + bl('LIVE', 'مباشر') + '</span>' +
        '</div>';
    }

    /* ── Card shell (built once; live ticks patch values, not the DOM) ───── */
    function renderChartCard() {
        var el = document.getElementById('chartCard');
        if (!el) return;

        el.innerHTML =
            '<div class="pf-bench-top">' +
                '<div class="pf-bench-head">' +
                    '<h2 class="pf-bench-title">' + bl('Portfolio vs S&P 500', 'المحفظة مقابل S&P 500').replace('&', '&amp;') + '</h2>' +
                    '<p class="pf-bench-sub">' + bl('Normalized performance, indexed to 100 at start date', 'أداء مُطبَّع، مُرتكز على 100 من تاريخ البداية') + '</p>' +
                '</div>' +
                ChartControls() +
                LivePill() +
            '</div>' +
            '<div class="pf-bench-kpis">' +
                PerformanceKpiCard(bl('Portfolio Return', 'عائد المحفظة'), 'kpiPReturn') +
                PerformanceKpiCard(bl('S&P 500 Return', 'عائد S&P 500').replace('&', '&amp;'), 'kpiSpyReturn') +
                PerformanceKpiCard(bl('Relative Performance', 'الأداء النسبي'), 'kpiRelative') +
                PerformanceKpiCard(bl('Max Drawdown', 'أقصى تراجع'), 'kpiMaxDD') +
            '</div>' +
            '<div class="pf-bench-midrow">' +
                ChartLegend() +
                InsightBadge() +
            '</div>' +
            '<div class="pf-bench-note">' +
                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>' +
                bl('Both lines start at 100 so you can compare performance fairly.', 'يبدأ كلا الخطين من 100 لتتمكن من مقارنة الأداء بإنصاف.') +
            '</div>' +
            '<div class="pf-chart-wrap" style="height:340px;position:relative;"><canvas id="perfChart"></canvas></div>' +
            MetricSummaryRow();

        el.querySelectorAll('.pf-period-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (btn.dataset.period === chartPeriod) return;
                el.querySelectorAll('.pf-period-btn').forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                chartPeriod = btn.dataset.period;
                initChart();
            });
        });
        el.querySelectorAll('.pf-mode-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                if (btn.dataset.mode === chartMode) return;
                el.querySelectorAll('.pf-mode-btn').forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                chartMode = btn.dataset.mode;
                initChart();
            });
        });

        initChart();
    }

    /* ── Empty / patch helpers ───────────────────────────────────────────── */
    function bmSetText(id, text, cls) {
        var node = document.getElementById(id);
        if (!node) return;
        // Robustness: never surface a NaN/Infinity artifact to the user.
        if (/NaN|Infinity/.test(String(text))) text = '—';
        node.textContent = text;
        if (cls !== undefined) { node.classList.remove('pf-pos', 'pf-neg'); if (cls) node.classList.add(cls); }
    }
    function bmDrawEmpty(canvas, isDark) {
        if (perfChart) { perfChart.destroy(); perfChart = null; }
        var cx = canvas.getContext('2d');
        cx.clearRect(0, 0, canvas.width, canvas.height);
        cx.font = '13px Manrope';
        cx.fillStyle = isDark ? '#a39a92' : '#7a6b5e';
        cx.textAlign = 'center';
        cx.fillText(bl('Benchmark history syncing…', 'جارٍ مزامنة بيانات المقارنة…'), canvas.width / 2, canvas.height / 2);
    }

    /* ── Drawer: fetch → compute → draw → patch (race-safe, last-good) ────── */
    var _benchToken = 0;
    var _benchLastGood = null;

    function initChart() {
        var canvas = document.getElementById('perfChart');
        if (!canvas) return;
        var isDark = document.documentElement.dataset.theme !== 'light';
        var intraday = chartPeriod === '1D';
        var token = ++_benchToken;

        bmFetchEquity(chartPeriod).then(function (equityRows) {
            if (token !== _benchToken) return; // superseded
            if (!equityRows || equityRows.length < 2) {
                if (!_benchLastGood) bmDrawEmpty(canvas, isDark);
                return;
            }
            var startDate = (equityRows[0].date || '').slice(0, 10);
            var endDate   = (equityRows[equityRows.length - 1].date || '').slice(0, 10);
            bmFetchSpy(chartPeriod, startDate, endDate, intraday).then(function (spyMap) {
                if (token !== _benchToken) return;
                try {
                    renderBenchmark(canvas, equityRows, spyMap, intraday, isDark);
                } catch (e) {
                    console.warn('[bench] render failed:', e && e.message);
                    if (!_benchLastGood) bmDrawEmpty(canvas, isDark);
                }
            });
        });
    }

    function renderBenchmark(canvas, equityRows, spyMap, intraday, isDark) {
        var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
        var tickColor = isDark ? '#a39a92' : '#7a6b5e';
        var pfColor   = '#E55A1F';
        var spyColor  = isDark ? '#9a8d82' : '#9b8e83';

        var labels     = equityRows.map(function (h) { return bmLabel(h.date || '', intraday); });
        var equityVals = equityRows.map(function (h) { return parseFloat(h.equity) || 0; });
        var startEq    = equityVals[0] || 1;
        var pIndex     = bmNormalize(equityVals, startEq);
        var spyIndex   = bmAlignSpyIndex(equityRows, spyMap, intraday); // may be null

        var pReturn   = pIndex[pIndex.length - 1] - 100;
        var spyReturn = spyIndex ? (spyIndex[spyIndex.length - 1] - 100) : null;
        var relative  = (spyReturn === null) ? null : (pReturn - spyReturn);
        var maxDD     = bmMaxDrawdown(pIndex);

        var initialCapital = (pfId === 'all') ? 300000 : 100000;
        var bw = bmBestWorst(equityRows);
        var sharpe = bmSharpe(equityVals, intraday);
        var beta = (spyIndex && !intraday) ? bmBeta(bmDailyReturns(equityVals), bmDailyReturns(spyIndex)) : null;

        // Mode → series
        var yTitle, pData, sData;
        if (chartMode === 'return') {
            yTitle = bl('Return %', 'العائد %');
            pData = toReturn(equityVals);
            sData = spyIndex ? spyIndex.map(function (v) { return v - 100; }) : null;
        } else if (chartMode === 'drawdown') {
            yTitle = bl('Drawdown %', 'التراجع %');
            pData = toDrawdown(pIndex);
            sData = spyIndex ? toDrawdown(spyIndex) : null;
        } else {
            yTitle = bl('Growth Index (Rebased)', 'مؤشر النمو (مُرتكز)');
            pData = pIndex;
            sData = spyIndex;
        }

        var ctx = canvas.getContext('2d');
        var grad = ctx.createLinearGradient(0, 0, 0, 340);
        grad.addColorStop(0,   'rgba(229,90,31,0.26)');
        grad.addColorStop(0.7, 'rgba(229,90,31,0.04)');
        grad.addColorStop(1,   'rgba(229,90,31,0.00)');

        var datasets = [{
            label: bl('Portfolio', 'المحفظة'),
            data: pData,
            borderColor: pfColor,
            backgroundColor: chartMode === 'drawdown' ? 'rgba(229,90,31,0.06)' : grad,
            borderWidth: 2.5,
            fill: chartMode !== 'drawdown',
            tension: 0.3, pointRadius: 0, pointHoverRadius: 5,
            pointHoverBackgroundColor: pfColor, order: 1
        }];
        if (sData) {
            datasets.push({
                label: 'S&P 500',
                data: sData,
                borderColor: spyColor,
                backgroundColor: 'transparent',
                borderWidth: 1.6,
                borderDash: [6, 4],
                fill: false,
                tension: 0.3, pointRadius: 0, pointHoverRadius: 4, order: 2
            });
        }

        // Index-mode dynamic range (~95–130 typical) with padding.
        // Tick precision adapts to the span so tiny ranges don't show duplicate labels.
        var idxDecimals = 0;
        var yScale = { position: 'right', grid: { color: gridColor, drawBorder: false },
            title: { display: true, text: yTitle, color: tickColor, font: { family: 'Manrope', size: 10, weight: '700' } },
            ticks: { font: { family: 'IBM Plex Mono', size: 9 }, color: tickColor,
                callback: function (v) { return chartMode === 'index' ? v.toFixed(idxDecimals) : v.toFixed(1) + '%'; } } };
        if (chartMode === 'index') {
            var all = pData.concat(sData || []);
            var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
            var span = hi - lo;
            idxDecimals = span <= 4 ? 2 : span <= 15 ? 1 : 0;
            var pad = Math.max(span * 0.12, 1.5);
            yScale.suggestedMin = lo - pad;
            yScale.suggestedMax = hi + pad;
        }

        if (perfChart) perfChart.destroy();
        perfChart = new Chart(ctx, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                animation: { duration: 600 },
                scales: {
                    x: { grid: { color: gridColor, drawBorder: false }, ticks: { font: { family: 'IBM Plex Mono', size: 9 }, color: tickColor, maxTicksLimit: intraday ? 10 : 8, maxRotation: 0 } },
                    y: yScale
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: isDark ? '#1a0f08' : '#fff', borderColor: gridColor, borderWidth: 1,
                        titleFont: { family: 'Manrope', size: 11, weight: '700' }, bodyFont: { family: 'IBM Plex Mono', size: 11 },
                        titleColor: isDark ? '#fff1e8' : '#1a0f08', bodyColor: isDark ? '#a39a92' : '#7a6b5e', padding: 10,
                        callbacks: {
                            label: function (c) {
                                var v = c.raw;
                                if (chartMode === 'index') return ' ' + c.dataset.label + ': ' + v.toFixed(2);
                                return ' ' + c.dataset.label + ': ' + (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
                            }
                        }
                    }
                }
            }
        });

        // ── Patch KPI cards ──
        bmSetText('kpiPReturn', pct(pReturn), pReturn >= 0 ? 'pf-pos' : 'pf-neg');
        if (spyReturn === null) { bmSetText('kpiSpyReturn', '—', ''); }
        else { bmSetText('kpiSpyReturn', pct(spyReturn), spyReturn >= 0 ? 'pf-pos' : 'pf-neg'); }
        if (relative === null) { bmSetText('kpiRelative', '—', ''); }
        else { bmSetText('kpiRelative', pct(relative), relative >= 0 ? 'pf-pos' : 'pf-neg'); }
        bmSetText('kpiMaxDD', fmt(maxDD, 2) + '%', maxDD < 0 ? 'pf-neg' : '');

        // ── Insight badge ──
        var insightEl = document.getElementById('benchInsight');
        var insightTxt = document.getElementById('benchInsightText');
        if (insightTxt && insightEl) {
            insightEl.classList.remove('is-pos', 'is-neg', 'is-neutral');
            if (relative === null) {
                insightEl.classList.add('is-neutral');
                insightTxt.textContent = bl('Benchmark data unavailable for this period', 'بيانات المقارنة غير متوفرة لهذه الفترة');
            } else if (relative < -0.05) {
                insightEl.classList.add('is-neg');
                insightTxt.textContent = bl('Portfolio underperformed S&P 500 by ' + fmt(Math.abs(relative), 2) + '%', 'تراجعت المحفظة عن مؤشر S&P 500 بنسبة ' + fmt(Math.abs(relative), 2) + '%');
            } else if (relative > 0.05) {
                insightEl.classList.add('is-pos');
                insightTxt.textContent = bl('Portfolio outperformed S&P 500 by ' + fmt(relative, 2) + '%', 'تفوقت المحفظة على مؤشر S&P 500 بنسبة ' + fmt(relative, 2) + '%');
            } else {
                insightEl.classList.add('is-neutral');
                insightTxt.textContent = bl('Portfolio is tracking the S&P 500', 'المحفظة تواكب مؤشر S&P 500');
            }
        }

        // ── Summary row ──
        bmSetText('sumStart', '$' + fmt(initialCapital, 0));
        if (metrics && isFinite(metrics.totalValue)) bmSetText('sumNav', '$' + fmt(metrics.totalValue, 2));
        if (bw.best)  { bmSetText('sumBest', '$' + fmt(bw.best.value, 0));  bmSetText('sumBestSub', bmSummaryDate(bw.best.date)); }
        if (bw.worst) { bmSetText('sumWorst', '$' + fmt(bw.worst.value, 0)); bmSetText('sumWorstSub', bmSummaryDate(bw.worst.date)); }
        bmSetText('sumRisk', (sharpe === null ? 'Sharpe —' : 'Sharpe ' + fmt(sharpe, 2)) + ' · ' + (beta === null ? 'β —' : 'β ' + fmt(beta, 2)));
        bmSetText('sumRiskSub', (sharpe === null && beta === null) ? bl('builds with ≥20d history', 'يُحتسب بعد ≥20 يوماً') : '');

        // ── Live pill timestamp ──
        var ts = new Date();
        bmSetText('benchLiveTs', bl('Updated ', 'تحديث ') + ts.toLocaleTimeString(lang === 'ar' ? 'ar-EG' : 'en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));

        _benchLastGood = { period: chartPeriod, mode: chartMode };
    }

    function toReturn(arr) {
        if (!arr.length) return [];
        var base = arr[0];
        return arr.map(function(v){ return base > 0 ? ((v - base) / base) * 100 : 0; });
    }

    function toDrawdown(arr) {
        var peak = arr[0], result = [];
        arr.forEach(function(v){
            if (v > peak) peak = v;
            result.push(peak > 0 ? ((v - peak) / peak) * 100 : 0);
        });
        return result;
    }

    /* ─── Portfolio Smart Panels (Advanced Tuners, watchlists) ───────── */
    function renderSmartPanels() {
        var grid = document.getElementById('smartPanelsGrid');
        if (!grid) return;

        if (!portfolio.isServer || !detailCache) {
            grid.style.display = 'none';
            return;
        }
        grid.style.display = 'grid';

        var leftPanel = '';
        var rightPanel = '';

        if (pfId === 'all') {
            var sourceLabels = detailCache ? (detailCache.source_labels || ['Self Improving Brain', 'Capitol Shadow', 'Cautious Sniper']) : ['Self Improving Brain', 'Capitol Shadow', 'Cautious Sniper'];
            var sourceCount = detailCache ? (detailCache.source_count || 3) : 3;
            leftPanel = `<div class="pf-card pf-panel">
                <div class="pf-panel__title">Aggregated Portfolio Overview</div>
                <div style="display:flex; flex-direction:column; gap:0.75rem;">
                    <div style="display:flex; align-items:center; justify-content:space-between; background:var(--page); border:1px solid var(--line); padding:0.65rem 0.85rem; border-radius:var(--pf-radius-sm);">
                        <span style="font-weight:700; color:var(--muted); font-size:0.7rem; text-transform:uppercase; letter-spacing:0.04em;">Portfolios Included</span>
                        <span class="pf-num pf-pos" style="font-weight:800; font-size:1.05rem; color:var(--teal);">${sourceCount}</span>
                    </div>
                    ${sourceLabels.map(function(label, i){
                        var colors = ['#FF8A3D', '#14b8a6', '#8b5cf6'];
                        return `<div style="display:flex; align-items:center; justify-content:space-between; background:var(--page); border:1px solid var(--line); padding:0.55rem 0.85rem; border-radius:var(--pf-radius-sm);">
                            <div style="display:flex; align-items:center; gap:0.55rem;">
                                <span style="width:8px; height:8px; border-radius:50%; background:${colors[i]}; display:inline-block;"></span>
                                <span style="font-weight:600; font-size:0.8rem; color:var(--ink);">${escHtml(label)}</span>
                            </div>
                            <span class="pf-num" style="font-size:0.72rem; color:var(--muted);">$100K Paper</span>
                        </div>`;
                    }).join('')}
                </div>
            </div>`;

            rightPanel = `<div class="pf-card pf-panel">
                <div class="pf-panel__title">Combined Trading Strategies</div>
                <div style="display:flex; flex-direction:column; gap:0.55rem; max-height:260px; overflow-y:auto;">
                    <div style="border-bottom:1px dashed var(--line); padding-bottom:0.45rem; font-size:0.75rem; line-height:1.5; color:var(--muted);">
                        <strong style="color:var(--teal);">Self Improving Brain</strong>: Multi-factor scoring, regime detection, adaptive self-learning parameters
                    </div>
                    <div style="border-bottom:1px dashed var(--line); padding-bottom:0.45rem; font-size:0.75rem; line-height:1.5; color:var(--muted);">
                        <strong style="color:var(--teal);">Capitol Shadow</strong>: Copy top-performing US politicians via Capitol Trades data
                    </div>
                    <div style="font-size:0.75rem; line-height:1.5; color:var(--muted);">
                        <strong style="color:var(--teal);">Cautious Sniper</strong>: Institutional multi-factor, ATR-based risk, 60/20/20 capital tranches
                    </div>
                </div>
            </div>`;
        } else if (pfId === 'portfolio_1') {
            // QUANT MULTI-FACTOR SPECIFIC PANELS (Adaptive Tuners + Heatmap Scorecard)
            var params = detailCache.strategy_params || {};
            leftPanel = `<div class="pf-card pf-panel">
                <div class="pf-panel__title">Adaptive Parameters (Self-Learning)</div>
                <div class="pf-params-grid">
                    <div class="pf-param-item"><label>Buy Score Threshold</label><span class="pf-num">${params.confidence_buy_threshold || 0.50}</span></div>
                    <div class="pf-param-item"><label>Short Score Threshold</label><span class="pf-num">-${params.confidence_short_threshold || 0.50}</span></div>
                    <div class="pf-param-item"><label>Stop ATR Multiplier</label><span class="pf-num">${params.trailing_stop_atr_mult || 2.50}</span></div>
                    <div class="pf-param-item"><label>Take Profit ATR Mult</label><span class="pf-num">${params.take_profit_atr_mult || 4.00}</span></div>
                    <div class="pf-param-item"><label>Position Size Mult</label><span class="pf-num">${params.position_size_multiplier || 1.00}</span></div>
                    <div class="pf-param-item"><label>Daily Trades Target</label><span class="pf-num">${params.max_trades_per_day || 12}</span></div>
                </div>
            </div>`;
            
            var rollingRank = (detailCache.signals || {}).relative_strength_ranking || [
                { symbol: 'GOOGL', percentile: 100.0, percentile_label: 'BULL' },
                { symbol: 'NVDA', percentile: 95.0, percentile_label: 'BULL' },
                { symbol: 'AMZN', percentile: 90.0, percentile_label: 'BULL' },
                { symbol: 'QQQ', percentile: 85.0, percentile_label: 'BULL' },
                { symbol: 'AAPL', percentile: 80.0, percentile_label: 'NEUTRAL' }
            ];
            var heatMapRows = rollingRank.slice(0, 5).map(h => {
                var rating = h.percentile >= 80 ? 'BULL' : h.percentile <= 40 ? 'BEAR' : 'NEUTRAL';
                var badgeCls = rating === 'BULL' ? 'bull' : rating === 'BEAR' ? 'bear' : 'neutral';
                return `<div class="pf-heatmap-item">
                    <span class="pf-heatmap-sym">${h.symbol}</span>
                    <span style="color:var(--muted); font-size:0.7rem;">Percentile: ${h.percentile}%</span>
                    <span class="pf-heatmap-badge ${badgeCls}">${rating}</span>
                </div>`;
            }).join('');

            rightPanel = `<div class="pf-card pf-panel">
                <div class="pf-panel__title">Multi-Factor Technical Scorecard Matrix</div>
                <div class="pf-heatmap-grid">${heatMapRows}</div>
            </div>`;

        } else if (pfId === 'portfolio_2') {
            // GOVERNMENT COPY BOT PANELS — real data from P2 API
            var p2Trades = detailCache ? (detailCache.trade_log || []) : [];
            var p2Latest = p2Trades.slice().reverse().slice(0, 5);
            
            var leaderRows = p2Latest.length > 0 ? p2Latest.map(function(t){
                var cls = t.side === 'buy' ? 'pf-pos' : 'pf-neg';
                var price = t.limit_price || (t.estimated_value && t.qty ? t.estimated_value / t.qty : 0) || t.price || 0;
                var tradeVal = t.estimated_value || (price > 0 && t.qty ? price * t.qty : 0);
                var politician = t.politician || t.source || '';
                return '<div style="padding:0.5rem 0.75rem;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;">' +
                    '<div>' +
                        '<strong style="font-family:var(--pf-mono);font-size:0.82rem;">' + escHtml(t.symbol) + '</strong>' +
                        (politician ? '<span style="display:block;font-size:0.68rem;color:var(--muted);margin-top:1px;">' + escHtml(politician) + '</span>' : '') +
                    '</div>' +
                    '<div style="text-align:right;">' +
                        '<span class="pf-num ' + cls + '" style="font-size:0.75rem;font-weight:700;">' + t.side.toUpperCase() + (tradeVal > 0 ? ' · $' + fmt(tradeVal, 0) : '') + '</span>' +
                        '<span class="pf-num" style="font-size:0.68rem;color:var(--muted);display:block;">' + (t.timestamp || t.date || '').slice(0,10) + '</span>' +
                    '</div>' +
                '</div>';
            }).join('') : '<div style="padding:1rem;color:var(--muted);font-size:0.78rem;">' + (lang==='ar'?'لا توجد صفقات حتى الآن':'No copy-trades executed yet.') + '</div>';

            leftPanel = '<div class="pf-card pf-panel" style="max-height:280px; overflow-y:auto;">' +
                '<div class="pf-panel__title">Copy-Trade Leaderboard</div>' +
                '<div style="display:flex;flex-direction:column;">' + leaderRows + '</div>' +
            '</div>';

            var p2Signals = detailCache ? (detailCache.signals || {}) : {};
            // research_results.json uses { stats: [{politician, total, buys, sells, ratio, top_assets}] }
            var p2Stats = p2Signals.stats || [];
            var watchRows = p2Stats.length > 0 ? p2Stats.slice(0, 6).map(function(s){
                var ratioColor = (s.ratio || 0) >= 2 ? 'var(--teal)' : (s.ratio || 0) >= 1 ? 'var(--ink)' : 'var(--muted)';
                var topAssets = (s.top_assets || []).slice(0, 3).map(function(a) {
                    if (!a) return '';
                    if (typeof a === 'string') return a;
                    return (a.ticker && a.ticker !== 'N/A') ? a.ticker : (a.issuer || '').slice(0, 14);
                }).filter(Boolean).join(', ');
                return '<div style="padding:0.45rem 0.75rem;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">' +
                    '<div style="min-width:0;">' +
                        '<span style="font-weight:700;font-size:0.78rem;color:var(--ink);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escHtml(s.politician || '') + '</span>' +
                        (topAssets ? '<span style="font-family:var(--pf-mono);font-size:0.65rem;color:var(--muted);">' + escHtml(topAssets) + '</span>' : '') +
                    '</div>' +
                    '<div style="text-align:right;flex-shrink:0;">' +
                        '<span class="pf-num" style="font-size:0.72rem;font-weight:700;color:' + ratioColor + ';">' + (s.buys || 0) + 'B / ' + (s.sells || 0) + 'S</span>' +
                        '<span style="display:block;font-size:0.65rem;color:var(--muted);">ratio ' + ((s.ratio || 0).toFixed(1)) + 'x</span>' +
                    '</div>' +
                '</div>';
            }).join('') : '<div style="padding:1rem;color:var(--muted);font-size:0.78rem;">' + (lang==='ar'?'لا توجد إشارات نشطة':'No active signals. Capitol Trades data will appear after next scan.') + '</div>';

            rightPanel = '<div class="pf-card pf-panel">' +
                '<div class="pf-panel__title">Capitol Trades Watchlist</div>' +
                '<div style="display:flex; flex-direction:column;max-height:280px;overflow-y:auto;">' + watchRows + '</div>' +
            '</div>';

        } else {
            // EVENT DRIVEN BOT PANELS (Signal scorecard + news catalyst terminal scanner)
            var signalsList = (detailCache.signals || {}).signals || [
                { symbol: 'PANW', score: 9.85, reasons: ['Cybersecurity contract rumors win', 'AI Cloud platform scale expansion'] },
                { symbol: 'CSCO', score: 8.42, reasons: ['Server networking architecture contract', 'Margin scale beat guidance'] }
            ];
            var signalRows = signalsList.slice(0, 3).map(s => `
                <div class="pf-pol-row" style="grid-template-columns:1fr 2fr; padding:0.65rem 0.85rem;">
                    <span class="pf-num pf-pos" style="font-weight:800; font-size:0.95rem;">+${fmt(s.score, 2)}</span>
                    <div style="text-align:left;">
                        <strong style="color:var(--ink); font-family:var(--pf-mono); font-size:0.85rem; display:block;">${s.symbol}</strong>
                        <span style="font-size:0.68rem; color:var(--muted);">${s.reasons?.slice(0,1).join(', ')}</span>
                    </div>
                </div>
            `).join('');

            leftPanel = `<div class="pf-card pf-panel">
                <div class="pf-panel__title">Sniper Breakout Catalyst Scorecard</div>
                <div style="display:flex; flex-direction:column; gap:0.45rem;">${signalRows || '<div class="pf-empty-inline">No signals loaded</div>'}</div>
            </div>`;

            rightPanel = `<div class="pf-card pf-panel">
                <div class="pf-panel__title">News Catalyst & Sentiment Terminal</div>
                <div style="padding:1rem;color:var(--muted);font-size:0.78rem;">` + (lang === 'ar' ? 'بيانات المحفزات الإخبارية قيد التحميل...' : 'News catalyst data pending refresh...') + `</div>
            </div>`;
        }

        grid.innerHTML = leftPanel + rightPanel;
    }

    /* ════════════════════════════════════════════════════════════════════
       ADVANCED PORTFOLIO INTELLIGENCE
       Nine componentized, real-data-first analytics modules rendered below
       the core dashboard. Each is pure (HTML-string) and degrades gracefully
       when a portfolio lacks a given data feed (sandbox / P2 / P3).
       ════════════════════════════════════════════════════════════════════ */

    // Deterministic sector risk model — turns REAL position weights into
    // institutional beta / annualized-volatility estimates (no fabrication of
    // price history; purely a transparent factor overlay on live weights).
    var SECTOR_RISK = {
        'Tech':            { beta: 1.28, vol: 0.30 },
        'Core Equity':     { beta: 1.00, vol: 0.16 },
        'Sector Momentum': { beta: 1.12, vol: 0.21 },
        'Defensive':       { beta: 0.38, vol: 0.08 },
        'Crypto':          { beta: 1.75, vol: 0.62 },
        'Gov Copy':        { beta: 1.05, vol: 0.19 },
        'Event Tech':      { beta: 1.22, vol: 0.27 },
        'Financials':      { beta: 1.18, vol: 0.22 },
        'Quant':           { beta: 1.10, vol: 0.18 },
        'Other':           { beta: 1.00, vol: 0.20 }
    };

    function il(en, ar) { return lang === 'ar' ? ar : en; }
    function moneyShort(n) {
        var a = Math.abs(n);
        if (a >= 1e6) return '$' + fmt(n / 1e6, 2) + 'M';
        if (a >= 1e3) return '$' + fmt(n / 1e3, 1) + 'K';
        return '$' + fmt(n, 0);
    }

    /* ── SVG micro-visualization helpers (self-contained, theme-aware) ──── */
    function svgSpark(vals, color) {
        if (!vals || vals.length < 2) vals = [0, (vals && vals[0]) || 0];
        var w = 76, h = 26, pad = 3;
        var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
        var rng = (max - min) || 1;
        var step = w / (vals.length - 1);
        var pts = vals.map(function (v, i) { return [i * step, h - pad - ((v - min) / rng) * (h - pad * 2)]; });
        var d = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
        var area = d + ' L ' + w + ' ' + h + ' L 0 ' + h + ' Z';
        return '<svg class="pf-spark-svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
            '<path d="' + area + '" fill="' + color + '" opacity="0.12"/>' +
            '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>' +
        '</svg>';
    }
    function svgMicroBars(vals, color) {
        var n = vals.length || 1;
        var max = Math.max.apply(null, vals.map(function (v) { return Math.abs(v); })) || 1;
        var gap = 6, bw = (100 - (n - 1) * gap) / n;
        var bars = vals.map(function (v, i) {
            var hh = Math.max((Math.abs(v) / max) * 100, 8);
            return '<rect x="' + (i * (bw + gap)).toFixed(2) + '" y="' + (100 - hh).toFixed(2) + '" width="' + bw.toFixed(2) + '" height="' + hh.toFixed(2) + '" rx="6" fill="' + color + '"/>';
        }).join('');
        return '<svg class="pf-microbars" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">' + bars + '</svg>';
    }
    function barsSeed(seed, n) {
        // Stable pseudo-random pattern (no flicker across renders) for decorative bars.
        var x = 0; for (var i = 0; i < seed.length; i++) x = (x * 31 + seed.charCodeAt(i)) % 9973;
        var out = [];
        for (var k = 0; k < n; k++) { x = (x * 1103515245 + 12345) & 0x7fffffff; out.push(0.35 + (x % 1000) / 1000 * 0.65); }
        return out;
    }
    function ICON(name) {
        var p = { stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', fill: 'none' };
        var paths = {
            heart: '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
            shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
            layers: '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
            cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
            check: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
            lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
            trend: '<path d="M3 17l6-6 4 4 7-7"/><path d="M17 7h4v4"/>',
            bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
            info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'
        };
        var attrs = Object.keys(p).map(function (k) { return k + '="' + p[k] + '"'; }).join(' ');
        return '<svg width="16" height="16" viewBox="0 0 24 24" ' + attrs + '>' + (paths[name] || '') + '</svg>';
    }
    function icHead(iconName, title, sub) {
        return '<div class="pf-ic-head"><span class="pf-ic-ico">' + ICON(iconName) + '</span>' +
            '<div><h3>' + title + '</h3>' + (sub ? '<div class="pf-ic-sub">' + sub + '</div>' : '') + '</div></div>';
    }

    /* ── Shared intelligence model derived from REAL metrics + detailCache ─ */
    function computeIntel() {
        var m = metrics || {};
        var holds = (m.holdings || []).slice();
        var acct = (detailCache && detailCache.account) ? detailCache.account : {};
        var equity = m.totalValue || acct.equity || 0;
        var invested = m.totalMarketValue || 0;
        var cash = (m.cashBalance != null ? m.cashBalance : acct.cash) || 0;

        var byWeight = holds.slice().sort(function (a, b) { return b.weight - a.weight; });
        var largest = byWeight[0] ? byWeight[0].weight : 0;
        var top5 = byWeight.slice(0, 5).reduce(function (s, h) { return s + h.weight; }, 0);

        var wsum = 0, betaAcc = 0, volAcc = 0;
        holds.forEach(function (h) {
            var sr = SECTOR_RISK[h.sector] || SECTOR_RISK.Other;
            var w = (h.weight || 0) / 100;
            wsum += w; betaAcc += w * sr.beta; volAcc += w * sr.vol;
        });
        var beta = wsum > 0 ? betaAcc / wsum : 1.0;
        var blendedVol = wsum > 0 ? volAcc / wsum : 0;
        var investedFrac = equity > 0 ? invested / equity : 0;
        var portVol = blendedVol * investedFrac; // annualized fraction (cash dampened)

        var cashDeploy = equity > 0 ? (invested / equity) * 100 : 0;
        var longMv = (acct.long_market_value != null && acct.long_market_value > 0) ? acct.long_market_value : invested;
        var shortMv = Math.abs(acct.short_market_value || 0);
        var longExp = equity > 0 ? (longMv / equity) * 100 : cashDeploy;
        var shortExp = equity > 0 ? (shortMv / equity) * 100 : 0;

        var sectorMap = {};
        holds.forEach(function (h) {
            var key = h.sector || 'Other';
            if (!sectorMap[key]) sectorMap[key] = { sector: key, weight: 0, mv: 0, gain: 0, cost: 0, day: 0, color: h.color, count: 0, wins: 0, rets: [] };
            var s = sectorMap[key];
            s.weight += (h.weight || 0); s.mv += (h.marketValue || 0); s.gain += (h.totalGain || 0);
            s.cost += (h.costBasis || (h.quantity * h.avgCost) || 0); s.day += (h.unrealizedIntradayPl || 0);
            s.count++; if ((h.totalGain || 0) > 0) s.wins++;
            s.rets.push(h.totalReturn || 0);
        });
        var sleeves = Object.keys(sectorMap).map(function (k) { return sectorMap[k]; }).sort(function (a, b) { return b.mv - a.mv; });

        return {
            equity: equity, invested: invested, cash: cash, cashPct: equity > 0 ? (cash / equity) * 100 : 0,
            holds: holds, byWeight: byWeight, largest: largest, top5: top5,
            beta: beta, portVol: portVol, cashDeploy: cashDeploy, longExp: longExp, shortExp: shortExp,
            sleeves: sleeves, holdingsCount: holds.length
        };
    }

    function signalPercentile(sym) {
        var sg = (detailCache && detailCache.signals) ? detailCache.signals : {};
        var rr = sg.relative_strength_ranking || [];
        for (var i = 0; i < rr.length; i++) { if (rr[i].symbol === sym) return rr[i].percentile; }
        return null;
    }

    /* ── Tier 2 Sidebar: Contributors + Quick Risk Status ─────────────── */
    var sidebarTab = 'contributors'; // 'contributors' | 'risk'

    /* Measure the actual rendered height of the holdings section and apply
       it as max-height to the sidebar so both are pixel-perfect equal.
       Called after every render that could change either column's height. */
    function syncSidebarHeight() {
        var mainEl = document.querySelector('.pf-terminal-main');
        var sideEl = document.getElementById('terminalSidebar');
        if (!mainEl || !sideEl) return;
        var h = Math.round(mainEl.getBoundingClientRect().height);
        if (h > 0) {
            sideEl.style.maxHeight = h + 'px';
            sideEl.style.overflow  = 'hidden';
        }
    }

    function renderSidebar() {
        var sb = document.getElementById('terminalSidebar');
        if (!sb) return;

        // Build risk rows
        var tradesToday = detailCache ? (detailCache.trade_log || []).length : 0;
        var signalCount = detailCache ? ((detailCache.signals || {}).signals || []).length : 0;
        var halted = portfolio.halted;
        function qrow(lbl, val, cls) {
            return '<div class="pf-qrisk-row"><span class="pf-qrisk-label">' + lbl + '</span>' +
                '<span class="pf-qrisk-val' + (cls ? ' ' + cls : '') + '">' + val + '</span></div>';
        }
        var qrisk =
            qrow(il('Status', 'الحالة'), halted ? 'HALTED' : 'ACTIVE', halted ? 'pf-neg' : 'pf-pos') +
            qrow(il('Trades Logged', 'الصفقات المُسجّلة'), tradesToday, '') +
            qrow(il('Active Signals', 'إشارات نشطة'), signalCount, signalCount ? 'pf-pos' : '') +
            qrow(il('Daily Loss Limit', 'حد الخسارة اليومي'), '4.0%', '') +
            qrow(il('Kill Switch', 'مفتاح الإيقاف'), il('Armed', 'مُفعّل'), 'pf-pos') +
            qrow(il('Kill Threshold', 'عتبة الإيقاف'), '18% DD', '');

        var isContrib = sidebarTab === 'contributors';
        var tabBar =
            '<button class="pf-sidebar-tab' + (isContrib ? ' active' : '') + '" data-stab="contributors">' +
                il('Contributors', 'المساهمون') +
            '</button>' +
            '<button class="pf-sidebar-tab' + (!isContrib ? ' active' : '') + '" data-stab="risk">' +
                il('Risk Status', 'حالة المخاطر') +
            '</button>';

        var paneContent = isContrib
            ? '<div id="contribPanel">' + renderContrib() + '</div>'
            : '<div class="pf-qrisk">' + qrisk + '</div>';

        sb.innerHTML =
            '<div class="pf-card pf-sidebar-card">' +
                '<div class="pf-sidebar-tabs">' + tabBar + '</div>' +
                '<div class="pf-sidebar-pane">' + paneContent + '</div>' +
            '</div>';

        // Wire tab switching
        sb.querySelectorAll('.pf-sidebar-tab').forEach(function(btn) {
            btn.addEventListener('click', function() {
                sidebarTab = btn.dataset.stab;
                renderSidebar();
            });
        });

        if (isContrib) wireContribTabs();
        // Sync sidebar height to holdings column after content paints
        setTimeout(syncSidebarHeight, 80);
    }

    /* ── Tier 3 Intelligence Hub Orchestrator (tabbed card) ───────────── */
    function renderIntelligence() {
        var root = document.getElementById('pfIntelHub');
        if (!root) return;
        var I;
        try { I = computeIntel(); }
        catch (e) { console.warn('[intel] compute failed:', e && e.message); return; }

        var TABS = [
            { id: 'overview',    label: il('Overview', 'نظرة عامة') },
            { id: 'attribution', label: il('Attribution & AI', 'الإسناد والذكاء') },
            { id: 'risk',        label: il('Risk & Alerts', 'المخاطر والتنبيهات') },
        ];
        var tabBar = TABS.map(function(tab) {
            return '<button class="pf-hub-tab' + (tab.id === intelTab ? ' active' : '') +
                '" data-hub-tab="' + tab.id + '">' + tab.label + '</button>';
        }).join('');

        var pane = intelTab === 'overview'    ? hubPaneOverview(I) :
                   intelTab === 'attribution' ? hubPaneAttribution(I) :
                                                hubPaneRisk(I);

        root.innerHTML =
            '<div class="pf-hub-head">' +
                '<div class="pf-hub-title">' + ICON('cpu') +
                    '<span>' + il('Portfolio Intelligence', 'ذكاء المحفظة') + '</span>' +
                '</div>' +
                '<div class="pf-hub-tabs">' + tabBar + '</div>' +
                '<span class="pf-live-pill"><span class="pf-live-dot"></span>' + il('Live', 'مباشر') + '</span>' +
            '</div>' +
            '<div class="pf-hub-pane">' + pane + '</div>';

        root.querySelectorAll('.pf-hub-tab').forEach(function(btn) {
            btn.addEventListener('click', function() {
                intelTab = btn.dataset.hubTab;
                renderIntelligence();
            });
        });

        // Wire sort on all tables rendered in the hub pane
        setTimeout(function() { wireAllTables(root); }, 0);

        if (intelTab === 'risk') loadDrawdownChart();
    }

    /* ── Hub pane renderers (one per tab) ────────────────────────────── */
    function hubPaneOverview(I) {
        return '<div class="pf-hub-ov">' +
            healthScoreCard(I) +
            riskExposureCard(I) +
        '</div>' +
        tradeQualityCard(I);
    }
    function hubPaneAttribution(I) {
        return strategyAttributionCard(I) + aiDecisionInsightsCard(I);
    }
    function hubPaneRisk(I) {
        return '<div class="pf-hub-risk-top">' +
            riskGuardrailsCard(I) +
            drawdownRecoveryCard(I) +
        '</div>' +
        attentionAlertsCard(I);
    }
    function hubPaneQuality(I) {
        return tradeQualityCard(I) + recommendedActionsCard(I);
    }

    /* ── 1) Portfolio Health Score ────────────────────────────────────── */
    function healthScoreCard(I) {
        var cashPct = I.cashPct;
        var liq = cashPct <= 0 ? 35 : cashPct < 3 ? 62 : cashPct <= 18 ? 92 : cashPct <= 32 ? 78 : 60;
        var sleeveScore = Math.min(I.sleeves.length, 6) / 6 * 100;
        var concPenalty = Math.max(0, I.top5 - 60);
        var div = Math.max(28, Math.min(100, sleeveScore * 0.6 + (100 - concPenalty) * 0.4));
        var conc = I.largest <= 8 ? 95 : I.largest <= 12 ? 82 : I.largest <= 20 ? 64 : 45;
        var v = I.portVol * 100;
        var volScore = v <= 12 ? 90 : v <= 20 ? 80 : v <= 30 ? 66 : 50;
        var disc = portfolio.halted ? 38 : 88;
        var score = Math.round(liq * 0.18 + div * 0.24 + conc * 0.24 + volScore * 0.16 + disc * 0.18);
        score = Math.max(1, Math.min(100, score)) || 1;

        var tone = score >= 75 ? 'is-good' : score >= 55 ? 'is-fair' : 'is-weak';
        var statusLabel = score >= 75 ? il('Healthy', 'صحية') : score >= 55 ? il('Stable', 'مستقرة') : il('Caution', 'تحذير');

        var r = 68, c = 2 * Math.PI * r, off = c * (1 - score / 100);
        var stroke = tone === 'is-good' ? 'var(--pf-green)' : tone === 'is-weak' ? 'var(--pf-red)' : 'var(--teal)';
        var gauge = '<svg viewBox="0 0 160 160" aria-hidden="true">' +
            '<circle class="pf-gauge-bg" cx="80" cy="80" r="' + r + '"/>' +
            '<circle class="pf-gauge-val" cx="80" cy="80" r="' + r + '" stroke="' + stroke + '" stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '"/>' +
        '</svg>';

        // Data-driven chips
        var volTxt = v <= 12 ? il('Low', 'منخفض') : v <= 22 ? il('Moderate', 'معتدل') : v <= 32 ? il('Elevated', 'مرتفع') : il('High', 'عالٍ');
        var volDot = v <= 22 ? 'var(--pf-green)' : v <= 32 ? 'var(--pf-amber)' : 'var(--pf-red)';
        var divGood = (I.sleeves.length >= 5 && I.top5 < 72);
        var divTxt = divGood ? il('Good', 'جيد') : I.sleeves.length >= 3 ? il('Fair', 'مقبول') : il('Concentrated', 'مركّز');
        var divDot = divGood ? 'var(--pf-green)' : I.sleeves.length >= 3 ? 'var(--pf-amber)' : 'var(--pf-red)';
        var liqStrong = cashPct >= 4 && cashPct <= 22;
        var liqTxt = liqStrong ? il('Strong', 'قوية') : cashPct >= 2 && cashPct <= 35 ? il('Adequate', 'كافية') : cashPct < 2 ? il('Tight', 'ضيقة') : il('Excess', 'فائضة');
        var liqDot = liqStrong ? 'var(--pf-green)' : 'var(--pf-amber)';
        var discTxt = portfolio.halted ? il('Review', 'مراجعة') : il('On Track', 'على المسار');
        var discDot = portfolio.halted ? 'var(--pf-red)' : 'var(--pf-green)';

        var note = score >= 75
            ? il('Healthy overall. Strong returns, ' + (I.largest > 10 ? 'moderate' : 'well-managed') + ' concentration risk, and a solid cash buffer.',
                 'صحية بشكل عام. عوائد قوية، ومخاطر تركّز ' + (I.largest > 10 ? 'معتدلة' : 'مُدارة جيداً') + '، واحتياطي نقدي قوي.')
            : score >= 55
            ? il('Stable footing with room to improve. Watch concentration and keep guardrails active.',
                 'وضع مستقر مع مجال للتحسين. راقب التركّز وأبقِ المصدّات نشطة.')
            : il('Caution warranted. Concentration and/or volatility are elevated — review positioning.',
                 'الحذر مطلوب. التركّز و/أو التقلب مرتفع — راجع المراكز.');

        function chip(label, val, dot) {
            return '<div class="pf-chip"><span class="pf-chip-label">' + label + '</span>' +
                '<span class="pf-chip-val"><span class="pf-chip-dot" style="background:' + dot + '"></span>' + val + '</span></div>';
        }

        return '<div class="pf-ic pf-health">' +
            icHead('heart', il('Portfolio Health Score', 'مؤشر صحة المحفظة'), il('Composite of liquidity, diversification, concentration & discipline', 'مركّب من السيولة والتنويع والتركّز والانضباط')) +
            '<div class="pf-health-body">' +
                '<div class="pf-gauge-wrap">' + gauge +
                    '<div class="pf-gauge-center">' +
                        '<span class="pf-gauge-score">' + score + '<sub>/100</sub></span>' +
                        '<span class="pf-gauge-tag ' + tone + '">' + statusLabel + '</span>' +
                    '</div>' +
                '</div>' +
                '<p class="pf-health-note">' + note + '</p>' +
                '<div class="pf-health-chips">' +
                    chip(il('Volatility', 'التقلب'), volTxt, volDot) +
                    chip(il('Diversification', 'التنويع'), divTxt, divDot) +
                    chip(il('Liquidity', 'السيولة'), liqTxt, liqDot) +
                    chip(il('Discipline', 'الانضباط'), discTxt, discDot) +
                '</div>' +
            '</div>' +
        '</div>';
    }

    /* ── 2) Risk Exposure Dashboard ───────────────────────────────────── */
    function riskExposureCard(I) {
        var palette = ['#E55A1F', '#FF8A3D', '#FFC396', '#C9461A', '#8b5cf6', '#14b8a6', '#3b82f6', '#94a3b8'];
        var sleeves = I.sleeves.slice(0, 7);
        var otherW = I.sleeves.slice(7).reduce(function (s, x) { return s + x.weight; }, 0);
        var segs = sleeves.map(function (s, i) { return { name: s.sector, w: s.weight, color: palette[i % palette.length] }; });
        if (otherW > 0.05) segs.push({ name: il('Other', 'أخرى'), w: otherW, color: '#94a3b8' });
        var totalW = segs.reduce(function (s, x) { return s + x.w; }, 0) || 1;

        var acc = 0, stops = segs.map(function (s) {
            var from = (acc / totalW) * 360; acc += s.w; var to = (acc / totalW) * 360;
            return s.color + ' ' + from.toFixed(1) + 'deg ' + to.toFixed(1) + 'deg';
        }).join(', ');
        var donut = '<div class="pf-donut2" style="background:conic-gradient(' + stops + ')">' +
            '<div class="pf-donut2-center"><strong>' + I.holdingsCount + '</strong><span>' + il('Holdings', 'مراكز') + '</span></div></div>';
        var legend = segs.map(function (s) {
            return '<div class="pf-dl2"><span class="pf-dl2-dot" style="background:' + s.color + '"></span>' +
                '<span class="pf-dl2-name">' + escHtml(s.name) + '</span>' +
                '<span class="pf-dl2-pct">' + fmt(s.w, 1) + '%</span></div>';
        }).join('');

        var maxW = I.byWeight[0] ? I.byWeight[0].weight : 1;
        var bars = I.byWeight.slice(0, 5).map(function (h) {
            var rel = maxW > 0 ? (h.weight / maxW) * 100 : 0;
            return '<div class="pf-conc-row"><span class="pf-conc-sym">' + escHtml(h.symbol) + '</span>' +
                '<span class="pf-conc-track"><span class="pf-conc-fill" style="width:' + rel.toFixed(1) + '%"></span></span>' +
                '<span class="pf-conc-pct">' + fmt(h.weight, 1) + '%</span></div>';
        }).join('') || ('<div class="pf-ic-sub">' + il('No open positions.', 'لا توجد مراكز مفتوحة.') + '</div>');

        function metric(label, val, sub) {
            return '<div class="pf-rex-metric"><label>' + label + '</label><div class="pf-rex-v">' + val + '</div>' +
                (sub ? '<div class="pf-rex-sub">' + sub + '</div>' : '') + '</div>';
        }
        var betaTone = I.beta > 1.15 ? 'pf-neg' : I.beta < 0.85 ? '' : '';
        var metricsRow =
            metric(il('Portfolio Beta', 'بيتا المحفظة'), '<span class="' + betaTone + '">' + fmt(I.beta, 2) + '</span>', il('vs S&P 500', 'مقابل S&P 500')) +
            metric(il('Volatility (Ann.)', 'التقلب السنوي'), fmt(I.portVol * 100, 1) + '%', il('estimated', 'تقديري')) +
            metric(il('Cash Deployment', 'نشر النقد'), fmt(I.cashDeploy, 1) + '%', il('invested', 'مُستثمر')) +
            metric(il('Largest Position', 'أكبر مركز'), fmt(I.largest, 1) + '%', I.byWeight[0] ? escHtml(I.byWeight[0].symbol) : '—') +
            metric(il('Long Exposure', 'التعرض الطويل'), fmt(I.longExp, 1) + '%', I.shortExp > 0.1 ? (il('Short', 'قصير') + ' ' + fmt(I.shortExp, 1) + '%') : il('No shorts', 'لا مكشوف')) +
            metric(il('Single-name Conc.', 'تركّز الاسم الواحد'), fmt(I.top5, 1) + '%', il('Top 5', 'أعلى 5'));

        var concVerdict = I.top5 > 65 ? il('elevated', 'مرتفع') : I.top5 > 45 ? il('moderate', 'معتدل') : il('well-balanced', 'متوازن جيداً');
        var insight = il(
            'Top 5 names make up ' + fmt(I.top5, 1) + '% of the book (' + concVerdict + '). Portfolio beta of ' + fmt(I.beta, 2) + ' implies ' + (I.beta > 1.05 ? 'above-market' : I.beta < 0.95 ? 'below-market' : 'market-like') + ' sensitivity.',
            'تشكّل أكبر 5 أسماء ' + fmt(I.top5, 1) + '% من المحفظة (' + concVerdict + '). بيتا ' + fmt(I.beta, 2) + ' تشير إلى حساسية ' + (I.beta > 1.05 ? 'أعلى من السوق' : I.beta < 0.95 ? 'أقل من السوق' : 'مماثلة للسوق') + '.'
        );

        return '<div class="pf-ic">' +
            icHead('shield', il('Risk Exposure Dashboard', 'لوحة التعرّض للمخاطر'), il('Sector mix, concentration & live exposure metrics', 'توزيع القطاعات والتركّز ومقاييس التعرّض المباشر')) +
            '<div class="pf-risk-exposure-grid">' +
                '<div><div class="pf-rex-block-title">' + il('Sector Exposure', 'التعرّض القطاعي') + '</div>' +
                    '<div class="pf-donut-row">' + donut + '<div class="pf-donut-legend2">' + legend + '</div></div></div>' +
                '<div><div class="pf-rex-block-title">' + il('Top Position Concentration', 'تركّز أكبر المراكز') + '</div>' + bars +
                    '<div class="pf-conc-total"><span>' + il('Top 5 Total', 'إجمالي أعلى 5') + '</span><strong>' + fmt(I.top5, 1) + '%</strong></div></div>' +
            '</div>' +
            '<div class="pf-rex-metrics">' + metricsRow + '</div>' +
            '<div class="pf-rex-insight">' + ICON('info') + '<span>' + insight + '</span></div>' +
        '</div>';
    }

    /* ── 3) Strategy Attribution (real per-sleeve attribution) ────────── */
    function strategyAttributionCard(I) {
        var palette = ['#E55A1F', '#FF8A3D', '#8b5cf6', '#14b8a6', '#3b82f6', '#FFC396', '#C9461A', '#94a3b8'];
        var rows = I.sleeves.map(function (s, i) {
            var ret = s.cost > 0 ? (s.gain / s.cost) * 100 : 0;
            var winRate = s.count > 0 ? (s.wins / s.count) * 100 : 0;
            var dd = Math.min.apply(null, s.rets.concat(0)); // worst position return (<=0)
            var dayCls = s.day >= 0 ? 'pf-pos' : 'pf-neg';
            var retCls = ret >= 0 ? 'pf-pos' : 'pf-neg';
            var color = s.color || palette[i % palette.length];
            // spark: cumulative path from per-position returns (visual shape of dispersion)
            var sparkVals = s.rets.slice().sort(function (a, b) { return a - b; });
            var cum = 0, cumVals = sparkVals.map(function (r) { cum += r; return cum; });
            return '<tr>' +
                '<td><div class="pf-attr-name"><span class="pf-attr-swatch" style="background:' + color + '"></span>' +
                    '<span><b>' + escHtml(s.sector) + '</b><small>' + s.count + ' ' + il('positions', 'مراكز') + '</small></span></div></td>' +
                '<td>' + moneyShort(s.mv) + '<br><small style="color:var(--muted);font-weight:500;">' + fmt(s.weight, 1) + '%</small></td>' +
                '<td class="' + dayCls + '">' + (s.day >= 0 ? '+' : '') + moneyShort(s.day) + '</td>' +
                '<td class="' + retCls + '">' + pct(ret) + '</td>' +
                '<td>' + fmt(winRate, 0) + '%</td>' +
                '<td class="pf-neg">' + fmt(dd, 1) + '%</td>' +
                '<td>' + s.count + '</td>' +
                '<td>' + svgSpark(cumVals.length > 1 ? cumVals : [0, ret], ret >= 0 ? '#22c55e' : '#ef4444') + '</td>' +
                '<td><span class="pf-attr-status' + (s.mv <= 0 ? ' is-idle' : '') + '">' + (s.mv > 0 ? il('Active', 'نشط') : il('Idle', 'خامل')) + '</span></td>' +
            '</tr>';
        }).join('');
        if (!rows) rows = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:1.5rem;">' + il('No allocation sleeves to attribute yet.', 'لا توجد شرائح تخصيص للإسناد بعد.') + '</td></tr>';

        var ths = [il('Allocation Sleeve', 'شريحة التخصيص'), il('Capital', 'رأس المال'), il("Today's P/L", 'ربح/خسارة اليوم'),
            il('Total Return', 'العائد الكلي'), il('Win Rate', 'معدل الربح'), il('Worst Pos.', 'أسوأ مركز'),
            il('Trades', 'الصفقات'), il('Trend', 'الاتجاه'), il('Status', 'الحالة')];

        return '<div class="pf-ic">' +
            icHead('layers', il('Strategy Attribution', 'إسناد الاستراتيجية'), il('Real performance contribution by allocation sleeve', 'مساهمة الأداء الحقيقية حسب شريحة التخصيص')) +
            '<div class="pf-attr-table-wrap"><table class="pf-attr-table"><thead><tr>' +
                ths.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '</div>';
    }

    /* ── 4) AI Decision Insights (derived from live signals + positions) ─ */
    function aiDecisionInsightsCard(I) {
        var src = I.byWeight.slice(0, 6);
        if (!src.length) {
            return '<div class="pf-ic">' + icHead('cpu', il('AI Decision Insights', 'رؤى قرارات الذكاء الاصطناعي')) +
                '<div class="pf-ic-sub">' + il('No open positions to analyze.', 'لا توجد مراكز لتحليلها.') + '</div></div>';
        }
        var rows = src.map(function (h) {
            var ret = h.totalReturn || 0, day = h.dayChangePct || 0, w = h.weight || 0;
            var sr = SECTOR_RISK[h.sector] || SECTOR_RISK.Other;
            var action, pillCls;
            if (portfolio.halted) { action = il('Hold', 'احتفاظ'); pillCls = 'is-hold'; }
            else if (w > 12) { action = il('Trim', 'تقليص'); pillCls = 'is-sell'; }
            else if (ret < -8) { action = il('Reduce', 'تخفيض'); pillCls = 'is-sell'; }
            else if (ret > 5 && day >= 0) { action = il('Add', 'إضافة'); pillCls = 'is-buy'; }
            else { action = il('Hold', 'احتفاظ'); pillCls = 'is-hold'; }

            var signal = w > 12 ? il('Overweight Risk', 'مخاطر وزن زائد')
                : day > 2 ? il('Bullish Breakout', 'اختراق صعودي')
                : ret > 8 ? il('Trend Continuation', 'استمرار الاتجاه')
                : ret < -5 ? il('Mean Reversion', 'ارتداد للمتوسط')
                : il('Range Bound', 'تداول عرضي');

            var pctile = signalPercentile(h.symbol);
            var conf = pctile != null ? Math.round(50 + pctile * 0.45)
                : Math.round(Math.max(52, Math.min(93, 60 + Math.abs(ret) * 1.4 + (day > 0 ? 6 : -4))));
            conf = Math.max(50, Math.min(95, conf));

            var riskLvl = (sr.vol > 0.28 || w > 12) ? 'is-high' : sr.vol < 0.12 ? 'is-low' : 'is-med';
            var riskTxt = riskLvl === 'is-high' ? il('High', 'عالٍ') : riskLvl === 'is-low' ? il('Low', 'منخفض') : il('Medium', 'متوسط');

            var hold = h.sector === 'Crypto' ? '1–3d' : h.sector === 'Defensive' ? '15–30d' : h.sector === 'Tech' ? '5–10d' : '7–14d';

            var expl = action === il('Trim', 'تقليص') ? il('Position exceeds single-name weight target; trimming reduces concentration risk.', 'يتجاوز المركز هدف وزن الاسم الواحد؛ التقليص يقلل مخاطر التركّز.')
                : action === il('Reduce', 'تخفيض') ? il('Underperforming vs cost basis; tighten risk and reassess thesis.', 'أداء أضعف من التكلفة؛ شدّد المخاطر وأعد تقييم الفرضية.')
                : action === il('Add', 'إضافة') ? il('Constructive momentum with intact trend; room to scale within limits.', 'زخم إيجابي واتجاه سليم؛ مجال للزيادة ضمن الحدود.')
                : il('Trend intact and within risk budget; maintain and monitor catalysts.', 'الاتجاه سليم وضمن ميزانية المخاطر؛ احتفظ وراقب المحفزات.');

            return '<tr>' +
                '<td><span class="pf-ai-sym">' + escHtml(h.symbol) + '</span></td>' +
                '<td><span class="pf-pill ' + pillCls + '">' + action + '</span></td>' +
                '<td><span class="pf-signal-tag">' + signal + '</span></td>' +
                '<td><div class="pf-conf"><span class="pf-conf-track"><span class="pf-conf-fill" style="width:' + conf + '%"></span></span><span class="pf-conf-num">' + conf + '%</span></div></td>' +
                '<td><span class="pf-risk-dot ' + riskLvl + '">' + riskTxt + '</span></td>' +
                '<td><span class="pf-num" style="font-size:.76rem;">' + hold + '</span></td>' +
                '<td><span class="pf-ai-expl">' + expl + '</span></td>' +
            '</tr>';
        }).join('');

        var ths = [il('Symbol', 'الرمز'), il('Action', 'الإجراء'), il('Signal', 'الإشارة'), il('Confidence', 'الثقة'),
            il('Risk', 'المخاطر'), il('Hold', 'المدة'), il('Rationale', 'المبرر')];

        return '<div class="pf-ic">' +
            icHead('cpu', il('AI Decision Insights', 'رؤى قرارات الذكاء الاصطناعي'), il('How the engine reads each core position right now', 'كيف يقرأ المحرك كل مركز أساسي الآن')) +
            '<div class="pf-ai-table-wrap"><table class="pf-ai-table"><thead><tr>' +
                ths.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '</div>';
    }

    /* ── 5) Recommended Actions (contextual, priority-sorted) ─────────── */
    function recommendedActionsCard(I) {
        var actions = [];
        var topSym = I.byWeight[0] ? I.byWeight[0].symbol : null;
        if (I.largest > 12) actions.push(['high', il('Trim overweight position', 'تقليص المركز ذي الوزن الزائد'), il('' + topSym + ' is ' + fmt(I.largest, 1) + '% of equity — above the single-name target.', '' + topSym + ' يمثل ' + fmt(I.largest, 1) + '% — أعلى من هدف الاسم الواحد.')]);
        else if (I.largest > 8) actions.push(['med', il('Watch top-position weight', 'راقب وزن أكبر مركز'), il('' + topSym + ' at ' + fmt(I.largest, 1) + '% is approaching the concentration cap.', '' + topSym + ' عند ' + fmt(I.largest, 1) + '% يقترب من حد التركّز.')]);

        if (I.cashDeploy < 85) actions.push(['med', il('Deploy idle cash gradually', 'انشر النقد الخامل تدريجياً'), il('Only ' + fmt(I.cashDeploy, 0) + '% deployed — scale in to target on strength.', 'فقط ' + fmt(I.cashDeploy, 0) + '% مُستثمر — ازد تدريجياً عند القوة.')]);
        else if (I.cashDeploy > 97) actions.push(['med', il('Rebuild a cash buffer', 'أعد بناء احتياطي نقدي'), il('Cash buffer is thin at ' + fmt(I.cashPct, 1) + '% — trim to restore dry powder.', 'الاحتياطي النقدي ضعيف عند ' + fmt(I.cashPct, 1) + '% — قلّص لاستعادة المرونة.')]);

        var losers = I.holds.filter(function (h) { return (h.totalReturn || 0) < -8; }).sort(function (a, b) { return a.totalReturn - b.totalReturn; });
        if (losers.length) actions.push([losers[0].totalReturn < -15 ? 'high' : 'med', il('Review losing positions', 'راجع المراكز الخاسرة'), il(losers.length + ' position' + (losers.length > 1 ? 's' : '') + ' down >8% (worst: ' + losers[0].symbol + ' ' + fmt(losers[0].totalReturn, 1) + '%).', losers.length + ' مركز بانخفاض >8% (الأسوأ: ' + losers[0].symbol + ' ' + fmt(losers[0].totalReturn, 1) + '%).')]);

        if (I.sleeves.length <= 2 || (I.sleeves[0] && I.sleeves[0].weight > 45)) actions.push(['med', il('Rebalance sector exposure', 'أعد توازن التعرّض القطاعي'), il('Allocation is sleeve-heavy — diversify toward target ranges.', 'التخصيص مركّز في شريحة — نوّع نحو النطاقات المستهدفة.')]);

        actions.push(['low', il('Keep risk guardrails active', 'أبقِ مصدّات المخاطر نشطة'), il('Daily, weekly and kill-switch limits are armed — leave enabled.', 'حدود يومية وأسبوعية ومفتاح إيقاف مُفعّلة — اتركها مفعّلة.')]);
        actions.push(['low', il('Review earnings calendar', 'راجع جدول الأرباح'), il('Check upcoming reports for core holdings to pre-empt volatility.', 'تحقق من التقارير القادمة للمراكز الأساسية لاستباق التقلب.')]);

        var rank = { high: 0, med: 1, low: 2 };
        actions.sort(function (a, b) { return rank[a[0]] - rank[b[0]]; });
        actions = actions.slice(0, 6);

        var prioLabel = { high: il('High', 'عالٍ'), med: il('Medium', 'متوسط'), low: il('Low', 'منخفض') };
        var prioCls = { high: 'is-high', med: 'is-med', low: 'is-low' };
        var list = actions.map(function (a) {
            return '<div class="pf-action-item"><span class="pf-action-check">' + ICON('check') + '</span>' +
                '<div class="pf-action-text"><b>' + a[1] + '</b><small>' + a[2] + '</small></div>' +
                '<span class="pf-prio ' + prioCls[a[0]] + '">' + prioLabel[a[0]] + '</span></div>';
        }).join('');

        return '<div class="pf-ic">' +
            icHead('check', il('Recommended Actions', 'إجراءات موصى بها')) +
            '<div class="pf-actions-list">' + list + '</div>' +
        '</div>';
    }

    /* ── 6) Advanced Risk Guardrails (hardcoded institutional limits) ─── */
    function riskGuardrailsCard(I) {
        var armed = !portfolio.halted;
        function row(name, sub, val, kind) {
            // kind: 'toggle' | 'pill'
            var right = kind === 'toggle'
                ? '<span class="pf-toggle ' + (armed ? 'is-on' : 'is-off') + '" role="img" aria-label="' + (armed ? 'armed' : 'off') + '"></span>'
                : '<span class="pf-guard-pill">' + il('Active', 'نشط') + '</span>';
            return '<div class="pf-guard-row">' +
                '<div class="pf-guard-name"><b>' + name + '</b>' + (sub ? '<small>' + sub + '</small>' : '') + '</div>' +
                (val ? '<span class="pf-guard-val">' + val + '</span>' : '') + right + '</div>';
        }
        var rows =
            row(il('Daily Loss Limit', 'حد الخسارة اليومي'), il('halt 24h on breach', 'إيقاف 24س عند الاختراق'), '4.0%', 'pill') +
            row(il('Weekly Loss Limit', 'حد الخسارة الأسبوعي'), il('halt 7d on breach', 'إيقاف 7أ عند الاختراق'), '8.0%', 'pill') +
            row(il('Max Position Size', 'الحد الأقصى للمركز'), il('stock 8% · ETF 12%', 'سهم 8% · ETF 12%'), '8–12%', 'pill') +
            row(il('Max Sector Exposure', 'الحد الأقصى للقطاع'), il('per allocation sleeve', 'لكل شريحة تخصيص'), '30%', 'pill') +
            row(il('Stop-loss Coverage', 'تغطية وقف الخسارة'), il('ATR trailing on entries', 'وقف متحرك ATR على الدخول'), '100%', 'pill') +
            row(il('Kill Switch', 'مفتاح الإيقاف'), il('liquidate at 18% drawdown', 'تسييل عند تراجع 18%'), '', 'toggle') +
            row(il('Human Approval Threshold', 'حد الموافقة البشرية'), il('orders above notional', 'الأوامر فوق القيمة'), '>$25K', 'pill');

        return '<div class="pf-ic">' +
            icHead('lock', il('Advanced Risk Guardrails', 'مصدّات المخاطر المتقدمة'), il('Non-negotiable hard limits', 'حدود صارمة غير قابلة للتفاوض')) +
            '<div class="pf-guard-list">' + rows + '</div>' +
        '</div>';
    }

    /* ── 7) Drawdown & Recovery (real equity history) ─────────────────── */
    function drawdownRecoveryCard(I) {
        return '<div class="pf-ic" id="pfDdCard">' +
            icHead('trend', il('Drawdown & Recovery', 'التراجع والتعافي'), il('Underwater curve from real equity history', 'منحنى التراجع من تاريخ الأسهم الحقيقي')) +
            '<div class="pf-dd-stats">' +
                '<div class="pf-dd-stat"><label>' + il('Current Drawdown', 'التراجع الحالي') + '</label><div class="pf-dd-v" id="ddCurrent">—</div></div>' +
                '<div class="pf-dd-stat"><label>' + il('Max Drawdown', 'أقصى تراجع') + '</label><div class="pf-dd-v pf-neg" id="ddMax">—</div></div>' +
                '<div class="pf-dd-stat"><label>' + il('Days Since High', 'أيام منذ القمة') + '</label><div class="pf-dd-v" id="ddDays">—</div></div>' +
                '<div class="pf-dd-stat"><label>' + il('Est. Recovery', 'التعافي المقدّر') + '</label><div class="pf-dd-v" id="ddRecovery">—</div></div>' +
            '</div>' +
            '<div id="ddChart"><svg class="pf-dd-chart" viewBox="0 0 300 92" preserveAspectRatio="none" aria-hidden="true"></svg></div>' +
            '<div class="pf-dd-axis"><span id="ddAxisL">' + il('peak', 'القمة') + '</span><span id="ddAxisR">' + il('now', 'الآن') + '</span></div>' +
            '<div class="pf-dd-risk"><span>' + il('Breach Risk (vs 18% kill-switch)', 'مخاطر الاختراق (مقابل 18%)') + '</span><span class="pf-guard-pill" id="ddBreach">—</span></div>' +
        '</div>';
    }

    function loadDrawdownChart() {
        if (typeof bmFetchEquity !== 'function') return;
        bmFetchEquity('All').then(function (rows) {
            if (!rows || rows.length < 2) { drawDrawdownEmpty(); return; }
            var eq = rows.map(function (r) { return parseFloat(r.equity) || 0; });
            var peak = eq[0], dd = [], peakIdx = 0, maxDD = 0;
            eq.forEach(function (v, i) {
                if (v > peak) { peak = v; peakIdx = i; }
                var d = peak > 0 ? (v / peak - 1) * 100 : 0;
                dd.push(d); if (d < maxDD) maxDD = d;
            });
            var current = dd[dd.length - 1];
            // days since high: from last index where a new peak was set
            var lastPeakIdx = 0;
            var rp = eq[0];
            eq.forEach(function (v, i) { if (v >= rp) { rp = v; lastPeakIdx = i; } });
            var daysSince = Math.max(0, eq.length - 1 - lastPeakIdx);

            // recovery estimate: drawdown depth / avg positive daily move
            var gains = [];
            for (var i = 1; i < eq.length; i++) { var ch = eq[i] / eq[i - 1] - 1; if (ch > 0) gains.push(ch); }
            var avgGain = gains.length ? gains.reduce(function (s, x) { return s + x; }, 0) / gains.length : 0;
            var recovery = (current < -0.05 && avgGain > 0) ? Math.ceil(Math.abs(current / 100) / avgGain) : 0;

            patch('ddCurrent', fmt(current, 1) + '%', current < 0 ? 'pf-neg' : 'pf-pos');
            patch('ddMax', fmt(maxDD, 1) + '%');
            patch('ddDays', daysSince + 'd');
            patch('ddRecovery', current < -0.05 ? (recovery > 0 ? '~' + recovery + 'd' : '—') : il('At highs', 'عند القمة'), current < -0.05 ? '' : 'pf-pos');

            var breach = Math.abs(current) >= 12 ? 'high' : Math.abs(current) >= 6 ? 'med' : 'low';
            var be = document.getElementById('ddBreach');
            if (be) {
                be.textContent = breach === 'high' ? il('High', 'عالٍ') : breach === 'med' ? il('Medium', 'متوسط') : il('Low', 'منخفض');
                be.className = 'pf-prio ' + (breach === 'high' ? 'is-high' : breach === 'med' ? 'is-med' : 'is-low');
            }

            // axis dates
            var lt = document.getElementById('ddAxisL'), rt = document.getElementById('ddAxisR');
            if (lt && rows[0].date) lt.textContent = (rows[0].date || '').slice(0, 10);
            if (rt && rows[rows.length - 1].date) rt.textContent = (rows[rows.length - 1].date || '').slice(0, 10);

            drawDrawdownSvg(dd);
        }).catch(function () { drawDrawdownEmpty(); });

        function patch(id, txt, cls) {
            var n = document.getElementById(id);
            if (!n) return;
            n.textContent = txt;
            n.classList.remove('pf-pos', 'pf-neg');
            if (cls) n.classList.add(cls);
        }
    }
    function drawDrawdownSvg(dd) {
        var svg = document.querySelector('#ddChart svg');
        if (!svg) return;
        var w = 300, h = 92;
        var min = Math.min.apply(null, dd); if (min >= 0) min = -1;
        var n = dd.length, step = n > 1 ? w / (n - 1) : w;
        var pts = dd.map(function (v, i) { return [i * step, Math.min(h - 2, (v / min) * (h - 12) + 2)]; });
        var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
        var area = line + ' L ' + (pts[n - 1][0]).toFixed(1) + ' 0 L 0 0 Z';
        svg.innerHTML =
            '<defs><linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">' +
                '<stop offset="0%" stop-color="#ef4444" stop-opacity="0.04"/>' +
                '<stop offset="100%" stop-color="#ef4444" stop-opacity="0.22"/>' +
            '</linearGradient></defs>' +
            '<path d="' + area + '" fill="url(#ddGrad)"/>' +
            '<path d="' + line + '" fill="none" stroke="#ef4444" stroke-width="1.6" stroke-linejoin="round"/>';
    }
    function drawDrawdownEmpty() {
        ['ddCurrent', 'ddMax', 'ddDays', 'ddRecovery'].forEach(function (id) { var n = document.getElementById(id); if (n && n.textContent === '—') n.textContent = '—'; });
        var be = document.getElementById('ddBreach'); if (be) be.textContent = il('Syncing…', 'مزامنة…');
    }

    /* ── 8) Trade Quality Analytics (learning report + live positions) ── */
    // Aggregate per-portfolio learning reports (the `all` view delivers an
    // array of { id, label, report }) into a single overall block, or return
    // the single portfolio's overall block directly. Real closed-trade data
    // only — no fabrication.
    function resolveLearningOverall(lrRaw) {
        if (!lrRaw) return null;
        if (!Array.isArray(lrRaw)) return lrRaw.overall || null;
        var totalTrades = 0, wins = 0, losses = 0, winPctSum = 0, lossPctSum = 0;
        lrRaw.forEach(function (item) {
            var o = item && item.report && item.report.overall;
            if (!o || !o.total_trades) return;
            totalTrades += o.total_trades;
            wins += (o.wins || 0);
            losses += (o.losses || 0);
            winPctSum  += Math.abs(o.avg_win_pct  || 0) * (o.wins   || 0);
            lossPctSum += Math.abs(o.avg_loss_pct || 0) * (o.losses || 0);
        });
        if (totalTrades <= 0) return null;
        return {
            total_trades: totalTrades,
            win_rate: wins / totalTrades,
            avg_win_pct: wins ? winPctSum / wins : 0,
            avg_loss_pct: losses ? lossPctSum / losses : 0,
            profit_factor: lossPctSum > 0 ? winPctSum / lossPctSum : (winPctSum > 0 ? 99 : 0),
            sharpe_estimate: null
        };
    }
    function computeTradeQuality(I) {
        var lr = (detailCache) ? resolveLearningOverall(detailCache.learning_report) : null;
        var hasClosed = lr && lr.total_trades > 0;

        // Fallback to live open-position quality when no closed-trade history.
        var winners = I.holds.filter(function (h) { return (h.totalGain || 0) > 0; });
        var losers = I.holds.filter(function (h) { return (h.totalGain || 0) < 0; });
        var sumWin = winners.reduce(function (s, h) { return s + h.totalGain; }, 0);
        var sumLoss = Math.abs(losers.reduce(function (s, h) { return s + h.totalGain; }, 0));
        var avgWinPct = winners.length ? winners.reduce(function (s, h) { return s + h.totalReturn; }, 0) / winners.length : 0;
        var avgLossPct = losers.length ? losers.reduce(function (s, h) { return s + h.totalReturn; }, 0) / losers.length : 0;

        var winRate = hasClosed ? lr.win_rate * 100 : (I.holds.length ? (winners.length / I.holds.length) * 100 : 0);
        var avgWin = hasClosed ? lr.avg_win_pct : avgWinPct;
        var avgLoss = hasClosed ? -Math.abs(lr.avg_loss_pct) : avgLossPct;
        var pf = hasClosed ? lr.profit_factor : (sumLoss > 0 ? sumWin / sumLoss : (sumWin > 0 ? 99 : 0));
        var sharpe = hasClosed && lr.sharpe_estimate ? lr.sharpe_estimate : null;

        // Turnover & holding period from trade log (real where available)
        var tl = (detailCache && detailCache.trade_log) ? detailCache.trade_log : [];
        var now = Date.now();
        var ages = [], turnoverVal = 0;
        tl.forEach(function (tr) {
            var d = tr.date || (tr.timestamp ? tr.timestamp.slice(0, 10) : null);
            if (d) { var age = (now - new Date(d).getTime()) / 86400000; if (age >= 0 && age < 800) ages.push(age); }
            var v = tr.estimated_value || ((tr.entry_price || tr.limit_price || tr.price || 0) * (tr.qty || 0));
            if (v) turnoverVal += v;
        });
        var avgHold = ages.length ? ages.reduce(function (s, x) { return s + x; }, 0) / ages.length : null;
        var turnover = (I.equity > 0 && turnoverVal > 0) ? Math.min(100, (turnoverVal / I.equity) * 100) : null;

        return { hasClosed: hasClosed, winRate: winRate, avgWin: avgWin, avgLoss: avgLoss, pf: pf, sharpe: sharpe, turnover: turnover, avgHold: avgHold };
    }
    function tradeQualityCard(I) {
        var q = computeTradeQuality(I);
        function card(label, val, seed, color, foot, footCls) {
            return '<div class="pf-tq-card">' +
                '<div class="pf-tq-top"><span class="pf-tq-label">' + label + '</span></div>' +
                '<div class="pf-tq-val">' + val + '</div>' +
                svgMicroBars(barsSeed(seed, 8), color) +
                '<span class="pf-tq-foot ' + footCls + '">' + foot + '</span>' +
            '</div>';
        }
        var green = '#22c55e', red = '#ef4444', teal = 'var(--teal)';
        var wrFoot = q.winRate >= 55 ? ['is-good', il('Above avg', 'فوق المتوسط')] : q.winRate >= 45 ? ['is-warn', il('In range', 'ضمن النطاق')] : ['is-bad', il('Below avg', 'تحت المتوسط')];
        var pfFoot = q.pf >= 1.5 ? ['is-good', il('Healthy', 'صحي')] : q.pf >= 1 ? ['is-warn', il('Marginal', 'حدّي')] : ['is-bad', il('At risk', 'في خطر')];
        var shFoot = q.sharpe == null ? ['is-warn', il('Building', 'قيد البناء')] : q.sharpe >= 1 ? ['is-good', il('Strong', 'قوي')] : ['is-warn', il('Developing', 'متطور')];

        var grid =
            card(il('Win Rate', 'معدل الربح'), fmt(q.winRate, 1) + '%', 'winrate' + pfId, green, wrFoot[1], wrFoot[0]) +
            card(il('Avg Win', 'متوسط الربح'), '+' + fmt(Math.abs(q.avgWin), 2) + '%', 'avgwin' + pfId, green, il('per winner', 'لكل رابح'), 'is-good') +
            card(il('Avg Loss', 'متوسط الخسارة'), fmt(-Math.abs(q.avgLoss), 2) + '%', 'avgloss' + pfId, red, il('per loser', 'لكل خاسر'), 'is-bad') +
            card(il('Profit Factor', 'عامل الربح'), q.pf >= 99 ? '∞' : fmt(q.pf, 2), 'pf' + pfId, teal, pfFoot[1], pfFoot[0]) +
            card(il('Sharpe Ratio', 'نسبة شارب'), q.sharpe == null ? '—' : fmt(q.sharpe, 2), 'sharpe' + pfId, teal, shFoot[1], shFoot[0]) +
            card(il('Turnover', 'معدل الدوران'), q.turnover == null ? '—' : fmt(q.turnover, 1) + '%', 'turn' + pfId, teal, il('of equity', 'من حقوق الملكية'), 'is-warn') +
            card(il('Avg Hold', 'متوسط المدة'), q.avgHold == null ? '—' : fmt(q.avgHold, 1) + 'd', 'hold' + pfId, teal, il('holding period', 'فترة الاحتفاظ'), 'is-good') +
            card(il('Open Positions', 'مراكز مفتوحة'), String(I.holdingsCount), 'open' + pfId, teal, il('live', 'مباشر'), 'is-good');

        var note = q.hasClosed ? il('From closed-trade learning report.', 'من تقرير تعلّم الصفقات المغلقة.') : il('Derived from live open positions (closed-trade history is still building).', 'مشتق من المراكز المفتوحة المباشرة (سجل الصفقات المغلقة قيد البناء).');

        return '<div class="pf-ic">' +
            icHead('trend', il('Trade Quality Analytics', 'تحليلات جودة التداول'), note) +
            '<div class="pf-tq-grid">' + grid + '</div>' +
        '</div>';
    }

    /* ── 9) Attention Required / Alerts (contextual severity) ─────────── */
    function attentionAlertsCard(I) {
        var alerts = [];
        if (portfolio.halted) alerts.push(['high', il('Trading is halted', 'التداول متوقف'), il('A safety guardrail tripped. Review the halt reason before re-enabling.', 'تم تفعيل مصدّ أمان. راجع سبب الإيقاف قبل إعادة التفعيل.')]);

        if (I.largest > 10) alerts.push([I.largest > 14 ? 'high' : 'med', il('Single-name concentration is high', 'تركّز الاسم الواحد مرتفع'),
            il((I.byWeight[0] ? I.byWeight[0].symbol : 'Top position') + ' is ' + fmt(I.largest, 1) + '% of equity; consider trimming toward target.', (I.byWeight[0] ? I.byWeight[0].symbol : 'أكبر مركز') + ' يمثل ' + fmt(I.largest, 1) + '%؛ فكّر في التقليص نحو الهدف.')]);

        if (I.beta > 1.1) alerts.push(['med', il('Portfolio beta is above target', 'بيتا المحفظة أعلى من الهدف'),
            il('Beta of ' + fmt(I.beta, 2) + ' adds market sensitivity; defensive sleeves can soften swings.', 'بيتا ' + fmt(I.beta, 2) + ' تزيد حساسية السوق؛ الشرائح الدفاعية تخفف التقلبات.')]);

        if (I.cashDeploy < 80) alerts.push(['med', il('Cash deployment is low', 'نشر النقد منخفض'),
            il('Only ' + fmt(I.cashDeploy, 0) + '% is invested — idle cash is a drag in trending markets.', 'فقط ' + fmt(I.cashDeploy, 0) + '% مُستثمر — النقد الخامل يثقل الأداء في الأسواق الصاعدة.')]);

        var losers = I.holds.filter(function (h) { return (h.totalReturn || 0) < -6; });
        if (losers.length) alerts.push(['low', il('Some positions need a stop-loss review', 'بعض المراكز تحتاج مراجعة وقف الخسارة'),
            il(losers.length + ' position' + (losers.length > 1 ? 's are' : ' is') + ' below the -6% review line.', losers.length + ' مركز تحت خط المراجعة -6%.')]);

        if (!alerts.length) alerts.push(['low', il('No critical alerts', 'لا توجد تنبيهات حرجة'),
            il('Concentration, beta, cash deployment and open P/L are all within target ranges.', 'التركّز والبيتا ونشر النقد والأرباح المفتوحة جميعها ضمن النطاقات المستهدفة.')]);

        var rank = { high: 0, med: 1, low: 2 };
        alerts.sort(function (a, b) { return rank[a[0]] - rank[b[0]]; });

        var sevLabel = { high: il('High', 'عالٍ'), med: il('Medium', 'متوسط'), low: il('Low', 'منخفض') };
        var sevCls = { high: 'sev-high', med: 'sev-med', low: 'sev-low' };
        var list = alerts.map(function (a) {
            return '<div class="pf-alert ' + sevCls[a[0]] + '">' +
                '<span class="pf-alert-ico">' + ICON(a[0] === 'low' ? 'info' : 'bell') + '</span>' +
                '<div class="pf-alert-body"><b>' + a[1] + '</b><p>' + a[2] + '</p></div>' +
                '<span class="pf-alert-sev">' + sevLabel[a[0]] + '</span></div>';
        }).join('');

        return '<div class="pf-ic">' +
            icHead('bell', il('Attention Required', 'تتطلب الانتباه'), il('Plain-English alerts, prioritized by severity', 'تنبيهات واضحة مرتّبة حسب الخطورة')) +
            '<div class="pf-alerts-list">' + list + '</div>' +
        '</div>';
    }

    /* ─── Positions Matrix (Holdings Table with Click switching) ──────── */
    function renderHoldings(tab) {
        holdingsTab = tab;
        tabChartInst = null;
        var sec = document.getElementById('holdingsSection');
        if (!sec) return;

        var HTABS = [
            { k: 'overview',    l: t('overview') },
            { k: 'performance', l: t('performance') },
            { k: 'allocation',  l: t('allocation') },
            { k: 'dividendTab', l: t('dividendTab') },
            { k: 'orders',      l: il('Open Orders', 'الأوامر المفتوحة') },
        ];
        var tabs = HTABS.map(function(tb) {
            return '<button class="pf-tab' + (holdingsTab === tb.k ? ' active' : '') + '" data-tab="' + tb.k + '">' + tb.l + '</button>';
        }).join('');

        var tableHtml = holdingsTab === 'overview'     ? holdingsOverviewTable()     :
                        holdingsTab === 'performance'   ? holdingsPerformanceTable()  :
                        holdingsTab === 'allocation'    ? holdingsAllocationTable()   :
                        holdingsTab === 'orders'        ? holdingsOrdersTable()       :
                                                          holdingsDividendsTable();
        var chartHtml = holdingsTab === 'overview'     ? holdingsOverviewChart()      :
                        holdingsTab === 'performance'   ? holdingsPerformanceChart()   :
                        holdingsTab === 'allocation'    ? holdingsAllocationChart()    :
                        holdingsTab === 'orders'        ? holdingsOrdersTable()        :
                                                          holdingsDividendsChart();

        var viewLabel = holdingsViewMode === 'table' ? (lang==='ar' ? 'عرض رسم بياني' : 'Chart View') : (lang==='ar' ? 'عرض جدول' : 'Table View');
        var toggleIcon = holdingsViewMode === 'table'
            ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>'
            : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><rect x="5" y="5" width="14" height="14" rx="1" fill="currentColor" opacity="0.3"/><polyline points="5,17 8,14 11,17 14,12 17,15 19,10"/></svg>';

        sec.innerHTML =
            '<div class="pf-holdings-head">' +
                '<div class="pf-tabs">' + tabs + '</div>' +
                '<div style="display:flex;gap:.5rem;align-items:center;">' +
                    '<button class="pf-btn pf-btn--sm pf-view-toggle" id="holdViewToggle" title="Toggle View" style="padding:0.35rem 0.55rem; font-size:0.7rem; gap:0.25rem;">' + toggleIcon + ' <span>' + viewLabel + '</span></button>' +
                    '<button class="pf-btn pf-btn--sm" id="holdAddTx">+ ' + t('addTx') + '</button>' +
                '</div>' +
            '</div>' +
            (holdingsViewMode === 'table' 
                ? '<div class="pf-table-wrap pf-table-scroll">' + tableHtml + '</div>'
                : '<div class="pf-chart-area">' + chartHtml + '</div>');

        // Wire sort on all tables in this section
        if (holdingsViewMode === 'table') setTimeout(function() { wireAllTables(sec); }, 0);
        // Sync sidebar height to match this column's real height
        setTimeout(syncSidebarHeight, 80);

        sec.querySelectorAll('.pf-tab').forEach(function(tabEl){
            tabEl.addEventListener('click', function(){ holdingsViewMode = 'table'; renderHoldings(tabEl.dataset.tab); });
        });
        
        var addBtn = sec.querySelector('#holdAddTx');
        if (addBtn) addBtn.addEventListener('click', openOrderModal);

        var vt = sec.querySelector('#holdViewToggle');
        if (vt) {
            vt.addEventListener('click', function() {
                holdingsViewMode = holdingsViewMode === 'table' ? 'chart' : 'table';
                renderHoldings(holdingsTab);
            });
        }

        // Chart initialization (after DOM rendered)
        if (holdingsViewMode === 'chart' && holdingsTab !== 'orders') {
            setTimeout(function() {
                if (holdingsTab === 'overview') initOverviewChart();
                else if (holdingsTab === 'performance') initPerformanceChart();
                else if (holdingsTab === 'allocation') initAllocationChart();
                else if (holdingsTab === 'dividendTab') initDividendChart();
            }, 50);
        }
        // Orders tab always shows table (no chart variant)
        if (holdingsTab === 'orders') wireCancelButtons();

        // Bind row clicks → drill into the dedicated stock detail page
        if (holdingsViewMode === 'table') {
            sec.querySelectorAll('tbody tr').forEach(function(row) {
                row.style.cursor = 'pointer';
                row.addEventListener('click', function() {
                    var sym = row.getAttribute('data-symbol');
                    if (sym) window.location.href = '/stock-detail.html?symbol=' + encodeURIComponent(sym);
                });
            });
            // Per-row action button: trade the symbol (individual portfolio) or
            // drill into stock detail (read-only aggregate view).
            sec.querySelectorAll('.pf-row-action').forEach(function(btn) {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    var sym = btn.getAttribute('data-symbol');
                    if (!sym) return;
                    if (pfId === 'all' || !portfolio.isServer) {
                        window.location.href = '/stock-detail.html?symbol=' + encodeURIComponent(sym);
                    } else {
                        openOrderModal(sym);
                    }
                });
            });
        }
    }

    function holdingsOverviewTable() {
        var ths = [t('symbol'), t('qty'), t('avgCost'), t('lastPrice'), t('mktValue'), t('weight'), t('dayChange'), t('totalPL'), t('action')];
        var rows = metrics.holdings.map(function(h){
            var dayClass = h.dayChange >= 0 ? 'pf-pos' : 'pf-neg';
            var plClass  = h.totalGain  >= 0 ? 'pf-pos' : 'pf-neg';
            var intraClass = (h.unrealizedIntradayPl || 0) >= 0 ? 'pf-pos' : 'pf-neg';
            var activeClass = h.symbol === selectedSymbol ? 'style="background:rgba(229,90,31,0.06); font-weight:bold;"' : '';
            return '<tr data-symbol="' + h.symbol + '" ' + activeClass + '>' +
                '<td>' + symChip(h) + '</td>' +
                '<td class="num pf-num">' + h.quantity.toLocaleString() + '</td>' +
                '<td class="num pf-num">$' + fmt(h.avgCost) + '</td>' +
                '<td class="num pf-num">$' + fmt(h.lastPrice) + '</td>' +
                '<td class="num pf-num">$' + fmt(h.marketValue) + '</td>' +
                '<td class="num pf-num">' + h.weight.toFixed(1) + '%</td>' +
                '<td class="num"><span class="' + dayClass + ' pf-num">' + (h.dayChange >= 0 ? '+' : '') + fmt(h.dayChange) + '</span>' +
                    '<br><span class="' + dayClass + ' pf-num" style="font-size:.7rem;">' + pct(h.dayChangePct) + '</span>' +
                    ((h.unrealizedIntradayPl !== undefined && h.unrealizedIntradayPl !== 0) ? 
                        `<br><span class="${intraClass} pf-num" style="font-size:0.65rem; opacity:0.85; font-weight:600;">Day: ${(h.unrealizedIntradayPl >= 0 ? '+' : '')}$${money(h.unrealizedIntradayPl)}</span>` : '') +
                '</td>' +
                '<td class="num"><span class="' + plClass + ' pf-num">' + (h.totalGain >= 0 ? '+' : '') + fmt(h.totalGain) + '</span>' +
                    '<br><span class="' + plClass + ' pf-num" style="font-size:.7rem;">' + pct(h.totalReturn) + '</span></td>' +
                '<td><button class="pf-action-btn pf-row-action" data-symbol="' + escHtml(h.symbol) + '" title="' + (pfId === 'all' ? il('Open ' + h.symbol + ' detail', 'فتح تفاصيل ' + h.symbol) : il('Trade ' + h.symbol, 'تداول ' + h.symbol)) + '">⋮</button></td>' +
            '</tr>';
        }).join('');
        return thTable(ths) + '<tbody>' + rows + '</tbody></table>';
    }

    function holdingsPerformanceTable() {
        var ths = [
            t('symbol'), 
            t('avgCost'), 
            t('lastPrice'), 
            lang === 'ar' ? 'تكلفة المركز' : 'Cost Basis',
            t('totalPL'), 
            t('totalRet'), 
            lang === 'ar' ? 'أرباح اليوم غير المحققة' : 'Intraday P&L',
            t('dayChange')
        ];
        var rows = metrics.holdings.map(function(h){
            var plCls = h.totalGain  >= 0 ? 'pf-pos' : 'pf-neg';
            var dayCls = h.dayChange >= 0 ? 'pf-pos' : 'pf-neg';
            var intraCls = (h.unrealizedIntradayPl || 0) >= 0 ? 'pf-pos' : 'pf-neg';
            var activeClass = h.symbol === selectedSymbol ? 'style="background:rgba(229,90,31,0.06); font-weight:bold;"' : '';
            return '<tr data-symbol="' + h.symbol + '" ' + activeClass + '><td>' + symChip(h) + '</td>' +
                '<td class="num pf-num">$' + fmt(h.avgCost) + '</td>' +
                '<td class="num pf-num">$' + fmt(h.lastPrice) + '</td>' +
                '<td class="num pf-num">$' + fmt(h.costBasis || (h.quantity * h.avgCost)) + '</td>' +
                '<td class="num pf-num ' + plCls + '">' + (h.totalGain >= 0 ? '+' : '') + '$' + money(h.totalGain) + '</td>' +
                '<td class="num pf-num ' + plCls + '">' + (h.totalReturn >= 0 ? '+' : '') + fmt(h.totalReturn) + '%</td>' +
                '<td class="num pf-num ' + intraCls + '">' + (h.unrealizedIntradayPl >= 0 ? '+' : '') + '$' + money(h.unrealizedIntradayPl) + ' (' + pct(h.unrealizedIntradayPlpc) + ')</td>' +
                '<td class="num pf-num ' + dayCls + '">' + (h.dayChange >= 0 ? '+' : '') + fmt(h.dayChange) + ' (' + pct(h.dayChangePct) + ')</td>' +
            '</tr>';
        }).join('');
        return thTable(ths) + '<tbody>' + rows + '</tbody></table>';
    }

    function holdingsAllocationTable() {
        var ths = [t('symbol'), t('mktValue'), t('weight'), 'Allocation Bucket'];
        var total = metrics.totalMarketValue;
        var rows = metrics.holdings.map(function(h){
            var barW = total > 0 ? (h.marketValue / total) * 100 : 0;
            var activeClass = h.symbol === selectedSymbol ? 'style="background:rgba(229,90,31,0.06); font-weight:bold;"' : '';
            return '<tr data-symbol="' + h.symbol + '" ' + activeClass + '><td>' + symChip(h) + '</td>' +
                '<td class="num pf-num">$' + fmt(h.marketValue) + '</td>' +
                '<td><div style="display:flex;align-items:center;gap:.5rem;">' +
                    '<div style="flex:1;height:4px;background:var(--line);border-radius:999px;"><div style="height:100%;background:' + h.color + ';width:' + barW.toFixed(1) + '%;border-radius:999px;"></div></div>' +
                    '<span class="pf-num" style="font-size:.75rem;min-width:3rem;">' + h.weight.toFixed(1) + '%</span>' +
                '</div></td>' +
                '<td><span class="pf-badge-neu">' + h.sector + '</span></td>' +
            '</tr>';
        }).join('');
        return thTable(ths) + '<tbody>' + rows + '</tbody></table>';
    }

    function holdingsDividendsTable() {
        if (!portfolio.transactions.length) return '<div class="pf-empty">' + (lang==='ar'?'لا توجد معاملات مسجلة.':'No transactions recorded.') + '</div>';
        
        var ths = [il('Date', 'التاريخ'), t('symbol'), il('Type', 'النوع'), il('Qty', 'الكمية'), il('Price', 'السعر'), il('Cost Basis', 'تكلفة المركز'), il('Description', 'الوصف')];
        var rows = portfolio.transactions.slice().reverse().slice(0, 20).map(function(tx){
            var cls = tx.type === 'buy' ? 'pf-neg' : 'pf-pos';
            var activeClass = tx.symbol === selectedSymbol ? 'style="background:rgba(229,90,31,0.06); font-weight:bold;"' : '';
            return '<tr data-symbol="' + tx.symbol + '" ' + activeClass + '>' +
                '<td>' + tx.date + '</td>' +
                '<td>' + symChipBySymbol(tx.symbol) + '</td>' +
                '<td><span class="pf-mock-badge-chip ' + (tx.type === 'buy' ? 'pf-badge-pos' : 'pf-badge-neg') + '">' + tx.type.toUpperCase() + '</span></td>' +
                '<td class="num pf-num">' + tx.quantity + '</td>' +
                '<td class="num pf-num">$' + fmt(tx.price) + '</td>' +
                '<td class="num pf-num ' + cls + '">$' + fmt(tx.quantity * tx.price) + '</td>' +
                '<td style="font-size:0.75rem; color:var(--muted); max-width:200px; overflow:hidden; text-overflow:ellipsis;" title="' + escHtml(tx.notes) + '">' + escHtml(tx.notes) + '</td>' +
            '</tr>';
        }).join('');
        return thTable(ths) + '<tbody>' + rows + '</tbody></table>';
    }

    /* ─── Open Orders tab (5th Holdings tab) ────────────────────────── */
    function holdingsOrdersTable() {
        if (!portfolio.isServer || !detailCache) {
            return '<div class="pf-empty" style="padding:1.5rem;">' + il('Live order data requires a connected Alpaca portfolio.', 'بيانات الأوامر المباشرة تتطلب محفظة Alpaca متصلة.') + '</div>';
        }
        var orders = detailCache.orders || [];
        if (!orders.length) {
            return '<div class="pf-empty" style="padding:1.5rem;">' + il('No active open orders on Alpaca right now.', 'لا توجد أوامر مفتوحة نشطة على Alpaca حالياً.') + '</div>';
        }
        var ths = [il('Symbol', 'الرمز'), il('Side', 'الجهة'), il('Type', 'النوع'), il('Qty', 'الكمية'), il('Limit Price', 'سعر الحد'), il('Status', 'الحالة'), ''];
        var rows = orders.map(function(o) {
            var sideCls = o.side === 'buy' ? 'pf-badge-pos' : 'pf-badge-neg';
            var price = parseFloat(o.limit_price || o.price || 0);
            return '<tr>' +
                '<td>' + symChipBySymbol(o.symbol) + '</td>' +
                '<td><span class="pf-mock-badge-chip ' + sideCls + '" style="font-size:.66rem;padding:.15rem .5rem;">' + (o.side||'').toUpperCase() + '</span></td>' +
                '<td class="pf-num" style="font-size:.74rem;">' + (o.type||'').toUpperCase() + ' · ' + (o.time_in_force||'').toUpperCase() + '</td>' +
                '<td class="num pf-num">' + (o.qty||0) + '</td>' +
                '<td class="num pf-num">' + (price > 0 ? '$' + fmt(price) : '—') + '</td>' +
                '<td><span class="pf-badge-neu">' + (o.status||'pending') + '</span></td>' +
                '<td><button class="pf-btn pf-btn--sm pf-btn--danger-ghost cancel-order-btn" data-order-id="' + escHtml(o.id||'') + '" style="font-size:.65rem;padding:.2rem .5rem;">' + il('Cancel', 'إلغاء') + '</button></td>' +
            '</tr>';
        }).join('');
        return thTable(ths) + '<tbody>' + rows + '</tbody></table>';
    }

    /* ─── Holdings Chart Views (Premium visualizations per tab) ─────── */

    function holdingsOverviewChart() {
        return '<div class="pf-chart-card">' +
            '<div class="pf-chart-card__title">' + t('holdings') + ' — Market Value Distribution</div>' +
            '<div style="display:flex;gap:1.5rem;align-items:stretch;">' +
                '<div style="flex:1; min-height:300px;"><canvas id="tabOverviewChart"></canvas></div>' +
                '<div class="pf-mini-cards" style="width:200px;display:flex;flex-direction:column;gap:0.35rem;overflow-y:auto;max-height:300px;">' +
                    metrics.holdings.map(function(h,i){
                        var plCls = h.totalGain >= 0 ? 'pf-pos' : 'pf-neg';
                        return '<div style="padding:0.5rem 0.65rem;border:1px solid var(--line);border-radius:var(--pf-radius-sm);cursor:pointer;" class="pf-mini-card" data-sym="'+h.symbol+'">' +
                            '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                                '<span style="font-weight:700;font-size:0.8rem;">'+h.symbol+'</span>' +
                                '<span class="pf-num" style="font-size:0.72rem;">'+h.weight.toFixed(1)+'%</span>' +
                            '</div>' +
                            '<div style="display:flex;justify-content:space-between;margin-top:0.2rem;">' +
                                '<span class="pf-num" style="font-size:0.7rem;color:var(--muted);">$'+fmt(h.marketValue)+'</span>' +
                                '<span class="pf-num '+plCls+'" style="font-size:0.68rem;">'+(h.totalGain>=0?'+':'')+fmt(h.totalGain)+'</span>' +
                            '</div>' +
                        '</div>';
                    }).join('') +
                '</div>' +
            '</div></div>';
    }

    function initOverviewChart() {
        var canvas = document.getElementById('tabOverviewChart');
        if (!canvas || !metrics.holdings.length) return;
        if (tabChartInst) tabChartInst.destroy();
        var isDark = document.documentElement.dataset.theme !== 'light';
        var colors = metrics.holdings.map(function(h){ return h.color; });
        var ctx = canvas.getContext('2d');
        tabChartInst = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: metrics.holdings.map(function(h){ return h.symbol; }),
                datasets: [{
                    label: 'Market Value',
                    data: metrics.holdings.map(function(h){ return h.marketValue; }),
                    backgroundColor: colors,
                    borderRadius: 6,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: function(c){ return '$'+fmt(c.raw,2); } } }
                },
                scales: {
                    x: { grid: { color: isDark?'rgba(255,255,255,0.05)':'rgba(0,0,0,0.05)' }, ticks: { font:{size:9,family:'IBM Plex Mono'}, callback: function(v){ return '$'+fmt(v,0); } } },
                    y: { grid: { display: false }, ticks: { font:{size:10,family:'IBM Plex Mono',weight:'700'} } }
                }
            }
        });
        // Wire mini-card clicks
        setTimeout(function(){
            document.querySelectorAll('.pf-mini-card').forEach(function(card){
                card.addEventListener('click', function(){
                    var sym = card.dataset.sym;
                    if (sym) window.location.href = '/stock-detail.html?symbol=' + encodeURIComponent(sym);
                });
            });
        }, 100);
    }

    function holdingsPerformanceChart() {
        return '<div class="pf-chart-card">' +
            '<div class="pf-chart-card__title">' + t('performance') + ' — Unrealized P&L by Position</div>' +
            '<div style="min-height:320px;"><canvas id="tabPerfChart"></canvas></div>' +
            '<div class="pf-chart-stats" style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:0.75rem;">' +
                metrics.holdings.map(function(h){
                    var cl = h.totalGain >= 0 ? 'pf-pos' : 'pf-neg';
                    return '<div style="padding:0.4rem 0.8rem;border:1px solid var(--line);border-radius:var(--pf-radius-sm);flex:1;min-width:100px;">' +
                        '<span style="font-weight:700;font-size:0.75rem;">'+h.symbol+'</span>' +
                        '<span class="pf-num '+cl+'" style="float:right;font-size:0.75rem;">'+(h.totalGain>=0?'+':'')+'$'+money(h.totalGain)+'</span>' +
                    '</div>';
                }).join('') +
            '</div></div>';
    }

    function initPerformanceChart() {
        var canvas = document.getElementById('tabPerfChart');
        if (!canvas || !metrics.holdings.length) return;
        if (tabChartInst) tabChartInst.destroy();
        var isDark = document.documentElement.dataset.theme !== 'light';
        var vals = metrics.holdings.map(function(h){ return h.totalGain; });
        var colors = vals.map(function(v){ return v >= 0 ? '#22c55e' : '#ef4444'; });
        var ctx = canvas.getContext('2d');
        tabChartInst = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: metrics.holdings.map(function(h){ return h.symbol; }),
                datasets: [{
                    data: vals,
                    backgroundColor: colors,
                    borderRadius: 4,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: function(c){ return (c.raw>=0?'+':'')+'$'+fmt(c.raw,2); } } } },
                scales: {
                    x: { grid: { color: isDark?'rgba(255,255,255,0.05)':'rgba(0,0,0,0.05)' }, ticks: { font:{size:9,family:'IBM Plex Mono'} } },
                    y: { grid: { color: isDark?'rgba(255,255,255,0.05)':'rgba(0,0,0,0.05)' }, ticks: { font:{size:9,family:'IBM Plex Mono'}, callback: function(v){ return '$'+fmt(v,0); } } }
                }
            }
        });
    }

    function holdingsAllocationChart() {
        var total = metrics.totalMarketValue || 1;
        return '<div class="pf-chart-card">' +
            '<div class="pf-chart-card__title">' + t('allocation') + ' — Portfolio Weight Distribution</div>' +
            '<div style="display:flex;gap:1.5rem;align-items:center;">' +
                '<div style="flex:1; min-height:320px;"><canvas id="tabAllocChart"></canvas></div>' +
                '<div class="pf-alloc-legend" style="width:180px;display:flex;flex-direction:column;gap:0.3rem;max-height:320px;overflow-y:auto;">' +
                    metrics.holdings.map(function(h){
                        return '<div style="display:flex;align-items:center;gap:0.4rem;padding:0.25rem 0;font-size:0.7rem;">' +
                            '<span style="width:10px;height:10px;border-radius:2px;background:'+h.color+';flex-shrink:0;"></span>' +
                            '<span style="font-weight:600;flex:1;">'+h.symbol+'</span>' +
                            '<span class="pf-num" style="color:var(--muted);">'+h.weight.toFixed(1)+'%</span>' +
                        '</div>';
                    }).join('') +
                '</div>' +
            '</div></div>';
    }

    function initAllocationChart() {
        var canvas = document.getElementById('tabAllocChart');
        if (!canvas || !metrics.holdings.length) return;
        if (tabChartInst) tabChartInst.destroy();
        var ctx = canvas.getContext('2d');
        tabChartInst = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: metrics.holdings.map(function(h){ return h.symbol; }),
                datasets: [{
                    data: metrics.holdings.map(function(h){ return h.marketValue; }),
                    backgroundColor: metrics.holdings.map(function(h){ return h.color; }),
                    borderColor: 'var(--surface)',
                    borderWidth: 2,
                    hoverBorderWidth: 3
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: function(c){
                        var tot = c.dataset.data.reduce(function(s,v){ return s + v; }, 0) || 1;
                        var wPct = (c.raw / tot) * 100;
                        return c.label+': '+wPct.toFixed(1)+'% ($'+fmt(c.raw,2)+')';
                    } } }
                }
            }
        });
    }

    function holdingsDividendsChart() {
        if (!portfolio.transactions.length) return '<div class="pf-empty">No transactions recorded.</div>';
        var txs = portfolio.transactions.slice().reverse().slice(0, 15);
        return '<div class="pf-chart-card">' +
            '<div class="pf-chart-card__title">' + t('dividendTab') + ' — Trade Activity Timeline</div>' +
            '<div style="min-height:300px;"><canvas id="tabDivChart"></canvas></div>' +
            '<div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.35rem;">' +
                txs.map(function(tx){
                    var cl = tx.type === 'buy' ? 'pf-neg' : 'pf-pos';
                    return '<span style="padding:0.2rem 0.55rem;border:1px solid var(--line);border-radius:999px;font-size:0.65rem;font-weight:600;">' +
                        tx.symbol + ' <span class="'+cl+'">'+(tx.type==='buy'?'B':'S')+'</span> $'+fmt(tx.quantity*tx.price) +
                    '</span>';
                }).join('') +
            '</div></div>';
    }

    function initDividendChart() {
        var canvas = document.getElementById('tabDivChart');
        if (!canvas || !portfolio.transactions.length) return;
        if (tabChartInst) tabChartInst.destroy();
        var isDark = document.documentElement.dataset.theme !== 'light';
        var txs = portfolio.transactions.slice().reverse().slice(0, 15);
        var ctx = canvas.getContext('2d');
        var labels = txs.map(function(tx){ return tx.symbol+' '+tx.type.toUpperCase(); });
        var sizes = txs.map(function(tx){ return Math.abs(tx.quantity * tx.price); });
        var colors = txs.map(function(tx){ return tx.type === 'buy' ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'; });
        tabChartInst = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: sizes,
                    backgroundColor: colors,
                    borderRadius: 3,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: function(c){ return '$'+fmt(c.raw,2); } } } },
                scales: {
                    x: { grid: { display: false }, ticks: { font:{size:7,family:'IBM Plex Mono'}, maxRotation: 45 } },
                    y: { grid: { color: isDark?'rgba(255,255,255,0.05)':'rgba(0,0,0,0.05)' }, ticks: { font:{size:9,family:'IBM Plex Mono'}, callback: function(v){ return '$'+fmt(v,0); } } }
                }
            }
        });
    }

    function thTable(ths) {
        return '<table class="pf-table"><thead><tr>' +
            ths.map(function(h, i){ return '<th' + (i > 0 ? ' class="num"' : '') + '>' + h + '</th>'; }).join('') +
        '</tr></thead>';
    }

    /* ─── Universal Table Sort Engine ────────────────────────────────────
       Wires click-to-sort on any <table> inside a wrapper element.
       Click header = ascending; click again = descending. Arrow indicator
       shows active column + direction. Works on any rendered table in the
       page without re-running data pipelines (pure DOM sort).          */
    function wireTableSort(table) {
        if (!table || table.dataset.sortWired) return;
        table.dataset.sortWired = '1';

        var thead = table.querySelector('thead');
        var tbody = table.querySelector('tbody');
        if (!thead || !tbody) return;

        var headers = thead.querySelectorAll('th');
        var sortCol = -1, sortDir = 1;

        // Inject indicator spans into every <th>
        headers.forEach(function(th) {
            var ind = document.createElement('span');
            ind.className = 'pf-th-sort';
            ind.innerHTML = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 5v14M5 12l7-7 7 7"/></svg>' +
                            '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 19V5M5 12l7 7 7-7"/></svg>';
            th.appendChild(ind);
        });

        headers.forEach(function(th, colIdx) {
            th.style.cursor = 'pointer';
            th.addEventListener('click', function() {
                if (sortCol === colIdx) { sortDir = -sortDir; }
                else { sortCol = colIdx; sortDir = 1; }

                // Update visual state on all headers
                headers.forEach(function(hh, ii) {
                    hh.classList.toggle('pf-th-sorted', ii === sortCol);
                    hh.classList.toggle('pf-th-asc',    ii === sortCol && sortDir > 0);
                    hh.classList.toggle('pf-th-desc',   ii === sortCol && sortDir < 0);
                });

                // Sort rows by the clicked column
                var rows = Array.from(tbody.querySelectorAll('tr'));
                rows.sort(function(a, b) {
                    var ca = (a.cells[colIdx] || {}).textContent || '';
                    var cb = (b.cells[colIdx] || {}).textContent || '';
                    // Strip currency/percent symbols and parse as number if possible
                    var na = parseFloat(ca.replace(/[^0-9.\-]/g, ''));
                    var nb = parseFloat(cb.replace(/[^0-9.\-]/g, ''));
                    if (!isNaN(na) && !isNaN(nb)) return (na - nb) * sortDir;
                    return ca.localeCompare(cb, undefined, { sensitivity: 'base' }) * sortDir;
                });
                rows.forEach(function(r) { tbody.appendChild(r); });
            });
        });
    }

    /* Wire every table inside a root element (skips already-wired ones) */
    function wireAllTables(root) {
        if (!root) return;
        root.querySelectorAll('table').forEach(wireTableSort);
    }

    function symChip(h) {
        var sideBadge = '';
        if (h.side) {
            var isLong = h.side.toLowerCase() === 'long';
            var sideLabel = isLong ? (lang === 'ar' ? 'شراء' : 'LONG') : (lang === 'ar' ? 'بيع قصير' : 'SHORT');
            var sideColor = isLong ? '#22c55e' : '#ef4444';
            var sideBg = isLong ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)';
            sideBadge = `<span style="font-size:0.6rem; font-weight:800; color:${sideColor}; background:${sideBg}; padding:0.15rem 0.4rem; border-radius:3px; margin-inline-start:0.4rem; text-transform:uppercase; border:1px solid ${sideColor}22; display:inline-block; line-height:1;">${sideLabel}</span>`;
        }
        
        var exchBadge = '';
        if (h.exchange) {
            exchBadge = `<span style="font-size:0.58rem; font-weight:700; color:var(--muted); border:1px solid var(--line); padding:0.1rem 0.3rem; border-radius:3px; margin-inline-start:0.35rem; text-transform:uppercase; font-family:var(--pf-mono); display:inline-block; line-height:1;">${h.exchange}</span>`;
        }

        return '<div class="pf-sym">' +
            '<div class="pf-sym-chip" style="background:' + h.color + '">' + h.symbol.slice(0,3) + '</div>' +
            '<div class="pf-sym-info">' +
                '<div class="sym-code" style="display:inline-flex; align-items:center; flex-wrap:wrap; gap:0.25rem;">' + h.symbol + sideBadge + exchBadge + '</div>' +
                '<div class="sym-name">' + (lang==='ar' ? escHtml(h.companyNameAr||h.companyName) : escHtml(h.companyName)) + '</div>' +
            '</div>' +
        '</div>';
    }

    function symChipBySymbol(sym) {
        var meta = PFStore.symMeta(sym);
        return '<div class="pf-sym"><div class="pf-sym-chip" style="background:' + meta.color + ';width:1.7rem;height:1.7rem;font-size:.58rem;">' + sym.slice(0,3) + '</div>' +
            '<span style="font-family:var(--pf-mono);font-size:.78rem;font-weight:700;">' + sym + '</span></div>';
    }

    /* ─── Bottom Panels (Risk circle SVGs, Contributors, Executions) ───── */
    function renderBottomGrid() {
        var bg = document.getElementById('bottomGrid');
        if (!bg) return;

        bg.innerHTML =
            '<div class="pf-card pf-contrib-panel" id="contribPanel">' + renderContrib() + '</div>' +
            '<div class="pf-card pf-risk-panel" style="padding:1.15rem;">' + renderRiskPanel() + '</div>' +
            '<div class="pf-card pf-tx-panel">' + renderTxPanel() + '</div>' +
            '<div class="pf-card pf-div-panel">' + renderLiveOrdersPanel() + '</div>';

        bg.querySelectorAll('.pf-contrib-tab').forEach(function(tab){
            tab.addEventListener('click', function(){
                contribTab = tab.dataset.tab;
                document.getElementById('contribPanel').innerHTML = renderContrib();
                wireContribTabs();
            });
        });

        wireCancelButtons();
    }

    function wireContribTabs() {
        var panel = document.getElementById('contribPanel');
        if (!panel) return;
        panel.querySelectorAll('.pf-contrib-tab').forEach(function(t2){
            t2.addEventListener('click', function(){
                contribTab = t2.dataset.tab;
                panel.innerHTML = renderContrib();
                wireContribTabs();
            });
        });
    }

    var _contribChart = null;

    function renderContrib() {
        var holds = metrics.holdings.slice();
        var gainers = holds.filter(function(h){ return h.totalGain > 0; })
                           .sort(function(a,b){ return b.totalGain - a.totalGain; });
        var losers  = holds.filter(function(h){ return h.totalGain < 0; })
                           .sort(function(a,b){ return a.totalGain - b.totalGain; });
        var totalGain = gainers.reduce(function(s,h){ return s + h.totalGain; }, 0);
        var totalLoss = Math.abs(losers.reduce(function(s,h){ return s + h.totalGain; }, 0));
        var winRate = holds.length ? Math.round(gainers.length / holds.length * 100) : 0;

        function row(h) {
            var cls  = h.totalGain >= 0 ? 'pf-pos' : 'pf-neg';
            var sign = h.totalGain >= 0 ? '+' : '';
            return '<div class="pf-contrib-row">' +
                '<div class="pf-contrib-chip" style="background:' + h.color + '">' + h.symbol.slice(0,3) + '</div>' +
                '<span class="pf-contrib-name">' + h.symbol + '</span>' +
                '<div class="pf-contrib-val">' +
                    '<span class="' + cls + ' pf-num">' + sign + '$' + fmt(h.totalGain, 0) + '</span>' +
                    '<span class="pf-num ' + cls + '">' + pct(h.totalReturn) + '</span>' +
                '</div></div>';
        }

        var html =
            '<div class="pf-panel__title">' + t('topContrib') + '</div>' +

            // Donut chart
            '<div class="pf-contrib-donut-wrap">' +
                '<div style="position:relative;width:128px;height:128px;flex-shrink:0;">' +
                    '<canvas id="contribDonutChart" width="128" height="128"></canvas>' +
                    '<div class="pf-contrib-donut-center">' +
                        '<span class="pf-num" style="font-size:1.35rem;font-weight:700;color:var(--ink);">' + winRate + '%</span>' +
                        '<span style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;">' + il('Win Rate', 'معدل الربح') + '</span>' +
                    '</div>' +
                '</div>' +
                '<div class="pf-contrib-donut-legend">' +
                    '<div class="pf-contrib-donut-stat">' +
                        '<span class="pf-contrib-donut-dot" style="background:#22c55e;"></span>' +
                        '<span style="font-size:.68rem;color:var(--muted);">' + il('Gainers', 'رابحون') + '</span>' +
                        '<span class="pf-num pf-pos" style="font-size:.8rem;font-weight:700;">+$' + fmt(totalGain, 0) + '</span>' +
                        '<span style="font-size:.65rem;color:var(--muted);">' + gainers.length + ' ' + il('pos.', 'مركز') + '</span>' +
                    '</div>' +
                    '<div class="pf-contrib-donut-stat">' +
                        '<span class="pf-contrib-donut-dot" style="background:#ef4444;"></span>' +
                        '<span style="font-size:.68rem;color:var(--muted);">' + il('Losers', 'خاسرون') + '</span>' +
                        '<span class="pf-num pf-neg" style="font-size:.8rem;font-weight:700;">-$' + fmt(totalLoss, 0) + '</span>' +
                        '<span style="font-size:.65rem;color:var(--muted);">' + losers.length + ' ' + il('pos.', 'مركز') + '</span>' +
                    '</div>' +
                '</div>' +
            '</div>' +

            // Top gainers
            '<div style="margin-top:.65rem;">' +
                '<div class="pf-contrib-group-label pf-pos">' + il('Top Gainers', 'أفضل الرابحين') + '</div>' +
                gainers.slice(0,3).map(row).join('') +
            '</div>' +

            // Top losers
            (losers.length ? '<div style="margin-top:.55rem;border-top:1px solid var(--line);padding-top:.55rem;">' +
                '<div class="pf-contrib-group-label pf-neg">' + il('Top Losers', 'أكبر الخاسرين') + '</div>' +
                losers.slice(0,3).map(row).join('') +
            '</div>' : '');

        // Init chart after DOM paint
        setTimeout(initContribChart, 60);
        return html;
    }

    function initContribChart() {
        var canvas = document.getElementById('contribDonutChart');
        if (!canvas) return;
        if (_contribChart) { try { _contribChart.destroy(); } catch(e){} _contribChart = null; }

        var holds = metrics.holdings.slice();
        var gainers = holds.filter(function(h){ return h.totalGain > 0; });
        var losers  = holds.filter(function(h){ return h.totalGain < 0; });
        var totalGain = gainers.reduce(function(s,h){ return s + h.totalGain; }, 0);
        var totalLoss = Math.abs(losers.reduce(function(s,h){ return s + h.totalGain; }, 0));

        if (totalGain + totalLoss <= 0) return;

        var isDark = document.documentElement.dataset.theme !== 'light';
        var ctx = canvas.getContext('2d');
        _contribChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: [il('Gainers','رابحون'), il('Losers','خاسرون')],
                datasets: [{
                    data: [totalGain, totalLoss],
                    backgroundColor: ['#22c55e', '#ef4444'],
                    borderWidth: 3,
                    borderColor: isDark ? '#1A0F08' : '#FFFFFF',
                    hoverOffset: 5
                }]
            },
            options: {
                responsive: false,
                cutout: '62%',
                animation: { duration: 700 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: isDark ? '#1a0f08' : '#fff',
                        borderColor: 'rgba(0,0,0,.08)', borderWidth: 1,
                        titleColor: isDark ? '#fff1e8' : '#1a0f08',
                        bodyColor: isDark ? '#a39a92' : '#7a6b5e',
                        bodyFont: { family: 'IBM Plex Mono', size: 11 },
                        callbacks: {
                            label: function(c) {
                                return ' ' + c.label + ': ' + (c.dataIndex === 0 ? '+' : '-') + '$' + fmt(c.raw, 0);
                            }
                        }
                    }
                }
            }
        });
    }

    function makeGauge(label, valStr, pct, smallText) {
        var offset = 226 - (226 * Math.min(Math.max(pct, 0), 100)) / 100;
        return '<div class="pf-risk-gauge-container">' +
            '<div class="pf-risk-gauge-svg">' +
                '<svg viewBox="0 0 80 80">' +
                    '<circle class="pf-risk-gauge-circle-bg" cx="40" cy="40" r="36" />' +
                    '<circle class="pf-risk-gauge-circle-val" cx="40" cy="40" r="36" style="stroke-dashoffset:' + offset + 'px;" />' +
                '</svg>' +
                '<span class="pf-risk-gauge-text pf-num">' + valStr + '</span>' +
            '</div>' +
            '<span class="pf-risk-gauge-label">' + label + '</span>' +
            (smallText ? '<span style="font-size:0.65rem;color:var(--muted);">' + smallText + '</span>' : '') +
        '</div>';
    }

    function renderRiskPanel() {
        var limits = detailCache ? detailCache.strategy_params || {} : {};
        var tradesToday = detailCache ? (detailCache.trade_log || []).length : 0;
        var signalCount = detailCache ? ((detailCache.signals || {}).signals || []).length : 0;
        return '<div class="pf-panel__title">' + t('riskMetrics') + '</div>' +
            '<div class="pf-risk-status" style="display:flex;flex-direction:column;gap:0.75rem;padding-top:0.45rem;">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0.65rem;background:var(--page);border:1px solid var(--line);border-radius:var(--pf-radius-sm);">' +
                    '<span style="font-size:0.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;">' + (lang === 'ar' ? 'حالة النظام' : 'System Status') + '</span>' +
                    '<span class="pf-pos" style="font-size:0.75rem;font-weight:800;">' + (portfolio.halted ? (lang === 'ar' ? 'متوقف' : 'HALTED') : (lang === 'ar' ? 'نشط' : 'ACTIVE')) + '</span>' +
                '</div>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0.65rem;background:var(--page);border:1px solid var(--line);border-radius:var(--pf-radius-sm);">' +
                    '<span style="font-size:0.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;">' + (lang === 'ar' ? 'صفقات اليوم' : 'Trades Today') + '</span>' +
                    '<span class="pf-num" style="font-size:0.9rem;font-weight:800;color:var(--ink);">' + tradesToday + '</span>' +
                '</div>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0.65rem;background:var(--page);border:1px solid var(--line);border-radius:var(--pf-radius-sm);">' +
                    '<span style="font-size:0.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;">' + (lang === 'ar' ? 'إشارات نشطة' : 'Active Signals') + '</span>' +
                    '<span class="pf-num" style="font-size:0.9rem;font-weight:800;color:var(--teal);">' + signalCount + '</span>' +
                '</div>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0.65rem;background:var(--page);border:1px solid var(--line);border-radius:var(--pf-radius-sm);">' +
                    '<span style="font-size:0.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;">' + (lang === 'ar' ? 'حد الخسارة اليومي' : 'Daily Loss Limit') + '</span>' +
                    '<span style="font-size:0.9rem;font-weight:800;color:var(--ink);font-family:var(--pf-mono);">4.0%</span>' +
                '</div>' +
            '</div>';
    }

    function renderTxPanel() {
        var txs = portfolio.transactions.slice().reverse().slice(0, 5);
        var rows = txs.map(function(tx){
            var iconCls = tx.type === 'buy' ? 'buy' : 'sell';
            var iconChar = tx.type === 'buy' ? '↑' : '↓';
            var amount = tx.quantity * tx.price;
            var amtCls = tx.type === 'sell' ? 'pf-pos' : 'pf-neg';
            var sign   = tx.type === 'sell' ? '+' : '-';
            
            return '<div class="pf-tx-row">' +
                '<div class="pf-tx-icon pf-tx-icon--' + iconCls + '">' + iconChar + '</div>' +
                '<div class="pf-tx-info"><strong>' + tx.symbol + '</strong>' +
                    '<span>' + tx.type.toUpperCase() + ' · ' + tx.date + '</span></div>' +
                '<div class="pf-tx-amount pf-num ' + amtCls + '">' + sign + '$' + fmt(amount, 0) + '</div>' +
            '</div>';
        }).join('');

        return '<div class="pf-panel__title">' + t('recentTx') + '</div>' +
            '<div class="pf-tx-list">' + (rows || '<div class="pf-empty-inline">No transactions log yet.</div>') + '</div>';
    }

    function renderLiveOrdersPanel() {
        if (!portfolio.isServer || !detailCache) {
            return '<div class="pf-panel__title">Live Action Hub</div><div class="pf-empty-inline">Add transactions manually above for sandbox portfolios.</div>';
        }

        var orders = detailCache.orders || [];
        var rows = orders.map(o => `
            <div class="pf-order-row" style="display:flex; justify-content:space-between; align-items:center; padding:0.5rem 0; border-bottom:1px solid var(--line);">
                <div style="display:flex; flex-direction:column;">
                    <strong class="pf-num">${o.symbol} <span class="pf-mock-badge-chip ${o.side === 'buy' ? 'pf-badge-pos' : 'pf-badge-neg'}" style="font-size:0.6rem; padding:0.1rem 0.45rem;">${o.side.toUpperCase()}</span></strong>
                    <span style="font-size:0.68rem; color:var(--muted); font-family:var(--pf-mono);">${o.type.toUpperCase()} · ${o.time_in_force.toUpperCase()}</span>
                </div>
                <div style="text-align:end; display:flex; align-items:center; gap:0.5rem;">
                    <div style="font-family:var(--pf-mono); font-size:0.75rem;">
                        <div>${o.qty} shares</div>
                        <div style="color:var(--teal); font-weight:700;">$${fmt(parseFloat(o.limit_price || o.price || 0))}</div>
                    </div>
                    <button class="pf-btn pf-btn--sm pf-btn--outline pf-btn--danger-ghost cancel-order-btn" data-order-id="${o.id}" style="padding:0.22rem 0.55rem; font-size:0.65rem;">Cancel</button>
                </div>
            </div>
        `).join('');

        return '<div class="pf-panel__title">Live Open Orders (Alpaca)</div>' +
            '<div class="pf-tx-list">' + (rows || '<div class="pf-empty-inline">No active open orders on Alpaca.</div>') + '</div>';
    }

    function wireCancelButtons() {
        document.querySelectorAll('.cancel-order-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var orderId = btn.getAttribute('data-order-id');
                if (confirm('Cancel this active Alpaca order?')) {
                    btn.disabled = true;
                    btn.textContent = '...';
                    fetch(`/api/portfolio/${pfId}/order/${orderId}`, { method: 'DELETE' })
                        .then(r => r.json())
                        .then(data => {
                            alert('Order successfully cancelled.');
                            location.reload();
                        })
                        .catch(err => {
                            alert('Cancel failed: ' + err.message);
                            btn.disabled = false;
                            btn.textContent = 'Cancel';
                        });
                }
            });
        });
    }

    /* ─── Order Placing Modal ─────────────────────────────────────────── */
    function openOrderModal(prefillSymbol) {
        var sym = (typeof prefillSymbol === 'string') ? prefillSymbol : '';
        if (pfId === 'all') {
            alert('All Portfolios is a read-only aggregated view. Select an individual portfolio to place trades.');
            return;
        }
        if (!portfolio.isServer) {
            alert('Custom sandbox transactions can be simulated by importing CSV spreadsheets or uploading XLSX sheets in the landing selection page.');
            return;
        }

        var overlay = document.getElementById('addTxModal');
        var body = document.getElementById('addTxBody');
        
        body.innerHTML = `
            <form class="pf-form" id="liveOrderForm" style="display:flex; flex-direction:column; gap:0.95rem; font-size:0.8rem;">
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem;">
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-weight:700; color:var(--muted); text-transform:uppercase; font-size:0.65rem; letter-spacing:0.04em;">Symbol / Ticker</label>
                        <input type="text" id="orderSymbol" placeholder="e.g. NVDA" required style="text-transform: uppercase; padding:0.45rem 0.65rem; border:1px solid var(--line); border-radius:var(--pf-radius-sm); background:var(--page); color:var(--ink);">
                    </div>
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-weight:700; color:var(--muted); text-transform:uppercase; font-size:0.65rem; letter-spacing:0.04em;">Side</label>
                        <select id="orderSide" style="padding:0.45rem 0.65rem; border:1px solid var(--line); border-radius:var(--pf-radius-sm); background:var(--page); color:var(--ink);">
                            <option value="buy" selected>BUY / GO LONG</option>
                            <option value="sell">SELL / GO SHORT</option>
                        </select>
                    </div>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem;">
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-weight:700; color:var(--muted); text-transform:uppercase; font-size:0.65rem; letter-spacing:0.04em;">Shares / Quantity</label>
                        <input type="number" id="orderQty" min="1" step="1" value="10" required style="padding:0.45rem 0.65rem; border:1px solid var(--line); border-radius:var(--pf-radius-sm); background:var(--page); color:var(--ink);">
                    </div>
                    <div style="display:flex; flex-direction:column; gap:0.25rem;">
                        <label style="font-weight:700; color:var(--muted); text-transform:uppercase; font-size:0.65rem; letter-spacing:0.04em;">Order Type</label>
                        <select id="orderType" style="padding:0.45rem 0.65rem; border:1px solid var(--line); border-radius:var(--pf-radius-sm); background:var(--page); color:var(--ink);">
                            <option value="limit" selected>LIMIT ORDER</option>
                            <option value="market">MARKET ORDER</option>
                        </select>
                    </div>
                </div>
                <div style="display:flex; flex-direction:column; gap:0.25rem;" id="limitPriceField">
                    <label style="font-weight:700; color:var(--muted); text-transform:uppercase; font-size:0.65rem; letter-spacing:0.04em;">Limit Price ($)</label>
                    <input type="number" id="orderPrice" step="0.01" min="0.01" placeholder="e.g. 195.50" required style="padding:0.45rem 0.65rem; border:1px solid var(--line); border-radius:var(--pf-radius-sm); background:var(--page); color:var(--ink);">
                </div>
                <div style="display:flex; gap:.75rem; justify-content:flex-end; padding-top:.5rem;">
                    <button type="button" class="pf-btn pf-btn--sm" id="closeLiveOrder" style="border-radius:var(--pf-radius-sm);">Cancel</button>
                    <button type="submit" class="pf-btn pf-btn--sm pf-btn--primary" id="submitLiveOrder" style="border-radius:var(--pf-radius-sm);">Place Live Order</button>
                </div>
            </form>
        `;

        overlay.classList.add('open');

        if (sym) {
            var symInput = body.querySelector('#orderSymbol');
            if (symInput) symInput.value = sym;
        }

        const typeSelect = body.querySelector('#orderType');
        const priceField = body.querySelector('#limitPriceField');
        const priceInput = body.querySelector('#orderPrice');
        typeSelect.addEventListener('change', function() {
            if (this.value === 'market') {
                priceField.style.display = 'none';
                priceInput.required = false;
            } else {
                priceField.style.display = 'flex';
                priceInput.required = true;
            }
        });

        body.querySelector('#closeLiveOrder').addEventListener('click', closeOrderModal);

        body.querySelector('#liveOrderForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            var submitBtn = body.querySelector('#submitLiveOrder');
            submitBtn.disabled = true;
            submitBtn.textContent = 'Executing...';

            var orderBody = {
                symbol: body.querySelector('#orderSymbol').value.trim().toUpperCase(),
                qty: parseInt(body.querySelector('#orderQty').value, 10),
                side: body.querySelector('#orderSide').value,
                type: body.querySelector('#orderType').value,
                price: parseFloat(body.querySelector('#orderPrice').value) || null
            };

            fetch(`/api/portfolio/${pfId}/order`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(orderBody)
            })
            .then(res => {
                if (!res.ok) throw new Error('Alpaca execution rejected. Check funds or market hours.');
                return res.json();
            })
            .then(data => {
                alert(`Order successfully executed! Status: ${data.status}`);
                closeOrderModal();
                location.reload();
            })
            .catch(err => {
                alert('Order failed: ' + err.message);
                submitBtn.disabled = false;
                submitBtn.textContent = 'Place Live Order';
            });
        });
    }

    function closeOrderModal() {
        document.getElementById('addTxModal').classList.remove('open');
    }

    /* ─── Language Switcher ────────────────────────────────────────────── */
    function applyLang(l) {
        lang = l; localStorage.setItem('starta-lang', l);
        document.documentElement.lang = l;
        document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
        document.getElementById('langToggle').textContent = l === 'ar' ? 'EN' : 'AR';
        
        applyNavLang(l);
        renderHeader();
        renderBody();
    }

    document.getElementById('langToggle').addEventListener('click', function () {
        applyLang(lang === 'ar' ? 'en' : 'ar');
    });

    if (lang === 'ar') {
        document.documentElement.lang = 'ar';
        document.documentElement.dir = 'rtl';
        document.getElementById('langToggle').textContent = 'EN';
    }

    applyNavLang(lang);
    
    document.getElementById('closeAddTx').addEventListener('click', closeOrderModal);

    // Initial triggers
    init();

}());
