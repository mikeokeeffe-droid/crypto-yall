-- Disposable PostgreSQL only; fail-closed service-role contract.
do $$
begin
  if has_function_privilege('anon',
      'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
      'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_table_privilege('anon',
      'public.bot_entry_executor_identities', 'SELECT')
     or has_table_privilege('authenticated',
      'public.bot_entry_executor_identities', 'INSERT') then
    raise exception 'Untrusted role has reservation RPC permission';
  end if;
  if has_function_privilege('service_role',
      'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('service_role',
      'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('service_role',
      'public.release_bot_entry(text,text,uuid)', 'EXECUTE') then
    raise exception 'service_role must not mutate reservations via RPC';
  end if;
  if has_table_privilege('service_role',
      'public.bot_entry_intents', 'INSERT')
     or has_table_privilege('service_role',
      'public.bot_entry_intents', 'UPDATE')
     or has_table_privilege('service_role',
      'public.bot_entry_intents', 'DELETE')
     or has_table_privilege('service_role',
      'public.bot_entry_reservations', 'INSERT')
     or has_table_privilege('service_role',
      'public.bot_entry_reservations', 'UPDATE')
     or has_table_privilege('service_role',
      'public.bot_entry_reservations', 'DELETE') then
    raise exception 'service_role direct reservation DML bypass';
  end if;
  if has_table_privilege('anon', 'public.bot_entry_intents', 'INSERT')
     or has_table_privilege('authenticated', 'public.bot_entry_reservations', 'UPDATE') then
    raise exception 'Untrusted role has direct entry-table write access';
  end if;
end $$;
