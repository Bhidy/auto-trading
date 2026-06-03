const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const fs = require('fs');
const path = require('path');
const https = require('https');

const app = express();
const PORT = process.env.PORT || 3000;

// Behind the Vercel proxy — needed so rate-limiting sees the real client IP.
app.set('trust proxy', 1);

// Security headers. CSP/COEP are disabled because the dashboard intentionally
// uses inline scripts/styles and external font/quote resources; the rest of
// helmet's protections (HSTS, noSniff, frameguard, referrer policy) still apply.
app.use(helmet({ contentSecurityPolicy: false, crossOriginEmbedderPolicy: false }));

// CORS locked to configured origins (default: production + localhost). Same-origin
// requests and tools without an Origin header (curl/health checks) are allowed.
const ALLOWED_ORIGINS = (process.env.DASHBOARD_ALLOWED_ORIGINS
    || 'https://autotradingportfolios.vercel.app,http://localhost:3000')
    .split(',').map(s => s.trim()).filter(Boolean);
app.use(cors({
    origin(origin, cb) {
        if (!origin || ALLOWED_ORIGINS.includes(origin)) return cb(null, true);
        return cb(null, false);
    },
}));

app.use(express.json());

// Rate-limit the API surface (per IP). Tunable via DASHBOARD_RATE_LIMIT.
app.use('/api', rateLimit({
    windowMs: 60 * 1000,
    max: Number(process.env.DASHBOARD_RATE_LIMIT || 120),
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: 'Too many requests — slow down.' },
}));

// FAIL-CLOSED auth for state-mutating endpoints (order placement, closing
// positions). Anonymous trade execution against live brokerage accounts must
// never be possible. When DASHBOARD_ACCESS_TOKEN is unset, mutations are
// disabled entirely; when set, callers must present it as a Bearer token or
// x-access-token header. Read endpoints remain public (showcase).
const ACCESS_TOKEN = process.env.DASHBOARD_ACCESS_TOKEN || '';
const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
app.use((req, res, next) => {
    // Gate ALL mutating verbs, not just POST. DELETE (cancel order / cancel-all /
    // delete watchlist) and PATCH/PUT (replace order / update watchlist) reach the
    // live broker and MUST require the token — anonymous DELETE /orders (cancel-all)
    // would wipe protective bracket stops. Reads (GET/HEAD/OPTIONS) stay public.
    if (!MUTATING_METHODS.has(req.method) || !req.path.startsWith('/api/')) return next();
    if (!ACCESS_TOKEN) {
        return res.status(503).json({
            error: 'Trade actions are disabled. Set DASHBOARD_ACCESS_TOKEN to enable.',
        });
    }
    const bearer = (req.get('authorization') || '').replace(/^Bearer\s+/i, '');
    const provided = bearer || req.get('x-access-token') || '';
    if (provided !== ACCESS_TOKEN) {
        return res.status(401).json({ error: 'Unauthorized.' });
    }
    return next();
});

// Serve static dashboard files
app.use(express.static(path.join(__dirname, 'public')));

// Server Route Redirects for Portfolio clean URLs
app.get('/Portfolio', (req, res) => {
    res.redirect('/portfolio.html');
});
app.get('/Portfolio/:id', (req, res) => {
    res.redirect(`/portfolio-detail.html?id=${req.params.id}`);
});

// Base directories - Support Vercel cloud deployments with zero local dependencies
const IS_VERCEL = process.env.VERCEL || !fs.existsSync('/Users/home/Documents/Auto Trading');
// On Vercel: api/index.js lives at /var/task/ (project root), not in a subdirectory.
// Data files are at /var/task/data/, /var/task/event-driven-bot/data/, etc.
function resolveRootDir() {
    if (!IS_VERCEL) return '/Users/home/Documents/Auto Trading';
    return __dirname;
}
const ROOT_DIR = resolveRootDir();


// Global portfolio configuration
let portfoliosConfig = {};

function loadConfig() {
    // Try multiple config file locations (dashboard > root > env vars)
    const configPaths = [
        path.join(__dirname, '..', 'config', 'portfolios.json'),      // ../config/ from api/
        path.join(ROOT_DIR, 'config', 'portfolios.json'),              // root config/
        path.join(__dirname, 'config', 'portfolios.json'),             // dashboard/config/
    ];

    for (const cp of configPaths) {
        try {
            if (fs.existsSync(cp)) {
                const raw = JSON.parse(fs.readFileSync(cp, 'utf-8'));
                if (raw && Object.keys(raw).length > 0) {
                    portfoliosConfig = raw;
                    console.log(`Portfolios config loaded from: ${cp}`);
                    break;
                }
            }
        } catch (e) {
            console.warn(`Config load attempt failed for ${cp}:`, e.message);
        }
    }

    // If still empty, build from environment variables (cloud-native primary path)
    if (!portfoliosConfig || Object.keys(portfoliosConfig).length === 0) {
        portfoliosConfig = {};
        const portfolioDefs = [
            { id: 'portfolio_1', label: 'Self Improving Brain', account: 'PA3HULQQ8OOH', strategy: 'Multi-factor scoring with regime detection', dir: './' },
            { id: 'portfolio_2', label: 'Capitol Shadow', account: 'PA38R564MIS7', strategy: 'Copy trades from top-performing US politicians', dir: './political-copy-bot' },
            { id: 'portfolio_3', label: 'Cautious Sniper', account: 'PA3M3WI7C58W', strategy: 'Institutional multi-factor: fundamental + technical + news', dir: './event-driven-bot' },
        ];
        for (const p of portfolioDefs) {
            const envKey = process.env[`${p.id.toUpperCase()}_API_KEY`] || '';
            const envSecret = process.env[`${p.id.toUpperCase()}_API_SECRET`] || '';
            portfoliosConfig[p.id] = {
                label: p.label,
                account_number: process.env[`${p.id.toUpperCase()}_ACCOUNT`] || p.account,
                api_key: envKey,
                api_secret: envSecret,
                base_url: process.env.ALPACA_BASE_URL || 'https://paper-api.alpaca.markets',
                data_url: process.env.ALPACA_DATA_URL || 'https://data.alpaca.markets',
                strategy: p.strategy,
                initial_capital: parseInt(process.env[`${p.id.toUpperCase()}_INITIAL_CAPITAL`] || '100000'),
                directory: p.dir
            };
        }
        console.log('Portfolios built from environment variables');
    }

    // Always override API keys from environment variables (highest priority)
    for (const id of Object.keys(portfoliosConfig)) {
        const envKey = process.env[`${id.toUpperCase()}_API_KEY`];
        const envSecret = process.env[`${id.toUpperCase()}_API_SECRET`];
        if (envKey) portfoliosConfig[id].api_key = envKey;
        if (envSecret) portfoliosConfig[id].api_secret = envSecret;
        // Normalize directory paths: convert absolute macOS paths to relative
        if (portfoliosConfig[id].directory && portfoliosConfig[id].directory.startsWith('/')) {
            const leaf = path.basename(portfoliosConfig[id].directory);
            portfoliosConfig[id].directory = './' + (leaf === 'Auto Trading' ? '' : leaf);
        }
    }
    console.log('Portfolios configured:', Object.keys(portfoliosConfig).join(', '));
}

// Initial load
loadConfig();

// Helper to query Alpaca REST API safely
function alpacaRequest(method, url, apiKey, apiSecret, body = null) {
    if (!apiKey || !apiSecret || apiKey.includes('REDACTED') || apiSecret.includes('REDACTED') || apiKey === 'MOCK_KEY_ID_REDACTED') {
        return Promise.reject(new Error('Alpaca keys are redacted or missing; running in mock fallback mode.'));
    }
    return new Promise((resolve, reject) => {
        try {
            const parsedUrl = new URL(url);
            const options = {
                method: method,
                hostname: parsedUrl.hostname,
                path: parsedUrl.pathname + parsedUrl.search,
                headers: {
                    'APCA-API-KEY-ID': apiKey,
                    'APCA-API-SECRET-KEY': apiSecret,
                    'Content-Type': 'application/json'
                },
                timeout: 10000 // 10 seconds for serverless cold starts
            };
            const req = https.request(options, (res) => {
                let data = '';
                res.on('data', (chunk) => { data += chunk; });
                res.on('end', () => {
                    if (res.statusCode >= 200 && res.statusCode < 300) {
                        try {
                            resolve(JSON.parse(data));
                        } catch (e) {
                            resolve(data);
                        }
                    } else {
                        reject(new Error(`Alpaca API error: ${res.statusCode} ${data}`));
                    }
                });
            });
            req.on('error', (err) => { reject(err); });
            req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
            if (body) {
                req.write(JSON.stringify(body));
            }
            req.end();
        } catch (e) {
            reject(e);
        }
    });
}

// Helper to read JSON files safely
function readJsonFile(filePath, defaultValue = {}) {
    try {
        if (fs.existsSync(filePath)) {
            const content = fs.readFileSync(filePath, 'utf-8');
            return JSON.parse(content);
        }
    } catch (e) {
        console.error(`Error reading file ${filePath}:`, e.message);
    }
    return defaultValue;
}

// Health/debug endpoint
app.get('/api/health', (req, res) => {
    const pf1 = getPortfolioPaths('portfolio_1');
    const info = {
        rootDir: ROOT_DIR,
        apiDir: __dirname,
        cwd: process.cwd(),
        isVercel: IS_VERCEL,
        pf1: pf1,
    };
    if (pf1) {
        info.files = {};
        for (const [k, p] of Object.entries(pf1)) {
            if (typeof p === 'string') info.files[k] = { path: p, exists: fs.existsSync(p), size: fs.existsSync(p) ? fs.statSync(p).size : 0 };
        }
    }
    res.json(info);
});

// Helper to get local data paths for a portfolio (cloud-safe, uses copied data dirs)
function getPortfolioPaths(id) {
    const item = portfoliosConfig[id];
    if (!item) return null;
    // On Vercel, data files are copied into subdirs by buildCommand.
    // Use simple relative paths from the dashboard root.
    let relDir = item.directory || './';
    // Strip any absolute macOS path prefix
    if (relDir.startsWith('/')) {
        relDir = './';
    }
    const baseDir = path.resolve(ROOT_DIR, relDir);
    return {
        baseDir,
        state: id === 'portfolio_1' ? path.join(baseDir, 'data/portfolio_state.json') :
               id === 'portfolio_2' ? path.join(baseDir, 'data/portfolio_state.json') :
                                      path.join(baseDir, 'data/bot_state.json'),
        tradeLog: path.join(baseDir, 'data/trade_log.json'),
        signals: id === 'portfolio_1' ? path.join(baseDir, 'data/signals.json') :
                 id === 'portfolio_2' ? path.join(baseDir, 'data/research_results.json') :
                                        path.join(baseDir, 'data/signals.json'),
        journalDir: path.join(baseDir, 'journal'),
        strategyParams: path.join(baseDir, 'data/strategy_params.json'),
        learningReport: path.join(baseDir, 'data/learning_report.json')
    };
}


// ──────────────────────────────────────────────────────────────────────────
// SYSTEM INTELLIGENCE — surfaces the hardening engine's data files (the new
// execution-quality / validation / accounting / governance / reconciliation
// outputs). Pure file reads + trade-log derivations, so it always works whether
// or not the Alpaca keys are live. Files that don't exist yet degrade to empty.
// ──────────────────────────────────────────────────────────────────────────

function getIntelligencePaths(id) {
    const base = getPortfolioPaths(id);
    if (!base) return null;
    const d = (f) => path.join(base.baseDir, 'data', f);
    return {
        ...base,
        reconciliation: d('reconciliation_report.json'),
        orderState: d('order_state.json'),
        paramChangeLog: d('param_change_log.json'),
        governanceAudit: d('governance_audit.json'),
        lastGood: d('strategy_params.last_good.json'),
    };
}

// Derive execution-quality + accounting facts from the schema-v2 trade log.
function deriveTradeLogIntelligence(tradeLog) {
    const trades = Array.isArray(tradeLog) ? tradeLog : [];
    const closed = trades.filter(t => t.status === 'closed');
    const withSlip = trades.filter(t => typeof t.slippage_pct === 'number');
    const avgSlippage = withSlip.length
        ? withSlip.reduce((s, t) => s + t.slippage_pct, 0) / withSlip.length : null;

    let grossPnl = 0, fees = 0, netPnl = 0, feeKnown = 0;
    closed.forEach(t => {
        if (typeof t.gross_pnl === 'number') { grossPnl += t.gross_pnl; feeKnown++; }
        if (typeof t.fees === 'number') fees += t.fees;
        const net = (typeof t.realized_pnl === 'number') ? t.realized_pnl
                  : (typeof t.pnl === 'number') ? t.pnl : 0;
        netPnl += net;
    });

    const orderClasses = {};
    const borrow = { etb: 0, htb: 0, unknown: 0 };
    trades.forEach(t => {
        const oc = t.order_class || 'unspecified';
        orderClasses[oc] = (orderClasses[oc] || 0) + 1;
        if (t.side === 'sell' || t.side === 'short') {
            if (t.borrow_status === 'etb') borrow.etb++;
            else if (t.borrow_status === 'htb') borrow.htb++;
            else if (t.borrow_status) borrow.unknown++;
        }
    });

    const schemaV2 = trades.filter(t => t.schema_version >= 2).length;
    return {
        total_trades: trades.length,
        closed_trades: closed.length,
        schema_v2_trades: schemaV2,
        avg_slippage_pct: avgSlippage === null ? null : Number(avgSlippage.toFixed(4)),
        slippage_sample: withSlip.length,
        accounting: {
            gross_pnl: Number(grossPnl.toFixed(2)),
            fees: Number(fees.toFixed(2)),
            net_pnl: Number(netPnl.toFixed(2)),
            fee_aware_trades: feeKnown,
        },
        order_classes: orderClasses,
        borrow_status: borrow,
    };
}

function summarizeWorkingOrders(orderState) {
    const WORKING = new Set(['new', 'accepted', 'partially_filled', 'pending_new',
        'held', 'pending_replace', 'pending_cancel']);
    const state = (orderState && typeof orderState === 'object') ? orderState : {};
    const working = [];
    let stale = 0;
    const now = Date.now();
    Object.entries(state).forEach(([oid, v]) => {
        if (!v || !WORKING.has(v.status)) return;
        let ageS = null;
        const ts = v.updated_at;
        if (ts) {
            const t = Date.parse(String(ts).replace('Z', '+00:00'));
            if (!isNaN(t)) ageS = Math.round((now - t) / 1000);
        }
        if (ageS !== null && ageS >= 7200) stale++;
        working.push({ order_id: oid, symbol: v.symbol, side: v.side,
            status: v.status, age_seconds: ageS });
    });
    return { working_count: working.length, stale_count: stale, working };
}

app.get('/api/portfolio/:id/intelligence', (req, res) => {
    loadConfig();
    const id = req.params.id;
    const paths = getIntelligencePaths(id);
    if (!paths) return res.status(404).json({ error: 'unknown portfolio' });

    const tradeLog = readJsonFile(paths.tradeLog, []);
    const reconciliation = readJsonFile(paths.reconciliation, null);
    const orderState = readJsonFile(paths.orderState, {});
    const paramLog = readJsonFile(paths.paramChangeLog, []);
    const lastGood = readJsonFile(paths.lastGood, null);
    const strategyParams = readJsonFile(paths.strategyParams, {});
    const learningReport = readJsonFile(paths.learningReport, {});

    const latestDecision = Array.isArray(paramLog) && paramLog.length
        ? paramLog[paramLog.length - 1] : null;
    const gate = latestDecision && latestDecision.gate ? latestDecision.gate : null;

    res.json({
        id,
        label: (portfoliosConfig[id] || {}).label || id,
        execution: deriveTradeLogIntelligence(tradeLog),
        order_state: summarizeWorkingOrders(orderState),
        reconciliation: reconciliation || { unavailable: true },
        validation: {
            current_oos_sharpe: gate ? gate.current_oos_sharpe : null,
            candidate_oos_sharpe: gate ? gate.candidate_oos_sharpe : null,
            pbo: gate ? gate.pbo : null,
            deflated_sharpe: gate ? gate.deflated_sharpe : null,
            challenger_sharpe: gate ? gate.challenger_sharpe : null,
            beats_challenger: gate ? gate.beats_challenger : null,
            n_windows: gate ? gate.n_windows : null,
            screen_reasons: gate ? (gate.screen_reasons || []) : [],
            self_learning: id === 'portfolio_1',
        },
        governance: {
            decisions: Array.isArray(paramLog) ? paramLog.slice(-8).reverse() : [],
            last_known_good: lastGood,
            total_decisions: Array.isArray(paramLog) ? paramLog.length : 0,
        },
        strategy_params: strategyParams,
        learning_report: learningReport,
    });
});

// Cross-portfolio concentration (R1): combined single-name + sector exposure.
const SECTOR_MAP = {
    SPY: 'Index', QQQ: 'Index', DIA: 'Index', IWM: 'Index',
    NVDA: 'Technology', AAPL: 'Technology', MSFT: 'Technology', GOOGL: 'Technology',
    META: 'Technology', AMZN: 'Consumer', TSLA: 'Consumer',
    XLK: 'Technology', XLE: 'Energy', XLF: 'Financials', XLV: 'Healthcare',
    XLY: 'Consumer', XLI: 'Industrials', XLC: 'Communications', XLB: 'Materials',
    XLU: 'Utilities', XLRE: 'Real Estate',
    BIL: 'Defensive', SHY: 'Defensive', TLT: 'Defensive', GLD: 'Defensive',
    JPM: 'Financials', MS: 'Financials',
    // P2 (Capitol Shadow) / P3 (Cautious Sniper) single names — classify into real
    // GICS sectors so combined exposure isn't understated as a large "Other" bucket.
    CSCO: 'Technology', INTU: 'Technology', TER: 'Technology', PANW: 'Technology',
    MPC: 'Energy', VLO: 'Energy', EOG: 'Energy',
    WMT: 'Consumer', HD: 'Consumer', PG: 'Consumer',
    MEDP: 'Healthcare', PH: 'Industrials', T: 'Communications',
};

app.get('/api/intelligence/cross-portfolio', async (req, res) => {
    loadConfig();
    const singleNameCap = 10.0, sectorCap = 30.0;
    let totalEquity = 0;
    const bySymbol = {}, bySector = {};
    const books = [];

    for (const id of Object.keys(portfoliosConfig)) {
        const d = await fetchPortfolioData(id);
        if (!d) continue;
        const equity = d.account ? parseFloat(d.account.equity) : 100000;
        totalEquity += equity;
        const positions = (d.positions && d.positions.length)
            ? d.positions.map(p => ({ symbol: p.symbol, mv: Math.abs(parseFloat(p.market_value || 0)) }))
            // Fallback to committed state cost-basis when Alpaca isn't connected.
            : Object.entries((d.localState && d.localState.positions) || {}).map(([sym, pos]) =>
                ({ symbol: sym, mv: Math.abs((pos.qty || 0) * (pos.avg_price || 0)) }));
        books.push({ portfolio_id: id, label: d.cfg.label, equity, positions });
        positions.forEach(p => {
            if (!p.symbol) return;
            if (!bySymbol[p.symbol]) bySymbol[p.symbol] = { mv: 0, books: new Set() };
            bySymbol[p.symbol].mv += p.mv;
            bySymbol[p.symbol].books.add(id);
            const sec = SECTOR_MAP[p.symbol] || 'Other';
            bySector[sec] = (bySector[sec] || 0) + p.mv;
        });
    }

    const pct = v => totalEquity > 0 ? Number((v / totalEquity * 100).toFixed(3)) : 0;
    const symbols = Object.entries(bySymbol).map(([sym, d]) => ({
        symbol: sym, market_value: Number(d.mv.toFixed(2)), pct_of_total: pct(d.mv),
        books: Array.from(d.books), breach: pct(d.mv) > singleNameCap,
    })).sort((a, b) => b.pct_of_total - a.pct_of_total);
    const sectors = Object.entries(bySector).map(([sec, mv]) => ({
        sector: sec, market_value: Number(mv.toFixed(2)), pct_of_total: pct(mv),
        breach: pct(mv) > sectorCap,
    })).sort((a, b) => b.pct_of_total - a.pct_of_total);

    res.json({
        total_equity: Number(totalEquity.toFixed(2)),
        single_name_cap_pct: singleNameCap,
        sector_cap_pct: sectorCap,
        books: books.map(b => ({ portfolio_id: b.portfolio_id, label: b.label,
            equity: b.equity, positions: b.positions.length })),
        by_symbol: symbols,
        by_sector: sectors,
        single_name_breaches: symbols.filter(s => s.breach).map(s => s.symbol),
        sector_breaches: sectors.filter(s => s.breach).map(s => s.sector),
        ok: !symbols.some(s => s.breach) && !sectors.some(s => s.breach),
    });
});

// ──────────────────────────────────────────────────────────────────────────
// API ENDPOINTS
// ──────────────────────────────────────────────────────────────────────────

// 1. Get portfolios metadata (secrets stripped)
app.get('/api/portfolios', async (req, res) => {
    loadConfig(); // reload config to pick up any changes
    const list = {};
    for (const [id, item] of Object.entries(portfoliosConfig)) {
        list[id] = {
            id: id,
            label: item.label,
            strategy: item.strategy,
            initial_capital: item.initial_capital || 100000,
            account_number: item.account_number,
            currency: 'USD',
            benchmark: id === 'portfolio_1' ? 'SPY' : id === 'portfolio_2' ? 'SPY' : 'SPY'
        };
    }
    res.json(list);
});

// ─── ALL PORTFOLIOS AGGREGATED ENDPOINTS ────────────────────────────────────

async function fetchPortfolioData(id) {
    const cfg = portfoliosConfig[id];
    if (!cfg) return null;
    const paths = getPortfolioPaths(id);
    const localState = readJsonFile(paths.state, {});
    let account = null;
    let positions = [];
    let orders = [];
    let liveConnected = false;
    try {
        account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
        positions = await alpacaRequest('GET', `${cfg.base_url}/v2/positions`, cfg.api_key, cfg.api_secret);
        orders = await alpacaRequest('GET', `${cfg.base_url}/v2/orders?status=open`, cfg.api_key, cfg.api_secret);
        liveConnected = true;
    } catch (e) {}
    const tradeLog = readJsonFile(paths.tradeLog, []);
    const signalsData = readJsonFile(paths.signals, {});
    const strategyParams = readJsonFile(paths.strategyParams, {});
    const learningReport = readJsonFile(paths.learningReport, {});
    return { id, cfg, paths, localState, account, positions, orders, liveConnected, tradeLog, signalsData, strategyParams, learningReport };
}

function parsePositionLive(p, equity) {
    const qty = parseFloat(p.qty);
    const entry = parseFloat(p.avg_entry_price);
    const price = parseFloat(p.current_price);
    const mktVal = parseFloat(p.market_value);
    const pl = parseFloat(p.unrealized_pl);
    const plpc = parseFloat(p.unrealized_plpc) * 100;
    const prev = parseFloat(p.lastday_price || price);
    const dayChg = price - prev;
    const dayChgPct = prev > 0 ? (dayChg / prev) * 100 : 0;
    return {
        symbol: p.symbol,
        asset_class: p.asset_class || 'us_equity',
        exchange: p.exchange || '',
        quantity: qty,
        side: p.side || 'long',
        avgCost: entry,
        lastPrice: price,
        marketValue: mktVal,
        cost_basis: parseFloat(p.cost_basis || (qty * entry)),
        unrealized_pl: pl,
        unrealized_plpc: plpc,
        unrealized_intraday_pl: parseFloat(p.unrealized_intraday_pl || 0),
        unrealized_intraday_plpc: parseFloat(p.unrealized_intraday_plpc || 0) * 100,
        dayChange: dayChg,
        dayChangePct: dayChgPct,
        lastday_price: prev,
        change_today: parseFloat(p.change_today || 0) * 100,
        weight: equity > 0 ? (mktVal / equity) * 100 : 0,
        source_portfolio: '',
        source_label: ''
    };
}

// 2. Fetch live and local status for a portfolio card
app.get('/api/portfolio/all/summary', async (req, res) => {
    loadConfig();
    let totalEquity = 0, totalCash = 0, totalDayPnL = 0, totalPositions = 0;
    const labels = [];
    let anyLive = false;
    for (const id of Object.keys(portfoliosConfig)) {
        const d = await fetchPortfolioData(id);
        if (!d) continue;
        labels.push(d.cfg.label);
        if (d.account) {
            totalEquity += parseFloat(d.account.equity);
            totalCash += parseFloat(d.account.cash);
            const dayPnL = parseFloat(d.account.equity) - parseFloat(d.account.last_equity);
            totalDayPnL += dayPnL;
            totalPositions += d.positions.length;
            anyLive = true;
        } else {
            const localState = d.localState;
            if (id === 'portfolio_1') { totalEquity += parseFloat(localState.equity || 100000); totalCash += parseFloat(localState.cash || 100000); totalDayPnL += parseFloat(localState.day_pnl || 0); totalPositions += localState.positions ? Object.keys(localState.positions).length : 0; }
            else if (id === 'portfolio_2') { const acct = localState.account || {}; totalEquity += parseFloat(acct.portfolio_value || acct.equity || 100000); totalCash += parseFloat(acct.cash || 100000); totalPositions += localState.positions ? localState.positions.length : 0; }
            else { totalEquity += parseFloat(localState.equity || 100000); totalCash += parseFloat(localState.cash || 100000); totalPositions += localState.positions || 0; }
        }
    }
    const totalDayPnlPct = 300000 > 0 ? (totalDayPnL / 300000) * 100 : 0;
    res.json({
        id: 'all',
        label: 'All Portfolios',
        strategy: `Aggregated: ${labels.join(' · ')}`,
        equity: totalEquity,
        cash: totalCash,
        day_pnl: totalDayPnL,
        day_pnl_pct: totalDayPnlPct,
        positions_count: totalPositions,
        halted: false,
        halt_reason: null,
        live_connected: anyLive
    });
});

app.get('/api/portfolio/all/details', async (req, res) => {
    loadConfig();
    let totalEquity = 0, totalCash = 0, totalBuyingPower = 0, totalLastEquity = 0;
    let totalLongMv = 0, totalShortMv = 0, totalInitialMargin = 0, totalMaintenanceMargin = 0;
    let totalDayPnL = 0;
    let anyLiveConnected = false;
    let aggregatedPositions = {};
    let aggregatedOrders = [];
    let aggregatedTradeLog = [];
    let aggregatedSignals = [];
    let aggregatedStrategyParams = {};
    let aggregatedLearningReports = [];

    for (const id of Object.keys(portfoliosConfig)) {
        const d = await fetchPortfolioData(id);
        if (!d) continue;
        if (d.account) {
            anyLiveConnected = true;
            totalEquity += parseFloat(d.account.equity);
            totalCash += parseFloat(d.account.cash);
            totalBuyingPower += parseFloat(d.account.buying_power);
            totalLastEquity += parseFloat(d.account.last_equity);
            totalLongMv += parseFloat(d.account.long_market_value || 0);
            totalShortMv += parseFloat(d.account.short_market_value || 0);
            totalInitialMargin += parseFloat(d.account.initial_margin || 0);
            totalMaintenanceMargin += parseFloat(d.account.maintenance_margin || 0);
            const dayPnL = parseFloat(d.account.equity) - parseFloat(d.account.last_equity);
            totalDayPnL += dayPnL;
            d.positions.forEach(p => {
                const parsed = parsePositionLive(p, parseFloat(d.account.equity));
                parsed.source_portfolio = id;
                parsed.source_label = d.cfg.label;
                const key = p.symbol + '|' + id;
                aggregatedPositions[key] = parsed;
            });
        } else {
            totalEquity += 100000;
            totalCash += 100000;
            totalBuyingPower += 200000;
            totalLastEquity += 100000;
        }
        if (d.orders && d.orders.length) aggregatedOrders = aggregatedOrders.concat(d.orders);
        if (d.tradeLog && d.tradeLog.length) {
            d.tradeLog.forEach(t => { t.source_portfolio = id; t.source_label = d.cfg.label; });
            aggregatedTradeLog = aggregatedTradeLog.concat(d.tradeLog);
        }
        if (d.signalsData && d.signalsData.signals) {
            d.signalsData.signals.forEach(s => { s.source_portfolio = id; });
            aggregatedSignals = aggregatedSignals.concat(d.signalsData.signals || []);
        }
        if (d.learningReport && Object.keys(d.learningReport).length) aggregatedLearningReports.push({ id, label: d.cfg.label, report: d.learningReport });
    }

    const totalDayPnlPct = totalLastEquity > 0 ? (totalDayPnL / totalLastEquity) * 100 : 0;
    const positionsList = Object.values(aggregatedPositions);

    // Merge positions across portfolios (same symbol, different portfolios)
    const mergedPositions = {};
    positionsList.forEach(p => {
        const symbolKey = p.symbol;
        if (!mergedPositions[symbolKey]) {
            mergedPositions[symbolKey] = { ...p, source_portfolio: '', source_label: '' };
        } else {
            const existing = mergedPositions[symbolKey];
            const totalQty = existing.quantity + p.quantity;
            existing.avgCost = (existing.avgCost * existing.quantity + p.avgCost * p.quantity) / totalQty;
            existing.quantity = totalQty;
            existing.marketValue += p.marketValue;
            existing.cost_basis += p.cost_basis;
            existing.unrealized_pl += p.unrealized_pl;
            existing.unrealized_plpc = existing.cost_basis > 0 ? (existing.unrealized_pl / existing.cost_basis) * 100 : 0;
            existing.weight = totalEquity > 0 ? (existing.marketValue / totalEquity) * 100 : 0;
            existing.dayChange = (existing.lastPrice - existing.lastday_price);
            existing.dayChangePct = existing.lastday_price > 0 ? (existing.dayChange / existing.lastday_price) * 100 : 0;
        }
    });

    const finalPositions = Object.values(mergedPositions);

    // Rebase EVERY position weight to the combined-book equity. parsePositionLive
    // computed each weight against its source portfolio's ~$100K equity, and the
    // merge above only rebased symbols held in >1 portfolio — so single-portfolio
    // positions stayed ~3x over-weighted. That inflated the aggregate Sector
    // Exposure, Top-5 concentration, Largest Position and every $-of-weight tooltip
    // (weights summed to ~202% instead of the true deployment %). One pass here is
    // the single source of truth for aggregate weight, fixing the whole cascade.
    finalPositions.forEach(p => {
        p.weight = totalEquity > 0 ? (p.marketValue / totalEquity) * 100 : 0;
    });

    res.json({
        id: 'all',
        label: 'All Portfolios',
        currency: 'USD',
        benchmark: 'SPY',
        live_connected: anyLiveConnected,
        halted: false,
        halt_reason: null,
        account: {
            equity: totalEquity,
            cash: totalCash,
            buying_power: totalBuyingPower,
            day_pnl: totalDayPnL,
            day_pnl_pct: totalDayPnlPct,
            last_equity: totalLastEquity,
            long_market_value: totalLongMv,
            short_market_value: totalShortMv,
            initial_margin: totalInitialMargin,
            maintenance_margin: totalMaintenanceMargin,
            daytrade_count: 0,
            pattern_day_trader: false,
            multiplier: 4,
            regt_buying_power: totalCash * 2,
            daytrading_buying_power: totalCash * 4,
            non_marginable_buying_power: totalCash,
            accrued_fees: 0,
            portfolio_value: totalEquity,
            shorting_enabled: true,
            account_status: 'ACTIVE',
            crypto_status: 'ACTIVE',
            options_level: 0,
            created_at: null,
            is_aggregated: true,
            portfolios_included: Object.keys(portfoliosConfig).length
        },
        positions: finalPositions,
        orders: aggregatedOrders,
        trade_log: aggregatedTradeLog,
        signals: { signals: aggregatedSignals, is_aggregated: true },
        strategy_params: aggregatedStrategyParams,
        learning_report: aggregatedLearningReports.length ? aggregatedLearningReports : {},
        is_aggregated: true,
        source_count: Object.keys(portfoliosConfig).length,
        source_labels: Object.values(portfoliosConfig).map(c => c.label)
    });
});

app.get('/api/portfolio/all/equity-history', async (req, res) => {
    loadConfig();
    const period = req.query.period || '3M';
    const timeframe = req.query.timeframe || '1D';
    const portfolioCount = Object.keys(portfoliosConfig).length;
    const baseCapital = portfolioCount * 100000;

    let combinedHistory = {};
    let dateContributors = {};

    for (const id of Object.keys(portfoliosConfig)) {
        const cfg = portfoliosConfig[id];
        try {
            const historyUrl = `${cfg.base_url}/v2/account/portfolio/history?period=${period}&timeframe=${timeframe}&intraday_reporting=market_hours&pnl_reset=per_day`;
            const alpacaHistory = await alpacaRequest('GET', historyUrl, cfg.api_key, cfg.api_secret);
            if (alpacaHistory && alpacaHistory.timestamp) {
                for (let i = 0; i < alpacaHistory.timestamp.length; i++) {
                    const ts = alpacaHistory.timestamp[i];
                    const eq = parseFloat(alpacaHistory.equity[i] || 0);
                    if (eq > 0) {
                        const dateObj = timeframe === '1D' || timeframe === '1Day'
                            ? new Date(ts * 1000).toISOString().slice(0, 10)
                            : new Date(ts * 1000).toISOString();
                        if (!combinedHistory[dateObj]) { combinedHistory[dateObj] = 0; dateContributors[dateObj] = 0; }
                        combinedHistory[dateObj] += eq;
                        dateContributors[dateObj] += 1;
                    }
                }
            }
        } catch (e) {}
    }

    // For dates where fewer portfolios contributed, add $100K per missing portfolio
    for (const d of Object.keys(combinedHistory)) {
        const missing = portfolioCount - (dateContributors[d] || 0);
        if (missing > 0) combinedHistory[d] += missing * 100000;
    }

    if (Object.keys(combinedHistory).length === 0) {
        const seedDate = new Date(); seedDate.setDate(seedDate.getDate() - 30);
        combinedHistory[seedDate.toISOString().slice(0, 10)] = baseCapital;
        let todayEq = 0;
        for (const id of Object.keys(portfoliosConfig)) {
            const paths = getPortfolioPaths(id);
            const localState = readJsonFile(paths.state, {});
            todayEq += parseFloat(localState.equity || 100000);
        }
        combinedHistory[new Date().toISOString().slice(0, 10)] = todayEq;
    }

    const dates = Object.keys(combinedHistory).sort();
    const history = dates.map(d => ({
        date: d,
        equity: Math.round(combinedHistory[d] * 100) / 100,
        profit_loss: Math.round((combinedHistory[d] - baseCapital) * 100) / 100,
        profit_loss_pct: Math.round(((combinedHistory[d] - baseCapital) / baseCapital) * 10000) / 100
    }));

    const periodDaysMap = { '1W': 5, '1M': 21, '3M': 63, '6M': 126, '1A': 252, '1Y': 252, 'All': 252 };
    const targetDays = periodDaysMap[period] || 63;
    const isDaily = (timeframe === '1D' || timeframe === '1Day');

    if (isDaily && history.length < 15) {
        const firstRealPoint = history[0];
        if (firstRealPoint) {
            // Extend backward with REAL persisted equity history (never fabricated).
            const backfill = await realEquityBackfill('all', firstRealPoint.date, baseCapital);
            if (backfill.length > 0) {
                res.json({ source: 'alpaca+supabase', base_value: baseCapital, history: backfill.concat(history) });
                return;
            }
        }
    }
    res.json({ source: 'alpaca', base_value: baseCapital, history });
});

// 2. Fetch live and local status for a portfolio card
app.get('/api/portfolio/:id/summary', async (req, res) => {
    const id = req.params.id;
    const cfg = portfoliosConfig[id];
    if (!cfg) {
        return res.status(404).json({ error: 'Portfolio not found' });
    }

    const paths = getPortfolioPaths(id);
    const localState = readJsonFile(paths.state, {});

    let liveEquity = 100000;
    let liveCash = 100000;
    let liveDayPnL = 0;
    let liveDayPnLPct = 0;
    let livePositionsCount = 0;
    let isHalted = localState.halted || false;
    let haltReason = localState.halt_reason || null;
    let isLiveConnected = false;

    // Attempt to query live Alpaca Account info
    try {
        const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
        liveEquity = parseFloat(account.equity);
        liveCash = parseFloat(account.cash);
        
        // Alpaca provides day_pl and day_plpc (percentage)
        liveDayPnL = parseFloat(account.equity) - parseFloat(account.last_equity);
        liveDayPnLPct = parseFloat(account.last_equity) > 0 ? (liveDayPnL / parseFloat(account.last_equity)) * 100 : 0;
        
        const positions = await alpacaRequest('GET', `${cfg.base_url}/v2/positions`, cfg.api_key, cfg.api_secret);
        livePositionsCount = positions.length;
        isLiveConnected = true;
    } catch (e) {
        console.warn(`[Summary] Live Alpaca request failed for ${id}, falling back to local files:`, e.message);
        // Local state fallback
        if (id === 'portfolio_1') {
            liveEquity = localState.equity || 100000;
            liveCash = localState.cash || 100000;
            liveDayPnL = localState.day_pnl || 0;
            liveDayPnLPct = (localState.day_pnl_pct || 0) * 100;
            livePositionsCount = localState.positions ? Object.keys(localState.positions).length : 0;
        } else if (id === 'portfolio_2') {
            const acct = localState.account || {};
            liveEquity = parseFloat(acct.portfolio_value || acct.equity || 100000);
            liveCash = parseFloat(acct.cash || 100000);
            liveDayPnLPct = parseFloat(acct.daily_pnl_pct || 0);
            liveDayPnL = liveEquity * (liveDayPnLPct / 100);
            livePositionsCount = localState.positions ? localState.positions.length : 0;
        } else if (id === 'portfolio_3') {
            liveEquity = localState.equity || 100000;
            liveCash = localState.cash || 100000;
            livePositionsCount = localState.positions || 0;
            liveDayPnL = 0; // default local
            liveDayPnLPct = 0;
        }
    }

    res.json({
        id: id,
        label: cfg.label,
        account_number: cfg.account_number,
        strategy: cfg.strategy,
        equity: liveEquity,
        cash: liveCash,
        day_pnl: liveDayPnL,
        day_pnl_pct: liveDayPnLPct,
        positions_count: livePositionsCount,
        halted: isHalted,
        halt_reason: haltReason,
        live_connected: isLiveConnected
    });
});

// 3. Fetch comprehensive details for a portfolio dashboard
app.get('/api/portfolio/:id/details', async (req, res) => {
    const id = req.params.id;
    const cfg = portfoliosConfig[id];
    if (!cfg) {
        return res.status(404).json({ error: 'Portfolio not found' });
    }

    const paths = getPortfolioPaths(id);
    const localState = readJsonFile(paths.state, {});
    const tradeLog = readJsonFile(paths.tradeLog, []);
    const signalsData = readJsonFile(paths.signals, {});
    const strategyParams = readJsonFile(paths.strategyParams, {});
    const learningReport = readJsonFile(paths.learningReport, {});

    let liveAccount = null;
    let livePositions = [];
    let liveOrders = [];
    let isLiveConnected = false;

    // Fetch live Alpaca details
    try {
        liveAccount = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
        livePositions = await alpacaRequest('GET', `${cfg.base_url}/v2/positions`, cfg.api_key, cfg.api_secret);
        liveOrders = await alpacaRequest('GET', `${cfg.base_url}/v2/orders?status=open`, cfg.api_key, cfg.api_secret);
        isLiveConnected = true;
    } catch (e) {
        console.warn(`[Details] Live Alpaca request failed for ${id}, falling back to local files:`, e.message);
    }

    // Synthesize response positions if live request failed
    let positionsList = [];
    if (isLiveConnected) {
        positionsList = livePositions.map(p => {
            const qty = parseFloat(p.qty);
            const entry = parseFloat(p.avg_entry_price);
            const price = parseFloat(p.current_price);
            const mktVal = parseFloat(p.market_value);
            const pl = parseFloat(p.unrealized_pl);
            const plpc = parseFloat(p.unrealized_plpc) * 100;
            const prev = parseFloat(p.lastday_price || price);
            const dayChg = price - prev;
            const dayChgPct = prev > 0 ? (dayChg / prev) * 100 : 0;
            
            return {
                symbol: p.symbol,
                asset_class: p.asset_class || 'us_equity',
                exchange: p.exchange || '',
                quantity: qty,
                side: p.side || 'long',
                avgCost: entry,
                lastPrice: price,
                marketValue: mktVal,
                cost_basis: parseFloat(p.cost_basis || (qty * entry)),
                unrealized_pl: pl,
                unrealized_plpc: plpc,
                unrealized_intraday_pl: parseFloat(p.unrealized_intraday_pl || 0),
                unrealized_intraday_plpc: parseFloat(p.unrealized_intraday_plpc || 0) * 100,
                dayChange: dayChg,
                dayChangePct: dayChgPct,
                lastday_price: prev,
                change_today: parseFloat(p.change_today || 0) * 100,
                weight: parseFloat(liveAccount.equity) > 0 ? (mktVal / parseFloat(liveAccount.equity)) * 100 : 0,
                sector: id === 'portfolio_2' ? 'Gov Copy' :
                        id === 'portfolio_3' ? (p.symbol === 'CSCO' || p.symbol === 'PANW' ? 'Tech' : 'Financials') : 'Quant'
            };
        });
    } else {
        // Fallback mapping of positions from local json
        if (id === 'portfolio_1' && localState.positions) {
            const totalEq = localState.equity || 100000;
            positionsList = Object.entries(localState.positions).map(([sym, p]) => {
                const qty = p.qty;
                const entry = p.avg_price;
                const mktVal = qty * entry;
                return {
                    symbol: sym,
                    quantity: qty,
                    avgCost: entry,
                    lastPrice: 0,       // unknown — not available from local state without live API
                    marketValue: mktVal,
                    unrealized_pl: 0,
                    unrealized_plpc: 0,
                    dayChange: 0,
                    dayChangePct: 0,
                    weight: totalEq > 0 ? (mktVal / totalEq) * 100 : 0,
                    sector: 'Quant',
                    isStale: true
                };
            });
        } else if (id === 'portfolio_2' && localState.positions) {
            const totalEq = parseFloat(localState.account?.portfolio_value || 100000);
            positionsList = (localState.positions || []).map(p => {
                const qty = parseFloat(p.qty);
                const entry = parseFloat(p.avg_entry);
                const mktVal = parseFloat(p.market_value);
                const price = qty > 0 ? mktVal / qty : entry;
                return {
                    symbol: p.symbol,
                    quantity: qty,
                    avgCost: entry,
                    lastPrice: price,
                    marketValue: mktVal,
                    unrealized_pl: parseFloat(p.unrealized_pl || 0),
                    unrealized_plpc: parseFloat(p.unrealized_plpc || 0) * 100,
                    dayChange: 0,
                    dayChangePct: 0,
                    weight: totalEq > 0 ? (mktVal / totalEq) * 100 : 0,
                    sector: 'Gov Copy'
                };
            });
        } else if (id === 'portfolio_3') {
            // Read from latest journal for details if bot_state doesn't list full pos
            let journals = [];
            try {
                if (fs.existsSync(paths.journalDir)) {
                    const files = fs.readdirSync(paths.journalDir).filter(f => f.endsWith('.json')).sort();
                    if (files.length > 0) {
                        journals = readJsonFile(path.join(paths.journalDir, files[files.length - 1]), []);
                    }
                }
            } catch (e) {
                console.error("Error reading portfolio_3 journal files:", e);
            }
            const lastJournal = journals[journals.length - 1] || {};
            const totalEq = localState.equity || 100000;
            positionsList = (lastJournal.positions || []).map(p => {
                const qty = parseFloat(p.qty);
                const entry = parseFloat(p.entry);
                const price = parseFloat(p.current);
                const mktVal = parseFloat(p.market_value);
                return {
                    symbol: p.symbol,
                    quantity: qty,
                    avgCost: entry,
                    lastPrice: price,
                    marketValue: mktVal,
                    unrealized_pl: parseFloat(p.unrealized_pl || 0),
                    unrealized_plpc: parseFloat(p.pnl_pct || 0),
                    dayChange: 0,
                    dayChangePct: 0,
                    weight: totalEq > 0 ? (mktVal / totalEq) * 100 : 0,
                    sector: p.sector || 'Event Tech'
                };
            });
        }
    }

    res.json({
        id: id,
        label: cfg.label,
        currency: 'USD',
        benchmark: 'SPY',
        live_connected: isLiveConnected,
        halted: localState.halted || false,
        halt_reason: localState.halt_reason || null,
        account: isLiveConnected ? {
            equity: parseFloat(liveAccount.equity),
            cash: parseFloat(liveAccount.cash),
            buying_power: parseFloat(liveAccount.buying_power),
            day_pnl: parseFloat(liveAccount.equity) - parseFloat(liveAccount.last_equity),
            day_pnl_pct: parseFloat(liveAccount.last_equity) > 0 ? ((parseFloat(liveAccount.equity) - parseFloat(liveAccount.last_equity)) / parseFloat(liveAccount.last_equity)) * 100 : 0,
            last_equity: parseFloat(liveAccount.last_equity || 0),
            long_market_value: parseFloat(liveAccount.long_market_value || 0),
            short_market_value: parseFloat(liveAccount.short_market_value || 0),
            initial_margin: parseFloat(liveAccount.initial_margin || 0),
            maintenance_margin: parseFloat(liveAccount.maintenance_margin || 0),
            daytrade_count: parseInt(liveAccount.daytrade_count || 0),
            pattern_day_trader: liveAccount.pattern_day_trader || false,
            multiplier: parseInt(liveAccount.multiplier || 1),
            regt_buying_power: parseFloat(liveAccount.regt_buying_power || 0),
            daytrading_buying_power: parseFloat(liveAccount.daytrading_buying_power || 0),
            non_marginable_buying_power: parseFloat(liveAccount.non_marginable_buying_power || 0),
            accrued_fees: parseFloat(liveAccount.accrued_fees || 0),
            portfolio_value: parseFloat(liveAccount.portfolio_value || liveAccount.equity),
            shorting_enabled: liveAccount.shorting_enabled || false,
            account_status: liveAccount.status || 'UNKNOWN',
            crypto_status: liveAccount.crypto_status || 'INACTIVE',
            options_level: parseInt(liveAccount.options_approved_level || 0),
            created_at: liveAccount.created_at || null
        } : (() => {
            if (id === 'portfolio_1') {
                return {
                    equity: parseFloat(localState.equity || 100000),
                    cash: parseFloat(localState.cash || 100000),
                    buying_power: parseFloat(localState.cash || 100000) * 2,
                    day_pnl: parseFloat(localState.day_pnl || 0),
                    day_pnl_pct: parseFloat(localState.day_pnl_pct || 0) * 100
                };
            } else if (id === 'portfolio_2') {
                const acct = localState.account || {};
                const eq = parseFloat(acct.portfolio_value || acct.equity || 100000);
                const cs = parseFloat(acct.cash || 100000);
                const pct = parseFloat(acct.daily_pnl_pct || 0);
                return {
                    equity: eq,
                    cash: cs,
                    buying_power: parseFloat(acct.buying_power || cs * 2),
                    day_pnl: eq * (pct / 100),
                    day_pnl_pct: pct
                };
            } else { // portfolio_3
                return {
                    equity: parseFloat(localState.equity || 99975.89 || 100000),
                    cash: parseFloat(localState.cash || 53673.45 || 100000),
                    buying_power: parseFloat(localState.cash || 53673.45 || 100000) * 2,
                    day_pnl: -33.98,
                    day_pnl_pct: -0.034
                };
            }
        })(),
        positions: positionsList,
        orders: liveOrders,
        trade_log: tradeLog,
        signals: signalsData,
        strategy_params: strategyParams,
        learning_report: learningReport
    });

});

// Honest historical backfill: pulls REAL persisted equity history from Supabase
// for dates strictly before `beforeDate`. Never fabricates a curve — if no
// persisted history exists, returns [] and the caller shows only real data.
// (Replaces the former synthetic generateStrategyBackfill, which manufactured
// equity curves and mislabeled them as real — an institutional-integrity defect.)
// Combine multiple per-portfolio equity series into ONE total-equity series by
// date. CRITICAL: forward-fill each portfolio's last-known equity across the
// union of dates before summing. A naive per-date sum collapses on any date
// where only some portfolios have posted a snapshot — e.g. intraday, before the
// others' EOD writers run — yielding ~1/3 of the book and crashing the
// normalized curve (the "-66.68%" all-portfolios bug). Before a portfolio's
// first observation its starting capital (basePerSeries) is assumed so the
// combined book starts whole.
function combineEquitySeries(serieses, basePerSeries = 100000) {
    const maps = [];
    const dateSet = new Set();
    for (const s of serieses) {
        const m = {};
        for (const r of (s || [])) {
            if (r && r.date) { m[r.date] = parseFloat(r.equity || 0); dateSet.add(r.date); }
        }
        maps.push(m);
    }
    const dates = [...dateSet].sort((a, b) => a.localeCompare(b));
    const running = maps.map(() => null);
    const out = [];
    for (const date of dates) {
        let total = 0;
        for (let i = 0; i < maps.length; i++) {
            if (maps[i][date] !== undefined) running[i] = maps[i][date];
            total += (running[i] !== null ? running[i] : basePerSeries);
        }
        out.push({ date, equity: Math.round(total * 100) / 100 });
    }
    return out;
}

async function realEquityBackfill(id, beforeDate, baseValue) {
    const START = '2020-01-01';
    const base = parseFloat(baseValue) || 100000;
    let rows = [];
    try {
        if (id === 'all' || id === 'portfolio_all') {
            const [p1, p2, p3] = await Promise.all([
                supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_1', date: `gte.${START}`, select: 'date,equity', order: 'date.asc', limit: 2000 }),
                supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_2', date: `gte.${START}`, select: 'date,equity', order: 'date.asc', limit: 2000 }),
                supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_3', date: `gte.${START}`, select: 'date,equity', order: 'date.asc', limit: 2000 }),
            ]);
            rows = combineEquitySeries([p1, p2, p3]);
        } else {
            rows = await supabaseGet('portfolio_equity_history', {
                portfolio_id: `eq.${id}`, date: `gte.${START}`,
                select: 'date,equity', order: 'date.asc', limit: 2000,
            });
        }
    } catch (e) {
        return [];
    }
    if (!Array.isArray(rows) || rows.length === 0) return [];
    return rows
        .filter(r => r.date && r.date < beforeDate)
        .sort((a, b) => a.date.localeCompare(b.date))
        .map(r => {
            const equity = parseFloat(r.equity || 0);
            return {
                date: r.date,
                equity: Math.round(equity * 100) / 100,
                profit_loss: Math.round((equity - base) * 100) / 100,
                profit_loss_pct: Math.round(((equity - base) / base) * 10000) / 100,
            };
        });
}

// 4. Compile historical performance curve from Alpaca Portfolio History API
app.get('/api/portfolio/:id/equity-history', async (req, res) => {
    const id = req.params.id;
    const cfg = portfoliosConfig[id];
    const paths = getPortfolioPaths(id);
    if (!paths || !cfg) {
        return res.status(404).json({ error: 'Portfolio not found' });
    }

    const period = req.query.period || '3M';
    const timeframe = req.query.timeframe || '1D';

    // Try Alpaca Portfolio History API first
    if (cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED') {
        try {
            const historyUrl = `${cfg.base_url}/v2/account/portfolio/history?period=${period}&timeframe=${timeframe}&intraday_reporting=market_hours&pnl_reset=per_day`;
            const alpacaHistory = await alpacaRequest('GET', historyUrl, cfg.api_key, cfg.api_secret);

            if (alpacaHistory && alpacaHistory.timestamp && alpacaHistory.equity) {
                const history = [];
                for (let i = 0; i < alpacaHistory.timestamp.length; i++) {
                    const ts = alpacaHistory.timestamp[i];
                    const eq = alpacaHistory.equity[i];
                    const pl = alpacaHistory.profit_loss ? alpacaHistory.profit_loss[i] : 0;
                    const plPct = alpacaHistory.profit_loss_pct ? alpacaHistory.profit_loss_pct[i] : 0;
                    // Filter out zero/null equity points (pre-funding days)
                    if (eq !== null && eq !== undefined && parseFloat(eq) > 0) {
                        const dateObj = new Date(ts * 1000);
                        history.push({
                            date: (timeframe === '1D' || timeframe === '1Day') ? dateObj.toISOString().slice(0, 10) : dateObj.toISOString(),
                            equity: parseFloat(eq),
                            profit_loss: parseFloat(pl || 0),
                            profit_loss_pct: parseFloat(plPct || 0)
                        });
                    }
                }
                // Also fetch current live equity to ensure latest point
                try {
                    const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
                    const liveEq = parseFloat(account.equity);
                    const todayStr = new Date().toISOString().slice(0, 10);
                    const lastPoint = history[history.length - 1];
                    if (liveEq > 0 && (!lastPoint || lastPoint.date !== todayStr || Math.abs(lastPoint.equity - liveEq) > 1)) {
                        if (lastPoint && lastPoint.date === todayStr) {
                            lastPoint.equity = liveEq;
                        } else {
                            history.push({ date: todayStr, equity: liveEq, profit_loss: liveEq - parseFloat(account.last_equity || liveEq), profit_loss_pct: 0 });
                        }
                    }
                } catch (e) { /* live account optional */ }

                let finalHistory = history;
                const isDaily = (timeframe === '1D' || timeframe === '1Day');
                if (isDaily && history.length < 15) {
                    const firstRealPoint = history[0];
                    if (firstRealPoint) {
                        // Extend backward with REAL persisted equity (never fabricated).
                        const backfill = await realEquityBackfill(id, firstRealPoint.date,
                            parseFloat(alpacaHistory.base_value || 100000));
                        if (backfill.length > 0) finalHistory = backfill.concat(history);
                    }
                }

                if (finalHistory.length > 0) {
                    return res.json({
                        source: 'alpaca_live',
                        base_value: parseFloat(alpacaHistory.base_value || 100000),
                        history: finalHistory
                    });
                }
            }
        } catch (e) {
            console.warn(`[Equity History] Alpaca portfolio history failed for ${id}:`, e.message);
        }
    }

    // Fallback: parse journal files
    const history = [];
    try {
        if (fs.existsSync(paths.journalDir)) {
            const files = fs.readdirSync(paths.journalDir)
                .filter(file => file.endsWith('.json'))
                .sort();

            for (const file of files) {
                const filePath = path.join(paths.journalDir, file);
                const dayEntries = readJsonFile(filePath, []);
                const dateStr = file.replace('.json', '');

                if (Array.isArray(dayEntries) && dayEntries.length > 0) {
                    let equityVal = 100000;
                    if (id === 'portfolio_1') {
                        const eod = dayEntries.find(e => e.mode === 'end-of-day') || dayEntries[dayEntries.length - 1];
                        equityVal = eod.account?.equity || eod.account?.ending_equity || 100000;
                    } else if (id === 'portfolio_2') {
                        const entry = dayEntries[dayEntries.length - 1] || {};
                        equityVal = parseFloat(entry.account_snapshot?.equity || 100000);
                    } else if (id === 'portfolio_3') {
                        const entry = dayEntries[dayEntries.length - 1] || {};
                        equityVal = entry.audit?.equity || 100000;
                    }
                    history.push({ date: dateStr, equity: equityVal, profit_loss: 0, profit_loss_pct: 0 });
                }
            }
        }
    } catch (e) {
        console.error(`Error compiling equity history for ${id}:`, e.message);
    }

    if (history.length === 0) {
        const todayStr = new Date().toISOString().slice(0, 10);
        let currentEq = 100000;
        try {
            const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
            currentEq = parseFloat(account.equity);
        } catch (e) {
            const localState = readJsonFile(paths.state, {});
            currentEq = localState.equity || 100000;
        }
        const seedDate = new Date();
        seedDate.setDate(seedDate.getDate() - 30);
        history.push({ date: seedDate.toISOString().slice(0, 10), equity: 100000, profit_loss: 0, profit_loss_pct: 0 });
        history.push({ date: todayStr, equity: currentEq, profit_loss: currentEq - 100000, profit_loss_pct: ((currentEq - 100000) / 100000) * 100 });
    }

    let finalHistory = history;
    const isDaily = (timeframe === '1D' || timeframe === '1Day');
    if (isDaily && history.length < 15) {
        const firstRealPoint = history[0];
        if (firstRealPoint) {
            // Extend backward with REAL persisted equity (never fabricated).
            const backfill = await realEquityBackfill(id, firstRealPoint.date, 100000);
            if (backfill.length > 0) finalHistory = backfill.concat(history);
        }
    }

    res.json({ source: 'journal_fallback', base_value: 100000, history: finalHistory });
});

// 5. Proxy major index feeds (SPY, QQQ, DIA) — uses snapshots for reliable prev-close
app.get('/api/market-indices', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) {
        return res.json({ SPY: { price: 520.50, change: 0, change_pct: 0 }, QQQ: { price: 440.20, change: 0, change_pct: 0 }, DIA: { price: 390.10, change: 0, change_pct: 0 } });
    }

    const symbols = ['SPY', 'QQQ', 'DIA'];

    try {
        const snapshotUrl = `${cfg.data_url}/v2/stocks/snapshots?symbols=${symbols.join(',')}`;
        const snaps = await alpacaRequest('GET', snapshotUrl, cfg.api_key, cfg.api_secret);
        const responseData = {};
        for (const sym of symbols) {
            const snap = snaps[sym];
            if (!snap) continue;
            const latestTrade = snap.latestTrade || {};
            const dailyBar = snap.dailyBar || {};
            const prevDailyBar = snap.prevDailyBar || {};
            const price = parseFloat(latestTrade.p || snap.latestQuote?.ap || dailyBar.c || 0);
            const prevClose = parseFloat(prevDailyBar.c || price);
            const change = price - prevClose;
            const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
            responseData[sym] = { price, change, change_pct: changePct };
        }
        res.json(responseData);
    } catch (e) {
        console.warn('Failed to fetch live market indices:', e.message);
        res.json({});
    }
});

// 5b. Market clock — Alpaca clock/calendar
app.get('/api/market/clock', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.json({ is_open: false, next_open: null, next_close: null, timestamp: null });

    try {
        const clock = await alpacaRequest('GET', `${cfg.base_url}/v2/clock`, cfg.api_key, cfg.api_secret);
        res.json({
            is_open: clock.is_open,
            next_open: clock.next_open,
            next_close: clock.next_close,
            timestamp: clock.timestamp
        });
    } catch (e) {
        console.warn('Failed to fetch market clock:', e.message);
        res.json({ is_open: false, next_open: null, next_close: null, timestamp: null });
    }
});

// 6. Execute live order on Alpaca
app.post('/api/portfolio/:id/order', async (req, res) => {
    const id = req.params.id;
    const cfg = portfoliosConfig[id];
    if (!cfg) {
        return res.status(404).json({ error: 'Portfolio not found' });
    }

    const { symbol, qty, side, type, price } = req.body;
    if (!symbol || !qty || !side || !type) {
        return res.status(400).json({ error: 'Missing required parameters: symbol, qty, side, type' });
    }

    try {
        const orderData = {
            symbol: symbol.toUpperCase(),
            qty: String(qty),
            side: side.toLowerCase(),
            type: type.toLowerCase(),
            time_in_force: 'day'
        };
        if (orderData.type === 'limit') {
            if (!price) return res.status(400).json({ error: 'Limit price is required for limit orders' });
            orderData.limit_price = String(price);
        }

        console.log(`Executing manual order for ${id}:`, orderData);
        const orderResult = await alpacaRequest('POST', `${cfg.base_url}/v2/orders`, cfg.api_key, cfg.api_secret, orderData);
        res.json(orderResult);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// 7. Cancel live order on Alpaca
app.delete('/api/portfolio/:id/order/:order_id', async (req, res) => {
    const id = req.params.id;
    const orderId = req.params.order_id;
    const cfg = portfoliosConfig[id];
    if (!cfg) {
        return res.status(404).json({ error: 'Portfolio not found' });
    }

    try {
        console.log(`Cancelling order ${orderId} for portfolio ${id}`);
        await alpacaRequest('DELETE', `${cfg.base_url}/v2/orders/${orderId}`, cfg.api_key, cfg.api_secret);
        res.json({ success: true, message: `Order ${orderId} successfully cancelled` });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// 7.5 Proxy US Market Clock (Alpaca / Simulated)
app.get('/api/market-clock', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (cfg && cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED') {
        try {
            const clock = await alpacaRequest('GET', `${cfg.base_url}/v2/clock`, cfg.api_key, cfg.api_secret);
            return res.json(clock);
        } catch (e) {
            console.warn('Alpaca clock query failed, falling back to simulated clock:', e.message);
        }
    }
    const now = new Date();
    const day = now.getDay();
    const hour = now.getHours();
    const minute = now.getMinutes();
    const isWeekday = day >= 1 && day <= 5;
    const isHours = (hour === 9 && minute >= 30) || (hour > 9 && hour < 16);
    const isOpen = isWeekday && isHours;
    res.json({
        timestamp: now.toISOString(),
        is_open: isOpen,
        next_open: new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 9, 30).toISOString(),
        next_close: new Date(now.getFullYear(), now.getMonth(), now.getDate(), 16, 0).toISOString()
    });
});

// 8. Proxy US Market News (Alpaca beta / Simulated)
app.get('/api/market-news', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (cfg && cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED') {
        try {
            const news = await alpacaRequest('GET', `${cfg.data_url}/v1beta1/news?limit=10`, cfg.api_key, cfg.api_secret);
            return res.json(news.news || []);
        } catch (e) {
            console.warn('Alpaca News API query failed, falling back to simulated news:', e.message);
        }
    }
    res.json([]);
});

// 9. Stock details — live Alpaca data only
app.get('/api/stock/:symbol/details', async (req, res) => {
    const symbol = req.params.symbol.toUpperCase();
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg || !cfg.api_key) return res.json({ symbol, quote: null, bars: [], profile: {} });

    let quoteData = null;
    let barData = [];
    let profile = { name: symbol };

    try {
        const [q, b, snap, asset] = await Promise.all([
            alpacaRequest('GET', `${cfg.data_url}/v2/stocks/${symbol}/quotes/latest`, cfg.api_key, cfg.api_secret).catch(() => null),
            alpacaRequest('GET', `${cfg.data_url}/v2/stocks/${symbol}/bars?timeframe=1Day&limit=60`, cfg.api_key, cfg.api_secret).catch(() => null),
            alpacaRequest('GET', `${cfg.data_url}/v2/stocks/snapshots?symbols=${symbol}`, cfg.api_key, cfg.api_secret).catch(() => null),
            alpacaRequest('GET', `${cfg.base_url}/v2/assets/${symbol}`, cfg.api_key, cfg.api_secret).catch(() => null)
        ]);

        barData = (b && b.bars) ? b.bars : [];
        const snapData = snap && snap[symbol];
        const ask = (q && q.quote) ? parseFloat(q.quote.ap || 0) : 0;
        const bid = (q && q.quote) ? parseFloat(q.quote.bp || 0) : 0;
        // Price-source priority mirrors /api/market/quotes so the hero price is the
        // REAL last trade — not a one-sided/zero quote. After hours, ask can be 0 and a
        // stale quote can even carry the wrong sign; last trade + prev daily close fix
        // both the magnitude and the direction of the % change.
        const lastTradePx = parseFloat(snapData?.latestTrade?.p || 0);
        const dayClosePx = parseFloat(snapData?.dailyBar?.c || 0);
        const midPx = (ask > 0 && bid > 0) ? (ask + bid) / 2 : 0;
        const prevClose = parseFloat(snapData?.prevDailyBar?.c || 0);
        const px = lastTradePx > 0 ? lastTradePx
                 : dayClosePx > 0 ? dayClosePx
                 : midPx > 0 ? midPx
                 : (bid > 0 ? bid : ask);
        if (px > 0) {
            quoteData = {
                price: px,
                bid: bid,
                ask: ask,
                size: (q && q.quote) ? parseInt(q.quote.as || 1) : 1,
                timestamp: snapData?.latestTrade?.t || (q && q.quote ? q.quote.t : null),
                prev: prevClose
            };
        }

        if (asset) {
            profile.name = asset.name || symbol;
            profile.exchange = asset.exchange;
            profile.asset_class = asset.class;
            profile.tradable = asset.tradable;
            profile.fractionable = asset.fractionable;
            profile.shortable = asset.shortable;
        }
        if (prevClose) profile.prev = prevClose;
    } catch (e) {
        console.warn(`Stock details fetch failed for ${symbol}:`, e.message);
    }

    res.json({ symbol, quote: quoteData, bars: barData, profile });
});

// 10. Batch stock quotes for multiple symbols (watchlist, movers, sectors)
app.get('/api/market/quotes', async (req, res) => {
    const symbolsParam = req.query.symbols || 'SPY,QQQ,DIA,NVDA,AAPL,MSFT,GOOGL,AMZN,TSLA,META';
    const symbols = symbolsParam.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    const result = {};

    if (cfg && cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED') {
        try {
            // Alpaca v2 snapshots endpoint (batch)
            const snapshotUrl = `${cfg.data_url}/v2/stocks/snapshots?symbols=${symbols.join(',')}`;
            const snaps = await alpacaRequest('GET', snapshotUrl, cfg.api_key, cfg.api_secret);
            for (const [sym, snap] of Object.entries(snaps)) {
                const latestTrade = snap.latestTrade || snap.latestQuote || {};
                const dailyBar = snap.dailyBar || {};
                const prevDailyBar = snap.prevDailyBar || {};
                const price = parseFloat(latestTrade.p || snap.latestQuote?.ap || dailyBar.c || 0);
                const prevClose = parseFloat(prevDailyBar.c || price);
                const change = price - prevClose;
                const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
                const latestQuote = snap.latestQuote || {};
                result[sym] = {
                    price,
                    change,
                    changePct,
                    open: parseFloat(dailyBar.o || price),
                    high: parseFloat(dailyBar.h || price),
                    low: parseFloat(dailyBar.l || price),
                    close: parseFloat(dailyBar.c || price),
                    volume: parseInt(dailyBar.v || 0),
                    bid: parseFloat(latestQuote.bp || 0),
                    ask: parseFloat(latestQuote.ap || 0),
                    bidSize: parseInt(latestQuote.bs || 0),
                    askSize: parseInt(latestQuote.as || 0)
                };
            }
            return res.json(result);
        } catch (e) {
            console.warn('Batch quotes error:', e.message);
        }
    }

    res.json(result);
});

// 11. Historical bars for a symbol (for sparkline / chart)
// Compute a safe default `start` so Alpaca never returns just one bar when the
// caller omits it. IEX historical bars require an explicit time range.
function defaultBarsStart(timeframe, limit) {
    const tf = String(timeframe);
    let days;
    if (/Day/i.test(tf)) {
        days = Math.ceil(limit * 1.6) + 5;          // calendar days cover weekends/holidays
    } else if (/Week/i.test(tf)) {
        days = limit * 8 + 14;
    } else if (/Hour/i.test(tf)) {
        const perDay = 7;                             // ~7 trading hours
        days = Math.ceil(limit / perDay) + 5;
    } else {                                          // minute bars
        const mins = parseInt(tf) || 5;
        const perDay = Math.max(1, Math.floor(390 / mins));
        days = Math.ceil(limit / perDay) + 5;
    }
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
}

app.get('/api/market/bars/:symbol', async (req, res) => {
    const symbol = req.params.symbol.toUpperCase();
    const limit = parseInt(req.query.limit || '30');
    const timeframe = req.query.timeframe || '1Day';
    const start = req.query.start || defaultBarsStart(timeframe, limit);
    const end = req.query.end || '';
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];

    if (cfg && cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED') {
        try {
            // sort=desc + limit => the most RECENT `limit` bars; reverse to
            // chronological for the chart. (sort=asc would return the OLDEST.)
            let barsUrl = `${cfg.data_url}/v2/stocks/${symbol}/bars?timeframe=${timeframe}&limit=${limit}&feed=iex&sort=desc`;
            if (start) barsUrl += `&start=${encodeURIComponent(start)}`;
            if (end) barsUrl += `&end=${encodeURIComponent(end)}`;
            const barsData = await alpacaRequest('GET', barsUrl, cfg.api_key, cfg.api_secret);
            if (barsData && barsData.bars && barsData.bars.length > 0) {
                return res.json(barsData.bars.slice().reverse());
            }
        } catch (e) {
            console.warn(`Bars fetch error for ${symbol}:`, e.message);
        }
    }

    // Fallback to Supabase for daily bars when Alpaca is unavailable
    if (timeframe === '1Day') {
        try {
            const rows = await supabaseGet('market_daily_history', {
                symbol: `eq.${symbol}`,
                select: 'date,close_price,open_price,high_price,low_price,volume',
                order: 'date.desc',
                limit: limit,
            });
            if (rows && rows.length > 0) {
                const bars = rows.reverse().map(r => ({
                    t: r.date,
                    c: parseFloat(r.close_price),
                    o: parseFloat(r.open_price),
                    h: parseFloat(r.high_price),
                    l: parseFloat(r.low_price),
                    v: parseInt(r.volume || 0)
                }));
                return res.json(bars);
            }
        } catch (e) {
            console.warn(`Supabase bars fallback error for ${symbol}:`, e.message);
        }
    }

    res.json([]);
});

// ── Supabase historical data endpoints ──────────────────────────────────────
// These read from the Supabase tables accumulated by daily EOD workflows.
// SUPABASE_URL and SUPABASE_ANON_KEY must be set in Vercel environment variables.

function supabaseGet(table, params) {
    return new Promise((resolve) => {
        const SB_URL = process.env.SUPABASE_URL;
        const SB_KEY = process.env.SUPABASE_ANON_KEY;
        if (!SB_URL || !SB_KEY) { resolve([]); return; }
        const qs = Object.entries(params).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
        const url = `${SB_URL}/rest/v1/${table}?${qs}`;
        const options = {
            hostname: new URL(url).hostname,
            path:     new URL(url).pathname + new URL(url).search,
            headers:  { 'apikey': SB_KEY, 'Authorization': `Bearer ${SB_KEY}` }
        };
        const https = require('https');
        const req = https.get(options, (r) => {
            let data = '';
            r.on('data', chunk => data += chunk);
            r.on('end', () => {
                try { resolve(JSON.parse(data)); }
                catch { resolve([]); }
            });
        });
        req.on('error', () => resolve([]));
        req.end();
    });
}

// 11b. Supabase equity history — /api/supabase/equity?portfolio_id=portfolio_1&start=2025-06-01
app.get('/api/supabase/equity', async (req, res) => {
    const portfolioId = req.query.portfolio_id || 'portfolio_1';
    const start = req.query.start || '2025-01-01';

    if (portfolioId === 'all') {
        // Aggregate all 3 portfolios by date
        const [p1, p2, p3] = await Promise.all([
            supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_1', date: `gte.${start}`, select: 'date,equity', order: 'date.asc', limit: 1000 }),
            supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_2', date: `gte.${start}`, select: 'date,equity', order: 'date.asc', limit: 1000 }),
            supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_3', date: `gte.${start}`, select: 'date,equity', order: 'date.asc', limit: 1000 }),
        ]);
        // Forward-fill each portfolio before summing (see combineEquitySeries):
        // a naive per-date sum collapses on partial dates → false -66% curve.
        return res.json(combineEquitySeries([p1, p2, p3]));
    }

    const rows = await supabaseGet('portfolio_equity_history', {
        portfolio_id: `eq.${portfolioId}`,
        date:         `gte.${start}`,
        select:       'date,equity,cash,pnl,pnl_pct,positions_count',
        order:        'date.asc',
        limit:        1000,
    });
    res.json(rows || []);
});

// 11b-2. Tail risk (read-only): historical VaR/CVaR from the equity series.
//   /api/portfolio/:id/tail-risk?start=2025-01-01   (id = portfolio_1.. or 'all')
// Advisory observability only — mirrors shared/portfolio_risk.py (positive % loss
// of equity). Returns n_obs:0 when no equity history is available.
function _quantileSorted(sorted, q) {
    if (!sorted.length) return 0;
    if (q <= 0) return sorted[0];
    if (q >= 1) return sorted[sorted.length - 1];
    const pos = q * (sorted.length - 1), lo = Math.floor(pos), frac = pos - lo;
    return lo + 1 < sorted.length ? sorted[lo] * (1 - frac) + sorted[lo + 1] * frac : sorted[lo];
}
function tailRisk(returns, confidence) {
    const rs = returns.filter(r => Number.isFinite(r));
    if (rs.length < 2) return { var_pct: 0, cvar_pct: 0, n: rs.length };
    const sorted = [...rs].sort((a, b) => a - b);
    const alpha = 1 - confidence;
    const q = _quantileSorted(sorted, alpha);
    const tail = sorted.filter(r => r <= q);
    const t = tail.length ? tail : [sorted[0]];
    return {
        var_pct: +Math.max(0, -q * 100).toFixed(4),
        cvar_pct: +Math.max(0, -(t.reduce((a, b) => a + b, 0) / t.length) * 100).toFixed(4),
        n: rs.length,
    };
}
function equityToReturns(rows) {
    const eq = (rows || []).map(r => parseFloat(r.equity)).filter(Number.isFinite);
    const out = [];
    for (let i = 1; i < eq.length; i++) if (eq[i - 1]) out.push(eq[i] / eq[i - 1] - 1);
    return out;
}
app.get('/api/portfolio/:id/tail-risk', async (req, res) => {
    const id = req.params.id;
    const start = req.query.start || '2025-01-01';
    let rows;
    if (id === 'all') {
        const [p1, p2, p3] = await Promise.all(['portfolio_1', 'portfolio_2', 'portfolio_3'].map(
            pid => supabaseGet('portfolio_equity_history', { portfolio_id: `eq.${pid}`, date: `gte.${start}`, select: 'date,equity', order: 'date.asc', limit: 1000 })));
        rows = combineEquitySeries([p1, p2, p3]);
    } else {
        rows = await supabaseGet('portfolio_equity_history', { portfolio_id: `eq.${id}`, date: `gte.${start}`, select: 'date,equity', order: 'date.asc', limit: 1000 });
    }
    const returns = equityToReturns(rows);
    res.json({
        portfolio_id: id,
        n_obs: returns.length,
        var_95: tailRisk(returns, 0.95),
        var_99: tailRisk(returns, 0.99),
        note: 'Historical VaR/CVaR as a positive % loss of equity (advisory observability).',
    });
});

// 11c. Supabase market history — /api/supabase/market?symbol=SPY&start=2025-06-01&limit=30
app.get('/api/supabase/market', async (req, res) => {
    const symbol = (req.query.symbol || 'SPY').toUpperCase();
    const start  = req.query.start || '2025-01-01';
    const limit  = parseInt(req.query.limit || '1000');
    const rows   = await supabaseGet('market_daily_history', {
        symbol: `eq.${symbol}`,
        date:   `gte.${start}`,
        select: 'date,close_price,open_price,high_price,low_price,volume',
        order:  'date.asc',
        limit:  Math.min(limit, 1000),
    });
    res.json(rows || []);
});

// 12. Sector ETF performance snapshot
app.get('/api/market/sectors', async (req, res) => {
    const SECTOR_ETFS = ['XLK', 'XLF', 'XLE', 'XLV', 'XLY', 'XLI', 'XLC', 'XLB', 'XLU', 'XLRE'];
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    const result = {};

    if (cfg && cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED') {
        try {
            const snapshotUrl = `${cfg.data_url}/v2/stocks/snapshots?symbols=${SECTOR_ETFS.join(',')}`;
            const snaps = await alpacaRequest('GET', snapshotUrl, cfg.api_key, cfg.api_secret);
            const sectorNames = {
                XLK: 'Technology', XLF: 'Financials', XLE: 'Energy',
                XLV: 'Health Care', XLY: 'Cons. Disc.', XLI: 'Industrials',
                XLC: 'Comm. Svcs', XLB: 'Materials', XLU: 'Utilities', XLRE: 'Real Estate'
            };
            for (const [sym, snap] of Object.entries(snaps)) {
                const latestTrade = snap.latestTrade || {};
                const dailyBar = snap.dailyBar || {};
                const prevDailyBar = snap.prevDailyBar || {};
                const price = parseFloat(latestTrade.p || dailyBar.c || 0);
                const prevClose = parseFloat(prevDailyBar.c || price);
                const changePct = prevClose > 0 ? ((price - prevClose) / prevClose) * 100 : 0;
                result[sym] = { price, changePct, name: sectorNames[sym] || sym, volume: parseInt(dailyBar.v || 0) };
            }
            return res.json(result);
        } catch (e) {
            console.warn('Sector ETF fetch error:', e.message);
        }
    }

    res.json({});
});

// 13. Full Alpaca account details (all fields exposed)
app.get('/api/portfolio/:id/account-full', async (req, res) => {
    const id = req.params.id;
    const cfg = portfoliosConfig[id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });

    try {
        const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
        return res.json(account);
    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
});

// 13.5 Account activities (dividends, fills, transfers)
app.get('/api/portfolio/:id/activities', async (req, res) => {
    const id = req.params.id;
    const cfg = portfoliosConfig[id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });

    const actType = req.query.activity_type || '';
    const limit = req.query.limit || '50';
    let url = `${cfg.base_url}/v2/account/activities`;
    if (actType) url += `/${actType}`;
    url += `?page_size=${limit}`;

    try {
        const activities = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        return res.json(activities);
    } catch (e) {
        return res.status(500).json({ error: e.message });
    }
});

// 14. Portfolio summary overview (3 portfolio cards)
app.get('/api/portfolios/overview', async (req, res) => {
    loadConfig();
    const summaries = [];

    for (const [id, cfg] of Object.entries(portfoliosConfig)) {
        const paths = getPortfolioPaths(id);
        const localState = paths ? readJsonFile(paths.state, {}) : {};
        let equity = 100000, cash = 100000, dayPnl = 0, dayPnlPct = 0, positions = 0, liveConnected = false;

        try {
            const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
            equity = parseFloat(account.equity);
            cash = parseFloat(account.cash);
            dayPnl = parseFloat(account.equity) - parseFloat(account.last_equity);
            dayPnlPct = parseFloat(account.last_equity) > 0 ? (dayPnl / parseFloat(account.last_equity)) * 100 : 0;
            const pos = await alpacaRequest('GET', `${cfg.base_url}/v2/positions`, cfg.api_key, cfg.api_secret);
            positions = pos.length;
            liveConnected = true;
        } catch (e) {
            // Local fallback
            if (id === 'portfolio_1') { equity = parseFloat(localState.equity || 100000); cash = parseFloat(localState.cash || 100000); dayPnl = parseFloat(localState.day_pnl || 0); positions = localState.positions ? Object.keys(localState.positions).length : 0; }
            else if (id === 'portfolio_2') { const acct = localState.account || {}; equity = parseFloat(acct.portfolio_value || acct.equity || 100000); cash = parseFloat(acct.cash || 100000); positions = localState.positions ? localState.positions.length : 0; }
            else { equity = parseFloat(localState.equity || 100000); cash = parseFloat(localState.cash || 100000); positions = localState.positions || 0; }
        }

        const totalReturn = ((equity - 100000) / 100000) * 100;
        summaries.push({ id, label: cfg.label, equity, cash, dayPnl, dayPnlPct, positions, totalReturn, initialCapital: cfg.initial_capital || 100000, liveConnected, strategy: cfg.strategy });
    }
    res.json(summaries);
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP A: Account & Configuration
// ──────────────────────────────────────────────────────────────────────────

// A1. Get account configuration
app.get('/api/portfolio/:id/account-config', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const config = await alpacaRequest('GET', `${cfg.base_url}/v2/account/configurations`, cfg.api_key, cfg.api_secret);
        res.json(config);
    } catch (e) {
        res.json({ dtbp_check: 'both', no_shorting: false, trade_confirm_email: 'all', suspend_trade: false, pdt_check: 'entry', max_margin_multiplier: '4', fractional_trading: true, ptp_no_exception_entry: false });
    }
});

// A2. Update account configuration
app.patch('/api/portfolio/:id/account-config', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const result = await alpacaRequest('PATCH', `${cfg.base_url}/v2/account/configurations`, cfg.api_key, cfg.api_secret, req.body);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// A3. Portfolio history (equity timeseries)
app.get('/api/portfolio/:id/portfolio-history', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { period, timeframe, date_start, date_end, extended_hours, pnl_reset } = req.query;
    let url = `${cfg.base_url}/v2/account/portfolio/history?`;
    if (period) url += `period=${period}&`;
    if (timeframe) url += `timeframe=${timeframe}&`;
    if (date_start) url += `date_start=${date_start}&`;
    if (date_end) url += `date_end=${date_end}&`;
    if (extended_hours) url += `extended_hours=${extended_hours}&`;
    if (pnl_reset) url += `pnl_reset=${pnl_reset}&`;
    try {
        const history = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(history);
    } catch (e) {
        res.json({ timestamp: [], equity: [], profit_loss: [], profit_loss_pct: [], base_value: 100000, timeframe: '1D' });
    }
});

// A4. All open positions
app.get('/api/portfolio/:id/positions', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const positions = await alpacaRequest('GET', `${cfg.base_url}/v2/positions`, cfg.api_key, cfg.api_secret);
        res.json(positions);
    } catch (e) {
        res.json([]);
    }
});

// A5. Close a specific position
app.post('/api/portfolio/:id/position/:symbol/close', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { qty, percentage } = req.body || {};
    let url = `${cfg.base_url}/v2/positions/${encodeURIComponent(req.params.symbol)}`;
    const params = [];
    if (qty) params.push(`qty=${qty}`);
    if (percentage) params.push(`percentage=${percentage}`);
    if (params.length) url += `?${params.join('&')}`;
    try {
        const result = await alpacaRequest('DELETE', url, cfg.api_key, cfg.api_secret);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// A6. Close all positions
app.post('/api/portfolio/:id/positions/close-all', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const cancel_orders = req.query.cancel_orders || 'true';
    try {
        const result = await alpacaRequest('DELETE', `${cfg.base_url}/v2/positions?cancel_orders=${cancel_orders}`, cfg.api_key, cfg.api_secret);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP B: Order Management
// ──────────────────────────────────────────────────────────────────────────

// B1. List orders with full filtering
app.get('/api/portfolio/:id/orders', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { status, limit, after, until, direction, nested, symbols, side } = req.query;
    let url = `${cfg.base_url}/v2/orders?`;
    if (status) url += `status=${status}&`;
    if (limit) url += `limit=${limit}&`;
    if (after) url += `after=${after}&`;
    if (until) url += `until=${until}&`;
    if (direction) url += `direction=${direction}&`;
    if (nested) url += `nested=${nested}&`;
    if (symbols) url += `symbols=${symbols}&`;
    if (side) url += `side=${side}&`;
    try {
        const orders = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(orders);
    } catch (e) {
        res.json([]);
    }
});

// B2. Get single order by ID
app.get('/api/portfolio/:id/order/:order_id', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const order = await alpacaRequest('GET', `${cfg.base_url}/v2/orders/${req.params.order_id}`, cfg.api_key, cfg.api_secret);
        res.json(order);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// B3. Get order by client order ID
app.get('/api/portfolio/:id/order-by-client/:client_id', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const order = await alpacaRequest('GET', `${cfg.base_url}/v2/orders:by_client_order_id?client_order_id=${encodeURIComponent(req.params.client_id)}`, cfg.api_key, cfg.api_secret);
        res.json(order);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// B4. Replace/modify an order
app.patch('/api/portfolio/:id/order/:order_id', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const result = await alpacaRequest('PATCH', `${cfg.base_url}/v2/orders/${req.params.order_id}`, cfg.api_key, cfg.api_secret, req.body);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// B5. Cancel all orders
app.delete('/api/portfolio/:id/orders', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const result = await alpacaRequest('DELETE', `${cfg.base_url}/v2/orders`, cfg.api_key, cfg.api_secret);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// B6-pre. Unified orders — authoritative real-time view across all portfolios.
// Uses status=all from Alpaca so bracket stop/take-profit legs (status=held/new)
// and same-day fills not yet committed to trade_log are never missed.
// trade_log provides descriptions + historical coverage beyond Alpaca's 500-order window.
// ?portfolio_id=all|portfolio_1|portfolio_2|portfolio_3
app.get('/api/orders/unified', async (req, res) => {
    loadConfig();
    const { portfolio_id } = req.query;
    const ids = (portfolio_id && portfolio_id !== 'all')
        ? [portfolio_id]
        : Object.keys(portfoliosConfig);

    // Non-terminal Alpaca statuses → shown as "Open"
    const OPEN_STATUSES = new Set([
        'new', 'partially_filled', 'held', 'pending_new', 'pending_cancel',
        'pending_replace', 'accepted', 'accepted_for_bidding', 'calculated',
        'done_for_day', 'stopped', 'suspended'
    ]);

    const executed = [];
    const open = [];
    const canceled = [];   // terminal-but-unfilled (expired/canceled/rejected), real orders only

    for (const id of ids) {
        const cfg = portfoliosConfig[id];
        if (!cfg) continue;
        const paths = getPortfolioPaths(id);
        const tradeLog = readJsonFile(paths.tradeLog, []);

        // Build trade_log description map (symbol|date|side|qty → reason)
        // and a set of keys covered by trade_log for dedup later
        const tlDescMap = {};
        tradeLog.forEach(t => {
            const d = t.date || (t.timestamp || '').slice(0, 10);
            const qty = Math.round(parseFloat(t.qty || t.quantity || 0));
            const key = `${t.symbol}|${d}|${t.side || t.type}|${qty}`;
            tlDescMap[key] = t.reason
                || (Array.isArray(t.reasons) ? t.reasons.join(', ') : (t.reasons || ''))
                || '';
        });

        // Fetch ALL Alpaca orders: filled + open + held (bracket legs) + canceled
        let alpacaOrders = [];
        try {
            const resp = await alpacaRequest(
                'GET',
                `${cfg.base_url}/v2/orders?status=all&limit=500&direction=desc`,
                cfg.api_key, cfg.api_secret
            );
            if (Array.isArray(resp)) alpacaOrders = resp;
        } catch (_) {}

        // Track the date range Alpaca data covers + filled keys for dedup
        let alpacaOldestDate = null;
        const alpacaFilledKeys = new Set();

        alpacaOrders.forEach(o => {
            const dateStr = (o.filled_at || o.submitted_at || '').slice(0, 10);
            if (dateStr && (!alpacaOldestDate || dateStr < alpacaOldestDate)) alpacaOldestDate = dateStr;

            const qty = parseFloat(o.filled_qty || o.qty || 0);
            const price = parseFloat(o.filled_avg_price || o.limit_price || o.stop_price || 0);

            // Enrich with description from trade_log if available
            const qtyRounded = Math.round(qty);
            const descKey = `${o.symbol}|${dateStr}|${o.side}|${qtyRounded}`;
            const reason = tlDescMap[descKey] || `${(o.type || 'market').replace(/_/g, ' ')} order`;

            const norm = {
                _source: 'alpaca',
                _portfolio_id: id,
                _portfolio_label: cfg.label,
                date: dateStr,
                timestamp: o.filled_at || o.submitted_at,
                symbol: o.symbol,
                side: o.side,
                qty: qty,
                entry_price: price,
                filled_avg_price: parseFloat(o.filled_avg_price || 0),
                limit_price: parseFloat(o.limit_price || 0),
                stop_price: parseFloat(o.stop_price || 0),
                order_type: o.type,
                order_status: o.status,
                order_id: o.id,
                time_in_force: o.time_in_force,
                reason,
            };

            if (o.status === 'filled') {
                executed.push(norm);
                alpacaFilledKeys.add(descKey);
            } else if (OPEN_STATUSES.has(o.status)) {
                open.push(norm);
            } else {
                // Terminal but NOT filled (canceled/expired/rejected/replaced).
                // Surface MEANINGFUL unfilled orders — e.g. a copy-trade limit that
                // expired before filling (P2 PGR/MA/SPGI/DHR) — but suppress the
                // auto-managed bracket/OCO exit legs: every closed bracket position
                // leaves a take-profit limit + stop-loss stop that expire/cancel as
                // normal management (order_class bracket/oco/oto). A standalone order
                // the system actually placed is order_class simple/empty. Previously
                // ALL of these were dropped, which hid the genuine unfilled orders too.
                const cls = (o.order_class || '').toLowerCase();
                if (cls === '' || cls === 'simple') canceled.push(norm);
            }
        });

        // Add trade_log entries NOT already covered by Alpaca filled data.
        // Alpaca covers up to 500 recent orders; trade_log fills gaps for older history.
        tradeLog.forEach(t => {
            const d = t.date || (t.timestamp || '').slice(0, 10);
            if (!d) return;
            // Within Alpaca's date window → dedup by composite key
            if (alpacaOldestDate && d >= alpacaOldestDate) {
                const qty = Math.round(parseFloat(t.qty || t.quantity || 0));
                const key = `${t.symbol}|${d}|${t.side || t.type}|${qty}`;
                if (alpacaFilledKeys.has(key)) return; // already in Alpaca
            }
            executed.push({ ...t, _source: 'tradelog', _portfolio_id: id, _portfolio_label: cfg.label });
        });
    }

    // Sort executed newest-first
    executed.sort((a, b) => {
        const da = new Date(a.date || (a.timestamp || '').slice(0, 10) || 0);
        const db = new Date(b.date || (b.timestamp || '').slice(0, 10) || 0);
        return db - da;
    });

    canceled.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
    res.json({ executed, open, canceled, fetched_at: new Date().toISOString() });
});

// B6. Place crypto order
app.post('/api/portfolio/:id/crypto-order', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { symbol, qty, notional, side, type, time_in_force, limit_price, stop_price } = req.body;
    if (!symbol || !side || !type) return res.status(400).json({ error: 'Missing required: symbol, side, type' });
    const orderData = { symbol: symbol.toUpperCase(), side: side.toLowerCase(), type: type.toLowerCase(), time_in_force: time_in_force || 'gtc' };
    if (qty) orderData.qty = String(qty);
    if (notional) orderData.notional = String(notional);
    if (limit_price) orderData.limit_price = String(limit_price);
    if (stop_price) orderData.stop_price = String(stop_price);
    try {
        const result = await alpacaRequest('POST', `${cfg.base_url}/v2/orders`, cfg.api_key, cfg.api_secret, orderData);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// B7. Place option order
app.post('/api/portfolio/:id/option-order', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { symbol, qty, side, type, time_in_force, limit_price, stop_price, order_class, legs } = req.body;
    if (!symbol && !legs) return res.status(400).json({ error: 'Missing required: symbol or legs' });
    const orderData = { side: (side || 'buy').toLowerCase(), type: (type || 'limit').toLowerCase(), time_in_force: time_in_force || 'day' };
    if (symbol) orderData.symbol = symbol;
    if (qty) orderData.qty = String(qty);
    if (limit_price) orderData.limit_price = String(limit_price);
    if (stop_price) orderData.stop_price = String(stop_price);
    if (order_class) orderData.order_class = order_class;
    if (legs) orderData.legs = legs;
    try {
        const result = await alpacaRequest('POST', `${cfg.base_url}/v2/orders`, cfg.api_key, cfg.api_secret, orderData);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP C: Watchlists
// ──────────────────────────────────────────────────────────────────────────

// C1. List all watchlists
app.get('/api/portfolio/:id/watchlists', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const watchlists = await alpacaRequest('GET', `${cfg.base_url}/v2/watchlists`, cfg.api_key, cfg.api_secret);
        res.json(watchlists);
    } catch (e) {
        res.json([]);
    }
});

// C2. Create a watchlist
app.post('/api/portfolio/:id/watchlists', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { name, symbols } = req.body;
    if (!name) return res.status(400).json({ error: 'Missing required: name' });
    try {
        const result = await alpacaRequest('POST', `${cfg.base_url}/v2/watchlists`, cfg.api_key, cfg.api_secret, { name, symbols: symbols || [] });
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// C3. Get single watchlist with assets
app.get('/api/portfolio/:id/watchlist/:wl_id', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const watchlist = await alpacaRequest('GET', `${cfg.base_url}/v2/watchlists/${req.params.wl_id}`, cfg.api_key, cfg.api_secret);
        res.json(watchlist);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// C4. Update watchlist
app.put('/api/portfolio/:id/watchlist/:wl_id', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const result = await alpacaRequest('PUT', `${cfg.base_url}/v2/watchlists/${req.params.wl_id}`, cfg.api_key, cfg.api_secret, req.body);
        res.json(result);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// C5. Delete watchlist
app.delete('/api/portfolio/:id/watchlist/:wl_id', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        await alpacaRequest('DELETE', `${cfg.base_url}/v2/watchlists/${req.params.wl_id}`, cfg.api_key, cfg.api_secret);
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// C6. Remove symbol from watchlist
app.delete('/api/portfolio/:id/watchlist/:wl_id/asset/:symbol', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        await alpacaRequest('DELETE', `${cfg.base_url}/v2/watchlists/${req.params.wl_id}/${req.params.symbol}`, cfg.api_key, cfg.api_secret);
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP D: Assets
// ──────────────────────────────────────────────────────────────────────────

// D1. List/search all assets
app.get('/api/assets', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { status, asset_class, exchange } = req.query;
    let url = `${cfg.base_url}/v2/assets?`;
    if (status) url += `status=${status}&`;
    if (asset_class) url += `asset_class=${asset_class}&`;
    if (exchange) url += `exchange=${exchange}&`;
    try {
        const assets = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(assets);
    } catch (e) {
        res.json([]);
    }
});

// D2. Single asset detail
app.get('/api/asset/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    try {
        const asset = await alpacaRequest('GET', `${cfg.base_url}/v2/assets/${encodeURIComponent(req.params.symbol)}`, cfg.api_key, cfg.api_secret);
        res.json(asset);
    } catch (e) {
        res.json({ error: 'Asset not found', symbol: req.params.symbol });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP E: Crypto Market Data
// ──────────────────────────────────────────────────────────────────────────

// E1. Crypto historical bars
app.get('/api/crypto/bars/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const sym = req.params.symbol.replace('/', '%2F');
    const { timeframe, start, end, limit } = req.query;
    const tf = timeframe || '1Day';
    const lim = parseInt(limit) || 80;
    // Crypto trades 24/7. Without an explicit `start` Alpaca returns only a tiny
    // recent slice (1Day → a SINGLE candle), the same empty-period pitfall as stock
    // bars. Derive a lookback that comfortably covers `limit` bars when none is sent.
    let startParam = start;
    if (!startParam) {
        const tfMin = { '1Min': 1, '5Min': 5, '15Min': 15, '1Hour': 60, '4Hour': 240, '1Day': 1440 }[tf] || 1440;
        startParam = new Date(Date.now() - tfMin * 60000 * lim * 1.5).toISOString();
    }
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/bars?symbols=${sym}&timeframe=${tf}&start=${startParam}&limit=${lim}`;
    if (end) url += `&end=${end}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ bars: {} });
    }
});

// E2. Crypto snapshot
app.get('/api/crypto/snapshot/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const sym = req.params.symbol.replace('/', '%2F');
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/snapshots?symbols=${sym}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ snapshots: {} });
    }
});

// E3. Crypto quotes
app.get('/api/crypto/quotes/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const sym = req.params.symbol.replace('/', '%2F');
    const { start, end, limit } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/quotes?symbols=${sym}`;
    if (start) url += `&start=${start}`;
    if (end) url += `&end=${end}`;
    if (limit) url += `&limit=${limit || 100}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ quotes: {} });
    }
});

// E4. Crypto trades
app.get('/api/crypto/trades/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const sym = req.params.symbol.replace('/', '%2F');
    const { start, end, limit } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/trades?symbols=${sym}`;
    if (start) url += `&start=${start}`;
    if (end) url += `&end=${end}`;
    if (limit) url += `&limit=${limit || 100}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ trades: {} });
    }
});

// E5. Crypto orderbook
app.get('/api/crypto/orderbook/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const sym = req.params.symbol.replace('/', '%2F');
    try {
        // Correct Alpaca path is /latest/orderbooks (the previous /orderbooks/books
        // 404'd, so the live depth ladder silently rendered empty for every visitor).
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/latest/orderbooks?symbols=${sym}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ orderbooks: {} });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP F: Options Market Data
// ──────────────────────────────────────────────────────────────────────────

// F1. Option chain for underlying
app.get('/api/options/chain/:underlying', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { expiration_date, expiration_date_gte, expiration_date_lte, strike_price_gte, strike_price_lte, type: optType, limit } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/options/snapshots/${req.params.underlying}?feed=indicative`;
    if (expiration_date) url += `&expiration_date=${expiration_date}`;
    if (expiration_date_gte) url += `&expiration_date_gte=${expiration_date_gte}`;
    if (expiration_date_lte) url += `&expiration_date_lte=${expiration_date_lte}`;
    if (strike_price_gte) url += `&strike_price_gte=${strike_price_gte}`;
    if (strike_price_lte) url += `&strike_price_lte=${strike_price_lte}`;
    if (optType) url += `&type=${optType}`;
    if (limit) url += `&limit=${limit}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ snapshots: {} });
    }
});

// F2. Single option contract
app.get('/api/options/contract/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    try {
        const contract = await alpacaRequest('GET', `${cfg.base_url}/v2/options/contracts/${encodeURIComponent(req.params.symbol)}`, cfg.api_key, cfg.api_secret);
        res.json(contract);
    } catch (e) {
        res.json({ error: 'Contract not found' });
    }
});

// F3. Option bars
app.get('/api/options/bars/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { timeframe, start, end, limit } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/options/bars?symbols=${encodeURIComponent(req.params.symbol)}&timeframe=${timeframe || '1Day'}`;
    if (start) url += `&start=${start}`;
    if (end) url += `&end=${end}`;
    if (limit) url += `&limit=${limit}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ bars: {} });
    }
});

// F4. Option trades
app.get('/api/options/trades/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { start, end, limit } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/options/trades?symbols=${encodeURIComponent(req.params.symbol)}`;
    if (start) url += `&start=${start}`;
    if (end) url += `&end=${end}`;
    if (limit) url += `&limit=${limit || 50}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ trades: {} });
    }
});

// F5. Option snapshot
app.get('/api/options/snapshot/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/options/snapshots?symbols=${encodeURIComponent(req.params.symbol)}&feed=indicative`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ snapshots: {} });
    }
});

// F6. Option exchange codes
app.get('/api/options/exchanges', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/options/meta/exchanges`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ 'A': 'NYSE American Options', 'B': 'BOX Options Exchange', 'C': 'CBOE', 'H': 'ISE Gemini', 'I': 'ISE', 'M': 'MIAX', 'N': 'NYSE Arca Options', 'O': 'Options Price Reporting Authority', 'P': 'MIAX Pearl', 'Q': 'NASDAQ Options Market', 'W': 'CBOE C2', 'X': 'NASDAQ OMX PHLX', 'Z': 'BATS Options' });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP G: Stock Market Data Enhancements
// ──────────────────────────────────────────────────────────────────────────

// G1. Stock historical trades
app.get('/api/stock/:symbol/trades', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { start, end, limit, feed } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v2/stocks/${req.params.symbol}/trades?`;
    if (start) url += `start=${start}&`;
    if (end) url += `end=${end}&`;
    if (limit) url += `limit=${limit || 50}&`;
    if (feed) url += `feed=${feed}&`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ trades: [], symbol: req.params.symbol });
    }
});

// G2. Stock historical quotes (NBBO)
app.get('/api/stock/:symbol/quotes', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { start, end, limit, feed } = req.query;
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v2/stocks/${req.params.symbol}/quotes?`;
    if (start) url += `start=${start}&`;
    if (end) url += `end=${end}&`;
    if (limit) url += `limit=${limit || 50}&`;
    if (feed) url += `feed=${feed}&`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ quotes: [], symbol: req.params.symbol });
    }
});

// G3. Market movers (top gainers/losers)
app.get('/api/market/movers', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const top = req.query.top || 10;
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/screener/stocks/movers?top=${top}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({
            gainers: [
                { symbol: 'NVDA', percent_change: 4.2, price: 135.50, change: 5.45, volume: 45000000 },
                { symbol: 'TSLA', percent_change: 3.1, price: 248.30, change: 7.45, volume: 32000000 },
                { symbol: 'AMZN', percent_change: 2.8, price: 192.40, change: 5.25, volume: 28000000 }
            ],
            losers: [
                { symbol: 'META', percent_change: -2.5, price: 485.20, change: -12.40, volume: 18000000 },
                { symbol: 'GOOGL', percent_change: -1.8, price: 176.30, change: -3.23, volume: 22000000 },
                { symbol: 'AAPL', percent_change: -1.2, price: 191.50, change: -2.33, volume: 35000000 }
            ]
        });
    }
});

// G4. Most active stocks
app.get('/api/market/most-active', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const top = req.query.top || 10;
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/screener/stocks/most-actives?top=${top}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json({ most_actives: [
            { symbol: 'NVDA', volume: 85000000, trade_count: 520000 },
            { symbol: 'TSLA', volume: 62000000, trade_count: 410000 },
            { symbol: 'AAPL', volume: 55000000, trade_count: 380000 },
            { symbol: 'SPY', volume: 48000000, trade_count: 350000 },
            { symbol: 'AMD', volume: 42000000, trade_count: 290000 }
        ]});
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP H: Activities (enhanced)
// ──────────────────────────────────────────────────────────────────────────

// H1. All activities with pagination
app.get('/api/portfolio/:id/activities/all', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { after, until, direction, page_size, page_token, category } = req.query;
    let url = `${cfg.base_url}/v2/account/activities?`;
    if (after) url += `after=${after}&`;
    if (until) url += `until=${until}&`;
    if (direction) url += `direction=${direction}&`;
    if (page_size) url += `page_size=${page_size}&`;
    if (page_token) url += `page_token=${page_token}&`;
    if (category) url += `category=${category}&`;
    try {
        const activities = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(activities);
    } catch (e) {
        res.json([]);
    }
});

// H2. Activities by type
app.get('/api/portfolio/:id/activities/:type', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    const { after, until, direction, page_size, page_token } = req.query;
    let url = `${cfg.base_url}/v2/account/activities/${req.params.type}?`;
    if (after) url += `after=${after}&`;
    if (until) url += `until=${until}&`;
    if (direction) url += `direction=${direction}&`;
    if (page_size) url += `page_size=${page_size}&`;
    if (page_token) url += `page_token=${page_token}&`;
    try {
        const activities = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(activities);
    } catch (e) {
        res.json([]);
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP I: Corporate Actions
// ──────────────────────────────────────────────────────────────────────────

// I1. Corporate action announcements
app.get('/api/corporate-actions', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { ca_types, since, until: untilDate, symbol, cusip, date_type } = req.query;
    let url = `${cfg.base_url}/v2/corporate_actions/announcements?`;
    if (ca_types) url += `ca_types=${ca_types}&`;
    if (since) url += `since=${since}&`;
    if (untilDate) url += `until=${untilDate}&`;
    if (symbol) url += `symbol=${symbol}&`;
    if (cusip) url += `cusip=${cusip}&`;
    if (date_type) url += `date_type=${date_type}&`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.json([]);
    }
});

// I2. Single corporate action
app.get('/api/corporate-action/:id', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    try {
        const data = await alpacaRequest('GET', `${cfg.base_url}/v2/corporate_actions/announcements/${req.params.id}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP J: Market Calendar
// ──────────────────────────────────────────────────────────────────────────

app.get('/api/market/calendar', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { start, end } = req.query;
    let url = `${cfg.base_url}/v2/calendar?`;
    if (start) url += `start=${start}&`;
    if (end) url += `end=${end}&`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        const days = [];
        const d = new Date();
        for (let i = 0; i < 30; i++) {
            const dt = new Date(d);
            dt.setDate(dt.getDate() + i);
            if (dt.getDay() > 0 && dt.getDay() < 6) {
                days.push({ date: dt.toISOString().slice(0, 10), open: '09:30', close: '16:00', session_open: '07:00', session_close: '19:00' });
            }
        }
        res.json(days);
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP K: Options Position Actions
// ──────────────────────────────────────────────────────────────────────────

// K1. Exercise option
app.post('/api/portfolio/:id/option/exercise/:symbol', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const result = await alpacaRequest('POST', `${cfg.base_url}/v2/positions/${encodeURIComponent(req.params.symbol)}/exercise`, cfg.api_key, cfg.api_secret);
        res.json(result || { success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// K2. Do-not-exercise option
app.post('/api/portfolio/:id/option/no-exercise/:symbol', async (req, res) => {
    const cfg = portfoliosConfig[req.params.id];
    if (!cfg) return res.status(404).json({ error: 'Portfolio not found' });
    try {
        const result = await alpacaRequest('POST', `${cfg.base_url}/v2/positions/${encodeURIComponent(req.params.symbol)}/do-not-exercise`, cfg.api_key, cfg.api_secret);
        res.json(result || { success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

if (require.main === module) {
    app.listen(PORT, () => {
        console.log(`=======================================================`);
        console.log(`  Auto Trading Portfolios Dashboard Server started!   `);
        console.log(`  Access dashboard at: http://localhost:${PORT}        `);
        console.log(`=======================================================`);
    });
}

module.exports = app;
