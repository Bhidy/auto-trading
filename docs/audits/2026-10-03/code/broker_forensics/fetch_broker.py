import json, requests, time, sys
ROOT="."
OUT=sys.argv[1]
P=json.load(open(f"{ROOT}/config/portfolios.json"))
def get(pid, path, params=None, data=False):
    c=P[pid]; base=c['data_url'] if data else c['base_url']
    h={"APCA-API-KEY-ID":c['api_key'],"APCA-API-SECRET-KEY":c['api_secret']}
    for i in range(5):
        r=requests.get(base+path,headers=h,params=params,timeout=30)
        if r.status_code==429: time.sleep(2*(i+1)); continue
        r.raise_for_status(); return r.json()
    r.raise_for_status()
for pid in P:
    out={}
    out['account']=get(pid,'/v2/account')
    out['positions']=get(pid,'/v2/positions')
    out['history']=get(pid,'/v2/account/portfolio/history',{"period":"1A","timeframe":"1D","intraday_reporting":"market_hours","pnl_reset":"no_reset"})
    acts=[]; page=None
    while True:
        p={"activity_types":"FILL","direction":"asc","page_size":100}
        if page: p['page_token']=page
        a=get(pid,'/v2/account/activities',p)
        if not a: break
        acts+=a; page=a[-1]['id']
        if len(a)<100: break
    out['fills']=acts
    nf=[]; page=None
    while True:
        p={"direction":"asc","page_size":100}
        if page: p['page_token']=page
        a=get(pid,'/v2/account/activities',p)
        if not a: break
        nf+=[x for x in a if x.get('activity_type')!='FILL']; page=a[-1]['id']
        if len(a)<100: break
    out['nonfill']=nf
    orders=[]; until=None
    while True:
        p={"status":"all","limit":500,"direction":"desc","nested":"false"}
        if until: p['until']=until
        o=get(pid,'/v2/orders',p)
        if not o: break
        orders+=o
        if len(o)<500: break
        until=o[-1]['submitted_at']
    # dedupe
    seen=set(); od=[]
    for o in orders:
        if o['id'] in seen: continue
        seen.add(o['id']); od.append(o)
    out['orders']=od
    json.dump(out,open(f"{OUT}/{pid}.json","w"))
    a=out['account']
    print(pid, "equity",a['equity'],"cash",a['cash'],"long_mv",a.get('long_market_value'),"short_mv",a.get('short_market_value'),"status",a['status'],"trading_blocked",a['trading_blocked'],"account_blocked",a['account_blocked'],"| fills",len(acts),"nonfill",len(nf),"orders",len(od),"positions",len(out['positions']))
# SPY + benchmark bars
bars={}
for sym in ["SPY","QQQ","IWM","RSP","AGG","BIL"]:
    allb=[]; tok=None
    while True:
        p={"timeframe":"1Day","start":"2026-05-01","end":"2026-10-03","adjustment":"all","feed":"iex","limit":10000}
        if tok: p['page_token']=tok
        r=get('portfolio_1',f'/v2/stocks/{sym}/bars',p,data=True)
        allb+=r.get('bars') or []; tok=r.get('next_page_token')
        if not tok: break
    bars[sym]=allb
json.dump(bars,open(f"{OUT}/bench_bars.json","w"))
print({k:len(v) for k,v in bars.items()}, bars['SPY'][0]['t'], bars['SPY'][-1]['t'])
