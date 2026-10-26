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

-- FAIL-CLOSED STAGING POLICY. No service_role direct DML or reservation RPCs.
-- Apply only in an isolated staging database after checking role inheritance,
-- function ownership, default PUBLIC privileges and every dependent caller.
-- Production rollout requires dedicated executor and reconciler DB identities.
grant usage on schema public to service_role;
grant select on public.bot_entry_reservations to service_role;
grant select on public.bot_entry_intents to service_role;
revoke insert, update, delete on public.bot_entry_reservations from service_role;
revoke insert, update, delete on public.bot_entry_intents from service_role;
revoke execute on function public.try_reserve_bot_entry(text,text,uuid,integer)
  from public, service_role;
revoke execute on function public.claim_bot_entry_intent(text,text,uuid)
  from public, service_role;
revoke execute on function public.release_bot_entry(text,text,uuid)
  from public, service_role;
revoke execute on function public.resolve_bot_entry_intent(text,text,uuid)
  from public, service_role;
-- Intentionally grants no replacement writer. Reservation writes stay unavailable
-- until separate scoped principals are provisioned and tested end-to-end.
