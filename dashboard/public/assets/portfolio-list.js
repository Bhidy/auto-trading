/**
 * portfolio-list.js — Landing page controller.
 * Renders live indexing marquee, Alpaca portfolio cards, and mock creation flows.
 */
(function () {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';

    /* ─── Nav translations ────────────────────────────────────────────── */
    var NAV = {
        en: { nav_pf1: 'Self Improving Brain', nav_pf2: 'Capitol Shadow', nav_pf3: 'Cautious Sniper', nav_market_pulse: 'Market Pulse', nav_trading: 'Trading', nav_orders: 'Orders', nav_crypto: 'Crypto Terminal', nav_options: 'Options Lab', nav_screener: 'Screener', nav_history: 'Account History' },
        ar: { nav_pf1: 'الدماغ ذاتي التحسين', nav_pf2: 'ظل الكابيتول', nav_pf3: 'القناص الحذر', nav_market_pulse: 'نبض السوق', nav_trading: 'التداول', nav_orders: 'الأوامر', nav_crypto: 'محطة العملات الرقمية', nav_options: 'مختبر الخيارات', nav_screener: 'فلتر الأسهم', nav_history: 'سجل الحساب' }
    };
    
    function applyNavLang(l) {
        var map = NAV[l] || NAV.en;
        document.querySelectorAll('[data-key]').forEach(function(el) {
            if (map[el.dataset.key]) el.textContent = map[el.dataset.key];
        });
    }

    var T = {
        en: {
            title: 'Autonomous Portfolio Intelligence',
            sub: 'Monitor and orchestrate your institutional-grade Alpaca trading portfolios in real-time.',
            newPortfolio: 'Sandbox Account',
            totalValue: 'Total Value', totalReturn: 'Total Return',
            holdings: 'Positions',
            currency: 'Currency', benchmark: 'Benchmark',
            lastUpdated: 'Status', default: 'Demo Sandbox',
            viewPortfolio: 'Monitor Dashboard', createManual: 'Create Sandbox',
            createManualDesc: 'Start a mock local portfolio and add transactions manually.',
            createImport: 'Import csv/xlsx',
            createImportDesc: 'Import mock holdings from spreadsheet template.',
            importTitle: 'Import Holdings',
            importSubtitle: 'Upload your holdings to create a pre-filled portfolio instantly.',
            importDrop: 'Drag & drop your CSV or XLSX file here',
            importOr: 'or',
            importBrowse: 'Browse File',
            importTemplate: 'Download Sample Template',
            importRequired: 'Required columns: Symbol, Quantity, Avg Price',
            importPreview: 'Preview ({n} rows)',
            importColSymbol: 'Symbol', importColQty: 'Quantity', importColAvg: 'Avg Price',
            importErrNoFile: 'Please select a CSV or XLSX file.',
            importErrCols: 'Missing required columns. File must include: Symbol, Quantity, Avg Price.',
            importErrNoRows: 'No valid holdings rows found in the file.',
            cancel: 'Cancel', create: 'Create Sandbox',
            createWatchlist: 'From Watchlist',
            createWatchlistDesc: 'Prefill sandbox using stock watchlist symbols.',
            createModalTitle: 'New Sandbox Portfolio',
            portfolioName: 'Portfolio Name', portfolioCurrency: 'Base Currency',
            benchmarkLabel: 'Benchmark', riskFreeRate: 'Risk-Free Rate (%)',
            description: 'Description (optional)',
            vsEgx: 'vs SPY',
            renamePortfolio: 'Rename', deletePortfolio: 'Delete',
            renameTitle: 'Rename Sandbox', renameLabel: 'New name', renameSave: 'Save',
            deleteTitle: 'Delete Sandbox',
            deleteConfirm: 'Permanently delete sandbox {name}? This cannot be undone.',
        },
        ar: {
            title: 'ذكاء المحافظ الاستثمارية المستقلة',
            sub: 'راقب وأدر محافظ التداول الآلية الخاصة بك في Alpaca مباشرة وخلال لحظات.',
            newPortfolio: 'حساب تجريبي',
            totalValue: 'إجمالي القيمة', totalReturn: 'إجمالي العائد',
            holdings: 'الصفقات المفتوحة',
            currency: 'العملة', benchmark: 'المؤشر المرجعي',
            lastUpdated: 'الحالة التشغيلية', default: 'محاكاة تجريبية',
            viewPortfolio: 'لوحة التحكم والمراقبة', createManual: 'إنشاء محاكاة',
            createManualDesc: 'ابدأ محفظة افتراضية محلية جديدة وأضف المعاملات خطوة بخطوة.',
            createImport: 'استيراد الأرصدة',
            createImportDesc: 'ارفع ملف CSV أو XLSX لاستيراد أرصدة افتراضية.',
            importTitle: 'استيراد الأرصدة',
            importSubtitle: 'ارفع أرصدتك لإنشاء محفظة جاهزة فورًا.',
            importDrop: 'اسحب وأفلت ملف CSV أو XLSX هنا',
            importOr: 'أو',
            importBrowse: 'تصفح الملف',
            importTemplate: 'تنزيل نموذج CSV',
            importRequired: 'الأعمدة المطلوبة: Symbol، Quantity، Avg Price',
            importPreview: 'معاينة ({n} صفوف)',
            importColSymbol: 'الرمز', importColQty: 'الكمية', importColAvg: 'متوسط السعر',
            importErrNoFile: 'الرجاء اختيار ملف CSV أو XLSX.',
            importErrCols: 'الأعمدة المطلوبة غير موجودة. يجب أن يحتوي الملف على: Symbol، Quantity، Avg Price.',
            importErrNoRows: 'لم يتم العثور على صفوف صالحة في الملف.',
            cancel: 'إلغاء', create: 'إنشاء المحفظة',
            createWatchlist: 'من قائمة المتابعة',
            createWatchlistDesc: 'حول قائمة متابعتك إلى محفظة تجريبية.',
            createModalTitle: 'محفظة تجريبية جديدة',
            portfolioName: 'اسم المحفظة', portfolioCurrency: 'العملة الأساسية',
            benchmarkLabel: 'المؤشر المرجعي', riskFreeRate: 'معدل العائد الخالي من المخاطر (%)',
            description: 'وصف (اختياري)',
            vsEgx: 'مقابل SPY',
            renamePortfolio: 'إعادة تسمية', deletePortfolio: 'حذف',
            renameTitle: 'إعادة تسمية المحفظة', renameLabel: 'الاسم الجديد', renameSave: 'حفظ',
            deleteTitle: 'حذف المحفظة',
            deleteConfirm: 'هل تريد حذف المحفظة الافتراضية {name} نهائياً؟ لا يمكن التراجع عن هذا الإجراء.',
        }
    };

    function t(key) { return (T[lang] || T.en)[key] || key; }
    function fmt(n, d) { return PFStore.fmt(n, d); }
    function pct(n) { return (n >= 0 ? '+' : '') + fmt(n, 2) + '%'; }

    /* ─── Render Live Market Index Ribbon (Real-Time Scrolling Ticker) ── */
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

    function renderIndexMarquee() {
        // No-op to prevent old stacked overlapping marquee
    }

    /* ─── Render Portfolios Cards Grid ───────────────────────────────── */
    function render() {
        var root = document.getElementById('pfListRoot');
        if (!root) return;

        var portfolios = PFStore.getAll();
        
        var cardsHtml = portfolios.map(function (p) {
            var isServer = p.isServer || false;
            var cardId = p.id;
            var displayName = (lang === 'ar' && p.nameAr) ? p.nameAr : p.name;
            
            // Build base skeleton placeholder (live values loaded async)
            return '<div class="pf-card pf-portfolio-card ' + (isServer ? 'pf-portfolio-card--server' : '') + '" data-id="' + p.id + '" id="card-' + cardId + '">' +
                '<div class="card-name">' +
                    '<div class="card-name-left">' +
                        '<span class="portfolio-title-text">' + escHtml(displayName) + '</span>' +
                        (isServer ? '<span class="default-badge server-badge">Alpaca</span>' : '<span class="default-badge">' + t('default') + '</span>') +
                    '</div>' +
                    '<div class="card-name-actions">' +
                        (!isServer ? 
                            '<button class="pf-btn pf-btn--icon pf-btn--ghost pf-card-edit" data-id="' + p.id + '" data-name="' + escHtml(displayName) + '" title="' + t('renamePortfolio') + '" aria-label="' + t('renamePortfolio') + '">' +
                                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>' +
                            '</button>' +
                            '<button class="pf-btn pf-btn--icon pf-btn--ghost pf-btn--danger-ghost pf-card-delete" data-id="' + p.id + '" data-name="' + escHtml(displayName) + '" title="' + t('deletePortfolio') + '" aria-label="' + t('deletePortfolio') + '">' +
                                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>' +
                            '</button>'
                        : '') +
                    '</div>' +
                '</div>' +
                '<div class="card-value pf-num" id="val-' + cardId + '"><span class="pf-loading-spinner"></span></div>' +
                '<div class="card-meta">' +
                    kv(t('totalReturn'), '<span id="ret-' + cardId + '" class="pf-num"><span class="pf-loading-spinner"></span></span>') +
                    kv(t('holdings'), '<span id="qty-' + cardId + '" class="pf-num"><span class="pf-loading-spinner"></span></span>') +
                    kv(t('currency'), p.currency) +
                    kv(t('benchmark'), p.benchmark) +
                '</div>' +
                '<div class="card-footer">' +
                    '<span>' + t('lastUpdated') + ': <span id="status-' + cardId + '" class="pf-status-val">Loading...</span></span>' +
                    '<div class="card-actions">' +
                        '<button class="pf-btn pf-btn--sm pf-btn--primary" data-open="' + p.id + '">' + t('viewPortfolio') + ' →</button>' +
                    '</div>' +
                '</div>' +
            '</div>';
        }).join('');

        var createHtml = [
            createCard('✦', t('createManual'),   t('createManualDesc'),   'manual'),
            createCard('⇪', t('createImport'),   t('createImportDesc'),   'import'),
            createCard('◈', t('createWatchlist'), t('createWatchlistDesc'), 'watchlist'),
        ].join('');

        root.innerHTML =
            '<div class="pf-list">' +
                '<div class="pf-list-head">' +
                    '<div><h1 class="display">' + t('title') + '</h1><p>' + t('sub') + '</p></div>' +
                    '<button id="newPfBtn" class="pf-btn pf-btn--primary">+ ' + t('newPortfolio') + '</button>' +
                '</div>' +
                '<div class="pf-list-grid">' + cardsHtml + createHtml + '</div>' +
            '</div>';

        // Load asynchronous live metadata for cards
        portfolios.forEach(function (p) {
            loadCardLiveDetails(p);
        });

        // Wire events
        root.querySelectorAll('[data-open]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                window.location.href = '/portfolio-detail.html?id=' + btn.getAttribute('data-open');
            });
        });
        root.querySelectorAll('.pf-card-edit').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                openRenameModal(btn.getAttribute('data-id'), btn.getAttribute('data-name'));
            });
        });
        root.querySelectorAll('.pf-card-delete').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                confirmDelete(btn.getAttribute('data-id'), btn.getAttribute('data-name'));
            });
        });
        root.querySelectorAll('.pf-portfolio-card').forEach(function (card) {
            card.addEventListener('click', function () {
                window.location.href = '/portfolio-detail.html?id=' + card.dataset.id;
            });
        });
        root.querySelectorAll('.pf-create-card').forEach(function (card) {
            card.addEventListener('click', function () { openCreateModal(card.dataset.method); });
        });
        document.getElementById('newPfBtn').addEventListener('click', function () { openCreateModal('manual'); });
    }

    // Fetches live details from Server API for Alpaca accounts, or LocalStorage for Custom
    function loadCardLiveDetails(portfolio) {
        var id = portfolio.id;
        var valEl = document.getElementById('val-' + id);
        var retEl = document.getElementById('ret-' + id);
        var qtyEl = document.getElementById('qty-' + id);
        var statusEl = document.getElementById('status-' + id);

        if (!valEl) return;

        if (portfolio.isServer) {
            fetch(`/api/portfolio/${id}/summary`)
                .then(res => {
                    if (!res.ok) throw new Error('API failed');
                    return res.json();
                })
                .then(data => {
                    // Update layout
                    valEl.textContent = '$' + fmt(data.equity, 2);
                    
                    var initialCapital = id === 'all' ? 300000 : 100000;
                    var totalReturn = ((data.equity - initialCapital) / initialCapital) * 100;
                    
                    retEl.textContent = pct(totalReturn);
                    retEl.className = totalReturn >= 0 ? 'pf-pos pf-num' : 'pf-neg pf-num';
                    
                    qtyEl.textContent = data.positions_count;
                    
                    if (data.halted) {
                        statusEl.innerHTML = `<span class="pf-status-badge pf-status-badge--halted">${lang === 'ar' ? 'متوقف' : 'Halted'}</span>`;
                    } else if (data.live_connected) {
                        statusEl.innerHTML = `<span class="pf-status-badge pf-status-badge--live">${lang === 'ar' ? 'متصل' : 'Active (Live)'}</span>`;
                    } else {
                        statusEl.innerHTML = `<span class="pf-status-badge pf-status-badge--offline">${lang === 'ar' ? 'أوفلاين' : 'Active (Offline)'}</span>`;
                    }
                })
                .catch(() => {
                    valEl.textContent = '$100,000.00';
                    retEl.textContent = '0.00%';
                    qtyEl.textContent = '—';
                    statusEl.textContent = 'Offline';
                });
        } else {
            var holdings = (portfolio.transactions || []).filter(function(t) { return t.type === 'buy' || t.type === 'sell'; });
            var syms = holdings.map(function(t) { return t.symbol; }).filter(Boolean);
            PFStore.fetchLivePrices(syms).then(function() {
                var m = PFStore.computeMetrics(portfolio);
                valEl.textContent = '$' + fmt(m.totalValue, 2);
                retEl.textContent = pct(m.totalReturn);
                retEl.className = m.totalReturn >= 0 ? 'pf-pos pf-num' : 'pf-neg pf-num';
                qtyEl.textContent = m.holdingsCount;
                statusEl.innerHTML = `<span class="pf-status-badge">${lang === 'ar' ? 'تجريبي' : 'Sandbox'}</span>`;
            });
        }
    }

    function kv(label, val) {
        return '<div class="card-meta-item"><label>' + label + '</label><span>' + val + '</span></div>';
    }

    function createCard(icon, title, desc, method) {
        return '<div class="pf-card pf-create-card" data-method="' + method + '">' +
            '<div class="create-icon">' + icon + '</div>' +
            '<h3>' + title + '</h3>' +
            '<p>' + desc + '</p>' +
        '</div>';
    }

    function escHtml(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }

    /* ─── Modal Creations flow ────────────────────────────────────────── */
    var selectedMethod = 'manual';

    function openCreateModal(method) {
        selectedMethod = method || 'manual';
        renderModalBody();
        document.getElementById('createModal').classList.add('open');
    }

    function renderModalBody() {
        var body = document.getElementById('createModalBody');
        var methodMeta = {
            manual:    { icon: '✦', labelKey: 'createManual',    descKey: 'createManualDesc' },
            import:    { icon: '⇪', labelKey: 'createImport',    descKey: 'createImportDesc' },
            watchlist: { icon: '◈', labelKey: 'createWatchlist', descKey: 'createWatchlistDesc' }
        };
        var meta = methodMeta[selectedMethod] || methodMeta.manual;

        body.innerHTML =
            '<div class="pf-method-badge">'+
                '<div class="pf-method-badge-icon">' + meta.icon + '</div>'+
                '<div class="pf-method-badge-text">'+
                    '<span class="pf-method-badge-label">' + t(meta.labelKey) + '</span>'+
                    '<span class="pf-method-badge-desc">' + t(meta.descKey) + '</span>'+
                '</div>'+
            '</div>'+
            '<div id="importZone" class="pf-import-zone" style="' + (selectedMethod === 'import' ? '' : 'display:none;') + '">'+
                '<div class="pf-import-header">'+
                    '<div class="pf-import-icon">'+
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>'+
                    '</div>'+
                    '<div>'+
                        '<h4 class="pf-import-title">' + t('importTitle') + '</h4>'+
                        '<p class="pf-import-sub">' + t('importSubtitle') + '</p>'+
                    '</div>'+
                '</div>'+
                '<div id="importDropArea" class="pf-import-drop" role="button" tabindex="0">'+
                    '<svg class="pf-import-drop-icon" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M24 32V16"/><polyline points="16 24 24 16 32 24"/><path d="M40 32v6a4 4 0 0 1-4 4H12a4 4 0 0 1-4-4v-6"/></svg>'+
                    '<p class="pf-import-drop-label">' + t('importDrop') + '</p>'+
                    '<p class="pf-import-drop-hint">' + t('importRequired') + '</p>'+
                    '<input type="file" id="importFileInput" accept=".csv,.xlsx,.xls" style="display:none;">'+
                '</div>'+
                '<div class="pf-import-actions">'+
                    '<button type="button" id="importBrowseBtn" class="pf-btn pf-btn--primary pf-btn--sm"> ' + t('importBrowse') + '</button>'+
                    '<span class="pf-import-or">' + t('importOr') + '</span>'+
                    '<button type="button" id="importTemplateBtn" class="pf-btn pf-btn--sm pf-btn--outline"> ' + t('importTemplate') + '</button>'+
                '</div>'+
                '<div id="importError" class="pf-import-error" style="display:none;"></div>'+
                '<div id="importPreview"></div>'+
            '</div>'+
            '<div class="pf-form" id="createForm">'+
                '<div class="pf-form-row">'+
                    field('portfolioName', t('portfolioName'), '<input type="text" id="pfName" placeholder="e.g. My Sandbox" required>') +
                    field('currency', t('portfolioCurrency'), '<select id="pfCurrency"><option value="USD" selected>USD \u2014 US Dollar</option></select>') +
                '</div>'+
                '<div class="pf-form-row">'+
                    field('benchmark', t('benchmarkLabel'), '<select id="pfBenchmark"><option value="SPY" selected>S&amp;P 500 (SPY)</option><option value="QQQ">NASDAQ 100 (QQQ)</option><option value="DIA">Dow Jones (DIA)</option></select>') +
                    field('riskFree', t('riskFreeRate'), '<input type="number" id="pfRiskFree" value="4.5" step="0.1" min="0" max="100">') +
                '</div>'+
                field('desc', t('description'), '<input type="text" id="pfDesc" placeholder="Optional description">') +
                '<div style="display:flex;gap:.75rem;justify-content:flex-end;padding-top:.5rem;">'+
                    '<button class="pf-btn" id="cancelCreate">' + t('cancel') + '</button>'+
                    '<button class="pf-btn pf-btn--primary" id="submitCreate">' + t('create') + '</button>'+
                '</div>'+
            '</div>';

        body.querySelector('#cancelCreate').addEventListener('click', closeModal);
        body.querySelector('#submitCreate').addEventListener('click', submitCreate);

        initImportZone(body);
    }

    function field(id, label, inputHtml) {
        return '<div class="pf-field"><label for="' + id + '">' + label + '</label>' + inputHtml + '</div>';
    }

    var _importRows = [];

    function downloadSampleTemplate() {
        var csv = 'Symbol,Quantity,Avg Price,Notes\r\nAAPL,50,175.50,Initial buy\r\nMSFT,30,420.30,Initial buy\r\nAMZN,80,185.75,Initial buy\r\n';
        var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = 'starta_holdings_template.csv';
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(url); document.body.removeChild(a); }, 200);
    }

    function parseCSV(text) {
        var lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
        var rows = [];
        lines.forEach(function (line) {
            if (!line.trim()) return;
            var cols = [];
            var inQ = false, cur = '';
            for (var i = 0; i < line.length; i++) {
                var ch = line[i];
                if (ch === '"') { inQ = !inQ; }
                else if (ch === ',' && !inQ) { cols.push(cur.trim()); cur = ''; }
                else { cur += ch; }
            }
            cols.push(cur.trim());
            rows.push(cols);
        });
        return rows;
    }

    function normaliseHeader(h) {
        return h.toLowerCase().replace(/[^a-z0-9]/g, '');
    }

    function mapImportRows(rawRows) {
        if (rawRows.length < 2) return null;
        var header = rawRows[0].map(normaliseHeader);
        var iSym = header.findIndex(function (h) { return h === 'symbol' || h === 'ticker' || h === 'code'; });
        var iQty = header.findIndex(function (h) { return h === 'quantity' || h === 'qty' || h === 'shares'; });
        var iAvg = header.findIndex(function (h) {
            return h === 'avgprice' || h === 'averageprice' || h === 'avgcost' || h === 'price';
        });
        if (iSym === -1 || iQty === -1 || iAvg === -1) return null;
        var rows = [];
        for (var r = 1; r < rawRows.length; r++) {
            var row = rawRows[r];
            if (!row || !row[iSym]) continue;
            var sym = String(row[iSym] || '').trim().toUpperCase();
            var qty = parseFloat(String(row[iQty] || '').replace(/,/g, ''));
            var avg = parseFloat(String(row[iAvg] || '').replace(/,/g, ''));
            if (!sym || !qty || qty <= 0 || !avg || avg <= 0) continue;
            rows.push({ symbol: sym, quantity: qty, avgPrice: avg });
        }
        return rows.length ? rows : null;
    }

    function renderImportPreview(rows, container) {
        if (!rows || !rows.length) {
            container.innerHTML = '<div class="pf-import-error">' + t('importErrNoRows') + '</div>';
            return;
        }
        var previewLabel = t('importPreview').replace('{n}', rows.length);
        var thead = '<tr><th>' + t('importColSymbol') + '</th><th>' + t('importColQty') + '</th><th>' + t('importColAvg') + '</th></tr>';
        var tbody = rows.map(function (r) {
            return '<tr><td><span class="pf-sym-badge">' + escHtml(r.symbol) + '</span></td><td>' +
                r.quantity + '</td><td>$' + fmt(r.avgPrice, 2) + '</td></tr>';
        }).join('');
        container.innerHTML =
            '<div class="pf-import-preview-label">' + escHtml(previewLabel) + '</div>' +
            '<div class="pf-import-table-wrap"><table class="pf-import-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table></div>';
    }

    function processImportFile(file, previewEl, errorEl) {
        var name = file.name.toLowerCase();
        errorEl.textContent = '';
        previewEl.innerHTML = '';
        _importRows = [];
        if (!name.endsWith('.csv') && !name.endsWith('.xlsx') && !name.endsWith('.xls')) {
            errorEl.textContent = t('importErrNoFile'); return;
        }
        var reader = new FileReader();
        if (name.endsWith('.csv')) {
            reader.onload = function (e) {
                var rawRows = parseCSV(e.target.result);
                var mapped = mapImportRows(rawRows);
                if (!mapped) { errorEl.textContent = t('importErrCols'); return; }
                _importRows = mapped;
                renderImportPreview(mapped, previewEl);
            };
            reader.readAsText(file);
        } else {
            reader.onload = function (e) {
                try {
                    if (typeof XLSX !== 'undefined') {
                        var wb = XLSX.read(new Uint8Array(e.target.result), { type: 'array' });
                        var ws = wb.Sheets[wb.SheetNames[0]];
                        var rawRows = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' });
                        var mapped = mapImportRows(rawRows);
                        if (!mapped) { errorEl.textContent = t('importErrCols'); return; }
                        _importRows = mapped;
                        renderImportPreview(mapped, previewEl);
                    } else {
                        errorEl.textContent = 'For XLSX files, please save as CSV for best compatibility.';
                    }
                } catch (_) { errorEl.textContent = t('importErrCols'); }
            };
            reader.readAsArrayBuffer(file);
        }
    }

    function initImportZone(body) {
        var zone = body.querySelector('#importZone');
        if (!zone) return;

        zone.style.display = selectedMethod === 'import' ? '' : 'none';

        var dropArea   = zone.querySelector('#importDropArea');
        var fileInput  = zone.querySelector('#importFileInput');
        var browseBtn  = zone.querySelector('#importBrowseBtn');
        var templateBtn= zone.querySelector('#importTemplateBtn');
        var previewEl  = zone.querySelector('#importPreview');
        var errorEl    = zone.querySelector('#importError');

        browseBtn.addEventListener('click', function () { fileInput.click(); });
        fileInput.addEventListener('change', function () {
            if (fileInput.files[0]) processImportFile(fileInput.files[0], previewEl, errorEl);
        });

        templateBtn.addEventListener('click', downloadSampleTemplate);

        ['dragenter','dragover'].forEach(function (evt) {
            dropArea.addEventListener(evt, function (e) { e.preventDefault(); dropArea.classList.add('drag-over'); });
        });
        ['dragleave','drop'].forEach(function (evt) {
            dropArea.addEventListener(evt, function (e) { e.preventDefault(); dropArea.classList.remove('drag-over'); });
        });
        dropArea.addEventListener('drop', function (e) {
            var file = e.dataTransfer.files[0];
            if (file) processImportFile(file, previewEl, errorEl);
        });
        dropArea.addEventListener('click', function () { fileInput.click(); });
    }

    function submitCreate() {
        var name = document.getElementById('pfName').value.trim();
        if (!name) { document.getElementById('pfName').focus(); return; }
        
        var cashBalance = 0;
        var transactions = [];
        var currency = document.getElementById('pfCurrency').value;

        if (selectedMethod === 'import') {
            if (!_importRows || !_importRows.length) {
                var errEl = document.getElementById('importError');
                if (errEl) { errEl.textContent = t('importErrNoRows'); errEl.style.display = ''; }
                return;
            }
            var totalInvested = _importRows.reduce(function (sum, r) { return sum + (r.quantity * r.avgPrice); }, 0);
            var depId = 'dep-import-' + Date.now();
            transactions.push({
                id: depId, type: 'deposit',
                date: new Date().toISOString().slice(0, 10),
                symbol: null, quantity: null, price: null,
                commission: 0, tax: 0, currency: currency,
                notes: 'Initial funding from imported holdings',
                amount: totalInvested
            });
            _importRows.forEach(function (r, idx) {
                var comm = Math.round(r.quantity * r.avgPrice * 0.001);
                transactions.push({
                    id: 'tx-imp-' + idx + '-' + Date.now(),
                    type: 'buy',
                    date: new Date().toISOString().slice(0, 10),
                    symbol: r.symbol.toUpperCase(),
                    companyName: PFStore.symMeta(r.symbol).name || r.symbol,
                    quantity: r.quantity,
                    price: r.avgPrice,
                    commission: comm,
                    tax: 0, currency: currency,
                    notes: 'Imported holding'
                });
            });
            cashBalance = 0;
        }

        if (selectedMethod === 'watchlist') {
            var initialCash = 200000;
            var watchlist = ["AMZN", "GOOGL", "AAPL", "MSFT"];
            transactions.push({
                id: 'dep-' + Date.now(),
                type: 'deposit',
                date: new Date().toISOString().slice(0, 10),
                symbol: null, quantity: null, price: null,
                commission: 0, tax: 0, currency: currency,
                notes: 'Initial Funding from Watchlist',
                amount: initialCash
            });

            var totalToSpend = initialCash * 0.8;
            var spendPerStock = Math.floor(totalToSpend / watchlist.length);
            var remainingCash = initialCash;

            watchlist.forEach(function (sym) {
                var price = 150.00; // default prefill
                var qty = Math.floor(spendPerStock / price);
                if (qty > 0) {
                    var cost = qty * price;
                    var comm = Math.round(cost * 0.001);
                    transactions.push({
                        id: 'tx-init-' + sym + '-' + Date.now(),
                        type: 'buy',
                        date: new Date().toISOString().slice(0, 10),
                        symbol: sym,
                        companyName: PFStore.symMeta(sym).name || sym,
                        quantity: qty,
                        price: price,
                        commission: comm,
                        tax: 0, currency: currency,
                        notes: 'Automated initial purchase from Watchlist'
                    });
                    remainingCash -= (cost + comm);
                }
            });
            cashBalance = remainingCash;
        }

        var p = PFStore.create({
            name: name,
            currency: currency,
            benchmark: document.getElementById('pfBenchmark').value,
            riskFreeRate: parseFloat(document.getElementById('pfRiskFree').value) || 4.5,
            description: document.getElementById('pfDesc').value.trim(),
            isDefault: false,
            cashBalance: cashBalance,
            transactions: transactions
        });
        closeModal();
        window.location.href = '/portfolio-detail.html?id=' + p.id;
    }

    function closeModal() {
        document.getElementById('createModal').classList.remove('open');
        document.getElementById('createModalTitle').textContent = t('createModalTitle');
    }

    function openRenameModal(id, currentName) {
        document.getElementById('createModalTitle').textContent = t('renameTitle');
        var body = document.getElementById('createModalBody');
        body.innerHTML =
            '<div class="pf-form">' +
                field('pfRenameInput', t('renameLabel'), '<input type="text" id="pfRenameInput" value="' + escHtml(currentName) + '" required>') +
                '<div style="display:flex;gap:.75rem;justify-content:flex-end;padding-top:.5rem;">' +
                    '<button class="pf-btn" id="cancelRename">' + t('cancel') + '</button>' +
                    '<button class="pf-btn pf-btn--primary" id="submitRename">' + t('renameSave') + '</button>' +
                '</div>' +
            '</div>';
        body.querySelector('#cancelRename').addEventListener('click', closeModal);
        body.querySelector('#submitRename').addEventListener('click', function () {
            var newName = document.getElementById('pfRenameInput').value.trim();
            if (!newName) { document.getElementById('pfRenameInput').focus(); return; }
            PFStore.update(id, { name: newName });
            closeModal();
            render();
        });
        document.getElementById('createModal').classList.add('open');
        setTimeout(function () {
            var inp = document.getElementById('pfRenameInput');
            if (inp) { inp.focus(); inp.select(); }
        }, 60);
    }

    function confirmDelete(id, name) {
        document.getElementById('createModalTitle').textContent = t('deleteTitle');
        var body = document.getElementById('createModalBody');
        var msg = t('deleteConfirm').replace('{name}', '<strong style="color:var(--ink);">' + escHtml(name) + '</strong>');
        body.innerHTML =
            '<p style="color:var(--muted);font-size:.9rem;line-height:1.65;margin:0 0 1.5rem;">' + msg + '</p>' +
            '<div style="display:flex;gap:.75rem;justify-content:flex-end;">' +
                '<button class="pf-btn" id="cancelDelete">' + t('cancel') + '</button>' +
                '<button class="pf-btn pf-btn--danger" id="submitDelete">' + t('deletePortfolio') + '</button>' +
            '</div>';
        body.querySelector('#cancelDelete').addEventListener('click', closeModal);
        body.querySelector('#submitDelete').addEventListener('click', function () {
            PFStore.remove(id);
            closeModal();
            render();
        });
        document.getElementById('createModal').classList.add('open');
    }

    /* ─── Theme / lang controllers ────────────────────────────────────── */
    function applyLang(l) {
        lang = l; localStorage.setItem('starta-lang', l);
        document.documentElement.lang = l;
        document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
        document.getElementById('langToggle').textContent = l === 'ar' ? 'EN' : 'AR';
        applyNavLang(l);
        render();
    }

    document.getElementById('langToggle').addEventListener('click', function () {
        applyLang(lang === 'ar' ? 'en' : 'ar');
    });
    document.getElementById('closeCreateModal').addEventListener('click', closeModal);
    document.getElementById('createModal').addEventListener('click', function (e) {
        if (e.target === this) closeModal();
    });

    if (lang === 'ar') {
        document.documentElement.lang = 'ar';
        document.documentElement.dir = 'rtl';
        document.getElementById('langToggle').textContent = 'EN';
    }
    
    applyNavLang(lang);
    
    // Initial renders
    render();
    updateTickerRibbon();
    
    // Refresh prices and top index marquee scrolling ribbon every 8 seconds
    setInterval(updateTickerRibbon, 8000);

    // Auto-refresh portfolio card values every 60 seconds
    setInterval(function() {
        var portfolios = PFStore.getAll();
        portfolios.forEach(function(p) {
            loadCardLiveDetails(p);
        });
    }, 60000);

}());
