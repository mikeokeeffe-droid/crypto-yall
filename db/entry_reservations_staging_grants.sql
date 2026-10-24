-- STAGING ONLY. Apply only after inspecting the existing roles and grants.
-- Keep service-role secrets exclusively in trusted server-side environments.
revoke all on public.bot_entry_reservations from public, anon, authenticated;
revoke all on public.bot_entry_intents from public, anon, authenticated;
revoke all on function public.try_reserve_bot_entry(text,text,uuid,integer)
  from public, anon, authenticated;
revoke all on function public.claim_bot_entry_intent(text,text,uuid)
  from public, anon, authenticated;
revoke all on function public.release_bot_entry(text,text,uuid)
  from public, anon, authenticated;
revoke all on function public.resolve_bot_entry_intent(text,text,uuid)
  from public, anon, authenticated;

grant usage on schema public to service_role;
grant select, insert, update, delete on public.bot_entry_reservations to service_role;
grant select, insert, update, delete on public.bot_entry_intents to service_role;
grant execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  to service_role;
grant execute on function public.claim_bot_entry_intent(text,text,uuid)
  to service_role;
grant execute on function public.release_bot_entry(text,text,uuid)
  to service_role;
-- Deliberately do not grant resolve_bot_entry_intent to routine executors.
-- A separate trusted reconciliation operator must verify exchange state first.
