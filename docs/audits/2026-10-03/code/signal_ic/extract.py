"""Reconstruct one point-in-time snapshot per trading day from git history (read-only)."""
import json
import subprocess
from datetime import datetime, timezone
from collections import defaultdict

REPO = "."
OUT = "/tmp/audit_2026_10_03/agentE"


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, check=True).stdout


def commits(path):
    out = []
    for line in git("log", "--format=%H %cI", "--", path).splitlines():
        h, ts = line.split()
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        out.append((dt, h))
    out.sort()
    return out


def show(h, path):
    try:
        return json.loads(git("show", f"{h}:{path}"))
    except Exception:
        return None


def snapshots(path):
    """For each UTC day: first commit at/after 13:30 UTC whose internal timestamp is that day."""
    by_day = defaultdict(list)
    for dt, h in commits(path):
        by_day[dt.date()].append((dt, h))
    res = {}
    stats = {"days_with_commits": 0, "chosen": 0, "stale_rejected": 0}
    for day, lst in sorted(by_day.items()):
        stats["days_with_commits"] += 1
        for dt, h in lst:
            if (dt.hour, dt.minute) < (13, 30):
                continue
            d = show(h, path)
            if not isinstance(d, dict) or not d.get("timestamp"):
                continue
            its = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
            if its.date() != day:
                stats["stale_rejected"] += 1
                continue
            if its > dt:  # impossible but guard
                continue
            res[str(day)] = {"commit": h, "commit_time": dt.isoformat(), "internal_ts": its.isoformat(), "data": d}
            stats["chosen"] += 1
            break
    return res, stats


if __name__ == "__main__":
    allstats = {}
    for name, path in [("p1", "data/signals.json"),
                       ("p3", "event-driven-bot/data/signals.json"),
                       ("p3news", "event-driven-bot/data/news_signals.json")]:
        snaps, st = snapshots(path)
        allstats[name] = st
        # attach point-in-time params / watchlist from the same commit
        for day, s in snaps.items():
            if name == "p1":
                s["params"] = show(s["commit"], "data/strategy_params.json")
            if name == "p3":
                s["watchlist"] = show(s["commit"], "event-driven-bot/data/watchlist.json")
                s["limits"] = show(s["commit"], "event-driven-bot/config/risk_limits.json")
            if name == "p3news":
                s["watchlist"] = show(s["commit"], "event-driven-bot/data/watchlist.json")
        json.dump(snaps, open(f"{OUT}/snap_{name}.json", "w"))
        print(name, st, "first", min(snaps) if snaps else None, "last", max(snaps) if snaps else None)
    json.dump(allstats, open(f"{OUT}/snap_stats.json", "w"), indent=2)
