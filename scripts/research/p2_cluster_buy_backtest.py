#!/usr/bin/env python3
"""P2 "Capitol Shadow" — SIGNAL-CONVERGENCE experiment.

Question
--------
Do CLUSTER-BUYS (>=2 — and separately >=3 — DISTINCT tracked members filing a
BUY into the SAME ticker inside a 30-day window) beat LONE disclosures?

The prior committed backtest (data/p2_congress_copy_backtest.json) found NO real
alpha for the deployed 8%-stop rule (t_alpha=0.41) and that the headline
hold_63d alpha (t=3.76) is 2020-COVID + 2022-concentrated BETA, not a stable
edge. The thesis here: a single politician's disclosure is one noisy signal;
several independent members converging on the same name within a short window is
a stronger, less-noisy signal. We test whether that convergence creates
significant, OUT-OF-SAMPLE-stable alpha.

No-look-ahead discipline (inherited + extended)
-----------------------------------------------
- This script REUSES the committed pipeline in p2_congress_copy_backtest.py
  (STAGE 1 index -> STAGE 2 cached PTR parse -> STAGE 3 ticker map + price load +
  matched-pair backtest). Nothing about fill/friction/stale-skip changes.
- The cluster label for a copy event at filing date t is computed using ONLY
  filings with filing_date <= t (a strict BACKWARD-looking [t-30d, t] window).
  We NEVER look forward to future co-filers — that would be look-ahead. So the
  cluster flag is exactly what a live copier would know at the close of t.
- Distinct-member counting normalizes name variants (e.g.
  "Marjorie Taylor Greene" / "Marjorie Taylor Mrs Greene",
  "Mark Green" / "Mark Dr Green") so a single member's amended/dual-name filings
  cannot fake a cluster.
- Each trade still fills at OPEN of t+1, pays friction (>=5bps each side) on both
  sides, and is matched to SPY over the identical window. Alpha = mean per-trade
  (stock_ret - spy_ret) excess, with a paired t-stat. Split OOS by filing year.

Honesty: REAL numbers only (run the script). Small N per cell is reported and
treated as not significant.

OFFLINE RESEARCH (T2). Never runs on the cloud trading path.
"""
import importlib.util
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.backtest import metrics as M  # noqa: E402
from scripts.backtest.friction import load_friction  # noqa: E402

# Import the committed backtest module by file path (it has a hyphen-free name
# but lives next to us) so we reuse its EXACT pipeline, not a re-implementation.
_SPEC = importlib.util.spec_from_file_location(
    "p2_congress_copy_backtest",
    str(Path(__file__).resolve().parent / "p2_congress_copy_backtest.py"),
)
P2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(P2)

CLUSTER_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Member-name normalization (collapse honorific / dual-name variants)
# ---------------------------------------------------------------------------
def normalize_member(name):
    """Collapse the known dual-name variants to ONE canonical identity so a
    single member cannot manufacture a cluster via amended / honorific filings."""
    n = name.strip().lower()
    # strip honorifics / titles that appear inside the House clerk strings
    n = re.sub(r"\b(mr|mrs|ms|dr|rep|hon|jr|sr|ii|iii)\b\.?", " ", n)
    n = re.sub(r"[^a-z ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # canonical surname-first key handles middle-name/initial drift
    parts = n.split()
    if len(parts) >= 2:
        # use first + last token (robust to dropped middle initials)
        return f"{parts[0]} {parts[-1]}"
    return n


def _iso(d):
    return date(int(d[:4]), int(d[5:7]), int(d[8:10]))


# ---------------------------------------------------------------------------
# Cluster flagging — strictly backward-looking, no look-ahead
# ---------------------------------------------------------------------------
def flag_clusters(buys, window_days=CLUSTER_WINDOW_DAYS):
    """For each buy event, count DISTINCT normalized members who filed a BUY in
    the SAME ticker with filing_date in [t - window_days, t]. The event's own
    member counts. Returns the same list with 'distinct_members_window' added.

    Look-ahead safety: only filings with filing_date <= t are considered. A live
    copier at close of t knows every disclosure already public on/before t.
    """
    # group filing dates per (ticker, normalized member)
    by_ticker = {}
    for b in buys:
        tk = b["ticker"]
        m = normalize_member(b["member"])
        fd = _iso(b["filing_date"])
        by_ticker.setdefault(tk, []).append((fd, m))
    for tk in by_ticker:
        by_ticker[tk].sort()

    out = []
    for b in buys:
        tk = b["ticker"]
        t = _iso(b["filing_date"])
        lo = t.toordinal() - window_days
        members = set()
        for fd, m in by_ticker[tk]:
            o = fd.toordinal()
            if o > t.toordinal():
                break  # sorted asc -> nothing past t matters (no look-ahead)
            if o >= lo:
                members.add(m)
        b2 = dict(b)
        b2["distinct_members_window"] = len(members)
        out.append(b2)
    return out


# ---------------------------------------------------------------------------
# Backtest a cohort of buys (subset) over fixed horizons + p2 rules
# ---------------------------------------------------------------------------
HORIZONS = [21, 63, 126]


def backtest_cohort(buys, bars, spy, fr):
    """Matched-pair backtest of a buy cohort. Mirrors P2.backtest_buys' fill +
    friction + stale-skip logic exactly, but for an arbitrary subset and with
    the same MAX_FILL_GAP_DAYS guard. Returns per-strategy pairs + by_year."""
    strat = {f"hold_{h}d": {"pairs": [], "by_year": {}} for h in HORIZONS}
    strat["p2_rules"] = {"pairs": [], "by_year": {}}
    strat["p2_rules_wide"] = {"pairs": [], "by_year": {}}
    n_filled = n_no_price = n_no_future = n_stale = 0

    for bz in buys:
        tk = bz["ticker"]
        series = bars.get(tk)
        if not series:
            n_no_price += 1
            continue
        fdate = bz["filing_date"]
        ei = P2.next_open_index(series, fdate)
        if ei is None:
            n_no_future += 1
            continue
        if P2._iso_gap_days(fdate, series[ei][0]) > P2.MAX_FILL_GAP_DAYS:
            n_stale += 1
            continue
        entry_open = series[ei][1]
        if entry_open <= 0:
            continue
        entry_px = entry_open * (1 + fr)
        n_filled += 1
        yr = str(bz["filing_year"])
        spy_ei = P2.next_open_index(spy, fdate) if spy else None

        for h in HORIZONS:
            xi = ei + h
            if xi >= len(series):
                continue
            exit_px = series[xi][2] * (1 - fr)
            ret = exit_px / entry_px - 1.0
            sret = P2.spy_ret(spy, spy_ei, h, fr)
            d = strat[f"hold_{h}d"]
            d["pairs"].append((ret, sret))
            d["by_year"].setdefault(yr, []).append((ret, sret))

        ret, hold_used = P2.p2_exit(series, ei, entry_px, fr, stop=0.08, tp=0.25, maxhold=180)
        sret = P2.spy_ret(spy, spy_ei, hold_used, fr)
        strat["p2_rules"]["pairs"].append((ret, sret))
        strat["p2_rules"]["by_year"].setdefault(yr, []).append((ret, sret))

        retw, holdw = P2.p2_exit(series, ei, entry_px, fr, stop=0.18, tp=0.25, maxhold=252)
        sretw = P2.spy_ret(spy, spy_ei, holdw, fr)
        strat["p2_rules_wide"]["pairs"].append((retw, sretw))
        strat["p2_rules_wide"]["by_year"].setdefault(yr, []).append((retw, sretw))

    fills = {"filled": n_filled, "no_price": n_no_price,
             "no_future_bar": n_no_future, "stale_skipped": n_stale}
    return strat, fills


def diff_test(cluster_pairs, lone_pairs):
    """Two-sample (Welch) t-test on per-trade ALPHA (stock-spy excess) between a
    cluster cohort and the lone cohort. Returns (delta_alpha_pct, t, n1, n2).
    This is the decision metric: does converging members' alpha EXCEED lone?"""
    a = [p[0] - p[1] for p in cluster_pairs if p[1] is not None]
    b = [p[0] - p[1] for p in lone_pairs if p[1] is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = M._mean(a), M._mean(b)
    va, vb = M._std(a) ** 2, M._std(b) ** 2
    se = (va / len(a) + vb / len(b)) ** 0.5
    t = (ma - mb) / se if se > 0 else 0.0
    return {"delta_alpha_pct": round((ma - mb) * 100, 3), "welch_t": round(t, 2),
            "n_cluster": len(a), "n_lone": len(b)}


def main():
    print("=" * 72)
    print("P2 CLUSTER-BUY experiment — does signal convergence create real edge?")
    print("=" * 72)

    # --- Reuse the committed pipeline to rebuild `final_buys` ----------------
    filings = json.loads(P2.INDEX.read_text())
    print("STAGE 1: %d PTR filings" % len(filings))
    cache = P2.stage2_parse(filings)

    txns = []
    for f in filings:
        rec = cache.get(f["doc_id"], {})
        for row in rec.get("rows", []):
            txns.append({**row, "member": f["member"],
                         "filing_date": f["filing_date"], "filing_year": f["year"]})

    equity_buys = [t for t in txns if t["code"] == "P"
                   and not P2.looks_like_bond_or_private(t["asset_name"], t["asset_code"])]

    bars = P2.load_universe_bars()
    priceable = set(bars.keys())
    # extend universe with cached extra bars (same as committed script)
    if P2.EXTRA_PRICE.exists():
        extra = json.loads(P2.EXTRA_PRICE.read_text())
        for tk, rows in extra.items():
            if len(rows) >= 100:
                series = sorted((b["t"][:10], float(b["o"]), float(b["c"])) for b in rows)
                bars[tk] = series
                priceable.add(tk)

    mapped = []
    for b in equity_buys:
        tk = P2.map_to_ticker(b, priceable)
        if tk:
            b2 = dict(b)
            b2["ticker"] = tk
            mapped.append(b2)

    final_buys = []
    for b in mapped:
        try:
            fd = P2.parse_mdy(b["filing_date"])
            td = P2.parse_mdy(b["txn_date"])
            lag = (fd - td).days
            if lag < 0 or lag > 400:
                lag = None
            b["filing_date"] = fd.isoformat()
            b["disclosure_lag_days"] = lag
            final_buys.append(b)
        except Exception:  # noqa: BLE001
            continue
    seen, dedup = set(), []
    for b in final_buys:
        k = (b["member"], b["ticker"], b["txn_date"], b["filing_date"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(b)
    final_buys = dedup
    print("  final distinct equity-BUY copy events: %d (tickers=%d)"
          % (len(final_buys), len({b["ticker"] for b in final_buys})))
    n_norm = len({normalize_member(b["member"]) for b in final_buys})
    print("  distinct NORMALIZED members: %d" % n_norm)

    # --- Cluster flagging (backward-looking 30d window) ---------------------
    flagged = flag_clusters(final_buys, CLUSTER_WINDOW_DAYS)
    dist = {}
    for b in flagged:
        d = b["distinct_members_window"]
        dist[d] = dist.get(d, 0) + 1
    print("\n  cluster size distribution (distinct members in trailing %dd):"
          % CLUSTER_WINDOW_DAYS)
    for k in sorted(dist):
        print("    %d member(s): %d events" % (k, dist[k]))

    lone = [b for b in flagged if b["distinct_members_window"] == 1]
    clu2 = [b for b in flagged if b["distinct_members_window"] >= 2]
    clu3 = [b for b in flagged if b["distinct_members_window"] >= 3]
    print("\n  cohorts: lone=%d  cluster>=2=%d  cluster>=3=%d"
          % (len(lone), len(clu2), len(clu3)))

    cost_bps, slip_bps = load_friction("portfolio_2")
    fr = (cost_bps + slip_bps) / 10000.0
    print("  friction: %.1f/%.1f bps each side -> %.4f per side" % (cost_bps, slip_bps, fr))
    spy = bars.get("SPY")

    cohorts = {"lone": lone, "cluster_ge2": clu2, "cluster_ge3": clu3}
    results = {}
    for name, cohort in cohorts.items():
        strat, fills = backtest_cohort(cohort, bars, spy, fr)
        results[name] = {"fills": fills, "strat": strat}

    # --- Report -------------------------------------------------------------
    report = {
        "as_of": datetime.utcnow().isoformat(),
        "experiment": "cluster_buy_signal_convergence",
        "cluster_window_days": CLUSTER_WINDOW_DAYS,
        "n_copy_events": len(final_buys),
        "n_normalized_members": n_norm,
        "cluster_size_distribution": dist,
        "cohort_sizes": {"lone": len(lone), "cluster_ge2": len(clu2),
                         "cluster_ge3": len(clu3)},
        "friction_bps_each_side": {"cost": cost_bps, "slippage": slip_bps},
        "cohorts": {},
        "cluster_vs_lone_diff": {},
    }

    for name in cohorts:
        report["cohorts"][name] = {"fills": results[name]["fills"], "strategies": {}}
        print("\n" + "-" * 72)
        print("COHORT: %s  (fills=%s)" % (name, results[name]["fills"]))
        for sname, d in results[name]["strat"].items():
            blk = P2.stats_block(d["pairs"])
            if not blk:
                continue
            by_year = {y: P2.stats_block(rs) for y, rs in sorted(d["by_year"].items())}
            report["cohorts"][name]["strategies"][sname] = {
                "overall": blk, "by_year": by_year}
            if sname == "hold_63d" or sname == "p2_rules":
                print("  [%s] n=%d mean=%.2f%% win=%.0f%% alpha=%s%% (t_alpha=%.2f, alpha_win=%s%%) SPY=%s%%"
                      % (sname, blk["n"], blk["mean_ret_pct"], blk["win_rate_pct"],
                         blk["mean_alpha_vs_spy_pct"], blk["t_stat_alpha"],
                         blk["alpha_win_rate_pct"], blk["spy_mean_pct"]))
                if sname == "hold_63d":
                    for y, yb in by_year.items():
                        if yb:
                            print("       %s: n=%-4d mean=%6.2f%% alpha=%6.2f%% t_a=%s"
                                  % (y, yb["n"], yb["mean_ret_pct"],
                                     yb["mean_alpha_vs_spy_pct"] or 0.0,
                                     yb.get("t_stat_alpha")))

    # --- Cluster-vs-lone difference tests (the decision metric) -------------
    print("\n" + "=" * 72)
    print("CLUSTER vs LONE — two-sample Welch t-test on per-trade ALPHA (excess vs SPY)")
    print("=" * 72)
    for sname in [f"hold_{h}d" for h in HORIZONS] + ["p2_rules", "p2_rules_wide"]:
        lone_pairs = results["lone"]["strat"][sname]["pairs"]
        report["cluster_vs_lone_diff"][sname] = {}
        for cl in ["cluster_ge2", "cluster_ge3"]:
            cl_pairs = results[cl]["strat"][sname]["pairs"]
            dt = diff_test(cl_pairs, lone_pairs)
            report["cluster_vs_lone_diff"][sname][cl] = dt
            if dt:
                print("  [%s] %s - lone: delta_alpha=%+.2f%% (Welch t=%+.2f, n_cl=%d vs n_lone=%d)"
                      % (sname, cl, dt["delta_alpha_pct"], dt["welch_t"],
                         dt["n_cluster"], dt["n_lone"]))

    # --- By-year cluster_ge2 vs lone on hold_63d (OOS stability check) ------
    print("\n  --- hold_63d cluster>=2 vs lone, BY YEAR (OOS stability) ---")
    ly = results["lone"]["strat"]["hold_63d"]["by_year"]
    cy = results["cluster_ge2"]["strat"]["hold_63d"]["by_year"]
    yearly_oos = {}
    for y in sorted(set(ly) | set(cy)):
        dt = diff_test(cy.get(y, []), ly.get(y, []))
        if dt:
            yearly_oos[y] = dt
            print("    %s: delta_alpha=%+.2f%% (Welch t=%+.2f, n_cl=%d vs n_lone=%d)"
                  % (y, dt["delta_alpha_pct"], dt["welch_t"], dt["n_cluster"], dt["n_lone"]))
    report["cluster_ge2_vs_lone_by_year_hold63d"] = yearly_oos

    out_path = REPO / "data" / "p2_cluster_buy_backtest.json"
    out_path.write_text(json.dumps(report, indent=2))
    print("\nReport -> %s" % out_path)
    return report


if __name__ == "__main__":
    main()
