-- Disposable PostgreSQL CI only: not a production migration or order adapter.
-- Demonstrate an atomic *pre-submission* record tied to an authenticated bot.
-- A saved intent is not proof that an exchange order was sent or filled.
create table public.ci_scoped_entry_intents (
  intent_token uuid primary key references public.ci_scoped_entry_claims(token),
  bot text not null check (bot in ('daily','intraday','aggressive')),
  environment text not null check (environment in ('mainnet','testnet')),
  effective_account text not null check (effective_account ~ '^0x[0-9a-f]{40}$'),
  dex text not null check (dex = ''),
  coin text not null check (coin ~ '^[A-Z0-9]+$'),
  action text not null check (action in ('open_long','open_short')),
  requested_size numeric not null check (
    requested_size > 0
    and requested_size::text not in ('NaN','Infinity','-Infinity')
  ),
  status text not null default 'pending' check (status = 'pending'),
  created_at timestamptz not null default now(),
  unique (environment,effective_account,dex,coin)
);
revoke all on public.ci_scoped_entry_intents
  from public, anon, authenticated, service_role, bot_entry_executor_trial;

-- PostgreSQL executes this function atomically inside the caller transaction.
-- A failure creating the immutable pre-submit intent rolls back its claim too.
-- No expiry, cleanup, order action, SDK, or trading authorization.
create function public.ci_record_pre_submit_intent(
  p_environment text, p_account text, p_dex text, p_coin text,
  p_bot text, p_token uuid, p_action text, p_size numeric
) returns table(recorded boolean, intent_id uuid, fencing bigint)
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_fence bigint;
begin
  if p_environment not in ('mainnet','testnet')
     or p_account is null or p_account !~ '^0x[0-9a-f]{40}$'
     or p_dex is distinct from ''
     or p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot not in ('daily','intraday','aggressive')
     or p_token is null
     or p_action not in ('open_long','open_short')
     or p_size is null or p_size <= 0
     or p_size::text in ('NaN','Infinity','-Infinity')
     or not exists (
       select 1 from public.bot_entry_executor_identities e
       join public.ci_scoped_executor_accounts a
         on a.db_login = e.db_login
       where e.bot = p_bot and e.db_login = session_user::name
         and a.environment = p_environment
         and a.effective_account = p_account
     )
  then
    raise exception 'invalid or unauthorized pre-submit intent'
      using errcode = '42501';
  end if;

  insert into public.ci_scoped_entry_claims
    (environment,effective_account,dex,coin,bot,token)
  values (p_environment,p_account,p_dex,p_coin,p_bot,p_token)
  on conflict do nothing returning fence_token into v_fence;

  if v_fence is null then
    return query select false, null::uuid, null::bigint;
    return;
  end if;

  insert into public.ci_scoped_entry_intents
    (intent_token,bot,environment,effective_account,dex,coin,action,requested_size)
  values (p_token,p_bot,p_environment,p_account,p_dex,p_coin,p_action,p_size);
  return query select true, p_token, v_fence;
end;
$$;
revoke all on function public.ci_record_pre_submit_intent(
  text,text,text,text,text,uuid,text,numeric
) from public, anon, authenticated, service_role;
grant execute on function public.ci_record_pre_submit_intent(
  text,text,text,text,text,uuid,text,numeric
) to bot_entry_executor_trial;
