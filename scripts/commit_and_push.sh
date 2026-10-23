#!/usr/bin/env bash
#
# commit_and_push.sh — conflict-proof state commit/push for concurrent CI jobs.
#
# Usage: commit_and_push.sh "<commit label>" <owned_path> [<owned_path> ...]
#   e.g. commit_and_push.sh "P2: monitor" political-copy-bot/data political-copy-bot/journal
#
# WHY THIS EXISTS (do not revert to `git pull --rebase || retry`):
#   During market hours up to ~5 trading workflows push to `main` inside the
#   same minute. The old loop ran `git pull --rebase origin main && git push`.
#   When two jobs rewrote the same generated JSON (e.g. portfolio_state.json),
#   the rebase hit a merge conflict and LEFT THE REPO HALF-REBASED. Every later
#   retry then died with "Pulling is not possible because you have unmerged
#   files" — a guaranteed dead-lock that failed the whole run (and fired the
#   scary "Run failed" push notification) even though the trade path was fine.
#
# HOW THIS IS CONFLICT-PROOF:
#   We never merge two versions of a generated file. Instead we ALWAYS rebuild
#   our commit on top of the freshest remote:
#     1. snapshot THIS job's own freshly-generated files,
#     2. hard-reset the tree to origin/main (so every other portfolio's files
#        become the latest remote — no stale clobber),
#     3. re-apply only our owned files on top,
#     4. re-mirror everything into dashboard/ for Vercel,
#     5. commit + push; if we lost the race, loop from step 2.
#   Because step 2 discards any half-done state, a conflict can never wedge the
#   repo, and the loop converges as soon as we win a push.
#
# NEVER LET OLDER STATE OVERWRITE NEWER STATE (audit 2026-10-23 D1):
#   Step 3 used to copy our files over remote-latest unconditionally. A run
#   whose checkout was STALE (a queued Guardian dispatch checked out the commit
#   from dispatch time) therefore replaced trade_log.json rows another run had
#   committed in the meantime. Now, per owned file, we compare the remote's
#   version with the version our run STARTED from (BASE):
#     * remote unchanged since BASE  -> our file is strictly newer: overlay it.
#     * remote changed since BASE    -> 3-way JSON merge (base, ours, remote):
#         - list  : remote order kept; elements we removed are removed; elements
#                   we added are appended (trade_log rows, processed_trades ids,
#                   journal entries). If BOTH sides removed/rewrote the same
#                   base element the merge is a CONFLICT.
#         - dict with a top-level timestamp (snapshot: portfolio_state,
#                   reports, caches): the document with the LATER timestamp
#                   wins whole — a snapshot is never spliced.
#         - other dict: key-wise recursive merge; same key changed to two
#                   different values on both sides is a CONFLICT.
#       A CONFLICT (or non-JSON file) keeps the REMOTE version, prints our
#       run's delta (vs BASE) to the log so nothing is lost, pushes everything
#       else, and exits 1 so failure-alert.yml raises an issue.
#
set -uo pipefail

LABEL="${1:?commit label required}"; shift
OWNED=("$@")

git config user.name  "Auto Trading Bot"
git config user.email "bot@autotrading.local"

# The commit this job's state was derived from (Guardian + P2 sync to origin/main
# right after checkout; elsewhere it is the checkout commit itself).
BASE="$(git rev-parse HEAD)"

# --- snapshot ONLY the files THIS job changed, before we touch the tree -------
# We carry forward exactly the owned files that differ from the checkout base
# (modified or new). Files this job did NOT touch are left at remote-latest by
# the reset below — so a multi-portfolio job (guardian) can never revert a
# portfolio it didn't regenerate, and a single-portfolio job only ever writes
# its own fresh output on top of everyone else's latest.
SNAP="$(mktemp -d)"
cleanup() { rm -rf "$SNAP"; }
trap cleanup EXIT

# merge3 <base_file|""> <ours_file> <remote_file> <out_file> <basename>
# Structural 3-way JSON merge (stdlib python). Exit 0 = merged into out_file,
# exit 1 = conflict / not JSON (caller keeps the remote version).
merge3() {
  python3 - "$@" << 'PYMERGE'
import json
import sys

base_p, ours_p, theirs_p, out_p = sys.argv[1:5]
NAME = sys.argv[5] if len(sys.argv) > 5 else ""
TS_KEYS = ("timestamp", "last_updated", "updated", "generated_at")
# High-water marks are monotonic by definition: when two runs both raised a
# symbol's peak, the higher peak is the true one.
MAX_ON_CONFLICT = {"trailing_peaks.json"}


class Conflict(Exception):
    pass


def load(p):
    if not p:
        return None
    with open(p) as f:
        return json.load(f)


def canon(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def multiset(xs):
    out = {}
    for x in xs:
        out.setdefault(canon(x), []).append(x)
    return out


def merge_list(base, ours, theirs):
    """Multiset 3-way merge: per distinct element, final count =
    base - removed_by_ours - removed_by_theirs + max(added_by_ours,
    added_by_theirs). Remote order is kept; our additions are appended."""
    base = base if isinstance(base, list) else []
    b, o, t = multiset(base), multiset(ours), multiset(theirs)
    target = {}
    for k in set(b) | set(o) | set(t):
        nb, no, nt = len(b.get(k, [])), len(o.get(k, [])), len(t.get(k, []))
        rem_o, rem_t = max(0, nb - no), max(0, nb - nt)
        if rem_o and rem_t:
            # The same base element was rewritten/removed on BOTH sides (e.g.
            # the same lot closed by two runs) — no safe automatic answer.
            raise Conflict("a list element was changed on both sides")
        target[k] = nb - rem_o - rem_t + max(0, no - nb, nt - nb)
    result, have = [], {}
    for x in list(theirs) + list(ours):
        k = canon(x)
        if have.get(k, 0) < target[k]:
            result.append(x)
            have[k] = have.get(k, 0) + 1
    return result


def ts_of(d):
    for k in TS_KEYS:
        if isinstance(d, dict) and d.get(k):
            return str(d[k])
    return None


def ts_parse(s):
    """Aware UTC datetime for an ISO stamp ('Z', '+00:00', '-04:00' or naive=UTC);
    None if unparseable. String comparison of mixed offsets is WRONG (audit L1):
    '2026-10-23T11:00:00-04:00' is LATER than '2026-10-23T14:40:00+00:00'."""
    import datetime as _dt
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def ours_is_newer(to, tt):
    a, b = ts_parse(to), ts_parse(tt)
    if a is not None and b is not None:
        return a > b
    if a is not None and b is None:
        return True                    # a real timestamp beats a missing/garbage one
    if a is None and b is not None:
        return False
    return (to or "") > (tt or "")


# Halt state is STICKY (audit M1): a newer-timestamped snapshot from a run that
# started on an OLDER base must never erase a halt (or a consumed clear / an
# observation) that another run latched after that base — e.g. the monitor
# latches a kill switch at 14:30 and a trading run based on 14:00 writes 14:40
# with halted:false. Unless our side carries the governed clear record for
# exactly that halt, it is a CONFLICT (remote kept, run fails loudly).
HALT_KEYS = ("halted", "halt_reason", "halt_set_at", "halt_kind", "halt_until",
             "halt_evidence", "halt_clears_consumed", "halt_observations")


def halt_view(d):
    d = d if isinstance(d, dict) else {}
    return {k: d.get(k) for k in HALT_KEYS}


def governed_clear_of(ours, theirs):
    lh = ours.get("last_halt") if isinstance(ours, dict) else None
    return (bool(theirs.get("halted")) and not ours.get("halted")
            and isinstance(lh, dict) and lh.get("ended") == "human_clear"
            and lh.get("halt_set_at") == theirs.get("halt_set_at")
            and lh.get("halt_reason") == theirs.get("halt_reason"))


def halt_guard(base, ours, theirs):
    if not (isinstance(ours, dict) and isinstance(theirs, dict)):
        return
    if not any(k in ours or k in theirs for k in HALT_KEYS):
        return
    hb, ho, ht = halt_view(base), halt_view(ours), halt_view(theirs)
    if canon(ht) != canon(hb) and canon(ho) != canon(ht):
        if governed_clear_of(ours, theirs):
            print("  halt: remote halt cleared by OUR governed clear record — ours kept")
            return
        raise Conflict("remote halt state changed since our base (halted="
                       f"{theirs.get('halted')}, reason={theirs.get('halt_reason')!r}) "
                       "and ours would overwrite it")


def merge(base, ours, theirs):
    if canon(ours) == canon(theirs):
        return ours
    if base is not None and canon(ours) == canon(base):
        return theirs
    if base is not None and canon(theirs) == canon(base):
        return ours
    if isinstance(ours, list) and isinstance(theirs, list):
        return merge_list(base, ours, theirs)
    if isinstance(ours, dict) and isinstance(theirs, dict):
        out = {}
        b = base if isinstance(base, dict) else {}
        for k in list(theirs.keys()) + [k for k in ours if k not in theirs]:
            if k in ours and k in theirs:
                out[k] = merge(b.get(k), ours[k], theirs[k])
            elif k in theirs:
                if k in b and canon(b[k]) != canon(theirs[k]):
                    raise Conflict(f"key {k!r} deleted by us, changed remotely")
                if k not in b:
                    out[k] = theirs[k]          # remote added it
                # else: we deleted an unchanged key -> stays deleted
            else:
                if k in b and canon(b[k]) != canon(ours[k]):
                    raise Conflict(f"key {k!r} changed by us, deleted remotely")
                if k not in b:
                    out[k] = ours[k]            # we added it
        return out
    if (NAME in MAX_ON_CONFLICT and isinstance(ours, (int, float))
            and isinstance(theirs, (int, float))
            and not isinstance(ours, bool) and not isinstance(theirs, bool)):
        return max(ours, theirs)
    raise Conflict("scalar changed to different values on both sides")


# P3 allocator state (event-driven-bot/data/allocator_state.json) is a
# timestamped snapshot (newer wins whole), EXCEPT two sub-maps that are never
# allowed to lose information to a racing/stale run:
#   * "orders"      — key-wise union by client_order_id; on a shared key the
#                     record that is booked (then final, then from the winning
#                     document) is kept, so a booked flag is never un-booked;
#   * "concurrency" — the stale-checkout detector's counter: max count, newest
#                     last_at (a stale run writes it WITHOUT bumping
#                     last_updated, so it never wins the snapshot itself).
ALLOC_STATE = "allocator_state.json"
_FINAL_ORDER = {"filled", "canceled", "expired", "rejected", "replaced"}


def _order_rank(r):
    r = r if isinstance(r, dict) else {}
    return (bool(r.get("booked")), r.get("status") in _FINAL_ORDER)


def allocator_state_merge(merged, ours, theirs):
    out = dict(merged)
    oo, ot = ours.get("orders") or {}, theirs.get("orders") or {}
    if isinstance(oo, dict) and isinstance(ot, dict):
        win = out.get("orders") or {}
        orders = {}
        for k in list(ot) + [k for k in oo if k not in ot]:
            cands = [x for x in (oo.get(k), ot.get(k)) if x is not None]
            best = max(cands, key=_order_rank)
            if k in win and _order_rank(win[k]) >= _order_rank(best):
                best = win[k]
            orders[k] = best
        out["orders"] = orders
    co, ct = ours.get("concurrency"), theirs.get("concurrency")
    if isinstance(co, dict) or isinstance(ct, dict):
        co, ct = co or {}, ct or {}
        newest = co if str(co.get("last_at") or "") >= str(ct.get("last_at") or "") else ct
        out["concurrency"] = dict(newest, count=max(int(co.get("count") or 0),
                                                    int(ct.get("count") or 0)))
    return out


try:
    base = load(base_p)
    ours = load(ours_p)
    theirs = load(theirs_p)
    if isinstance(ours, dict) and isinstance(theirs, dict) and (ts_of(ours) or ts_of(theirs)):
        # Snapshot document: newest snapshot wins whole (parsed, offset-aware),
        # except that halt state is sticky (see halt_guard).
        to, tt = ts_of(ours) or "", ts_of(theirs) or ""
        merged = ours if ours_is_newer(to, tt) else theirs
        if merged is ours:
            halt_guard(base, ours, theirs)
        print(f"  snapshot: {'ours' if merged is ours else 'remote'} is newer "
              f"(ours={to or 'none'}, remote={tt or 'none'})")
        if NAME == ALLOC_STATE:
            merged = allocator_state_merge(merged, ours, theirs)
            print("  allocator_state: orders key-wise union, concurrency max")
    else:
        merged = merge(base, ours, theirs)
except Conflict as e:
    print(f"  CONFLICT: {e}")
    sys.exit(1)
except (OSError, ValueError) as e:
    print(f"  not mergeable as JSON: {e}")
    sys.exit(1)
with open(out_p, "w") as f:
    json.dump(merged, f, indent=2)
    f.write("\n")
PYMERGE
}

CHANGED=()
while IFS= read -r line; do
  [ -n "$line" ] && CHANGED+=("${line:3}")
done < <(git status --porcelain --untracked-files=all -- "${OWNED[@]}")

for f in ${CHANGED[@]+"${CHANGED[@]}"}; do
  [ -f "$f" ] || continue   # skip deletions — state/journal files are never deleted
  mkdir -p "$SNAP/$(dirname "$f")"
  cp -a "$f" "$SNAP/$f"
done

blob_of() { git rev-parse -q --verify "$1:$2" 2>/dev/null || echo "none"; }

WITHHELD=()
restore_owned() {
  # Overlay our changed files ON TOP of the reset (remote-latest) tree — but
  # only where that cannot overwrite something newer (see header).
  WITHHELD=()
  local f base_blob remote_blob base_file merged
  for f in ${CHANGED[@]+"${CHANGED[@]}"}; do
    [ -f "$SNAP/$f" ] || continue
    mkdir -p "$(dirname "$f")"
    base_blob="$(blob_of "$BASE" "$f")"
    remote_blob="$(blob_of origin/main "$f")"
    if [ "$remote_blob" = "$base_blob" ]; then
      cp -a "$SNAP/$f" "$f"                       # remote untouched since BASE
      continue
    fi
    echo "Remote changed $f since this run's base ($BASE) — 3-way merging."
    base_file=""
    if [ "$base_blob" != "none" ]; then
      base_file="$SNAP/.base/$f"; mkdir -p "$(dirname "$base_file")"
      git cat-file -p "$base_blob" > "$base_file"
    fi
    merged="$SNAP/.merged/$f"; mkdir -p "$(dirname "$merged")"
    if merge3 "$base_file" "$SNAP/$f" "$f" "$merged" "$(basename "$f")"; then
      cp "$merged" "$f"
    else
      WITHHELD+=("$f")
      echo "::warning::Withholding $f — remote has newer conflicting state. This run's delta vs base:"
      if [ -n "$base_file" ]; then
        git --no-pager diff --no-index --stat -- "$base_file" "$SNAP/$f" || true
        git --no-pager diff --no-index -U0 -- "$base_file" "$SNAP/$f" | head -400 || true
      else
        head -c 20000 "$SNAP/$f" || true
      fi
    fi
  done
}

# Atomic ledger groups (audit M2): within one data directory these files
# describe ONE accounting state — the trade log, the fill ledger that says which
# broker fills are already in it, the pending settlement queues and the
# portfolio snapshot. Pushing some without the others corrupts it (e.g. the
# ledger says "booked" while the trade-log row was withheld, so the fill can
# never be re-booked). If any member is withheld, the whole group is.
# allocator_state.json (P3 crisis_core_v1 sleeve) holds that sleeve's booked
# order flags, so it travels with trade_log.json the same way.
GROUP_FILES=" trade_log.json booked_fills.json pending_exits.json pending_entries.json portfolio_state.json allocator_state.json "
withhold_groups() {
  local w f d dirs=" " already
  for w in ${WITHHELD[@]+"${WITHHELD[@]}"}; do
    case "$GROUP_FILES" in *" $(basename "$w") "*) dirs="$dirs$(dirname "$w") " ;; esac
  done
  [ "$dirs" = " " ] && return 0
  for f in ${CHANGED[@]+"${CHANGED[@]}"}; do
    d="$(dirname "$f")"
    case "$dirs" in *" $d "*) ;; *) continue ;; esac
    case "$GROUP_FILES" in *" $(basename "$f") "*) ;; *) continue ;; esac
    already=0
    for w in ${WITHHELD[@]+"${WITHHELD[@]}"}; do [ "$w" = "$f" ] && already=1; done
    [ "$already" = 1 ] && continue
    if git cat-file -e "origin/main:$f" 2>/dev/null; then
      git show "origin/main:$f" > "$f"
    else
      rm -f "$f"
    fi
    WITHHELD+=("$f")
    echo "::warning::Withholding $f with its ledger group in $d (atomic: a group member could not be merged). This run's version vs remote:"
    git --no-pager diff --no-index -U0 -- "$f" "$SNAP/$f" 2>/dev/null | head -200 || true
  done
}

finish() {
  if [ ${#WITHHELD[@]} -gt 0 ]; then
    echo "::error::commit_and_push [$LABEL]: withheld ${#WITHHELD[@]} file(s) whose remote copy changed concurrently and could not be merged safely: ${WITHHELD[*]}. Remote (newer) state was kept; this run's delta is printed above. Broker state is unaffected (idempotent client_order_ids); EOD reconciliation re-syncs the ledger."
    exit 1
  fi
  exit 0
}

# Mirror the freshest tree into dashboard/ so Vercel serves current state for
# ALL portfolios (root data/ etc. are remote-latest after the reset).
sync_dashboard() {
  mkdir -p dashboard/data dashboard/event-driven-bot/data \
           dashboard/political-copy-bot/data dashboard/journal dashboard/config
  cp data/*.json dashboard/data/ 2>/dev/null || true
  cp event-driven-bot/data/*.json dashboard/event-driven-bot/data/ 2>/dev/null || true
  cp political-copy-bot/data/*.json dashboard/political-copy-bot/data/ 2>/dev/null || true
  cp journal/*.json dashboard/journal/ 2>/dev/null || true
  cp config/risk_limits.json config/watchlist.json dashboard/config/ 2>/dev/null || true
}

for attempt in 1 2 3 4 5; do
  if ! git fetch origin main; then
    echo "fetch failed (attempt $attempt) — retrying..."; sleep $((attempt * 3)); continue
  fi

  # Discard any partial rebase/merge and rebuild on the freshest remote.
  git rebase --abort 2>/dev/null || true
  git merge  --abort 2>/dev/null || true
  git reset --hard origin/main

  restore_owned
  withhold_groups
  sync_dashboard

  git add -A
  if git diff --cached --quiet; then
    echo "No net changes vs latest remote — nothing to push."
    finish
  fi

  git commit -m "$LABEL $(date -u '+%Y-%m-%d %H:%M')Z"
  if git push origin HEAD:main; then
    echo "Push succeeded on attempt $attempt."
    finish
  fi
  echo "Push lost the race (attempt $attempt) — rebuilding on freshest remote..."
  sleep $((attempt * 3))
done

echo "::error::commit_and_push: all 5 attempts failed for [$LABEL] — state NOT synced. Idempotent client_order_ids + EOD reconciliation keep the broker safe; the failure-alert watchdog will fire."
exit 1
