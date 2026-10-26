-- DISPOSABLE POSTGRESQL ONLY. Run after restricted_grants_trial.sql.
do $$
begin
  if has_table_privilege('service_role', 'public.bot_entry_reservations', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'DELETE')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'DELETE') then
    raise exception 'service_role retains direct reservation/intent DML';
  end if;
  if has_function_privilege('service_role', 'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('service_role', 'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('service_role', 'public.release_bot_entry(text,text,uuid)', 'EXECUTE') then
    raise exception 'service_role retains routine reservation RPC access';
  end if;
  if not has_function_privilege('bot_entry_executor_trial', 'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE') then
    raise exception 'trial executor lost scoped reservation RPC';
  end if;
end $$;

-- Verify effective permissions under the actual database role, not only via
-- role-name introspection. Run only against disposable PostgreSQL.
begin;
set local role service_role;
do $$
begin
  if has_table_privilege(current_user, 'public.bot_entry_reservations', 'INSERT')
     or has_table_privilege(current_user, 'public.bot_entry_intents', 'UPDATE')
     or has_function_privilege(current_user,
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE') then
    raise exception 'service_role still has effective entry mutation access';
  end if;
end $$;
rollback;

begin;
set local role bot_entry_executor_trial;
do $$
begin
  if has_table_privilege(current_user, 'public.bot_entry_reservations', 'INSERT')
     or has_table_privilege(current_user, 'public.bot_entry_intents', 'DELETE')
     or not has_function_privilege(current_user,
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege(current_user,
       'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE') then
    raise exception 'trial executor role privileges exceed scoped RPC access';
  end if;
end $$;
rollback;

-- Assert the trusted reconciler's effective role cannot write protected tables
-- directly and cannot borrow the routine executor's entry RPC privileges.
begin;
set local role bot_reconciler;
do $$
begin
  if has_table_privilege(current_user, 'public.bot_position_owners', 'UPDATE')
     or has_table_privilege(current_user, 'public.bot_entry_intents', 'DELETE')
     or has_table_privilege(current_user, 'public.bot_entry_reservations', 'INSERT')
     or has_function_privilege(current_user,
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or not has_function_privilege(current_user,
       'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE') then
    raise exception 'reconciler role has unexpected effective privileges';
  end if;
end $$;
rollback;
