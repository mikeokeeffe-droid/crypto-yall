-- Disposable GitHub Actions safety_test database ONLY.
-- Demonstrates account-scoped atomic admission. Not a production migration.
-- No live bot uses this table/function. No order placement or claim release.
create table public.ci_scoped_executor_accounts (
  db_login name not null,
  environment text not null check (environment in ('mainnet','testnet')),
  effective_account text not null
    check (effective_account ~ '^0x[0-9a-f]{40}$'),
  primary key (db_login, environment, effective_account)
);

create table public.ci_scoped_entry_claims (
  environment text not null check (environment in ('mainnet','testnet')),
  effective_account text not null
    check (effective_account ~ '^0x[0-9a-f]{40}$'),
  dex text not null check (dex = ''),
  coin text not null check (coin ~ '^[A-Z0-9]+$'),
  bot text not null check (bot in ('daily','intraday','aggressive')),
  token uuid not null unique,
  status text not null default 'pending' check
    (status in ('pending','submitted','uncertain','filled')),
  fence_token bigint generated always as identity,
  created_at timestamptz not null default now(),
  primary key (environment, effective_account, dex, coin)
);
revoke all on public.ci_scoped_executor_accounts, public.ci_scoped_entry_claims
  from public, anon, authenticated, service_role, bot_entry_executor_trial;

-- Atomic PK constraint serializes simultaneous claims of the same scope.
-- No expiry, automatic release, ownership transfer or live order submission.
create function public.ci_claim_scoped_entry(
  p_environment text, p_account text, p_dex text, p_coin text,
  p_bot text, p_token uuid
) returns table(accepted boolean, claim_id uuid, fencing bigint)
language plpgsql security definer
set search_path = pg_catalog, public
as $$
begin
  if p_environment not in ('mainnet','testnet')
     or p_account is null or p_account !~ '^0x[0-9a-f]{40}$'
     or p_dex is distinct from ''
     or p_coin is null or p_coin !~ '^[A-Z0-9]+$'
     or p_bot not in ('daily','intraday','aggressive')
     or p_token is null
     or not exists (
       select 1 from public.bot_entry_executor_identities e
       join public.ci_scoped_executor_accounts a
         on a.db_login=e.db_login
       where e.bot=p_bot and e.db_login=session_user::name
         and a.environment=p_environment
         and a.effective_account=p_account
     )
  then
    raise exception 'unrecognized or unauthorized scoped entry identity'
      using errcode='42501';
  end if;
  return query
    with new_claim as (
      insert into public.ci_scoped_entry_claims
        (environment,effective_account,dex,coin,bot,token)
      values (p_environment,p_account,p_dex,p_coin,p_bot,p_token)
      on conflict do nothing
      returning token,fence_token
    )
    select true, c.token, c.fence_token from new_claim c;
  if not found then
    return query select false, null::uuid, null::bigint;
  end if;
end;
$$;
revoke all on function public.ci_claim_scoped_entry(
  text,text,text,text,text,uuid
) from public, anon, authenticated, service_role;
grant execute on function public.ci_claim_scoped_entry(
  text,text,text,text,text,uuid
) to bot_entry_executor_trial;

-- Synthetic account allowlist. Only this disposable CI administrator
-- populates it; bot logins have NO direct read/write access.
insert into public.ci_scoped_executor_accounts
  (db_login, environment, effective_account)
values
  ('entry_login_daily','mainnet','0x1111111111111111111111111111111111111111'),
  ('entry_login_intraday','mainnet','0x1111111111111111111111111111111111111111'),
  ('entry_login_aggressive','mainnet','0x1111111111111111111111111111111111111111'),
  ('entry_login_intraday','mainnet','0x2222222222222222222222222222222222222222'),
  ('entry_login_daily','testnet','0x1111111111111111111111111111111111111111');
