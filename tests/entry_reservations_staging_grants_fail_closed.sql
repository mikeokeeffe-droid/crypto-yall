-- Disposable PostgreSQL only: verify the staging grants file itself,
-- before later trial migrations could mask a privilege regression.
do $$
begin
  if has_table_privilege('service_role','public.bot_entry_reservations','INSERT')
     or has_table_privilege('service_role','public.bot_entry_reservations','UPDATE')
     or has_table_privilege('service_role','public.bot_entry_reservations','DELETE')
     or has_table_privilege('service_role','public.bot_entry_intents','INSERT')
     or has_table_privilege('service_role','public.bot_entry_intents','UPDATE')
     or has_table_privilege('service_role','public.bot_entry_intents','DELETE')
     or has_function_privilege('service_role','public.try_reserve_bot_entry(text,text,uuid,integer)','EXECUTE')
     or has_function_privilege('service_role','public.claim_bot_entry_intent(text,text,uuid)','EXECUTE')
     or has_function_privilege('service_role','public.release_bot_entry(text,text,uuid)','EXECUTE')
     or has_function_privilege('service_role','public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE')
  then
    raise exception 'staging grants permit service_role reservation mutation';
  end if;
end $$;
begin;
set local role service_role;
do $$
begin
  if has_table_privilege(current_user,'public.bot_entry_reservations','INSERT')
     or has_table_privilege(current_user,'public.bot_entry_intents','UPDATE')
     or has_table_privilege(current_user,'public.bot_entry_executor_identities','SELECT')
     or has_table_privilege(current_user,'public.bot_entry_executor_identities','INSERT')
     or has_function_privilege(current_user,'public.try_reserve_bot_entry(text,text,uuid,integer)','EXECUTE')
  then
    raise exception 'service_role effective permissions exceed read-only staging policy';
  end if;
end $$;
rollback;
