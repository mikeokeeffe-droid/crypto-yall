-- Ensure ordinary executor service_role cannot call privileged reconciliation.
do $$
begin
  if has_function_privilege('service_role',
    'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE') then
    raise exception 'service_role must not mark positions closed';
  end if;
  if has_function_privilege('service_role',
    'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE') then
    raise exception 'service_role must not release closed positions';
  end if;
  if has_function_privilege('service_role',
    'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE') then
    raise exception 'routine executor must not self-certify fills';
  end if;
  if has_function_privilege('anon',
    'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE') then
    raise exception 'anon must not record owner';
  end if;
  if has_function_privilege('authenticated',
    'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE') then
    raise exception 'authenticated must not release owner';
  end if;
end $$;
