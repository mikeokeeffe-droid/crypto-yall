-- STAGING ONLY: durable owner handoff. Do not deploy to live trading.
-- Retain the intent row as the permanent per-coin fence while owned.
-- All state transitions serialize on the same per-coin advisory lock.

create table if not exists public.bot_position_owners (
  coin text primary key check (coin ~ '^[A-Z0-9]+$'),
  bot text not null check (bot in ('aggressive','intraday','daily')),
  token uuid not null unique,
  exchange_order_id text not null check (length(exchange_order_id) > 0),
  state text not null default 'owned' check (state in ('owned','closed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.record_bot_position_owner(
  p_coin text, p_bot text, p_token uuid, p_exchange_order_id text,
  p_fill_verified boolean
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot not in ('aggressive','intraday','daily')
     or p_token is null or nullif(btrim(p_exchange_order_id),'') is null
     or p_fill_verified is distinct from true then
    return false;
  end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin,0));
  update public.bot_entry_intents
     set status='filled',updated_at=now()
   where coin=p_coin and bot=p_bot and token=p_token
     and status in ('submitted','uncertain','filled')
     and exchange_order_id=p_exchange_order_id;
  get diagnostics v_count=row_count;
  if v_count<>1 then return false; end if;
  insert into public.bot_position_owners(coin,bot,token,exchange_order_id)
  values(p_coin,p_bot,p_token,p_exchange_order_id)
  on conflict (coin) do update
    set updated_at=now()
    where bot_position_owners.bot=excluded.bot
      and bot_position_owners.token=excluded.token
      and bot_position_owners.exchange_order_id=excluded.exchange_order_id
      and bot_position_owners.state='owned';
  get diagnostics v_count=row_count;
  if v_count<>1 then
    raise exception 'owner handoff conflict; transaction rolled back';
  end if;
  return true;
end;
$$;

-- A no-fill fence can be removed only by the independent reconciler after
-- it has verified a final canceled/rejected order, complete zero-fill
-- history, a flat position, and no open orders. TTL is never sufficient.
create or replace function public.release_resolved_bot_entry_intent(
  p_coin text, p_bot text, p_token uuid, p_exchange_order_id text,
  p_final_status text, p_zero_fills boolean, p_exchange_flat boolean,
  p_no_open_orders boolean
) returns boolean language plpgsql security invoker
set search_path = public
as $$
declare v_count integer;
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot not in ('aggressive','intraday','daily')
     or p_token is null
     or nullif(btrim(p_exchange_order_id),'') is null
     or p_final_status not in ('canceled','cancelled','rejected','expired')
     or p_zero_fills is distinct from true
     or p_exchange_flat is distinct from true
     or p_no_open_orders is distinct from true then
    return false;
  end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin,0));
  if exists (
    select 1 from public.bot_position_owners
    where coin=p_coin
  ) then
    return false;
  end if;
  delete from public.bot_entry_intents
   where coin=p_coin and bot=p_bot and token=p_token
     and status in ('submitted','uncertain')
     and exchange_order_id=p_exchange_order_id;
  get diagnostics v_count = row_count;
  if v_count <> 1 then
    return false;
  end if;
  delete from public.bot_entry_reservations
   where coin=p_coin and bot=p_bot and token=p_token;
  return true;
end;
$$;

create or replace function public.get_bot_entry_reconciliation_intent(
  p_coin text, p_bot text, p_token uuid
) returns table(
  status text, exchange_order_id text,
  submitted_at_ms bigint, requested_size numeric
) language sql security invoker stable
set search_path = pg_catalog, public
as $$
  select i.status, i.exchange_order_id, i.submitted_at_ms, i.requested_size
  from public.bot_entry_intents i
  where i.coin = p_coin and i.bot = p_bot and i.token = p_token
$$;

-- Only a trusted reconciler should call this after independent exchange checks.
-- Booleans are assertions by the caller, NOT proof from the database.
create or replace function public.mark_bot_position_closed(
  p_coin text,p_bot text,p_token uuid,
  p_exchange_flat boolean,p_no_open_orders boolean
) returns boolean language plpgsql security invoker
set search_path=public
as $$
declare v_count integer;
begin
  if p_exchange_flat is distinct from true
     or p_no_open_orders is distinct from true
     or p_coin is null then return false; end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin,0));
  update public.bot_position_owners set state='closed',updated_at=now()
  where coin=p_coin and bot=p_bot and token=p_token
    and state in ('owned','closed');
  get diagnostics v_count=row_count;
  return v_count=1;
end;
$$;

create or replace function public.release_closed_bot_position(
  p_coin text,p_bot text,p_token uuid,
  p_exchange_flat boolean,p_no_open_orders boolean
) returns boolean language plpgsql security invoker
set search_path=public
as $$
declare v_count integer;
begin
  if p_exchange_flat is distinct from true
     or p_no_open_orders is distinct from true
     or p_coin is null then return false; end if;
  perform pg_advisory_xact_lock(hashtextextended('entry:' || p_coin,0));
  delete from public.bot_position_owners
   where coin=p_coin and bot=p_bot and token=p_token and state='closed';
  get diagnostics v_count=row_count;
  if v_count<>1 then return false; end if;
  delete from public.bot_entry_intents
   where coin=p_coin and bot=p_bot and token=p_token and status='filled';
  get diagnostics v_count=row_count;
  if v_count<>1 then
    raise exception 'intent release conflict; transaction rolled back';
  end if;
  -- Remove the same owner's short-lived reservation as part of the
  -- verified release transaction, otherwise a new bot stays blocked.
  delete from public.bot_entry_reservations
   where coin=p_coin and bot=p_bot and token=p_token;
  return true;
end;
$$;

revoke all on public.bot_position_owners from public,anon,authenticated;
-- The legacy service-role key is not a trusted reconciler identity.
revoke all on public.bot_position_owners from service_role;
revoke all on function public.record_bot_position_owner(text,text,uuid,text,boolean)
 from public,anon,authenticated;
revoke all on function public.release_resolved_bot_entry_intent(
 text,text,uuid,text,text,boolean,boolean,boolean)
 from public,anon,authenticated,service_role;
revoke all on function public.get_bot_entry_reconciliation_intent(text,text,uuid)
 from public,anon,authenticated,service_role;
revoke all on function public.mark_bot_position_closed(text,text,uuid,boolean,boolean)
 from public,anon,authenticated,service_role;
revoke all on function public.release_closed_bot_position(text,text,uuid,boolean,boolean)
 from public,anon,authenticated,service_role;
do $$
begin
  if exists (select 1 from pg_catalog.pg_roles
             where rolname='bot_entry_executor_trial') then
    execute 'revoke all on function public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean) from bot_entry_executor_trial';
    execute 'revoke all on function public.get_bot_entry_reconciliation_intent(text,text,uuid) from bot_entry_executor_trial';
  end if;
end;
$$;
-- No routine executor grants for close/release; reconciliation is privileged.
-- IMPORTANT: the staging migration runs as the database owner; revoke
-- EXECUTE from untrusted roles on all new functions above and explicitly
-- remove existing service_role grants as well as default PUBLIC grants.
revoke execute on function public.record_bot_position_owner(text,text,uuid,text,boolean)
 from service_role;
