import json
from collections import defaultdict
S="/tmp/audit_2026_10_03"
R=json.load(open(f"{S}/broker/roundtrips.json"))
def stats(ts):
    if not ts: return None
    w=[t for t in ts if t['pnl']>0]; l=[t for t in ts if t['pnl']<=0]
    gw=sum(t['pnl'] for t in w); gl=-sum(t['pnl'] for t in l)
    aw=gw/len(w) if w else 0; al=gl/len(l) if l else 0
    awr=sum(t['ret'] for t in w)/len(w) if w else 0; alr=-sum(t['ret'] for t in l)/len(l) if l else 0
    return dict(n=len(ts),win=len(w)/len(ts),pnl=round(gw-gl,2),pf=round(gw/gl,2) if gl else None,avg_w=round(aw,1),avg_l=round(al,1),avg_w_pct=round(awr*100,2),avg_l_pct=round(alr*100,2),payoff=round(aw/al,2) if al else None,exp=round((gw-gl)/len(ts),1),exp_pct=round(sum(t['ret'] for t in ts)/len(ts)*100,2),hold=round(sum(t['hold'] for t in ts)/len(ts),1))
def show(label,s):
    if s: print(f"  {label:34s} n={s['n']:3d} win={s['win']*100:4.0f}% PnL={s['pnl']:>9.2f} PF={s['pf']} avgW={s['avg_w_pct']}% avgL={s['avg_l_pct']}% payoff={s['payoff']} E/trade={s['exp_pct']}% hold={s['hold']}d")
for pid,v in R.items():
    T=v['trades']; print(f"\n===== {pid}  (round trips={len(T)})")
    show("ALL",stats(T))
    for key in ['order_class','exit_reason','dir']:
        g=defaultdict(list)
        for t in T: g[str(t.get(key))].append(t)
        print(f" by {key}:")
        for k in sorted(g,key=lambda k:-len(g[k])): show(k,stats(g[k]))
    g=defaultdict(list)
    for t in T: g[t['exit'][:7]].append(t)
    print(" by exit month:")
    for k in sorted(g): show(k,stats(g[k]))
    g=defaultdict(list)
    for t in T:
        h=t['hold']; b='0-1d' if h<=1 else '2-5d' if h<=5 else '6-20d' if h<=20 else '21-60d' if h<=60 else '>60d'
        g[b].append(t)
    print(" by holding period:")
    for k in ['0-1d','2-5d','6-20d','21-60d','>60d']: show(k,stats(g.get(k,[])))
