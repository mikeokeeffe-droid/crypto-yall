-- STAGING ONLY: independent reconciler identity, not deployed.
do $$
begin
  if not exists (select 1 from pg_roles where rolname='bot_reconciler') then
    create role bot_reconciler nologin;
  end if;
end $$;
-- Dedicated migration owner executes privileged routines; callers get no
-- direct table access to intent, reservation, ownership, or identity rows.
alter function public.record_bot_position_owner(text,text,uuid,text,boolean)
  security definer set search_path = pg_catalog, public;
alter function public.mark_bot_position_closed(text,text,uuid,boolean,boolean)
  security definer set search_path = pg_catalog, public;
alter function public.release_closed_bot_position(text,text,uuid,boolean,boolean)
  security definer set search_path = pg_catalog, public;
alter function public.release_resolved_bot_entry_intent(
  text,text,uuid,text,text,boolean,boolean,boolean)
  security definer set search_path = pg_catalog, public;
alter function public.get_bot_entry_reconciliation_intent(text,text,uuid)
  security definer set search_path = pg_catalog, public;
alter function public.is_bot_reconciler_identity(text)
  security definer set search_path = pg_catalog, public;
revoke all on public.bot_position_owners from bot_reconciler;
revoke all on public.bot_entry_intents from bot_reconciler;
revoke all on public.bot_entry_reservations from bot_reconciler;
revoke all on public.bot_reconciler_identities from bot_reconciler;
grant usage on schema public to bot_reconciler;
revoke create on schema public from bot_reconciler;
grant execute on function public.record_bot_position_owner(text,text,uuid,text,boolean)
  to bot_reconciler;
grant execute on function public.mark_bot_position_closed(text,text,uuid,boolean,boolean)
  to bot_reconciler;
grant execute on function public.release_closed_bot_position(text,text,uuid,boolean,boolean)
  to bot_reconciler;
grant execute on function public.release_resolved_bot_entry_intent(
  text,text,uuid,text,text,boolean,boolean,boolean)
  to bot_reconciler;
grant execute on function public.get_bot_entry_reconciliation_intent(
  text,text,uuid)
  to bot_reconciler;
grant execute on function public.is_bot_reconciler_identity(text)
  to bot_reconciler;
