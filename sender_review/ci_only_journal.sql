-- Disposable PostgreSQL CI ONLY. Never run against production or Supabase.
-- No signing, exchange dispatch, DB lock release, account ownership, or
-- authenticated workload identity. This is a persistently blocked journal
-- design test, not a production migration or trading permission.
CREATE SCHEMA IF NOT EXISTS sender_review_ci;
REVOKE ALL ON SCHEMA sender_review_ci FROM PUBLIC;

CREATE TABLE IF NOT EXISTS sender_review_ci.scope_fences (
    environment text NOT NULL CHECK (environment = 'testnet'),
    account text NOT NULL CHECK (account ~ '^0x[0-9a-f]{40}$'),
    dex text NOT NULL DEFAULT '' CHECK (dex = ''),
    coin text NOT NULL CHECK (coin ~ '^[A-Z][A-Z0-9]{0,23}$'),
    fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
    active_nonce text CHECK (active_nonce ~ '^[0-9a-f]{32}$'),
    PRIMARY KEY (environment, account, dex, coin)
);

CREATE TABLE IF NOT EXISTS sender_review_ci.review_intents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    environment text NOT NULL CHECK (environment = 'testnet'),
    account text NOT NULL CHECK (account ~ '^0x[0-9a-f]{40}$'),
    dex text NOT NULL CHECK (dex = ''),
    coin text NOT NULL CHECK (coin ~ '^[A-Z][A-Z0-9]{0,23}$'),
    bot text NOT NULL CHECK (bot IN ('daily','intraday','aggressive')),
    action text NOT NULL CHECK (action IN ('open_long','open_short')),
    side text NOT NULL CHECK (side IN ('long','short')),
    request_nonce text NOT NULL CHECK (request_nonce ~ '^[0-9a-f]{32}$'),
    cloid text NOT NULL CHECK (cloid ~ '^0x[0-9a-f]{32}$'),
    rounded_size numeric(20,8) NOT NULL CHECK (rounded_size > 0 AND rounded_size <= 1000000),
    requested_leverage int NOT NULL CHECK (requested_leverage BETWEEN 1 AND 5),
    fence bigint NOT NULL CHECK (fence > 0),
    state text NOT NULL DEFAULT 'review_only' CHECK (state IN ('review_only','hold_unknown')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (environment, account, request_nonce),
    -- Composite identity must match evidence's intent ID + scope + bot.
    UNIQUE (id,environment,account,request_nonce,bot),
    UNIQUE (environment, account, cloid),
    UNIQUE (environment, account, dex, coin, fence),
    CHECK ((action = 'open_long' AND side = 'long') OR
           (action = 'open_short' AND side = 'short'))
);

CREATE TABLE IF NOT EXISTS sender_review_ci.review_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    intent_id bigint NOT NULL REFERENCES sender_review_ci.review_intents(id),
    kind text NOT NULL CHECK (kind IN ('review_recorded','unknown_held')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- This transaction-scoped function intentionally does not authenticate
-- any caller; only an isolated CI test harness may invoke it. The passed bot
-- and address are test metadata, NEVER proof of actual service credentials.
-- All results and all states are non-executable. There is NO release function.
CREATE OR REPLACE FUNCTION sender_review_ci.record_review_only(
    p_account text, p_bot text, p_coin text, p_action text,
    p_side text, p_size numeric, p_leverage integer, p_nonce text
) RETURNS TABLE(recorded boolean, assigned_fence bigint, reason text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
AS $$
DECLARE
    v_fence bigint;
    v_active text;
    v_id bigint;
    v_cloid text;
BEGIN
    IF (p_account IS NULL OR p_account !~ '^0x[0-9a-f]{40}$'
        OR p_bot IS NULL OR p_bot NOT IN ('daily','intraday','aggressive')
        OR p_coin IS NULL OR p_coin !~ '^[A-Z][A-Z0-9]{0,23}$'
        OR p_action IS NULL OR p_action NOT IN ('open_long','open_short')
        OR p_side IS NULL OR
            NOT ((p_action='open_long' AND p_side='long') OR
                 (p_action='open_short' AND p_side='short'))
        OR p_size IS NULL OR p_size <= 0 OR p_size > 1000000
        OR p_leverage IS NULL OR p_leverage NOT BETWEEN 1 AND 5
        OR p_nonce IS NULL OR p_nonce !~ '^[0-9a-f]{32}$') THEN
        RETURN QUERY SELECT false, 0::bigint, 'invalid-review-input'::text;
        RETURN;
    END IF;

    -- An account-scoped transaction lock rejects replay BEFORE creating
    -- a different coin's scope row. It is CI-only serialization, not
    -- exchange ownership or a deployable auth/signer control.
    -- Hash collisions merely serialize unrelated CI review requests.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('sender_review_ci|testnet|' || p_account, 0)
    );
    IF EXISTS (
       SELECT 1 FROM sender_review_ci.review_intents i
       WHERE i.environment='testnet'
         AND i.account=p_account AND i.request_nonce=p_nonce
    ) THEN
        RETURN QUERY SELECT false, 0::bigint, 'replayed-request-nonce'::text;
        RETURN;
    END IF;

    -- Row lock serializes all three bots and *all* requests for same scope.
    -- Never clear active_nonce in this CI implementation, even after crash.
    INSERT INTO sender_review_ci.scope_fences
        (environment, account, dex, coin)
    VALUES ('testnet', p_account, '', p_coin)
    ON CONFLICT DO NOTHING;

    SELECT s.fence, s.active_nonce INTO v_fence, v_active
      FROM sender_review_ci.scope_fences AS s
     WHERE s.environment='testnet' AND s.account=p_account
       AND s.dex='' AND s.coin=p_coin FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'missing scope lock';
    END IF;
    IF v_active IS NOT NULL THEN
        RETURN QUERY SELECT false, v_fence, 'active-scope-held'::text;
        RETURN;
    END IF;

    -- Replay is account-wide, not merely coin-local or bot-local. A concurrent
    -- same nonce on a different coin will be rejected by the UNIQUE constraint.
    IF EXISTS (
       SELECT 1 FROM sender_review_ci.review_intents i
       WHERE i.environment='testnet'
         AND i.account=p_account AND i.request_nonce=p_nonce
    ) THEN
        RETURN QUERY SELECT false, v_fence, 'replayed-request-nonce'::text;
        RETURN;
    END IF;
    v_cloid := '0x' || md5('ci-review-only|' || p_account || '|' || p_nonce);
    INSERT INTO sender_review_ci.review_intents
        (environment,account,dex,coin,bot,action,side,request_nonce,
         cloid,rounded_size,requested_leverage,fence)
    VALUES ('testnet',p_account,'',p_coin,p_bot,p_action,p_side,p_nonce,
            v_cloid,p_size,p_leverage,v_fence + 1)
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NULL THEN
        RETURN QUERY SELECT false, v_fence, 'duplicate-claim-held'::text;
        RETURN;
    END IF;

    UPDATE sender_review_ci.scope_fences s
       SET fence=v_fence+1, active_nonce=p_nonce
     WHERE s.environment='testnet' AND s.account=p_account
       AND s.dex='' AND s.coin=p_coin;
    INSERT INTO sender_review_ci.review_events(intent_id,kind)
    VALUES (v_id,'review_recorded');
    RETURN QUERY SELECT true, (v_fence+1), 'persisted-review-only-HOLD'::text;
END
$$;

-- Only direction permitted after recording: move to a more conservative HOLD.
-- No automatic retry, release, approval, reconcile or exchange call.
CREATE OR REPLACE FUNCTION sender_review_ci.hold_uncertain(
    p_account text, p_coin text, p_nonce text, p_fence bigint
) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
AS $$
DECLARE
    v_id bigint;
BEGIN
    UPDATE sender_review_ci.review_intents i
       SET state='hold_unknown'
     WHERE i.environment='testnet' AND i.account=p_account
       AND i.dex='' AND i.coin=p_coin AND i.request_nonce=p_nonce
       AND i.fence=p_fence AND i.state='review_only'
    RETURNING i.id INTO v_id;
    IF v_id IS NULL THEN
        RETURN false;
    END IF;
    INSERT INTO sender_review_ci.review_events(intent_id,kind)
    VALUES (v_id,'unknown_held');
    RETURN true;
END
$$;


-- Signed OIDC test fixture JTI consumption is durable across CI process
-- restarts. These rows are NOT server authentication or trading permission.
CREATE TABLE IF NOT EXISTS sender_review_ci.fixture_identity_receipts (
    environment text NOT NULL CHECK (environment = 'testnet'),
    account text NOT NULL CHECK (account ~ '^0x[0-9a-f]{40}$'),
    jti text NOT NULL CHECK (jti ~ '^[A-Za-z0-9_-]{6,128}$'),
    bot text NOT NULL CHECK (bot IN ('daily','intraday','aggressive')),
    request_nonce text NOT NULL CHECK (request_nonce ~ '^[0-9a-f]{32}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (environment, account, jti),
    UNIQUE (environment, account, request_nonce),
    -- Only the exact receipt identity+nonce may be cited as evidence.
    UNIQUE (environment,account,jti,bot,request_nonce)
);


-- Exact bytes of a signed TEST fixture and REVIEW-ONLY entry intent are
-- evidenced together. Hashes are audit evidence, NEVER a trading signature.
-- The references bind journal scope/nonce to evidence in the same database.
-- The real runtime cannot use this design as an authentication service.
CREATE TABLE IF NOT EXISTS sender_review_ci.fixture_request_evidence (
    intent_id bigint PRIMARY KEY
        REFERENCES sender_review_ci.review_intents(id) ON DELETE RESTRICT,
    environment text NOT NULL CHECK (environment = 'testnet'),
    account text NOT NULL CHECK (account ~ '^0x[0-9a-f]{40}$'),
    request_nonce text NOT NULL CHECK (request_nonce ~ '^[0-9a-f]{32}$'),
    bot text NOT NULL CHECK (bot IN ('daily','intraday','aggressive')),
    jti text NOT NULL CHECK (jti ~ '^[A-Za-z0-9_-]{6,128}$'),
    token_sha256 text NOT NULL CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    body_sha256 text NOT NULL CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
    body_length int NOT NULL CHECK (body_length BETWEEN 1 AND 1024),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    -- The intent id, scope, nonce and bot must all match ONE intent.
    FOREIGN KEY (intent_id,environment,account,request_nonce,bot)
        REFERENCES sender_review_ci.review_intents(
            id,environment,account,request_nonce,bot
        ),
    -- The signed-fixture receipt must match that exact identity and nonce.
    FOREIGN KEY (environment,account,jti,bot,request_nonce)
        REFERENCES sender_review_ci.fixture_identity_receipts(
            environment,account,jti,bot,request_nonce
        ),
    UNIQUE (environment,account,jti),
    UNIQUE (environment,account,request_nonce)
);


-- Block UPDATE/DELETE even by the disposable table owner in ordinary SQL.
-- CI truncation resets the whole transient test schema between test cases.
CREATE OR REPLACE FUNCTION sender_review_ci.reject_fixture_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'fixture evidence is append-only';
END
$$;
DROP TRIGGER IF EXISTS fixture_evidence_no_mutate
  ON sender_review_ci.fixture_request_evidence;
CREATE TRIGGER fixture_evidence_no_mutate
BEFORE UPDATE OR DELETE ON sender_review_ci.fixture_request_evidence
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.reject_fixture_evidence_mutation();

-- Preserve the CI review-only transition audit as append-only too.
-- Unlike fixture_request_evidence, review_events previously allowed owner
-- UPDATE/DELETE, which could conceal the recorded HOLD transition. These
-- triggers are defense-in-depth for the disposable harness, NOT proof
-- against a database superuser, table TRUNCATE, or production tampering.
DROP TRIGGER IF EXISTS review_events_no_mutate
  ON sender_review_ci.review_events;
CREATE TRIGGER review_events_no_mutate
BEFORE UPDATE OR DELETE ON sender_review_ci.review_events
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.reject_fixture_evidence_mutation();


REVOKE ALL ON ALL TABLES IN SCHEMA sender_review_ci FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA sender_review_ci FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA sender_review_ci FROM PUBLIC;
