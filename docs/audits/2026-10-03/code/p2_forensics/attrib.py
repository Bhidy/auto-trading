import json, datetime as dt, collections
B=json.load(open("bars.json")); bars={s:{b['t'][:10]:b['c'] for b in v} for s,v in B.items()}
days=sorted(bars['SPY'])
br=json.load(open("../broker/portfolio_2.json"))
SLEEVE={"SPY","QQQ","DIA","IWM","XLK","XLF","XLV","XLE","XLY","XLI"}
fills=sorted(br['fills'],key=lambda f:f['transaction_time'])
fees=sum(float(a['net_amount']) for a in br['nonfill'] if a.get('activity_type')=='FEE')
other=[a for a in br['nonfill'] if a.get('activity_type') not in ('FEE','JNLC')]
print('fees',round(fees,2),'other nonfill',other)
# equity history
hh=br['history']; hist={dt.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d'):e for t,e in zip(hh['timestamp'],hh['equity'])}
def close(s,d):
    for x in reversed([y for y in days if y<=d]):
        if x in bars[s]: return bars[s][x]
qty=collections.defaultdict(float); cash=100000.0
cf={'copy':0.0,'sleeve':0.0}  # net cash invested
rows=[]
fi=0
# convert fill time to ET date: transaction_time UTC; trading hours => same date
for d in days:
    if d<'2026-05-27': continue
    while fi<len(fills) and fills[fi]['transaction_time'][:10]<=d:
        f=fills[fi]; q=float(f['qty'])*(1 if f['side']=='buy' else -1); p=float(f['price'])
        qty[f['symbol']]+=q; cash-=q*p
        cf['sleeve' if f['symbol'] in SLEEVE else 'copy']+=q*p
        fi+=1
    mv={'copy':0.0,'sleeve':0.0}
    for s,q in qty.items():
        if abs(q)<1e-9: continue
        mv['sleeve' if s in SLEEVE else 'copy']+=q*close(s,d)
    eq=cash+mv['copy']+mv['sleeve']
    rows.append(dict(d=d,cash=cash,copy_mv=mv['copy'],sleeve_mv=mv['sleeve'],eq=eq,copy_pnl=mv['copy']-cf['copy'],sleeve_pnl=mv['sleeve']-cf['sleeve']))
last=rows[-1]
print('final recon eq',round(last['eq'],2),'+fees',round(last['eq']+fees,2),'broker',br['account']['equity'])
print('copy P&L (realized+unrealized)',round(last['copy_pnl'],2),' sleeve P&L',round(last['sleeve_pnl'],2),' fees',round(fees,2))
# monthly composition snapshot
snap=['2026-05-29','2026-06-02','2026-06-30','2026-07-02','2026-07-31','2026-08-31','2026-09-30','2026-10-02']
for r in rows:
    if r['d'] in snap or r['d']==rows[-1]['d']:
        e=r['eq']; print(r['d'], 'eq',round(e),' copy',round(r['copy_mv']),f"({r['copy_mv']/e*100:.1f}%)",' sleeve',round(r['sleeve_mv']),f"({r['sleeve_mv']/e*100:.1f}%)",' cash',round(r['cash']),f"({r['cash']/e*100:.1f}%)", ' cum copyPnL',round(r['copy_pnl']),' cum sleevePnL',round(r['sleeve_pnl']), ' broker_eq', hist.get(r['d']))
# avg weights
import statistics as st
print('avg copy wt %',round(st.mean(r['copy_mv']/r['eq'] for r in rows)*100,2),' avg sleeve wt %',round(st.mean(r['sleeve_mv']/r['eq'] for r in rows)*100,2), ' avg cash %', round(st.mean(r['cash']/r['eq'] for r in rows)*100,2))
# sub-period attribution since Jul 3 close
base=[r for r in rows if r['d']<='2026-07-03'][-1]
print('since', base['d'], 'copy pnl', round(last['copy_pnl']-base['copy_pnl'],2), 'sleeve pnl', round(last['sleeve_pnl']-base['sleeve_pnl'],2), 'eq chg', round(last['eq']-base['eq'],2))
# avg capital deployed copy since Jul 3
post=[r for r in rows if r['d']>base['d']]
print('post avg copy MV', round(st.mean(r['copy_mv'] for r in post)), 'avg sleeve MV', round(st.mean(r['sleeve_mv'] for r in post)))
# max diff vs broker history
diffs=[(r['d'],round(r['eq']-hist[r['d']],2)) for r in rows if r['d'] in hist]
print('max |model-broker| eq diff', max(diffs,key=lambda x:abs(x[1])))
json.dump(rows,open("attrib_daily.json","w"))
