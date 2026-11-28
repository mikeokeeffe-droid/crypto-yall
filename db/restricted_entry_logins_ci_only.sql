-- Disposable GitHub Actions database only; NEVER apply to production.
-- Each bot has a unique LOGIN and only the minimum RPC permissions.
-- The test fence sequence is DB-generated; production architecture still
-- requires independent review of stale workers, leases and reconciliation.
alter table public.bot_entry_intents
  add column fence_token bigint generated always as identity;
create role bot_entry_executor_trial nologin;
grant usage on schema public to bot_entry_executor_trial;
revoke create on schema public from public;
revoke all on public.bot_entry_executor_identities from public, anon, authenticated, service_role, bot_entry_executor_trial;
revoke all on public.bot_entry_reservations, public.bot_entry_intents from public, anon, authenticated, service_role, bot_entry_executor_trial;
grant select on public.bot_entry_intents to bot_entry_executor_trial;
alter function public.try_reserve_bot_entry(text,text,uuid,integer)
  security definer set search_path = pg_catalog, public;
alter function public.claim_bot_entry_intent(text,text,uuid)
  security definer set search_path = pg_catalog, public;
revoke execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  from public, anon, authenticated, service_role;
revoke execute on function public.claim_bot_entry_intent(text,text,uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  to bot_entry_executor_trial;
grant execute on function public.claim_bot_entry_intent(text,text,uuid)
  to bot_entry_executor_trial;
revoke execute on function public.release_bot_entry(text,text,uuid) from public, anon, authenticated, service_role, bot_entry_executor_trial;
revoke execute on function public.resolve_bot_entry_intent(text,text,uuid) from public, anon, authenticated, service_role, bot_entry_executor_trial;
revoke execute on function public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text) from public, anon, authenticated, service_role, bot_entry_executor_trial;
create role entry_login_daily login password 'disposable-daily-only';
create role entry_login_intraday login password 'disposable-intraday-only';
create role entry_login_aggressive login password 'disposable-aggressive-only';
grant bot_entry_executor_trial to entry_login_daily, entry_login_intraday, entry_login_aggressive;
insert into public.bot_entry_executor_identities(bot,db_login)
 values ('daily','entry_login_daily'),
        ('intraday','entry_login_intraday'),
        ('aggressive','entry_login_aggressive');
