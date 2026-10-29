-- ISOLATED POSTGRESQL EXPERIMENT ONLY. Not a production migration.
-- Run as disposable database owner after staging schemas have been loaded.
do $$ begin
  if not exists (select 1 from pg_roles where rolname='bot_entry_executor_trial') then
    create role bot_entry_executor_trial nologin;
  end if;
end $$;
grant usage on schema public to bot_entry_executor_trial;
revoke create on schema public from bot_entry_executor_trial;
revoke all on public.bot_entry_reservations, public.bot_entry_intents from bot_entry_executor_trial;
grant select on public.bot_entry_reservations, public.bot_entry_intents to bot_entry_executor_trial;
-- SECURITY DEFINER avoids granting table writes to the trial executor role.
alter function public.try_reserve_bot_entry(text,text,uuid,integer)
  security definer set search_path = pg_catalog, public;
alter function public.claim_bot_entry_intent(text,text,uuid)
  security definer set search_path = pg_catalog, public;
alter function public.release_bot_entry(text,text,uuid)
  security definer set search_path = pg_catalog, public;
revoke execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  from public, anon, authenticated;
revoke execute on function public.claim_bot_entry_intent(text,text,uuid)
  from public, anon, authenticated;
revoke execute on function public.release_bot_entry(text,text,uuid)
  from public, anon, authenticated;
grant execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  to bot_entry_executor_trial;
grant execute on function public.claim_bot_entry_intent(text,text,uuid)
  to bot_entry_executor_trial;
grant execute on function public.release_bot_entry(text,text,uuid)
  to bot_entry_executor_trial;
