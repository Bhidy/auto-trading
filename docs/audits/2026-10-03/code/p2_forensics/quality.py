import json, datetime as dt, statistics as st, math
B=json.load(open("bars.json"))
bars={s:{b['t'][:10]:b for b in v} for s,v in B.items()}
days=sorted(bars['SPY'])
def px(s,d,k='c'):
    # bar on or before d
    ds=[x for x in days if x<=d]
    for x in reversed(ds):
        if x in bars[s]: return bars[s][x][k]
def tidx(d): return max(i for i,x in enumerate(days) if x<=d)
def tdays(a,b): return tidx(b)-tidx(a)
broker=json.load(open("../broker/portfolio_2.json"))
fills=broker['fills']
pos={p['symbol']:p for p in broker['positions']}
# copy lots: (sym, pol, txn, filing, entry_date, entry_px, qty, exit_date, exit_px, reason)
rt=json.load(open("../broker/roundtrips.json"))['portfolio_2']['trades']
meta={ # txn, filing (None=unknown), politician
 'TER':('2026-05-11',None,'McCaul'),'P':('2026-05-11',None,'McCaul'),'WDAY':('2026-05-11',None,'McCaul'),'INTU':('2026-05-11',None,'McCaul'),
 'HD':('2026-05-08',None,'Taylor'),'PG@2026-05-27':('2026-05-08',None,'Taylor'),'T':('2026-05-15',None,'Taylor'),'MEDP':('2026-05-15',None,'Taylor'),'PH':('2026-05-15',None,'Taylor'),
 'PANW':('2026-07-16','2026-08-10','Gottheimer'),'PG@2026-08-24':('2026-08-11','2026-08-20','Taylor'),'PG@2026-09-21':('2026-09-08','2026-09-17','Taylor'),
 'KR':('2026-07-24','2026-08-06','Taylor'),'CB':('2026-08-31','2026-09-25','Hern'),'KO':('2026-08-31','2026-09-25','Hern')}
# aggregate roundtrips per (symbol, entry)
agg={}
for x in rt:
    k=(x['symbol'],x['entry'])
    a=agg.setdefault(k,{'qty':0,'pnl':0,'notional':0,'exits':[], 'reasons':set()})
    a['qty']+=x['qty']; a['pnl']+=x['pnl']; a['notional']+=x['notional']; a['exits'].append(x['exit']); a['reasons'].add(x.get('exit_reason') or 'stop/tp(pre-D7)')
rows=[]
for (s,e),a in agg.items():
    key = s if s in meta else f"{s}@{e}"
    rows.append((s,e,max(a['exits']),a['qty'],a['pnl'],a['notional'],'/'.join(sorted(a['reasons'])),key))
for s in ('KR','CB','KO'):
    p=pos[s]; e={'KR':'2026-08-10','CB':'2026-09-29','KO':'2026-09-29'}[s]
    rows.append((s,e,'OPEN(2026-10-02)',float(p['qty']),float(p['unrealized_pl']),float(p['cost_basis']),'open',s))
reasonfix={'P':'stop -12%','WDAY':'TP 25%','T':'stop -8%','INTU':'stop -9%'}
out=[];ex=[]
for s,e,x,q,pnl,notional,reason,key in sorted(rows,key=lambda r:r[1]):
    txn,filing,pol=meta[key]
    entry=notional/q
    xd = '2026-10-02' if x.startswith('OPEN') else x
    ret=pnl/notional*100
    spy=(px('SPY',xd,'vw')/px('SPY',e,'vw')-1)*100
    tx_px=px(s,txn,'c')
    pre=(entry/tx_px-1)*100
    lag=(dt.date.fromisoformat(e)-dt.date.fromisoformat(txn)).days
    # spec counterfactual: 63 trading-day hold from entry
    i63=min(tidx(e)+63,len(days)-1); d63=days[i63]
    r63=(px(s,d63,'c')/entry-1)*100; s63=(px('SPY',d63,'c')/px('SPY',e,'vw')-1)*100
    r=dict(sym=s,pol=pol,txn=txn,filing=filing,entry=e,exit=x[:10] if not x.startswith('OPEN') else 'open',lag_cd=lag,
           pre_entry_move_pct=round(pre,2),hold_td=tdays(e,xd),reason=reason if reason!='stop/tp(pre-D7)' else reasonfix.get(s,reason),
           ret_pct=round(ret,2),spy_pct=round(spy,2),excess_pct=round(ret-spy,2),pnl=round(pnl,2),
           cf63_end=d63,cf63_excess=round(r63-s63,2), cf63_complete=(tidx(e)+63<=len(days)-1))
    out.append(r)
for r in out: print(r)
ex=[r['excess_pct'] for r in out]
print('n',len(ex),'mean excess',round(st.mean(ex),2),'median',round(st.median(ex),2),'sd',round(st.stdev(ex),2),'t',round(st.mean(ex)/(st.stdev(ex)/math.sqrt(len(ex))),2), 'win', sum(1 for v in ex if v>0))
post=[r for r in out if r['entry']>='2026-07-04']
pe=[r['excess_pct'] for r in post]
print('post-Jul4 n',len(pe),'mean',round(st.mean(pe),2), 'pnl', round(sum(r['pnl'] for r in post),2))
pre=[r for r in out if r['entry']<'2026-07-04']
print('pre n',len(pre),'pnl',round(sum(r['pnl'] for r in pre),2))
cf=[r['cf63_excess'] for r in out if r['cf63_complete']]
print('cf63 complete n',len(cf),'mean',round(st.mean(cf),2), 'live excess same names mean', round(st.mean([r['excess_pct'] for r in out if r['cf63_complete']]),2))
# unfilled counterfactual
for s in ('DHR','SPGI','MA','PGR'):
    e='2026-05-27'; i63=tidx(e)+63; d63=days[i63]
    r63=(px(s,d63,'c')/px(s,e,'vw')-1)*100; s63=(px('SPY',d63,'c')/px('SPY',e,'vw')-1)*100
    print('unfilled',s,'63d ret',round(r63,2),'excess',round(r63-s63,2),'end',d63)
print('lag stats post', [r['lag_cd'] for r in post], 'filing->entry', [ (dt.date.fromisoformat(r['entry'])-dt.date.fromisoformat(r['filing'])).days for r in post])
json.dump(out,open("copy_quality.json","w"),indent=1)
