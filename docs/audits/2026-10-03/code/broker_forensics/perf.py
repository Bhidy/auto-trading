import json, math, datetime as dt
S="/tmp/audit_2026_10_03/broker"
B=json.load(open(f"{S}/bench_bars.json"))
def series(sym): return {b['t'][:10]:b['c'] for b in B[sym]}
spy=series('SPY'); bil=series('BIL'); agg=series('AGG')
def mean(x): return sum(x)/len(x)
def sd(x):
    m=mean(x); return math.sqrt(sum((v-m)**2 for v in x)/(len(x)-1))
out={}
for pid in ['portfolio_1','portfolio_2','portfolio_3']:
    d=json.load(open(f"{S}/{pid}.json"))
    h=d['history']
    ts=[(dt.datetime.utcfromtimestamp(t)-dt.timedelta(hours=4)).strftime('%Y-%m-%d') for t in h['timestamp']]
    eq=h['equity']
    pts=[(t,e) for t,e in zip(ts,eq) if e and e>0]
    # find first day equity materially deployed -> inception: first nonzero
    print(pid,"history points",len(pts),"first",pts[0],"last",pts[-1])
    # align with spy
    al=[(t,e,spy[t]) for t,e in pts if t in spy]
    # flows: check deposits in nonfill (CSD/JNLC)
    flows=[a for a in d['nonfill'] if a['activity_type'] in ('CSD','CSW','JNLC','JNLS','TRANS')]
    print("  cash flows:",[(f['activity_type'],f.get('date'),f.get('net_amount')) for f in flows][:5])
    r=[al[i][1]/al[i-1][1]-1 for i in range(1,len(al))]
    rb=[al[i][2]/al[i-1][2]-1 for i in range(1,len(al))]
    n=len(r)
    tot=al[-1][1]/al[0][1]-1; btot=al[-1][2]/al[0][2]-1
    cov=sum((a-mean(r))*(b-mean(rb)) for a,b in zip(r,rb))/(n-1)
    beta=cov/sd(rb)**2
    active=[a-b for a,b in zip(r,rb)]
    te=sd(active)*math.sqrt(252)
    ann=(1+tot)**(252/n)-1; bann=(1+btot)**(252/n)-1
    vol=sd(r)*math.sqrt(252)
    sharpe=mean(r)/sd(r)*math.sqrt(252)
    alpha_d=mean(r)-beta*mean(rb)
    ir=mean(active)/sd(active)*math.sqrt(252)
    # maxdd
    pk=-1;mdd=0
    for _,e,_ in al:
        pk=max(pk,e); mdd=min(mdd,e/pk-1)
    up=[(a,b) for a,b in zip(r,rb) if b>0]; dn=[(a,b) for a,b in zip(r,rb) if b<0]
    upc=sum(a for a,b in up)/sum(b for a,b in up); dnc=sum(a for a,b in dn)/sum(b for a,b in dn)
    print(f"  window {al[0][0]}..{al[-1][0]} n={n} | port {tot*100:.2f}% SPY {btot*100:.2f}% excess {(tot-btot)*100:.2f}pp | beta {beta:.2f} vol {vol*100:.1f}% sharpe {sharpe:.2f} TE {te*100:.1f}% IR {ir:.2f} alpha_ann {alpha_d*252*100:.1f}% maxDD {mdd*100:.2f}% upcap {upc:.2f} dncap {dnc:.2f}")
    # monthly
    months={}
    for t,e,s in al: months.setdefault(t[:7],[]).append((e,s))
    prev=None
    row=[]
    for m in sorted(months):
        e1,s1=months[m][-1]
        if prev: row.append(f"{m}: {((e1/prev[0])-1)*100:+.2f}% vs SPY {((s1/prev[1])-1)*100:+.2f}%")
        prev=(e1,s1)
    print("  monthly:", " | ".join(row))
    out[pid]=dict(start=al[0][0],end=al[-1][0],ret=tot,spy=btot,beta=beta,te=te,ir=ir,maxdd=mdd,sharpe=sharpe,n=n)
json.dump(out,open(f"{S}/perf_summary.json","w"),indent=1)
