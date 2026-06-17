# Alpaca Skills Library, CLI & MCP — adoption & governance

This documents how the **Alpaca Skills Library** (`alpacahq/alpaca-skills`), the
**Alpaca CLI** (`alpacahq/cli`), and the **Alpaca MCP server** are used in this
project, and the hard boundaries that keep them off the autonomous money path.

## What we adopted (and what we did NOT)

We did **not** adopt Alpaca's backtest *engine* — ours is deeper (`scripts/backtest/`
has CPCV, deflated Sharpe, PBO, a fail-closed walk-forward gate). We adopted:

1. **The operating standard** — formalize → fingerprint → benchmark → disclose.
2. **A governed data/exec surface** — the CLI + the live MCP, **interactive/research lane only**.
3. **Realistic friction** — the discipline that exposed our flat-5bps assumption.

## The two hard invariants (non-negotiable)

- **Invariant A — cloud path is `requests`-only.** The skill, the CLI, and the
  heavy scientific stack are **never** imported on the GitHub Actions
  trading/monitor/EOD/weekly path. They run offline (the `scripts/research/` T2
  lane / interactive sessions) and emit **static JSON artifacts** the pure-Python
  path *reads*. Enforced by `tests/test_trading_path_purity.py`.
- **Invariant B — no Claude/LLM in the autonomous loop.** The Alpaca skill is an
  *interactive* agent-skill: it runs only when a human + Claude drive research or
  dev. Nothing wires it (or any LLM/MCP call) into Actions. The LLM SDKs are in
  the purity tripwire's banned set.

## Pinning (invariant C — PREVIEW upstreams ship breaking changes)

| Tool | Pin | Where |
|------|-----|-------|
| Alpaca backtest skill | commit `8b2d86b5d22e8b3395e3b59c2431b007a43837a0`, sha256 `830db169…5f42da3c` | `skills-lock.json` → `alpaca-trading-backtest`; vendored at `.claude/skills/alpaca-trading-backtest/`; hash-verified by `tests/test_skills_lock_pinned.py` |
| Alpaca CLI | pin a specific release/commit before any use | `go install github.com/alpacahq/cli/cmd/alpaca@<TAG>` — pin `<TAG>`, never `@latest`/`main` |

> **Note:** commit-pinning was a *new* field added to `skills-lock.json`
> (`pinnedCommit` / `localPath` / `scope`). The pre-existing entries carried only
> `computedHash`. Unknown fields are additive and ignored by the global installer.

## The Alpaca CLI — research lane only

- Install (research/dev machines only): `brew install alpacahq/tap/cli` or
  `go install github.com/alpacahq/cli/cmd/alpaca@<PINNED_TAG>`.
- Auth: OAuth for **paper + market data** (no keys). A live key is required only
  for live trading — which we do not do. Use a **dedicated data/paper token**,
  never the `P1/P2/P3` trading keys.
- It is composable (`--quiet` JSON, `--csv`, `--jq`) for offline artifact
  generation. It must **never** be installed in a trading/monitor/EOD workflow.

## The Alpaca MCP server — read-only evidence layer

When a human + Claude review trades (the interactive investment committee), the
MCP may be used for **read-only** evidence: `get_news`, `get_market_movers`,
`get_most_active_stocks`, `get_option_chain`/`get_option_snapshot`,
`get_corporate_actions`, `get_portfolio_history`, quotes/orderbook.

**Hard ban inside any committee/research flow:** `place_*`, `close_*`,
`cancel_*`. Order execution stays with the deterministic system rules and the
idempotent `shared/alpaca_http.py` path. Paper-only until `docs/LIVE_READINESS.md`
gates pass.

## Kill / rollback path

1. Revert the `skills-lock.json` pin to the last-known-good commit + hash.
2. Delete the suspect `data/*.json` research artifact → the cloud path falls back
   to its last-good value (e.g. `strategy_params.last_good.json`).
3. The purity tripwire + `preflight.py` param-bounds clamp prevent any tainted
   value from reaching an order.
