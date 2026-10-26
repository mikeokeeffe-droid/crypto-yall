-- READ-ONLY PREFLIGHT. Run manually against the intended staging database
-- using a migration/admin connection; never use as a migration or grant script.
-- Stops on any unexpected effective privileges. Does not provision identities.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'bot_entry_executor_trial')
     or not exists (select 1 from pg_roles where rolname = 'bot_reconciler') then
    raise exception 'missing separate executor or reconciler database role';
  end if;
  if exists (
    select 1 from pg_auth_members m
    join pg_roles child on child.oid = m.member
    join pg_roles parent on parent.oid = m.roleid
    where child.rolname in ('bot_entry_executor_trial', 'bot_reconciler')
      and parent.rolname in ('service_role', 'postgres', 'supabase_admin')
  ) then
    raise exception 'restricted role inherits a privileged database role';
  end if;
  if has_table_privilege('service_role', 'public.bot_entry_reservations', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'UPDATE')
     or has_function_privilege('service_role',
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
  then
    raise exception 'service_role has forbidden effective mutation privilege';
  end if;
  if not has_function_privilege('bot_entry_executor_trial',
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('bot_entry_executor_trial',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_table_privilege('bot_entry_executor_trial',
       'public.bot_entry_reservations', 'INSERT')
  then
    raise exception 'executor role is not restricted to entry RPCs';
  end if;
  if not has_function_privilege('bot_reconciler',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_function_privilege('bot_reconciler',
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_table_privilege('bot_reconciler',
       'public.bot_position_owners', 'UPDATE')
  then
    raise exception 'reconciler role is not restricted to position RPCs';
  end if;
end $$;
