/**
 * research.js
 * Drives the Neural Stock Analyst simulator, strategy hold rationales, and
 * circular consensus news sentiment radial rings in English & Arabic.
 */
(function() {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';

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
            research_tag: 'Neural Quant Intelligence',
            research_title: 'AI Research & Insights',
            box_title: 'Neural Stock Analyst',
            box_sub: 'Input asset symbol and run deep neural analysis for detailed catalysts splits, risk gauges, and target score.',
            btn_analyze: 'Analyze',
            out_confidence: 'NEURAL CONFIDENCE',
            out_catalysts: 'Growth Catalysts',
            out_risks: 'Identified Risk Indexes',
            strat_title: 'Active Bot Allocations Explanation',
            strat1_name: 'Self Improving Brain (Quant Neural)',
            strat1_style: 'CONVEX GROWTH',
            strat1_desc: 'Holds high-liquidity indexes and dominant tech shares (SPY, NVDA, AAPL). Automatically rotates allocations into cash or safe-havens upon detecting high-frequency market volume drop patterns.',
            strat2_name: 'Capitol Shadow (Legislative Copy)',
            strat2_style: 'SECTORIAL FLOW',
            strat2_desc: 'Emulates public congressional purchase filings. Focuses tightly on government contracts pipelines, infrastructure spending beneficiaries, and technological semiconductor leaders (MSFT, NVDA).',
            strat3_name: 'Cautious Sniper (Momentum Swing)',
            strat3_style: 'SCALPING PROFILE',
            strat3_desc: 'Uses precision indicators to catch short momentum curves. It deploys quick entry thresholds and algorithmic trailing-stops (tight 2%) to scalp quick price deviations on liquid indices.',
            sentiment_title: 'Consensus News Sentiment',
            sentiment_sub: 'Aggregated global sentiment ratio parsed from over 2,000 news articles daily.',
            sent_bullish: 'Bullish Sentiment',
            sent_neutral: 'Neutral Sentiment',
            sent_bearish: 'Bearish Sentiment',
            disclaimer_box: '<strong>NOT FINANCIAL ADVICE & METHODOLOGY DISCLOSURE</strong><br><br>All information and automated research alerts published on Auto Trading are provided strictly for educational and data logging purposes. Auto Trading is a software utility and not a registered broker-dealer, financial advisor, or asset manager. Real-time connections are directed to Alpaca Paper Trading accounts. Investing in capital instruments involves high risk and possible loss. Neural AI scores represent mathematical evaluations derived from historical prices and simulated sentiment, and should not be used as investment advice.'
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
            research_tag: 'الذكاء الكمي الاصطناعي',
            research_title: 'الأبحاث والذكاء الاصطناعي',
            box_title: 'محلل الأسهم العصبي الذكي',
            box_sub: 'أدخل رمز السهم لتشغيل تحليل الشبكة العصبية الشامل لكشف المحفزات الماليّة، مؤشرات المخاطر، ودرجة تقييم السهم الفورية.',
            btn_analyze: 'حلل الآن',
            out_confidence: 'مؤشر ثقة الشبكة العصبية',
            out_catalysts: 'محفزات وعوامل النمو الرئيسية',
            out_risks: 'مؤشرات المخاطر التي تم رصدها',
            strat_title: 'تفسير وتبرير توزيع البوتات الحالي',
            strat1_name: 'الدماغ ذاتي التحسين (الكمي العصبي)',
            strat1_style: 'نمو محدب للأسهم الكبرى',
            strat1_desc: 'يحتفظ بالمؤشرات عالية السيولة والأسهم التكنولوجية المهيمنة (SPY, NVDA, AAPL). يدير المحفظة بالتحول للنقدية تلقائياً عند استشعار انخفاضات السيولة.',
            strat2_name: 'بوت ظل الكابيتول (نسخ صفقات الكونجرس)',
            strat2_style: 'تدفق قطاعي ذكي',
            strat2_desc: 'يحاكي صفقات الشراء المودعة من السياسيين وصناع القرار. يركز بدقة على قطاعات العقود الحكومية، المستفيدين من البنية التحتية، ورواد التكنولوجيا.',
            strat3_name: 'بوت القناص الحذر (تداول الزخم والسكالبينج)',
            strat3_style: 'ملف سكالبينج حذر',
            strat3_desc: 'يستخدم مؤشرات زخم دقيقة ومقاييس زمنية قصيرة. يفعل التداول بنسب ضيقة ووقف خسارة متحرك (٢٪ كحد أقصى) لتجنب الانعكاسات الحادة في السوق.',
            sentiment_title: 'مشاعر وتحليلات الأخبار الإجمالية',
            sentiment_sub: 'نسب التقييم المجمعة لأكثر من ٢,٠٠٠ مقال وصحيفة مالية عالمية يومياً.',
            sent_bullish: 'مشاعر إيجابية (Bullish)',
            sent_neutral: 'مشاعر محايدة (Neutral)',
            sent_bearish: 'مشاعر سلبية (Bearish)',
            disclaimer_box: '<strong>إخلاء مسؤولية تنظيمي - الأبحاث ليست نصيحة مالية</strong><br><br>جميع التقارير وأبحاث الذكاء الاصطناعي والتحليلات المنشورة في Auto Trading هي لأغراض تعليمية وإحصائية وتوثيقية بحتة. المنصة هي أداة برمجية وليست مستشاراً مالياً معتمداً أو وسيطاً مسجلاً. الربط المالي الفوري موجه لحسابات التداول التجريبي (Alpaca Paper). ينطوي الاستثمار بالأسهم على مخاطر مرتفعة. درجات التقييم العصبية تعتمد على دراسات رياضية للبيانات التاريخية ولا تمثل ضمانات للمستقبل.'
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
                el.innerHTML = dict[k];
            }
        });

        // If analysis box is active, re-analyze to refresh text
        var outputBox = document.getElementById('analysisOutputBox');
        if (outputBox && outputBox.style.display === 'block') {
            triggerAnalysis();
        }
    }

    function triggerAnalysis() {
        var input = document.getElementById('researchSymbolInput');
        var sym = input.value.trim().toUpperCase() || 'NVDA';

        var outputBox = document.getElementById('analysisOutputBox');
        outputBox.style.display = 'block';
        document.getElementById('outSymbolName').textContent = sym;
        document.getElementById('outCompName').textContent = 'Loading...';
        document.getElementById('outScore').textContent = '—';
        document.getElementById('outCatalystsText').innerHTML = '';
        document.getElementById('outRisksText').innerHTML = '';

        Promise.all([
            fetch('/api/portfolio/portfolio_1/details').then(function(r) { return r.json(); }),
            fetch('/api/stock/' + sym + '/details').then(function(r) { return r.json(); }),
            fetch('/api/market/bars/' + sym + '?timeframe=1Day&limit=30').then(function(r) { return r.json(); })
        ]).then(function(results) {
            var portfolioData = results[0];
            var stockData = results[1];
            var bars = results[2] || [];

            var signals = (portfolioData.signals && portfolioData.signals.signals) || [];
            var matched = signals.find(function(s) { return s.symbol === sym; });
            var profile = stockData.profile || {};

            document.getElementById('outCompName').textContent = profile.name || sym;

            if (matched) {
                var scoreVal = ((matched.score || 0) * 10).toFixed(1);
                document.getElementById('outScore').textContent = scoreVal + ' / 10';
                var catalysts = (matched.reasons || []).filter(function(r) {
                    return r.toLowerCase().indexOf('bullish') !== -1 || r.toLowerCase().indexOf('uptrend') !== -1 || r.toLowerCase().indexOf('positive') !== -1 || r.toLowerCase().indexOf('above') !== -1;
                });
                var risks = (matched.reasons || []).filter(function(r) {
                    return r.toLowerCase().indexOf('bearish') !== -1 || r.toLowerCase().indexOf('overbought') !== -1 || r.toLowerCase().indexOf('negative') !== -1 || r.toLowerCase().indexOf('below') !== -1;
                });
                if (catalysts.length === 0 && risks.length === 0) {
                    catalysts = matched.reasons.slice(0, Math.ceil(matched.reasons.length / 2));
                    risks = matched.reasons.slice(Math.ceil(matched.reasons.length / 2));
                }
                document.getElementById('outCatalystsText').innerHTML = catalysts.map(function(c, i) { return (i + 1) + '. ' + c; }).join('<br>') || 'No bullish catalysts detected.';
                document.getElementById('outRisksText').innerHTML = risks.map(function(r, i) { return (i + 1) + '. ' + r; }).join('<br>') || 'No bearish risks detected.';

                var ind = matched.indicators || {};
                var extra = '';
                if (ind.rsi14) extra += 'RSI(14): ' + ind.rsi14.toFixed(1) + ' | ';
                if (ind.atr_pct) extra += 'ATR%: ' + ind.atr_pct.toFixed(2) + '% | ';
                if (ind.momentum_1m !== undefined) extra += '1M: ' + (ind.momentum_1m >= 0 ? '+' : '') + ind.momentum_1m.toFixed(1) + '%';
                if (extra) {
                    document.getElementById('outRisksText').innerHTML += '<br><br><span style="color:var(--teal); font-family:var(--pf-mono); font-size:0.72rem;">' + extra + '</span>';
                }
            } else {
                var priceInfo = '';
                if (bars.length > 1) {
                    var first = bars[0].c;
                    var last = bars[bars.length - 1].c;
                    var ret = ((last - first) / first * 100).toFixed(2);
                    priceInfo = 'Price: $' + last.toFixed(2) + ' | 30D Return: ' + (ret >= 0 ? '+' : '') + ret + '%';
                }
                document.getElementById('outScore').textContent = 'N/A';
                document.getElementById('outCatalystsText').innerHTML = 'No active trading signal for ' + sym + '. Symbol not in current watchlist.' + (priceInfo ? '<br><br><span style="color:var(--teal); font-family:var(--pf-mono); font-size:0.72rem;">' + priceInfo + '</span>' : '');
                document.getElementById('outRisksText').innerHTML = 'Add ' + sym + ' to the watchlist to generate AI analysis signals.';
            }
        }).catch(function() {
            document.getElementById('outCompName').textContent = sym;
            document.getElementById('outScore').textContent = 'Error';
            document.getElementById('outCatalystsText').innerHTML = 'Unable to fetch analysis data. Check API connection.';
            document.getElementById('outRisksText').innerHTML = '';
        });
    }

    /* ─── Initialization ────────────────────────────────────────────────── */
    document.addEventListener('DOMContentLoaded', function() {
        // Bind analyze click
        document.getElementById('researchAnalyzeBtn').addEventListener('click', triggerAnalysis);

        // Bind enter key
        document.getElementById('researchSymbolInput').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') triggerAnalysis();
        });

        // Bind language toggle
        document.getElementById('langToggle').addEventListener('click', function() {
            applyLang(lang === 'ar' ? 'en' : 'ar');
        });

        applyLang(lang);

        // Trigger default analysis NVDA
        triggerAnalysis();

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
    });

})();
