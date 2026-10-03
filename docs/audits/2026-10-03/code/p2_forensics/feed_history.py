import json, subprocess, collections, datetime as dt
REPO="."
def git(*a):
    return subprocess.run(["git","-C",REPO,*a],capture_output=True,text=True).stdout
def versions(path, since="2026-06-20"):
    out=git("log","--since="+since,"--format=%H %cI %s","--",path)
    rows=[]
    for line in out.strip().splitlines():
        h,ts,*s=line.split(" ",2)
        try:
            content=json.loads(git("show",f"{h}:{path}"))
        except Exception as e:
            content=None
        rows.append((ts,h,s[0] if s else "",content))
    return list(reversed(rows))
skips=versions("political-copy-bot/data/p2_skipped_disclosures.json")
conf=versions("political-copy-bot/data/strategy_conformance.json")
seen=versions("political-copy-bot/data/house_fd_seen.json")
out={"skips":[],"conf":[],"seen":[]}
for ts,h,s,c in skips:
    out["skips"].append({"commit_ts":ts,"label":s,"ts":c.get("timestamp") if c else None,"evaluated":c.get("processed_evaluated") if c else None,"copied":c.get("copied") if c else None,"skipped":c.get("skipped") if c else None,"skips":c.get("skips") if c else None})
for ts,h,s,c in conf:
    det=[x for x in (c or {}).get("checks",[]) if x.get("name")=="disclosure_feed_reachable"]
    out["conf"].append({"commit_ts":ts,"ts":(c or {}).get("timestamp"),"conformant":(c or {}).get("conformant"),"feed":det[0] if det else None})
prev=set()
for ts,h,s,c in seen:
    ids=set((c or {}).get("doc_ids",[]))
    out["seen"].append({"commit_ts":ts,"n":len(ids),"new":sorted(ids-prev)})
    prev=ids
json.dump(out,open("/tmp/audit_2026_10_03/agentC/feed_history.json","w"),indent=1)
print(len(out["skips"]),len(out["conf"]),len(out["seen"]))
