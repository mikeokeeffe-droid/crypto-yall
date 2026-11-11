-- Disposable safety_test database ONLY. Never apply to Supabase/production.
-- Review-only central sender schema; no exchange order, release or close RPC.
-- Separate from existing ci_scoped_entry_* models pending independent review.

create role ci_sender_entry_api nologin;
create role ci_sender_worker login password 'disposable-sender-only';
grant ci_sender_entry_api to
  entry_login_daily, entry_login_intraday, entry_login_aggressive;
grant usage on schema public to ci_sender_entry_api, ci_sender_worker;

create table public.ci_sender_intents (
  token uuid primary key,
  request_id uuid not null unique,
  environment text not null check (environment in ('mainnet', 'testnet')),
  effective_account text not null check (
    effective_account ~ '^0x[0-9a-f]{40}$'
  ),
  dex text not null check (dex = ''),
  coin text not null check (coin ~ '^[A-Z0-9]+$'),
  bot text not null check (bot in ('daily', 'intraday', 'aggressive')),
  action text not null check (action in ('open_long', 'open_short')),
  requested_size numeric not null check (
    requested_size > 0
    and requested_size::text not in ('NaN','Infinity','-Infinity')
  ),
  cloid text not null unique check (cloid ~ '^0x[0-9a-f]{32}$'),
  fence_token bigint generated always as identity unique,
  state text not null default 'reserved' check (
    state in ('reserved','dispatch_unknown')
  ),
  created_at timestamptz not null default now(),
  unique (environment, effective_account, dex, coin)
);

create table public.ci_sender_attempts (
  attempt_id bigint generated always as identity primary key,
  intent_token uuid not null unique
    references public.ci_sender_intents(token),
  fence_token bigint not null,
  cloid text not null check (cloid ~ '^0x[0-9a-f]{32}$'),
  state text not null default 'dispatch_unknown'
    check (state = 'dispatch_unknown'),
  recorded_at timestamptz not null default now()
);

revoke all on public.ci_sender_intents, public.ci_sender_attempts
  from public, anon, authenticated, service_role, bot_entry_executor_trial,
       ci_sender_entry_api, ci_sender_worker,
       entry_login_daily, entry_login_intraday, entry_login_aggressive;

-- Authenticate the real PostgreSQL LOGIN rather than a caller-supplied
-- bot string. Scope must be on the disposable per-login allowlist.
-- Precommitted independent CLOID and immutable intent share one transaction.
create function public.ci_sender_reserve(
  p_environment text, p_account text, p_dex text, p_coin text,
  p_bot text, p_action text, p_size numeric, p_request_id uuid
) returns table(accepted boolean, intent_id uuid, fencing bigint)
language plpgsql security definer
set search_path = pg_catalog, public
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
     or p_request_id is null
     or not exists (
       select 1 from public.bot_entry_executor_identities e
       join public.ci_scoped_executor_accounts a
         on a.db_login = e.db_login
       where e.bot = p_bot and e.db_login = session_user::name
         and a.environment = p_environment
         and a.effective_account = p_account
     )
  then
    raise exception 'invalid or unauthorised CI sender intent'
      using errcode = '42501';
  end if;

  insert into public.ci_sender_intents (
    token,request_id,environment,effective_account,dex,coin,
    bot,action,requested_size,cloid
  ) values (
    pg_catalog.gen_random_uuid(),p_request_id,p_environment,p_account,p_dex,
    p_coin,p_bot,p_action,p_size,
    '0x' || replace(pg_catalog.gen_random_uuid()::text,'-','')
  )
  on conflict do nothing
  returning token,fence_token into v_token,v_fence;

  if v_token is null then
    return query select false,null::uuid,null::bigint;
  else
    return query select true,v_token,v_fence;
  end if;
end;
$$;

revoke all on function public.ci_sender_reserve(
  text,text,text,text,text,text,numeric,uuid
) from public, anon, authenticated, service_role,
       bot_entry_executor_trial, ci_sender_worker;
grant execute on function public.ci_sender_reserve(
  text,text,text,text,text,text,numeric,uuid
) to ci_sender_entry_api;

-- Only a distinct disposable sender LOGIN can perform the final CAS.
-- The entire marker and intent state transition commit together,
-- BEFORE any fake side effect; no release, retry or real dispatch RPC.
create function public.ci_sender_mark_unknown(
  p_token uuid, p_fence bigint
) returns table(marked boolean, stored_cloid text)
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_cloid text;
begin
  if session_user::text <> 'ci_sender_worker'
     or p_token is null or p_fence is null or p_fence <= 0
  then
    raise exception 'unauthorised CI sender identity'
      using errcode = '42501';
  end if;

  update public.ci_sender_intents
  set state = 'dispatch_unknown'
  where token = p_token
    and fence_token = p_fence
    and state = 'reserved'
  returning cloid into v_cloid;

  if v_cloid is null then
    return query select false,null::text;
    return;
  end if;

  insert into public.ci_sender_attempts (
    intent_token,fence_token,cloid
  ) values (p_token,p_fence,v_cloid);
  return query select true,v_cloid;
end;
$$;

revoke all on function public.ci_sender_mark_unknown(uuid,bigint)
  from public, anon, authenticated, service_role,
       bot_entry_executor_trial, ci_sender_entry_api,
       entry_login_daily, entry_login_intraday, entry_login_aggressive;
grant execute on function public.ci_sender_mark_unknown(uuid,bigint)
  to ci_sender_worker;
