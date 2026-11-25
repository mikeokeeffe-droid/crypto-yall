-- CI-ONLY account-wide quarantine enforcement across three synthetic bots.
-- Apply only after ci_only_journal.sql AND
-- ci_only_protection_reentry_holds.sql, against disposable sender_review_test.
-- No signer, network, order sender, runtime authorization, release, migration
-- or trusted exchange outcome. DO NOT apply to Supabase/live/test servers.
DO $guard$
BEGIN
  IF current_database() <> 'sender_review_test' THEN
    RAISE EXCEPTION 'disposable CI only: wrong database';
  END IF;
END $guard$;

-- Preserve every simulated incident even if a prior incident has already
-- quarantined the account. This is NOT an audit ledger against a DB superuser:
-- TRUNCATE, trigger disabling and schema replacement remain possible in CI.
CREATE TABLE IF NOT EXISTS sender_review_ci.simulated_account_quarantine_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_intent_id bigint NOT NULL REFERENCES
        sender_review_ci.review_intents(id) ON DELETE RESTRICT,
    environment text NOT NULL CHECK (environment='testnet'),
    account text NOT NULL CHECK (account ~ '^0x[0-9a-f]{40}$'),
    bot text NOT NULL CHECK (bot IN ('daily','intraday','aggressive')),
    coin text NOT NULL CHECK (coin ~ '^[A-Z][A-Z0-9]{0,23}$'),
    request_nonce text NOT NULL CHECK (request_nonce ~ '^[0-9a-f]{32}$'),
    fence bigint NOT NULL CHECK (fence > 0),
    reason text NOT NULL CHECK (reason IN (
        'JOURNAL_UNKNOWN',
        'PROTECTION_PENDING_EXIT',
        'PROTECTION_UNKNOWN_ACK',
        'PROTECTION_PARTIAL_FILL',
        'PROTECTION_CLAIMED_CLOSED'
    )),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(source_intent_id,reason),
    FOREIGN KEY(source_intent_id,environment,account,request_nonce,bot)
        REFERENCES sender_review_ci.review_intents(
            id,environment,account,request_nonce,bot
        ) ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS simulated_account_quarantine_no_mutate
  ON sender_review_ci.simulated_account_quarantine_events;
CREATE TRIGGER simulated_account_quarantine_no_mutate
BEFORE UPDATE OR DELETE ON sender_review_ci.simulated_account_quarantine_events
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.reject_fixture_evidence_mutation();

-- An already-serialized account journal admission must be denied if there
-- is ANY unresolved synthetic incident, including on a DIFFERENT COIN.
-- record_review_only() takes a transaction-scoped per-account advisory lock
-- before INSERT, so competing CI workers are serialised at this trigger.
-- A denied candidate is skipped in the same transaction; a temporary
-- empty scope row may remain, but cannot authorise an order or new entry.
CREATE OR REPLACE FUNCTION sender_review_ci.reject_quarantined_review_intent()
RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog
AS $fn$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'CI ONLY: wrong database';
    END IF;
    IF EXISTS (
        SELECT 1 FROM sender_review_ci.simulated_account_quarantine_events q
        WHERE q.environment=NEW.environment AND q.account=NEW.account
    ) OR EXISTS (
        -- A signed fixture can commit its entry evidence BEFORE the
        -- separate protection HOLD. Treat that incomplete handoff, or
        -- an altered/missing scope fence, as account-wide NO-GO even if
        -- no explicit quarantine event has been committed yet.
        SELECT 1 FROM sender_review_ci.simulated_protection_handoff_audit a
        WHERE a.environment=NEW.environment AND a.account=NEW.account
          AND a.review_state <> 'PERSISTED_FIXTURE_HOLD_NO_REAL_PROTECTION'
    ) THEN
        -- Suppress candidate insertion: record_review_only() observes no
        -- RETURNING row and returns a generic denied result. No new
        -- intent is recorded. An empty scope candidate row may remain.
        RETURN NULL;
    END IF;
    RETURN NEW;
END $fn$;

DROP TRIGGER IF EXISTS simulated_quarantine_blocks_all_coin_claims
  ON sender_review_ci.review_intents;
CREATE TRIGGER simulated_quarantine_blocks_all_coin_claims
BEFORE INSERT ON sender_review_ci.review_intents
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.reject_quarantined_review_intent();

-- A journal UNKNOWN transition automatically latches the entire account,
-- in the SAME SQL transaction as the status/event update. An aborted
-- transition cannot create a ghost quarantine; a committed transition
-- cannot omit its quarantine event through the normal guarded function.
CREATE OR REPLACE FUNCTION sender_review_ci.latch_quarantine_on_unknown()
RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog
AS $fn$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'CI ONLY: wrong database';
    END IF;
    IF NEW.state='hold_unknown' AND OLD.state IS DISTINCT FROM NEW.state THEN
        INSERT INTO sender_review_ci.simulated_account_quarantine_events(
            source_intent_id,environment,account,bot,coin,request_nonce,
            fence,reason
        ) VALUES (
            NEW.id,NEW.environment,NEW.account,NEW.bot,NEW.coin,
            NEW.request_nonce,NEW.fence,'JOURNAL_UNKNOWN'
        ) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END $fn$;

DROP TRIGGER IF EXISTS simulated_quarantine_after_unknown
  ON sender_review_ci.review_intents;
CREATE TRIGGER simulated_quarantine_after_unknown
AFTER UPDATE OF state ON sender_review_ci.review_intents
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.latch_quarantine_on_unknown();

-- A synthetic protection pending exit, uncertain ACK, partial fill, or even
-- an asserted 'closed' are ALL unresolved by real authenticated exchange
-- evidence, so every one freezes the account. The assertion never releases
-- an earlier latch or allows a new entry.
CREATE OR REPLACE FUNCTION sender_review_ci.latch_quarantine_on_protection()
RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog
AS $fn$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'CI ONLY: wrong database';
    END IF;
    INSERT INTO sender_review_ci.simulated_account_quarantine_events(
        source_intent_id,environment,account,bot,coin,request_nonce,
        fence,reason
    ) VALUES (
        NEW.source_intent_id,NEW.environment,NEW.account,NEW.bot,NEW.coin,
        NEW.request_nonce,NEW.fence,'PROTECTION_' || upper(NEW.outcome_fixture)
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
END $fn$;

DROP TRIGGER IF EXISTS simulated_quarantine_after_protection_hold
  ON sender_review_ci.simulated_protection_reentry_holds;
CREATE TRIGGER simulated_quarantine_after_protection_hold
AFTER INSERT ON sender_review_ci.simulated_protection_reentry_holds
FOR EACH ROW EXECUTE FUNCTION
    sender_review_ci.latch_quarantine_on_protection();

CREATE OR REPLACE VIEW sender_review_ci.simulated_account_quarantine_review
WITH (security_invoker=true) AS
SELECT environment,account,COUNT(*)::bigint AS unresolved_incident_count,
       COUNT(DISTINCT coin)::bigint AS affected_coins,
       MIN(created_at) AS first_incident_at,
       'ACCOUNT_WIDE_QUARANTINE_HOLD_NO_TRADING_AUTHORITY'::text AS review_state
FROM sender_review_ci.simulated_account_quarantine_events
GROUP BY environment,account;

-- Read-only aggregate shows all accounted reasons for an admission
-- freeze, including signed handoffs interrupted before any quarantine
-- event was inserted. No row is ever a GO or permission statement:
-- absence of rows is also NOT an authenticated clearance.
CREATE OR REPLACE VIEW sender_review_ci.simulated_account_admission_review
WITH (security_invoker=true) AS
SELECT COALESCE(q.environment,a.environment) AS environment,
       COALESCE(q.account,a.account) AS account,
       COALESCE(q.incident_count,0)::bigint AS explicit_incident_count,
       COALESCE(a.incomplete_count,0)::bigint AS critical_handoff_count,
       'ACCOUNT_ADMISSION_FROZEN_CI_REVIEW_ONLY'::text AS review_state
FROM (
    SELECT environment,account,count(*) AS incident_count
    FROM sender_review_ci.simulated_account_quarantine_events
    GROUP BY environment,account
) AS q
FULL JOIN (
    SELECT environment,account,
           count(*) FILTER (
              WHERE review_state <>
                    'PERSISTED_FIXTURE_HOLD_NO_REAL_PROTECTION'
           ) AS incomplete_count
    FROM sender_review_ci.simulated_protection_handoff_audit
    GROUP BY environment,account
) AS a
 ON q.environment=a.environment AND q.account=a.account
WHERE COALESCE(q.incident_count,0)>0 OR COALESCE(a.incomplete_count,0)>0;

REVOKE ALL ON sender_review_ci.simulated_account_quarantine_events FROM PUBLIC;
REVOKE ALL ON sender_review_ci.simulated_account_quarantine_review FROM PUBLIC;
REVOKE ALL ON sender_review_ci.simulated_account_admission_review FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION
 sender_review_ci.reject_quarantined_review_intent() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION
 sender_review_ci.latch_quarantine_on_unknown() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION
 sender_review_ci.latch_quarantine_on_protection() FROM PUBLIC;
