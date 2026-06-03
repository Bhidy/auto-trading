/* System Intelligence dashboard — renders the hardening engine's data files.
 * Brand-compliant (warm palette, DM Serif numbers, mono labels). Read-only. */
(function () {
  'use strict';

  let currentPf = 'all';
  let timer = null;

  const $ = (id) => document.getElementById(id);
  const fmtMoney = (v) => {
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    const sign = n < 0 ? '-' : '';
    return sign + '$' + Math.abs(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
  };
  const fmtNum = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(d);
  const pct = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(d) + '%';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const getLogoHtml = (sym, size = 16) => {
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
  };

  function setPill(el, kind, text) {
    el.className = 'pill ' + (kind === 'ok' ? 'pill-ok' : kind === 'warn' ? 'pill-warn' : 'pill-muted');
    el.textContent = text;
  }

  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(url + ' -> ' + r.status);
    return r.json();
  }

  // ---- Cross-portfolio concentration ----
  function renderConcentration(d) {
    const status = $('concStatus');
    if (!d || d.total_equity === undefined) {
      $('concBody').innerHTML = '<div class="empty-note">No cross-portfolio data available.</div>';
      setPill(status, 'muted', 'n/a');
      return;
    }
    setPill(status, d.ok ? 'ok' : 'warn', d.ok ? 'within caps' : 'breach');
    const topSyms = (d.by_symbol || []).slice(0, 6);
    const topSecs = (d.by_sector || []).slice(0, 5);

    const symBars = topSyms.map(s => {
      const w = Math.min(100, (s.pct_of_total / d.single_name_cap_pct) * 100);
      return `<div class="bar-row">
        <div class="bar-head" style="display:flex; align-items:center; gap:0.45rem;">
          <span style="display:inline-flex; align-items:center; flex:1;">
            ${getLogoHtml(s.symbol, 16)}
            <strong style="margin-inline-start:0.35rem">${esc(s.symbol)}</strong>
            <span class="mono" style="margin-inline-start:.4rem">${s.books.length} book${s.books.length > 1 ? 's' : ''}</span>
          </span>
          <span class="mono">${pct(s.pct_of_total)}</span></div>
        <div class="bar-track"><div class="bar-fill ${s.breach ? 'breach' : ''}" style="width:${w}%"></div></div></div>`;
    }).join('') || '<div class="empty-note">No positions held.</div>';

    const secBars = topSecs.map(s => {
      const w = Math.min(100, (s.pct_of_total / d.sector_cap_pct) * 100);
      return `<div class="bar-row">
        <div class="bar-head"><span>${esc(s.sector)}</span><span class="mono">${pct(s.pct_of_total)}</span></div>
        <div class="bar-track"><div class="bar-fill ${s.breach ? 'breach' : ''}" style="width:${w}%"></div></div></div>`;
    }).join('') || '<div class="empty-note">—</div>';

    // Null-safe: never dereference .length on a missing array. The endpoint always
    // returns these, but a partial/200 error body must degrade to 0, not throw and
    // blank the whole concentration panel.
    const breachCount = (d.single_name_breaches || []).length + (d.sector_breaches || []).length;

    $('concBody').innerHTML = `
      <div class="metric-row" style="margin-bottom:1.25rem">
        <div class="metric"><div class="label">Total Equity</div><div class="value">${fmtMoney(d.total_equity)}</div></div>
        <div class="metric"><div class="label">Single-name cap</div><div class="value">${fmtNum(d.single_name_cap_pct, 0)}<span class="unit">%</span></div></div>
        <div class="metric"><div class="label">Sector cap</div><div class="value">${fmtNum(d.sector_cap_pct, 0)}<span class="unit">%</span></div></div>
        <div class="metric"><div class="label">Breaches</div><div class="value ${breachCount ? 'neg' : 'pos'}">${breachCount}</div></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem">
        <div><div class="card-sub" style="margin-bottom:.75rem">By name (vs ${fmtNum(d.single_name_cap_pct, 0)}% cap)</div>${symBars}</div>
        <div><div class="card-sub" style="margin-bottom:.75rem">By sector (vs ${fmtNum(d.sector_cap_pct, 0)}% cap)</div>${secBars}</div>
      </div>`;
  }

  // ---- Validation / overfitting ----
  function renderValidation(v) {
    const status = $('valStatus');
    if (!v) { $('valBody').innerHTML = '<div class="empty-note">—</div>'; return; }
    if (!v.self_learning) {
      setPill(status, 'muted', 'static');
      $('valBody').innerHTML = `<div class="empty-note">This book has no self-learning loop; its
        walk-forward number is a robustness check, not a tuning gate.</div>`;
      return;
    }
    const has = v.candidate_oos_sharpe !== null && v.candidate_oos_sharpe !== undefined;
    setPill(status, has ? 'ok' : 'muted', has ? 'gated' : 'no change yet');
    if (!has) {
      $('valBody').innerHTML = `<div class="empty-note">No parameter change proposed yet. When the
        nightly loop proposes one, its OOS Sharpe, PBO, Deflated Sharpe and challenger result
        appear here before it can reach production.</div>`;
      return;
    }
    const pboKind = v.pbo === null ? '' : (v.pbo < 0.5 ? 'pos' : 'neg');
    const dsrKind = v.deflated_sharpe === null ? '' : (v.deflated_sharpe >= 0.5 ? 'pos' : 'neg');
    const reasons = (v.screen_reasons || []).map(r => `<span class="reason-chip">${esc(r)}</span>`).join('');
    $('valBody').innerHTML = `
      <div class="metric" style="margin-bottom:1rem">
        <div class="label">OOS Sharpe — candidate vs current</div>
        <div class="gauge"><span class="big" style="color:var(--ink)">${fmtNum(v.candidate_oos_sharpe)}</span>
          <span class="mono" style="color:var(--muted)">vs ${fmtNum(v.current_oos_sharpe)}</span></div>
      </div>
      <div class="metric-row">
        <div class="metric"><div class="label">PBO</div><div class="value ${pboKind}">${v.pbo === null ? '—' : fmtNum(v.pbo)}</div></div>
        <div class="metric"><div class="label">Deflated Sharpe</div><div class="value ${dsrKind}">${v.deflated_sharpe === null ? '—' : fmtNum(v.deflated_sharpe)}</div></div>
        <div class="metric"><div class="label">Challenger</div><div class="value">${fmtNum(v.challenger_sharpe)}</div></div>
      </div>
      <div style="margin-top:.75rem"><span class="pill ${v.beats_challenger ? 'pill-ok' : 'pill-warn'}">
        ${v.beats_challenger === null ? 'n/a' : v.beats_challenger ? 'beats benchmark' : 'below benchmark'}</span>
        <span class="mono" style="font-size:.66rem;color:var(--muted);margin-inline-start:.5rem">${v.n_windows || 0} OOS windows</span></div>
      ${reasons ? `<div style="margin-top:.75rem">${reasons}</div>` : ''}`;
  }

  // ---- Execution quality ----
  function renderExecution(ex, os) {
    const status = $('execStatus');
    if (!ex) { $('execBody').innerHTML = '<div class="empty-note">—</div>'; return; }
    const stale = os ? os.stale_count : 0;
    setPill(status, stale > 0 ? 'warn' : 'ok', stale > 0 ? stale + ' stale' : 'clean');
    const ocs = Object.entries(ex.order_classes || {})
      .map(([k, n]) => `<span class="reason-chip">${esc(k)} · ${n}</span>`).join('') || '<span class="empty-note">—</span>';
    const b = ex.borrow_status || { etb: 0, htb: 0, unknown: 0 };
    const slip = ex.avg_slippage_pct;
    const slipKind = slip === null ? '' : (slip <= 0 ? 'pos' : 'neg');
    $('execBody').innerHTML = `
      <div class="metric-row">
        <div class="metric"><div class="label">Avg slippage</div><div class="value ${slipKind}">${slip === null ? '—' : fmtNum(slip, 3)}<span class="unit">%</span></div></div>
        <div class="metric"><div class="label">Working orders</div><div class="value">${os ? os.working_count : 0}</div></div>
        <div class="metric"><div class="label">Stale &gt;2h</div><div class="value ${stale ? 'neg' : 'pos'}">${stale}</div></div>
        <div class="metric"><div class="label">Schema v2</div><div class="value">${ex.schema_v2_trades}<span class="unit">/${ex.total_trades}</span></div></div>
      </div>
      <div style="margin-top:1rem"><div class="card-sub" style="margin-bottom:.5rem">Order classes</div>${ocs}</div>
      <div style="margin-top:1rem"><div class="card-sub" style="margin-bottom:.5rem">Short borrow confirmations</div>
        <span class="pill pill-ok">ETB ${b.etb}</span>
        <span class="pill ${b.htb ? 'pill-warn' : 'pill-muted'}" style="margin-inline-start:.4rem">HTB ${b.htb}</span>
        <span class="pill pill-muted" style="margin-inline-start:.4rem">other ${b.unknown}</span></div>`;
  }

  // ---- Accounting ----
  function renderAccounting(ex) {
    const status = $('acctStatus');
    if (!ex || !ex.accounting) { $('acctBody').innerHTML = '<div class="empty-note">—</div>'; return; }
    const a = ex.accounting;
    setPill(status, a.fee_aware_trades > 0 ? 'ok' : 'muted', a.fee_aware_trades > 0 ? 'net of fees' : 'no closes yet');
    const netKind = a.net_pnl > 0 ? 'pos' : a.net_pnl < 0 ? 'neg' : '';
    $('acctBody').innerHTML = `
      <div class="metric-row">
        <div class="metric"><div class="label">Realized (net)</div><div class="value ${netKind}">${fmtMoney(a.net_pnl)}</div></div>
        <div class="metric"><div class="label">Gross</div><div class="value">${fmtMoney(a.gross_pnl)}</div></div>
        <div class="metric"><div class="label">Fees paid</div><div class="value neg">${fmtMoney(-Math.abs(a.fees))}</div></div>
        <div class="metric"><div class="label">Closed</div><div class="value">${ex.closed_trades}</div></div>
      </div>
      <div class="legend" style="margin-top:1rem">Regulatory fees (SEC §31, FINRA TAF, CAT) are
        modeled on every fill; the realized figure above is what the readiness gates read.</div>`;
  }

  // ---- Governance ----
  function renderGovernance(g, selfLearning) {
    const status = $('govStatus');
    if (!g) { $('govBody').innerHTML = '<div class="empty-note">—</div>'; return; }
    if (!selfLearning) {
      setPill(status, 'muted', 'static');
      $('govBody').innerHTML = `<div class="empty-note">No self-learning loop on this book —
        parameters are fixed, so there is no adaptive change to govern.</div>`;
      return;
    }
    setPill(status, 'ok', g.total_decisions + ' logged');
    const rows = (g.decisions || []).map(dn => {
      const knobs = Object.keys(dn.changed_knobs || {});
      const when = dn.timestamp ? new Date(dn.timestamp).toLocaleString() : '—';
      return `<tr>
        <td class="mono" style="font-size:.72rem">${esc(when)}</td>
        <td><span class="pill ${dn.approved ? 'pill-ok' : 'pill-warn'}">${dn.approved ? 'approved' : 'reverted'}</span></td>
        <td>${dn.n_changes || 0}</td>
        <td class="mono" style="font-size:.72rem">${knobs.length ? esc(knobs.join(', ')) : '—'}</td></tr>`;
    }).join('');
    const lkg = g.last_known_good && g.last_known_good.params
      ? `<span class="pill pill-ok">snapshot ready</span>` : `<span class="pill pill-muted">none yet</span>`;
    $('govBody').innerHTML = `
      <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem;flex-wrap:wrap">
        <div class="metric"><div class="label">Decisions recorded</div><div class="value">${g.total_decisions}</div></div>
        <div class="metric"><div class="label">Auto-rollback</div><div style="margin-top:.4rem">${lkg}</div></div>
      </div>
      ${rows ? `<table class="intel-table"><thead><tr><th>When</th><th>Decision</th><th>#</th><th>Knobs</th></tr></thead><tbody>${rows}</tbody></table>`
        : `<div class="empty-note">No parameter decisions recorded yet. The deterministic gate
           (OOS Sharpe + PBO + Deflated Sharpe + challenger) writes a provenance row here on each
           nightly adaptation — fully automated, no human in the loop.</div>`}`;
  }

  // ---- Reconciliation ----
  function renderReconcile(r) {
    const status = $('recStatus');
    if (!r || r.unavailable) {
      setPill(status, 'muted', 'n/a');
      $('recBody').innerHTML = '<div class="empty-note">No reconciliation report yet.</div>';
      return;
    }
    const inSync = !!r.in_sync;
    setPill(status, inSync ? 'ok' : 'warn', inSync ? 'in sync' : 'drift');
    const block = (label, arr) => {
      const items = (arr || []);
      const body = items.length
        ? items.map(x => `<span class="reason-chip">${esc(typeof x === 'string' ? x : (x.symbol || JSON.stringify(x)))}</span>`).join('')
        : '<span class="pill pill-ok">none</span>';
      return `<div style="margin-bottom:.85rem"><div class="card-sub" style="margin-bottom:.4rem">${label}</div>${body}</div>`;
    };
    $('recBody').innerHTML = `
      <div class="metric-row" style="margin-bottom:1rem">
        <div class="metric"><div class="label">Positions</div><div class="value">${r.positions_held ?? '—'}</div></div>
        <div class="metric"><div class="label">Open trades</div><div class="value">${r.open_trades_logged ?? '—'}</div></div>
      </div>
      ${block('Orphan open trades', r.orphan_open_trades)}
      ${block('Unlogged positions', r.unlogged_positions)}
      ${block('Quantity drift', r.qty_drift)}
      ${block('Cost-basis drift', r.cost_basis_drift)}`;
  }

  async function loadAll() {
    $('lastUpdated').textContent = 'Refreshing…';
    try {
      const cross = await getJSON('/api/intelligence/cross-portfolio');
      renderConcentration(cross);
    } catch (e) { renderConcentration(null); }

    // The cross-portfolio concentration panel is genuinely aggregated, but the
    // per-book engine panels have no aggregate endpoint — under "All Books" they
    // show P1. Label that explicitly instead of implying it's an all-books figure.
    const id = currentPf === 'all' ? 'portfolio_1' : currentPf;
    const scopeNote = $('bookScopeNote');
    if (scopeNote) {
      if (currentPf === 'all') {
        scopeNote.style.display = 'block';
        scopeNote.innerHTML = 'Concentration above is aggregated across all books. The per-book engine panels below (Validation, Execution, Accounting, Governance, Reconciliation) reflect <strong>P1 · Self-Improving</strong> — select a specific book for P2/P3.';
      } else {
        scopeNote.style.display = 'none';
      }
    }
    try {
      const intel = await getJSON('/api/portfolio/' + id + '/intelligence');
      renderValidation(intel.validation);
      renderExecution(intel.execution, intel.order_state);
      renderAccounting(intel.execution);
      renderGovernance(intel.governance, intel.validation && intel.validation.self_learning);
      renderReconcile(intel.reconciliation);
    } catch (e) {
      ['valBody', 'execBody', 'acctBody', 'govBody', 'recBody'].forEach(b => {
        $(b).innerHTML = '<div class="empty-note">Unavailable.</div>';
      });
    }
    $('lastUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  }

  function initSelector() {
    document.getElementById('portfolioSelector').addEventListener('click', (e) => {
      const btn = e.target.closest('.intel-seg');
      if (!btn) return;
      document.querySelectorAll('.intel-seg').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentPf = btn.dataset.pf;
      loadAll();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initSelector();
    loadAll();
    timer = setInterval(loadAll, 30000);
    window.addEventListener('beforeunload', () => clearInterval(timer));
  });
})();
