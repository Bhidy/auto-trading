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
set -uo pipefail

LABEL="${1:?commit label required}"; shift
OWNED=("$@")

git config user.name  "Auto Trading Bot"
git config user.email "bot@autotrading.local"

# --- snapshot ONLY the files THIS job changed, before we touch the tree -------
# We carry forward exactly the owned files that differ from the checkout base
# (modified or new). Files this job did NOT touch are left at remote-latest by
# the reset below — so a multi-portfolio job (guardian) can never revert a
# portfolio it didn't regenerate, and a single-portfolio job only ever writes
# its own fresh output on top of everyone else's latest.
SNAP="$(mktemp -d)"
cleanup() { rm -rf "$SNAP"; }
trap cleanup EXIT

CHANGED=()
while IFS= read -r line; do
  [ -n "$line" ] && CHANGED+=("${line:3}")
done < <(git status --porcelain --untracked-files=all -- "${OWNED[@]}")

for f in ${CHANGED[@]+"${CHANGED[@]}"}; do
  [ -f "$f" ] || continue   # skip deletions — state/journal files are never deleted
  mkdir -p "$SNAP/$(dirname "$f")"
  cp -a "$f" "$SNAP/$f"
done

restore_owned() {
  # Overlay our changed files ON TOP of the reset (remote-latest) tree.
  for f in ${CHANGED[@]+"${CHANGED[@]}"}; do
    [ -f "$SNAP/$f" ] || continue
    mkdir -p "$(dirname "$f")"
    cp -a "$SNAP/$f" "$f"
  done
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
  sync_dashboard

  git add -A
  if git diff --cached --quiet; then
    echo "No net changes vs latest remote — nothing to push."
    exit 0
  fi

  git commit -m "$LABEL $(date -u '+%Y-%m-%d %H:%M')Z"
  if git push origin HEAD:main; then
    echo "Push succeeded on attempt $attempt."
    exit 0
  fi
  echo "Push lost the race (attempt $attempt) — rebuilding on freshest remote..."
  sleep $((attempt * 3))
done

echo "::error::commit_and_push: all 5 attempts failed for [$LABEL] — state NOT synced. Idempotent client_order_ids + EOD reconciliation keep the broker safe; the failure-alert watchdog will fire."
exit 1
