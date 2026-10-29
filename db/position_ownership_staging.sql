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
     and status in ('pending','submitted','uncertain','filled');
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
  where coin=p_coin and bot=p_bot and token=p_token and state='owned';
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
revoke all on function public.mark_bot_position_closed(text,text,uuid,boolean,boolean)
 from public,anon,authenticated,service_role;
revoke all on function public.release_closed_bot_position(text,text,uuid,boolean,boolean)
 from public,anon,authenticated,service_role;
-- No routine executor grants for close/release; reconciliation is privileged.
-- IMPORTANT: the staging migration runs as the database owner; revoke
-- EXECUTE from untrusted roles on all new functions above and explicitly
-- remove existing service_role grants as well as default PUBLIC grants.
revoke execute on function public.record_bot_position_owner(text,text,uuid,text,boolean)
 from service_role;
