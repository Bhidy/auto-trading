(function () {
    'use strict';

    var T = {
        en: {
            orders_title: 'Order Management',
            orders_subtitle: 'Full order lifecycle — create, monitor, replace, and cancel orders across all portfolios',
            nav_home: 'Home', nav_portfolios: 'Portfolios', nav_pf_list: 'Portfolio List',
            nav_pf1: 'Self Improving Brain', nav_pf2: 'Capitol Shadow', nav_pf3: 'Cautious Sniper',
            nav_market_pulse: 'Market Pulse', nav_trading: 'Trading', nav_orders: 'Orders',
            nav_crypto: 'Crypto Terminal', nav_options: 'Options Lab', nav_screener: 'Screener',
            nav_history: 'Account History', nav_alerts: 'Alerts', nav_research: 'Research & AI', nav_settings: 'Settings',
            kpi_total: 'Total Orders', kpi_open: 'Open', kpi_filled: 'Filled', kpi_canceled: 'Canceled', kpi_value: 'Est. Fill Value',
            th_symbol: 'Symbol', th_side: 'Side', th_type: 'Type', th_qty: 'Qty', th_filled: 'Filled',
            th_price: 'Price', th_stop: 'Stop', th_avg_fill: 'Avg Fill', th_status: 'Status',
            th_tif: 'TIF', th_submitted: 'Submitted', th_actions: 'Actions',
            btn_new_order: 'New Order', btn_refresh: 'Refresh', btn_cancel_all: 'Cancel All',
            btn_cancel: 'Cancel', btn_submit_order: 'Submit Order', btn_replace: 'Replace Order',
            btn_buy: 'BUY', btn_sell: 'SELL',
            modal_new_order: 'New Order', modal_replace: 'Replace Order', drawer_detail: 'Order Detail',
            lbl_side: 'Side', lbl_symbol: 'Symbol', lbl_order_type: 'Order Type', lbl_tif: 'Time in Force',
            lbl_quantity: 'Quantity', lbl_limit_price: 'Limit Price', lbl_stop_price: 'Stop Price',
            lbl_trail: 'Trail Percent', lbl_extended: 'Extended Hours', lbl_order_class: 'Order Class',
            lbl_client_id: 'Client Order ID (optional)',
            lbl_new_qty: 'New Quantity', lbl_new_limit: 'New Limit Price', lbl_new_stop: 'New Stop Price',
            lbl_new_trail: 'New Trail', lbl_new_tif: 'New TIF',
            no_orders: 'Select a portfolio to view orders',
            filter_all_status: 'All Status', filter_all_side: 'All Sides', search_symbol: 'Search symbol...',
            confirm_cancel: 'Cancel this order?', confirm_cancel_all: 'Cancel ALL open orders?',
            toast_submitted: 'Order submitted', toast_canceled: 'Order canceled', toast_replaced: 'Order replaced',
            toast_cancel_all: 'All orders canceled', toast_error: 'Error'
        },
        ar: {
            orders_title: 'إدارة الأوامر',
            orders_subtitle: 'دورة حياة الأوامر الكاملة — إنشاء ومراقبة واستبدال وإلغاء الأوامر',
            nav_home: 'الرئيسية', nav_portfolios: 'المحافظ', nav_pf_list: 'قائمة المحافظ',
            nav_pf1: 'العقل الذاتي', nav_pf2: 'ظل الكابيتول', nav_pf3: 'القناص الحذر',
            nav_market_pulse: 'نبض السوق', nav_trading: 'التداول', nav_orders: 'الأوامر',
            nav_crypto: 'محطة الكريبتو', nav_options: 'مختبر الخيارات', nav_screener: 'الفرز',
            nav_history: 'سجل الحساب', nav_alerts: 'التنبيهات', nav_research: 'البحث والذكاء', nav_settings: 'الإعدادات',
            kpi_total: 'إجمالي الأوامر', kpi_open: 'مفتوحة', kpi_filled: 'منفذة', kpi_canceled: 'ملغاة', kpi_value: 'قيمة التنفيذ',
            th_symbol: 'الرمز', th_side: 'الاتجاه', th_type: 'النوع', th_qty: 'الكمية', th_filled: 'منفذ',
            th_price: 'السعر', th_stop: 'وقف', th_avg_fill: 'متوسط', th_status: 'الحالة',
            th_tif: 'المدة', th_submitted: 'تاريخ', th_actions: 'إجراءات',
            btn_new_order: 'أمر جديد', btn_refresh: 'تحديث', btn_cancel_all: 'إلغاء الكل',
            btn_cancel: 'إلغاء', btn_submit_order: 'تقديم الأمر', btn_replace: 'استبدال',
            btn_buy: 'شراء', btn_sell: 'بيع',
            modal_new_order: 'أمر جديد', modal_replace: 'استبدال الأمر', drawer_detail: 'تفاصيل الأمر',
            lbl_side: 'الاتجاه', lbl_symbol: 'الرمز', lbl_order_type: 'نوع الأمر', lbl_tif: 'مدة الصلاحية',
            lbl_quantity: 'الكمية', lbl_limit_price: 'سعر الحد', lbl_stop_price: 'سعر الوقف',
            lbl_trail: 'نسبة التتبع', lbl_extended: 'ساعات ممتدة', lbl_order_class: 'فئة الأمر',
            lbl_client_id: 'معرف العميل (اختياري)',
            lbl_new_qty: 'الكمية الجديدة', lbl_new_limit: 'سعر حد جديد', lbl_new_stop: 'سعر وقف جديد',
            lbl_new_trail: 'تتبع جديد', lbl_new_tif: 'مدة جديدة',
            no_orders: 'اختر محفظة لعرض الأوامر',
            filter_all_status: 'كل الحالات', filter_all_side: 'كل الاتجاهات', search_symbol: 'بحث الرمز...',
            confirm_cancel: 'إلغاء هذا الأمر؟', confirm_cancel_all: 'إلغاء جميع الأوامر؟',
            toast_submitted: 'تم تقديم الأمر', toast_canceled: 'تم إلغاء الأمر', toast_replaced: 'تم استبدال الأمر',
            toast_cancel_all: 'تم إلغاء الكل', toast_error: 'خطأ'
        }
    };

    var lang = document.documentElement.lang || 'en';
    var allOrders = [];
    var currentPfId = '';
    var currentSide = 'buy';

    function t(key) { return (T[lang] && T[lang][key]) || (T.en && T.en[key]) || key; }

    function applyLang() {
        lang = document.documentElement.lang || 'en';
        document.querySelectorAll('[data-key]').forEach(function (el) {
            var k = el.getAttribute('data-key');
            if (T[lang] && T[lang][k]) el.textContent = T[lang][k];
        });
        document.querySelectorAll('[data-key-placeholder]').forEach(function (el) {
            var k = el.getAttribute('data-key-placeholder');
            if (T[lang] && T[lang][k]) el.placeholder = T[lang][k];
        });
    }

    function $(id) { return document.getElementById(id); }
    function fmtPrice(v) { var n = parseFloat(v); return isNaN(n) ? '—' : '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    function fmtDate(iso) { if (!iso) return '—'; var d = new Date(iso); return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }); }
    function fmtQty(v) { var n = parseFloat(v); return isNaN(n) ? '—' : n.toLocaleString('en-US'); }

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

    function showToast(msg, type) {
        var toast = document.createElement('div');
        toast.textContent = msg;
        toast.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;z-index:200;padding:.65rem 1.25rem;border-radius:999px;font-size:.82rem;font-weight:700;color:#fff;background:' + (type === 'error' ? 'var(--pf-red)' : 'var(--pf-green)') + ';box-shadow:0 8px 24px rgba(0,0,0,.3);animation:fadeIn .2s ease;';
        document.body.appendChild(toast);
        setTimeout(function () { toast.remove(); }, 3000);
    }

    async function loadPortfolios() {
        var sel = $('ordPortfolioSelect');
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
                loadOrders();
            }
        } catch (e) {
            sel.innerHTML = '<option>No portfolios</option>';
        }
    }

    async function loadOrders() {
        if (!currentPfId) return;
        // Always send an explicit status. Alpaca's orders API defaults to `open`
        // when status is omitted, so "All" (which previously sent nothing) showed an
        // EMPTY table for any portfolio with no open orders (P1/P2) despite dozens of
        // filled orders. status=all returns open+closed.
        var status = $('filterStatus').value || 'all';
        var url = '/api/portfolio/' + currentPfId + '/orders?limit=200&nested=true&status=' + status;
        try {
            var resp = await fetch(url);
            allOrders = await resp.json();
            if (!Array.isArray(allOrders)) allOrders = [];
        } catch (e) {
            allOrders = [];
        }
        renderOrders();
        updateKpis();
    }

    function getFilteredOrders() {
        var sideF = $('filterSide').value;
        var symF = $('filterSymbol').value.toUpperCase().trim();
        return allOrders.filter(function (o) {
            if (sideF && o.side !== sideF) return false;
            if (symF && (o.symbol || '').indexOf(symF) === -1) return false;
            return true;
        });
    }

    function renderOrders() {
        var tbody = $('ordTableBody');
        var orders = getFilteredOrders();
        if (orders.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" class="ord-empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 9 6 6m0-6-6 6"/></svg><div>' + t('no_orders') + '</div></td></tr>';
            return;
        }
        tbody.innerHTML = orders.map(function (o) {
            var statusCls = 'ord-status ord-status--' + (o.status || 'new').replace(/ /g, '_');
            var sideCls = 'ord-side--' + (o.side || 'buy');
            var limitP = o.limit_price ? fmtPrice(o.limit_price) : (o.type === 'market' ? 'MKT' : '—');
            var stopP = o.stop_price ? fmtPrice(o.stop_price) : (o.trail_percent ? o.trail_percent + '%' : (o.trail_price ? fmtPrice(o.trail_price) : '—'));
            var avgFill = o.filled_avg_price ? fmtPrice(o.filled_avg_price) : '—';
            var isOpen = ['new', 'accepted', 'partially_filled', 'pending_new', 'pending_cancel', 'pending_replace', 'held'].indexOf(o.status) !== -1;
            var actions = '<div class="ord-actions-cell">';
            actions += '<button class="pf-btn pf-btn--sm pf-btn--ghost" onclick="window._ordViewDetail(\'' + o.id + '\')" title="View"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button>';
            if (isOpen) {
                actions += '<button class="pf-btn pf-btn--sm pf-btn--ghost" onclick="window._ordReplace(\'' + o.id + '\')" title="Replace"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>';
                actions += '<button class="pf-btn pf-btn--sm pf-btn--danger-ghost" onclick="window._ordCancel(\'' + o.id + '\')" title="Cancel"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></button>';
            }
            actions += '</div>';
            return '<tr>' +
                '<td style="font-weight:700;color:var(--ink);display:flex;align-items:center;gap:0.45rem;">' +
                    getLogoHtml(o.symbol, 20) +
                    '<span>' + (o.symbol || '—') + '</span>' +
                '</td>' +
                '<td><span class="' + sideCls + '">' + (o.side || '').toUpperCase() + '</span></td>' +
                '<td>' + (o.type || '').replace(/_/g, ' ') + '</td>' +
                '<td>' + fmtQty(o.qty || o.notional) + '</td>' +
                '<td>' + fmtQty(o.filled_qty) + '</td>' +
                '<td>' + limitP + '</td>' +
                '<td>' + stopP + '</td>' +
                '<td>' + avgFill + '</td>' +
                '<td><span class="' + statusCls + '">' + (o.status || '').replace(/_/g, ' ') + '</span></td>' +
                '<td>' + (o.time_in_force || '').toUpperCase() + '</td>' +
                '<td style="font-size:.72rem;color:var(--muted);">' + fmtDate(o.submitted_at || o.created_at) + '</td>' +
                '<td>' + actions + '</td>' +
                '</tr>';
        }).join('');
    }

    function updateKpis() {
        var total = allOrders.length;
        var open = 0, filled = 0, canceled = 0, value = 0;
        allOrders.forEach(function (o) {
            if (['new', 'accepted', 'partially_filled', 'pending_new', 'held'].indexOf(o.status) !== -1) open++;
            if (o.status === 'filled') filled++;
            if (o.status === 'canceled') canceled++;
            if (o.filled_avg_price && o.filled_qty) value += parseFloat(o.filled_avg_price) * parseFloat(o.filled_qty);
        });
        $('kpiTotal').textContent = total;
        $('kpiOpen').textContent = open;
        $('kpiFilled').textContent = filled;
        $('kpiCanceled').textContent = canceled;
        $('kpiValue').textContent = fmtPrice(value);
    }

    var ORDER_FIELDS = [
        ['id', 'Order ID'], ['client_order_id', 'Client Order ID'], ['symbol', 'Symbol'],
        ['asset_class', 'Asset Class'], ['side', 'Side'], ['type', 'Type'],
        ['qty', 'Quantity'], ['notional', 'Notional'], ['filled_qty', 'Filled Qty'],
        ['filled_avg_price', 'Avg Fill Price'], ['limit_price', 'Limit Price'],
        ['stop_price', 'Stop Price'], ['trail_price', 'Trail Price'], ['trail_percent', 'Trail %'],
        ['time_in_force', 'Time in Force'], ['order_class', 'Order Class'],
        ['status', 'Status'], ['extended_hours', 'Extended Hours'],
        ['created_at', 'Created'], ['submitted_at', 'Submitted'], ['filled_at', 'Filled At'],
        ['expired_at', 'Expired At'], ['canceled_at', 'Canceled At'], ['failed_at', 'Failed At'],
        ['replaced_at', 'Replaced At'], ['replaced_by', 'Replaced By'], ['replaces', 'Replaces'],
        ['asset_id', 'Asset ID'], ['hwm', 'HWM']
    ];

    window._ordViewDetail = function (orderId) {
        var order = allOrders.find(function (o) { return o.id === orderId; });
        if (!order) return;
        var html = ORDER_FIELDS.map(function (f) {
            var val = order[f[0]];
            if (val === undefined || val === null || val === '') return '';
            if (f[0].endsWith('_at')) val = fmtDate(val);
            else if (f[0] === 'filled_avg_price' || f[0] === 'limit_price' || f[0] === 'stop_price' || f[0] === 'trail_price') val = fmtPrice(val);
            return '<div class="ord-drawer-field"><span class="ord-drawer-field-label">' + f[1] + '</span><span class="ord-drawer-field-val">' + val + '</span></div>';
        }).filter(Boolean).join('');
        if (order.legs && order.legs.length) {
            html += '<div style="margin-top:1rem;"><div class="ord-form-label">Legs</div>';
            order.legs.forEach(function (leg, i) {
                html += '<div style="background:var(--page);border:1px solid var(--line);border-radius:.5rem;padding:.65rem;margin-top:.5rem;font-size:.75rem;">';
                html += '<div><strong>Leg ' + (i + 1) + ':</strong> ' + (leg.symbol || '') + ' ' + (leg.side || '') + ' ' + (leg.qty || '') + '</div>';
                html += '<div>Type: ' + (leg.type || '') + ' | Status: ' + (leg.status || '') + '</div>';
                if (leg.limit_price) html += '<div>Limit: ' + fmtPrice(leg.limit_price) + '</div>';
                if (leg.stop_price) html += '<div>Stop: ' + fmtPrice(leg.stop_price) + '</div>';
                html += '</div>';
            });
            html += '</div>';
        }
        $('drawerContent').innerHTML = html;
        var isOpen = ['new', 'accepted', 'partially_filled', 'pending_new', 'pending_cancel', 'pending_replace', 'held'].indexOf(order.status) !== -1;
        $('drawerActions').innerHTML = isOpen ?
            '<button class="pf-btn pf-btn--primary" onclick="window._ordReplace(\'' + orderId + '\');window._closeDrawer();">Replace</button>' +
            '<button class="pf-btn pf-btn--danger" onclick="window._ordCancel(\'' + orderId + '\');window._closeDrawer();">Cancel</button>' : '';
        $('drawerBg').classList.add('active');
        $('orderDrawer').classList.add('active');
    };

    window._closeDrawer = function () {
        $('drawerBg').classList.remove('active');
        $('orderDrawer').classList.remove('active');
    };

    window._ordCancel = async function (orderId) {
        if (!confirm(t('confirm_cancel'))) return;
        try {
            var resp = await fetch('/api/portfolio/' + currentPfId + '/order/' + orderId, { method: 'DELETE' });
            if (resp.ok) { showToast(t('toast_canceled'), 'success'); loadOrders(); }
            else { var e = await resp.json(); showToast(e.error || t('toast_error'), 'error'); }
        } catch (e) { showToast(e.message, 'error'); }
    };

    window._ordReplace = function (orderId) {
        var order = allOrders.find(function (o) { return o.id === orderId; });
        if (!order) return;
        $('replaceOrderId').value = orderId;
        $('replaceQty').value = order.qty || '';
        $('replaceLimitPrice').value = order.limit_price || '';
        $('replaceStopPrice').value = order.stop_price || '';
        $('replaceTrail').value = order.trail_percent || order.trail_price || '';
        $('replaceTif').value = '';
        $('replaceModal').classList.add('active');
    };

    async function submitReplace() {
        var orderId = $('replaceOrderId').value;
        var body = {};
        var qty = $('replaceQty').value;
        var lp = $('replaceLimitPrice').value;
        var sp = $('replaceStopPrice').value;
        var tr = $('replaceTrail').value;
        var tif = $('replaceTif').value;
        if (qty) body.qty = String(qty);
        if (lp) body.limit_price = String(lp);
        if (sp) body.stop_price = String(sp);
        if (tr) body.trail = String(tr);
        if (tif) body.time_in_force = tif;
        try {
            var resp = await fetch('/api/portfolio/' + currentPfId + '/order/' + orderId, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
            if (resp.ok) { showToast(t('toast_replaced'), 'success'); $('replaceModal').classList.remove('active'); loadOrders(); }
            else { var e = await resp.json(); showToast(e.error || t('toast_error'), 'error'); }
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function submitNewOrder() {
        var symbol = $('modalSymbol').value.trim().toUpperCase();
        var type = $('modalType').value;
        var tif = $('modalTif').value;
        var qty = $('modalQty').value;
        var limitPrice = $('modalLimitPrice').value;
        var stopPrice = $('modalStopPrice').value;
        var trailPercent = $('modalTrailPercent').value;
        var extended = $('modalExtended').value;
        var orderClass = $('modalOrderClass').value;
        var clientId = $('modalClientId').value.trim();

        if (!symbol || !qty) { showToast('Symbol and quantity required', 'error'); return; }

        var body = {
            symbol: symbol, side: currentSide, type: type, time_in_force: tif, qty: String(qty)
        };
        if (type === 'limit' || type === 'stop_limit') body.limit_price = String(limitPrice);
        if (type === 'stop' || type === 'stop_limit') body.stop_price = String(stopPrice);
        if (type === 'trailing_stop') body.trail_percent = String(trailPercent);
        if (extended === 'true') body.extended_hours = true;
        if (orderClass !== 'simple') body.order_class = orderClass;
        if (clientId) body.client_order_id = clientId;

        try {
            var resp = await fetch('/api/portfolio/' + currentPfId + '/order', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
            if (resp.ok) { showToast(t('toast_submitted'), 'success'); $('orderModal').classList.remove('active'); loadOrders(); }
            else { var e = await resp.json(); showToast(e.error || t('toast_error'), 'error'); }
        } catch (e) { showToast(e.message, 'error'); }
    }

    async function cancelAll() {
        if (!confirm(t('confirm_cancel_all'))) return;
        try {
            var resp = await fetch('/api/portfolio/' + currentPfId + '/orders', { method: 'DELETE' });
            if (resp.ok) { showToast(t('toast_cancel_all'), 'success'); loadOrders(); }
            else { var e = await resp.json(); showToast(e.error || t('toast_error'), 'error'); }
        } catch (e) { showToast(e.message, 'error'); }
    }

    function toggleOrderTypeFields() {
        var type = $('modalType').value;
        $('rowLimitPrice').style.display = (type === 'limit' || type === 'stop_limit') ? '' : 'none';
        $('rowStopPrice').style.display = (type === 'stop' || type === 'stop_limit') ? '' : 'none';
        $('rowTrailPercent').style.display = (type === 'trailing_stop') ? '' : 'none';
    }

    function init() {
        applyLang();
        loadPortfolios();

        $('ordPortfolioSelect').addEventListener('change', function () { currentPfId = this.value; loadOrders(); });
        $('filterStatus').addEventListener('change', loadOrders);
        $('filterSide').addEventListener('change', renderOrders);
        $('filterSymbol').addEventListener('input', renderOrders);
        $('btnRefresh').addEventListener('click', loadOrders);
        $('btnCancelAll').addEventListener('click', cancelAll);

        $('btnNewOrder').addEventListener('click', function () { $('orderModal').classList.add('active'); });
        $('btnCloseModal').addEventListener('click', function () { $('orderModal').classList.remove('active'); });
        $('btnCancelModal').addEventListener('click', function () { $('orderModal').classList.remove('active'); });
        $('btnSubmitOrder').addEventListener('click', submitNewOrder);
        $('modalType').addEventListener('change', toggleOrderTypeFields);

        $('sideToggleBuy').addEventListener('click', function () {
            currentSide = 'buy';
            this.className = 'active-buy';
            $('sideToggleSell').className = '';
        });
        $('sideToggleSell').addEventListener('click', function () {
            currentSide = 'sell';
            this.className = 'active-sell';
            $('sideToggleBuy').className = '';
        });

        $('btnCloseDrawer').addEventListener('click', window._closeDrawer);
        $('drawerBg').addEventListener('click', window._closeDrawer);

        $('btnCloseReplace').addEventListener('click', function () { $('replaceModal').classList.remove('active'); });
        $('btnCancelReplace').addEventListener('click', function () { $('replaceModal').classList.remove('active'); });
        $('btnSubmitReplace').addEventListener('click', submitReplace);

        var langBtn = $('langToggle');
        if (langBtn) {
            langBtn.addEventListener('click', function () {
                lang = lang === 'en' ? 'ar' : 'en';
                document.documentElement.lang = lang;
                document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
                langBtn.textContent = lang === 'en' ? 'AR' : 'EN';
                applyLang();
                renderOrders();
            });
        }

        var themeBtn = $('themeToggle');
        if (themeBtn) {
            themeBtn.addEventListener('click', function () {
                var current = document.documentElement.getAttribute('data-theme');
                var next = current === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', next);
                localStorage.setItem('theme', next);
            });
        }

        toggleOrderTypeFields();

        // Auto-refresh orders every 30 seconds
        setInterval(function () {
            if (currentPfId) loadOrders();
        }, 30000);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();