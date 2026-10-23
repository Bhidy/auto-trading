const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');

const app = express();
const PORT = process.env.PORT || 3000;

// Route matching must be exact: with Express's default case-INSENSITIVE routing,
// `/API/.../order` matched the order handler while a case-sensitive prefix check
// let it skip the auth gate (audit 2026-10-23, D1). MUST be set before the first
// app.use(): Express creates its router lazily and freezes these options then.
app.set('case sensitive routing', true);
app.set('strict routing', false);

// Express 4 does not route async rejections or post-await throws to the error
// handler: the request simply hangs until the 30s serverless timeout (audit
// 2026-10-23, D4: `/api/market/bars/X?limit=abc`). Wrap every route handler so
// any failure lands in the single JSON error handler at the bottom of this file.
for (const verb of ['get', 'post', 'put', 'patch', 'delete']) {
    const register = app[verb].bind(app);
    app[verb] = (route, ...handlers) => {
        if (verb === 'get' && handlers.length === 0) return register(route); // app.get(setting)
        return register(route, ...handlers.map(h => (typeof h === 'function' && h.length < 4)
            ? (req, res, next) => { try { return Promise.resolve(h(req, res, next)).catch(next); } catch (e) { return next(e); } }
            : h));
    };
}

// Behind the Vercel proxy — needed so rate-limiting sees the real client IP.
app.set('trust proxy', 1);

// Security headers. A script-only CSP (post-deploy audit D11): pages use inline
// scripts/handlers, so 'unsafe-inline' stays, but script hosts are pinned to the
// ones the pages actually load — jsDelivr (Chart.js, GSAP, three, SheetJS) and
// TradingView's widget loader on Market Pulse. Styles, fonts, images, frames and
// fetches are deliberately left unrestricted (no default-src) so Google Fonts,
// logo images and the TradingView iframe keep working. COEP stays off.
app.use(helmet({
    contentSecurityPolicy: {
        useDefaults: false,
        directives: {
            defaultSrc: helmet.contentSecurityPolicy.dangerouslyDisableDefaultSrc,
            scriptSrc: ["'self'", "'unsafe-inline'", 'https://cdn.jsdelivr.net', 'https://s3.tradingview.com'],
            objectSrc: ["'none'"],
            baseUri: ["'self'"],
        },
    },
    crossOriginEmbedderPolicy: false,
}));

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


// Constant-time secret comparison that is also length-safe: both sides are
// hashed to fixed-length digests first, so timingSafeEqual never throws on a
// length mismatch and the response time does not reveal the secret's length.
function secretMatches(provided, secret) {
    if (!secret) return false;
    const a = crypto.createHash('sha256').update(String(provided)).digest();
    const b = crypto.createHash('sha256').update(String(secret)).digest();
    return crypto.timingSafeEqual(a, b);
}

function tokenMatches(provided) {
    const a = Buffer.from(String(provided));
    const b = Buffer.from(ACCESS_TOKEN);
    return a.length === b.length && crypto.timingSafeEqual(a, b);
}

app.use((req, res, next) => {
    // Reject dot-segment / encoded-traversal paths outright — no legitimate
    // dashboard URL contains them.
    if (/(^|\/)\.\.?(\/|$)|%2e|%5c/i.test(req.originalUrl.split('?')[0])) {
        return res.status(400).json({ error: 'Bad path.' });
    }
    // Gate EVERY mutating verb on EVERY path (not a path-prefix check). DELETE
    // (cancel order / cancel-all) and PATCH/PUT (replace order) reach the broker;
    // anonymous DELETE /orders would wipe protective bracket stops. Static files
    // never accept mutations, so there is no legitimate unauthenticated case.
    if (!MUTATING_METHODS.has(req.method)) return next();
    if (!ACCESS_TOKEN) {
        return res.status(503).json({
            error: 'Trade actions are disabled. Set DASHBOARD_ACCESS_TOKEN to enable.',
        });
    }
    const bearer = (req.get('authorization') || '').replace(/^Bearer\s+/i, '');
    const provided = bearer || req.get('x-access-token') || '';
    if (!provided || !tokenMatches(provided)) {
        return res.status(401).json({ error: 'Unauthorized.' });
    }
    return next();
});

// Strict input validation for every route (audit 2026-10-23, D6/D7). Values are
// interpolated into upstream Alpaca URLs, so each must be a plain token: no dot
// segments, no `&`/`?`/`#` smuggling, no arrays/objects from qs bracket syntax.
const SAFE_VALUE = /^[A-Za-z0-9 ._:,+=\-\/]*$/;
// A symbol list (`symbols=A,B,...`, up to 50 tickers for bars-batch) needs more
// room than a single token; every other value stays capped at 200 characters.
const MAX_VALUE_LEN = { symbols: 600 };
function unsafeValue(v, maxLen = 200) {
    if (Array.isArray(v) || (v !== null && typeof v === 'object')) return true;
    const str = String(v);
    return str.length > maxLen || !SAFE_VALUE.test(str) || /(^|\/)\.\.?(\/|$)/.test(str);
}
app.use('/api', (req, res, next) => {
    for (const [k, v] of Object.entries(req.query || {})) {
        if (unsafeValue(v, MAX_VALUE_LEN[k] || 200)) return res.status(400).json({ error: `Invalid query parameter: ${k}` });
    }
    return next();
});

// CDN caching (audit 2026-10-23 follow-up). Pure market-data GETs are identical
// for every viewer and IEX data is 15-min delayed, so a 15 s edge cache removes
// most duplicate Alpaca calls. Everything else under /api — portfolio, account,
// orders, positions, health, intelligence, state — is per-book truth and is
// explicitly `no-store`. The cache header is applied only to a 200 response, so
// an upstream error is never pinned at the edge. The crypto order book (5 s
// depth refresh) is deliberately NOT cached.
const MARKET_CACHE_CONTROL = 'public, s-maxage=15, stale-while-revalidate=30';
const MARKET_CACHE_ROUTES = [
    /^\/api\/market\/bars\/[^/]+$/,
    /^\/api\/market\/bars-batch$/,
    /^\/api\/market\/(quotes|sectors|movers|most-active)$/,
    /^\/api\/market-(indices|news)$/,
    /^\/api\/stock\/[^/]+\/(details|trades|quotes)$/,
    /^\/api\/crypto\/(bars|snapshot|quotes|trades)\/.+$/,
    /^\/api\/supabase\/market$/,
];
function isMarketDataRoute(method, urlPath) {
    return (method === 'GET' || method === 'HEAD') && MARKET_CACHE_ROUTES.some(re => re.test(urlPath));
}
// Reference data (tradable-asset master, exchange calendar) changes at most daily:
// a 1 h edge cache (post-deploy audit D9 — /api/assets was 14.6 MB / 5.2 s per hit).
const REFERENCE_CACHE_CONTROL = 'public, s-maxage=3600, stale-while-revalidate=600';
const REFERENCE_CACHE_ROUTES = [/^\/api\/assets$/, /^\/api\/market\/calendar$/];
function isReferenceDataRoute(method, urlPath) {
    return (method === 'GET' || method === 'HEAD') && REFERENCE_CACHE_ROUTES.some(re => re.test(urlPath));
}
app.use('/api', (req, res, next) => {
    const urlPath = req.originalUrl.split('?')[0];
    const policy = isMarketDataRoute(req.method, urlPath) ? MARKET_CACHE_CONTROL
        : isReferenceDataRoute(req.method, urlPath) ? REFERENCE_CACHE_CONTROL : null;
    if (!policy) {
        res.setHeader('Cache-Control', 'no-store');
        return next();
    }
    const writeHead = res.writeHead;
    res.writeHead = function (statusCode, ...rest) {
        this.setHeader('Cache-Control', statusCode === 200 ? policy : 'no-store');
        return writeHead.call(this, statusCode, ...rest);
    };
    return next();
});
for (const name of ['id', 'order_id', 'client_id', 'symbol', 'type', 'underlying', 'wl_id']) {
    app.param(name, (req, res, next, value) => {
        if (unsafeValue(value)) return res.status(400).json({ error: `Invalid ${name}.` });
        return next();
    });
}

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
            { id: 'portfolio_1', label: 'Improving Brain', account: 'PA3HULQQ8OOH', strategy: 'Multi-factor scoring with regime detection', dir: './' },
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
    // Null-prototype map: `portfoliosConfig['__proto__']` / `['constructor']` must be
    // undefined (-> 404), never an inherited object served as a fake account (D9).
    portfoliosConfig = Object.assign(Object.create(null), portfoliosConfig);
    console.log('Portfolios configured:', Object.keys(portfoliosConfig).join(', '));
}

// Initial load
loadConfig();

// Helper to query Alpaca REST API safely
function alpacaRequest(method, url, apiKey, apiSecret, body = null) {
    if (!apiKey || !apiSecret || apiKey.includes('REDACTED') || apiSecret.includes('REDACTED') || apiKey === 'MOCK_KEY_ID_REDACTED') {
        return Promise.reject(new Error('Alpaca keys are redacted or missing; running in mock fallback mode.'));
    }
    // Last line of defence against path traversal (audit 2026-10-23, D6): the URL
    // parser silently resolves `..` segments, so `/v2/account/activities/../../clock`
    // became `/v2/clock`. Refuse any dot segment and any non-Alpaca host.
    const rawPath = String(url).replace(/^https?:\/\/[^/]+/i, '').split('?')[0];
    if (/(^|\/)\.\.?(\/|$)/.test(rawPath) || /%2e|%5c/i.test(rawPath)) {
        return Promise.reject(Object.assign(new Error('Refused: unsafe upstream path.'), { statusCode: 400 }));
    }
    return new Promise((resolve, reject) => {
        try {
            const parsedUrl = new URL(url);
            if (!/(^|\.)alpaca\.markets$/i.test(parsedUrl.hostname)) {
                reject(Object.assign(new Error('Refused: non-Alpaca upstream host.'), { statusCode: 400 }));
                return;
            }
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
                        reject(Object.assign(new Error(`Alpaca API error: ${res.statusCode} ${data}`),
                            { statusCode: res.statusCode }));
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

// Map upstream failures to safe client responses (audit 2026-10-23, D10): raw
// broker error bodies (order ids, validation internals) stay in server logs only.
function sendUpstreamError(res, e) {
    const code = Number(e && e.statusCode) || 0;
    console.error('[upstream]', e && e.message);
    if (code >= 400 && code < 500) {
        const status = code === 401 || code === 403 ? 502 : code;   // our creds, not the caller's
        return res.status(status).json({ error: status === 404 ? 'Not found.' : 'Request rejected by broker.' });
    }
    return res.status(502).json({ error: 'Upstream broker request failed.' });
}

// ──────────────────────────────────────────────────────────────────────────
// LIVE STATE OVERLAY (audit 2026-10-23, D2/D3). The bots commit state JSON many
// times a day, but data-only commits never redeploy Vercel, so the bundled files
// were frozen at the last code deploy (July): stale trade logs, signals, and a
// wrong halt flag. The repo is public, so every /api request first refreshes
// (≤ once per STATE_TTL_MS per instance) the state files this server reads from
// the latest commit on main via raw.githubusercontent.com. The bundled copy is
// the fallback on any fetch/parse failure, so an outage degrades to "stale",
// never to "broken". Disable with DASHBOARD_LIVE_STATE=0.
// ──────────────────────────────────────────────────────────────────────────
const LIVE_STATE = process.env.DASHBOARD_LIVE_STATE !== '0';
const STATE_RAW_BASE = (process.env.DASHBOARD_STATE_RAW_BASE
    || 'https://raw.githubusercontent.com/Bhidy/auto-trading/main/dashboard/').replace(/\/?$/, '/');
const STATE_TTL_MS = Number(process.env.DASHBOARD_STATE_TTL_MS || 60000);
const stateOverlay = new Map();      // absPath -> parsed JSON from latest main
const hotStatePaths = new Set();     // absPaths this instance has been asked to read
const STATE_FAIL_BACKOFF_MS = 5 * 60000;   // after a fully failed refresh, stop retrying for 5 min
const stateMeta = { lastRefresh: 0, lastOk: 0, files: 0, errors: 0, coreOk: null, inflight: null, backoffUntil: 0 };
// Bounded fan-out: firing every tracked file at raw.githubusercontent.com at once
// tripped its per-IP throttling (prod saw 15/16 then 12 then 1 errors within
// minutes — post-deploy audit D3), so at most this many fetches run at a time.
const STATE_FETCH_CONCURRENCY = 6;
const STATE_CORE_RETRY_MS = 15000;  // a refresh whose core files failed retries sooner than TTL
// Per-file refresh status, keyed by repo-relative path (never an absolute path):
// { lastOk, lastError, errors (consecutive), absent (404 on main) }.
const stateFileStatus = new Map();
// Core files: each book's state + trade log. A refresh counts as "ok" only when
// every core file refreshed. CONSISTENT-PAIR RULE: a book's state file and its
// trade log are only ever served from the SAME snapshot. If one of the pair fails
// in a refresh, neither is updated: the instance keeps serving the last pair that
// refreshed together, or — on a cold instance with no such pair yet — the bundled
// pair. Mixing a fresh trade log with a stale state (or vice versa) shows trades
// that the account/halt state does not reflect, so a whole stale pair is
// preferred over a mixed one.
const stateCorePairs = [];           // [{ id, state: absPath, tradeLog: absPath }]

function overlayKey(filePath) {
    const rel = path.relative(ROOT_DIR, path.resolve(filePath));
    if (!rel || rel.startsWith('..') || path.isAbsolute(rel) || !rel.endsWith('.json')) return null;
    // Journals are listed from the bundle (readdir), so overlaying individual
    // journal files cannot surface new days — keep them out of the refresh set.
    if (/(^|\/)journal\//.test(rel.split(path.sep).join('/'))) return null;
    return rel.split(path.sep).join('/');
}

function fetchRawJson(rel, timeoutMs = 2500, base = STATE_RAW_BASE) {
    return new Promise((resolve, reject) => {
        const req = https.get(base + rel.split('/').map(encodeURIComponent).join('/'),
            { timeout: timeoutMs, headers: { 'User-Agent': 'auto-trading-dashboard' } }, (r) => {
                if (r.statusCode !== 200) { r.resume(); return reject(new Error(`HTTP ${r.statusCode}`)); }
                let body = '';
                r.setEncoding('utf8');
                r.on('data', (c) => { body += c; if (body.length > 8e6) req.destroy(new Error('too large')); });
                r.on('end', () => { try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
            });
        req.on('timeout', () => req.destroy(new Error('timeout')));
        req.on('error', reject);
    });
}

async function settledPool(items, limit, fn) {
    const out = new Array(items.length);
    let next = 0;
    async function worker() {
        while (next < items.length) {
            const i = next++;
            try { out[i] = { status: 'fulfilled', value: await fn(items[i]) }; }
            catch (e) { out[i] = { status: 'rejected', reason: e }; }
        }
    }
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
    return out;
}

// Pure decision step of a refresh, separated for unit tests. `results` maps an
// absPath to { ok: true, value } | { ok: false, absent: bool }. Returns the
// entries to write into the overlay and whether every core file refreshed.
function planOverlayUpdate(results, corePairs) {
    const writes = new Map();
    for (const [abs, r] of results) if (r.ok) writes.set(abs, r.value);
    let coreOk = true;
    for (const pair of corePairs) {
        const a = results.get(pair.state), b = results.get(pair.tradeLog);
        const usable = (r) => !!r && (r.ok || r.absent);
        if (!usable(a) || !usable(b)) {
            coreOk = false;
            writes.delete(pair.state);
            writes.delete(pair.tradeLog);
        } else if (!(a.ok && b.ok)) {
            // One side is absent on main: serve both from the bundle, never mixed.
            writes.delete(pair.state);
            writes.delete(pair.tradeLog);
        }
    }
    return { writes, coreOk };
}

async function refreshStateOverlay() {
    const now = Date.now();
    if (!LIVE_STATE || now - stateMeta.lastRefresh < STATE_TTL_MS || now < stateMeta.backoffUntil) return;
    if (stateMeta.inflight) return stateMeta.inflight;
    stateMeta.inflight = (async () => {
        const targets = [...hotStatePaths].map(p => [p, overlayKey(p)]).filter(([, k]) => k);
        const settled = await settledPool(targets, STATE_FETCH_CONCURRENCY, ([, k]) => fetchRawJson(k));
        const results = new Map();
        let ok = 0, errors = 0;
        const at = Date.now();
        settled.forEach((r, i) => {
            const [abs, rel] = targets[i];
            const st = stateFileStatus.get(rel) || { lastOk: null, lastError: null, errors: 0, absent: false };
            if (r.status === 'fulfilled') {
                results.set(abs, { ok: true, value: r.value });
                Object.assign(st, { lastOk: at, errors: 0, absent: false });
                ok++;
            } else if (/HTTP 404/.test(String(r.reason && r.reason.message))) {
                results.set(abs, { ok: false, absent: true });
                Object.assign(st, { errors: 0, absent: true });
            } else {
                results.set(abs, { ok: false, absent: false });
                Object.assign(st, { lastError: at, errors: st.errors + 1, absent: false });
                errors++;
            }
            stateFileStatus.set(rel, st);
        });
        const { writes, coreOk } = planOverlayUpdate(results, stateCorePairs);
        for (const [abs, value] of writes) stateOverlay.set(abs, value);
        stateMeta.lastRefresh = Date.now();
        stateMeta.coreOk = coreOk;
        if (coreOk) stateMeta.lastOk = stateMeta.lastRefresh;
        else if (ok) stateMeta.lastRefresh -= Math.max(0, STATE_TTL_MS - STATE_CORE_RETRY_MS);
        if (!ok && errors) stateMeta.backoffUntil = stateMeta.lastRefresh + STATE_FAIL_BACKOFF_MS;
        stateMeta.files = ok;
        stateMeta.errors = errors;
    })().finally(() => { stateMeta.inflight = null; });
    return stateMeta.inflight;
}

// ── Journal overlay (audit 2026-10-23 follow-up). Journal directories were
// listed from the deployed bundle (readdirSync), so a day journaled after the
// last code deploy never appeared in prod. For each journal directory a route
// actually reads, the last JOURNAL_LOOKBACK_DAYS ET calendar days are fetched
// by exact filename (`YYYY-MM-DD.json`) from the repo's raw files — no GitHub
// API listing calls, so no unauthenticated rate limit. 404 = that day has no
// journal; any failure leaves the bundled copy as the fallback. Journals are
// fetched from the REPO ROOT layout (journal/, event-driven-bot/journal/, ...),
// which is where the bots commit them and which the dashboard bundle mirrors.
const JOURNAL_RAW_BASE = (process.env.DASHBOARD_JOURNAL_RAW_BASE
    || STATE_RAW_BASE.replace(/dashboard\/$/, '')).replace(/\/?$/, '/');
const JOURNAL_LOOKBACK_DAYS = 10;
const JOURNAL_TTL_MS = Number(process.env.DASHBOARD_JOURNAL_TTL_MS || 5 * 60000);
const journalOverlay = new Map();    // abs journal file -> parsed JSON from latest main
const journalDirMeta = new Map();    // abs journal dir -> { lastRefresh, inflight }

// The last `n` ET calendar dates, newest first (calendar arithmetic, not 24 h
// steps, so a DST transition can never skip or repeat a day).
function recentEtDates(n, now = Date.now()) {
    const [y, m, d] = etDate(now).split('-').map(Number);
    const out = [];
    for (let i = 0; i < n; i++) out.push(new Date(Date.UTC(y, m - 1, d - i)).toISOString().slice(0, 10));
    return out;
}

function journalRepoRel(dir) {
    const rel = path.relative(ROOT_DIR, path.resolve(dir));
    if (rel.startsWith('..') || path.isAbsolute(rel)) return null;
    const posix = rel.split(path.sep).join('/');
    return /(^|\/)journal$/.test(posix) ? posix : null;
}

// Dates the overlay must cover for one journal directory: EVERY ET calendar day
// after the newest journal in the deployed bundle through today (a deploy can be
// weeks old — fetching only a fixed recent window left a silent multi-week gap
// in journal-backed equity charts; Codex review on PR #95), and never fewer
// than JOURNAL_LOOKBACK_DAYS. Capped at JOURNAL_MAX_GAP_DAYS (newest kept).
const JOURNAL_MAX_GAP_DAYS = Number(process.env.DASHBOARD_JOURNAL_MAX_GAP_DAYS || 400);
const JOURNAL_FETCH_BATCH = 20;
function journalDatesToCover(abs, now = Date.now()) {
    let newestBundled = null;
    try {
        if (fs.existsSync(abs)) {
            for (const f of fs.readdirSync(abs)) {
                const m = /^(\d{4}-\d{2}-\d{2})\.json$/.exec(f);
                if (m && (!newestBundled || m[1] > newestBundled)) newestBundled = m[1];
            }
        }
    } catch (e) { /* bundle unreadable: fall back to the minimum window */ }
    const today = etDate(now);
    let span = JOURNAL_LOOKBACK_DAYS;
    if (newestBundled && newestBundled < today) {
        const gap = Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${newestBundled}T00:00:00Z`)) / 86400000);
        span = Math.max(span, gap);
    }
    return recentEtDates(Math.min(span, JOURNAL_MAX_GAP_DAYS), now);
}

function refreshJournalDir(dir) {
    const rel = journalRepoRel(dir);
    if (!LIVE_STATE || !rel) return null;
    const abs = path.resolve(dir);
    let meta = journalDirMeta.get(abs);
    if (!meta) { meta = { lastRefresh: 0, inflight: null, missing: new Set() }; journalDirMeta.set(abs, meta); }
    if (meta.inflight) return meta.inflight;
    if (Date.now() - meta.lastRefresh < JOURNAL_TTL_MS) return null;
    meta.inflight = (async () => {
        const dates = journalDatesToCover(abs);
        const live = new Set(dates.slice(0, 2));   // today + yesterday can still be appended
        // Past days are immutable: fetch each once (hit or confirmed 404), then reuse.
        const todo = dates.filter(dt => live.has(dt)
            || (!journalOverlay.has(path.join(abs, `${dt}.json`)) && !meta.missing.has(dt)));
        for (let i = 0; i < todo.length; i += JOURNAL_FETCH_BATCH) {
            const batch = todo.slice(i, i + JOURNAL_FETCH_BATCH);
            const results = await Promise.allSettled(batch.map(dt =>
                fetchRawJson(`${rel}/${dt}.json`, 2500, JOURNAL_RAW_BASE)));
            results.forEach((r, j) => {
                const dt = batch[j];
                if (r.status === 'fulfilled') journalOverlay.set(path.join(abs, `${dt}.json`), r.value);
                else if (/HTTP 404/.test(String(r.reason && r.reason.message)) && !live.has(dt)) meta.missing.add(dt);
            });
        }
        meta.lastRefresh = Date.now();
    })().finally(() => { meta.inflight = null; });
    return meta.inflight;
}

// Journal filenames for a directory: the bundle's listing merged with the
// recent days fetched from main, deduplicated by filename, sorted. Only a
// directory with nothing fetched yet waits for its first refresh.
async function listJournalFiles(dir) {
    const abs = path.resolve(dir);
    const inDir = (k) => path.dirname(k) === abs;
    const p = refreshJournalDir(abs);
    if (p) {
        if (![...journalOverlay.keys()].some(inDir)) await p.catch(() => {});
        else p.catch(() => {});
    }
    const names = new Set();
    try {
        if (fs.existsSync(abs)) fs.readdirSync(abs).filter(f => f.endsWith('.json')).forEach(f => names.add(f));
    } catch (e) {
        console.error(`Error listing journal dir ${abs}:`, e.message);
    }
    for (const k of journalOverlay.keys()) if (inDir(k)) names.add(path.basename(k));
    return [...names].sort();
}

// Stale-while-revalidate: only a cold instance (empty overlay) waits for the
// first refresh; afterwards requests are served immediately from the current
// overlay while the next refresh runs in the background (after-audit N8).
app.use('/api', (req, res, next) => {
    const p = refreshStateOverlay();
    if (stateOverlay.size === 0 && p) return p.then(() => next(), () => next());
    if (p) p.catch(() => {});
    return next();
});

// Helper to read JSON files safely (latest committed state first, bundle second)
function readJsonFile(filePath, defaultValue = {}) {
    if (journalOverlay.size) {
        const abs = path.resolve(filePath);
        if (journalOverlay.has(abs)) return journalOverlay.get(abs);
    }
    if (LIVE_STATE && overlayKey(filePath)) {
        const abs = path.resolve(filePath);
        if (!hotStatePaths.has(abs)) hotStatePaths.add(abs);   // joins the next scheduled refresh
        if (stateOverlay.has(abs)) return stateOverlay.get(abs);
    }
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
    // Public endpoint: only what the deploy smoke test and the CLAUDE.md
    // verification need (rootDir + the three critical files' exists/size).
    // No absolute paths, cwd or config layout (post-deploy audit D11).
    const pf1 = getPortfolioPaths('portfolio_1');
    const info = { rootDir: ROOT_DIR, isVercel: !!IS_VERCEL, files: {} };
    if (pf1) {
        for (const k of ['tradeLog', 'signals', 'state']) {
            const exists = fs.existsSync(pf1[k]);
            info.files[k] = { exists, size: exists ? fs.statSync(pf1[k]).size : 0 };
        }
    }
    const iso = (ms) => (ms ? new Date(ms).toISOString() : null);
    const files = {};
    for (const [rel, st] of [...stateFileStatus.entries()].sort(([a], [b]) => a.localeCompare(b))) {
        files[rel] = { lastOk: iso(st.lastOk), lastError: iso(st.lastError), errors: st.errors, absent: st.absent };
    }
    info.liveState = {
        enabled: LIVE_STATE, source: STATE_RAW_BASE, tracked: hotStatePaths.size,
        overlaid: stateOverlay.size, lastRefresh: iso(stateMeta.lastRefresh),
        lastOk: iso(stateMeta.lastOk), coreOk: stateMeta.coreOk, errors: stateMeta.errors,
        concurrency: STATE_FETCH_CONCURRENCY, files,
        journals: { source: JOURNAL_RAW_BASE, lookbackDays: JOURNAL_LOOKBACK_DAYS,
            dirs: journalDirMeta.size, files: journalOverlay.size },
    };
    res.json(info);
});

// Momentum sleeve live-readiness ledger (P1 high-return PAPER sleeve). Read-only:
// serves the committed data/momentum_readiness.json computed by P1 EOD. Honest
// go/no-go evidence — never a trade trigger.
app.get('/api/momentum/readiness', (req, res) => {
    const p = path.join(ROOT_DIR, 'data', 'momentum_readiness.json');
    res.json(readJsonFile(p, { status: 'not_started', note: 'No readiness data yet.' }));
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


// Engine safety ledgers surfaced by the intelligence endpoint (see getIntelligencePaths).
const SAFETY_FILES = ['haltGovernance', 'pendingExits', 'pendingEntries', 'bookedFills'];

// Seed the live-state overlay with every per-portfolio file so even the first
// request after a cold start serves the latest committed state.
// Seed the live-state overlay with every file the API reads for every book (state,
// trade log, signals, params, learning report, intelligence + safety ledgers), so
// the first request after a cold start is served from ONE refresh of all of them
// rather than a mix of fresh and bundled files (post-deploy audit D3). Each book's
// state + trade log is registered as a core pair (see the consistent-pair rule).
(function seedHotStatePaths() {
    const add = (f) => { if (f && overlayKey(f)) hotStatePaths.add(path.resolve(f)); };
    for (const id of Object.keys(portfoliosConfig)) {
        const p = getIntelligencePaths(id);
        if (!p) continue;
        for (const k of ['state', 'tradeLog', 'signals', 'strategyParams', 'learningReport',
            'reconciliation', 'orderState', 'paramChangeLog', 'governanceAudit', 'lastGood', ...SAFETY_FILES]) add(p[k]);
        if (overlayKey(p.state) && overlayKey(p.tradeLog)) {
            stateCorePairs.push({ id, state: path.resolve(p.state), tradeLog: path.resolve(p.tradeLog) });
        }
    }
    add(path.join(ROOT_DIR, 'data', 'momentum_readiness.json'));
})();

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
        // Engine safety ledgers (P1 runner, audit 2026-10-23): governed halt
        // clears, orders awaiting EOD settlement, and the booked-fill ledger.
        haltGovernance: d('halt_governance.json'),
        pendingExits: d('pending_exits.json'),
        pendingEntries: d('pending_entries.json'),
        bookedFills: d('booked_fills.json'),
    };
}


// Engine safety state for one book: halt latch + its evidence, confirmed peak
// equity, the last governed halt clear, orders awaiting EOD settlement and the
// fill ledger. Every value is read from committed state; a file the engine has
// not written yet is reported absent (`files.*=false`), never filled in.
function buildSafetyState(id, paths) {
    const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) ? null : Number(v);
    const str = (v) => (v === null || v === undefined || v === '') ? null : String(v);
    const rows = (v) => Array.isArray(v) ? v.filter(x => x && typeof x === 'object') : [];
    const state = readJsonFile(paths.state, {}) || {};
    const gov = readJsonFile(paths.haltGovernance, null);
    const exits = readJsonFile(paths.pendingExits, null);
    const entries = readJsonFile(paths.pendingEntries, null);
    const fills = readJsonFile(paths.bookedFills, null);

    const pendingRow = (p, kind) => ({
        kind, order_id: str(p.order_id), symbol: str(p.symbol), qty: num(p.qty),
        reason: str(p.reason), source: str(p.source), submitted_at: str(p.submitted_at),
        intended_price: num(p.intended_price),
    });
    const pending = [...rows(exits).map(p => pendingRow(p, 'exit')), ...rows(entries).map(p => pendingRow(p, 'entry'))]
        .sort((a, b) => String(b.submitted_at || '').localeCompare(String(a.submitted_at || '')));

    const clears = rows(gov).filter(r => r.type === 'halt_clear')
        .sort((a, b) => String(a.applied_at || '').localeCompare(String(b.applied_at || '')));
    const g = clears[clears.length - 1];
    let lastClear = null;
    if (g) {
        const reqd = (g.request && typeof g.request === 'object') ? g.request : {};
        const ver = (g.verification && typeof g.verification === 'object') ? g.verification : {};
        const cleared = (g.cleared_halt && typeof g.cleared_halt === 'object') ? g.cleared_halt : {};
        lastClear = {
            record: 'halt_governance', applied_at: str(g.applied_at), source: str(g.source),
            clear_key: str(g.clear_key), reason: str(reqd.reason), changed_by: str(reqd.changed_by),
            verified_equity: num(g.verified_equity), drawdown_pct_from_peak: num(ver.drawdown_pct_from_peak),
            kill_switch_drawdown_pct: num(g.kill_switch_drawdown_pct),
            cleared_halt_reason: str(cleared.halt_reason), cleared_halt_set_at: str(cleared.halt_set_at),
        };
    } else if (state.last_halt_clear && typeof state.last_halt_clear === 'object') {
        const c = state.last_halt_clear;
        lastClear = {
            record: 'portfolio_state', applied_at: str(c.applied_at), source: null, clear_key: str(c.clear_key),
            reason: null, changed_by: str(c.changed_by), verified_equity: num(c.verified_equity),
            drawdown_pct_from_peak: num(c.drawdown_pct_from_peak), kill_switch_drawdown_pct: null,
            cleared_halt_reason: null, cleared_halt_set_at: null,
        };
    }
    const attempt = state.halt_clear_last_attempt && typeof state.halt_clear_last_attempt === 'object'
        ? { at: str(state.halt_clear_last_attempt.at), applied: !!state.halt_clear_last_attempt.applied,
            source: str(state.halt_clear_last_attempt.source) } : null;

    const fillRows = (fills && typeof fills === 'object' && !Array.isArray(fills))
        ? Object.entries(fills).filter(([, v]) => v && typeof v === 'object') : [];
    const latestFills = fillRows
        .map(([oid, v]) => ({ order_id: oid, symbol: str(v.symbol), kind: str(v.kind), qty: num(v.qty), price: num(v.px), at: str(v.at) }))
        .sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')));

    const obs = rows(state.halt_observations);
    const halted = !!state.halted;
    const evidence = (state.halt_evidence && typeof state.halt_evidence === 'object') ? state.halt_evidence : null;
    // Same rule as the engine's annotate_halt_verification: a halt is verified
    // only when it carries timestamped equity evidence. A legacy halt latched
    // before stamping (no halt_verified field) is therefore unverified.
    let verified = null, unverifiedReason = null;
    if (halted) {
        verified = typeof state.halt_verified === 'boolean' ? state.halt_verified
            : !!(evidence && evidence.at && evidence.equity !== null && evidence.equity !== undefined);
        unverifiedReason = verified ? null : (str(state.halt_unverified_reason)
            || 'Latched with no recorded evidence (no equity reads or timestamp); cleared only by a governed halt_clear.');
    }
    return {
        engine_managed: id === 'portfolio_1',
        files: { halt_governance: gov !== null, pending_exits: exits !== null,
            pending_entries: entries !== null, booked_fills: fills !== null },
        halt: {
            halted,
            reason: halted ? str(state.halt_reason) : null,
            kind: halted ? str(state.halt_kind) : null,
            verified,
            unverified_reason: unverifiedReason,
            set_at: str(state.halt_set_at),
            until: str(state.halt_until),
            evidence,
            observations_count: obs.length,
            last_observation: obs.length ? obs[obs.length - 1] : null,
        },
        peak_equity: num(state.peak_equity) === null ? null
            : { value: num(state.peak_equity), at: str(state.peak_equity_at) },
        halt_governance: { total_clears: clears.length, last_clear: lastClear, last_attempt: attempt },
        pending: {
            exits: rows(exits).length, entries: rows(entries).length,
            total: pending.length, orders: pending.slice(0, 25),
        },
        booked_fills: { count: fillRows.length, latest: latestFills.slice(0, 5) },
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
        safety: buildSafetyState(id, paths),
    });
});

// Symbol → GICS sector (single source of truth for every sector the API reports:
// position rows in /details and the cross-portfolio concentration check). Sector
// ETFs map to the sector they track; broad index ETFs, T-bills/treasuries/gold and
// crypto get their own buckets. An unknown symbol is `null` ("Unclassified" in the
// UI) — never a guessed sector and never the book's strategy name (post-deploy
// audit D2: P3's ANET/DG/KO/MRK were all reported as "Financials").
const SECTOR_MAP = {
    SPY: 'Broad Market', QQQ: 'Broad Market', DIA: 'Broad Market', IWM: 'Broad Market',
    BIL: 'Defensive', SHY: 'Defensive', TLT: 'Defensive', GLD: 'Defensive',
    XLK: 'Technology', XLF: 'Financials', XLE: 'Energy', XLV: 'Health Care', XLY: 'Consumer Discretionary',
    XLP: 'Consumer Staples', XLI: 'Industrials', XLC: 'Communication Services', XLB: 'Materials',
    XLU: 'Utilities', XLRE: 'Real Estate',
    AAPL: 'Technology', MSFT: 'Technology', NVDA: 'Technology', AMD: 'Technology', AVGO: 'Technology',
    ANET: 'Technology', CSCO: 'Technology', INTC: 'Technology', INTU: 'Technology', LRCX: 'Technology',
    MRVL: 'Technology', MU: 'Technology', PANW: 'Technology', TER: 'Technology', WDAY: 'Technology',
    DDOG: 'Technology', ORCL: 'Technology', CRM: 'Technology', ADBE: 'Technology',
    GOOGL: 'Communication Services', GOOG: 'Communication Services', META: 'Communication Services',
    NFLX: 'Communication Services', T: 'Communication Services', VZ: 'Communication Services',
    AMZN: 'Consumer Discretionary', TSLA: 'Consumer Discretionary', HD: 'Consumer Discretionary',
    F: 'Consumer Discretionary', MCD: 'Consumer Discretionary', NKE: 'Consumer Discretionary',
    WMT: 'Consumer Staples', PG: 'Consumer Staples', KO: 'Consumer Staples', KR: 'Consumer Staples',
    DG: 'Consumer Staples', TGT: 'Consumer Staples', COST: 'Consumer Staples', PEP: 'Consumer Staples',
    JPM: 'Financials', MS: 'Financials', GS: 'Financials', C: 'Financials', AXP: 'Financials',
    CB: 'Financials', PGR: 'Financials', SCHW: 'Financials', SPGI: 'Financials', V: 'Financials',
    MA: 'Financials', BAC: 'Financials', WFC: 'Financials',
    XOM: 'Energy', CVX: 'Energy', COP: 'Energy', EOG: 'Energy', MPC: 'Energy', OXY: 'Energy',
    PSX: 'Energy', SLB: 'Energy', VLO: 'Energy',
    ABBV: 'Health Care', AMGN: 'Health Care', DHR: 'Health Care', EW: 'Health Care', JNJ: 'Health Care',
    LLY: 'Health Care', MEDP: 'Health Care', MRK: 'Health Care', TMO: 'Health Care', UNH: 'Health Care',
    PFE: 'Health Care',
    CAT: 'Industrials', CARR: 'Industrials', EMR: 'Industrials', GE: 'Industrials', PH: 'Industrials',
    RTX: 'Industrials', UNP: 'Industrials', UPS: 'Industrials', HON: 'Industrials',
    FCX: 'Materials', LIN: 'Materials',
    D: 'Utilities', NEE: 'Utilities', DUK: 'Utilities',
    SPG: 'Real Estate', PLD: 'Real Estate',
};

function sectorFor(symbol, assetClass) {
    const sym = String(symbol || '').trim().toUpperCase();
    if (assetClass === 'crypto' || /\/(USD|USDT|USDC)$/.test(sym)) return 'Crypto';
    return Object.prototype.hasOwnProperty.call(SECTOR_MAP, sym) ? SECTOR_MAP[sym] : null;
}

// ET (America/New_York) calendar date YYYY-MM-DD for a ms timestamp. Alpaca daily
// portfolio-history bars are stamped 00:00 UTC = 20:00 ET of the PRIOR trading day,
// so toISOString() mislabels every daily point +1 day (and lands two on Saturdays).
// Always label daily equity points in ET.
const etDate = (ms) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date(ms));

app.get('/api/intelligence/cross-portfolio', async (req, res) => {
    loadConfig();
    const singleNameCap = 10.0, sectorCap = 30.0;
    let totalEquity = 0;
    const bySymbol = {}, bySector = {};
    const books = [];

    for (const id of Object.keys(portfoliosConfig)) {
        const d = await fetchPortfolioData(id);
        if (!d) continue;
        const fbAcct = d.account ? null : stateAccountFallback(d.localState);
        const equity = d.account ? parseFloat(d.account.equity) : (fbAcct ? fbAcct.equity : 0);
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
            const sec = sectorFor(p.symbol) || 'Unclassified';
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
        sector: sectorFor(p.symbol, p.asset_class),
        source_portfolio: '',
        source_label: ''
    };
}

// Last committed account snapshot for a book whose live broker read failed.
// Returns null when the state carries no equity (the book is then reported in
// `missing_portfolios`, never filled with a made-up placeholder).
function stateAccountFallback(localState) {
    const ls = localState || {};
    const acct = ls.account || {};
    const equity = parseFloat(ls.equity ?? acct.portfolio_value ?? acct.equity);
    if (!Number.isFinite(equity)) return null;
    const cash = parseFloat(ls.cash ?? acct.cash);
    const dayPnl = parseFloat(ls.day_pnl || 0) || 0;
    const pos = ls.positions;
    return {
        equity,
        cash: Number.isFinite(cash) ? cash : 0,
        day_pnl: dayPnl,
        last_equity: equity - dayPnl,
        positions_count: Array.isArray(pos) ? pos.length : (pos && typeof pos === 'object') ? Object.keys(pos).length : (Number(pos) || 0),
    };
}

// Is a recorded halt consistent with the account as measured now? A kill-switch
// halt that records e.g. "73.94% drawdown" while equity is within a few % of its
// reference is a phantom (the 2026-07-07 bad-equity latch). The engine clears such
// halts only through the governed `halt_clear`; the dashboard must not present
// them as a verified lockdown in the meantime (after-audit N6).
function haltAssessment(localState, equity, initialCapital) {
    const ls = localState || {};
    if (!ls.halted) return { halt_verified: null, halt_measured_drawdown_pct: null, halt_recorded_drawdown_pct: null, halt_note_code: null, halt_note: null };
    const ref = Math.max(Number(initialCapital) || 100000, parseFloat(ls.peak_equity) || 0);
    const eq = parseFloat(equity);
    const measured = Number.isFinite(eq) && ref > 0 ? Math.max(0, (ref - eq) / ref * 100) : null;
    const m = /Kill switch:\s*([\d.]+)%/i.exec(ls.halt_reason || '');
    const recorded = m ? parseFloat(m[1]) : null;
    if (ls.halt_verified === false) {
        return { halt_verified: false, halt_measured_drawdown_pct: measured === null ? null : Math.round(measured * 100) / 100,
                 halt_recorded_drawdown_pct: recorded, halt_note_code: 'no_evidence',
                 halt_note: ls.halt_unverified_reason || 'Halt has no recorded evidence; governed review pending.' };
    }
    if (recorded !== null && measured !== null && recorded - measured > 5) {
        return { halt_verified: false, halt_measured_drawdown_pct: Math.round(measured * 100) / 100,
                 halt_recorded_drawdown_pct: recorded, halt_note_code: 'contradicted',
                 halt_note: `Recorded ${recorded.toFixed(2)}% drawdown contradicts measured ${measured.toFixed(2)}%; governed clear pending.` };
    }
    return { halt_verified: true, halt_measured_drawdown_pct: measured === null ? null : Math.round(measured * 100) / 100,
             halt_recorded_drawdown_pct: recorded, halt_note_code: null, halt_note: null };
}

// ──────────────────────────────────────────────────────────────────────────
// DAY-P/L BASIS (post-deploy audit D1). Day P/L stays Alpaca's definition,
// equity − last_equity (it includes realized P/L), but last_equity is the close
// of `account.balance_asof`, which before the open can be TWO sessions back. The
// API therefore states the basis explicitly and only calls the figure "today"
// when the market is open AND the basis is the session immediately before today:
//   day_pnl_basis_date     YYYY-MM-DD close the figure is measured from (or null)
//   market_open            from /v2/clock (cached ≤60 s per instance; estimated
//                          from NY wall time when the broker clock is unreachable)
//   previous_session_date  last trading session before today (ET), from /v2/calendar
//   day_pnl_is_today       market_open && basis === previous_session_date
// ──────────────────────────────────────────────────────────────────────────
const CLOCK_TTL_MS = 60000;
const CALENDAR_TTL_MS = 3600000;
const sessionCache = { clock: null, clockAt: 0, clockInflight: null, sessions: null, sessionsAt: 0, sessionsKey: '', sessionsInflight: null };

function firstKeyedConfig() {
    return Object.values(portfoliosConfig).find(c => c && c.api_key && c.api_secret) || Object.values(portfoliosConfig)[0] || null;
}

function isoDay(v) {
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(String(v || ''));
    return m ? m[1] : null;
}

async function marketClockCached() {
    if (sessionCache.clock && Date.now() - sessionCache.clockAt < CLOCK_TTL_MS) return sessionCache.clock;
    if (sessionCache.clockInflight) return sessionCache.clockInflight;
    sessionCache.clockInflight = (async () => {
        let clock;
        try {
            const cfg = firstKeyedConfig();
            if (!cfg) throw new Error('no broker config');
            const c = await alpacaRequest('GET', `${cfg.base_url}/v2/clock`, cfg.api_key, cfg.api_secret);
            clock = { is_open: c.is_open === true, next_open: c.next_open || null, next_close: c.next_close || null, timestamp: c.timestamp || null, estimated: false };
        } catch (e) {
            clock = estimatedClock();
        }
        sessionCache.clock = clock;
        sessionCache.clockAt = Date.now();
        return clock;
    })().finally(() => { sessionCache.clockInflight = null; });
    return sessionCache.clockInflight;
}

// Weekday-only fallback when the broker calendar is unreachable (holidays are
// not modelled — the result is flagged `estimated`).
function previousWeekday(dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    let dt = new Date(Date.UTC(y, m - 1, d));
    do { dt = new Date(dt.getTime() - 86400000); } while (dt.getUTCDay() === 0 || dt.getUTCDay() === 6);
    return dt.toISOString().slice(0, 10);
}

// Trading-session dates (ET) covering the last ~6 weeks, from the broker calendar.
async function recentSessionDates(todayEt) {
    if (sessionCache.sessions && sessionCache.sessionsKey === todayEt && Date.now() - sessionCache.sessionsAt < CALENDAR_TTL_MS) {
        return sessionCache.sessions;
    }
    if (sessionCache.sessionsInflight) return sessionCache.sessionsInflight;
    sessionCache.sessionsInflight = (async () => {
        let sessions = null;
        try {
            const cfg = firstKeyedConfig();
            if (!cfg) throw new Error('no broker config');
            const [y, m, d] = todayEt.split('-').map(Number);
            const start = new Date(Date.UTC(y, m - 1, d - 45)).toISOString().slice(0, 10);
            const cal = await alpacaRequest('GET', `${cfg.base_url}/v2/calendar?start=${start}&end=${todayEt}`, cfg.api_key, cfg.api_secret);
            if (Array.isArray(cal) && cal.length) sessions = cal.map(c => isoDay(c.date)).filter(Boolean).sort();
        } catch (e) { /* fall back to weekdays */ }
        if (sessions) {
            sessionCache.sessions = sessions;
            sessionCache.sessionsKey = todayEt;
            sessionCache.sessionsAt = Date.now();
        }
        return sessions;
    })().finally(() => { sessionCache.sessionsInflight = null; });
    return sessionCache.sessionsInflight;
}

// The last trading session strictly before `dateStr` (YYYY-MM-DD, ET).
async function sessionBefore(dateStr) {
    const sessions = await recentSessionDates(etDate(Date.now()));
    const prior = (sessions || []).filter(s => s < dateStr);
    if (prior.length) return { date: prior[prior.length - 1], estimated: false };
    return { date: previousWeekday(dateStr), estimated: true };
}

async function sessionContext() {
    const today = etDate(Date.now());
    const [clock, prev] = await Promise.all([marketClockCached(), sessionBefore(today)]);
    return {
        market_open: clock.is_open === true,
        clock_estimated: !!clock.estimated,
        previous_session_date: prev.date,
        calendar_estimated: prev.estimated,
    };
}

// Basis fields for one book. `basisDate` is account.balance_asof for a live read;
// a committed-state fallback has no reliable basis (null → never "today").
function dayPnlBasis(basisDate, ctx) {
    const basis = isoDay(basisDate);
    return {
        day_pnl_basis_date: basis,
        market_open: ctx ? ctx.market_open : null,
        previous_session_date: ctx ? ctx.previous_session_date : null,
        day_pnl_is_today: !!(ctx && basis && ctx.market_open === true && basis === ctx.previous_session_date),
    };
}

// Aggregate basis: a combined day P/L has ONE basis only when every included
// book shares it; otherwise it is reported as mixed (and never as "today").
function aggregateDayPnlBasis(basisDates, ctx) {
    const known = basisDates.filter(Boolean);
    const same = known.length > 0 && known.length === basisDates.length && known.every(b => b === known[0]);
    const out = dayPnlBasis(same ? known[0] : null, ctx);
    out.day_pnl_basis_mixed = known.length > 0 && !same;
    return out;
}

// 2. Fetch live and local status for a portfolio card
app.get('/api/portfolio/all/summary', async (req, res) => {
    loadConfig();
    let totalEquity = 0, totalCash = 0, totalDayPnL = 0, totalPositions = 0;
    const labels = [];
    const missingBooks = [];
    const staleBooks = [];
    const haltedBooks = [];
    const basisDates = [];
    let anyLive = false;
    for (const id of Object.keys(portfoliosConfig)) {
        const d = await fetchPortfolioData(id);
        if (!d) continue;
        labels.push(d.cfg.label);
        if (d.account) {
            basisDates.push(d.account.balance_asof || null);
            totalEquity += parseFloat(d.account.equity);
            totalCash += parseFloat(d.account.cash);
            const dayPnL = parseFloat(d.account.equity) - parseFloat(d.account.last_equity);
            totalDayPnL += dayPnL;
            totalPositions += d.positions.length;
            anyLive = true;
        } else {
            // Live broker unavailable: use the last committed state, never a made-up
            // $100K placeholder. A book with no recorded equity is reported as missing.
            const fb = stateAccountFallback(d.localState);
            if (fb) {
                basisDates.push(null);
                totalEquity += fb.equity;
                totalCash += fb.cash;
                totalDayPnL += fb.day_pnl;
                totalPositions += fb.positions_count;
                staleBooks.push(id);
            } else {
                missingBooks.push(id);
            }
        }
        if (d.localState && d.localState.halted) haltedBooks.push(`${d.cfg.label}: ${d.localState.halt_reason || 'halted'}`);
    }
    // Day-change % divides by PRIOR-DAY equity (equity − today's P&L), not the fixed
    // $300k initial capital — otherwise it disagrees with /all/details and drifts as
    // equity moves away from book value.
    const totalLastEquity = totalEquity - totalDayPnL;
    const totalDayPnlPct = totalLastEquity > 0 ? (totalDayPnL / totalLastEquity) * 100 : 0;
    res.json({
        id: 'all',
        label: 'All Portfolios',
        strategy: `Aggregated: ${labels.join(' · ')}`,
        equity: totalEquity,
        cash: totalCash,
        day_pnl: totalDayPnL,
        day_pnl_pct: totalDayPnlPct,
        ...aggregateDayPnlBasis(basisDates, await sessionContext()),
        positions_count: totalPositions,
        halted: haltedBooks.length > 0,
        halt_reason: haltedBooks.length ? haltedBooks.join(' | ') : null,
        missing_portfolios: missingBooks,
        stale_portfolios: staleBooks,
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
    const missingDetailBooks = [];
    const staleDetailBooks = [];
    const haltedDetailBooks = [];
    const detailBasisDates = [];

    for (const id of Object.keys(portfoliosConfig)) {
        const d = await fetchPortfolioData(id);
        if (!d) continue;
        if (d.account) {
            detailBasisDates.push(d.account.balance_asof || null);
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
            // No live account: fall back to the last committed snapshot (marked stale),
            // never to invented $100K/$200K placeholders and never to $0 (which showed
            // a -100% "loss" for the whole book — after-audit N1).
            const fb = stateAccountFallback(d.localState);
            if (fb) {
                detailBasisDates.push(null);
                totalEquity += fb.equity;
                totalCash += fb.cash;
                totalLastEquity += fb.last_equity;
                totalDayPnL += fb.day_pnl;
                staleDetailBooks.push(id);
            } else {
                missingDetailBooks.push(id);
            }
        }
        if (d.localState && d.localState.halted) haltedDetailBooks.push(`${d.cfg.label}: ${d.localState.halt_reason || 'halted'}`);
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
        halted: haltedDetailBooks.length > 0,
        halt_reason: haltedDetailBooks.length ? haltedDetailBooks.join(' | ') : null,
        missing_portfolios: missingDetailBooks,
        stale_portfolios: staleDetailBooks,
        ...aggregateDayPnlBasis(detailBasisDates, await sessionContext()),
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
                        const dateObj = (timeframe === '1D' || timeframe === '1Day')
                            ? etDate(ts * 1000)
                            : new Date(ts * 1000).toISOString();
                        if (!combinedHistory[dateObj]) { combinedHistory[dateObj] = 0; dateContributors[dateObj] = 0; }
                        combinedHistory[dateObj] += eq;
                        dateContributors[dateObj] += 1;
                    }
                }
            }
        } catch (e) {}
    }

    // A combined point is only real when EVERY book reported that date. Partial
    // dates are dropped — never padded with a $100K placeholder, and an empty
    // result is reported as unavailable, never seeded (after-audit N2).
    for (const d of Object.keys(combinedHistory)) {
        if ((dateContributors[d] || 0) < portfolioCount) delete combinedHistory[d];
    }
    if (Object.keys(combinedHistory).length === 0) {
        return res.json({ source: 'unavailable', unavailable: true, base_value: baseCapital, history: [] });
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

    let liveEquity = null;
    let liveCash = null;
    let isStale = false;
    let liveDayPnL = 0;
    let liveDayPnLPct = 0;
    let livePositionsCount = 0;
    let isHalted = localState.halted || false;
    let haltReason = localState.halt_reason || null;
    let isLiveConnected = false;
    let basisDate = null;

    // Attempt to query live Alpaca Account info
    try {
        const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
        basisDate = account.balance_asof || null;
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
        // Last committed snapshot (marked stale); null when none — never a $100K placeholder.
        const fb = stateAccountFallback(localState);
        if (fb) {
            liveEquity = fb.equity;
            liveCash = fb.cash;
            liveDayPnL = fb.day_pnl;
            liveDayPnLPct = fb.last_equity > 0 ? (fb.day_pnl / fb.last_equity) * 100 : 0;
            livePositionsCount = fb.positions_count;
            isStale = true;
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
        ...dayPnlBasis(isLiveConnected ? basisDate : null, await sessionContext()),
        positions_count: livePositionsCount,
        halted: isHalted,
        halt_reason: haltReason,
        ...haltAssessment(localState, liveEquity, cfg.initial_capital),
        live_connected: isLiveConnected,
        stale: isStale
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
                sector: sectorFor(p.symbol, p.asset_class)
            };
        });
    } else {
        // Fallback mapping of positions from local json
        if (id === 'portfolio_1' && localState.positions) {
            const totalEq = parseFloat(localState.equity) || 0;
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
                    sector: sectorFor(sym),
                    isStale: true
                };
            });
        } else if (id === 'portfolio_2' && localState.positions) {
            const totalEq = parseFloat(localState.account?.portfolio_value) || 0;
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
                    sector: sectorFor(p.symbol)
                };
            });
        } else if (id === 'portfolio_3') {
            // Read from latest journal for details if bot_state doesn't list full pos
            let journals = [];
            try {
                const files = await listJournalFiles(paths.journalDir);
                if (files.length > 0) {
                    journals = readJsonFile(path.join(paths.journalDir, files[files.length - 1]), []);
                }
            } catch (e) {
                console.error("Error reading portfolio_3 journal files:", e);
            }
            const lastJournal = journals[journals.length - 1] || {};
            const totalEq = parseFloat(localState.equity) || 0;
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
                    sector: sectorFor(p.symbol)
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
        ...haltAssessment(localState, isLiveConnected ? parseFloat(liveAccount.equity) : (stateAccountFallback(localState) || {}).equity, cfg.initial_capital),
        ...dayPnlBasis(isLiveConnected ? liveAccount.balance_asof : null, await sessionContext()),
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
            // Offline: last committed snapshot, flagged stale; null when the state has
            // no equity — never $100K/$200K placeholders (after-audit N1/N7).
            const fb = stateAccountFallback(localState);
            return fb ? {
                equity: fb.equity,
                cash: fb.cash,
                buying_power: null,
                day_pnl: fb.day_pnl,
                day_pnl_pct: fb.last_equity > 0 ? (fb.day_pnl / fb.last_equity) * 100 : 0,
                last_equity: fb.last_equity,
                stale: true
            } : null;
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
                supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_1', date: `gte.${START}`, select: 'date,equity,cash', order: 'date.asc', limit: 2000 }),
                supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_2', date: `gte.${START}`, select: 'date,equity,cash', order: 'date.asc', limit: 2000 }),
                supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_3', date: `gte.${START}`, select: 'date,equity,cash', order: 'date.asc', limit: 2000 }),
            ]);
            rows = combineEquitySeries([p1, p2, p3].map(r => dropEquityAnchors(r)));
        } else {
            rows = dropEquityAnchors(await supabaseGet('portfolio_equity_history', {
                portfolio_id: `eq.${id}`, date: `gte.${START}`,
                select: 'date,equity,cash', order: 'date.asc', limit: 2000,
            }));
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
                            date: (timeframe === '1D' || timeframe === '1Day') ? etDate(ts * 1000) : dateObj.toISOString(),
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
                    const todayStr = etDate(Date.now());
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
                    // 1D: base_value is the close of the session BEFORE the first
                    // intraday bar's session — state that date so the benchmark can
                    // baseline SPY on the very same close (post-deploy audit D1).
                    let baseDate = null, baseDateEstimated = null;
                    if (period === '1D' && !isDaily && alpacaHistory.timestamp.length) {
                        const b = await sessionBefore(etDate(alpacaHistory.timestamp[0] * 1000));
                        baseDate = b.date;
                        baseDateEstimated = b.estimated;
                    }
                    return res.json({
                        source: 'alpaca_live',
                        base_value: parseFloat(alpacaHistory.base_value || 100000),
                        ...(baseDate ? { base_date: baseDate, base_date_estimated: baseDateEstimated } : {}),
                        history: finalHistory
                    });
                }
            }
        } catch (e) {
            console.warn(`[Equity History] Alpaca portfolio history failed for ${id}:`, e.message);
        }
    }

    // Fallback: parse journal files. Journals hold ONE end-of-day equity per
    // session, so they can never answer an intraday request (a 1D chart built from
    // months of daily points was captioned "Today vs previous close" — N3).
    const isIntraday = period === '1D' || !/^1D(ay)?$/.test(timeframe);
    if (isIntraday) {
        return res.json({ source: 'unavailable', unavailable: true, reason: 'intraday history unavailable', base_value: 100000, history: [] });
    }
    const history = [];
    try {
        {
            const files = await listJournalFiles(paths.journalDir);

            for (const file of files) {
                const filePath = path.join(paths.journalDir, file);
                const dayEntries = readJsonFile(filePath, []);
                const dateStr = file.replace('.json', '');

                if (Array.isArray(dayEntries) && dayEntries.length > 0) {
                    // Only a recorded equity becomes a point — a journal day without
                    // one is skipped, never defaulted to $100K (honesty rule).
                    let equityVal = null;
                    if (id === 'portfolio_1') {
                        const eod = dayEntries.find(e => e.mode === 'end-of-day') || dayEntries[dayEntries.length - 1];
                        equityVal = eod.account?.equity ?? eod.account?.ending_equity;
                    } else if (id === 'portfolio_2') {
                        const entry = dayEntries[dayEntries.length - 1] || {};
                        equityVal = entry.account_snapshot?.equity;
                    } else if (id === 'portfolio_3') {
                        const entry = dayEntries[dayEntries.length - 1] || {};
                        equityVal = entry.audit?.equity;
                    }
                    const eqNum = parseFloat(equityVal);
                    if (Number.isFinite(eqNum) && eqNum > 0) {
                        history.push({ date: dateStr, equity: eqNum, profit_loss: eqNum - 100000, profit_loss_pct: (eqNum - 100000) / 1000 });
                    }
                }
            }
        }
    } catch (e) {
        console.error(`Error compiling equity history for ${id}:`, e.message);
    }

    if (history.length === 0) {
        return res.json({ source: 'unavailable', unavailable: true, base_value: 100000, history: [] });
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
// Broker clock unavailable: estimate from New York wall time (Vercel runs in
// UTC, so local getHours() was wrong by 4-5h). Holidays are not modelled,
// hence `estimated: true` — consumers must not treat it as authoritative.
function estimatedClock() {
    const now = new Date();
    const ny = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hourCycle: 'h23',
    }).formatToParts(now).map(p => [p.type, p.value]));
    const mins = Number(ny.hour) * 60 + Number(ny.minute);
    const isWeekday = !['Sat', 'Sun'].includes(ny.weekday);
    return {
        timestamp: now.toISOString(),
        is_open: isWeekday && mins >= 570 && mins < 960,
        next_open: null,
        next_close: null,
        estimated: true,
    };
}

app.get('/api/market/clock', async (req, res) => {
    loadConfig();
    // Shares the per-instance ≤60 s clock cache used for the day-P/L basis.
    const clock = await marketClockCached();
    if (clock.estimated) return res.json(clock);
    res.json({ is_open: clock.is_open, next_open: clock.next_open, next_close: clock.next_close, timestamp: clock.timestamp });
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
    res.json(estimatedClock());
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
                    prevClose,
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

const BAR_TIMEFRAMES = /^([1-9]|[1-5][0-9])(Min|Hour)$|^1(Day|Week|Month)$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

app.get('/api/market/bars/:symbol', async (req, res) => {
    const symbol = req.params.symbol.toUpperCase();
    const limit = Math.min(1000, Math.max(1, parseInt(req.query.limit || '30', 10) || 30));
    const timeframe = req.query.timeframe || '1Day';
    if (!BAR_TIMEFRAMES.test(timeframe)) return res.status(400).json({ error: 'Invalid timeframe.' });
    for (const k of ['start', 'end']) {
        if (req.query[k] && (!ISO_DATE.test(req.query[k]) || isNaN(Date.parse(req.query[k])))) {
            return res.status(400).json({ error: `Invalid ${k} date.` });
        }
    }
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

// 11a. Multi-symbol bars in ONE request (market-pulse sparklines fired ~29
// single-symbol calls on a cold load). Same validation as the single-symbol
// route; `limit` is PER SYMBOL. Alpaca's multi-symbol endpoint applies `limit`
// to the whole page, so pages are walked (sort=desc => newest first within each
// symbol) until every symbol has `limit` bars or the data runs out, then each
// series is returned chronologically. Offline/upstream failure => {} (never
// fabricated bars).
const BATCH_SYMBOL = /^[A-Z][A-Z0-9.\-]{0,9}$/;
const BARS_BATCH_MAX_SYMBOLS = 50;
const BARS_BATCH_PAGE_LIMIT = 10000;
const BARS_BATCH_MAX_PAGES = 10;

app.get('/api/market/bars-batch', async (req, res) => {
    const symbols = [...new Set(String(req.query.symbols || '').split(',')
        .map(s => s.trim().toUpperCase()).filter(Boolean))];
    if (!symbols.length) return res.status(400).json({ error: 'symbols is required.' });
    if (symbols.length > BARS_BATCH_MAX_SYMBOLS) {
        return res.status(400).json({ error: `At most ${BARS_BATCH_MAX_SYMBOLS} symbols per request.` });
    }
    const bad = symbols.find(s => !BATCH_SYMBOL.test(s));
    if (bad) return res.status(400).json({ error: `Invalid symbol: ${bad}` });
    const limit = Math.min(1000, Math.max(1, parseInt(req.query.limit || '30', 10) || 30));
    const timeframe = req.query.timeframe || '1Day';
    if (!BAR_TIMEFRAMES.test(timeframe)) return res.status(400).json({ error: 'Invalid timeframe.' });
    for (const k of ['start', 'end']) {
        if (req.query[k] && (!ISO_DATE.test(req.query[k]) || isNaN(Date.parse(req.query[k])))) {
            return res.status(400).json({ error: `Invalid ${k} date.` });
        }
    }
    const start = req.query.start || defaultBarsStart(timeframe, limit);
    const end = req.query.end || '';
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    const out = {};
    if (!(cfg && cfg.api_key && !cfg.api_key.includes('REDACTED') && cfg.api_key !== 'MOCK_KEY_ID_REDACTED')) {
        return res.json(out);
    }
    const want = new Set(symbols);
    const collected = Object.fromEntries(symbols.map(s => [s, []]));
    const full = () => symbols.every(s => collected[s].length >= limit);
    let pageToken = '';
    try {
        for (let page = 0; page < BARS_BATCH_MAX_PAGES; page++) {
            let url = `${cfg.data_url}/v2/stocks/bars?symbols=${symbols.map(encodeURIComponent).join(',')}`
                + `&timeframe=${timeframe}&limit=${BARS_BATCH_PAGE_LIMIT}&feed=iex&sort=desc`
                + `&start=${encodeURIComponent(start)}`;
            if (end) url += `&end=${encodeURIComponent(end)}`;
            if (pageToken) url += `&page_token=${encodeURIComponent(pageToken)}`;
            const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
            for (const [sym, bars] of Object.entries((data && data.bars) || {})) {
                if (!want.has(sym) || !Array.isArray(bars)) continue;
                const room = limit - collected[sym].length;
                if (room > 0) collected[sym].push(...bars.slice(0, room));
            }
            pageToken = data && data.next_page_token;
            if (!pageToken || full()) break;
        }
    } catch (e) {
        console.warn('[bars-batch] upstream error:', e.message);
    }
    for (const sym of symbols) {
        if (collected[sym].length) out[sym] = collected[sym].slice().reverse();
    }
    res.json(out);
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

// Seed rows (post-deploy audit D10): the equity writer recorded the starting
// capital (cash NULL) for dates before the account's first real broker snapshot.
// They are anchors, not performance: flagged `anchor: true` here, and dropped
// wherever rows are combined or plotted server-side. A row is an anchor only while
// no real (cash-bearing) point has been seen yet AND its equity equals the
// starting capital.
function markEquityAnchors(rows, initialCapital = 100000) {
    if (!Array.isArray(rows)) return [];
    let seenReal = false;
    return rows.slice().sort((a, b) => String(a.date).localeCompare(String(b.date))).map(r => {
        if (!r || typeof r !== 'object') return r;
        const hasCash = r.cash !== null && r.cash !== undefined;
        if (hasCash) seenReal = true;
        const eq = parseFloat(r.equity);
        if (!seenReal && !hasCash && Number.isFinite(eq) && Math.abs(eq - initialCapital) < 0.005) {
            return { ...r, anchor: true };
        }
        return r;
    });
}
const dropEquityAnchors = (rows, initialCapital) => markEquityAnchors(rows, initialCapital).filter(r => !(r && r.anchor));

// 11b. Supabase equity history — /api/supabase/equity?portfolio_id=portfolio_1&start=2025-06-01
app.get('/api/supabase/equity', async (req, res) => {
    const portfolioId = req.query.portfolio_id || 'portfolio_1';
    const start = req.query.start || '2025-01-01';

    if (portfolioId === 'all') {
        // Aggregate all 3 portfolios by date
        const [p1, p2, p3] = await Promise.all([
            supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_1', date: `gte.${start}`, select: 'date,equity,cash', order: 'date.asc', limit: 1000 }),
            supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_2', date: `gte.${start}`, select: 'date,equity,cash', order: 'date.asc', limit: 1000 }),
            supabaseGet('portfolio_equity_history', { portfolio_id: 'eq.portfolio_3', date: `gte.${start}`, select: 'date,equity,cash', order: 'date.asc', limit: 1000 }),
        ]);
        // Forward-fill each portfolio before summing (see combineEquitySeries):
        // a naive per-date sum collapses on partial dates → false -66% curve.
        return res.json(combineEquitySeries([p1, p2, p3].map(r => dropEquityAnchors(r))));
    }

    const rows = await supabaseGet('portfolio_equity_history', {
        portfolio_id: `eq.${portfolioId}`,
        date:         `gte.${start}`,
        select:       'date,equity,cash,pnl,pnl_pct,positions_count',
        order:        'date.asc',
        limit:        1000,
    });
    const cfg = portfoliosConfig[portfolioId];
    res.json(markEquityAnchors(rows || [], (cfg && cfg.initial_capital) || 100000));
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
            pid => supabaseGet('portfolio_equity_history', { portfolio_id: `eq.${pid}`, date: `gte.${start}`, select: 'date,equity,cash', order: 'date.asc', limit: 1000 })));
        rows = combineEquitySeries([p1, p2, p3].map(r => dropEquityAnchors(r)));
    } else {
        // Seed anchors are flat starting-capital rows: zero "returns" that would dilute VaR.
        rows = dropEquityAnchors(await supabaseGet('portfolio_equity_history', { portfolio_id: `eq.${id}`, date: `gte.${start}`, select: 'date,equity,cash', order: 'date.asc', limit: 1000 }));
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
        return sendUpstreamError(res, e);
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
        return sendUpstreamError(res, e);
    }
});

// 14. Portfolio summary overview (3 portfolio cards)
app.get('/api/portfolios/overview', async (req, res) => {
    loadConfig();
    const summaries = [];
    const ctx = await sessionContext();

    for (const [id, cfg] of Object.entries(portfoliosConfig)) {
        const paths = getPortfolioPaths(id);
        const localState = paths ? readJsonFile(paths.state, {}) : {};
        const initialCapital = cfg.initial_capital || 100000;
        // Honest data: no $100K placeholders. An offline book carries its last
        // committed snapshot (`stale: true`) or nulls when none exists.
        let equity = null, cash = null, dayPnl = null, dayPnlPct = null, positions = null;
        let liveConnected = false, stale = false, basisDate = null;

        try {
            const account = await alpacaRequest('GET', `${cfg.base_url}/v2/account`, cfg.api_key, cfg.api_secret);
            equity = parseFloat(account.equity);
            cash = parseFloat(account.cash);
            dayPnl = parseFloat(account.equity) - parseFloat(account.last_equity);
            dayPnlPct = parseFloat(account.last_equity) > 0 ? (dayPnl / parseFloat(account.last_equity)) * 100 : 0;
            basisDate = account.balance_asof || null;
            const pos = await alpacaRequest('GET', `${cfg.base_url}/v2/positions`, cfg.api_key, cfg.api_secret);
            positions = pos.length;
            liveConnected = true;
        } catch (e) {
            const fb = stateAccountFallback(localState);
            if (fb) {
                equity = fb.equity;
                cash = fb.cash;
                dayPnl = fb.day_pnl;
                dayPnlPct = fb.last_equity > 0 ? (fb.day_pnl / fb.last_equity) * 100 : 0;
                positions = fb.positions_count;
                stale = true;
            }
        }

        const totalReturn = equity === null ? null : ((equity - initialCapital) / initialCapital) * 100;
        const halt = haltAssessment(localState, equity, initialCapital);
        summaries.push({
            id, label: cfg.label, equity, cash, dayPnl, dayPnlPct, positions, totalReturn, initialCapital,
            liveConnected, stale, strategy: cfg.strategy,
            halted: !!localState.halted, halt_reason: localState.halt_reason || null, ...halt,
            ...dayPnlBasis(liveConnected ? basisDate : null, ctx),
        });
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
    }
});

// ──────────────────────────────────────────────────────────────────────────
// GROUP D: Assets
// ──────────────────────────────────────────────────────────────────────────

// D1. List/search all assets — paginated (post-deploy audit D9). The full Alpaca
// asset master is ~15 MB, so it is fetched once per filter combination per
// instance (1 h), searched server-side (`q`: symbol or name) and returned one page
// at a time. The body stays a plain array; paging metadata is in headers:
// X-Total-Count (matches after `q`), X-Page, X-Page-Limit.
const ASSETS_DEFAULT_LIMIT = 500;
const ASSETS_MAX_LIMIT = 2000;
const ASSETS_CACHE_TTL_MS = 3600000;
const assetListCache = new Map();   // "status|class|exchange" -> { at, list }

function pageAssets(list, { q, page, limit }) {
    let rows = list;
    if (q) {
        const Q = q.toUpperCase();
        const rank = (a) => {
            const sym = String(a.symbol || '').toUpperCase();
            if (sym === Q) return 0;
            if (sym.startsWith(Q)) return 1;
            if (sym.includes(Q)) return 2;
            return String(a.name || '').toUpperCase().includes(Q) ? 3 : -1;
        };
        rows = list.map(a => [rank(a), a]).filter(([r]) => r >= 0)
            .sort((x, y) => x[0] - y[0]).map(([, a]) => a);
    }
    const start = (page - 1) * limit;
    return { total: rows.length, items: rows.slice(start, start + limit) };
}

app.get('/api/assets', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { status, asset_class, exchange } = req.query;
    const page = Math.max(1, parseInt(req.query.page, 10) || 1);
    const limit = Math.min(ASSETS_MAX_LIMIT, Math.max(1, parseInt(req.query.limit, 10) || ASSETS_DEFAULT_LIMIT));
    const q = String(req.query.q || '').trim();
    const key = `${status || ''}|${asset_class || ''}|${exchange || ''}`;
    let entry = assetListCache.get(key);
    if (!entry || Date.now() - entry.at > ASSETS_CACHE_TTL_MS) {
        let url = `${cfg.base_url}/v2/assets?`;
        if (status) url += `status=${status}&`;
        if (asset_class) url += `asset_class=${asset_class}&`;
        if (exchange) url += `exchange=${exchange}&`;
        try {
            const assets = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
            entry = { at: Date.now(), list: Array.isArray(assets) ? assets : [] };
            assetListCache.set(key, entry);
        } catch (e) {
            return sendUpstreamError(res, e);
        }
    }
    const { total, items } = pageAssets(entry.list, { q, page, limit });
    res.set({ 'X-Total-Count': String(total), 'X-Page': String(page), 'X-Page-Limit': String(limit) });
    res.json(items);
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

// Crypto pairs must be BASE/QUOTE (Alpaca's v1beta3 form). "BTCUSD" — the form
// Alpaca uses for crypto POSITIONS — is normalised to "BTC/USD"; anything else is
// a 400, never a silent 200 with an empty body (post-deploy audit D9).
function normalizeCryptoPair(raw) {
    const s = String(raw || '').trim().toUpperCase();
    let m = /^([A-Z0-9]{2,10})\/(USD|USDT|USDC|BTC)$/.exec(s);
    if (m) return `${m[1]}/${m[2]}`;
    m = /^([A-Z0-9]{2,10}?)(USDT|USDC|USD)$/.exec(s);
    return m ? `${m[1]}/${m[2]}` : null;
}
function cryptoSymbolParam(req, res) {
    const pair = normalizeCryptoPair(req.params.symbol);
    if (!pair) { res.status(400).json({ error: 'Unknown crypto pair. Use BASE/QUOTE, e.g. BTC/USD.' }); return null; }
    return encodeURIComponent(pair);
}

// E1. Crypto historical bars
app.get('/api/crypto/bars/:symbol', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const sym = cryptoSymbolParam(req, res);
    if (!sym) return;
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
    // sort=desc + limit => the most RECENT `lim` bars (ascending from a 1.5x
    // lookback returned the OLDEST bars, leaving the chart ~0.5x`lim` bars stale);
    // reverse each series back to chronological for the chart.
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/bars?symbols=${sym}&timeframe=${encodeURIComponent(tf)}&start=${encodeURIComponent(startParam)}&limit=${lim}&sort=desc`;
    if (end) url += `&end=${encodeURIComponent(end)}`;
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        if (data && data.bars) for (const k of Object.keys(data.bars)) data.bars[k] = (data.bars[k] || []).slice().reverse();
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
    const sym = cryptoSymbolParam(req, res);
    if (!sym) return;
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
    const sym = cryptoSymbolParam(req, res);
    if (!sym) return;
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
    const sym = cryptoSymbolParam(req, res);
    if (!sym) return;
    const { start, end, limit } = req.query;
    // Newest first: without sort=desc Alpaca returns the first trades of the UTC
    // day, so the "Recent Trades" tape showed hours-old prints (audit D4).
    const lim = Math.min(1000, Math.max(1, parseInt(limit, 10) || 100));
    let url = `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta3/crypto/us/trades?symbols=${sym}&limit=${lim}&sort=desc`;
    if (start) url += `&start=${encodeURIComponent(start)}`;
    if (end) url += `&end=${encodeURIComponent(end)}`;
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
    const sym = cryptoSymbolParam(req, res);
    if (!sym) return;
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
    const top = Math.min(50, Math.max(1, parseInt(req.query.top, 10) || 10));
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/screener/stocks/movers?top=${top}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        // Honesty rule: never fabricate prices. Signal unavailability instead.
        console.warn('[movers] unavailable:', e.message);
        res.status(503).json({ unavailable: true, gainers: [], losers: [] });
    }
});

// G4. Most active stocks
app.get('/api/market/most-active', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const top = Math.min(50, Math.max(1, parseInt(req.query.top, 10) || 10));
    try {
        const data = await alpacaRequest('GET', `${cfg.data_url || 'https://data.alpaca.markets'}/v1beta1/screener/stocks/most-actives?top=${top}`, cfg.api_key, cfg.api_secret);
        res.json(data);
    } catch (e) {
        console.warn('[most-active] unavailable:', e.message);
        res.status(503).json({ unavailable: true, most_actives: [] });
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
const CORP_ACTIONS_DEFAULT_LIMIT = 100;
const CORP_ACTIONS_MAX_LIMIT = 500;
const encodeCorpActionsToken = (offset) => Buffer.from(`o:${offset}`).toString('base64url');
function decodeCorpActionsToken(token) {
    const m = /^o:(\d{1,7})$/.exec(Buffer.from(String(token), 'base64url').toString('utf8'));
    return m ? Number(m[1]) : null;
}
app.get('/api/corporate-actions', async (req, res) => {
    loadConfig();
    const cfg = Object.values(portfoliosConfig)[0];
    if (!cfg) return res.status(500).json({ error: 'No portfolio configured' });
    const { ca_types, since, until: untilDate, symbol, cusip, date_type } = req.query;
    // The unfiltered announcement list was ~1.0 MB. Alpaca's announcements
    // endpoint has no server-side paging, so pages are cut here: `limit`
    // (default 100, max 500) and an opaque `page_token` (returned in the
    // X-Next-Page-Token header) select a window; the body stays a plain array.
    const limit = Math.min(CORP_ACTIONS_MAX_LIMIT,
        Math.max(1, parseInt(req.query.limit || String(CORP_ACTIONS_DEFAULT_LIMIT), 10) || CORP_ACTIONS_DEFAULT_LIMIT));
    let offset = 0;
    if (req.query.page_token) {
        offset = decodeCorpActionsToken(req.query.page_token);
        if (offset === null) return res.status(400).json({ error: 'Invalid page_token.' });
    }
    let url = `${cfg.base_url}/v2/corporate_actions/announcements?`;
    if (ca_types) url += `ca_types=${encodeURIComponent(ca_types)}&`;
    if (since) url += `since=${encodeURIComponent(since)}&`;
    if (untilDate) url += `until=${encodeURIComponent(untilDate)}&`;
    if (symbol) url += `symbol=${encodeURIComponent(symbol)}&`;
    if (cusip) url += `cusip=${encodeURIComponent(cusip)}&`;
    if (date_type) url += `date_type=${encodeURIComponent(date_type)}&`;
    let all = [];
    try {
        const data = await alpacaRequest('GET', url, cfg.api_key, cfg.api_secret);
        all = Array.isArray(data) ? data : [];
    } catch (e) {
        console.warn('[corporate-actions]', e.message);
    }
    const page = all.slice(offset, offset + limit);
    res.setHeader('X-Total-Count', String(all.length));
    if (offset + limit < all.length) res.setHeader('X-Next-Page-Token', encodeCorpActionsToken(offset + limit));
    res.json(page);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
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
        sendUpstreamError(res, e);
    }
});

// ─── Guardian External Trigger — Vercel Cron L2 Scheduler ──────────────────
// Vercel fires this endpoint on weekdays via vercel.json "crons" schedule.
// It dispatches a GitHub repository_dispatch (event_type: trading-catchup)
// which starts the Guardian workflow within seconds — NOT subject to the
// GitHub Actions cron throttle that caused today's missed session.
//
// Required Vercel env vars:
//   CRON_SECRET         — random secret; Vercel sends it as Authorization: Bearer
//   GITHUB_DISPATCH_PAT — fine-grained GitHub PAT with repo "actions:write" scope
//
// If either var is unset the endpoint returns 503 (fail-closed — no silent no-ops).
app.get('/api/guardian-trigger', async (req, res) => {
    const CRON_SECRET = process.env.CRON_SECRET || '';
    const GITHUB_DISPATCH_PAT = process.env.GITHUB_DISPATCH_PAT || '';

    if (!CRON_SECRET || !GITHUB_DISPATCH_PAT) {
        console.error('[guardian-trigger] CRON_SECRET or GITHUB_DISPATCH_PAT not set — trigger disabled.');
        return res.status(503).json({
            ok: false,
            error: 'Guardian trigger not configured. Set CRON_SECRET and GITHUB_DISPATCH_PAT in Vercel env vars.',
        });
    }

    // Vercel cron requests carry Authorization: Bearer ${CRON_SECRET}. Compared in
    // constant time over fixed-length digests, so neither content nor length leaks.
    const authHeader = String(req.headers['authorization'] || '');
    if (!secretMatches(authHeader, `Bearer ${CRON_SECRET}`)) {
        return res.status(401).json({ ok: false, error: 'Unauthorized.' });
    }

    const payload = JSON.stringify({
        event_type: 'trading-catchup',
        client_payload: { source: 'vercel-cron', fired_at: new Date().toISOString() },
    });

    try {
        const result = await new Promise((resolve, reject) => {
            const options = {
                hostname: 'api.github.com',
                path: '/repos/Bhidy/auto-trading/dispatches',
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${GITHUB_DISPATCH_PAT}`,
                    'Accept': 'application/vnd.github+json',
                    'X-GitHub-Api-Version': '2022-11-28',
                    'User-Agent': 'auto-trading-vercel-cron/1.0',
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(payload),
                },
            };
            const r2 = https.request(options, (r) => {
                let body = '';
                r.on('data', d => body += d);
                r.on('end', () => resolve({ status: r.statusCode, body }));
            });
            r2.setTimeout(10000, () => r2.destroy(new Error('timeout')));
            r2.on('error', reject);
            r2.write(payload);
            r2.end();
        });

        if (result.status === 204) {
            console.log(`[guardian-trigger] repository_dispatch OK at ${new Date().toISOString()}`);
            return res.json({ ok: true, dispatched: true, at: new Date().toISOString() });
        }
        // GitHub's error body (token scopes, repo internals) stays in server logs.
        console.error(`[guardian-trigger] GitHub returned ${result.status}: ${String(result.body).slice(0, 500)}`);
        return res.status(502).json({ ok: false, error: 'Dispatch failed.' });
    } catch (e) {
        console.error(`[guardian-trigger] dispatch error: ${e.message}`);
        return res.status(502).json({ ok: false, error: 'Dispatch failed.' });
    }
});

// Unknown API routes -> JSON 404; any unhandled error -> JSON 500 (never a hang,
// never a stack trace or internal path in the body).
app.use('/api', (req, res) => res.status(404).json({ error: 'Not found.' }));
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
    console.error('[unhandled]', req.method, req.originalUrl, err && err.stack || err);
    if (res.headersSent) return;
    const code = Number(err && (err.statusCode || err.status)) || 500;
    res.status(code >= 400 && code < 500 ? code : 500)
        .json({ error: code >= 400 && code < 500 ? 'Bad request.' : 'Internal error.' });
});

if (require.main === module) {
    app.listen(PORT, () => {
        console.log(`=======================================================`);
        console.log(`  Auto Trading Portfolios Dashboard Server started!   `);
        console.log(`  Access dashboard at: http://localhost:${PORT}        `);
        console.log(`=======================================================`);
    });
}

// Pure helpers exposed for unit tests only.
app._internals = {
    journalDatesToCover, planOverlayUpdate, dayPnlBasis, aggregateDayPnlBasis, sectorFor,
    normalizeCryptoPair, pageAssets, markEquityAnchors, previousWeekday, haltAssessment,
};
module.exports = app;
