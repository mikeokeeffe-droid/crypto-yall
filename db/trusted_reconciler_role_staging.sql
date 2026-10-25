-- STAGING ONLY. Run after entry and owner migrations, never in production unreviewed.
-- Dedicated reconciler role: not a member of routine service_role.
do $$
begin
  if not exists (select 1 from pg_roles where rolname='bot_reconciler') then
    create role bot_reconciler nologin;
  end if;
end $$;

grant usage on schema public to bot_reconciler;
grant select on public.bot_entry_intents, public.bot_entry_reservations,
  public.bot_position_owners to bot_reconciler;
grant update on public.bot_entry_intents to bot_reconciler;
grant delete on public.bot_entry_intents, public.bot_entry_reservations,
  public.bot_position_owners to bot_reconciler;
grant insert, update on public.bot_position_owners to bot_reconciler;
grant execute on function public.record_bot_position_owner(text,text,uuid,text,boolean)
  to bot_reconciler;
grant execute on function public.mark_bot_position_closed(text,text,uuid,boolean,boolean)
  to bot_reconciler;
grant execute on function public.release_closed_bot_position(text,text,uuid,boolean,boolean)
  to bot_reconciler;
-- Direct DML remains possible for this privileged role. In production, use
-- narrowly scoped SECURITY DEFINER routines and remove direct DML grants.
