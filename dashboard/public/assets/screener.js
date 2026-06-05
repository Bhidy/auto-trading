(function () {
    'use strict';

    var T = {
        en: {
            scr_title: 'Asset Screener', scr_subtitle: 'Browse and filter all tradable assets — stocks, ETFs, crypto, and options',
            nav_home: 'Home', nav_portfolios: 'Portfolios', nav_pf_list: 'Portfolio List',
            nav_pf1: 'Improving Brain', nav_pf2: 'Capitol Shadow', nav_pf3: 'Cautious Sniper',
            nav_market_pulse: 'Market Pulse', nav_trading: 'Trading', nav_orders: 'Orders',
            nav_crypto: 'Crypto Terminal', nav_options: 'Options Lab', nav_screener: 'Screener',
            nav_history: 'Account History', nav_alerts: 'Alerts', nav_research: 'Research & AI', nav_settings: 'Settings',
            th_symbol: 'Symbol', th_name: 'Name', th_class: 'Class', th_exchange: 'Exchange',
            th_status: 'Status', th_tradable: 'Tradable', th_fractionable: 'Fractional', th_shortable: 'Shortable',
            th_etb: 'Easy Borrow', th_marginable: 'Marginable', th_margin_req: 'Margin Req', th_min_order: 'Min Order', th_min_increment: 'Min Increment',
            class_equity: 'US Equity', class_crypto: 'Crypto', btn_search: 'Search',
            scr_click_search: 'Click Search to load assets',
            wl_title: 'Alpaca Watchlists', btn_new_wl: '+ New Watchlist', wl_empty: 'Select a portfolio to view watchlists',
            wl_create: 'Create Watchlist', wl_name: 'Name', wl_symbols: 'Symbols (comma separated)',
            btn_cancel: 'Cancel', btn_create: 'Create',
            stat_showing: 'Showing', stat_of: 'of', stat_assets: 'assets'
        },
        ar: {
            scr_title: 'فرز الأصول', scr_subtitle: 'تصفح وفلترة جميع الأصول القابلة للتداول — أسهم وصناديق وكريبتو وخيارات',
            nav_home: 'الرئيسية', nav_portfolios: 'المحافظ', nav_pf_list: 'قائمة المحافظ',
            nav_pf1: 'العقل الذاتي', nav_pf2: 'ظل الكابيتول', nav_pf3: 'القناص الحذر',
            nav_market_pulse: 'نبض السوق', nav_trading: 'التداول', nav_orders: 'الأوامر',
            nav_crypto: 'محطة الكريبتو', nav_options: 'مختبر الخيارات', nav_screener: 'الفرز',
            nav_history: 'سجل الحساب', nav_alerts: 'التنبيهات', nav_research: 'البحث والذكاء', nav_settings: 'الإعدادات',
            th_symbol: 'الرمز', th_name: 'الاسم', th_class: 'الفئة', th_exchange: 'البورصة',
            th_status: 'الحالة', th_tradable: 'قابل للتداول', th_fractionable: 'كسري', th_shortable: 'بيع على المكشوف',
            th_etb: 'سهل الاقتراض', th_marginable: 'هامشي', th_margin_req: 'متطلب الهامش', th_min_order: 'حد أدنى', th_min_increment: 'أدنى زيادة',
            class_equity: 'أسهم أمريكية', class_crypto: 'كريبتو', btn_search: 'بحث',
            scr_click_search: 'اضغط بحث لتحميل الأصول',
            wl_title: 'قوائم المراقبة', btn_new_wl: '+ قائمة جديدة', wl_empty: 'اختر محفظة لعرض القوائم',
            wl_create: 'إنشاء قائمة مراقبة', wl_name: 'الاسم', wl_symbols: 'الرموز (مفصولة بفاصلة)',
            btn_cancel: 'إلغاء', btn_create: 'إنشاء',
            stat_showing: 'عرض', stat_of: 'من', stat_assets: 'أصل'
        }
    };

    var lang = document.documentElement.lang || 'en';
    var allAssets = [];
    var wlPfId = '';

    function t(k) { return (T[lang] && T[lang][k]) || (T.en[k]) || k; }
    function $(id) { return document.getElementById(id); }
    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

    function applyLang() {
        lang = document.documentElement.lang || 'en';
        document.querySelectorAll('[data-key]').forEach(function (el) {
            var k = el.getAttribute('data-key');
            if (T[lang] && T[lang][k]) el.textContent = T[lang][k];
        });
    }

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

    function badge(val, yesClass, noClass) {
        if (val === true || val === 'true') return '<span class="scr-badge ' + yesClass + '">Yes</span>';
        if (val === false || val === 'false') return '<span class="scr-badge ' + noClass + '">No</span>';
        return '—';
    }

    async function loadAssets() {
        var cls = $('filterClass').value;
        var status = $('filterStatus').value;
        var exchange = $('filterExchange').value;
        var tbody = $('scrTableBody');
        tbody.innerHTML = '<tr><td colspan="13" class="scr-load">Loading assets...</td></tr>';

        var url = '/api/assets?status=' + status + '&asset_class=' + cls;
        if (exchange) url += '&exchange=' + exchange;

        try {
            var resp = await fetch(url);
            allAssets = await resp.json();
            if (!Array.isArray(allAssets)) allAssets = [];
        } catch (e) {
            allAssets = [];
        }
        filterAndRender();
    }

    function filterAndRender() {
        var query = $('searchInput').value.toUpperCase().trim();
        var filtered = allAssets;
        if (query) {
            filtered = allAssets.filter(function (a) {
                return (a.symbol || '').toUpperCase().indexOf(query) !== -1 || (a.name || '').toUpperCase().indexOf(query) !== -1;
            });
        }
        var showing = Math.min(filtered.length, 500);
        $('scrStats').innerHTML = '<span class="scr-stat">' + t('stat_showing') + ' <strong>' + showing + '</strong> ' + t('stat_of') + ' <strong>' + filtered.length + '</strong> ' + t('stat_assets') + '</span>';

        var tbody = $('scrTableBody');
        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="13" class="scr-empty">No assets found</td></tr>';
            return;
        }
        var display = filtered.slice(0, 500);
        tbody.innerHTML = display.map(function (a) {
            var statusBadge = a.status === 'active' ? '<span class="scr-badge scr-badge--active">active</span>' : '<span class="scr-badge scr-badge--inactive">' + (a.status || '') + '</span>';
            return '<tr>' +
                '<td style="font-weight:700;color:var(--ink); display:flex; align-items:center; gap:0.45rem;"><a href="/stock-detail.html?symbol=' + (a.symbol || '') + '" style="color:var(--teal);text-decoration:none; display:inline-flex; align-items:center;">' +
                    getLogoHtml(a.symbol, 20) +
                    '<span>' + (a.symbol || '') + '</span>' +
                '</a></td>' +
                '<td style="font-family:Manrope,sans-serif;max-width:250px;overflow:hidden;text-overflow:ellipsis;">' + (a.name || '') + '</td>' +
                '<td>' + (a.class || a.asset_class || '') + '</td>' +
                '<td>' + (a.exchange || '') + '</td>' +
                '<td>' + statusBadge + '</td>' +
                '<td>' + badge(a.tradable, 'scr-badge--yes', 'scr-badge--no') + '</td>' +
                '<td>' + badge(a.fractionable, 'scr-badge--yes', 'scr-badge--no') + '</td>' +
                '<td>' + badge(a.shortable, 'scr-badge--yes', 'scr-badge--no') + '</td>' +
                '<td>' + badge(a.easy_to_borrow, 'scr-badge--yes', 'scr-badge--no') + '</td>' +
                '<td>' + badge(a.marginable, 'scr-badge--yes', 'scr-badge--no') + '</td>' +
                '<td>' + (a.maintenance_margin_requirement != null ? a.maintenance_margin_requirement + '%' : '—') + '</td>' +
                '<td>' + (a.min_order_size || '—') + '</td>' +
                '<td>' + (a.min_trade_increment || '—') + '</td>' +
                '</tr>';
        }).join('');
    }

    async function loadPortfolios() {
        try {
            var resp = await fetch('/api/portfolios');
            var data = await resp.json();
            var sel = $('wlPortfolio');
            sel.innerHTML = '';
            Object.entries(data).forEach(function (e) {
                var opt = document.createElement('option');
                opt.value = e[0]; opt.textContent = e[1].label || e[0];
                sel.appendChild(opt);
            });
            if (sel.options.length > 0) { wlPfId = sel.value; loadWatchlists(); }
        } catch (e) {}
    }

    async function loadWatchlists() {
        if (!wlPfId) return;
        var grid = $('wlGrid');
        try {
            var resp = await fetch('/api/portfolio/' + wlPfId + '/watchlists');
            var wls = await resp.json();
            if (!Array.isArray(wls) || wls.length === 0) {
                grid.innerHTML = '<div class="scr-empty">No watchlists found</div>';
                return;
            }
            grid.innerHTML = wls.map(function (wl) {
                var syms = (wl.assets || []).map(function (a) { return esc(a.symbol); }).join(', ') || 'Empty';
                var wlId = (wl.id || '').slice(0, 8);
                return '<div class="scr-wl-card">' +
                    '<div class="scr-wl-name">' + esc(wl.name || 'Unnamed') + '</div>' +
                    '<div class="scr-wl-symbols">' + syms + '</div>' +
                    '<div style="font-size:.68rem;color:var(--muted);margin-top:.3rem;">' + (wl.assets || []).length + ' symbols &middot; ID: ' + esc(wlId) + '</div>' +
                    '<div class="scr-wl-actions">' +
                    '<button class="pf-btn pf-btn--sm pf-btn--danger-ghost" onclick="window._deleteWl(\'' + esc(wl.id) + '\')">Delete</button>' +
                    '</div></div>';
            }).join('');
        } catch (e) {
            grid.innerHTML = '<div class="scr-empty">Error loading watchlists</div>';
        }
    }

    window._deleteWl = async function (wlId) {
        if (!confirm('Delete this watchlist?')) return;
        try {
            await fetch('/api/portfolio/' + wlPfId + '/watchlist/' + wlId, { method: 'DELETE' });
            loadWatchlists();
        } catch (e) {}
    };

    async function createWatchlist() {
        var name = $('wlName').value.trim();
        var symbols = $('wlSymbols').value.split(',').map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean);
        if (!name) return;
        try {
            await fetch('/api/portfolio/' + wlPfId + '/watchlists', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, symbols: symbols })
            });
            $('wlModal').classList.remove('active');
            $('wlName').value = '';
            $('wlSymbols').value = '';
            loadWatchlists();
        } catch (e) {}
    }

    function init() {
        applyLang();
        loadPortfolios();

        $('btnLoad').addEventListener('click', loadAssets);
        $('searchInput').addEventListener('input', filterAndRender);
        $('filterClass').addEventListener('change', function () {
            $('filterExchange').style.display = this.value === 'crypto' ? 'none' : '';
        });
        $('wlPortfolio').addEventListener('change', function () { wlPfId = this.value; loadWatchlists(); });
        $('btnNewWl').addEventListener('click', function () { $('wlModal').classList.add('active'); });
        $('btnCancelWl').addEventListener('click', function () { $('wlModal').classList.remove('active'); });
        $('btnCreateWl').addEventListener('click', createWatchlist);

        var langBtn = $('langToggle');
        if (langBtn) langBtn.addEventListener('click', function () {
            lang = lang === 'en' ? 'ar' : 'en';
            document.documentElement.lang = lang;
            document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
            langBtn.textContent = lang === 'en' ? 'AR' : 'EN';
            applyLang();
        });
        var themeBtn = $('themeToggle');
        if (themeBtn) themeBtn.addEventListener('click', function () {
            var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
        });

        // Auto-refresh watchlists every 30 seconds
        setInterval(function () {
            if (wlPfId) loadWatchlists();
        }, 30000);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();