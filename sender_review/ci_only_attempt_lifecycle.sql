-- DISPOSABLE PostgreSQL CI ONLY. This is a simulated order-attempt
-- lifecycle. NO exchange client, signer, transport, permission to send,
-- release, retry, production schema migration or deployment authority.
-- Load AFTER ci_only_journal.sql in the isolated sender_review_test DB.
DO $$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'disposable sender review only: wrong database';
    END IF;
END
$$;

-- Durable, append-only simulated events. The only legal progression is
-- simulated_attempt_started -> simulated_unknown_held; no "sent" or "GO".
-- Each intent may have at most one of each event.
CREATE TABLE IF NOT EXISTS sender_review_ci.simulated_attempt_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    intent_id bigint NOT NULL REFERENCES sender_review_ci.review_intents(id)
        ON DELETE RESTRICT,
    kind text NOT NULL CHECK (
        kind IN ('simulated_attempt_started', 'simulated_unknown_held')
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (intent_id, kind)
);

DROP TRIGGER IF EXISTS simulated_attempt_events_no_mutate
    ON sender_review_ci.simulated_attempt_events;
CREATE TRIGGER simulated_attempt_events_no_mutate
BEFORE UPDATE OR DELETE ON sender_review_ci.simulated_attempt_events
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.reject_fixture_evidence_mutation();

-- Recording a fake START requires an existing signed CI fixture receipt
-- and exact request evidence, a held matching scope fence, and an intent
-- that has not entered unknown HOLD. The matching intent is row-locked.
CREATE OR REPLACE FUNCTION sender_review_ci.record_simulated_attempt_start(
    p_account text, p_coin text, p_nonce text, p_fence bigint
) RETURNS TABLE(recorded boolean, reason text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
AS $$
DECLARE
    v_id bigint;
    v_event_id bigint;
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RETURN QUERY SELECT false, 'wrong-disposable-database'::text;
        RETURN;
    END IF;
    SELECT i.id INTO v_id
    FROM sender_review_ci.review_intents AS i
    JOIN sender_review_ci.fixture_request_evidence AS e ON e.intent_id=i.id
    JOIN sender_review_ci.scope_fences AS s
      ON s.environment=i.environment AND s.account=i.account
     AND s.dex=i.dex AND s.coin=i.coin
    WHERE i.environment='testnet' AND i.account=p_account
      AND i.dex='' AND i.coin=p_coin
      AND i.request_nonce=p_nonce AND i.fence=p_fence
      AND i.state='review_only'
      AND e.account=i.account AND e.request_nonce=i.request_nonce
      AND e.bot=i.bot
      AND s.fence=i.fence AND s.active_nonce=i.request_nonce
    FOR UPDATE OF i;
    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'unverified-or-unheld-review-intent'::text;
        RETURN;
    END IF;
    INSERT INTO sender_review_ci.simulated_attempt_events(intent_id,kind)
    VALUES (v_id,'simulated_attempt_started')
    ON CONFLICT DO NOTHING RETURNING event_id INTO v_event_id;
    IF v_event_id IS NULL THEN
        RETURN QUERY SELECT false, 'simulated-attempt-already-recorded'::text;
        RETURN;
    END IF;
    RETURN QUERY SELECT true, 'simulated-start-recorded-no-send'::text;
END
$$;

-- Conservative progression only: a started attempt can be moved to
-- unknown HOLD. This uses the existing journal function, retains the
-- original account/coin fence, and never releases or reuses a nonce.
CREATE OR REPLACE FUNCTION sender_review_ci.hold_simulated_attempt_unknown(
    p_account text, p_coin text, p_nonce text, p_fence bigint
) RETURNS TABLE(held boolean, reason text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
AS $$
DECLARE
    v_id bigint;
    v_held boolean;
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RETURN QUERY SELECT false, 'wrong-disposable-database'::text;
        RETURN;
    END IF;
    SELECT i.id INTO v_id
      FROM sender_review_ci.review_intents AS i
     WHERE i.environment='testnet' AND i.account=p_account
       AND i.dex='' AND i.coin=p_coin
       AND i.request_nonce=p_nonce AND i.fence=p_fence
       AND i.state='review_only'
       AND EXISTS (
           SELECT 1 FROM sender_review_ci.simulated_attempt_events AS e
            WHERE e.intent_id=i.id AND e.kind='simulated_attempt_started'
       )
     FOR UPDATE OF i;
    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'no-started-review-attempt'::text;
        RETURN;
    END IF;
    SELECT sender_review_ci.hold_uncertain(
        p_account,p_coin,p_nonce,p_fence
    ) INTO v_held;
    IF NOT COALESCE(v_held,false) THEN
        RETURN QUERY SELECT false, 'journal-could-not-hold'::text;
        RETURN;
    END IF;
    INSERT INTO sender_review_ci.simulated_attempt_events(intent_id,kind)
    VALUES (v_id,'simulated_unknown_held');
    RETURN QUERY SELECT true, 'unknown-held-no-retry-or-release'::text;
END
$$;

-- Recovery visibility for an independent CI test observer. A crashed
-- worker need not reconnect for a different *read-only* session to see
-- started-but-not-held and unknown-held incidents. This view grants no
-- ability to reconcile an actual exchange outcome, retry or clear fences.
-- SECURITY INVOKER also prevents the view-owner privilege from becoming
-- an accidental escape hatch if a role gains SELECT on this view later.
CREATE OR REPLACE VIEW sender_review_ci.simulated_unresolved_attempts
WITH (security_invoker=true) AS
SELECT
    i.id AS intent_id,
    i.account,
    i.coin,
    i.bot,
    i.request_nonce,
    i.fence,
    i.state AS journal_state,
    a.created_at AS simulated_started_at,
    CASE
        WHEN a.intent_id IS NULL THEN 'UNKNOWN_HELD_MISSING_START'
        WHEN i.state = 'hold_unknown' AND EXISTS (
            SELECT 1 FROM sender_review_ci.simulated_attempt_events AS e
             WHERE e.intent_id=i.id
               AND e.kind='simulated_unknown_held'
        ) THEN 'UNKNOWN_HELD'
        ELSE 'STARTED_OUTCOME_UNCONFIRMED'
    END::text AS incident_state,
    COALESCE(
        s.active_nonce=i.request_nonce AND s.fence=i.fence, false
    ) AS fence_still_held,
    CASE
        WHEN s.fence IS DISTINCT FROM i.fence
          OR s.active_nonce IS DISTINCT FROM i.request_nonce
          THEN 'CRITICAL_FENCE_MISSING_OR_CHANGED'
        WHEN a.intent_id IS NULL
          THEN 'CRITICAL_START_EVENT_MISSING'
        WHEN i.state='hold_unknown' AND NOT EXISTS (
            SELECT 1 FROM sender_review_ci.simulated_attempt_events AS e
            WHERE e.intent_id=i.id AND e.kind='simulated_unknown_held'
        ) THEN 'CRITICAL_HOLD_EVENT_MISSING'
        WHEN i.state='review_only' AND EXISTS (
            SELECT 1 FROM sender_review_ci.simulated_attempt_events AS e
            WHERE e.intent_id=i.id AND e.kind='simulated_unknown_held'
        ) THEN 'CRITICAL_INCONSISTENT_EVENT'
        WHEN i.state='hold_unknown' THEN 'CRITICAL_UNKNOWN_OUTCOME'
        ELSE 'CRITICAL_OUTCOME_UNCONFIRMED'
    END::text AS incident_attention
FROM sender_review_ci.review_intents AS i
LEFT JOIN sender_review_ci.simulated_attempt_events AS a
  ON a.intent_id=i.id AND a.kind='simulated_attempt_started'
LEFT JOIN sender_review_ci.scope_fences AS s
  ON s.environment=i.environment AND s.account=i.account
 AND s.dex=i.dex AND s.coin=i.coin
WHERE i.environment='testnet'
  AND i.state IN ('review_only','hold_unknown')
  AND (a.intent_id IS NOT NULL OR i.state='hold_unknown');

REVOKE ALL ON sender_review_ci.simulated_unresolved_attempts FROM PUBLIC;

-- CI harness owner only. No TEST role, PUBLIC user or live bot may call
-- these functions or read/write attempt events. These statements do not
-- attest to production database privileges.
REVOKE ALL ON sender_review_ci.simulated_attempt_events FROM PUBLIC;
REVOKE ALL ON SEQUENCE sender_review_ci.simulated_attempt_events_event_id_seq FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION sender_review_ci.record_simulated_attempt_start(
    text,text,text,bigint) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION sender_review_ci.hold_simulated_attempt_unknown(
    text,text,text,bigint) FROM PUBLIC;
