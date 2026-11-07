-- Disposable PostgreSQL only. Run after the restricted-grants trial.
-- Verify effective permissions of each distinct DB principal.
do $$
begin
  if has_function_privilege('bot_entry_executor_trial',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_function_privilege('bot_entry_executor_trial',
       'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
     or has_function_privilege('bot_entry_executor_trial',
       'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
  then
    raise exception 'executor can invoke reconciler-only position mutations';
  end if;
  if has_function_privilege('bot_reconciler',
       'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('bot_reconciler',
       'public.release_bot_entry(text,text,uuid)', 'EXECUTE')
  then
    raise exception 'reconciler can invoke executor-only reservation mutations';
  end if;
  if has_function_privilege('service_role',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
  then
    raise exception 'service_role can invoke trusted reconciler mutations';
  end if;
end $$;

-- Exercise effective role identities, not only role-name lookups.
begin;
set local role bot_entry_executor_trial;
do $$
begin
  if has_function_privilege(current_user,
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_function_privilege(current_user,
       'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
     or has_function_privilege(current_user,
       'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
     or has_table_privilege(current_user, 'public.bot_position_owners', 'UPDATE')
  then
    raise exception 'effective executor identity crosses reconciler boundary';
  end if;
end $$;
rollback;

begin;
set local role bot_reconciler;
do $$
begin
  if has_function_privilege(current_user,
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege(current_user,
       'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege(current_user,
       'public.release_bot_entry(text,text,uuid)', 'EXECUTE')
     or has_function_privilege(current_user,
       'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_table_privilege(current_user, 'public.bot_entry_reservations', 'UPDATE')
     or has_table_privilege(current_user, 'public.bot_entry_intents', 'INSERT')
  then
    raise exception 'effective reconciler identity crosses executor boundary';
  end if;
end $$;
rollback;
