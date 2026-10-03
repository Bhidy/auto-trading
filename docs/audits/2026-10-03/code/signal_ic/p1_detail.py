import json
from collections import defaultdict
from common import OUT, fwd, mean, CIDX
snaps=json.load(open(f"{OUT}/snap_p1.json"))
days=sorted(snaps)
short=defaultdict(list); buy=defaultdict(list); sc=defaultdict(list)
for d in days:
    for x in snaps[d]['data']['signals']:
        if x.get('score') is None: continue
        r=fwd(x['symbol'],d,10,excess=True)
        sc[x['symbol']].append(x['score'])
        if x['signal']=='SHORT': short[x['symbol']].append((d,r))
        if x['signal']=='BUY' and r is not None: buy[x['symbol']].append(r)
print("SHORT by symbol (n, mean 10d excess, first/last date)")
for s,v in short.items():
    vv=[r for _,r in v if r is not None]
    print(s,len(v),f"{mean(vv)*100:+.2f}%" if vv else None, v[0][0], v[-1][0])
print("BUY by symbol (n, mean 10d excess)")
for s,v in sorted(buy.items(), key=lambda kv:-len(kv[1])):
    print(s,len(v),f"{mean(v)*100:+.2f}%")
print("avg score by symbol")
for s,v in sorted(sc.items(), key=lambda kv:-mean(kv[1])):
    print(s, round(mean(v),3), end='; ')
print()
# per-symbol avg 21d excess over whole window to see what drove cross-section
for s in sorted(sc):
    v=[fwd(s,d,21,excess=True) for d in days]; v=[x for x in v if x is not None]
    print(s, f"{mean(v)*100:+.2f}%", end='; ')
print()
# same-day close entry sensitivity for BUY h=5 : close(t)->open(t+1+5)? skip
