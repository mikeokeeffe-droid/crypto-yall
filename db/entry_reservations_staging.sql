-- STAGING ONLY. Do not apply to production or enable live entries without review.
-- A reservation serializes entry intent across Aggressive, Intraday and Daily.
-- This is not sufficient alone: executors must acquire before order placement,
-- renew as needed, and reconcile exchange fills before releasing.
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
     or p_bot not in ('aggressive', 'intraday', 'daily')
     or p_token is null or p_ttl_seconds not between 30 and 600 then
    raise exception 'invalid entry reservation arguments';
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
