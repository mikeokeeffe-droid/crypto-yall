-- Run against disposable PostgreSQL only, after db/entry_reservations_staging.sql.
begin;
do $$
declare a uuid := '00000000-0000-4000-8000-000000000001';
        b uuid := '00000000-0000-4000-8000-000000000002';
begin
  if not public.try_reserve_bot_entry('BTC','aggressive',a,120) then
    raise exception 'first reservation failed';
  end if;
  if public.try_reserve_bot_entry('BTC','intraday',b,120) then
    raise exception 'competing bot acquired reserved BTC';
  end if;
  if public.release_bot_entry('BTC','intraday',b) then
    raise exception 'other bot released BTC';
  end if;
  if not public.try_reserve_bot_entry('BTC','aggressive',a,120) then
    raise exception 'idempotent renewal failed';
  end if;
  if not public.release_bot_entry('BTC','aggressive',a) then
    raise exception 'owner release failed';
  end if;
  if not public.try_reserve_bot_entry('BTC','intraday',b,120) then
    raise exception 'released BTC not available';
  end if;
  update public.bot_entry_reservations set expires_at=now()-interval '1 second'
    where coin='BTC';
  if not public.try_reserve_bot_entry('BTC','daily',a,120) then
    raise exception 'expired reservation not reclaimable';
  end if;
end $$;
rollback;
