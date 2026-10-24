-- REVIEW ONLY. DO NOT APPLY UNTIL SOURCE FREEZE AND EXCHANGE RECONCILIATION.
-- This function initializes all three bot_state rows from explicitly selected,
-- previously verified snapshots in one transaction. No existing row is overwritten.
-- The calling operator must independently verify snapshot IDs and hashes.
create or replace function public.initialize_bot_states_from_snapshots(
  p_aggressive uuid,
  p_intraday uuid,
  p_daily uuid
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_count integer;
begin
  -- Serialize initialization attempts, including other calls to this function.
  perform pg_catalog.pg_advisory_xact_lock(8675309, 2401);

  if p_aggressive is null or p_intraday is null or p_daily is null
     or p_aggressive = p_intraday or p_aggressive = p_daily
     or p_intraday = p_daily then
    raise exception 'Three distinct snapshot IDs are required';
  end if;

  select count(*) into v_count
  from public.bot_state_snapshots s
  where (s.bot = 'aggressive' and s.snapshot_id = p_aggressive)
     or (s.bot = 'intraday' and s.snapshot_id = p_intraday)
     or (s.bot = 'daily' and s.snapshot_id = p_daily);
  if v_count <> 3 then
    raise exception 'One or more snapshots missing or assigned to wrong bot';
  end if;

  select count(*) into v_count
  from public.bot_state_snapshots s
  where s.verified = true
    and s.verified_at is not null
    and ((s.bot = 'aggressive' and s.snapshot_id = p_aggressive)
      or (s.bot = 'intraday' and s.snapshot_id = p_intraday)
      or (s.bot = 'daily' and s.snapshot_id = p_daily));
  if v_count <> 3 then
    raise exception 'All three snapshots must be verified';
  end if;

  -- Refuse partial initialization or any pre-existing state.
  if exists (select 1 from public.bot_state
             where bot in ('aggressive', 'intraday', 'daily')) then
    raise exception 'Existing bot_state row detected: no changes made';
  end if;

  insert into public.bot_state(bot, state, revision)
  select s.bot, s.state, 1
  from public.bot_state_snapshots s
  where (s.bot = 'aggressive' and s.snapshot_id = p_aggressive)
     or (s.bot = 'intraday' and s.snapshot_id = p_intraday)
     or (s.bot = 'daily' and s.snapshot_id = p_daily);

  get diagnostics v_count = row_count;
  if v_count <> 3 then
    raise exception 'Initialization incomplete: transaction rolled back';
  end if;
end;
$$;

revoke all on function public.initialize_bot_states_from_snapshots(uuid,uuid,uuid)
  from public, anon, authenticated;
grant execute on function public.initialize_bot_states_from_snapshots(uuid,uuid,uuid)
  to service_role;
