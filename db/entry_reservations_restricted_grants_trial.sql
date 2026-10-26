-- DISPOSABLE POSTGRESQL TRIAL ONLY; not a production migration.
-- Apply after entry_reservation_least_privilege_trial.sql.
-- This intentionally removes the known direct-table-DML bypass for service_role.
-- IMPORTANT: routine service_role RPC access is also removed; do not deploy
-- until every executor uses a separately authenticated, scoped RPC principal.
revoke insert, update, delete on public.bot_entry_reservations
  from service_role;
revoke insert, update, delete on public.bot_entry_intents
  from service_role;
revoke execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  from service_role;
revoke execute on function public.claim_bot_entry_intent(text,text,uuid)
  from service_role;
revoke execute on function public.release_bot_entry(text,text,uuid)
  from service_role;
-- Keep the trial role as the only explicitly authorized routine writer via RPC.
-- Neither trial role nor service_role may resolve durable intents.
revoke execute on function public.resolve_bot_entry_intent(text,text,uuid)
  from service_role, bot_entry_executor_trial;
