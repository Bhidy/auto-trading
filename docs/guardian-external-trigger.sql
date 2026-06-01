-- ===========================================================================
-- GUARDIAN EXTERNAL TRIGGER (L2) — Supabase pg_cron → GitHub repository_dispatch
-- ===========================================================================
--
-- WHY: GitHub Actions only throttles `schedule:` (cron) triggers. They can be
-- delayed 10–40 min or skipped under platform load. API-triggered runs
-- (repository_dispatch) start within SECONDS. This makes Supabase — which is
-- always-on and already our system-of-record — poke the Guardian workflow on a
-- reliable schedule. Guardian then runs ONLY the portfolios that haven't traded
-- today (idempotent; client_order_ids prevent any double-placement).
--
-- This is the layer that makes the schedule truly independent of GitHub's cron.
--
-- ── ONE-TIME PREREQUISITE (you do this) ────────────────────────────────────
-- 1. Create a GitHub fine-grained PAT:
--    GitHub → Settings → Developer settings → Fine-grained tokens → Generate
--      • Resource owner: Bhidy
--      • Repository access: Only select repositories → Bhidy/auto-trading
--      • Repository permissions → Contents: Read and write   (required by the
--        repository_dispatch endpoint)
--      • Expiration: 1 year (set a calendar reminder to rotate)
--    Copy the token (starts with `github_pat_...`).
--
-- 2. In Supabase → SQL Editor, run STEP 1 below ONCE with your token pasted in,
--    then run STEP 2 and STEP 3.
-- ===========================================================================


-- ── STEP 1 — enable extensions + store the PAT in Vault (run once) ──────────
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Store the GitHub PAT encrypted in Supabase Vault (never in plaintext SQL/logs).
-- Replace github_pat_REPLACE_ME with your real token, then run this line once.
select vault.create_secret('github_pat_REPLACE_ME', 'github_dispatch_pat',
                           'PAT to fire Guardian repository_dispatch');


-- ── STEP 2 — the reusable poke function ─────────────────────────────────────
create or replace function public.fire_guardian_catchup()
returns void
language plpgsql
security definer
as $$
declare
  pat text;
begin
  select decrypted_secret into pat
  from vault.decrypted_secrets
  where name = 'github_dispatch_pat';

  perform net.http_post(
    url     := 'https://api.github.com/repos/Bhidy/auto-trading/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || pat,
      'Accept',        'application/vnd.github+json',
      'Content-Type',  'application/json',
      'User-Agent',    'supabase-guardian-trigger',
      'X-GitHub-Api-Version', '2022-11-28'
    ),
    body    := jsonb_build_object('event_type', 'trading-catchup')
  );
end;
$$;


-- ── STEP 3 — schedule the pokes (UTC; weekdays only) ────────────────────────
-- Times are AFTER each native trading window so Guardian only acts when the
-- native crons actually slipped. EDT (summer) + EST (winter) both covered.
-- pg_cron uses UTC on Supabase. Idempotent: re-poking a fresh day is a no-op.

select cron.schedule('guardian-poke-1410', '10 14 * * 1-5', $$select public.fire_guardian_catchup();$$); -- 10:10 ET (EDT)
select cron.schedule('guardian-poke-1440', '40 14 * * 1-5', $$select public.fire_guardian_catchup();$$);
select cron.schedule('guardian-poke-1540', '40 15 * * 1-5', $$select public.fire_guardian_catchup();$$); -- 10:40 ET (EST) / 11:40 ET (EDT)
select cron.schedule('guardian-poke-1640', '40 16 * * 1-5', $$select public.fire_guardian_catchup();$$); -- EST late-morning backstop


-- ── VERIFY ──────────────────────────────────────────────────────────────────
-- Scheduled jobs:        select jobname, schedule, active from cron.job;
-- Manual test poke:      select public.fire_guardian_catchup();
--                        (then check GitHub → Actions → "Guardian — Trading
--                         Catch-Up & Self-Heal" for a repository_dispatch run)
-- Recent HTTP responses: select status_code, content::text
--                          from net._http_response order by created desc limit 5;
-- Remove a job:          select cron.unschedule('guardian-poke-1410');
-- ===========================================================================
