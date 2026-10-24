-- Runs ONLY against an isolated CI PostgreSQL instance. Never production.
\set ON_ERROR_STOP on
CREATE TABLE public.bot_state_snapshots (
 snapshot_id uuid primary key,
 bot text not null,
 source_gist_id text not null,
 source_gist_version text not null,
 source_sha256 text not null,
 state jsonb not null,
 verified boolean not null,
 verified_at timestamptz
);
INSERT INTO public.bot_state_snapshots VALUES
 ('00000000-0000-0000-0000-000000000001','aggressive','g1','v1',repeat('a',64),'{"cash":1}',true,now()),
 ('00000000-0000-0000-0000-000000000002','intraday','g2','v1',repeat('b',64),'{"cash":2}',true,now()),
 ('00000000-0000-0000-0000-000000000003','daily','g3','v1',repeat('c',64),'{"cash":3}',true,now()),
 ('00000000-0000-0000-0000-000000000004','daily','g3','v2',repeat('d',64),'{"cash":4}',false,null);

-- Forced failure on the third insert must roll back all prior inserts.
CREATE FUNCTION public.reject_daily_test() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.bot='daily' THEN RAISE EXCEPTION 'simulated third insert failure'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER reject_daily BEFORE INSERT ON public.bot_state
FOR EACH ROW EXECUTE FUNCTION public.reject_daily_test();

DO $$
BEGIN
 BEGIN
  PERFORM public.initialize_bot_states_from_snapshots(
   '00000000-0000-0000-0000-000000000001',
   '00000000-0000-0000-0000-000000000002',
   '00000000-0000-0000-0000-000000000003');
  RAISE EXCEPTION 'Expected simulated failure';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Expected simulated failure' THEN RAISE; END IF;
 END;
 IF (SELECT count(*) FROM public.bot_state)<>0 THEN
  RAISE EXCEPTION 'Rollback failed: partial rows remain';
 END IF;
END $$;
DROP TRIGGER reject_daily ON public.bot_state;
DROP FUNCTION public.reject_daily_test();

-- Unverified snapshot must not initialize anything.
DO $$
BEGIN
 BEGIN
  PERFORM public.initialize_bot_states_from_snapshots(
   '00000000-0000-0000-0000-000000000001',
   '00000000-0000-0000-0000-000000000002',
   '00000000-0000-0000-0000-000000000004');
  RAISE EXCEPTION 'Expected unverified rejection';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Expected unverified rejection' THEN RAISE; END IF;
 END;
 IF (SELECT count(*) FROM public.bot_state)<>0 THEN
  RAISE EXCEPTION 'Unverified snapshot changed state';
 END IF;
END $$;

SELECT public.initialize_bot_states_from_snapshots(
 '00000000-0000-0000-0000-000000000001',
 '00000000-0000-0000-0000-000000000002',
 '00000000-0000-0000-0000-000000000003');
DO $$
BEGIN
 IF (SELECT count(*) FROM public.bot_state)<>3 THEN
  RAISE EXCEPTION 'Expected exactly three initialized rows';
 END IF;
 IF (SELECT count(*) FROM public.bot_state WHERE revision=1)<>3 THEN
  RAISE EXCEPTION 'Unexpected revision';
 END IF;
 BEGIN
  PERFORM public.initialize_bot_states_from_snapshots(
   '00000000-0000-0000-0000-000000000001',
   '00000000-0000-0000-0000-000000000002',
   '00000000-0000-0000-0000-000000000003');
  RAISE EXCEPTION 'Expected overwrite rejection';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='Expected overwrite rejection' THEN RAISE; END IF;
 END;
 IF (SELECT count(*) FROM public.bot_state)<>3 THEN
  RAISE EXCEPTION 'Reinitialization changed row count';
 END IF;
END $$;
