/**
 * portfolio-showcase.js — Premium Animated Showcase Controller.
 * Renders bilingual feature showcase section and controls interactive mockup slides.
 */
(function () {
    'use strict';

    var lang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';

    // ─── Translations Dictionary ─────────────────────────────────────────
    var T_SHOWCASE = {
        en: {
            tag: '✦ PORTFOLIO INTELLIGENCE',
            title: 'Everything you need for smarter portfolios',
            sub: 'Create, track, analyze, and optimize your EGX investments from one premium, intelligent workspace.',
            
            // Features
            f1_title: 'Create and manage your portfolio',
            f1_desc: 'Create a portfolio, add transactions, and manage holdings in one place.',
            f2_title: 'Track performance against the market',
            f2_desc: 'Monitor portfolio value, returns, dividends, win rate, and compare performance with EGX30.',
            f3_title: 'Analyze allocation and diversification',
            f3_desc: 'View asset allocation by stock and sector allocation across your portfolio.',
            f4_title: 'Review risk, dividends, and transactions',
            f4_desc: 'Track risk metrics, recent transactions, dividend income, and top contributors.',

            // Mockup Labels
            live: 'LIVE WORKSPACE',
            portfolio: 'My Portfolio',
            personal: 'Personal Account',
            totalValue: 'Total Value',
            dayChange: 'Day Change',
            totalReturn: 'Total Return',
            winRate: 'Win Rate',
            holdingsCount: 'Holdings',
            recentTx: 'Recent Transactions',
            liveActivity: 'Activity Logs',
            assetAlloc: 'Asset Allocation',
            sectorAlloc: 'Sector Allocation',
            conRisk: 'Concentration Risk',
            riskMetrics: 'Risk Metrics',
            sharpe: 'Sharpe Ratio',
            volatility: 'Volatility (Ann.)',
            beta: 'Beta vs EGX30',
            maxDrawdown: 'Max Drawdown',
            divIncome: 'Dividend Income',
            ytdDividends: 'YTD Dividends',
            cta: 'Start Now',

            // Status Values
            low: 'Low',
            good: 'Good',
            active: 'Active',
            
            // Transactions & Ticker Symbol Metadata
            txBuy: 'BUY',
            txSell: 'SELL',
            txDiv: 'DIV',
            txDep: 'DEP',
            shares: 'shares',
            price: 'price',
            credited: 'credited',
            deposited: 'deposited',

            // Log messages templates
            log1: 'Price feed updated for {n} EGX holdings',
            log2: 'Received dividend {val} from {sym}',
            log3: 'Adjusted {sym} for stock split ratio 1:5',
            log4: 'Executed BUY transaction: {qty} shares {sym}',
            log5: 'Risk analysis regenerated: Beta is {v}',
            log6: 'Portfolio successfully backed up to Vercel CDN'
        },
        ar: {
            tag: '✦ ذكاء المحفظة الاستثمارية',
            title: 'كل ما تحتاجه لمحفظة استثمارية أذكى',
            sub: 'أنشئ، وتتبع، وحلل، وحسّن استثماراتك في البورصة المصرية من مساحة عمل متكاملة وفائقة التطور.',
            
            // Features
            f1_title: 'أنشئ وأدر محفظتك الاستثمارية',
            f1_desc: 'أنشئ محفظة استثمارية، وأضف معاملاتك، وأدر أسهمك وممتلكاتك بالكامل في مكان واحد.',
            f2_title: 'تتبع الأداء مقابل مؤشر السوق',
            f2_desc: 'راقب قيمة المحفظة، والعوائد، والأرباح، ونسبة النجاح، وقارن الأداء التراكمي بمؤشر EGX30.',
            f3_title: 'حلل توزيع الأصول والتنويع',
            f3_desc: 'اعرض توزيع الأصول حسب الأسهم وتوزيع القطاعات والمخاطر عبر قطاعات محفظتك.',
            f4_title: 'راجع المخاطر، والأرباح، والمعاملات',
            f4_desc: 'تتبع مقاييس المخاطر المؤسسية، والمعاملات الأخيرة، ودخل الأرباح، وأهم المساهمين.',

            // Mockup Labels
            live: 'مساحة عمل مباشرة',
            portfolio: 'محفظتي الاستثمارية',
            personal: 'حساب شخصي',
            totalValue: 'إجمالي القيمة',
            dayChange: 'تغير اليوم',
            totalReturn: 'إجمالي العائد',
            winRate: 'نسبة النجاح',
            holdingsCount: 'الأسهم',
            recentTx: 'المعاملات الأخيرة',
            liveActivity: 'سجل الأنشطة',
            assetAlloc: 'توزيع الأصول',
            sectorAlloc: 'توزيع القطاعات',
            conRisk: 'مخاطر التركيز',
            riskMetrics: 'مقاييس المخاطر',
            sharpe: 'نسبة شارب',
            volatility: 'التقلب (سنوي)',
            beta: 'بيتا مقابل EGX30',
            maxDrawdown: 'أقصى تراجع',
            divIncome: 'دخل الأرباح',
            ytdDividends: 'الأرباح السنوية YTD',
            cta: 'ابدأ الآن',

            // Status Values
            low: 'منخفض',
            good: 'ممتاز',
            active: 'نشط',

            // Transactions & Ticker Symbol Metadata
            txBuy: 'شراء',
            txSell: 'بيع',
            txDiv: 'أرباح',
            txDep: 'إيداع',
            shares: 'سهم',
            price: 'بسعر',
            credited: 'تم قيدها',
            deposited: 'تم إيداعه',

            // Log messages templates
            log1: 'تم تحديث الأسعار لـ {n} من أسهم EGX',
            log2: 'تم استلام أرباح بقيمة {val} من سهم {sym}',
            log3: 'تعديل سهم {sym} لتجزئة القيمة الاسمية بنسبة 1:5',
            log4: 'تم تنفيذ صفقة شراء: {qty} سهم في {sym}',
            log5: 'تم تجديد تحليل المخاطر: قيمة بيتا هي {v}',
            log6: 'تم حفظ نسخة احتياطية للمحفظة على شبكة Vercel'
        }
    };

    function t(key) { return (T_SHOWCASE[lang] || T_SHOWCASE.en)[key] || key; }
    function fmt(n, d) { return PFStore.fmt(n, typeof d === 'number' ? d : 2); }

    // State Variables
    var activeIndex = 0;
    var autoPlay = true;
    var timerId = null;
    var simulationTimers = [];

    // Mock Live Values
    var mockTotalVal = 765078.75;
    var mockReturnPct = 6.12;
    var mockCashBalance = 44825.00;

    // ─── Render Showcase Shell ───────────────────────────────────────────
    function renderShowcase() {
        var root = document.getElementById('pfShowcaseRoot');
        if (!root) return;

        var dir = lang === 'ar' ? 'rtl' : 'ltr';
        document.documentElement.dir = dir;
        document.documentElement.lang = lang;

        var html = 
            '<div class="pf-showcase-container">' +
                // Header
                '<div class="pf-showcase-header">' +
                    '<h2 class="pf-showcase-title display">' + t('title') + '</h2>' +
                    '<p class="pf-showcase-sub">' + t('sub') + '</p>' +
                '</div>' +
                // Grid Content
                '<div class="pf-showcase-grid">' +
                    // Left Column (Feature Cards Selector)
                    '<div class="pf-showcase-features" id="showcaseFeatures">' +
                        featureCardHtml(0, t('f1_title'), t('f1_desc')) +
                        featureCardHtml(1, t('f2_title'), t('f2_desc')) +
                        featureCardHtml(2, t('f3_title'), t('f3_desc')) +
                        featureCardHtml(3, t('f4_title'), t('f4_desc')) +
                    '</div>' +
                    // Right Column (Dynamic Simulated Screen)
                    '<div style="display:flex; flex-direction:column; gap:0.6rem; min-width:0;">' +
                        '<div style="display:flex; justify-content:flex-end; align-items:center;">' +
                            '<button class="pf-showcase-cta" type="button">' + t('cta') + '</button>' +
                        '</div>' +
                        '<div class="pf-showcase-viewport" id="showcaseViewport">' +
                            '<div class="pf-showcase-inner">' +
                            // Slide 1: Create & Manage
                            '<div class="pf-showcase-slide active" data-slide="0">' +
                                slideHeadHtml(t('f1_title')) +
                                '<div class="pf-mock-grid">' +
                                    '<div class="pf-mock-panel">' +
                                        kpiPanelHtml() +
                                    '</div>' +
                                    '<div class="pf-mock-panel">' +
                                        '<div class="pf-mock-kpi-label">' + t('liveActivity') + '</div>' +
                                        '<div class="pf-mock-log-panel">' +
                                            '<div class="pf-mock-log-list" id="mockLogList"></div>' +
                                        '</div>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="pf-mock-panel" style="flex:1; margin-top:0.25rem;">' +
                                    '<div class="pf-mock-kpi-label" style="margin-bottom:0.45rem;">' + t('recentTx') + '</div>' +
                                    '<div class="pf-mock-table-wrap">' +
                                        '<table class="pf-mock-table">' +
                                            '<thead>' +
                                                '<tr><th>' + (lang === 'ar' ? 'السهم' : 'Symbol') + '</th><th>' + (lang === 'ar' ? 'النوع' : 'Type') + '</th><th style="text-align:end;">' + (lang === 'ar' ? 'الكمية' : 'Qty') + '</th><th style="text-align:end;">' + (lang === 'ar' ? 'القيمة' : 'Value') + '</th></tr>' +
                                            '</thead>' +
                                            '<tbody id="mockTxBody"></tbody>' +
                                        '</table>' +
                                    '</div>' +
                                '</div>' +
                                '</div>' +

                            // Slide 2: Performance Chart
                            '<div class="pf-showcase-slide" data-slide="1">' +
                                slideHeadHtml(t('f2_title')) +
                                '<div class="pf-showcase-chart-card pf-mock-panel" style="flex:1;">' +
                                    '<div style="display:flex; justify-content:space-between; align-items:center;">' +
                                        '<div>' +
                                            '<div class="pf-mock-kpi-label">' + t('portfolio') + ' ' + t('totalReturn') + '</div>' +
                                            '<div class="pf-mock-kpi-sub" style="font-size:1.15rem; font-family:var(--pf-mono); font-weight:700; color:var(--pf-green);">' +
                                                '<span id="chartRetVal">+6.12%</span>' +
                                            '</div>' +
                                        '</div>' +
                                        '<div style="display:flex; gap:0.6rem; font-size:0.68rem; font-weight:700; font-family:var(--pf-mono);">' +
                                            '<span style="color:var(--teal); display:inline-flex; align-items:center; gap:0.25rem;"><span style="width:0.5rem; height:0.5rem; border-radius:50%; background:var(--teal); display:inline-block;"></span>' + (lang === 'ar' ? 'محفظتي' : 'Portfolio') + '</span>' +
                                            '<span style="color:var(--muted); display:inline-flex; align-items:center; gap:0.25rem;"><span style="width:0.5rem; height:0.5rem; border-radius:50%; border:2px dashed var(--muted); display:inline-block; background:transparent;"></span>' + (lang === 'ar' ? 'مؤشر EGX30' : 'EGX30') + '</span>' +
                                        '</div>' +
                                    '</div>' +
                                    '<div class="pf-showcase-chart-wrap" id="perfShowcaseChartWrap">' +
                                        // Live SVG Chart drawing paths
                                        '<svg class="pf-chart-svg" viewBox="0 0 400 200" preserveAspectRatio="none">' +
                                            // Grid lines
                                            '<line x1="0" y1="160" x2="400" y2="160" stroke="var(--line)" stroke-width="1"></line>' +
                                            '<line x1="0" y1="100" x2="400" y2="100" stroke="var(--line)" stroke-dasharray="4" stroke-width="1"></line>' +
                                            '<line x1="0" y1="40" x2="400" y2="40" stroke="var(--line)" stroke-width="1"></line>' +
                                            // Gradient fill
                                            '<defs>' +
                                                '<linearGradient id="chartGlow" x1="0%" y1="0%" x2="0%" y2="100%">' +
                                                    '<stop offset="0%" stop-color="var(--teal)" stop-opacity="0.15"></stop>' +
                                                    '<stop offset="100%" stop-color="var(--teal)" stop-opacity="0.00"></stop>' +
                                                '</linearGradient>' +
                                            '</defs>' +
                                            '<path d="M 0 160 L 50 140 L 100 150 L 150 120 L 200 130 L 250 85 L 300 70 L 350 95 L 400 45 L 400 200 L 0 200 Z" fill="url(#chartGlow)"></path>' +
                                            // EGX30 Benchmark Path
                                            '<path d="M 0 160 Q 100 145 200 135 T 400 115" fill="none" stroke="var(--muted)" stroke-width="2" class="pf-chart-path-benchmark"></path>' +
                                            // Portfolio Outperformance Path
                                            '<path d="M 0 160 L 50 140 L 100 150 L 150 120 L 200 130 L 250 85 L 300 70 L 350 95 L 400 45" fill="none" stroke="var(--teal)" stroke-width="3" class="pf-chart-path-portfolio" id="showcaseChartPath"></path>' +
                                            // Tracer vertical line
                                            '<line id="showcaseChartTracer" x1="300" y1="0" x2="300" y2="200" stroke="var(--teal)" stroke-opacity="0.25" stroke-width="1.5" style="transform: translateX(0px);"></line>' +
                                            // Active coordinate indicator dots
                                            '<circle id="showcaseChartTracerPtPf" cx="300" cy="70" r="5" fill="var(--teal)" stroke="var(--surface)" stroke-width="2.5" class="pf-chart-tracer-dot"></circle>' +
                                            '<circle id="showcaseChartTracerPtBench" cx="300" cy="122" r="4.5" fill="var(--muted)" stroke="var(--surface)" stroke-width="2"></circle>' +
                                        '</svg>' +
                                        // Floating Tooltip
                                        '<div id="showcaseChartTooltip" style="position:absolute; top:25px; left:220px; background:var(--surface); border:1px solid var(--teal); padding:0.35rem 0.6rem; border-radius:0.4rem; font-size:0.65rem; box-shadow:0 4px 12px rgba(0,0,0,0.18); transition:left 300ms ease, top 300ms ease; font-family:var(--pf-mono); pointer-events:none;">' +
                                            '<div style="color:var(--muted); font-weight:600;" id="showcaseChartTooltipDate">26 May 2026</div>' +
                                            '<div style="color:var(--teal); font-weight:700;">' + (lang === 'ar' ? 'المحفظة' : 'Portfolio') + ': <span id="showcaseChartTooltipVal">+7.31%</span></div>' +
                                        '</div>' +
                                    '</div>' +
                                    '<div class="pf-mock-stats-strip">' +
                                        statBoxHtml(lang === 'ar' ? 'أفضل يوم' : 'Best Day', '+2.89%', 'var(--pf-green)') +
                                        statBoxHtml(lang === 'ar' ? 'أسوأ يوم' : 'Worst Day', '-1.34%', 'var(--pf-red)') +
                                        statBoxHtml(lang === 'ar' ? 'التراجع الأقصى' : 'Max Drawdown', '-4.23%', 'var(--pf-red)') +
                                        statBoxHtml(lang === 'ar' ? 'نسبة النجاح' : 'Win Rate', '64.3%', 'var(--ink)') +
                                    '</div>' +
                                '</div>' +
                            '</div>' +

                            // Slide 3: Allocation Donut & Sector
                            '<div class="pf-showcase-slide" data-slide="2">' +
                                slideHeadHtml(t('f3_title')) +
                                '<div class="pf-mock-panel" style="flex:1; display:flex; flex-direction:column; justify-content:center; gap:1.2rem;">' +
                                    '<div class="pf-alloc-mock-grid">' +
                                        // Donut
                                        '<div class="pf-donut-container" id="mockDonutContainer">' +
                                            '<svg class="pf-donut-svg" viewBox="0 0 100 100">' +
                                                '<circle class="pf-donut-circle-bg" cx="50" cy="50" r="38"></circle>' +
                                                // Segment CIB: 28% -> dasharray 49.2 176
                                                '<circle class="pf-donut-segment" cx="50" cy="50" r="38" stroke="#10b981" stroke-dasharray="66.8 171.9" stroke-dashoffset="0" id="donutSeg1"></circle>' +
                                                // Segment COMI: 25.4% -> dashoffset = -66.8 -> dasharray 60.6 178
                                                '<circle class="pf-donut-segment" cx="50" cy="50" r="38" stroke="#3b82f6" stroke-dasharray="60.6 178" stroke-dashoffset="-66.8" id="donutSeg2"></circle>' +
                                                // Segment SWDY: 23% -> dashoffset = -127.4 -> dasharray 54.9 183
                                                '<circle class="pf-donut-segment" cx="50" cy="50" r="38" stroke="#f59e0b" stroke-dasharray="54.9 183.8" stroke-dashoffset="-127.4" id="donutSeg3"></circle>' +
                                                // Segment TMGH: 15.3% -> dashoffset = -182.3 -> dasharray 36.5 202
                                                '<circle class="pf-donut-segment" cx="50" cy="50" r="38" stroke="#ec4899" stroke-dasharray="36.5 202.2" stroke-dashoffset="-182.3" id="donutSeg4"></circle>' +
                                                // Segment HRHO: 8.3% -> dashoffset = -218.8 -> dasharray 19.8 218
                                                '<circle class="pf-donut-segment" cx="50" cy="50" r="38" stroke="#8b5cf6" stroke-dasharray="19.8 218.9" stroke-dashoffset="-218.8" id="donutSeg5"></circle>' +
                                            '</svg>' +
                                            '<div class="pf-donut-text">' +
                                                '<span class="pf-donut-text-value">5</span>' +
                                                '<span class="pf-donut-text-label">' + t('holdingsCount') + '</span>' +
                                            '</div>' +
                                        '</div>' +
                                        // Legend list
                                        '<div class="pf-showcase-legend-grid">' +
                                            legendRowHtml('#10b981', 'CIB', '28.0%') +
                                            legendRowHtml('#3b82f6', 'COMI', '25.4%') +
                                            legendRowHtml('#f59e0b', 'SWDY', '23.0%') +
                                            legendRowHtml('#ec4899', 'TMGH', '15.3%') +
                                            legendRowHtml('#8b5cf6', 'HRHO', '8.3%') +
                                        '</div>' +
                                    '</div>' +
                                    // Sector allocation progress bars
                                    '<div class="pf-showcase-sectors">' +
                                        '<div class="pf-mock-kpi-label" style="margin-bottom:0.1rem;">' + t('sectorAlloc') + '</div>' +
                                        sectorRowHtml(lang === 'ar' ? 'البنوك والخدمات المالية' : 'Banks & Financial Services', '53.4%', 'sectorBar1') +
                                        sectorRowHtml(lang === 'ar' ? 'العقارات والإنشاءات' : 'Real Estate & Development', '23.6%', 'sectorBar2') +
                                        sectorRowHtml(lang === 'ar' ? 'الطاقة والصناعة' : 'Energy & Industrials', '23.0%', 'sectorBar3') +
                                    '</div>' +
                                '</div>' +
                            '</div>' +

                            // Slide 4: Risk and Dividend
                            '<div class="pf-showcase-slide" data-slide="3">' +
                                slideHeadHtml(t('f4_title')) +
                                '<div class="pf-risk-grid-showcase">' +
                                    riskCardHtml(t('sharpe'), '1.45', lang === 'ar' ? 'عائد خالي من المخاطر: 25.5%' : 'Risk-Free: 25.5%') +
                                    riskCardHtml(t('volatility'), '14.32%', lang === 'ar' ? 'تذبذب سنوي مقدر' : 'Annual Volatility') +
                                    riskCardHtml(t('beta'), '0.92', lang === 'ar' ? 'مستقر مقابل مؤشر السوق' : 'Stable vs EGX30') +
                                    riskCardHtml(t('conRisk'), t('low'), lang === 'ar' ? 'تنويع أصول ممتاز' : 'Highly Diversified', 'var(--pf-green)') +
                                '</div>' +
                                '<div style="display:grid; grid-template-columns: 1.65fr 1.35fr; gap:0.75rem; flex:1; margin-top:0.15rem; min-height:0;">' +
                                    // Left: Dividend chart
                                    '<div class="pf-mock-panel" style="display:flex; flex-direction:column; gap:0.45rem;">' +
                                        '<div style="display:flex; justify-content:space-between; align-items:center;">' +
                                            '<div class="pf-mock-kpi-label">' + t('divIncome') + '</div>' +
                                            '<div style="font-family:var(--pf-mono); font-size:0.82rem; font-weight:700; color:var(--ink);">' +
                                                '<span id="showcaseDivTotal">EGP 26,580.75</span>' +
                                            '</div>' +
                                        '</div>' +
                                        '<div class="pf-div-chart-showcase" id="showcaseDivChart">' +
                                            dividendBarHtml('Jan', 15) +
                                            dividendBarHtml('Feb', 22) +
                                            dividendBarHtml('Mar', 10) +
                                            dividendBarHtml('Apr', 45, true) +
                                            dividendBarHtml('May', 30) +
                                            dividendBarHtml('Jun', 55) +
                                            dividendBarHtml('Jul', 18) +
                                            dividendBarHtml('Aug', 70) +
                                            dividendBarHtml('Sep', 40) +
                                            dividendBarHtml('Oct', 12) +
                                            dividendBarHtml('Nov', 32) +
                                            dividendBarHtml('Dec', 50) +
                                        '</div>' +
                                    '</div>' +
                                    // Right: Live Dividend Feed
                                    '<div class="pf-mock-panel" style="display:flex; flex-direction:column; gap:0.45rem; overflow:hidden;">' +
                                        '<div class="pf-mock-kpi-label">' + t('recentTx') + '</div>' +
                                        '<div class="pf-mock-table-wrap" style="height:175px;">' +
                                            '<table class="pf-mock-table">' +
                                                '<thead>' +
                                                    '<tr><th>' + (lang === 'ar' ? 'السهم' : 'Symbol') + '</th><th style="text-align:end;">' + (lang === 'ar' ? 'توزيع الأرباح' : 'Payout') + '</th></tr>' +
                                                '</thead>' +
                                                '<tbody id="showcaseDivFeedBody"></tbody>' +
                                            '</table>' +
                                        '</div>' +
                                    '</div>' +
                                '</div>' +
                            '</div>' +

                        '</div>' +

                        // Viewport Bottom Navigation controls strip
                        '<div class="pf-showcase-controls">' +
                            '<button id="showcasePrev" class="pf-ctrl-btn" type="button" aria-label="Previous Feature">' +
                                '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>' +
                            '</button>' +
                            '<div id="showcaseIndicator" class="pf-ctrl-indicator">1 / 4</div>' +
                            '<button id="showcaseNext" class="pf-ctrl-btn" type="button" aria-label="Next Feature">' +
                                '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>' +
                            '</button>' +
                            '<button id="showcasePlayPause" class="pf-ctrl-btn" type="button" aria-label="Pause Auto-Scrolling" style="margin-inline-start: 0.25rem;">' +
                                '<svg class="pause-svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"></rect><rect x="14" y="4" width="4" height="16" rx="1"></rect></svg>' +
                                '<svg class="play-svg" width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="display:none; margin-inline-start: 0.1rem;"><path d="M8 5v14l11-7z"></path></svg>' +
                            '</button>' +
                        '</div>' +
                    '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        root.innerHTML = html;

        // Wire click events and init interactive components
        initInteractiveShowcase();
    }

    var ICONS = [
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>',
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>',
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path></svg>',
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'
    ];

    // Helper builders
    function featureCardHtml(index, title, desc) {
        var cls = index === 0 ? 'active' : '';
        return '<div class="pf-feature-card ' + cls + '" data-index="' + index + '">' +
            '<div class="pf-feature-icon">' + ICONS[index] + '</div>' +
            '<div class="pf-feature-info">' +
                '<h3><span>' + escHtml(title) + '</span><span class="pf-feature-checkmark">✓</span></h3>' +
                '<p>' + escHtml(desc) + '</p>' +
            '</div>' +
        '</div>';
    }

    function slideHeadHtml(title) {
        return '<div class="pf-showcase-slide-head">' +
            '<div class="pf-showcase-slide-title"><span class="indicator"></span>' + escHtml(title) + '</div>' +
            '<div style="display:flex; align-items:center; gap:0.65rem;">' +
                '<span class="pf-badge-neu pf-num" style="font-weight:600; display:inline-flex; align-items:center; gap:0.25rem;"><span style="width:0.35rem; height:0.35rem; border-radius:50%; background:var(--pf-green); display:inline-block;"></span>' + t('live') + '</span>' +
            '</div>' +
        '</div>';
    }

    function kpiPanelHtml() {
        return '<div class="pf-mock-kpi-wrap">' +
            '<div class="pf-mock-kpi-main">' +
                '<div class="pf-mock-kpi-label">' + t('portfolio') + ' ' + t('totalValue') + '</div>' +
                '<div class="pf-mock-kpi-value pf-num" id="showcaseLiveTotalVal">EGP ' + fmt(mockTotalVal) + '</div>' +
                '<div style="margin-top:0.25rem;">' +
                    '<span class="pf-mock-kpi-sub pf-pos pf-num" id="showcaseLiveTotalRet">' + pct(mockReturnPct) + '</span>' +
                '</div>' +
            '</div>' +
            '<div style="text-align:end; font-size:0.75rem; border-inline-start:1px solid var(--line); padding-inline-start:1.15rem;">' +
                '<div style="margin-bottom:0.45rem;">' +
                    '<span class="pf-mock-kpi-label" style="display:block;">' + t('winRate') + '</span>' +
                    '<span class="pf-num" style="font-weight:700; font-size:0.9rem;">64.3%</span>' +
                '</div>' +
                '<div>' +
                    '<span class="pf-mock-kpi-label" style="display:block;">' + t('holdingsCount') + '</span>' +
                    '<span class="pf-num" style="font-weight:700; font-size:0.9rem;">5</span>' +
                '</div>' +
            '</div>' +
        '</div>';
    }

    function statBoxHtml(label, val, color) {
        var style = color ? 'style="color:' + color + ';"' : '';
        return '<div class="pf-mock-stat-box">' +
            '<div class="pf-mock-stat-label">' + escHtml(label) + '</div>' +
            '<div class="pf-mock-stat-value pf-num" ' + style + '>' + escHtml(val) + '</div>' +
        '</div>';
    }

    function legendRowHtml(dotColor, name, pct) {
        return '<div class="pf-showcase-legend-row">' +
            '<span class="pf-showcase-legend-dot" style="background:' + dotColor + ';"></span>' +
            '<span class="pf-showcase-legend-name">' + escHtml(name) + '</span>' +
            '<span class="pf-showcase-legend-pct pf-num">' + escHtml(pct) + '</span>' +
        '</div>';
    }

    function sectorRowHtml(name, pct, id) {
        return '<div class="pf-showcase-sector-row">' +
            '<div class="pf-showcase-sector-meta">' +
                '<span class="pf-showcase-sector-name">' + escHtml(name) + '</span>' +
                '<span class="pf-showcase-sector-pct pf-num">' + escHtml(pct) + '</span>' +
            '</div>' +
            '<div class="pf-showcase-bar-track">' +
                '<div class="pf-showcase-bar-fill" id="' + id + '"></div>' +
            '</div>' +
        '</div>';
    }

    function riskCardHtml(label, val, desc, valColor) {
        var style = valColor ? 'style="color:' + valColor + ';"' : '';
        return '<div class="pf-risk-card-showcase">' +
            '<label>' + escHtml(label) + '</label>' +
            '<span class="pf-num" ' + style + '>' + escHtml(val) + '</span>' +
            '<small style="font-size:0.58rem; color:var(--muted); display:block; margin-top:0.18rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + escHtml(desc) + '</small>' +
        '</div>';
    }

    function dividendBarHtml(month, pctHeight, isActive) {
        var actCls = isActive ? 'active-pulse' : '';
        return '<div class="pf-div-bar-wrap-showcase">' +
            '<div class="pf-div-bar-showcase ' + actCls + '" data-height="' + pctHeight + '" style="height:0%;"></div>' +
            '<div class="pf-div-month-showcase">' + month + '</div>' +
        '</div>';
    }

    function pct(n) { return (n >= 0 ? '+' : '') + fmt(n, 2) + '%'; }
    function escHtml(s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }

    // ─── Interactive Showcase Controls wiring ───────────────────────────
    function initInteractiveShowcase() {
        var features = document.querySelectorAll('.pf-feature-card');
        var prevBtn = document.getElementById('showcasePrev');
        var nextBtn = document.getElementById('showcaseNext');
        var playPauseBtn = document.getElementById('showcasePlayPause');

        // Card clicks
        features.forEach(function (card) {
            card.addEventListener('click', function () {
                var index = parseInt(card.getAttribute('data-index'), 10);
                setActiveSlide(index);
                pauseAutoPlay();
            });
        });

        // Prev & Next Buttons
        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                var prev = (activeIndex - 1 + 4) % 4;
                setActiveSlide(prev);
                pauseAutoPlay();
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function () {
                var next = (activeIndex + 1) % 4;
                setActiveSlide(next);
                pauseAutoPlay();
            });
        }

        // Play/Pause Button
        if (playPauseBtn) {
            playPauseBtn.addEventListener('click', function () {
                if (autoPlay) {
                    pauseAutoPlay();
                } else {
                    startAutoPlay();
                }
            });
        }

        // Wire CTA buttons to scroll smoothly down to #pfListRoot
        document.querySelectorAll('.pf-showcase-cta').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                var target = document.getElementById('pfListRoot');
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        });

        // Initialize simulations
        initSimulations();

        // Start Auto advancement
        startAutoPlay();
    }

    // ─── Set Active Slide and transitions ──────────────────────────────
    function setActiveSlide(index) {
        activeIndex = index;

        // Highlight card selector
        var features = document.querySelectorAll('.pf-feature-card');
        features.forEach(function (card, idx) {
            if (idx === index) {
                card.classList.add('active');
            } else {
                card.classList.remove('active');
            }
        });

        // Trigger slide transition
        var slides = document.querySelectorAll('.pf-showcase-slide');
        slides.forEach(function (slide) {
            var slideIdx = parseInt(slide.getAttribute('data-slide'), 10);
            if (slideIdx === index) {
                slide.classList.add('active');
            } else {
                slide.classList.remove('active');
            }
        });

        // Numeric Indicator
        var indicator = document.getElementById('showcaseIndicator');
        if (indicator) {
            indicator.textContent = (index + 1) + ' / 4';
        }

        // Trigger active slide specific initial animations
        triggerSlideInitialAnimations(index);
    }

    function triggerSlideInitialAnimations(index) {
        if (index === 2) {
            // Slide 3: sector progress bars rise animation
            setTimeout(function () {
                var fill1 = document.getElementById('sectorBar1');
                var fill2 = document.getElementById('sectorBar2');
                var fill3 = document.getElementById('sectorBar3');
                if (fill1) fill1.style.width = '53.4%';
                if (fill2) fill2.style.width = '23.6%';
                if (fill3) fill3.style.width = '23.0%';
            }, 50);
        } else {
            // Reset sector progress bars if not active
            var fill1 = document.getElementById('sectorBar1');
            var fill2 = document.getElementById('sectorBar2');
            var fill3 = document.getElementById('sectorBar3');
            if (fill1) fill1.style.width = '0%';
            if (fill2) fill2.style.width = '0%';
            if (fill3) fill3.style.width = '0%';
        }

        if (index === 3) {
            // Slide 4: monthly dividend bars grow animation
            setTimeout(function () {
                var bars = document.querySelectorAll('.pf-div-bar-showcase');
                bars.forEach(function (bar) {
                    var h = bar.getAttribute('data-height');
                    bar.style.height = h + '%';
                });
            }, 50);
        } else {
            // Reset monthly dividend bars if not active
            var bars = document.querySelectorAll('.pf-div-bar-showcase');
            bars.forEach(function (bar) {
                bar.style.height = '0%';
            });
        }
    }

    // ─── Play / Pause timers ─────────────────────────────────────────────
    function startAutoPlay() {
        autoPlay = true;
        
        var playPauseBtn = document.getElementById('showcasePlayPause');
        if (playPauseBtn) {
            playPauseBtn.querySelector('.pause-svg').style.display = 'block';
            playPauseBtn.querySelector('.play-svg').style.display = 'none';
            playPauseBtn.setAttribute('aria-label', 'Pause Auto-Scrolling');
        }

        if (timerId) clearInterval(timerId);
        timerId = setInterval(function () {
            var next = (activeIndex + 1) % 4;
            setActiveSlide(next);
        }, 5000);
    }

    function pauseAutoPlay() {
        autoPlay = false;

        var playPauseBtn = document.getElementById('showcasePlayPause');
        if (playPauseBtn) {
            playPauseBtn.querySelector('.pause-svg').style.display = 'none';
            playPauseBtn.querySelector('.play-svg').style.display = 'block';
            playPauseBtn.setAttribute('aria-label', 'Resume Auto-Scrolling');
        }

        if (timerId) clearInterval(timerId);
    }

    // ─── Real-Time Live Simulations Engines ──────────────────────────────
    function initSimulations() {
        // Clear old intervals
        simulationTimers.forEach(function (tId) { clearInterval(tId); });
        simulationTimers = [];

        // Pre-populate slide 1 transactions and logs
        populateInitialMockData();

        // 1. KPI & Log Simulation (Slide 1)
        var kpiTimer = setInterval(function () {
            // Fluctuating total portfolio value slightly
            var diff = (Math.random() - 0.42) * 8.5; // slight positive bias
            mockTotalVal += diff;
            mockReturnPct += (diff / 720000) * 100;

            var valEl = document.getElementById('showcaseLiveTotalVal');
            var retEl = document.getElementById('showcaseLiveTotalRet');

            if (valEl && retEl) {
                valEl.textContent = 'EGP ' + fmt(mockTotalVal);
                retEl.textContent = pct(mockReturnPct);

                // Add flash class
                var cls = diff >= 0 ? 'pf-flash-pos' : 'pf-flash-neg';
                valEl.className = 'pf-mock-kpi-value pf-num ' + cls;
                retEl.className = 'pf-mock-kpi-sub pf-num ' + (mockReturnPct >= 0 ? 'pf-pos' : 'pf-neg') + ' ' + cls;

                setTimeout(function () {
                    valEl.className = 'pf-mock-kpi-value pf-num';
                    retEl.className = 'pf-mock-kpi-sub pf-num ' + (mockReturnPct >= 0 ? 'pf-pos' : 'pf-neg');
                }, 400);
            }
        }, 2200);
        simulationTimers.push(kpiTimer);

        // Predefined pool of tickers for Slide 1 transactions
        var tickerPool = [
            { sym: 'COMI', name: 'Commercial International Bank', p: 85.50 },
            { sym: 'SWDY', name: 'Elsewedy Electric', p: 58.20 },
            { sym: 'TMGH', name: 'Talaat Moustafa Group', p: 68.40 },
            { sym: 'HRHO', name: 'EFG Holding', p: 19.80 },
            { sym: 'ABUK', name: 'Abu Qir Fertilizers', p: 72.50 },
            { sym: 'EAST', name: 'Eastern Company', p: 26.30 },
            { sym: 'CIB',  name: 'CIB Bank Egypt', p: 85.50 }
        ];

        // 2. Transaction and Live Activity Logger Simulation (Slide 1)
        var txTimer = setInterval(function () {
            var tbody = document.getElementById('mockTxBody');
            var listEl = document.getElementById('mockLogList');
            if (!tbody || !listEl) return;

            // Roll action
            var ticker = tickerPool[Math.floor(Math.random() * tickerPool.length)];
            var types = ['BUY', 'SELL', 'DIV'];
            var type = types[Math.floor(Math.random() * types.length)];
            var qty = Math.floor(Math.random() * 8 + 1) * 100;
            var val = qty * ticker.p;

            // Append live transaction row
            var newTr = document.createElement('tr');
            newTr.className = 'pf-tx-row-new';

            var badgeCls = 'pf-badge-pos';
            var typeText = t('txBuy');
            if (type === 'SELL') { badgeCls = 'pf-badge-neg'; typeText = t('txSell'); }
            else if (type === 'DIV') { badgeCls = 'pf-badge-neu'; typeText = t('txDiv'); val = qty * 2.2; }

            newTr.innerHTML = 
                '<td>' +
                    '<div style="font-weight:700; font-family:var(--pf-mono);">' + ticker.sym + '</div>' +
                    '<div style="font-size:0.62rem; color:var(--muted); max-width:85px; overflow:hidden; text-overflow:ellipsis;">' + ticker.name + '</div>' +
                '</td>' +
                '<td><span class="pf-mock-badge-chip ' + badgeCls + '">' + typeText + '</span></td>' +
                '<td class="num">' + fmt(qty, 0) + '</td>' +
                '<td class="num ' + (type === 'SELL' ? 'pf-neg' : 'pf-pos') + '">EGP ' + fmt(val) + '</td>';

            tbody.insertBefore(newTr, tbody.firstChild);
            if (tbody.children.length > 3) tbody.removeChild(tbody.lastChild);

            // Generate corresponding log entry
            var logText = '';
            var logIcon = 'ℹ️';
            if (type === 'BUY') {
                logText = t('log4').replace('{qty}', fmt(qty, 0)).replace('{sym}', ticker.sym);
                logIcon = '🛒';
            } else if (type === 'SELL') {
                logText = lang === 'ar' 
                    ? 'تم تنفيذ صفقة بيع: ' + fmt(qty, 0) + ' سهم في ' + ticker.sym
                    : 'Executed SELL transaction: ' + fmt(qty, 0) + ' shares ' + ticker.sym;
                logIcon = '💸';
            } else {
                logText = t('log2').replace('{val}', 'EGP ' + fmt(val)).replace('{sym}', ticker.sym);
                logIcon = '💰';
            }

            appendLog(logIcon, logText);
        }, 4200);
        simulationTimers.push(txTimer);

        // Periodically write general activities to logs (Slide 1)
        var generalLogTimer = setInterval(function () {
            var listEl = document.getElementById('mockLogList');
            if (!listEl) return;

            var index = Math.floor(Math.random() * 3);
            var logText = '';
            var logIcon = '⚙️';
            if (index === 0) {
                logText = t('log1').replace('{n}', Math.floor(Math.random() * 4 + 8));
                logIcon = '🔄';
            } else if (index === 1) {
                logText = t('log5').replace('{v}', (0.85 + Math.random() * 0.15).toFixed(2));
                logIcon = '🛡️';
            } else {
                logText = t('log6');
                logIcon = '☁️';
            }

            appendLog(logIcon, logText);
        }, 6500);
        simulationTimers.push(generalLogTimer);

        // 3. Performance Tracer Line Animation (Slide 2)
        var coords = [
            { x: 0,   yPf: 160, yBench: 160, date: '26 Feb', rPf: '+0.00%', rBench: '+0.00%' },
            { x: 50,  yPf: 140, yBench: 145, date: '11 Mar', rPf: '+2.89%', rBench: '+2.18%' },
            { x: 100, yPf: 150, yBench: 152, date: '24 Mar', rPf: '+1.45%', rBench: '+1.15%' },
            { x: 150, yPf: 120, yBench: 135, date: '06 Apr', rPf: '+5.78%', rBench: '+3.62%' },
            { x: 200, yPf: 130, yBench: 138, date: '17 Apr', rPf: '+4.33%', rBench: '+3.18%' },
            { x: 250, yPf: 85,  yBench: 125, date: '30 Apr', rPf: '+10.83%',rBench: '+5.07%' },
            { x: 300, yPf: 70,  yBench: 122, date: '13 May', rPf: '+13.01%',rBench: '+5.50%' },
            { x: 350, yPf: 95,  yBench: 118, date: '20 May', rPf: '+9.40%', rBench: '+6.10%' },
            { x: 400, yPf: 45,  yBench: 115, date: '26 May', rPf: '+16.62%',rBench: '+6.54%' }
        ];
        var activeCoordIdx = 6;

        var chartTimer = setInterval(function () {
            if (activeIndex !== 1) return; // Only process when Slide 2 is active

            activeCoordIdx = (activeCoordIdx + 1) % coords.length;
            var coord = coords[activeCoordIdx];

            var lineEl = document.getElementById('showcaseChartTracer');
            var dotPfEl = document.getElementById('showcaseChartTracerPtPf');
            var dotBenchEl = document.getElementById('showcaseChartTracerPtBench');
            var ttEl = document.getElementById('showcaseChartTooltip');
            var ttDate = document.getElementById('showcaseChartTooltipDate');
            var ttVal = document.getElementById('showcaseChartTooltipVal');
            var retValMain = document.getElementById('chartRetVal');

            if (lineEl && dotPfEl && dotBenchEl && ttEl) {
                // Shift elements
                lineEl.setAttribute('x1', coord.x);
                lineEl.setAttribute('x2', coord.x);
                dotPfEl.setAttribute('cx', coord.x);
                dotPfEl.setAttribute('cy', coord.yPf);
                dotBenchEl.setAttribute('cx', coord.x);
                dotBenchEl.setAttribute('cy', coord.yBench);

                // Tooltip position adjusting
                var dirMult = lang === 'ar' ? -1 : 1;
                var leftOffset = coord.x - 60;
                if (leftOffset < 10) leftOffset = 10;
                if (leftOffset > 270) leftOffset = 270;
                ttEl.style.left = leftOffset + 'px';
                ttEl.style.top = (coord.yPf - 58) + 'px';

                // Text updates
                if (ttDate) ttDate.textContent = coord.date + ' 2026';
                if (ttVal) ttVal.textContent = coord.rPf;
                if (retValMain) retValMain.textContent = coord.rPf;
            }
        }, 2500);
        simulationTimers.push(chartTimer);

        // 4. Slide 4: Risk & Dividend Accrual & Scrolling Feed
        var divAccrualTimer = setInterval(function () {
            if (activeIndex !== 3) return; // Only execute on Slide 4

            // Fluctuate YTD dividends slightly as simulated payouts clear
            var payout = (Math.random() > 0.65) ? (Math.floor(Math.random() * 8 + 2) * 50) : 0.00;
            if (payout > 0) {
                var totalEl = document.getElementById('showcaseDivTotal');
                var feedBody = document.getElementById('showcaseDivFeedBody');
                if (totalEl) {
                    var cur = parseFloat(totalEl.textContent.replace(/[^\d.]/g, '')) || 26580.75;
                    var nextTotal = cur + payout;
                    totalEl.textContent = 'EGP ' + fmt(nextTotal);
                    
                    // Flash green
                    totalEl.style.color = 'var(--pf-green)';
                    setTimeout(function () { totalEl.style.color = ''; }, 600);

                    // Add row to Dividend Feed!
                    if (feedBody) {
                        var ticker = tickerPool[Math.floor(Math.random() * tickerPool.length)];
                        var newTr = document.createElement('tr');
                        newTr.className = 'pf-tx-row-new';
                        newTr.innerHTML =
                            '<td>' +
                                '<div style="font-weight:700; font-family:var(--pf-mono);">' + ticker.sym + '</div>' +
                                '<div style="font-size:0.58rem; color:var(--muted);">' + ticker.name + '</div>' +
                            '</td>' +
                            '<td class="num pf-pos">EGP ' + fmt(payout) + '</td>';
                        feedBody.insertBefore(newTr, feedBody.firstChild);
                        if (feedBody.children.length > 3) feedBody.removeChild(feedBody.lastChild);
                    }

                    // Push a simulated activity log
                    var logMsg = lang === 'ar' 
                        ? 'تم إضافة توزيع أرباح EGP ' + fmt(payout) + ' لمحفظة الاستثمار بنجاح.'
                        : 'Accrued dividend EGP ' + fmt(payout) + ' to cash account successfully.';
                    appendLog('💰', logMsg);
                }
            }
        }, 3500);
        simulationTimers.push(divAccrualTimer);

        // 5. Allocation Fluctuations & SVG Donut Redraw (Slide 3)
        var allocationWeights = [28.0, 25.4, 23.0, 15.3, 8.3];
        var allocTimer = setInterval(function () {
            if (activeIndex !== 2) return; // Only execute on Slide 3

            // Fluctuate weights slightly
            var totalFluct = 0;
            var newWeights = allocationWeights.map(function (w, idx) {
                if (idx === 4) return w; // HRHO absorbs balance
                var change = (Math.random() - 0.5) * 0.4; // +/- 0.2%
                var nextW = Math.max(w + change, 3.0); // minimum 3%
                totalFluct += (nextW - w);
                return parseFloat(nextW.toFixed(1));
            });
            // Adjust last weight to sum to exactly 100
            newWeights[4] = parseFloat((100 - newWeights.slice(0, 4).reduce(function(a,b){return a+b;}, 0)).toFixed(1));
            allocationWeights = newWeights;

            // Update text nodes in Legend
            var legendRows = document.querySelectorAll('.pf-showcase-legend-pct');
            if (legendRows.length === 5) {
                legendRows.forEach(function (pctEl, idx) {
                    pctEl.textContent = allocationWeights[idx].toFixed(1) + '%';
                });
            }

            // Redraw SVG Donut segments
            var circ = 2 * Math.PI * 38; // 238.76
            var offset = 0;
            for (var i = 0; i < 5; i++) {
                var seg = document.getElementById('donutSeg' + (i + 1));
                if (seg) {
                    var len = (allocationWeights[i] / 100) * circ;
                    seg.setAttribute('stroke-dasharray', len.toFixed(2) + ' ' + (circ - len).toFixed(2));
                    seg.setAttribute('stroke-dashoffset', offset.toFixed(2));
                    offset -= len;
                }
            }

            // Update Sector Allocation progress bars
            var banksVal = allocationWeights[0] + allocationWeights[1];
            var reVal = allocationWeights[3] + allocationWeights[4] + 0.2;
            var energyVal = allocationWeights[2];

            var bar1 = document.getElementById('sectorBar1');
            var bar2 = document.getElementById('sectorBar2');
            var bar3 = document.getElementById('sectorBar3');

            if (bar1 && bar2 && bar3) {
                bar1.style.width = banksVal.toFixed(1) + '%';
                bar2.style.width = reVal.toFixed(1) + '%';
                bar3.style.width = energyVal.toFixed(1) + '%';

                var pctEls = document.querySelectorAll('.pf-showcase-sector-pct');
                if (pctEls.length === 3) {
                    pctEls[0].textContent = banksVal.toFixed(1) + '%';
                    pctEls[1].textContent = reVal.toFixed(1) + '%';
                    pctEls[2].textContent = energyVal.toFixed(1) + '%';
                }
            }
        }, 2200);
        simulationTimers.push(allocTimer);
    }

    function populateInitialMockData() {
        var tbody = document.getElementById('mockTxBody');
        var listEl = document.getElementById('mockLogList');
        var divFeed = document.getElementById('showcaseDivFeedBody');
        if (!tbody || !listEl) return;

        // Init Transactions
        tbody.innerHTML = 
            '<tr>' +
                '<td><div style="font-weight:700; font-family:var(--pf-mono);">CIB</div><div style="font-size:0.62rem; color:var(--muted);">CIB Bank Egypt</div></td>' +
                '<td><span class="pf-mock-badge-chip pf-badge-pos">' + t('txBuy') + '</span></td>' +
                '<td class="num">1,200</td>' +
                '<td class="num pf-pos">EGP 102,600.00</td>' +
            '</tr>' +
            '<tr>' +
                '<td><div style="font-weight:700; font-family:var(--pf-mono);">COMI</div><div style="font-size:0.62rem; color:var(--muted);">Commercial Int Bank</div></td>' +
                '<td><span class="pf-mock-badge-chip pf-badge-neu">' + t('txDiv') + '</span></td>' +
                '<td class="num">500</td>' +
                '<td class="num pf-pos">EGP 14,800.00</td>' +
            '</tr>' +
            '<tr>' +
                '<td><div style="font-weight:700; font-family:var(--pf-mono);">TMGH</div><div style="font-size:0.62rem; color:var(--muted);">Talaat Moustafa Group</div></td>' +
                '<td><span class="pf-mock-badge-chip pf-badge-neg">' + t('txSell') + '</span></td>' +
                '<td class="num">1,000</td>' +
                '<td class="num pf-neg">EGP 68,400.00</td>' +
            '</tr>';

        // Init Logs
        listEl.innerHTML = 
            '<div class="pf-mock-log-item">🔄 ' + t('log1').replace('{n}', '12') + '</div>' +
            '<div class="pf-mock-log-item">⚙️ ' + t('log3').replace('{sym}', 'COMI') + '</div>' +
            '<div class="pf-mock-log-item">☁️ ' + t('log6') + '</div>';

        // Init Dividend Feed (Slide 4)
        if (divFeed) {
            divFeed.innerHTML =
                '<tr>' +
                    '<td><div style="font-weight:700; font-family:var(--pf-mono);">COMI</div><div style="font-size:0.58rem; color:var(--muted);">Commercial Int Bank</div></td>' +
                    '<td class="num pf-pos">EGP 14,800.00</td>' +
                '</tr>' +
                '<tr>' +
                    '<td><div style="font-weight:700; font-family:var(--pf-mono);">HRHO</div><div style="font-size:0.58rem; color:var(--muted);">EFG Holding</div></td>' +
                    '<td class="num pf-pos">EGP 6,450.00</td>' +
                '</tr>' +
                '<tr>' +
                    '<td><div style="font-weight:700; font-family:var(--pf-mono);">SWDY</div><div style="font-size:0.58rem; color:var(--muted);">Elsewedy Electric</div></td>' +
                    '<td class="num pf-pos">EGP 5,330.75</td>' +
                '</tr>';
        }
    }

    function appendLog(icon, text) {
        var listEl = document.getElementById('mockLogList');
        if (!listEl) return;

        var newItem = document.createElement('div');
        newItem.className = 'pf-mock-log-item';
        newItem.innerHTML = icon + ' ' + escHtml(text);

        listEl.insertBefore(newItem, listEl.firstChild);
        if (listEl.children.length > 4) listEl.removeChild(listEl.lastChild);
    }

    // ─── Lang switcher hook ──────────────────────────────────────────────
    function hookLanguageToggle() {
        var toggle = document.getElementById('langToggle');
        if (!toggle) return;

        toggle.addEventListener('click', function () {
            // We use a short timeout to run *after* portfolio-list.js's sync click handler
            setTimeout(function () {
                var nextLang = localStorage.getItem('starta-lang') || localStorage.getItem('lang') || 'en';
                if (nextLang !== lang) {
                    lang = nextLang;
                    renderShowcase();
                }
            }, 10);
        });
    }

    // Initialize on Script Load
    document.addEventListener('DOMContentLoaded', function () {
        renderShowcase();
        hookLanguageToggle();
    });

    // Fallback if DOMContentLoaded already fired
    if (document.readyState === 'interactive' || document.readyState === 'complete') {
        renderShowcase();
        hookLanguageToggle();
    }

}());
