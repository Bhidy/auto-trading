/**
 * stock-detail.js
 * Institutional-grade stock quote metrics, fundamentals, advanced chart.js curve,
 * options chain ladders, regulatory SEC filings, Level 2 depth lists, and AI neural confidence gauges.
 */
(function() {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';
    // Deep-link support: /stock-detail.html?symbol=NVDA (e.g. from holding clicks).
    // Sanitize to a safe ticker (letters/digits, plus . / - for crypto/class shares).
    function sanitizeSymbol(raw) {
        if (!raw) return '';
        var s = String(raw).trim().toUpperCase().replace(/[^A-Z0-9./-]/g, '');
        return s.slice(0, 12);
    }
    var currentSymbol = sanitizeSymbol(new URLSearchParams(window.location.search).get('symbol')) || 'AAPL';
    var stockChartInstance = null;
    var rawBarsData = [];

    function getLogoHtml(sym, size = 20) {
        if (!sym) return '';
        var ticker = sym.toUpperCase().trim();
        var logoFile = ticker;
        if (ticker.includes('BTC') || ticker === 'BTC/USD' || ticker === 'BTCUSD') {
            logoFile = 'BTC_USD';
        } else if (ticker.includes('ETH') || ticker === 'ETH/USD' || ticker === 'ETHUSD') {
            logoFile = 'ETH_USD';
        } else {
            logoFile = logoFile.replace('/', '-');
        }
        var src = '/assets/logos/' + logoFile + '.svg';
        var fallbackSrc = 'https://img.logo.dev/ticker/' + logoFile.replace('_', '-') + '?token=pk_XldCCgGITcKAcfCcVh8lXg&size=32';
        return '<img src="' + src + '" width="' + size + '" height="' + size + '" alt="' + ticker + '" ' +
            'style="width:' + size + 'px; height:' + size + 'px; border-radius:50%; object-fit:contain; background:rgba(255,255,255,0.04); border:1px solid var(--line); flex-shrink:0; display:inline-block; vertical-align:middle; margin-right:0.45rem; transition: transform 0.2s;" ' +
            'onerror="this.onerror=null; this.src=\'' + fallbackSrc + '\';" ' +
            'onmouseover="this.style.transform=\'scale(1.08)\'" ' +
            'onmouseout="this.style.transform=\'scale(1)\'" />';
    }

    /* ─── Translations Dictionary ───────────────────────────────────────── */
    var T = {
        en: {
            nav_home: 'Home',
            nav_portfolios: 'Portfolios',
            nav_pf_list: 'Portfolio List',
            nav_pf1: 'Self Improving Brain',
            nav_pf2: 'Capitol Shadow',
            nav_pf3: 'Cautious Sniper',
            nav_market_pulse: 'Market Pulse',
            nav_alerts: 'Alerts',
            nav_research: 'Research & AI',
            nav_settings: 'Settings',
            nav_trading: 'Trading',
            nav_orders: 'Orders',
            nav_crypto: 'Crypto Terminal',
            nav_options: 'Options Lab',
            nav_screener: 'Screener',
            nav_history: 'Account History',
            search_tag: 'Terminal Analysis',
            search_title: 'Institutional Quote Research',
            btn_search: 'Search',
            realtime_label: 'REAL-TIME MULTI-TICK',
            chart_title: 'Technical Intraday Curve',
            fundamentals_title: 'Fundamentals & Financial Key metrics',
            options_title: 'Derivative Options Chain (Call/Put Spreads)',
            sec_title: 'Regulatory SEC Filings',
            ai_summary_title: 'AI Research Summary',
            ai_score_label: 'Overall AI Catalyst Index',
            ai_score_sub: 'Neural confidence index (Scale 1-10)',
            l2_title: 'Level 2 Depth Order Book',
            l2_sub: 'Live depth ladders and liquid spreads (Bids / Asks)',
            consensus_title: 'Analyst Consensus Ratings',
            peers_title: 'Sector Peer Contrast',
            
            // Table / Headers
            opt_bid_c: 'Call Bid',
            opt_ask_c: 'Call Ask',
            opt_vol_c: 'Call Vol',
            opt_strike: 'Strike',
            opt_bid_p: 'Put Bid',
            opt_ask_p: 'Put Ask',
            opt_vol_p: 'Put Vol',
            sec_form: 'Form Type',
            sec_date: 'Filing Date',
            sec_desc: 'Description',
            sec_act: 'Action',
            sec_download: 'Download PDF',
            
            // Metrics keys
            m_ceo: 'CEO',
            m_cap: 'Market Cap',
            m_pe: 'P/E Ratio',
            m_yield: 'Div Yield',
            m_beta: 'Beta',
            m_prev: 'Prev Close'
        },
        ar: {
            nav_home: 'الرئيسية',
            nav_portfolios: 'المحافظ',
            nav_pf_list: 'قائمة المحافظ',
            nav_pf1: 'الدماغ ذاتي التحسين',
            nav_pf2: 'ظل الكابيتول',
            nav_pf3: 'القناص الحذر',
            nav_market_pulse: 'نبض السوق',
            nav_alerts: 'التنبيهات',
            nav_research: 'الأبحاث والذكاء',
            nav_settings: 'الإعدادات',
            nav_trading: 'التداول',
            nav_orders: 'الأوامر',
            nav_crypto: 'محطة العملات الرقمية',
            nav_options: 'مختبر الخيارات',
            nav_screener: 'فلتر الأسهم',
            nav_history: 'سجل الحساب',
            search_tag: 'تحليل المنصة الرقمية',
            search_title: 'أبحاث وتقارير الأسهم الفورية',
            btn_search: 'بحث',
            realtime_label: 'بث حي - متعدد البيانات',
            chart_title: 'المنحنى الفني للأسعار',
            fundamentals_title: 'البيانات الأساسية والمالية الكبرى',
            options_title: 'سلسلة عقود الخيارات المشتقة (Calls/Puts)',
            sec_title: 'الإفصاحات والتقارير التنظيمية SEC',
            ai_summary_title: 'ملخص أبحاث الذكاء الاصطناعي',
            ai_score_label: 'مؤشر محفزات الذكاء الاصطناعي الإجمالي',
            ai_score_sub: 'مؤشر الثقة العصبي (مقياس ١-١٠)',
            l2_title: 'دفتر أوامر المستوى الثاني L2',
            l2_sub: 'عمق صانع السوق وفجوات السيولة الحية',
            consensus_title: 'توقعات وتوصيات المحللين',
            peers_title: 'مقارنة النظراء في القطاع',
            
            // Table / Headers
            opt_bid_c: 'شراء عقود الشراء',
            opt_ask_c: 'بيع عقود الشراء',
            opt_vol_c: 'حجم الشراء',
            opt_strike: 'سعر التنفيذ',
            opt_bid_p: 'شراء عقود البيع',
            opt_ask_p: 'بيع عقود البيع',
            opt_vol_p: 'حجم البيع',
            sec_form: 'نوع النموذج',
            sec_date: 'تاريخ الإيداع',
            sec_desc: 'تفاصيل التقرير',
            sec_act: 'الإجراء',
            sec_download: 'تحميل PDF',
            
            // Metrics keys
            m_ceo: 'الرئيس التنفيذي',
            m_cap: 'القيمة السوقية',
            m_pe: 'مكرر الربحية',
            m_yield: 'عائد التوزيعات',
            m_beta: 'معامل بيتا',
            m_prev: 'الإغلاق السابق'
        }
    };

    function applyLang(l) {
        lang = l;
        localStorage.setItem('starta-lang', l);
        document.documentElement.lang = l;
        document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
        
        var toggle = document.getElementById('langToggle');
        if (toggle) toggle.textContent = l === 'ar' ? 'EN' : 'AR';
        
        var dict = T[l] || T.en;
        document.querySelectorAll('[data-key]').forEach(function(el) {
            var k = el.getAttribute('data-key');
            if (dict[k]) {
                el.textContent = dict[k];
            }
        });
        
        // Refresh specific localized texts
        renderDetails();
    }

    /* ─── Core Logic ────────────────────────────────────────────────────── */
    function loadStockDetails(symbol) {
        currentSymbol = symbol.trim().toUpperCase() || 'AAPL';
        
        fetch(`/api/stock/${currentSymbol}/details`)
            .then(function(res) { return res.json(); })
            .then(function(data) {
                renderStockData(data);
            })
            .catch(function(err) {
                console.error('Error fetching stock details:', err);
            });
    }

    function renderStockData(data) {
        var symbol = data.symbol;
        var quote = data.quote || { price: 150.00, bid: 149.95, ask: 150.05, size: 100 };
        var profile = data.profile || {};
        rawBarsData = data.bars || [];

        // Meta text
        var logoEl = document.getElementById('stockDetailLogo');
        if (logoEl) {
            var logoFile = symbol.toUpperCase();
            logoEl.src = '/assets/logos/' + logoFile + '.svg';
            logoEl.onerror = function() {
                this.onerror = null;
                this.src = 'https://img.logo.dev/ticker/' + logoFile + '?token=pk_XldCCgGITcKAcfCcVh8lXg&size=64';
            };
            logoEl.style.display = 'block';
        }
        document.getElementById('stockSymbolText').textContent = symbol;
        document.getElementById('stockCompanyName').textContent = profile.name || (symbol + ' Corp.');
        document.getElementById('stockCompanyDesc').textContent = profile.desc || 'No profile description available.';
        
        // Price Hero
        document.getElementById('stockLastPrice').textContent = '$' + quote.price.toFixed(2);
        
        // Change calculate
        var prevClose = parseFloat(profile.prev || quote.price);
        var change = quote.price - prevClose;
        var changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
        
        var changePill = document.getElementById('stockChangePill');
        if (change >= 0) {
            changePill.className = 'chg-pill pos';
            changePill.textContent = '▲ +' + changePct.toFixed(2) + '%';
        } else {
            changePill.className = 'chg-pill neg';
            changePill.textContent = '▼ ' + changePct.toFixed(2) + '%';
        }

        // Render sections
        renderFundamentals(profile, prevClose);
        renderSECFilings(symbol);
        renderOptionsChain(quote.price);
        renderAIResearchSummary(symbol, changePct);
        renderLevel2Depth(quote.price);
        renderAnalystConsensus(symbol);
        renderPeers(symbol, profile);
        
        // Load Chart
        renderTechnicalChart('1D');
    }

    function renderFundamentals(p, prevClose) {
        var grid = document.getElementById('fundamentalsGrid');
        var dict = T[lang] || T.en;

        var items = [
            { label: dict.m_prev || 'Prev Close', val: '$' + prevClose.toFixed(2) },
            { label: 'Exchange', val: p.exchange || '—' },
            { label: 'Asset Class', val: p.asset_class || '—' },
            { label: 'Tradable', val: p.tradable ? 'Yes' : 'No' },
            { label: 'Shortable', val: p.shortable ? 'Yes' : 'No' },
            { label: 'Fractionable', val: p.fractionable ? 'Yes' : 'No' }
        ];

        grid.innerHTML = items.map(function(item) {
            return '<div class="metric-card">' +
                '<span class="label">' + item.label + '</span>' +
                '<span class="value">' + item.val + '</span>' +
            '</div>';
        }).join('');
    }

    function renderSECFilings(symbol) {
        // SEC filings not available via Alpaca free tier — section removed from UI
    }

    function renderOptionsChain(price) {
        var list = document.getElementById('optionsChainList');
        list.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:1rem;">Loading options chain from Alpaca...</td></tr>';

        fetch('/api/options/chain/' + currentSymbol)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var snapshots = data.snapshots || {};
                var keys = Object.keys(snapshots).slice(0, 10);
                if (keys.length === 0) {
                    list.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--muted); font-size:0.75rem; padding:1rem;">No options data available for ' + currentSymbol + '.</td></tr>';
                    return;
                }
                var html = '';
                keys.forEach(function(contractId) {
                    var snap = snapshots[contractId];
                    var q = snap.latestQuote || {};
                    var greeks = snap.greeks || {};
                    var bid = parseFloat(q.bp || 0);
                    var ask = parseFloat(q.ap || 0);
                    var vol = parseInt(snap.impliedVolatility || 0);
                    var parts = contractId.match(/(\d{6})([CP])(\d+)/);
                    var strike = parts ? (parseInt(parts[3]) / 1000).toFixed(0) : '—';
                    var isCall = parts ? parts[2] === 'C' : true;
                    var rowId = 'opt-row-' + contractId.slice(-8);
                    html += '<tr id="' + rowId + '" class="opt-clickable" style="cursor:pointer;" onclick="var snap=arguments[0];window._showGreeks && window._showGreeks(\'' + contractId + '\', snap)">';
                    if (isCall) {
                        html += '<td style="color:var(--pf-green); font-family:var(--pf-mono); font-weight:700;">$' + bid.toFixed(2) + '</td>';
                        html += '<td style="color:var(--pf-green); font-family:var(--pf-mono);">$' + ask.toFixed(2) + '</td>';
                        html += '<td style="font-family:var(--pf-mono); text-align:center;">' + vol + '</td>';
                        html += '<td style="font-family:var(--pf-mono); font-weight:800; text-align:center; background:var(--teal-soft); color:var(--teal); border-radius:4px;">$' + strike + '</td>';
                        html += '<td colspan="3" style="color:var(--muted); text-align:center;">—</td>';
                    } else {
                        html += '<td colspan="3" style="color:var(--muted); text-align:center;">—</td>';
                        html += '<td style="font-family:var(--pf-mono); font-weight:800; text-align:center; background:var(--teal-soft); color:var(--teal); border-radius:4px;">$' + strike + '</td>';
                        html += '<td style="color:var(--pf-red); font-family:var(--pf-mono); font-weight:700;">$' + bid.toFixed(2) + '</td>';
                        html += '<td style="color:var(--pf-red); font-family:var(--pf-mono);">$' + ask.toFixed(2) + '</td>';
                        html += '<td style="font-family:var(--pf-mono); text-align:center;">' + vol + '</td>';
                    }
                    html += '</tr>';
                });
                list.innerHTML = html;
                // Wire click handlers
                var rows = list.querySelectorAll('tr');
                rows.forEach(function(row) {
                    row.addEventListener('click', function(e) {
                        var idx = Array.from(list.querySelectorAll('tr')).indexOf(row) - 0;
                        var contractId = keys[idx];
                        if (contractId && snapshots[contractId]) {
                            renderOptionsGreeks(contractId, snapshots[contractId]);
                        }
                    });
                });
            })
            .catch(function() {
                list.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--muted); font-size:0.75rem; padding:1rem;">Options data unavailable.</td></tr>';
            });
    }

    function renderAIResearchSummary(symbol, changePct) {
        document.getElementById('aiCatalystText').textContent = 'Loading signal data...';
        document.getElementById('aiCatalystScoreRing').textContent = '—';

        fetch('/api/portfolio/portfolio_1/details')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var signals = (data.signals && data.signals.signals) || [];
                var matched = signals.find(function(s) { return s.symbol === symbol; });

                if (matched) {
                    var score = (matched.score * 10).toFixed(1);
                    var reasons = (matched.reasons || []).join('. ');
                    var ind = matched.indicators || {};
                    var extra = '';
                    if (ind.rsi14) extra += 'RSI: ' + ind.rsi14.toFixed(1);
                    if (ind.momentum_1m !== undefined) extra += ' | 1M: ' + (ind.momentum_1m >= 0 ? '+' : '') + ind.momentum_1m.toFixed(1) + '%';
                    if (ind.atr_pct) extra += ' | ATR: ' + ind.atr_pct.toFixed(2) + '%';

                    document.getElementById('aiCatalystText').textContent = matched.signal + ' signal — ' + reasons + (extra ? ' [' + extra + ']' : '');
                    document.getElementById('aiCatalystScoreRing').textContent = score;
                    document.getElementById('aiCatalystScoreRing').style.setProperty('--score-fill', (parseFloat(score) * 10) + '%');
                } else {
                    document.getElementById('aiCatalystText').textContent = 'No active AI signal for ' + symbol + '. Not in current trading watchlist.';
                    document.getElementById('aiCatalystScoreRing').textContent = 'N/A';
                    document.getElementById('aiCatalystScoreRing').style.setProperty('--score-fill', '0%');
                }
            })
            .catch(function() {
                document.getElementById('aiCatalystText').textContent = 'Signal data unavailable.';
                document.getElementById('aiCatalystScoreRing').textContent = '—';
            });
    }

    function renderLevel2Depth(price) {
        // L2 depth requires paid SIP subscription — replaced with Options Greeks card
        var list = document.getElementById('optionsGreeksGrid');
        if (!list) return;
        list.innerHTML = '<div style="text-align:center;color:var(--muted);padding:1rem;font-size:0.72rem;">Click an options contract row to view live Greeks (delta, gamma, theta, vega, IV)</div>';
    }

    function renderL2FromQuote(list, price) {
        // No-op — L2 replaced by Greeks
    }

    function renderOptionsGreeks(contractId, snap) {
        var grid = document.getElementById('optionsGreeksGrid');
        if (!grid) return;
        var greeks = snap.greeks || {};
        var iv = snap.impliedVolatility;
        var items = [
            { label: 'Delta', val: greeks.delta ? greeks.delta.toFixed(4) : '—', color: '#FF8A3D' },
            { label: 'Gamma', val: greeks.gamma ? greeks.gamma.toFixed(4) : '—', color: '#E55A1F' },
            { label: 'Theta', val: greeks.theta ? greeks.theta.toFixed(4) : '—', color: 'var(--pf-red)' },
            { label: 'Vega', val: greeks.vega ? greeks.vega.toFixed(4) : '—', color: 'var(--pf-green)' },
            { label: 'Rho', val: greeks.rho ? greeks.rho.toFixed(4) : '—', color: '#8b5cf6' },
            { label: 'IV', val: iv ? (iv * 100).toFixed(1) + '%' : '—', color: 'var(--teal)' }
        ];
        grid.innerHTML = '<div style="font-size:0.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.5rem;">' + contractId.slice(0, 18) + '</div>' +
            items.map(function(item) {
                return '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.35rem 0;border-bottom:1px solid var(--line);">' +
                    '<span style="font-weight:700;font-size:0.75rem;color:var(--ink);">' + item.label + '</span>' +
                    '<span style="font-family:var(--pf-mono);font-weight:700;font-size:0.8rem;color:' + item.color + ';">' + item.val + '</span>' +
                '</div>';
            }).join('');
    }

    function renderAnalystConsensus(symbol) {
        var ratingEl = document.getElementById('consensusRatingText');
        var bars = document.getElementById('analystConsensusBars');
        ratingEl.textContent = '...';

        fetch('/api/portfolio/portfolio_1/details')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var signals = (data.signals && data.signals.signals) || [];
                var matched = signals.find(function(s) { return s.symbol === symbol; });

                var consensus, buy, hold, sell;
                if (matched) {
                    var score = matched.score || 0;
                    if (score >= 0.8) { consensus = 'STRONG BUY'; buy = 85; hold = 12; sell = 3; }
                    else if (score >= 0.6) { consensus = 'BUY'; buy = 70; hold = 22; sell = 8; }
                    else if (score >= 0.4) { consensus = 'HOLD'; buy = 30; hold = 50; sell = 20; }
                    else if (score >= 0.2) { consensus = 'SELL'; buy = 15; hold = 25; sell = 60; }
                    else { consensus = 'STRONG SELL'; buy = 5; hold = 15; sell = 80; }
                } else {
                    consensus = 'NO SIGNAL'; buy = 0; hold = 0; sell = 0;
                }

                ratingEl.textContent = consensus;
                ratingEl.style.color = buy > 60 ? 'var(--pf-green)' : (hold > 40 ? '#FF8A3D' : 'var(--pf-red)');

                if (buy === 0 && hold === 0 && sell === 0) {
                    bars.innerHTML = '<div style="text-align:center; color:var(--muted); font-size:0.72rem; padding:0.5rem;">Not in active watchlist.</div>';
                } else {
                    bars.innerHTML =
                        '<div class="rating-row"><span class="label">' + (lang === 'ar' ? 'شراء' : 'Buy') + '</span><div class="bar-outer"><div class="bar-inner" style="width:' + buy + '%; background:var(--pf-green);"></div></div><span class="num">' + buy + '%</span></div>' +
                        '<div class="rating-row"><span class="label">' + (lang === 'ar' ? 'احتفاظ' : 'Hold') + '</span><div class="bar-outer"><div class="bar-inner" style="width:' + hold + '%; background:#FF8A3D;"></div></div><span class="num">' + hold + '%</span></div>' +
                        '<div class="rating-row"><span class="label">' + (lang === 'ar' ? 'بيع' : 'Sell') + '</span><div class="bar-outer"><div class="bar-inner" style="width:' + sell + '%; background:var(--pf-red);"></div></div><span class="num">' + sell + '%</span></div>';
                }
            })
            .catch(function() {
                ratingEl.textContent = '—';
                bars.innerHTML = '<div style="text-align:center; color:var(--muted); font-size:0.72rem;">Signal data unavailable.</div>';
            });
    }

    function renderPeers(symbol, profile) {
        var list = document.getElementById('peerContrastList');
        var peers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META'];
        if (peers.indexOf(symbol) === -1) { peers[4] = symbol; }
        list.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--muted);">Loading peer data...</td></tr>';

        fetch('/api/market/quotes?symbols=' + peers.join(','))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var html = '';
                peers.forEach(function(pSym) {
                    var q = data[pSym] || {};
                    var styleHighlight = pSym === symbol ? 'background: var(--teal-soft); font-weight:800;' : '';
                    var price = q.price ? '$' + q.price.toFixed(2) : '—';
                    var changePct = q.changePct !== undefined ? (q.changePct >= 0 ? '+' : '') + q.changePct.toFixed(2) + '%' : '—';
                    var vol = q.volume ? (q.volume / 1e6).toFixed(1) + 'M' : '—';
                    html += '<tr style="' + styleHighlight + '">' +
                        '<td style="font-family:var(--pf-mono); display:flex; align-items:center; gap:0.45rem;">' +
                            getLogoHtml(pSym, 20) +
                            '<span>' + pSym + '</span>' +
                        '</td>' +
                        '<td style="font-family:var(--pf-mono);">' + price + '</td>' +
                        '<td style="font-family:var(--pf-mono); color:' + (q.changePct >= 0 ? 'var(--pf-green)' : 'var(--pf-red)') + ';">' + changePct + '</td>' +
                        '<td style="font-family:var(--pf-mono);">' + vol + '</td>' +
                    '</tr>';
                });
                list.innerHTML = html;
            })
            .catch(function() {
                list.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--muted);">Peer data unavailable.</td></tr>';
            });
    }

    function renderTechnicalChart(range) {
        var ctx = document.getElementById('stockDetailChart');
        if (!ctx) return;

        if (range === '1D') {
            fetch('/api/market/bars/' + currentSymbol + '?timeframe=5Min&limit=78')
                .then(function(r) { return r.ok ? r.json() : []; })
                .then(function(bars) {
                    renderChartFromBars(ctx, bars || []);
                })
                .catch(function() {
                    renderChartFallback(ctx);
                });
            return;
        }

        renderChartFromBars(ctx, rawBarsData);
    }

    function renderChartFromBars(ctx, bars) {
        var slice = bars.length > 78 ? bars.slice(bars.length - 78) : bars;
        if (slice.length === 0) {
            renderChartFallback(ctx);
            return;
        }

        var labels = slice.map(function(b) {
            var date = new Date(b.t);
            if (b.t && b.t.includes('T')) return b.t.slice(11, 16);
            return isNaN(date.getTime()) ? b.t : date.toLocaleDateString(lang === 'ar' ? 'ar-EG' : 'en-US', { month: 'short', day: 'numeric' });
        });
        var prices = slice.map(function(b) { return b.c; });

        if (stockChartInstance) {
            stockChartInstance.destroy();
        }

        var gridColor = StartaTheme.current() === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(26,15,8,0.06)';
        var inkColor = StartaTheme.current() === 'dark' ? '#FFF1E8' : '#1A0F08';
        var isIntraday = slice.length > 0 && slice[0].t && slice[0].t.includes('T');

        stockChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: currentSymbol,
                    data: prices,
                    borderColor: '#FF8A3D',
                    borderWidth: 2.5,
                    backgroundColor: 'rgba(255, 138, 61, 0.05)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: prices.length > 30 ? 0 : 2,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#FF8A3D'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        grid: { color: gridColor },
                        ticks: { color: inkColor, font: { size: isIntraday ? 8 : 10 }, maxTicksLimit: isIntraday ? 12 : 8, maxRotation: 0 }
                    },
                    y: {
                        position: lang === 'ar' ? 'right' : 'left',
                        grid: { color: gridColor },
                        ticks: { color: inkColor, font: { size: 10 }, callback: function(v) { return '$' + v.toFixed(1); } }
                    }
                }
            }
        });
    }

    function renderChartFallback(ctx) {
        var ctxCanvas = ctx.getContext ? ctx.getContext('2d') : null;
        if (ctxCanvas) {
            ctxCanvas.font = '12px Manrope';
            ctxCanvas.fillStyle = StartaTheme.current() === 'dark' ? '#a39a92' : '#7a6b5e';
            ctxCanvas.textAlign = 'center';
            ctxCanvas.fillText('Intraday chart data loading...', ctx.width / 2, ctx.height / 2);
        }
    }

    function renderDetails() {
        if (currentSymbol) {
            loadStockDetails(currentSymbol);
        }
    }

    /* ─── Initialization & Event Handlers ───────────────────────────────── */
    document.addEventListener('DOMContentLoaded', function() {
        // Bind search btn
        document.getElementById('stockSearchBtn').addEventListener('click', function() {
            var val = document.getElementById('stockSearchInput').value;
            if (val) loadStockDetails(val);
        });

        // Search input Enter key bind
        document.getElementById('stockSearchInput').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                var val = this.value;
                if (val) loadStockDetails(val);
            }
        });

        // Range buttons
        document.querySelectorAll('.chart-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.chart-btn').forEach(function(b) { b.classList.remove('active'); });
                this.classList.add('active');
                renderTechnicalChart(this.getAttribute('data-range'));
            });
        });

        // Theme sync
        document.addEventListener('starta:themechange', function() {
            renderTechnicalChart('1D');
        });

        // Lang switch bind
        document.getElementById('langToggle').addEventListener('click', function() {
            applyLang(lang === 'ar' ? 'en' : 'ar');
        });

        applyLang(lang);
        
        // Scrolling marquee
        function updateMarquee() {
            fetch('/api/market/quotes')
                .then(r => r.json())
                .then(data => {
                    var el = document.getElementById('marketTickerMarquee');
                    if (!el) return;
                    var html = '';
                    var symbols = ['SPY', 'QQQ', 'DIA', 'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META'];
                    symbols.forEach(function(sym) {
                        var q = data[sym];
                        if (q) {
                            var sign = q.change >= 0 ? '▲' : '▼';
                            var cls = q.change >= 0 ? 'pf-pos' : 'pf-neg';
                            html += `<div class="pf-ticker-item">
                                <span class="sym">${sym}</span>
                                <span class="price pf-num">$${q.price.toFixed(2)}</span>
                                <span class="chg ${cls} pf-num">${sign} ${q.changePct.toFixed(2)}%</span>
                            </div>`;
                        }
                    });
                    if (html) el.innerHTML = html + html;
                })
                .catch(err => console.warn('Ticker error:', err));
        }
        updateMarquee();
        setInterval(updateMarquee, 12000);

        // Auto-refresh stock price and data every 15 seconds
        setInterval(function () {
            if (currentSymbol) loadStockDetails(currentSymbol);
        }, 15000);
    });

})();
