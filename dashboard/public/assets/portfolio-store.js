/**
 * portfolio-store.js — Client-side portfolio data layer and Alpaca sync agent.
 * Handles both native localStorage (custom) and Node.js Express Server (Alpaca 3 Portfolios) data.
 */
(function (global) {
    'use strict';

    var KEY = 'starta-portfolios';
    var SERVER_PORTFOLIOS = ['portfolio_1', 'portfolio_2', 'portfolio_3', 'all'];
    
    // Cache for server fetched portfolios
    var serverCache = {};

    var SYMBOLS = {
        AAPL: { name: 'Apple Inc.', nameAr: 'أبل', sector: 'Tech', color: '#a3a3a3' },
        AMZN: { name: 'Amazon.com Inc.', nameAr: 'أمازون دوت كوم', sector: 'Tech', color: '#f59e0b' },
        BIL:  { name: 'SPDR Barclays 1-3 Month T-Bill ETF', nameAr: 'سندات الخزانة الأمريكية قصيرة الأجل', sector: 'Defensive', color: '#475569' },
        DIA:  { name: 'SPDR Dow Jones Industrial Average ETF', nameAr: 'مؤشر داو جونز الصناعي', sector: 'Core Equity', color: '#8b5cf6' },
        GOOGL: { name: 'Alphabet Inc.', nameAr: 'ألفابت (جوجل)', sector: 'Tech', color: '#0ea5e9' },
        IWM:  { name: 'iShares Russell 2000 ETF', nameAr: 'مؤشر راسل 2000 للشركات الصغيرة', sector: 'Core Equity', color: '#ec4899' },
        QQQ:  { name: 'Invesco QQQ Trust Series 1', nameAr: 'مؤشر ناسداك 100', sector: 'Core Equity', color: '#14b8a6' },
        SPY:  { name: 'SPDR S&P 500 ETF Trust', nameAr: 'مؤشر إس أند بي 500', sector: 'Core Equity', color: '#22c55e' },
        TSLA: { name: 'Tesla Inc.', nameAr: 'تسلا للسيارات الكهربائية', sector: 'Tech', color: '#ef4444' },
        XLI:  { name: 'Industrial Select Sector SPDR Fund', nameAr: 'قطاع الصناعات الأمريكي', sector: 'Sector Momentum', color: '#3b82f6' },
        XLK:  { name: 'Technology Select Sector SPDR Fund', nameAr: 'قطاع التكنولوجيا الأمريكي', sector: 'Sector Momentum', color: '#10b981' },
        XLY:  { name: 'Consumer Discretionary Select Sector SPDR Fund', nameAr: 'قطاع الاستهلاك الكمالي الأمريكي', sector: 'Sector Momentum', color: '#a855f7' },
        INTU: { name: 'Intuit Inc.', nameAr: 'إنتويت للبرمجيات', sector: 'Gov Copy', color: '#06b6d4' },
        PG:   { name: 'Procter & Gamble Co.', nameAr: 'بروكتل آند غامبل الاستهلاكية', sector: 'Gov Copy', color: '#f97316' },
        TER:  { name: 'Teradyne Inc.', nameAr: 'تيرادين للإلكترونيات', sector: 'Gov Copy', color: '#84cc16' },
        WDAY: { name: 'Workday Inc.', nameAr: 'ورك داي لبرمجيات الموارد', sector: 'Gov Copy', color: '#0ea5e9' },
        CSCO: { name: 'Cisco Systems Inc.', nameAr: 'سيسكو لنظم الشبكات', sector: 'Event Tech', color: '#14b8a6' },
        META: { name: 'Meta Platforms Inc.', nameAr: 'ميتا بلاتفورمز', sector: 'Tech', color: '#1877f2' },
        MS:   { name: 'Morgan Stanley', nameAr: 'مورجان ستانلي للخدمات المالية', sector: 'Event Tech', color: '#3b82f6' },
        MSFT: { name: 'Microsoft Corp.', nameAr: 'مايكروسوفت', sector: 'Tech', color: '#00a4ef' },
        NVDA: { name: 'NVIDIA Corp.', nameAr: 'إنفيديا', sector: 'Tech', color: '#76b900' },
        PANW: { name: 'Palo Alto Networks Inc.', nameAr: 'بالو ألتو لشبكات الأمان', sector: 'Event Tech', color: '#ec4899' }
    };

    function symMeta(sym) {
        if (!sym) return { name: 'Other', nameAr: 'أخرى', sector: 'Other', color: '#9ca6b5' };
        var cleanSym = String(sym).trim().toUpperCase();
        return SYMBOLS[cleanSym] || { name: cleanSym, nameAr: cleanSym, sector: 'Other', color: '#9ca6b5' };
    }

    /* ─── Fetch Portfolio from Local Express Server ──────────────────────── */
    function loadPortfolio(id) {
        if (!SERVER_PORTFOLIOS.includes(id)) {
            return Promise.resolve(getLocalStoragePortfolio(id));
        }

        return fetch(`/api/portfolio/${id}/details`, { cache: 'no-store' })
            .then(function (res) {
                if (!res.ok) throw new Error('Server API failed');
                return res.json();
            })
            .then(function (data) {
                serverCache[id] = data;

                var name = data.label;
                var nameAr = 'جميع المحافظ';
                var strategy = data.is_aggregated
                    ? ('All Portfolios · ' + (data.source_labels || []).join(' · '))
                    : data.strategy || '';
                if (id === 'portfolio_1') {
                    nameAr = 'الدماغ ذاتي التحسين';
                    strategy = data.strategy || strategy;
                } else if (id === 'portfolio_2') {
                    nameAr = 'ظل الكابيتول';
                    strategy = data.strategy || strategy;
                } else if (id === 'portfolio_3') {
                    nameAr = 'القناص الحذر';
                    strategy = data.strategy || strategy;
                }

                var p = {
                    id: data.id,
                    name: name,
                    nameAr: nameAr,
                    currency: data.currency || 'USD',
                    benchmark: data.benchmark || 'SPY',
                    riskFreeRate: data.strategy_params?.risk_free_rate || 4.5,
                    description: strategy,
                    cashBalance: data.account.cash,
                    isDefault: false,
                    isServer: true,
                    liveConnected: data.live_connected,
                    halted: data.halted,
                    haltReason: data.halt_reason,
                    isAggregated: data.is_aggregated || false,
                    transactions: (data.trade_log || []).map(function(t, idx) {
                        return {
                            id: t.order_id || 'tx-' + idx,
                            type: t.side === 'buy' ? 'buy' : t.side === 'sell' ? 'sell' : t.type || 'buy',
                            date: t.date || t.timestamp?.slice(0, 10) || new Date().toISOString().slice(0, 10),
                            symbol: t.symbol,
                            companyName: symMeta(t.symbol).name,
                            quantity: t.qty,
                            price: t.entry_price || t.price || 0,
                            commission: t.commission || 0,
                            notes: (t.source_label ? '[' + t.source_label + '] ' : '') + (t.reason || t.reasons?.join(', ') || '')
                        };
                    })
                };
                return p;
            })
            .catch(function (err) {
                console.error(`Error loading server portfolio ${id}:`, err);
                return getLocalStoragePortfolio(id);
            });
    }

    // Compiles historical equity list for charts
    function loadEquityHistory(id, period) {
        if (!SERVER_PORTFOLIOS.includes(id)) {
            return Promise.resolve({ source: 'local', base_value: 100000, history: [] });
        }

        var p = period || '3M';
        var periodMap = { '1D': '1D', '1W': '1W', '1M': '1M', '3M': '3M', '6M': '6M', 'YTD': '1A', 'All': '1A' };
        var apiPeriod = periodMap[p] || '3M';
        var tf = (p === '1D') ? '5Min' : '1D';

        return fetch('/api/portfolio/' + id + '/equity-history?period=' + apiPeriod + '&timeframe=' + tf, { cache: 'no-store' })
            .then(function (res) {
                if (!res.ok) throw new Error('History fetch failed');
                return res.json();
            })
            .then(function (data) {
                if (data && data.history && data.history.length > 0) {
                    return data;
                }
                return { source: 'empty', base_value: 100000, history: [] };
            })
            .catch(function () {
                return { source: 'error', base_value: 100000, history: [] };
            });
    }

    // Get live quotes for index ribbon
    function loadMarketIndices() {
        return fetch('/api/market-indices', { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : {}; })
            .catch(function () { return {}; });
    }

    /* ─── Compute Metrics (Express API Cache vs local Average Cost) ───────── */
    function computeMetrics(portfolio) {
        if (!portfolio) return null;
        const id = portfolio.id;
        
        // If server cached portfolio exists, translate precompiled server metrics
        if (SERVER_PORTFOLIOS.includes(id) && serverCache[id]) {
            var data = serverCache[id];
            var cash = data.account.cash;
            var equity = data.account.equity;
            var dayPnL = data.account.day_pnl;
            var dayPnLPct = data.account.day_pnl_pct;
            
            var totalCost = 0;
            var totalMarketValue = 0;
            
            // Map enriched holdings
            var enriched = (data.positions || []).map(function (p) {
                var meta = symMeta(p.symbol);
                totalCost += (p.quantity * p.avgCost);
                totalMarketValue += p.marketValue;
                
                return {
                    symbol: p.symbol,
                    companyName: meta.name,
                    companyNameAr: meta.nameAr,
                    sector: meta.sector,
                    color: meta.color,
                    quantity: p.quantity,
                    avgCost: p.avgCost,
                    lastPrice: p.lastPrice,
                    prevClose: p.lastPrice - (p.dayChange || 0),
                    marketValue: p.marketValue,
                    weight: p.weight,
                    dayChange: p.dayChange || 0,
                    dayChangePct: p.dayChangePct || 0,
                    totalGain: p.unrealized_pl || 0,
                    totalReturn: p.unrealized_plpc || 0,
                    side: p.side || 'long',
                    costBasis: p.cost_basis || (p.quantity * p.avgCost),
                    unrealizedIntradayPl: p.unrealized_intraday_pl || 0,
                    unrealizedIntradayPlpc: p.unrealized_intraday_plpc || 0,
                    exchange: p.exchange || ''
                };
            });
            
            // Sort by weight
            enriched.sort(function (a, b) { return b.weight - a.weight; });
            
            // Sector allocation weights
            var sectors = {};
            enriched.forEach(function (h) {
                sectors[h.sector] = (sectors[h.sector] || 0) + h.weight;
            });
            
            var initialCapital = portfolio.isAggregated ? 300000 : 100000; // paper capital baseline
            var totalGain = equity - initialCapital;
            var totalReturn = (totalGain / initialCapital) * 100;
            
            var bestHolder = enriched.slice().sort(function (a, b) { return b.totalReturn - a.totalReturn; })[0];
            var worstHolder = enriched.slice().sort(function (a, b) { return a.totalReturn - b.totalReturn; })[0];

            return {
                totalValue: equity,
                totalMarketValue: totalMarketValue,
                cashBalance: cash,
                invested: totalCost,
                totalGain: totalGain,
                totalReturn: totalReturn,
                todayGain: dayPnL,
                todayPct: dayPnLPct,
                dividendsYTD: 0, // Optionals
                holdings: enriched,
                sectors: sectors,
                bestHolder: bestHolder,
                worstHolder: worstHolder,
                holdingsCount: enriched.length
            };
        }

        // Local Storage holdings calculation
        return computeLocalStorageMetrics(portfolio);
    }

    /* ─── Local Storage CRUD & Logic ────────────────────────────────────────── */
    function getLocalStoragePortfolio(id) {
        var list = loadAll();
        return list.find(function (p) { return p.id === id; }) || null;
    }

    function computeLocalStorageHoldings(transactions) {
        var map = {};
        transactions.filter(function (t) { return t.type === 'buy' || t.type === 'sell'; })
            .sort(function (a, b) { return a.date.localeCompare(b.date); })
            .forEach(function (t) {
                var sym = String(t.symbol || '').trim().toUpperCase();
                if (!sym) return;
                if (!map[sym]) map[sym] = { symbol: sym, quantity: 0, totalCost: 0 };
                if (t.type === 'buy') {
                    map[sym].totalCost += (t.quantity * t.price) + (t.commission || 0);
                    map[sym].quantity += t.quantity;
                } else {
                    var avgCost = map[sym].quantity ? map[sym].totalCost / map[sym].quantity : 0;
                    map[sym].totalCost -= avgCost * t.quantity;
                    map[sym].quantity -= t.quantity;
                }
            });
        return Object.values(map).filter(function (h) { return h.quantity > 0; });
    }

    var _livePriceCache = {};

    function fetchLivePrices(symbols) {
        if (!symbols || !symbols.length) return Promise.resolve();
        var unique = symbols.filter(function(s, i, a) { return a.indexOf(s) === i; });
        return fetch('/api/market/quotes', { cache: 'no-store' })
            .then(function(r) { return r.ok ? r.json() : {}; })
            .then(function(data) {
                Object.keys(data).forEach(function(sym) {
                    var q = data[sym];
                    if (q) {
                        _livePriceCache[sym] = {
                            price: q.price || 0,
                            prevClose: q.close || q.price || 0
                        };
                    }
                });
                unique.forEach(function(sym) {
                    if (!_livePriceCache[sym] && !data[sym]) {
                        fetch('/api/stock/' + sym + '/details', { cache: 'no-store' })
                            .then(function(r) { return r.ok ? r.json() : {}; })
                            .then(function(d) {
                                if (d.quote && d.quote.price) {
                                    _livePriceCache[sym] = { price: d.quote.price, prevClose: d.quote.prevClose || d.quote.price };
                                }
                            }).catch(function() {});
                    }
                });
            })
            .catch(function() {});
    }

    function lastPrice(sym, fallback) {
        if (!sym) return fallback || 0;
        var cleanSym = String(sym).trim().toUpperCase();
        var cached = _livePriceCache[cleanSym];
        return (cached && cached.price) ? cached.price : (fallback || 0);
    }

    function prevClose(sym, fallback) {
        if (!sym) return fallback || 0;
        var cleanSym = String(sym).trim().toUpperCase();
        var cached = _livePriceCache[cleanSym];
        return (cached && cached.prevClose) ? cached.prevClose : lastPrice(cleanSym, fallback);
    }

    function computeLocalStorageMetrics(portfolio) {
        var holdings = computeLocalStorageHoldings(portfolio.transactions);
        var totalMarketValue = 0;
        var totalCost = 0;
        var dividendsYTD = 0;
        var yearStart = new Date().getFullYear() + '-01-01';

        holdings.forEach(function (h) {
            var avgCost = h.quantity ? h.totalCost / h.quantity : 0;
            var price = lastPrice(h.symbol, avgCost);
            totalMarketValue += (h.quantity * price);
            totalCost += (h.quantity * avgCost);
        });

        portfolio.transactions.filter(function (t) {
            return t.type === 'dividend' && t.date >= yearStart;
        }).forEach(function (t) {
            dividendsYTD += (t.amount || 0);
        });

        var invested = portfolio.transactions.filter(function (t) {
            return t.type === 'deposit';
        }).reduce(function (s, t) { return s + (t.amount || 0); }, 0) -
            portfolio.transactions.filter(function (t) {
                return t.type === 'withdrawal';
            }).reduce(function (s, t) { return s + (t.amount || 0); }, 0);

        var totalValue = totalMarketValue + (portfolio.cashBalance || 0);
        var totalGain = totalMarketValue - totalCost;
        var totalReturn = totalCost > 0 ? (totalGain / totalCost) * 100 : 0;

        var todayGain = 0;
        holdings.forEach(function (h) {
            var avgCost = h.quantity ? h.totalCost / h.quantity : 0;
            todayGain += h.quantity * (lastPrice(h.symbol, avgCost) - prevClose(h.symbol, avgCost));
        });
        var todayPct = totalValue > 0 ? (todayGain / (totalValue - todayGain)) * 100 : 0;

        var enriched = holdings.map(function (h) {
            var meta = symMeta(h.symbol);
            var avgCost = h.quantity ? h.totalCost / h.quantity : 0;
            var price = lastPrice(h.symbol, avgCost);
            var prev  = prevClose(h.symbol, avgCost);
            var mktVal = h.quantity * price;
            var gain = mktVal - h.totalCost;
            return {
                symbol: h.symbol,
                companyName: meta.name,
                companyNameAr: meta.nameAr,
                sector: meta.sector,
                color: meta.color,
                quantity: h.quantity,
                avgCost: avgCost,
                lastPrice: price,
                prevClose: prev,
                marketValue: mktVal,
                weight: totalMarketValue > 0 ? (mktVal / totalMarketValue) * 100 : 0,
                dayChange: price - prev,
                dayChangePct: prev > 0 ? ((price - prev) / prev) * 100 : 0,
                totalGain: gain,
                totalReturn: h.totalCost > 0 ? (gain / h.totalCost) * 100 : 0
            };
        });

        enriched.sort(function (a, b) { return b.marketValue - a.marketValue; });

        var sectors = {};
        enriched.forEach(function (h) {
            sectors[h.sector] = (sectors[h.sector] || 0) + h.weight;
        });

        var bestHolder = enriched.slice().sort(function (a, b) { return b.totalReturn - a.totalReturn; })[0];
        var worstHolder = enriched.slice().sort(function (a, b) { return a.totalReturn - b.totalReturn; })[0];

        return {
            totalValue: totalValue,
            totalMarketValue: totalMarketValue,
            cashBalance: portfolio.cashBalance || 0,
            invested: invested,
            totalGain: totalGain,
            totalReturn: totalReturn,
            todayGain: todayGain,
            todayPct: todayPct,
            dividendsYTD: dividendsYTD,
            holdings: enriched,
            sectors: sectors,
            bestHolder: bestHolder,
            worstHolder: worstHolder,
            holdingsCount: enriched.length
        };
    }

    function makeDemoPortfolio() {
        var now = new Date();
        return {
            id: 'demo',
            name: 'Local Sandbox Portfolio',
            nameAr: 'محفظة التجربة المحلية',
            currency: 'USD',
            benchmark: 'SPY',
            riskFreeRate: 4.5,
            description: 'US market sandbox portfolio',
            createdAt: now.toISOString().slice(0, 10),
            isDefault: true,
            cashBalance: 5000,
            transactions: [
                { id: 'dep-1', type: 'deposit', date: now.toISOString().slice(0, 10), symbol: null, quantity: null, price: null, commission: 0, tax: 0, currency: 'USD', notes: 'Initial funding', amount: 100000 },
                { id: 'tx-1', type: 'buy', date: now.toISOString().slice(0, 10), symbol: 'AAPL', quantity: 100, price: 190.00, commission: 0, tax: 0, currency: 'USD', notes: '' },
                { id: 'tx-2', type: 'buy', date: now.toISOString().slice(0, 10), symbol: 'MSFT', quantity: 50, price: 420.00, commission: 0, tax: 0, currency: 'USD', notes: '' },
                { id: 'tx-3', type: 'buy', date: now.toISOString().slice(0, 10), symbol: 'GOOGL', quantity: 150, price: 175.00, commission: 0, tax: 0, currency: 'USD', notes: '' }
            ]
        };
    }

    function loadAll() {
        try {
            var raw = localStorage.getItem(KEY);
            if (raw === null) {
                var list = [makeDemoPortfolio()];
                saveAll(list);
                return list;
            }
            return raw ? JSON.parse(raw) : [];
        } catch (_) { return [makeDemoPortfolio()]; }
    }

    function saveAll(list) {
        try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (_) {}
    }

    function getAll() {
        var list = loadAll();
        
        var serverSlots = [
            { id: 'all',         name: 'All Portfolios',       nameAr: 'جميع المحافظ',           currency: 'USD', benchmark: 'SPY', isServer: true, isAggregated: true },
            { id: 'portfolio_1', name: 'Self Improving Brain', nameAr: 'الدماغ ذاتي التحسين', currency: 'USD', benchmark: 'SPY', isServer: true },
            { id: 'portfolio_2', name: 'Capitol Shadow',       nameAr: 'ظل الكابيتول',          currency: 'USD', benchmark: 'SPY', isServer: true },
            { id: 'portfolio_3', name: 'Cautious Sniper',      nameAr: 'القناص الحذر',          currency: 'USD', benchmark: 'SPY', isServer: true }
        ];

        return serverSlots.concat(list);
    }

    function get(id) {
        if (SERVER_PORTFOLIOS.includes(id)) {
            var data = serverCache[id];
            if (!data) {
                if (id === 'all') return { id: 'all', name: 'All Portfolios', nameAr: 'جميع المحافظ', currency: 'USD', benchmark: 'SPY', isServer: true, isAggregated: true };
                return { id: id, name: 'Alpaca Account', currency: 'USD', benchmark: 'SPY', isServer: true };
            }
            return {
                id: id,
                name: data.label,
                nameAr: id === 'all' ? 'جميع المحافظ' :
                        id === 'portfolio_1' ? 'الدماغ ذاتي التحسين' :
                        id === 'portfolio_2' ? 'ظل الكابيتول' :
                                               'القناص الحذر',
                currency: data.currency || 'USD',
                benchmark: data.benchmark || 'SPY',
                riskFreeRate: data.strategy_params?.risk_free_rate || 4.5,
                description: id === 'all' ? ('All Portfolios · ' + (data.source_labels || []).join(' · ')) : data.strategy,
                cashBalance: data.account.cash,
                isServer: true,
                liveConnected: data.live_connected,
                halted: data.halted,
                haltReason: data.halt_reason,
                isAggregated: data.is_aggregated || false,
                transactions: []
            };
        }
        return getLocalStoragePortfolio(id);
    }

    function create(data) {
        var list = loadAll();
        var p = Object.assign({
            id: 'pf-' + Date.now(),
            createdAt: new Date().toISOString().slice(0, 10),
            cashBalance: 0,
            transactions: []
        }, data);
        list.push(p);
        saveAll(list);
        return p;
    }

    function update(id, patch) {
        if (SERVER_PORTFOLIOS.includes(id)) return; // Server portfolios are read-only locally
        var list = loadAll();
        list = list.map(function (p) { return p.id === id ? Object.assign({}, p, patch) : p; });
        saveAll(list);
    }

    function remove(id) {
        if (SERVER_PORTFOLIOS.includes(id)) return;
        var list = loadAll().filter(function (p) { return p.id !== id; });
        saveAll(list);
    }

    function addTransaction(id, tx) {
        if (SERVER_PORTFOLIOS.includes(id)) return;
        var list = loadAll();
        list = list.map(function (p) {
            if (p.id !== id) return p;
            tx.id = 'tx-' + Date.now() + '-' + Math.random().toString(36).slice(2);
            var updated = Object.assign({}, p);
            updated.transactions = p.transactions.concat([tx]);
            if (tx.type === 'deposit') updated.cashBalance += (tx.amount || 0);
            if (tx.type === 'withdrawal') updated.cashBalance -= (tx.amount || 0);
            if (tx.type === 'buy') updated.cashBalance -= (tx.quantity * tx.price + (tx.commission || 0));
            if (tx.type === 'sell') updated.cashBalance += (tx.quantity * tx.price - (tx.commission || 0));
            if (tx.type === 'dividend') updated.cashBalance += (tx.amount || 0);
            return updated;
        });
        saveAll(list);
    }

    function fmt(n, decimals) {
        decimals = decimals === undefined ? 2 : decimals;
        if (typeof n !== 'number') return '0.00';
        return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    }

    global.PFStore = {
        getAll: getAll, get: get,
        create: create, update: update, remove: remove,
        addTransaction: addTransaction,
        computeMetrics: computeMetrics,
        symMeta: symMeta, lastPrice: lastPrice,
        fmt: fmt,
        loadPortfolio: loadPortfolio,
        loadEquityHistory: loadEquityHistory,
        loadMarketIndices: loadMarketIndices,
        fetchLivePrices: fetchLivePrices,
        serverCache: serverCache
    };

}(window));
