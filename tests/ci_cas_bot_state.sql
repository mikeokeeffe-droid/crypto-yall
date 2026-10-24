\set ON_ERROR_STOP on
INSERT INTO public.bot_state(bot,state,revision) VALUES
('aggressive','{"x":1}',1),('intraday','{"x":2}',1),('daily','{"x":3}',1);
DO $$
DECLARE rev bigint;
BEGIN
 rev:=public.cas_bot_state('aggressive',1,'{"x":10}'::jsonb);
 IF rev<>2 THEN RAISE EXCEPTION 'revision not incremented'; END IF;
 IF (SELECT count(*) FROM public.bot_state_backups WHERE bot='aggressive' AND revision=1 AND state='{"x":1}'::jsonb)<>1 THEN
  RAISE EXCEPTION 'original backup missing';
 END IF;
 BEGIN
  PERFORM public.cas_bot_state('aggressive',1,'{"x":999}'::jsonb);
  RAISE EXCEPTION 'expected revision conflict';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='expected revision conflict' THEN RAISE; END IF;
 END;
 IF (SELECT state FROM public.bot_state WHERE bot='aggressive')<>'{"x":10}'::jsonb THEN
  RAISE EXCEPTION 'conflict overwrote state';
 END IF;
 IF (SELECT count(*) FROM public.bot_state_backups WHERE bot='aggressive')<>1 THEN
  RAISE EXCEPTION 'conflict created extra backup';
 END IF;
 BEGIN
  PERFORM public.cas_bot_state('daily',1,'[]'::jsonb);
  RAISE EXCEPTION 'expected invalid state rejection';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='expected invalid state rejection' THEN RAISE; END IF;
 END;
 IF (SELECT revision FROM public.bot_state WHERE bot='daily')<>1 THEN
  RAISE EXCEPTION 'invalid state modified revision';
 END IF;
END $$;
