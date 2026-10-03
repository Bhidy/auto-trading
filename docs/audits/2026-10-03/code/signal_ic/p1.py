import json
from collections import defaultdict
from common import (OUT, HORIZONS, DEFENSIVE, fwd, spearman, mean, series_stats, CIDX)

snaps = json.load(open(f"{OUT}/snap_p1.json"))
days = sorted(d for d in snaps if d in CIDX)
missing_cal = sorted(d for d in snaps if d not in CIDX)


def factors(x, params, rs_map):
    r = " | ".join(x.get("reasons", []))
    ind = x.get("indicators", {})
    thr = (params or {}).get("momentum_threshold", 0) or 0
    f = {}
    f["trend"] = 0.30 if "Uptrend" in r else (-0.30 if "Downtrend" in r else 0.0)
    m1, m3, m6 = ind.get("momentum_1m"), ind.get("momentum_3m"), ind.get("momentum_6m")
    ms = 0.0
    if m1 and m1 > 0: ms += 0.08
    if m3 and m3 > thr: ms += 0.10
    if m6 and m6 > thr: ms += 0.07
    if m1 and m1 < 0: ms -= 0.08
    if m3 and m3 < -thr: ms -= 0.10
    if m6 and m6 < -thr: ms -= 0.07
    f["momentum"] = ms
    if "RSI overbought" in r: f["rsi"] = -0.15
    elif "RSI oversold" in r or "RSI in buy zone" in r: f["rsi"] = 0.10
    elif "RSI neutral" in r: f["rsi"] = 0.05
    else: f["rsi"] = 0.0
    f["macd"] = 1.0 if "MACD bullish" in r else (-1.0 if "MACD bearish" in r else 0.0)
    f["bollinger"] = 1.0 if "below lower Bollinger" in r else (-1.0 if "above upper Bollinger" in r else 0.0)
    f["volume"] = 1.0 if "Volume surging" in r else (-0.6 if "Volume declining" in r else 0.0)
    f["rel_strength"] = 1.0 if "relative strength" in r and r.find("Top ") >= 0 else (-0.5 if "Bottom " in r else 0.0)
    # continuous raw drivers
    p = ind.get("price")
    c = {}
    if p and ind.get("ma_fast"): c["c_px_vs_ma50"] = p / ind["ma_fast"] - 1
    if p and ind.get("ma_slow"): c["c_px_vs_ma200"] = p / ind["ma_slow"] - 1
    c["c_mom1m"] = m1 if m1 is not None else 0.0
    c["c_mom3m"] = m3 if m3 is not None else 0.0
    if m6 is not None: c["c_mom6m"] = m6
    if ind.get("rsi14") is not None: c["c_rsi14"] = ind["rsi14"]
    if p and ind.get("macd_histogram") is not None: c["c_macdhist_px"] = ind["macd_histogram"] / p
    if p and ind.get("bb_lower") and ind.get("bb_upper") and ind["bb_upper"] > ind["bb_lower"]:
        c["c_pctB"] = (p - ind["bb_lower"]) / (ind["bb_upper"] - ind["bb_lower"])
    if ind.get("volume_trend_pct") is not None: c["c_voltrend"] = ind["volume_trend_pct"]
    if x["symbol"] in rs_map: c["c_rs_score"] = rs_map[x["symbol"]]
    f.update(c)
    # additive raw composite (pre-regime, weights as in analyst_v2 defaults)
    w = params or {}
    f["_raw"] = (f["trend"] + f["momentum"] + f["rsi"] + f["macd"] * w.get("macd_weight", 0.10)
                 + f["bollinger"] * w.get("bb_weight", 0.05)
                 + (w.get("volume_weight", 0.05) if f["volume"] > 0 else (-0.03 if f["volume"] < 0 else 0))
                 + (w.get("rs_weight", 0.10) if f["rel_strength"] > 0 else (-0.5 * w.get("rs_weight", 0.10) if f["rel_strength"] < 0 else 0)))
    f["_w"] = {"trend": f["trend"], "momentum": f["momentum"], "rsi": f["rsi"],
               "macd": f["macd"] * w.get("macd_weight", 0.10), "bollinger": f["bollinger"] * w.get("bb_weight", 0.05),
               "volume": (w.get("volume_weight", 0.05) if f["volume"] > 0 else (-0.03 if f["volume"] < 0 else 0)),
               "rel_strength": (w.get("rs_weight", 0.10) if f["rel_strength"] > 0 else (-0.5 * w.get("rs_weight", 0.10) if f["rel_strength"] < 0 else 0))}
    return f


rows = defaultdict(list)  # day -> list of dict
for d in days:
    s = snaps[d]
    rs_map = {r["symbol"]: r["rs_score"] for r in s["data"].get("relative_strength_ranking", [])}
    for x in s["data"]["signals"]:
        if x.get("score") is None or "/" in x["symbol"]:
            continue
        f = factors(x, s.get("params"), rs_map)
        rec = {"sym": x["symbol"], "score": x["score"], "signal": x["signal"], "regime": s["data"].get("market_regime"), **f}
        for h in HORIZONS:
            rec[f"r{h}"] = fwd(x["symbol"], d, h)
            rec[f"x{h}"] = fwd(x["symbol"], d, h, excess=True)
        rows[d].append(rec)

# check reconstruction: raw additive (pre-regime) vs committed score rank agreement
agree = []
for d in days:
    rr = rows[d]
    v = spearman([r["_raw"] for r in rr], [r["score"] for r in rr])
    if v is not None:
        agree.append(v)


def ic_series(key, h, subset=None, day_filter=None):
    out = []
    for d in days:
        if day_filter and not day_filter(d):
            continue
        rr = [r for r in rows[d] if r[f"r{h}"] is not None and key in r and (subset is None or subset(r))]
        if len(rr) < 5:
            continue
        v = spearman([r[key] for r in rr], [r[f"r{h}"] for r in rr])
        if v is not None:
            out.append((d, v))
    return out


res = {"days": len(days), "first": days[0], "last": days[-1], "missing_cal": missing_cal,
       "names_per_day": mean([len(rows[d]) for d in days]), "recon_rank_agreement_mean": mean(agree),
       "recon_rank_agreement_min": min(agree)}

# 1) composite IC
res["ic"] = {}
for uni, sub in [("all", None), ("risk_only", lambda r: r["sym"] not in DEFENSIVE)]:
    for h in HORIZONS:
        res["ic"][f"{uni}_h{h}"] = series_stats(ic_series("score", h, sub), h)

# 2) quintile / tercile buckets (rank-based within day)
def buckets(h, nb):
    acc = defaultdict(list)
    spread = []
    for d in days:
        rr = [r for r in rows[d] if r[f"r{h}"] is not None]
        if len(rr) < nb * 2:
            continue
        rr.sort(key=lambda r: (r["score"], r["sym"]))
        # average-rank based to treat ties fairly
        from common import rank
        rk = rank([r["score"] for r in rr])
        n = len(rr)
        b = defaultdict(list)
        for r, k in zip(rr, rk):
            q = min(int((k - 1) / n * nb), nb - 1)
            b[q].append(r[f"x{h}"])
        for q in range(nb):
            if b[q]:
                acc[q].append(mean(b[q]))
        if b[0] and b[nb - 1]:
            spread.append((d, mean(b[nb - 1]) - mean(b[0])))
    return {q: mean(v) for q, v in sorted(acc.items())}, series_stats(spread, h)

res["quint"] = {}
for h in HORIZONS:
    q, sp = buckets(h, 5)
    t, spt = buckets(h, 3)
    res["quint"][h] = {"quint_excess": q, "q5_q1": sp, "terc_excess": t, "t3_t1": spt}

# 3) BUY / SHORT forward excess (equal-weight per day, then time-series)
res["buy"], res["short"] = {}, {}
for h in HORIZONS:
    for lab, key in [("buy", "BUY"), ("short", "SHORT")]:
        ser, pooled, pooled_raw = [], [], []
        for d in days:
            v = [r[f"x{h}"] for r in rows[d] if r["signal"] == key and r[f"x{h}"] is not None]
            vr = [r[f"r{h}"] for r in rows[d] if r["signal"] == key and r[f"r{h}"] is not None]
            if v:
                ser.append((d, mean(v)))
                pooled += v
                pooled_raw += vr
        st = series_stats(ser, h)
        st["pooled_n"] = len(pooled)
        st["pooled_mean_excess"] = mean(pooled)
        st["pooled_mean_raw"] = mean(pooled_raw)
        st["hit_excess_pooled"] = mean([1.0 if v > 0 else 0.0 for v in pooled]) if pooled else None
        res[lab][h] = st
    # HOLD baseline
    ser = []
    for d in days:
        v = [r[f"x{h}"] for r in rows[d] if r["signal"] == "HOLD" and r[f"x{h}"] is not None]
        if v:
            ser.append((d, mean(v)))
    res.setdefault("hold", {})[h] = series_stats(ser, h)

# 4) factor ICs
FACT = ["trend", "momentum", "rsi", "macd", "bollinger", "volume", "rel_strength",
        "c_px_vs_ma50", "c_px_vs_ma200", "c_mom1m", "c_mom3m", "c_mom6m", "c_rsi14", "c_macdhist_px", "c_pctB",
        "c_voltrend", "c_rs_score", "_raw"]
res["factor"] = {}
for fk in FACT:
    for h in HORIZONS:
        res["factor"][f"{fk}_h{h}"] = series_stats(ic_series(fk, h), h)

# drop-one: IC of raw composite minus one factor's weighted contribution
for d in days:
    for r in rows[d]:
        for k, v in r["_w"].items():
            r[f"_drop_{k}"] = r["_raw"] - v
for k in ["trend", "momentum", "rsi", "macd", "bollinger", "volume", "rel_strength"]:
    for h in HORIZONS:
        res["factor"][f"_drop_{k}_h{h}"] = series_stats(ic_series(f"_drop_{k}", h), h)

# factor coverage: share of names with nonzero value
res["factor_nonzero_share"] = {k: mean([mean([1.0 if r[k] != 0 else 0.0 for r in rows[d]]) for d in days])
                               for k in ["trend", "momentum", "rsi", "macd", "bollinger", "volume", "rel_strength"]}

# 5) stability: halves and regime
half = days[len(days) // 2]
res["stab"] = {}
for h in HORIZONS:
    res["stab"][f"H1_h{h}"] = series_stats(ic_series("score", h, day_filter=lambda d: d < half), h)
    res["stab"][f"H2_h{h}"] = series_stats(ic_series("score", h, day_filter=lambda d: d >= half), h)
    for reg in ["STRONG_BULL", "BULL", "CORRECTION"]:
        res["stab"][f"{reg}_h{h}"] = series_stats(
            ic_series("score", h, day_filter=lambda d, reg=reg: snaps[d]["data"].get("market_regime") == reg), h)
res["half_split"] = half

# 6) regime timing: SPY fwd return by regime label (time-series)
res["regime_spy"] = {}
for h in HORIZONS:
    for reg in ["STRONG_BULL", "BULL", "CORRECTION"]:
        ser = [(d, fwd("SPY", d, h)) for d in days if snaps[d]["data"].get("market_regime") == reg and fwd("SPY", d, h) is not None]
        res["regime_spy"][f"{reg}_h{h}"] = series_stats(ser, h)

json.dump(res, open(f"{OUT}/res_p1.json", "w"), indent=1, default=str)


def fmt(st):
    return f"n={st['n']:3d} IC={st['mean']:+.3f} sd={st['std']:.3f} hit={st['hit']:.0%} tNW={st['t_nw']:+.2f} tNO={st['t_nonov']:+.2f}(n={st['n_nonov']})"


print("days", res["days"], res["first"], res["last"], "names/day", round(res["names_per_day"], 1),
      "recon agreement", round(res["recon_rank_agreement_mean"], 3), round(res["recon_rank_agreement_min"], 3), "missing", missing_cal)
print("== composite IC")
for k, v in res["ic"].items():
    print(f"{k:14s}", fmt(v))
print("== buckets (excess vs SPY, mean per-day)")
for h, v in res["quint"].items():
    print(h, "Q:", {q: round(x * 100, 2) for q, x in v["quint_excess"].items()}, "Q5-Q1", f"{v['q5_q1']['mean']*100:+.2f}% tNW={v['q5_q1']['t_nw']:+.2f} tNO={v['q5_q1']['t_nonov']:+.2f}")
    print(h, "T:", {q: round(x * 100, 2) for q, x in v["terc_excess"].items()}, "T3-T1", f"{v['t3_t1']['mean']*100:+.2f}% tNW={v['t3_t1']['t_nw']:+.2f} tNO={v['t3_t1']['t_nonov']:+.2f}")
print("== BUY / SHORT / HOLD excess")
for lab in ["buy", "short", "hold"]:
    for h, st in res[lab].items():
        extra = f" pooledN={st.get('pooled_n')} pooledX={st.get('pooled_mean_excess', float('nan'))*100:+.2f}% raw={st.get('pooled_mean_raw', float('nan'))*100:+.2f}% hit={st.get('hit_excess_pooled')}" if lab != "hold" else ""
        print(lab, h, f"days={st['n']} meanX={st['mean']*100:+.2f}% tNW={st['t_nw']:+.2f} tNO={st['t_nonov']:+.2f}(n={st['n_nonov']})" + extra)
print("== factor IC")
for k, v in res["factor"].items():
    print(f"{k:22s}", fmt(v))
print("nonzero share", {k: round(v, 2) for k, v in res["factor_nonzero_share"].items()})
print("== stability (half split at", half, ")")
for k, v in res["stab"].items():
    print(f"{k:16s}", fmt(v))
print("== regime -> SPY fwd")
for k, v in res["regime_spy"].items():
    print(f"{k:16s} n={v['n']} mean={v['mean']*100:+.2f}% tNW={v['t_nw']:+.2f}")
