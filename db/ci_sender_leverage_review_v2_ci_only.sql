-- PR #40 DISPOSABLE CI safety_test ONLY. NEVER run on production or Supabase.
-- V2 leverage/size REVIEW JOURNAL; no exchange endpoint, signer, sender
-- dispatch function, close function, or authorization to submit an order.
-- This is deliberately separate from existing V1 sender schema because V1
-- has no leverage or margin-mode field. No migration of V1 is implied.

-- Separate coordinator-only SQL principals from the legacy bot entry logins.
-- All passwords below are disposable CI fixtures, never production secrets.
create role ci_v2_coordinator_daily login
  password 'disposable-v2-coordinator-daily-only';
create role ci_v2_coordinator_intraday login
  password 'disposable-v2-coordinator-intraday-only';
create role ci_v2_coordinator_aggressive login
  password 'disposable-v2-coordinator-aggressive-only';
grant usage on schema public to
  ci_v2_coordinator_daily,ci_v2_coordinator_intraday,
  ci_v2_coordinator_aggressive;

create table public.ci_v2_coordinator_scopes (
  bot text primary key check (bot in ('daily','intraday','aggressive')),
  db_login name not null unique,
  environment text not null check (environment='mainnet'),
  effective_account text not null check (
    effective_account ~ '^0x[0-9a-f]{40}$'
  )
);
insert into public.ci_v2_coordinator_scopes
  (bot,db_login,environment,effective_account)
values
  ('daily','ci_v2_coordinator_daily','mainnet',
   '0x1111111111111111111111111111111111111111'),
  ('intraday','ci_v2_coordinator_intraday','mainnet',
   '0x1111111111111111111111111111111111111111'),
  ('aggressive','ci_v2_coordinator_aggressive','mainnet',
   '0x1111111111111111111111111111111111111111');
revoke all on public.ci_v2_coordinator_scopes from
  public,anon,authenticated,service_role,
  bot_entry_executor_trial,ci_sender_entry_api,ci_sender_worker,
  ci_sender_reviewer,entry_login_daily,entry_login_intraday,
  entry_login_aggressive,ci_v2_coordinator_daily,
  ci_v2_coordinator_intraday,ci_v2_coordinator_aggressive;

create table public.ci_sender_v2_reviews (
  token uuid primary key,
  request_id uuid not null unique,
  environment text not null check (environment in ('mainnet','testnet')),
  effective_account text not null check (
    effective_account ~ '^0x[0-9a-f]{40}$'
  ),
  dex text not null check (dex = ''),
  coin text not null check (coin ~ '^[A-Z0-9]+$'),
  bot text not null check (bot in ('daily','intraday','aggressive')),
  action text not null check (action in ('open_long','open_short')),
  requested_size numeric not null check (
    requested_size > 0 and
    requested_size::text not in ('NaN','Infinity','-Infinity')
  ),
  -- CI-review-only range; production leverage policy not approved.
  requested_leverage integer not null
    check (requested_leverage between 1 and 5),
  margin_mode text not null check (margin_mode = 'cross'),
  cloid text not null unique check (cloid ~ '^0x[0-9a-f]{32}$'),
  fence_token bigint generated always as identity unique,
  state text not null default 'review_only'
    check (state = 'review_only'),
  created_at timestamptz not null default now(),
  unique (environment,effective_account,dex,coin)
);

revoke all on public.ci_sender_v2_reviews
  from public,anon,authenticated,service_role,
       bot_entry_executor_trial,ci_sender_entry_api,
       ci_sender_worker,ci_sender_reviewer,
       entry_login_daily,entry_login_intraday,entry_login_aggressive,
       ci_v2_coordinator_daily,ci_v2_coordinator_intraday,
       ci_v2_coordinator_aggressive;

-- The actual PostgreSQL session_user AND configured account scope pin the
-- bot. A claim is an immutable, non-executable review snapshot. The v2
-- caller provides desired leverage; NO leverage application is inferred.
create function public.ci_sender_v2_record_review(
  p_environment text,p_account text,p_dex text,p_coin text,
  p_bot text,p_action text,p_size numeric,p_leverage integer,
  p_margin_mode text,p_request_id uuid
) returns table(recorded boolean,review_token uuid,fencing bigint)
language plpgsql security definer
set search_path = pg_catalog,public
as $$
declare
  v_token uuid;
  v_fence bigint;
begin
  if p_environment is null or p_environment not in ('mainnet','testnet')
     or p_account is null or p_account !~ '^0x[0-9a-f]{40}$'
     or p_dex is distinct from ''
     or p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot is null or p_bot not in ('daily','intraday','aggressive')
     or p_action is null or p_action not in ('open_long','open_short')
     or p_size is null or p_size <= 0
     or p_size::text in ('NaN','Infinity','-Infinity')
     or p_leverage is null or p_leverage < 1 or p_leverage > 5
     or p_margin_mode is distinct from 'cross'
     or p_request_id is null
     or not exists (
       select 1 from public.ci_v2_coordinator_scopes a
       where a.bot=p_bot and a.db_login=session_user::name
         and a.environment=p_environment
         and a.effective_account=p_account
     )
  then
    raise exception 'invalid or unapproved CI leverage review'
      using errcode='42501';
  end if;

  insert into public.ci_sender_v2_reviews (
    token,request_id,environment,effective_account,dex,coin,bot,action,
    requested_size,requested_leverage,margin_mode,cloid
  ) values (
    pg_catalog.gen_random_uuid(),p_request_id,p_environment,p_account,
    p_dex,p_coin,p_bot,p_action,p_size,p_leverage,p_margin_mode,
    '0x'||replace(pg_catalog.gen_random_uuid()::text,'-','')
  ) on conflict do nothing
  returning token,fence_token into v_token,v_fence;

  if v_token is null then
    return query select false,null::uuid,null::bigint;
  else
    return query select true,v_token,v_fence;
  end if;
end;
$$;

revoke execute on function public.ci_sender_v2_record_review(
  text,text,text,text,text,text,numeric,integer,text,uuid
) from public,anon,authenticated,service_role,
       bot_entry_executor_trial,ci_sender_entry_api,
       ci_sender_worker,ci_sender_reviewer,
       entry_login_daily,entry_login_intraday,entry_login_aggressive;
grant execute on function public.ci_sender_v2_record_review(
  text,text,text,text,text,text,numeric,integer,text,uuid
) to ci_v2_coordinator_daily,ci_v2_coordinator_intraday,
     ci_v2_coordinator_aggressive;
grant select on public.ci_sender_v2_reviews to ci_sender_reviewer;

-- Intentional absence: no update/release/mark-unknown/dispatch functions on
-- this V2 table, no sender worker permissions, and no accepted live order.
