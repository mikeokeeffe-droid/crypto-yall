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
-- Do not allow one executor to read another bot's intent or token.
-- Return only the row pinned to its own authenticated PostgreSQL LOGIN.
create or replace function public.read_bot_entry_claim_proof(
  p_coin text, p_bot text, p_token uuid
) returns table(bot text, coin text, token uuid, status text, fence_token bigint)
language plpgsql security definer
set search_path = pg_catalog, public
as $
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+
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

     or p_bot not in ('daily','intraday','aggressive')
     or p_token is null
     or not exists (
       select 1 from public.bot_entry_executor_identities e
       where e.bot=p_bot and e.db_login=session_user::name
     ) then
    raise exception 'claim proof identity not authorized'
      using errcode = '42501';
  end if;
  return query
    select i.bot,i.coin,i.token,i.status,i.fence_token
    from public.bot_entry_intents i
    where i.coin=p_coin and i.bot=p_bot and i.token=p_token;
end;
$;
revoke all on function public.read_bot_entry_claim_proof(text,text,uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.read_bot_entry_claim_proof(text,text,uuid)
  to bot_entry_executor_trial;
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
