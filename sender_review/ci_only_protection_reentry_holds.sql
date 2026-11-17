-- CI-ONLY immutable synthetic protective-exit re-entry hold.
-- This is NOT a database migration, runtime identity grant, exchange
-- reconciliation, signer, protective exit, live position ownership proof or
-- trading authorization. Apply ONLY after ci_only_journal.sql, in the
-- disposable local sender_review_test PostgreSQL CI database. Never run on
-- Supabase or any other server or application database.
DO $guard$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'CI ONLY: wrong database';
    END IF;
END $guard$;

-- A successful signed TEST-fixture entry recording can be given an immutable
-- protection HOLD. This is explicitly an illustration of persistence, NOT
-- evidence of a real protective close: the underlying review_intents table
-- contains synthetic OPEN actions only, not exit-order provenance.
--
-- One permanent HOLD per account/dex/coin in this disposable database.
-- We deliberately provide no release/update API, timeout or signal-reset
-- path. A CI superuser/TRUNCATE can bypass ordinary controls, so this is
-- NOT proof of operational immutability.
CREATE TABLE IF NOT EXISTS sender_review_ci.simulated_protection_reentry_holds (
    environment text NOT NULL DEFAULT 'testnet' CHECK (environment='testnet'),
    account text NOT NULL CHECK (account ~ '^0x[0-9a-f]{40}$'),
    dex text NOT NULL DEFAULT '' CHECK (dex=''),
    coin text NOT NULL CHECK (coin ~ '^[A-Z][A-Z0-9]{0,23}$'),
    bot text NOT NULL CHECK (bot IN ('daily','intraday','aggressive')),
    side text NOT NULL CHECK (side IN ('long','short')),
    request_nonce text NOT NULL CHECK (request_nonce ~ '^[0-9a-f]{32}$'),
    fence bigint NOT NULL CHECK (fence>0),
    source_intent_id bigint NOT NULL,
    outcome_fixture text NOT NULL CHECK (outcome_fixture IN (
        'pending_exit','unknown_ack','partial_fill','claimed_closed'
    )),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (environment,account,dex,coin),
    UNIQUE (source_intent_id),
    FOREIGN KEY (source_intent_id,environment,account,request_nonce,bot)
      REFERENCES sender_review_ci.review_intents(
        id,environment,account,request_nonce,bot
      ) ON DELETE RESTRICT,
    FOREIGN KEY (environment,account,dex,coin)
      REFERENCES sender_review_ci.scope_fences(
        environment,account,dex,coin
      ) ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS protection_reentry_holds_no_mutate
    ON sender_review_ci.simulated_protection_reentry_holds;
CREATE TRIGGER protection_reentry_holds_no_mutate
BEFORE UPDATE OR DELETE ON sender_review_ci.simulated_protection_reentry_holds
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.reject_fixture_evidence_mutation();

-- A CI-only caller must present the SAME source entry identity as an
-- already journalled, fake signed request with matching body evidence.
-- This function does not cryptographically authenticate its own caller;
-- caller metadata and a fixture receipt are not operational identity.
-- All requests result in a permanent HOLD or denial. No release possible.
CREATE OR REPLACE FUNCTION sender_review_ci.record_ci_protection_reentry_hold(
    p_account text,p_bot text,p_coin text,p_side text,
    p_nonce text,p_fence bigint,p_outcome text
) RETURNS TABLE(recorded boolean,reason text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog
AS $fn$
DECLARE
    v_id bigint;
    v_inserted bigint;
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RETURN QUERY SELECT false,'wrong-disposable-database'::text;
        RETURN;
    END IF;
    IF (p_account IS NULL OR p_account !~ '^0x[0-9a-f]{40}$'
        OR p_bot IS NULL OR p_bot NOT IN ('daily','intraday','aggressive')
        OR p_coin IS NULL OR p_coin !~ '^[A-Z][A-Z0-9]{0,23}$'
        OR p_side IS NULL OR p_side NOT IN ('long','short')
        OR p_nonce IS NULL OR p_nonce !~ '^[0-9a-f]{32}$'
        OR p_fence IS NULL OR p_fence <= 0
        OR p_outcome IS NULL OR p_outcome NOT IN (
            'pending_exit','unknown_ack','partial_fill','claimed_closed'
        )) THEN
        RETURN QUERY SELECT false,'invalid-protection-fixture'::text;
        RETURN;
    END IF;
    -- Lock both journal intent and account/coin fence. Retained scope
    -- ownership is never inferred from a caller-provided 'closed' claim.
    SELECT i.id INTO v_id
      FROM sender_review_ci.review_intents AS i
      JOIN sender_review_ci.fixture_request_evidence AS e
        ON e.intent_id=i.id AND e.environment=i.environment
       AND e.account=i.account AND e.request_nonce=i.request_nonce
       AND e.bot=i.bot
      JOIN sender_review_ci.scope_fences AS s
        ON s.environment=i.environment AND s.account=i.account
       AND s.dex=i.dex AND s.coin=i.coin
     WHERE i.environment='testnet' AND i.account=p_account
       AND i.dex='' AND i.coin=p_coin
       AND i.bot=p_bot AND i.side=p_side
       AND i.request_nonce=p_nonce AND i.fence=p_fence
       AND i.state IN ('review_only','hold_unknown')
       AND s.fence=i.fence AND s.active_nonce=i.request_nonce
     FOR UPDATE OF i,s;
    IF v_id IS NULL THEN
        RETURN QUERY SELECT false,'unverified-or-unheld-fixture'::text;
        RETURN;
    END IF;
    INSERT INTO sender_review_ci.simulated_protection_reentry_holds (
        environment,account,dex,coin,bot,side,
        request_nonce,fence,source_intent_id,outcome_fixture
    ) VALUES (
        'testnet',p_account,'',p_coin,p_bot,p_side,
        p_nonce,p_fence,v_id,p_outcome
    )
    ON CONFLICT DO NOTHING RETURNING source_intent_id INTO v_inserted;
    IF v_inserted IS NULL THEN
        RETURN QUERY SELECT false,'existing-protection-hold-retained'::text;
        RETURN;
    END IF;
    RETURN QUERY SELECT true,'durable-review-only-protection-HOLD'::text;
END $fn$;

-- A separately connecting reviewer can see whether the underlying
-- account/coin fence was tampered with. A closed-claim has NO special
-- authority and cannot clear this view or authorize a new entry.
CREATE OR REPLACE VIEW sender_review_ci.simulated_protection_hold_review
WITH (security_invoker=true) AS
SELECT h.environment,h.account,h.coin,h.bot,h.side,h.request_nonce,
       h.fence,h.outcome_fixture,h.created_at,
       COALESCE(s.fence=h.fence AND s.active_nonce=h.request_nonce,false)
         AS fence_still_held,
       CASE WHEN s.fence IS DISTINCT FROM h.fence
             OR s.active_nonce IS DISTINCT FROM h.request_nonce
         THEN 'CRITICAL_FENCE_MISSING_OR_CHANGED'
         ELSE 'PERMANENT_REVIEW_ONLY_HOLD'
       END::text AS review_state
FROM sender_review_ci.simulated_protection_reentry_holds AS h
LEFT JOIN sender_review_ci.scope_fences AS s
  ON s.environment=h.environment AND s.account=h.account
 AND s.dex=h.dex AND s.coin=h.coin;

-- In CI the schema owner is the test harness. The arbitrary untrusted role
-- and the NOLOGIN restricted role have NO direct table/function/view access.
REVOKE ALL ON sender_review_ci.simulated_protection_reentry_holds FROM PUBLIC;
REVOKE ALL ON sender_review_ci.simulated_protection_hold_review FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION
    sender_review_ci.record_ci_protection_reentry_hold(
        text,text,text,text,text,bigint,text
    ) FROM PUBLIC;
