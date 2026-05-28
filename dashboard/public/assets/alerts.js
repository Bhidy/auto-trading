/**
 * alerts.js
 * Manages tactical alert profiles, active thresholds, creation flows, and
 * ticking live AI signals feeds in English & Arabic.
 */
(function() {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';
    var alerts = [
        { id: 1, symbol: 'AAPL', type: 'price_gt', threshold: 195.00, enabled: true },
        { id: 2, symbol: 'NVDA', type: 'technical_ma', threshold: 950.00, enabled: true },
        { id: 3, symbol: 'TSLA', type: 'price_lt', threshold: 170.00, enabled: false },
        { id: 4, symbol: 'SPY', type: 'volume_gt', threshold: 100000000, enabled: true }
    ];

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
            alerts_tag: 'Signal Control Center',
            alerts_title: 'AI & Market Alerts',
            form_title: 'Deploy Smart Alert',
            label_symbol: 'Asset Symbol',
            label_type: 'Alert Type',
            label_val: 'Threshold Value',
            btn_deploy: 'Deploy Alert',
            feed_title: 'Neural Signals Feed',
            live_label: 'LIVE STREAM',
            active_title: 'Active Tactical Alerts',
            col_sym: 'Symbol',
            col_type: 'Condition Type',
            col_val: 'Threshold',
            col_status: 'Status',
            col_action: 'Action',
            btn_delete: 'Delete',
            opt_p_gt: 'Price crosses above ($)',
            opt_p_lt: 'Price crosses below ($)',
            opt_v_gt: 'Volume spike above (Shares)',
            opt_sentiment: 'AI news sentiment negative',
            opt_earnings: 'Earnings release announcement',
            opt_ma: 'Technical MA(20/50) crossover',
            opt_ai_signal: 'AI Neural Buy/Sell Signal',
            
            // Types short texts
            type_price_gt: 'Price >',
            type_price_lt: 'Price <',
            type_volume_gt: 'Volume >',
            type_news_sentiment: 'Negative Sentiment',
            type_earnings: 'Earnings Announcement',
            type_technical_ma: 'MA(20/50) Crossover',
            type_ai_signal: 'AI Neural Trade Signal'
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
            alerts_tag: 'مركز التحكم بالإشارات الفورية',
            alerts_title: 'تنبيهات السوق والذكاء الاصطناعي',
            form_title: 'نشر تنبيه ذكي',
            label_symbol: 'رمز الأصل المالي',
            label_type: 'نوع التنبيه',
            label_val: 'قيمة العتبة التنبيهية',
            btn_deploy: 'تفعيل التنبيه',
            feed_title: 'ملخص الإشارات العصبية الحية',
            live_label: 'بث حي',
            active_title: 'التنبيهات التكتيكية النشطة',
            col_sym: 'رمز السهم',
            col_type: 'حالة التنبيه المعينة',
            col_val: 'القيمة/الحد',
            col_status: 'الحالة',
            col_action: 'إجراء',
            btn_delete: 'حذف',
            opt_p_gt: 'تجاوز السعر للأعلى ($)',
            opt_p_lt: 'تجاوز السعر للأسفل ($)',
            opt_v_gt: 'ارتفاع حجم التداول فوق (سهم)',
            opt_sentiment: 'مشاعر الأخبار سلبية بالذكاء',
            opt_earnings: 'إعلان نتائج الأرباح الربعية',
            opt_ma: 'تقاطع المتوسطات المتحركة MA',
            opt_ai_signal: 'إشارات البيع/الشراء العصبية',
            
            // Types short texts
            type_price_gt: 'السعر أعلى من',
            type_price_lt: 'السعر أقل من',
            type_volume_gt: 'حجم التداول أكبر من',
            type_news_sentiment: 'مشاعر سلبية بالذكاء',
            type_earnings: 'إعلان الأرباح الربعية',
            type_technical_ma: 'تقاطع MA(20/50)',
            type_ai_signal: 'إشارة بيع/شراء ذكية'
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
        
        // Re-render select options
        var select = document.getElementById('alertTypeSelect');
        if (select) {
            Array.from(select.options).forEach(function(opt) {
                var key = opt.getAttribute('data-key');
                if (dict[key]) opt.textContent = dict[key];
            });
        }

        renderAlertsTable();
    }

    function renderAlertsTable() {
        var body = document.getElementById('activeAlertsBody');
        var dict = T[lang] || T.en;
        var btnDelText = dict.btn_delete || 'Delete';

        if (alerts.length === 0) {
            body.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--muted);">${lang === 'ar' ? 'لا توجد تنبيهات مفعلة حالياً.' : 'No active alerts deployed.'}</td></tr>`;
            return;
        }

        body.innerHTML = alerts.map(function(item) {
            var typeLabel = dict['type_' + item.type] || item.type;
            var isChecked = item.enabled ? 'checked' : '';
            var valFormatted = typeof item.threshold === 'number' && item.type.indexOf('volume') === -1
                ? '$' + item.threshold.toFixed(2)
                : item.threshold.toLocaleString();

            return `<tr id="alert-row-${item.id}">
                <td style="font-weight: 800; font-family: var(--pf-mono);">${item.symbol}</td>
                <td>${typeLabel}</td>
                <td style="font-family: var(--pf-mono);">${valFormatted}</td>
                <td>
                    <label class="switch-toggle">
                        <input type="checkbox" ${isChecked} onchange="toggleAlert(${item.id}, this.checked)">
                        <span class="slider-round"></span>
                    </label>
                </td>
                <td>
                    <button class="btn-delete" onclick="deleteAlert(${item.id})">${btnDelText}</button>
                </td>
            </tr>`;
        }).join('');
    }

    // Expose helpers globally so they function in inline html callbacks
    window.toggleAlert = function(id, checked) {
        var alertItem = alerts.find(function(a) { return a.id === id; });
        if (alertItem) {
            alertItem.enabled = checked;
            console.log('Alert id ' + id + ' status toggled to: ' + checked);
        }
    };

    window.deleteAlert = function(id) {
        alerts = alerts.filter(function(a) { return a.id !== id; });
        renderAlertsTable();
    };

    function addAlert() {
        var symbolInput = document.getElementById('alertSymbolInput');
        var typeSelect = document.getElementById('alertTypeSelect');
        var thresholdInput = document.getElementById('alertThresholdInput');

        var sym = symbolInput.value.trim().toUpperCase();
        var type = typeSelect.value;
        var threshold = parseFloat(thresholdInput.value) || 0;

        if (!sym) {
            alert(lang === 'ar' ? 'يرجى إدخال رمز أصل صالح.' : 'Please enter a valid asset symbol.');
            return;
        }

        var newAlert = {
            id: Date.now(),
            symbol: sym,
            type: type,
            threshold: threshold,
            enabled: true
        };

        alerts.push(newAlert);
        renderAlertsTable();

        // Clear input or reset
        symbolInput.value = '';
    }

    /* ─── Neural Signals Feed Simulator ─────────────────────────────────── */
    var feedLogs = [];
    var feedContainer = null;

    var mockSignals = [
        { sym: 'NVDA', type: 'RSI Bullish', desc: 'RSI(14) crosses above 30, signaling heavy oversold capitulation recovery.', cls: 'success' },
        { sym: 'AAPL', type: 'Volume Spike', desc: 'Volume spikes 140% above 20-day moving average on key support level.', cls: 'success' },
        { sym: 'TSLA', type: 'MACD Bearish', desc: 'MACD line crosses below signal line on 4H chart, warnings of technical correction.', cls: 'danger' },
        { sym: 'SPY', type: 'S&P 500 Drop', desc: 'Price crossed below 50-day SMA, accelerating short-term liquidations.', cls: 'danger' },
        { sym: 'MSFT', type: 'AI Buy Signal', desc: 'Neural core triggers BULLISH momentum cross matching institutional flow.', cls: 'success' },
        { sym: 'META', type: 'Earnings Pre-gap', desc: 'Options pricing reflects 8.2% expected move ahead of earnings disclosure.', cls: 'success' }
    ];

    var mockSignalsAr = [
        { sym: 'NVDA', type: 'زخم RSI إيجابي', desc: 'مؤشر القوة النسبية يتجاوز ٣٠ صعوداً، مشيراً إلى خروج من ذروة البيع.', cls: 'success' },
        { sym: 'AAPL', type: 'ارتفاع في الحجم', desc: 'حجم التداول يرتفع بنسبة ١٤٠٪ فوق متوسط ٢٠ يوماً عند الدعم الفني.', cls: 'success' },
        { sym: 'TSLA', type: 'MACD سلبي', desc: 'خط الماكد يتقاطع هبوطاً مع خط الإشارة على إطار ٤ ساعات المالي.', cls: 'danger' },
        { sym: 'SPY', type: 'كسر دعم S&P', desc: 'مؤشر S&P 500 يكسر هبوطاً المتوسط المتحرك البسيط لـ ٥٠ يوماً.', cls: 'danger' },
        { sym: 'MSFT', type: 'شراء عصبوني', desc: 'الشبكة العصبية ترصد زخم شراء مؤسسي ضخم وتفوق فوري في التدفقات.', cls: 'success' },
        { sym: 'META', type: 'فجوة الأرباح المتوقعة', desc: 'تسعير عقود الخيارات يشير إلى حركة حادة متوقعة بنسبة ٨.٢٪ قبيل الإعلان.', cls: 'success' }
    ];

    function pushSignal() {
        if (!feedContainer) return;
        
        var pool = lang === 'ar' ? mockSignalsAr : mockSignals;
        var r = pool[Math.floor(Math.random() * pool.length)];
        var now = new Date();
        var timeStr = now.toLocaleTimeString(lang === 'ar' ? 'ar-EG' : 'en-US', { hour12: false });

        var card = document.createElement('div');
        card.className = 'live-feed-card ' + r.cls;
        card.innerHTML = `
            <div>
                <span style="font-weight:800; color:var(--ink); font-size:0.8rem; margin-inline-end: 0.5rem;">${r.sym}</span>
                <span style="font-size:0.7rem; font-weight:700; color:var(--teal); text-transform:uppercase;">${r.type}</span>
                <p style="margin-top:0.35rem; color:var(--muted); font-size:0.72rem;">${r.desc}</p>
            </div>
            <div style="font-size:0.65rem; color:var(--muted); white-space:nowrap; text-align:right;">
                ${timeStr}
            </div>
        `;

        feedContainer.insertBefore(card, feedContainer.firstChild);

        // Limit count to 5
        if (feedContainer.children.length > 5) {
            feedContainer.removeChild(feedContainer.lastChild);
        }
    }

    /* ─── Initialization ────────────────────────────────────────────────── */
    document.addEventListener('DOMContentLoaded', function() {
        feedContainer = document.getElementById('neuralSignalsFeed');
        
        // Bind submit btn
        document.getElementById('createAlertBtn').addEventListener('click', addAlert);

        // Bind language toggle
        document.getElementById('langToggle').addEventListener('click', function() {
            applyLang(lang === 'ar' ? 'en' : 'ar');
        });

        applyLang(lang);

        // Push some initial signals
        for (var i = 0; i < 3; i++) {
            pushSignal();
        }

        // Ticking signals feed every 5 seconds
        setInterval(pushSignal, 5000);

        // Dynamic marquee
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
