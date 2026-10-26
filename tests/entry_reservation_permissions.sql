-- Disposable PostgreSQL only; check least-privilege service-role contract.
do $$
begin
  if has_function_privilege('anon',
      'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
      'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE') then
    raise exception 'Untrusted role has reservation RPC permission';
  end if;
  if not has_function_privilege('service_role',
      'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
      'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE') then
    raise exception 'Trusted role missing entry RPC permission';
  end if;
end $$;

-- Document current staging exposure explicitly. This is an expected-risk
-- regression test, not proof that direct DML is safe for production.
do $$
begin
  if not has_table_privilege('service_role',
      'public.bot_entry_intents', 'INSERT, UPDATE, DELETE')
     or not has_table_privilege('service_role',
      'public.bot_entry_reservations', 'INSERT, UPDATE, DELETE') then
    raise exception 'Staging privilege contract changed; review DML bypass risk';
  end if;
  if has_table_privilege('anon', 'public.bot_entry_intents', 'INSERT')
     or has_table_privilege('authenticated', 'public.bot_entry_reservations', 'UPDATE') then
    raise exception 'Untrusted role has direct entry-table write access';
  end if;
end $$;
