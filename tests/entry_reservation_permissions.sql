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
