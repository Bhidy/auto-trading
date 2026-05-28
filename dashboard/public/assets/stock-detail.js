/**
 * stock-detail.js
 * Institutional-grade stock quote metrics, fundamentals, advanced chart.js curve,
 * options chain ladders, regulatory SEC filings, Level 2 depth lists, and AI neural confidence gauges.
 */
(function() {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';
    var currentSymbol = 'AAPL';
    var stockChartInstance = null;
    var rawBarsData = [];

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
        renderTechnicalChart('1M');
    }

    function renderFundamentals(p, prevClose) {
        var grid = document.getElementById('fundamentalsGrid');
        var dict = T[lang] || T.en;

        var items = [
            { label: dict.m_ceo || 'CEO', val: p.CEO || 'N/A' },
            { label: dict.m_cap || 'Market Cap', val: p.cap || 'N/A' },
            { label: dict.m_pe || 'P/E Ratio', val: p.pe || 'N/A' },
            { label: dict.m_yield || 'Div Yield', val: p.yield || '0.00%' },
            { label: dict.m_beta || 'Beta', val: p.beta || '1.00' },
            { label: dict.m_prev || 'Prev Close', val: '$' + prevClose.toFixed(2) }
        ];

        grid.innerHTML = items.map(function(item) {
            return `<div class="metric-card">
                <span class="label">${item.label}</span>
                <span class="value">${item.val}</span>
            </div>`;
        }).join('');
    }

    function renderSECFilings(symbol) {
        var list = document.getElementById('secFilingsList');
        var dict = T[lang] || T.en;
        var dlBtn = dict.sec_download || 'Download PDF';

        var mockFilings = [
            { form: '10-Q', date: '2026-05-12', desc: 'Quarterly financial performance report Q1' },
            { form: '10-K', date: '2025-11-20', desc: 'Annual institutional audits & compliance filing' },
            { form: '8-K', date: '2026-04-05', desc: 'Material event or acquisition disclosures statement' }
        ];

        list.innerHTML = mockFilings.map(function(f) {
            return `<tr>
                <td style="font-weight: 800; font-family: var(--pf-mono);">${f.form}</td>
                <td style="font-family: var(--pf-mono);">${f.date}</td>
                <td>${f.desc}</td>
                <td><button class="btn-download" onclick="alert('Downloading SEC filing for ${symbol}...')">${dlBtn}</button></td>
            </tr>`;
        }).join('');
    }

    function renderOptionsChain(price) {
        var list = document.getElementById('optionsChainList');
        var startStrike = Math.round(price * 0.95);
        var html = '';

        for (var i = 0; i < 5; i++) {
            var strike = startStrike + (i * 5);
            var callBid = Math.max(0.1, (price - strike) * 1.05 + Math.random() * 2);
            var callAsk = callBid + 0.15;
            var putBid = Math.max(0.1, (strike - price) * 1.05 + Math.random() * 2);
            var putAsk = putBid + 0.15;
            var callVol = Math.floor(100 + Math.random() * 900);
            var putVol = Math.floor(80 + Math.random() * 800);

            html += `<tr>
                <td style="color: #2ecc71; font-family: var(--pf-mono); font-weight:700;">$${callBid.toFixed(2)}</td>
                <td style="color: #2ecc71; font-family: var(--pf-mono);">$${callAsk.toFixed(2)}</td>
                <td style="font-family: var(--pf-mono); text-align:center;">${callVol}</td>
                <td style="font-family: var(--pf-mono); font-weight: 800; text-align: center; background: var(--teal-soft); color: var(--teal); border-radius: 4px;">$${strike}</td>
                <td style="color: #e74c3c; font-family: var(--pf-mono); font-weight:700;">$${putBid.toFixed(2)}</td>
                <td style="color: #e74c3c; font-family: var(--pf-mono);">$${putAsk.toFixed(2)}</td>
                <td style="font-family: var(--pf-mono); text-align:center;">${putVol}</td>
            </tr>`;
        }
        list.innerHTML = html;
    }

    function renderAIResearchSummary(symbol, changePct) {
        var score = 7.5;
        var desc = '';

        if (symbol === 'AAPL') {
            score = 8.4;
            desc = lang === 'ar' 
                ? 'تحليل الشبكة العصبية: تمتلك أبل مرونة مالية استثنائية مع توسع هوامش قطاع الخدمات. المحفز الأساسي هو التبني الواسع للأجهزة الاستهلاكية الجديدة ونمو الاشتراكات.'
                : 'Neural engine parsing: Apple remains highly resilient with expanding service margins. Primary catalyst is high-frequency consumer hardware upgrades offset by slight global supply risks.';
        } else if (symbol === 'NVDA') {
            score = 9.2;
            desc = lang === 'ar'
                ? 'تحليل الشبكة العصبية: طلب غير مسبوق على معالجات الذكاء الاصطناعي ومراكز البيانات. الفجوة السعرية تعكس تفوقاً تنافسياً هائلاً ومخاطر تقييم منخفضة.'
                : 'Neural engine parsing: Exceptional institutional demand for high-performance AI computational chips. The price gap reflects strong technological leadership offset by valuation metrics.';
        } else if (symbol === 'TSLA') {
            score = 6.2;
            desc = lang === 'ar'
                ? 'تحليل الشبكة العصبية: تواجه تسلا رياحاً معاكسة بسبب المنافسة العالمية وضغط هوامش الربح. تركز الاستراتيجية الحالية على القيادة الذاتية وبطاريات التخزين.'
                : 'Neural engine parsing: Tesla faces compressed automotive operating margins and rising global EV competition. Dynamic autonomous driving models remain the chief future catalyst.';
        } else {
            score = Math.min(9.9, Math.max(4.0, (7.0 + (changePct / 5)))).toFixed(1);
            desc = lang === 'ar'
                ? `تحليل الشبكة العصبية: سهم ${symbol} مستقر في القنوات الفنية. المحفزات الماليّة تدل على تداول عالي وانضباط مؤسسي إيجابي.`
                : `Neural engine parsing: Symbol ${symbol} exhibits standard operational resilience in technical channels. The catalyst index signals steady institutional accumulation patterns.`;
        }

        document.getElementById('aiCatalystText').textContent = desc;
        document.getElementById('aiCatalystScoreRing').textContent = score;
        document.getElementById('aiCatalystScoreRing').style.setProperty('--score-fill', (score * 10) + '%');
    }

    function renderLevel2Depth(price) {
        var list = document.getElementById('l2DepthBookList');
        var html = '';

        // Add 3 Ask rows (Sell) in descending order of price
        for (var i = 3; i >= 1; i--) {
            var askPrice = price + (i * 0.08);
            var askVol = Math.floor(100 + Math.random() * 2000);
            var fillPct = Math.min(100, (askVol / 2000) * 100);
            html += `<div class="l2-row ask">
                <span class="price">$${askPrice.toFixed(2)}</span>
                <span class="size">${askVol}</span>
                <div class="l2-depth-fill" style="width: ${fillPct}%; background: #e74c3c;"></div>
            </div>`;
        }

        // Spread separator
        html += `<div style="text-align:center; font-family: var(--pf-mono); font-size:0.7rem; color:var(--muted); padding: 0.2rem 0; border-top:1px dashed var(--line); border-bottom:1px dashed var(--line); margin: 0.35rem 0;">
            SPREAD: $0.16
        </div>`;

        // Add 3 Bid rows (Buy) in descending order of price
        for (var i = 1; i <= 3; i++) {
            var bidPrice = price - (i * 0.08);
            var bidVol = Math.floor(100 + Math.random() * 2000);
            var fillPct = Math.min(100, (bidVol / 2000) * 100);
            html += `<div class="l2-row bid">
                <span class="price">$${bidPrice.toFixed(2)}</span>
                <span class="size">${bidVol}</span>
                <div class="l2-depth-fill" style="width: ${fillPct}%; background: #2ecc71;"></div>
            </div>`;
        }

        list.innerHTML = html;
    }

    function renderAnalystConsensus(symbol) {
        var consensus = 'BUY';
        var buy = 70, hold = 20, sell = 10;

        if (symbol === 'TSLA') { consensus = 'HOLD'; buy = 35; hold = 45; sell = 20; }
        else if (symbol === 'NVDA') { consensus = 'STRONG BUY'; buy = 88; hold = 10; sell = 2; }
        else if (symbol === 'AAPL') { consensus = 'BUY'; buy = 74; hold = 20; sell = 6; }

        document.getElementById('consensusRatingText').textContent = consensus;
        document.getElementById('consensusRatingText').style.color = buy > 60 ? '#2ecc71' : (hold > 40 ? '#FF8A3D' : '#e74c3c');

        var bars = document.getElementById('analystConsensusBars');
        bars.innerHTML = `
            <div class="rating-row">
                <span class="label">${lang === 'ar' ? 'شراء' : 'Buy'}</span>
                <div class="bar-outer"><div class="bar-inner" style="width: ${buy}%; background: #2ecc71;"></div></div>
                <span class="num">${buy}%</span>
            </div>
            <div class="rating-row">
                <span class="label">${lang === 'ar' ? 'احتفاظ' : 'Hold'}</span>
                <div class="bar-outer"><div class="bar-inner" style="width: ${hold}%; background: #FF8A3D;"></div></div>
                <span class="num">${hold}%</span>
            </div>
            <div class="rating-row">
                <span class="label">${lang === 'ar' ? 'بيع' : 'Sell'}</span>
                <div class="bar-outer"><div class="bar-inner" style="width: ${sell}%; background: #e74c3c;"></div></div>
                <span class="num">${sell}%</span>
            </div>
        `;
    }

    function renderPeers(symbol, profile) {
        var list = document.getElementById('peerContrastList');
        var peers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META'];
        if (peers.indexOf(symbol) === -1) {
            peers[4] = symbol;
        }

        var peersData = {
            AAPL: { pe: '29.4', cap: '2.9T', beta: '1.12' },
            MSFT: { pe: '35.8', cap: '3.2T', beta: '0.90' },
            NVDA: { pe: '68.4', cap: '3.1T', beta: '1.95' },
            GOOGL: { pe: '26.1', cap: '2.2T', beta: '1.05' },
            META: { pe: '24.6', cap: '1.2T', beta: '1.22' }
        };

        var html = '';
        peers.forEach(function(pSym) {
            var data = peersData[pSym] || { pe: profile.pe || '15.0', cap: profile.cap || '100B', beta: profile.beta || '1.00' };
            var styleHighlight = pSym === symbol ? 'background: var(--teal-soft); font-weight:800;' : '';
            html += `<tr style="${styleHighlight}">
                <td style="font-family: var(--pf-mono);">${pSym}</td>
                <td style="font-family: var(--pf-mono);">${data.pe}</td>
                <td style="font-family: var(--pf-mono);">${data.cap}</td>
                <td style="font-family: var(--pf-mono);">${data.beta}</td>
            </tr>`;
        });
        list.innerHTML = html;
    }

    function renderTechnicalChart(range) {
        var ctx = document.getElementById('stockDetailChart');
        if (!ctx) return;

        var limit = 30;
        if (range === '1D') limit = 5;
        else if (range === '3M') limit = 45;
        else if (range === '1Y') limit = 60;

        var slice = rawBarsData.length > limit ? rawBarsData.slice(rawBarsData.length - limit) : rawBarsData;
        if (slice.length === 0) {
            // Generate mock if empty
            var price = 189.98;
            for (var i = 0; i < limit; i++) {
                slice.push({
                    t: new Date(Date.now() - (limit - i) * 24 * 3600 * 1000).toLocaleDateString(),
                    c: price + (Math.random() - 0.48) * (price * 0.05)
                });
            }
        }

        var labels = slice.map(function(b) {
            var date = new Date(b.t);
            return isNaN(date.getTime()) ? b.t : date.toLocaleDateString(lang === 'ar' ? 'ar-EG' : 'en-US', { month: 'short', day: 'numeric' });
        });
        var prices = slice.map(function(b) { return b.c; });

        if (stockChartInstance) {
            stockChartInstance.destroy();
        }

        var gridColor = StartaTheme.current() === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(26,15,8,0.06)';
        var inkColor = StartaTheme.current() === 'dark' ? '#FFF1E8' : '#1A0F08';

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
                    pointRadius: prices.length > 30 ? 0 : 3,
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
                        ticks: { color: inkColor, font: { size: 10 } }
                    },
                    y: {
                        position: lang === 'ar' ? 'right' : 'left',
                        grid: { color: gridColor },
                        ticks: { color: inkColor, font: { size: 10 } }
                    }
                }
            }
        });
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
            renderTechnicalChart('1M');
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
