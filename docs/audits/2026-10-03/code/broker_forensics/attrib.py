import json, requests, time, datetime as dt
from collections import defaultdict
ROOT="."; S="/tmp/audit_2026_10_03/broker"
P=json.load(open(f"{ROOT}/config/portfolios.json"))['portfolio_1']
H={"APCA-API-KEY-ID":P['api_key'],"APCA-API-SECRET-KEY":P['api_secret']}
def bars(sym):
    out=[];tok=None
    while True:
        p={"timeframe":"1Day","start":"2026-05-20","end":"2026-10-03","adjustment":"raw","feed":"iex","limit":10000}
        if tok:p['page_token']=tok
        for i in range(5):
            r=requests.get(f"https://data.alpaca.markets/v2/stocks/{sym}/bars",headers=H,params=p,timeout=30)
            if r.status_code==429: time.sleep(2);continue
            break
        if r.status_code!=200: return {}
        j=r.json(); out+=j.get('bars') or []; tok=j.get('next_page_token')
        if not tok:break
    return {b['t'][:10]:b['c'] for b in out}
cache_f=f"{S}/closes_raw.json"
try: closes=json.load(open(cache_f))
except: closes={}
syms=set(['SPY','BIL'])
for pid in ['portfolio_1','portfolio_2','portfolio_3']:
    for f in json.load(open(f"{S}/{pid}.json"))['fills']: syms.add(f['symbol'])
for s in sorted(syms):
    if s not in closes and '/' not in s: closes[s]=bars(s)
json.dump(closes,open(cache_f,"w"))
spy=closes['SPY']; days=sorted(spy)
res={}
for pid in ['portfolio_1','portfolio_2','portfolio_3']:
    B=json.load(open(f"{S}/{pid}.json"))
    h=B['history']
    eq={(dt.datetime.utcfromtimestamp(t)-dt.timedelta(hours=4)).strftime('%Y-%m-%d'):e for t,e in zip(h['timestamp'],h['equity']) if e}
    fills=sorted(B['fills'],key=lambda x:x['transaction_time'])
    pos=defaultdict(float); fi=0
    eod={}
    for d in days:
        while fi<len(fills) and fills[fi]['transaction_time'][:10]<=d:
            f=fills[fi]; q=float(f['qty']); pos[f['symbol']]+= q if f['side']=='buy' else -q; fi+=1
        eod[d]=dict(pos)
    rows=[]; prev=None
    missing=set()
    for d in days:
        if d not in eq or d<'2026-05-27': prev=None if d not in eq else d; continue
        mv=0
        for s,q in eod[d].items():
            if abs(q)<1e-9: continue
            c=closes.get(s,{}).get(d)
            if c is None: missing.add(s); continue
            mv+=q*c
        rows.append((d,eq[d],mv))
    # daily decomposition
    sel=cash=resid=0; tot_p=tot_b=0; wsum=0
    out_rows=[]
    for i in range(1,len(rows)):
        d,e,mv=rows[i]; d0,e0,mv0=rows[i-1]
        rp=e/e0-1; rb=spy[d]/spy[d0]-1
        w=mv0/e0
        # holding return of yesterday's book
        hp=0
        for s,q in eod[d0].items():
            if abs(q)<1e-9: continue
            c0=closes.get(s,{}).get(d0); c1=closes.get(s,{}).get(d)
            if c0 and c1: hp+=q*(c1-c0)
        rinv=hp/mv0 if mv0 else 0
        rc=0.04/252
        s_=w*(rinv-rb); c_=(1-w)*(rc-rb); r_=rp-(w*rinv+(1-w)*rc)
        sel+=s_; cash+=c_; resid+=r_; wsum+=w
        out_rows.append((d,round(w,3)))
    n=len(rows)-1
    res[pid]=dict(selection=sel,cash_drag=cash,trading_residual=resid,avg_invested=wsum/n,n=n,missing=sorted(missing))
    print(f"{pid}: avg invested {wsum/n*100:.0f}% | sum daily excess decomposition: selection {sel*100:+.2f}pp, cash/beta drag {cash*100:+.2f}pp, trading/execution residual {resid*100:+.2f}pp => total {(sel+cash+resid)*100:+.2f}pp | missing prices {sorted(missing)[:8]}")
    # invested weight by month
    m=defaultdict(list)
    for d,w in out_rows: m[d[:7]].append(w)
    print("   avg invested by month:",{k:round(sum(v)/len(v)*100) for k,v in sorted(m.items())})
json.dump(res,open(f"{S}/attrib.json","w"),indent=1)
