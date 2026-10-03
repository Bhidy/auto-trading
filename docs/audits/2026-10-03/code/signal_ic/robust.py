import json, runpy, io, contextlib
from common import t_simple, mean
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    g=runpy.run_path('p1.py')
ic_series=g['ic_series']; days=g['days']; rows=g['rows']; DEF=g['DEFENSIVE']
def offs(series,h):
    vals=[v for _,v in series]
    ts=[t_simple(vals[o::h]) for o in range(h)]
    ms=[mean(vals[o::h]) for o in range(h)]
    ts=[t for t in ts if t==t]
    return round(mean(ts),2), round(min(ts),2), round(max(ts),2), len(vals[0::h])
for h in [5,10,21]:
    print('composite IC all', h, offs(ic_series('score',h),h))
    print('composite IC risk', h, offs(ic_series('score',h,lambda r:r['sym'] not in DEF),h))
    for k in ['momentum','rel_strength','trend','rsi','c_mom3m','c_px_vs_ma50']:
        print('  factor',k,h,offs(ic_series(k,h),h))
    for key in ['BUY','SHORT']:
        ser=[]
        for d in days:
            v=[r[f'x{h}'] for r in rows[d] if r['signal']==key and r[f'x{h}'] is not None]
            if v: ser.append((d,mean(v)))
        print('  ',key,'excess',h,offs(ser,h), 'mean%', round(mean([v for _,v in ser])*100,2))
