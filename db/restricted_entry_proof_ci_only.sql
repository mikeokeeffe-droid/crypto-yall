-- Disposable safety_test PostgreSQL CI only. Do not apply to production.
-- The baseline grants broad SELECT. Remove it before bot tests execute.
revoke select on public.bot_entry_intents from bot_entry_executor_trial;

-- This is a narrow view of one pending durable entry claim, NOT proof of a
-- Hyperliquid position, and cannot authorize trading or release any fence.
create or replace function public.read_bot_entry_claim_proof(
  p_coin text, p_bot text, p_token uuid
) returns table(bot text, coin text, token uuid, status text, fence_token bigint)
language plpgsql security definer
set search_path = pg_catalog, public
as $$
begin
  if p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot not in ('daily', 'intraday', 'aggressive')
     or p_token is null
     or not exists (
       select 1 from public.bot_entry_executor_identities e
       where e.bot = p_bot and e.db_login = session_user::name
     ) then
    raise exception 'claim proof identity not authorized' using errcode = '42501';
  end if;
  return query
    select i.bot, i.coin, i.token, i.status, i.fence_token
    from public.bot_entry_intents i
    where i.coin = p_coin and i.bot = p_bot and i.token = p_token;
end;
$$;
revoke all on function public.read_bot_entry_claim_proof(text,text,uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.read_bot_entry_claim_proof(text,text,uuid)
  to bot_entry_executor_trial;
