(function () {
    'use strict';

    /* ──────────────────────────────────────────────────────────────────────
       TRANSLATIONS
    ────────────────────────────────────────────────────────────────────── */
    var T = {
        en: {
            ct_title: 'Crypto Terminal',
            ct_subtitle: 'Real-time cryptocurrency trading — orderbook, trade tape, and order entry',
            ct_last_price: 'Last Price', ct_24h_change: 'Today Change', ct_24h_high: 'Today High',
            ct_24h_low: 'Today Low', ct_24h_vol: 'Today Volume', ct_spread: 'Spread',
            ct_orderbook: 'Orderbook', ct_trades: 'Recent Trades', ct_new_order: 'New Crypto Order',
            ct_positions: 'Crypto Positions', ct_no_positions: 'Select a portfolio to view positions',
            ct_no_crypto_pos: 'No crypto positions in this portfolio',
            ct_buy: 'BUY', ct_sell: 'SELL', ct_order_type: 'Order Type', ct_tif: 'Time in Force',
            ct_qty: 'Quantity', ct_notional: 'Notional ($)', ct_limit_price: 'Limit Price',
            ct_stop_price: 'Stop Price', ct_place_order: 'Place Buy Order',
            ct_size: 'Size', ct_price: 'Price', ct_total: 'Total', ct_time: 'Time',
            ct_symbol: 'Symbol', ct_side: 'Side', ct_avg_entry: 'Avg Entry', ct_mkt_val: 'Mkt Value',
            ct_unrealized: 'Unrealized P&L', ct_pct: '%',
            ct_spread_label: 'Spread',
            toast_submitted: 'Crypto order submitted', toast_error: 'Error',
            confirm_order: 'Submit this crypto order?',
            nav_home: 'Home', nav_portfolios: 'Portfolios', nav_pf_list: 'Portfolio List',
            nav_pf1: 'Improving Brain', nav_pf2: 'Capitol Shadow', nav_pf3: 'Cautious Sniper',
            nav_market_pulse: 'Market Pulse', nav_trading: 'Trading', nav_orders: 'Orders', nav_readiness: 'Readiness',
            nav_crypto: 'Crypto Terminal', nav_options: 'Options Lab', nav_screener: 'Screener',
            nav_history: 'Account History', nav_alerts: 'Alerts', nav_research: 'Research & AI', nav_settings: 'Settings'
        },
        ar: {
            ct_title: 'محطة العملات الرقمية',
            ct_subtitle: 'تداول العملات الرقمية في الوقت الفعلي — دفتر الأوامر وشريط التداول وإدخال الأوامر',
            ct_last_price: 'آخر سعر', ct_24h_change: 'تغيير اليوم', ct_24h_high: 'أعلى اليوم',
            ct_24h_low: 'أدنى اليوم', ct_24h_vol: 'حجم اليوم', ct_spread: 'الفارق',
            ct_orderbook: 'دفتر الأوامر', ct_trades: 'آخر التداولات', ct_new_order: 'أمر كريبتو جديد',
            ct_positions: 'مراكز الكريبتو', ct_no_positions: 'اختر محفظة لعرض المراكز',
            ct_no_crypto_pos: 'لا توجد مراكز كريبتو في هذه المحفظة',
            ct_buy: 'شراء', ct_sell: 'بيع', ct_order_type: 'نوع الأمر', ct_tif: 'مدة الصلاحية',
            ct_qty: 'الكمية', ct_notional: 'القيمة ($)', ct_limit_price: 'سعر الحد',
            ct_stop_price: 'سعر الوقف', ct_place_order: 'أمر شراء',
            ct_size: 'الحجم', ct_price: 'السعر', ct_total: 'الإجمالي', ct_time: 'الوقت',
            ct_symbol: 'الرمز', ct_side: 'الاتجاه', ct_avg_entry: 'متوسط الدخول', ct_mkt_val: 'القيمة السوقية',
            ct_unrealized: 'الربح/الخسارة', ct_pct: '%',
            ct_spread_label: 'الفارق',
            toast_submitted: 'تم تقديم أمر الكريبتو', toast_error: 'خطأ',
            confirm_order: 'تأكيد تقديم أمر الكريبتو؟',
            nav_home: 'الرئيسية', nav_portfolios: 'المحافظ', nav_pf_list: 'قائمة المحافظ',
            nav_pf1: 'العقل الذاتي', nav_pf2: 'ظل الكابيتول', nav_pf3: 'القناص الحذر',
            nav_market_pulse: 'نبض السوق', nav_trading: 'التداول', nav_orders: 'الأوامر', nav_readiness: 'الجاهزية',
            nav_crypto: 'محطة الكريبتو', nav_options: 'مختبر الخيارات', nav_screener: 'الفرز',
            nav_history: 'سجل الحساب', nav_alerts: 'التنبيهات', nav_research: 'البحث والذكاء', nav_settings: 'الإعدادات'
        }
    };

    /* ──────────────────────────────────────────────────────────────────────
       STATE
    ────────────────────────────────────────────────────────────────────── */
    var SYMBOLS = ['BTC/USD', 'ETH/USD', 'LTC/USD', 'DOGE/USD', 'SHIB/USD', 'AVAX/USD', 'UNI/USD', 'LINK/USD', 'DOT/USD'];
    var currentSymbol = 'BTC/USD';
    var currentTf = '1Min';
    var currentPfId = '';
    var currentSide = 'buy';
    var lang = document.documentElement.lang || 'en';
    var refreshTimers = {};
    var chartBars = [];

    /* ──────────────────────────────────────────────────────────────────────
       HELPERS
    ────────────────────────────────────────────────────────────────────── */
    function t(key) { return (T[lang] && T[lang][key]) || (T.en && T.en[key]) || key; }

    function applyLang() {
        lang = document.documentElement.lang || 'en';
        document.querySelectorAll('[data-key]').forEach(function (el) {
            var k = el.getAttribute('data-key');
            if (T[lang] && T[lang][k]) el.textContent = T[lang][k];
        });
    }

    function $(id) { return document.getElementById(id); }

    function fmtPrice(v, decimals) {
        var n = parseFloat(v);
        if (isNaN(n)) return '—';
        if (decimals === undefined) {
            if (n >= 1000) decimals = 2;
            else if (n >= 1) decimals = 4;
            else if (n >= 0.01) decimals = 6;
            else decimals = 8;
        }
        return '$' + n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    }

    function fmtNum(v, dec) {
        var n = parseFloat(v);
        if (isNaN(n)) return '—';
        return n.toLocaleString('en-US', { minimumFractionDigits: dec || 2, maximumFractionDigits: dec || 2 });
    }

    function fmtPct(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return '—';
        return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
    }

    function fmtVol(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return '—';
        if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
        if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
        if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
        return n.toFixed(2);
    }

    function fmtTime(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    }

    function showToast(msg, type) {
        var toast = document.createElement('div');
        toast.textContent = msg;
        toast.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:200;padding:.65rem 1.25rem;border-radius:999px;font-size:.82rem;font-weight:700;color:#fff;background:' + (type === 'error' ? 'var(--pf-red)' : 'var(--pf-green)') + ';box-shadow:0 8px 24px rgba(0,0,0,.3);animation:ct-fade-in .2s ease;';
        if (document.documentElement.dir === 'rtl') {
            toast.style.right = 'auto';
            toast.style.left = '1.5rem';
        }
        document.body.appendChild(toast);
        setTimeout(function () { toast.remove(); }, 3500);
    }

    function getLogoHtml(sym, size = 16) {
        if (!sym) return '';
        var ticker = sym.toUpperCase().trim();
        var logoFile = ticker;
        if (ticker.includes('BTC') || ticker === 'BTC/USD' || ticker === 'BTCUSD') {
            logoFile = 'BTC_USD';
        } else if (ticker.includes('ETH') || ticker === 'ETH/USD' || ticker === 'ETHUSD') {
            logoFile = 'ETH_USD';
        } else {
            // Underscore convention to match existing BTC_USD.svg / ETH_USD.svg and
            // the local {SYM}_USD.svg assets (e.g. LTC/USD -> LTC_USD.svg).
            logoFile = logoFile.replace('/', '_');
        }
        var src = '/assets/logos/' + logoFile + '.svg';
        var fallbackSrc = 'https://img.logo.dev/ticker/' + logoFile.replace('_', '-') + '?token=pk_XldCCgGITcKAcfCcVh8lXg&size=32';
        return '<img src="' + src + '" width="' + size + '" height="' + size + '" alt="' + ticker + '" ' +
            'style="width:' + size + 'px; height:' + size + 'px; border-radius:50%; object-fit:contain; background:rgba(255,255,255,0.04); border:1px solid var(--line); flex-shrink:0; display:inline-block; vertical-align:middle; transition: transform 0.2s;" ' +
            'onerror="this.onerror=null; this.src=\'' + fallbackSrc + '\';" ' +
            'onmouseover="this.style.transform=\'scale(1.08)\'" ' +
            'onmouseout="this.style.transform=\'scale(1)\'" />';
    }

    function updateOrderLogo() {
        $('ctOrderSymbol').textContent = currentSymbol;
        var logoEl = $('ctOrderLogo');
        if (logoEl) {
            var logoFile = currentSymbol.replace('/', '_').toUpperCase();
            logoEl.src = '/assets/logos/' + logoFile + '.svg';
            logoEl.onerror = function() {
                this.onerror = null;
                this.src = 'https://img.logo.dev/ticker/' + logoFile.replace('_', '-') + '?token=pk_XldCCgGITcKAcfCcVh8lXg&size=32';
            };
            logoEl.style.display = 'inline-block';
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       INIT
    ────────────────────────────────────────────────────────────────────── */
    function init() {
        buildSymbolBar();
        bindEvents();
        loadPortfolios();
        applyLang();
        updateOrderLogo();
        loadSnapshot();
        loadOrderbook();
        loadTrades();
        loadBars();
        startAutoRefresh();
    }

    /* ──────────────────────────────────────────────────────────────────────
       SYMBOL BAR
    ────────────────────────────────────────────────────────────────────── */
    function buildSymbolBar() {
        var bar = $('ctSymBar');
        bar.innerHTML = SYMBOLS.map(function (sym) {
            var cls = sym === currentSymbol ? 'ct-sym-pill active' : 'ct-sym-pill';
            var logoHtml = getLogoHtml(sym, 16);
            return '<button class="' + cls + '" data-sym="' + sym + '" style="display:inline-flex; align-items:center; gap:0.4rem; padding:0.35rem 0.65rem;">' + logoHtml + '<span>' + sym.replace('/', '<span style="opacity:.4">/</span>') + '</span></button>';
        }).join('');
    }

    /* ──────────────────────────────────────────────────────────────────────
       EVENTS
    ────────────────────────────────────────────────────────────────────── */
    function bindEvents() {
        /* Symbol pills */
        $('ctSymBar').addEventListener('click', function (e) {
            var btn = e.target.closest('[data-sym]');
            if (!btn) return;
            currentSymbol = btn.getAttribute('data-sym');
            buildSymbolBar();
            updateOrderLogo();
            refreshAll();
        });

        /* Timeframe buttons */
        document.querySelector('.ct-chart-toolbar').addEventListener('click', function (e) {
            var btn = e.target.closest('.ct-tf-btn');
            if (!btn) return;
            document.querySelectorAll('.ct-tf-btn').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentTf = btn.getAttribute('data-tf');
            loadBars();
        });

        /* Portfolio selector */
        $('ctPortfolioSelect').addEventListener('change', function () {
            currentPfId = this.value;
            loadPositions();
        });

        /* Side toggle */
        $('ctBuyBtn').addEventListener('click', function () {
            currentSide = 'buy';
            $('ctBuyBtn').className = 'active-buy';
            $('ctSellBtn').className = '';
            $('ctSubmitOrder').className = 'ct-submit-btn buy';
            $('ctSubmitOrder').textContent = lang === 'ar' ? 'أمر شراء' : 'Place Buy Order';
        });
        $('ctSellBtn').addEventListener('click', function () {
            currentSide = 'sell';
            $('ctSellBtn').className = 'active-sell';
            $('ctBuyBtn').className = '';
            $('ctSubmitOrder').className = 'ct-submit-btn sell';
            $('ctSubmitOrder').textContent = lang === 'ar' ? 'أمر بيع' : 'Place Sell Order';
        });

        /* Order type visibility */
        $('ctOrderType').addEventListener('change', function () {
            var v = this.value;
            $('ctLimitRow').style.display = (v === 'limit' || v === 'stop_limit') ? '' : 'none';
            $('ctStopRow').style.display = (v === 'stop' || v === 'stop_limit') ? '' : 'none';
        });

        /* Submit order */
        $('ctSubmitOrder').addEventListener('click', submitOrder);

        /* Theme toggle */
        var themeBtn = $('themeToggle');
        if (themeBtn) {
            themeBtn.addEventListener('click', function () {
                var html = document.documentElement;
                var next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
                html.setAttribute('data-theme', next);
                localStorage.setItem('theme', next);
                drawChart();
            });
        }

        /* Language toggle */
        var langBtn = $('langToggle');
        if (langBtn) {
            langBtn.addEventListener('click', function () {
                var html = document.documentElement;
                if (html.lang === 'en') {
                    html.lang = 'ar';
                    html.dir = 'rtl';
                    langBtn.textContent = 'EN';
                } else {
                    html.lang = 'en';
                    html.dir = 'ltr';
                    langBtn.textContent = 'AR';
                }
                applyLang();
            });
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       LOAD PORTFOLIOS
    ────────────────────────────────────────────────────────────────────── */
    async function loadPortfolios() {
        var sel = $('ctPortfolioSelect');
        try {
            var resp = await fetch('/api/portfolios');
            var data = await resp.json();
            sel.innerHTML = '';
            Object.entries(data).forEach(function (entry) {
                var opt = document.createElement('option');
                opt.value = entry[0];
                opt.textContent = entry[1].label || entry[0];
                sel.appendChild(opt);
            });
            if (sel.options.length > 0) {
                currentPfId = sel.value;
                loadPositions();
            }
        } catch (e) {
            sel.innerHTML = '<option>No portfolios</option>';
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       LOAD SNAPSHOT (KPI Strip)
    ────────────────────────────────────────────────────────────────────── */
    async function loadSnapshot() {
        try {
            var resp = await fetch('/api/crypto/snapshot/' + encodeURIComponent(currentSymbol));
            var data = await resp.json();
            var snap = data.snapshots ? data.snapshots[currentSymbol] : null;
            if (!snap) return;

            var last = snap.latestTrade ? snap.latestTrade.p : 0;
            var daily = snap.dailyBar || {};
            var prev = snap.prevDailyBar || {};
            var prevClose = prev.c || daily.o || last;
            var change = prevClose ? ((last - prevClose) / prevClose) * 100 : 0;

            $('kpiLast').textContent = fmtPrice(last);
            var chgEl = $('kpi24hChange');
            chgEl.textContent = fmtPct(change);
            chgEl.className = 'ct-kpi-val ' + (change >= 0 ? 'green' : 'red');
            $('kpi24hHigh').textContent = fmtPrice(daily.h || last);
            $('kpi24hLow').textContent = fmtPrice(daily.l || last);
            $('kpi24hVol').textContent = fmtVol(daily.v || 0);

            var bid = snap.latestQuote ? snap.latestQuote.bp : 0;
            var ask = snap.latestQuote ? snap.latestQuote.ap : 0;
            var spread = ask && bid ? (ask - bid) : 0;
            $('kpiSpread').textContent = fmtPrice(spread);
        } catch (e) {
            /* silent */
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       LOAD ORDERBOOK
    ────────────────────────────────────────────────────────────────────── */
    async function loadOrderbook() {
        try {
            var resp = await fetch('/api/crypto/orderbook/' + encodeURIComponent(currentSymbol));
            var data = await resp.json();
            var book = data.orderbooks ? data.orderbooks[currentSymbol] : null;
            if (!book) {
                $('ctOrderbook').innerHTML = '<div class="ct-pos-empty">No orderbook data</div>';
                return;
            }

            var asks = (book.a || []).slice(0, 12).reverse();
            var bids = (book.b || []).slice(0, 12);
            var maxAskSize = Math.max.apply(null, asks.map(function (a) { return a.s; }).concat([0.001]));
            var maxBidSize = Math.max.apply(null, bids.map(function (b) { return b.s; }).concat([0.001]));

            var askCumul = 0;
            var askHtml = asks.map(function (a) {
                askCumul += a.s;
                var pct = (a.s / maxAskSize) * 100;
                return '<div class="ct-ob-row ct-ob-row--ask">' +
                    '<div class="ct-ob-depth" style="width:' + pct + '%"></div>' +
                    '<span>' + fmtNum(a.s, 6) + '</span>' +
                    '<span>' + fmtPrice(a.p) + '</span>' +
                    '<span>' + fmtNum(askCumul, 4) + '</span></div>';
            }).join('');

            var bestAsk = asks.length > 0 ? asks[asks.length - 1].p : 0;
            var bestBid = bids.length > 0 ? bids[0].p : 0;
            var spread = bestAsk && bestBid ? bestAsk - bestBid : 0;
            var spreadPct = bestBid ? (spread / bestBid * 100) : 0;
            var spreadHtml = '<div class="ct-ob-spread">' + t('ct_spread_label') + ': ' + fmtPrice(spread) + ' (' + spreadPct.toFixed(3) + '%)</div>';

            var bidCumul = 0;
            var bidHtml = bids.map(function (b) {
                bidCumul += b.s;
                var pct = (b.s / maxBidSize) * 100;
                return '<div class="ct-ob-row ct-ob-row--bid">' +
                    '<div class="ct-ob-depth" style="width:' + pct + '%"></div>' +
                    '<span>' + fmtNum(b.s, 6) + '</span>' +
                    '<span>' + fmtPrice(b.p) + '</span>' +
                    '<span>' + fmtNum(bidCumul, 4) + '</span></div>';
            }).join('');

            $('ctOrderbook').innerHTML = askHtml + spreadHtml + bidHtml;
            $('obLastUpdate').textContent = fmtTime(book.t || new Date().toISOString());
        } catch (e) {
            $('ctOrderbook').innerHTML = '<div class="ct-pos-empty">Failed to load orderbook</div>';
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       LOAD TRADES (Trade Tape)
    ────────────────────────────────────────────────────────────────────── */
    async function loadTrades() {
        try {
            var resp = await fetch('/api/crypto/trades/' + encodeURIComponent(currentSymbol) + '?limit=50');
            var data = await resp.json();
            var trades = data.trades ? data.trades[currentSymbol] : [];
            if (!trades || trades.length === 0) {
                $('ctTrades').innerHTML = '<div class="ct-pos-empty">No recent trades</div>';
                return;
            }

            $('ctTrades').innerHTML = trades.slice(0, 30).map(function (tr) {
                var side = tr.tks === 'B' ? 'buy' : 'sell';
                return '<div class="ct-tape-row ' + side + '">' +
                    '<span>' + fmtPrice(tr.p) + '</span>' +
                    '<span>' + fmtNum(tr.s, 6) + '</span>' +
                    '<span>' + fmtTime(tr.t) + '</span></div>';
            }).join('');
        } catch (e) {
            $('ctTrades').innerHTML = '<div class="ct-pos-empty">Failed to load trades</div>';
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       LOAD BARS (Chart Data)
    ────────────────────────────────────────────────────────────────────── */
    async function loadBars() {
        try {
            var limit = 80;
            var resp = await fetch('/api/crypto/bars/' + encodeURIComponent(currentSymbol) + '?timeframe=' + currentTf + '&limit=' + limit);
            var data = await resp.json();
            chartBars = data.bars ? (data.bars[currentSymbol] || []) : [];
            drawChart();
        } catch (e) {
            chartBars = [];
            drawChart();
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       LOAD POSITIONS
    ────────────────────────────────────────────────────────────────────── */
    async function loadPositions() {
        if (!currentPfId) return;
        try {
            var resp = await fetch('/api/portfolio/' + currentPfId + '/positions');
            var positions = await resp.json();
            if (!Array.isArray(positions)) positions = [];

            var cryptoPositions = positions.filter(function (p) {
                return (p.asset_class === 'crypto') || (p.symbol && p.symbol.indexOf('/') !== -1);
            });

            if (cryptoPositions.length === 0) {
                $('ctPositions').innerHTML = '<div class="ct-pos-empty">' + t('ct_no_crypto_pos') + '</div>';
                return;
            }

            var html = '<table class="ct-pos-table"><thead><tr>' +
                '<th>' + t('ct_symbol') + '</th>' +
                '<th>' + t('ct_qty') + '</th>' +
                '<th>' + t('ct_avg_entry') + '</th>' +
                '<th>' + t('ct_price') + '</th>' +
                '<th>' + t('ct_mkt_val') + '</th>' +
                '<th>' + t('ct_unrealized') + '</th>' +
                '<th>' + t('ct_pct') + '</th>' +
                '</tr></thead><tbody>';

            cryptoPositions.forEach(function (p) {
                var unrealized = parseFloat(p.unrealized_pl || 0);
                var pct = parseFloat(p.unrealized_plpc || 0) * 100;
                var clr = unrealized >= 0 ? 'var(--pf-green)' : 'var(--pf-red)';
                html += '<tr>' +
                    '<td style="font-weight:700;color:var(--ink); display:flex; align-items:center; gap:0.45rem;">' +
                        getLogoHtml(p.symbol, 18) +
                        '<span>' + (p.symbol || '—') + '</span>' +
                    '</td>' +
                    '<td>' + fmtNum(p.qty, 6) + '</td>' +
                    '<td>' + fmtPrice(p.avg_entry_price) + '</td>' +
                    '<td>' + fmtPrice(p.current_price) + '</td>' +
                    '<td>' + fmtPrice(p.market_value) + '</td>' +
                    '<td style="color:' + clr + ';font-weight:700;">' + (unrealized >= 0 ? '+' : '') + fmtPrice(unrealized) + '</td>' +
                    '<td style="color:' + clr + ';font-weight:700;">' + fmtPct(pct) + '</td>' +
                    '</tr>';
            });

            html += '</tbody></table>';
            $('ctPositions').innerHTML = html;
        } catch (e) {
            $('ctPositions').innerHTML = '<div class="ct-pos-empty">Failed to load positions</div>';
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       CANDLESTICK CHART (Canvas)
    ────────────────────────────────────────────────────────────────────── */
    function drawChart() {
        var canvas = $('ctChart');
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = rect.height + 'px';
        ctx.scale(dpr, dpr);

        var w = rect.width;
        var h = rect.height;
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var bgColor = isDark ? '#1A0F08' : '#FFFFFF';
        var gridColor = isDark ? 'rgba(255,255,255,.06)' : 'rgba(26,15,8,.06)';
        var textColor = isDark ? '#A39A92' : '#7A6B5E';
        var greenColor = '#22c55e';
        var redColor = '#ef4444';

        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, w, h);

        if (chartBars.length === 0) {
            ctx.fillStyle = textColor;
            ctx.font = '13px Manrope, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Loading chart data...', w / 2, h / 2);
            return;
        }

        var padL = 12;
        var padR = 72;
        var padT = 16;
        var padB = 38;
        var volH = 50;

        var bars = chartBars;
        var highs = bars.map(function (b) { return b.h; });
        var lows = bars.map(function (b) { return b.l; });
        var vols = bars.map(function (b) { return b.v || 0; });
        var priceMin = Math.min.apply(null, lows);
        var priceMax = Math.max.apply(null, highs);
        var volMax = Math.max.apply(null, vols.concat([1]));
        var pRange = priceMax - priceMin;
        if (pRange === 0) pRange = priceMax * 0.01 || 1;
        priceMin -= pRange * 0.05;
        priceMax += pRange * 0.05;
        pRange = priceMax - priceMin;

        var chartW = w - padL - padR;
        var chartH = h - padT - padB - volH;
        var barW = chartW / bars.length;
        var candleW = Math.max(1, barW * 0.6);

        function priceY(p) { return padT + chartH - ((p - priceMin) / pRange) * chartH; }

        /* Grid lines */
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 0.5;
        var gridLines = 5;
        for (var gi = 0; gi <= gridLines; gi++) {
            var gy = padT + (chartH / gridLines) * gi;
            ctx.beginPath();
            ctx.moveTo(padL, gy);
            ctx.lineTo(w - padR, gy);
            ctx.stroke();
        }

        /* Price axis labels */
        ctx.fillStyle = textColor;
        ctx.font = '10px IBM Plex Mono, monospace';
        ctx.textAlign = 'left';
        for (var pi = 0; pi <= gridLines; pi++) {
            var pVal = priceMax - (pRange / gridLines) * pi;
            var py = padT + (chartH / gridLines) * pi;
            ctx.fillText(fmtPrice(pVal), w - padR + 6, py + 3);
        }

        /* Candlesticks */
        bars.forEach(function (bar, i) {
            var x = padL + i * barW + barW / 2;
            var isGreen = bar.c >= bar.o;
            var color = isGreen ? greenColor : redColor;

            /* Wick */
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, priceY(bar.h));
            ctx.lineTo(x, priceY(bar.l));
            ctx.stroke();

            /* Body */
            var bodyTop = priceY(Math.max(bar.o, bar.c));
            var bodyBot = priceY(Math.min(bar.o, bar.c));
            var bodyH = Math.max(1, bodyBot - bodyTop);
            ctx.fillStyle = color;
            ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
        });

        /* Volume bars */
        var volBase = h - padB;
        bars.forEach(function (bar, i) {
            var x = padL + i * barW + barW / 2;
            var vh = (bar.v / volMax) * volH;
            var isGreen = bar.c >= bar.o;
            ctx.fillStyle = isGreen ? 'rgba(34,197,94,.25)' : 'rgba(239,68,68,.25)';
            ctx.fillRect(x - candleW / 2, volBase - vh, candleW, vh);
        });

        /* Time labels */
        ctx.fillStyle = textColor;
        ctx.font = '9px IBM Plex Mono, monospace';
        ctx.textAlign = 'center';
        var labelInterval = Math.max(1, Math.floor(bars.length / 6));
        bars.forEach(function (bar, i) {
            if (i % labelInterval !== 0) return;
            var x = padL + i * barW + barW / 2;
            var d = new Date(bar.t);
            var lbl = '';
            if (currentTf === '1Day') {
                lbl = (d.getMonth() + 1) + '/' + d.getDate();
            } else {
                lbl = d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
            }
            ctx.fillText(lbl, x, h - padB + 14);
        });

        /* Symbol watermark */
        ctx.fillStyle = isDark ? 'rgba(255,255,255,.03)' : 'rgba(26,15,8,.03)';
        ctx.font = 'bold 48px DM Serif Display, serif';
        ctx.textAlign = 'center';
        ctx.fillText(currentSymbol, w / 2, h / 2 + 16);
    }

    /* ──────────────────────────────────────────────────────────────────────
       SUBMIT ORDER
    ────────────────────────────────────────────────────────────────────── */
    async function submitOrder() {
        if (!currentPfId) {
            showToast('Select a portfolio first', 'error');
            return;
        }

        var orderType = $('ctOrderType').value;
        var qty = $('ctQty').value;
        var notional = $('ctNotional').value;
        var limitPrice = $('ctLimitPrice').value;
        var stopPrice = $('ctStopPrice').value;
        var tif = $('ctTif').value;

        if (!qty && !notional) {
            showToast('Enter quantity or notional amount', 'error');
            return;
        }

        var body = {
            symbol: currentSymbol,
            side: currentSide,
            type: orderType,
            time_in_force: tif
        };
        if (qty) body.qty = qty;
        if (notional && !qty) body.notional = notional;
        if (limitPrice && (orderType === 'limit' || orderType === 'stop_limit')) body.limit_price = limitPrice;
        if (stopPrice && (orderType === 'stop' || orderType === 'stop_limit')) body.stop_price = stopPrice;

        try {
            var resp = await fetch('/api/portfolio/' + currentPfId + '/crypto-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            var result = await resp.json();
            if (result.error) {
                showToast(result.error, 'error');
            } else {
                showToast(t('toast_submitted'), 'success');
                $('ctQty').value = '';
                $('ctNotional').value = '';
                $('ctLimitPrice').value = '';
                $('ctStopPrice').value = '';
                loadPositions();
            }
        } catch (e) {
            showToast(t('toast_error') + ': ' + e.message, 'error');
        }
    }

    /* ──────────────────────────────────────────────────────────────────────
       REFRESH ALL DATA
    ────────────────────────────────────────────────────────────────────── */
    function refreshAll() {
        loadSnapshot();
        loadOrderbook();
        loadTrades();
        loadBars();
        if (currentPfId) loadPositions();
    }

    /* ──────────────────────────────────────────────────────────────────────
       AUTO-REFRESH TIMERS
    ────────────────────────────────────────────────────────────────────── */
    function startAutoRefresh() {
        clearAutoRefresh();
        refreshTimers.snapshot = setInterval(loadSnapshot, 10000);
        refreshTimers.orderbook = setInterval(loadOrderbook, 5000);
        refreshTimers.trades = setInterval(loadTrades, 8000);
        refreshTimers.bars = setInterval(loadBars, 30000);
        refreshTimers.positions = setInterval(function () { if (currentPfId) loadPositions(); }, 15000);
    }

    function clearAutoRefresh() {
        Object.keys(refreshTimers).forEach(function (k) {
            clearInterval(refreshTimers[k]);
        });
        refreshTimers = {};
    }

    /* ──────────────────────────────────────────────────────────────────────
       RESIZE HANDLER
    ────────────────────────────────────────────────────────────────────── */
    var resizeTimeout;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(drawChart, 150);
    });

    /* ──────────────────────────────────────────────────────────────────────
       CLEANUP ON LEAVE
    ────────────────────────────────────────────────────────────────────── */
    window.addEventListener('beforeunload', clearAutoRefresh);

    /* ──────────────────────────────────────────────────────────────────────
       BOOT
    ────────────────────────────────────────────────────────────────────── */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
