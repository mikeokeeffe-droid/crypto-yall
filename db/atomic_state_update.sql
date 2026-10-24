-- STAGING ONLY: apply and verify before connecting any live bot.
-- Atomic compare-and-swap: the backup and update succeed or fail together.
-- Revoke RPC execution from public roles. Use trusted service credentials only.
create or replace function public.cas_bot_state(
  p_bot text,
  p_expected_revision bigint,
  p_state jsonb
)
returns bigint
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_revision bigint;
begin
  if p_bot not in ('aggressive', 'intraday', 'daily') or
     p_state is null or jsonb_typeof(p_state) <> 'object' then
    raise exception 'Invalid bot or state';
  end if;

  -- Lock row so two writers cannot both succeed with the same revision.
  select revision into v_revision
  from public.bot_state
  where bot = p_bot
  for update;

  if not found then
    raise exception 'Missing state for bot %', p_bot;
  end if;
  if v_revision <> p_expected_revision then
    raise exception 'State revision conflict for bot %', p_bot;
  end if;

  insert into public.bot_state_backups (bot, revision, state)
  select bot, revision, state from public.bot_state where bot = p_bot;

  update public.bot_state
  set state = p_state, revision = revision + 1, updated_at = now()
  where bot = p_bot
  returning revision into v_revision;

  return v_revision;
end;
$$;

revoke all on function public.cas_bot_state(text,bigint,jsonb) from public, anon, authenticated;
grant execute on function public.cas_bot_state(text,bigint,jsonb) to service_role;
