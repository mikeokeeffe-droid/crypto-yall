-- Assert role separation on disposable staging PostgreSQL.
do $$
begin
 if not has_function_privilege('bot_reconciler',
   'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
 then raise exception 'reconciler missing handoff permission'; end if;
 if not has_function_privilege('bot_reconciler',
   'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
 then raise exception 'reconciler missing close permission'; end if;
 if not has_function_privilege('bot_reconciler',
   'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
 then raise exception 'reconciler missing release permission'; end if;
 if has_table_privilege('bot_reconciler','public.bot_position_owners','INSERT')
 or has_table_privilege('bot_reconciler','public.bot_position_owners','UPDATE')
 or has_table_privilege('bot_reconciler','public.bot_position_owners','DELETE')
 or has_table_privilege('bot_reconciler','public.bot_entry_intents','UPDATE')
 or has_table_privilege('bot_reconciler','public.bot_entry_intents','DELETE')
 then raise exception 'reconciler must not have direct mutation privileges'; end if;
 if pg_has_role('service_role','bot_reconciler','MEMBER')
 then raise exception 'routine service role must not inherit reconciler role'; end if;
end $$;
