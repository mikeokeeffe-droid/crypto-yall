-- Disposable database only. A role with RPC access must not get table writes.
begin;
set local role bot_entry_executor_trial;
do $$ begin
 if has_table_privilege(current_user,'public.bot_entry_reservations','INSERT')
    or has_table_privilege(current_user,'public.bot_entry_reservations','UPDATE')
    or has_table_privilege(current_user,'public.bot_entry_reservations','DELETE')
    or has_table_privilege(current_user,'public.bot_entry_intents','INSERT')
    or has_table_privilege(current_user,'public.bot_entry_intents','UPDATE')
    or has_table_privilege(current_user,'public.bot_entry_intents','DELETE') then
   raise exception 'trial executor has direct table mutation privileges';
 end if;
 if has_function_privilege(current_user,
    'public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE') then
   raise exception 'trial executor can resolve durable intent';
 end if;
 if not has_function_privilege(current_user,
    'public.try_reserve_bot_entry(text,text,uuid,integer)','EXECUTE') then
   raise exception 'trial executor lacks RPC access';
 end if;
end $$;
do $$ declare tok uuid := '11111111-1111-4111-8111-111111111111';
begin
 if not public.try_reserve_bot_entry('TRIALCOIN','intraday',tok,120) then
   raise exception 'trial reservation failed';
 end if;
 if not public.claim_bot_entry_intent('TRIALCOIN','intraday',tok) then
   raise exception 'trial claim failed';
 end if;
 if not public.record_bot_entry_order(
    'TRIALCOIN','intraday',tok,'trial-order-1',100000,1,'submitted') then
   raise exception 'trial order identity record failed';
 end if;
 if public.try_reserve_bot_entry('TRIALCOIN','aggressive',
    '22222222-2222-4222-8222-222222222222',120) then
   raise exception 'cross-bot reservation bypassed durable intent';
 end if;
end $$;
rollback;
