-- Isolated PostgreSQL transaction checks; no production connections.
begin;
do $$
declare t uuid := '11111111-1111-4111-8111-111111111111';
begin
  if not public.try_reserve_bot_entry('BTC','aggressive',t,120) then raise exception 'reserve failed'; end if;
  if not public.claim_bot_entry_intent('BTC','aggressive',t) then raise exception 'intent failed'; end if;
  if public.record_bot_position_owner('BTC','aggressive',t,'oid-1',false) then raise exception 'unverified fill accepted'; end if;
  if public.record_bot_position_owner('BTC','intraday',t,'oid-1',true) then raise exception 'wrong bot accepted'; end if;
  if not public.record_bot_entry_order('BTC','aggressive',t,'oid-1',100000,1,'submitted') then raise exception 'order identity record failed'; end if;
  if public.record_bot_position_owner('BTC','aggressive',t,'wrong-order',true) then raise exception 'mismatched order accepted'; end if;
  if not public.record_bot_position_owner('BTC','aggressive',t,'oid-1',true) then raise exception 'handoff failed'; end if;
  if public.try_reserve_bot_entry('BTC','daily','22222222-2222-4222-8222-222222222222',120) then raise exception 'owner fence bypassed'; end if;
  if public.mark_bot_position_closed('BTC','aggressive',t,false,true) then raise exception 'unverified close accepted'; end if;
  if not public.mark_bot_position_closed('BTC','aggressive',t,true,true) then raise exception 'close failed'; end if;
  if public.release_closed_bot_position('BTC','aggressive',t,true,false) then raise exception 'open orders bypassed'; end if;
  if not public.mark_bot_position_closed('BTC','aggressive',t,true,true) then raise exception 'close retry failed'; end if;
  if not public.release_closed_bot_position('BTC','aggressive',t,true,true) then raise exception 'release failed'; end if;
  if not public.try_reserve_bot_entry('BTC','daily','22222222-2222-4222-8222-222222222222',120) then raise exception 'new reservation failed after release'; end if;
end $$;
rollback;
