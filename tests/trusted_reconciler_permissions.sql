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

-- Explicitly protect intent resolution: no routine executor can clear the
-- durable unresolved-order fence, and reconciliation cannot do so until
-- a separately reviewed authorization path is implemented.
do $$
begin
 if has_function_privilege('service_role',
   'public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE')
 then raise exception 'routine service role can resolve durable intent'; end if;
 if has_function_privilege('bot_reconciler',
   'public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE')
 then raise exception 'reconciler intent resolution is not yet approved'; end if;
 if has_function_privilege('service_role',
   'public.release_closed_bot_position(text,text,uuid,boolean,boolean)','EXECUTE')
 then raise exception 'routine service role can release verified ownership'; end if;
end $$;

-- The reconciler identity must not be inherited by ordinary client roles.
do $$
begin
 if pg_has_role('anon','bot_reconciler','MEMBER')
    or pg_has_role('authenticated','bot_reconciler','MEMBER') then
   raise exception 'client role inherits reconciler privileges';
 end if;
 if has_function_privilege('anon',
   'public.release_closed_bot_position(text,text,uuid,boolean,boolean)','EXECUTE')
    or has_function_privilege('authenticated',
   'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)','EXECUTE') then
   raise exception 'client role can invoke reconciler mutation RPC';
 end if;
end $$;
