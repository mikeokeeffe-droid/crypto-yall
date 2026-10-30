-- STAGING ONLY. Do not apply to production or enable live entries without review.
-- A reservation serializes entry intent across Aggressive, Intraday and Daily.
-- This is not sufficient alone: executors must acquire before order placement,
-- renew as needed, and reconcile exchange fills before releasing.
-- Superusers remain trusted database administrators; ordinary LOGINs must map
-- to exactly their own bot below.
create table if not exists public.bot_entry_executor_identities (
  bot text primary key check (bot in ('aggressive', 'intraday', 'daily')),
  db_login name not null unique
);

create table if not exists public.bot_entry_reservations (
  coin text primary key check (coin ~ '^[A-Z0-9]+$'),
  bot text not null check (bot in ('aggressive', 'intraday', 'daily')),
  token uuid not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create or replace function public.try_reserve_bot_entry(
  p_coin text, p_bot text, p_token uuid, p_ttl_seconds integer default 120
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot is null or p_bot not in ('aggressive', 'intraday', 'daily')
     or p_token is null or p_ttl_seconds not between 30 and 600 then
    raise exception 'invalid entry reservation arguments';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles r
    where r.rolname = session_user and r.rolsuper
  ) and not exists (
    select 1 from public.bot_entry_executor_identities i
    where i.bot = p_bot and i.db_login = session_user::name
  ) then
    raise exception 'database login is not authorized for requested bot'
      using errcode = '42501';
  end if;
  insert into public.bot_entry_reservations(coin,bot,token,expires_at)
  values (p_coin,p_bot,p_token,now() + make_interval(secs => p_ttl_seconds))
  on conflict (coin) do update
    set bot = excluded.bot, token = excluded.token,
        expires_at = excluded.expires_at, created_at = now()
    where bot_entry_reservations.expires_at < now()
       or (bot_entry_reservations.bot = excluded.bot
           and bot_entry_reservations.token = excluded.token);
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function public.release_bot_entry(
  p_coin text, p_bot text, p_token uuid
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if not exists (
    select 1 from pg_catalog.pg_roles r
    where r.rolname = session_user and r.rolsuper
  ) and not exists (
    select 1 from public.bot_entry_executor_identities i
    where i.bot = p_bot and i.db_login = session_user::name
  ) then
    raise exception 'database login is not authorized for requested bot'
      using errcode = '42501';
  end if;
  delete from public.bot_entry_reservations
  where coin = p_coin and bot = p_bot and token = p_token;
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

-- Deployment must restrict EXECUTE/table permissions to the server-side
-- service role and never expose the service key to clients.
revoke all on public.bot_entry_reservations from public, anon, authenticated;
revoke all on function public.try_reserve_bot_entry(text,text,uuid,integer)
  from public, anon, authenticated;
revoke all on function public.release_bot_entry(text,text,uuid)
  from public, anon, authenticated;

-- Fail-closed durable unresolved-order fence. An expired short reservation
-- is NOT sufficient to grant a new entry if any order remains unresolved.
create table if not exists public.bot_entry_intents (
  coin text primary key check (coin ~ '^[A-Z0-9]+$'),
  bot text not null check (bot in ('aggressive','intraday','daily')),
  token uuid not null unique,
  status text not null check (status in ('pending','submitted','uncertain','filled')),
  exchange_order_id text,
  submitted_at_ms bigint,
  requested_size numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.bot_entry_intents
  add column if not exists exchange_order_id text,
  add column if not exists submitted_at_ms bigint,
  add column if not exists requested_size numeric;

-- Call only after a reservation is acquired and before sending an order.
-- A coin with a pending/uncertain/filled intent is unavailable to other bots.
create or replace function public.claim_bot_entry_intent(
  p_coin text, p_bot text, p_token uuid
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_bot is null or p_token is null then
    raise exception 'invalid intent arguments';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles r
    where r.rolname = session_user and r.rolsuper
  ) and not exists (
    select 1 from public.bot_entry_executor_identities i
    where i.bot = p_bot and i.db_login = session_user::name
  ) then
    raise exception 'database login is not authorized for requested bot'
      using errcode = '42501';
  end if;
  insert into public.bot_entry_intents(coin,bot,token,status)
  select r.coin,r.bot,r.token,'pending'
  from public.bot_entry_reservations r
  where r.coin=p_coin and r.bot=p_bot and r.token=p_token
    and r.expires_at > now()
  on conflict (coin) do nothing;
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

-- An operator/reconciler must verify exchange order AND position status
-- before resolving a claim; there is deliberately no auto-expiry here.
create or replace function public.resolve_bot_entry_intent(
  p_coin text, p_bot text, p_token uuid
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  delete from public.bot_entry_intents
  where coin=p_coin and bot=p_bot and token=p_token;
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

-- Reservation acquisition must also check the durable fence.
-- Concurrent claim vs reservation requires a single serialized per-coin
-- transaction; use an advisory transaction lock in BOTH paths.
create or replace function public.try_reserve_bot_entry(
  p_coin text, p_bot text, p_token uuid, p_ttl_seconds integer default 120
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot is null or p_bot not in ('aggressive','intraday','daily')
     or p_token is null or p_ttl_seconds not between 30 and 600 then
    raise exception 'invalid entry reservation arguments';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles r
    where r.rolname = session_user and r.rolsuper
  ) and not exists (
    select 1 from public.bot_entry_executor_identities i
    where i.bot = p_bot and i.db_login = session_user::name
  ) then
    raise exception 'database login is not authorized for requested bot'
      using errcode = '42501';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin, 0));
  if exists (select 1 from public.bot_entry_intents where coin=p_coin) then
    return false;
  end if;
  insert into public.bot_entry_reservations(coin,bot,token,expires_at)
  values (p_coin,p_bot,p_token,now()+make_interval(secs => p_ttl_seconds))
  on conflict (coin) do update
    set bot=excluded.bot,token=excluded.token,
        expires_at=excluded.expires_at,created_at=now()
    where bot_entry_reservations.expires_at < now()
       or (bot_entry_reservations.bot=excluded.bot
           and bot_entry_reservations.token=excluded.token);
  get diagnostics v_count = row_count;
  return v_count=1;
end;
$$;

-- Match reservation's advisory lock when creating the durable fence.
create or replace function public.claim_bot_entry_intent(
  p_coin text, p_bot text, p_token uuid
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_bot is null or p_token is null then
    raise exception 'invalid intent arguments';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles r
    where r.rolname = session_user and r.rolsuper
  ) and not exists (
    select 1 from public.bot_entry_executor_identities i
    where i.bot = p_bot and i.db_login = session_user::name
  ) then
    raise exception 'database login is not authorized for requested bot'
      using errcode = '42501';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin, 0));
  insert into public.bot_entry_intents(coin,bot,token,status)
  select r.coin,r.bot,r.token,'pending'
  from public.bot_entry_reservations r
  where r.coin=p_coin and r.bot=p_bot and r.token=p_token
    and r.expires_at > now()
  on conflict (coin) do nothing;
  get diagnostics v_count = row_count;
  return v_count=1;
end;
$$;

-- Record the exchange identity after submission. A timeout without an
-- authoritative order ID remains uncertain and cannot be automatically freed.
create or replace function public.record_bot_entry_order(
  p_coin text, p_bot text, p_token uuid, p_exchange_order_id text,
  p_submitted_at_ms bigint, p_requested_size numeric, p_status text
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot not in ('aggressive','intraday','daily')
     or p_token is null
     or p_status not in ('submitted','uncertain')
     or p_submitted_at_ms is null or p_submitted_at_ms < 0
     or p_requested_size is null or p_requested_size <= 0
     or p_requested_size::text in ('NaN','Infinity','-Infinity')
     or (p_status = 'submitted'
         and nullif(btrim(p_exchange_order_id),'') is null) then
    raise exception 'invalid durable order identity';
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles r
    where r.rolname = session_user and r.rolsuper
  ) and not exists (
    select 1 from public.bot_entry_executor_identities i
    where i.bot = p_bot and i.db_login = session_user::name
  ) then
    raise exception 'database login is not authorized for requested bot'
      using errcode = '42501';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin, 0));
  update public.bot_entry_intents
     set status = p_status,
         exchange_order_id = coalesce(exchange_order_id, p_exchange_order_id),
         submitted_at_ms = coalesce(submitted_at_ms, p_submitted_at_ms),
         requested_size = coalesce(requested_size, p_requested_size),
         updated_at = now()
   where coin = p_coin and bot = p_bot and token = p_token
     and status in ('pending','submitted','uncertain')
     and (exchange_order_id is null or p_exchange_order_id is null
          or exchange_order_id = p_exchange_order_id)
     and (submitted_at_ms is null or submitted_at_ms = p_submitted_at_ms)
     and (requested_size is null or requested_size = p_requested_size)
     and (p_status <> 'submitted' or p_exchange_order_id is not null);
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

revoke all on public.bot_entry_intents from public,anon,authenticated;
revoke all on public.bot_entry_executor_identities from public,anon,authenticated;
revoke all on function public.claim_bot_entry_intent(text,text,uuid)
  from public,anon,authenticated;
revoke all on function public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)
  from public,anon,authenticated;
revoke all on function public.resolve_bot_entry_intent(text,text,uuid)
  from public,anon,authenticated;
