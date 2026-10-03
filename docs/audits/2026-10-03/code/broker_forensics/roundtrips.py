import json, datetime as dt
from collections import defaultdict, deque
ROOT="."
S="/tmp/audit_2026_10_03/broker"
LOGS={'portfolio_1':f"{ROOT}/data/trade_log.json",'portfolio_2':f"{ROOT}/political-copy-bot/data/trade_log.json",'portfolio_3':f"{ROOT}/event-driven-bot/data/trade_log.json"}
def d(s): return s[:10]
allrt={}
for pid in LOGS:
    B=json.load(open(f"{S}/{pid}.json"))
    fills=sorted(B['fills'],key=lambda x:x['transaction_time'])
    # orders by id for client_order_id
    oid={o['id']:o for o in B['orders']}
    lots=defaultdict(deque)  # symbol -> deque of [qty(signed), px, time, coid]
    rts=[]
    for f in fills:
        sym=f['symbol']; q=float(f['qty']); px=float(f['price']); side=f['side']
        sq= q if side=='buy' else -q
        coid=(oid.get(f.get('order_id')) or {}).get('client_order_id','')
        dq=lots[sym]
        while sq!=0 and dq and (dq[0][0]>0)!=(sq>0):
            lq,lpx,lt,lc=dq[0]
            m=min(abs(lq),abs(sq))
            direction= 1 if lq>0 else -1
            pnl=(px-lpx)*m*direction
            rts.append(dict(symbol=sym,dir='long' if direction>0 else 'short',qty=m,entry_px=lpx,exit_px=px,entry_t=lt,exit_t=f['transaction_time'],pnl=pnl,ret=(px/lpx-1)*direction,entry_coid=lc,exit_coid=coid,notional=m*lpx))
            lq_new = lq - m*direction
            sq = sq + m*direction
            if abs(lq_new)<1e-9: dq.popleft()
            else: dq[0][0]=lq_new
        if abs(sq)>1e-9: dq.append([sq,px,f['transaction_time'],coid])
    # aggregate round trips by (symbol, entry day, exit day) to collapse partial fills into "trades"
    agg={}
    for r in rts:
        k=(r['symbol'],d(r['entry_t']),d(r['exit_t']),r['dir'])
        a=agg.setdefault(k,dict(symbol=r['symbol'],dir=r['dir'],entry=d(r['entry_t']),exit=d(r['exit_t']),qty=0,pnl=0,notional=0,entry_coid=r['entry_coid'],exit_coid=r['exit_coid']))
        a['qty']+=r['qty']; a['pnl']+=r['pnl']; a['notional']+=r['notional']
    trades=list(agg.values())
    for t in trades:
        t['ret']=t['pnl']/t['notional'] if t['notional'] else 0
        t['hold']=(dt.date.fromisoformat(t['exit'])-dt.date.fromisoformat(t['entry'])).days
    # join trade log for exit reason/class
    TL=json.load(open(LOGS[pid])); TL=TL if isinstance(TL,list) else TL.get('trades',[])
    for t in trades:
        best=None
        for x in TL:
            if x.get('symbol')!=t['symbol']: continue
            xe=str(x.get('exit_timestamp') or x.get('exit_date') or '')[:10]
            if xe==t['exit']: best=x; break
        t['exit_reason']=(best or {}).get('exit_reason') or (best or {}).get('close_reason')
        t['order_class']=(best or {}).get('order_class') or (best or {}).get('bucket') or (best or {}).get('tranche') or (best or {}).get('strategy')
    open_lots={s:sum(l[0] for l in dq) for s,dq in lots.items() if dq}
    allrt[pid]=dict(trades=trades,open=open_lots)
    pos={p['symbol']:float(p['qty']) for p in B['positions']}
    mism={s:(open_lots.get(s,0),pos.get(s,0)) for s in set(open_lots)|set(pos) if abs(open_lots.get(s,0)-pos.get(s,0))>1e-6}
    print(pid,"fills",len(fills),"round-trip trades",len(trades),"| FIFO open vs broker positions mismatch:",mism)
json.dump(allrt,open(f"{S}/roundtrips.json","w"),indent=1,default=str)
