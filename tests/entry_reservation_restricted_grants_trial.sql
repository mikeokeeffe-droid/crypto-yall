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
