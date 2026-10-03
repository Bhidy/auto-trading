import json
from collections import defaultdict
from common import OUT, HORIZONS, fwd, spearman, mean, series_stats, t_simple, CIDX, CAL, nw_t

snaps = json.load(open(f"{OUT}/snap_p3.json"))
days = sorted(d for d in snaps if d in CIDX)


def p3_score(stock, limits):
    """Mirror of event_driven_bot.generate_signals scoring (returns None if regime-filtered)."""
    price = stock["price"]
    bb_upper, bb_width = stock.get("bb_upper"), stock.get("bb_width_pct")
    ml, ms, mh = stock.get("macd_line"), stock.get("macd_signal"), stock.get("macd_histogram")
    rsi_val, rvol = stock.get("rsi14"), stock.get("rvol_5d", 1.0)
    a200, a50, rs = stock.get("above_ema200", False), stock.get("above_ema50", False), stock.get("rs_vs_spy_3m", 0)
    if not a200 and limits.get("regime_filter_enabled"):
        return None, {}
    comp = {"bb_break": 0.0, "squeeze": 0.0, "macd": 0.0, "rvol": 0.0, "rs": 0.0, "trend": 0.0, "rsi": 0.0}
    if bb_upper and price >= bb_upper * 0.995: comp["bb_break"] = 0.30
    if bb_width and bb_width < 5.0: comp["squeeze"] = 0.10
    if mh and mh > 0 and ml and ms and ml > ms:
        comp["macd"] = 0.20 + (0.10 if ml < 0 else 0)
    if rvol >= limits.get("breakout_rvol_threshold", 1.5): comp["rvol"] = 0.15
    comp["rs"] = 0.15 if rs > 10 else (0.08 if rs > 5 else 0)
    if a200 and a50: comp["trend"] = 0.10
    if rsi_val:
        comp["rsi"] = 0.05 if 40 <= rsi_val <= 65 else (-0.15 if rsi_val >= 80 else 0)
    return round(sum(comp.values()), 3), comp


rows = {}
mism, checked = 0, 0
screen_days = []
prev_wl = None
for d in days:
    s = snaps[d]
    wl = s.get("watchlist") or {}
    limits = s.get("limits") or {}
    wts = (wl.get("timestamp") or "")[:10]  # one screen per watchlist DATE (same-day re-saves merged)
    if wts != prev_wl:
        screen_days.append(d)
    prev_wl = wts
    committed = {x["symbol"]: x["score"] for x in s["data"]["signals"]}
    rr = []
    for st in wl.get("universe", []):
        sc, comp = p3_score(st, limits)
        if sc is None:
            continue
        if st["symbol"] in committed:
            checked += 1
            if abs(committed[st["symbol"]] - sc) > 1e-6:
                mism += 1
        rec = {"sym": st["symbol"], "score": sc, "sel": st["symbol"] in committed, **comp,
               "c_rs": st.get("rs_vs_spy_3m"), "c_rsi": st.get("rsi14"), "c_rvol": st.get("rvol_5d"),
               "c_ret1m": st.get("return_1m")}
        for h in HORIZONS:
            rec[f"r{h}"] = fwd(st["symbol"], d, h)
            rec[f"x{h}"] = fwd(st["symbol"], d, h, excess=True)
        rr.append(rec)
    rows[d] = rr
# committed names not found in watchlist
notfound = sum(1 for d in days for x in snaps[d]["data"]["signals"] if x["symbol"] not in {r["sym"] for r in rows[d]})


def ic_series(key, h, dayset):
    out = []
    for d in dayset:
        rr = [r for r in rows[d] if r[f"r{h}"] is not None and r.get(key) is not None]
        if len(rr) < 8:
            continue
        v = spearman([r[key] for r in rr], [r[f"r{h}"] for r in rr])
        if v is not None:
            out.append((d, v))
    return out


res = {"days": len(days), "screens": len(screen_days), "screen_days": screen_days,
       "recon_checked": checked, "recon_mismatch": mism, "committed_not_in_wl": notfound,
       "scored_per_day": mean([len(rows[d]) for d in days]),
       "selected_per_day": mean([sum(r["sel"] for r in rows[d]) for d in days])}

# Weekly (screen-day) sampling is the primary independent unit: signals are frozen Tue-Fri.
res["ic_weekly"], res["ic_daily"] = {}, {}
for h in HORIZONS:
    res["ic_weekly"][h] = series_stats(ic_series("score", h, screen_days), max(1, h // 5), step=max(1, -(-h // 5)))
    res["ic_daily"][h] = series_stats(ic_series("score", h, days), h + 4)

# Selected BUY vs non-selected scored names, excess vs SPY (screen-day sampling and all days)
res["sel"] = {}
for h in HORIZONS:
    for lab, dset in [("weekly", screen_days), ("daily", days)]:
        ser_sel, ser_spread, pooled = [], [], []
        for d in dset:
            a = [r[f"x{h}"] for r in rows[d] if r["sel"] and r[f"x{h}"] is not None]
            b = [r[f"x{h}"] for r in rows[d] if not r["sel"] and r[f"x{h}"] is not None]
            if a:
                ser_sel.append((d, mean(a)))
                pooled += a
            if a and b:
                ser_spread.append((d, mean(a) - mean(b)))
        lag = max(1, h // 5) if lab == "weekly" else h + 4
        step = max(1, -(-h // 5)) if lab == "weekly" else h
        res["sel"][f"{lab}_h{h}"] = {"sel_excess": series_stats(ser_sel, lag, step=step),
                                    "sel_minus_unsel": series_stats(ser_spread, lag, step=step),
                                    "pooled_n": len(pooled), "pooled_hit": mean([1.0 if v > 0 else 0.0 for v in pooled]) if pooled else None}

# Tercile buckets on screen days
res["terc"] = {}
from common import rank
for h in HORIZONS:
    acc = defaultdict(list)
    for d in screen_days:
        rr = [r for r in rows[d] if r[f"x{h}"] is not None]
        if len(rr) < 9:
            continue
        rk = rank([r["score"] for r in rr])
        b = defaultdict(list)
        for r, k in zip(rr, rk):
            b[min(int((k - 1) / len(rr) * 3), 2)].append(r[f"x{h}"])
        for q in range(3):
            if b[q]:
                acc[q].append(mean(b[q]))
    res["terc"][h] = {q: mean(v) for q, v in sorted(acc.items())}

# Component ICs (screen days)
res["comp"] = {}
for k in ["bb_break", "squeeze", "macd", "rvol", "rs", "trend", "rsi", "c_rs", "c_rsi", "c_rvol", "c_ret1m"]:
    for h in [5, 10, 21]:
        res["comp"][f"{k}_h{h}"] = series_stats(ic_series(k, h, screen_days), max(1, h // 5), step=max(1, -(-h // 5)))

# Staleness: IC on screen day vs later days in the same week (h=5)
fresh = [d for d in days if d in screen_days]
stale = [d for d in days if d not in screen_days]
res["stale"] = {f"h{h}": {"fresh": series_stats(ic_series("score", h, fresh), 1, step=1),
                          "stale": series_stats(ic_series("score", h, stale), h + 4, step=h)} for h in [1, 5]}

# Halves (screen days)
half = screen_days[len(screen_days) // 2]
res["halves"] = {}
for h in HORIZONS:
    res["halves"][f"H1_h{h}"] = series_stats(ic_series("score", h, [d for d in screen_days if d < half]), max(1, h // 5), step=max(1, -(-h // 5)))
    res["halves"][f"H2_h{h}"] = series_stats(ic_series("score", h, [d for d in screen_days if d >= half]), max(1, h // 5), step=max(1, -(-h // 5)))

# P1 regime label by day for P3 IC by regime
p1 = json.load(open(f"{OUT}/snap_p1.json"))
res["by_regime"] = {}
for reg in ["STRONG_BULL", "BULL", "CORRECTION"]:
    dd = [d for d in days if p1.get(d, {}).get("data", {}).get("market_regime") == reg]
    for h in [5, 10]:
        res["by_regime"][f"{reg}_h{h}"] = series_stats(ic_series("score", h, dd), h + 4)

# News event study
news = json.load(open(f"{OUT}/snap_p3news.json"))
ev = {}
for d in sorted(news):
    for x in news[d]["data"]["signals"]:
        ev[(x["symbol"], d)] = x
res["news"] = {"events": len(ev)}
for h in HORIZONS:
    v = [fwd(s, d, h, excess=True) for (s, d) in ev]
    v = [x for x in v if x is not None]
    res["news"][h] = {"n": len(v), "mean": mean(v), "t": t_simple(v), "hit": mean([1.0 if x > 0 else 0.0 for x in v]) if v else None}

json.dump(res, open(f"{OUT}/res_p3.json", "w"), indent=1, default=str)


def fmt(st):
    return f"n={st['n']:3d} mean={st['mean']:+.3f} sd={st['std']:.3f} hit={st['hit']:.0%} tNW={st['t_nw']:+.2f} tNO={st['t_nonov']:+.2f}(n={st['n_nonov']})"


print({k: res[k] for k in ["days", "screens", "recon_checked", "recon_mismatch", "committed_not_in_wl", "scored_per_day", "selected_per_day"]})
print("screen days", screen_days)
print("== IC weekly (screen-day sampling)")
for h, v in res["ic_weekly"].items(): print(h, fmt(v))
print("== IC daily (NW lag h+4)")
for h, v in res["ic_daily"].items(): print(h, fmt(v))
print("== selected BUY vs SPY and vs unselected (excess)")
for k, v in res["sel"].items():
    print(k, "selX", fmt(v["sel_excess"]), "| sel-unsel", fmt(v["sel_minus_unsel"]), "pooled", v["pooled_n"], round(v["pooled_hit"] or 0, 2))
print("== terciles excess (screen days)")
for h, v in res["terc"].items(): print(h, {q: round(x * 100, 2) for q, x in v.items()})
print("== components")
for k, v in res["comp"].items(): print(f"{k:14s}", fmt(v))
print("== stale vs fresh")
for k, v in res["stale"].items(): print(k, "fresh", fmt(v["fresh"]), "| stale", fmt(v["stale"]))
print("== halves", half)
for k, v in res["halves"].items(): print(k, fmt(v))
print("== by regime (daily)")
for k, v in res["by_regime"].items(): print(k, fmt(v))
print("== news", res["news"]["events"])
for h in HORIZONS:
    v = res["news"][h]; print(h, v["n"], f"{v['mean']*100:+.2f}%", f"t={v['t']:+.2f}", v["hit"])
