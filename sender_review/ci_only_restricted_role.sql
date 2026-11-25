-- DISPOSABLE CI ONLY: no server role, production migration, or order sender.
-- This file MUST NOT be deployed to Supabase or any live/testnet service.
-- A NOLOGIN test role can execute only a REVIEW-ONLY function; it cannot
-- read raw journal rows, release fences, submit orders, or update credentials.
-- This is NOT workload authentication: test caller impersonation of a bot is
-- still possible inside the disposable DB and requires a separate trusted
-- remote service / real issuer verification before any rollout.
DO $$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'CI ONLY: wrong database';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'sender_review_ci_restricted'
    ) THEN
        CREATE ROLE sender_review_ci_restricted NOLOGIN NOSUPERUSER
          NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;

-- Hard-coded synthetic account, testnet and DEX only.
-- SECURITY DEFINER is intentionally confined to this disposable database.
-- No dynamic SQL; all journal objects are fully qualified, search_path pinned.
-- Function and its DB owner are NOT a production privilege design.
CREATE OR REPLACE FUNCTION sender_review_ci.record_fixture_restricted(
    p_jti text, p_bot text, p_coin text, p_action text, p_side text,
    p_size numeric, p_leverage integer, p_nonce text
) RETURNS TABLE(recorded boolean, assigned_fence bigint, reason text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_account CONSTANT text := '0x1111111111111111111111111111111111111111';
    v_consumed text;
    v_recorded boolean;
    v_fence bigint;
    v_reason text;
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'CI ONLY: wrong database';
    END IF;
    IF p_jti IS NULL OR p_jti !~ '^[A-Za-z0-9_-]{6,128}$'
       OR p_bot IS NULL OR p_bot NOT IN ('daily','intraday','aggressive')
       OR p_nonce IS NULL OR p_nonce !~ '^[0-9a-f]{32}$' THEN
        RETURN QUERY SELECT false, 0::bigint, 'invalid-fixture-identity'::text;
        RETURN;
    END IF;

    -- Nested exception block forms a PostgreSQL subtransaction. If the
    -- journal rejects a fixture claim, roll back *both* the newly consumed
    -- JTI receipt and any scope rows created during that claim. Never
    -- DELETE a receipt: receipt rows are append-only, including unbound
    -- ones, and must not be manually erased as a rollback workaround.
    BEGIN
        INSERT INTO sender_review_ci.fixture_identity_receipts
            (environment,account,jti,bot,request_nonce)
        VALUES ('testnet',v_account,p_jti,p_bot,p_nonce)
        ON CONFLICT DO NOTHING RETURNING jti INTO v_consumed;
        IF v_consumed IS NULL THEN
            RETURN QUERY SELECT false, 0::bigint, 'fixture-replay-held'::text;
            RETURN;
        END IF;

        SELECT r.recorded, r.assigned_fence, r.reason
          INTO v_recorded,v_fence,v_reason
          FROM sender_review_ci.record_review_only(
              v_account,p_bot,p_coin,p_action,p_side,p_size,p_leverage,p_nonce
          ) AS r;
        IF NOT COALESCE(v_recorded,false) THEN
            -- CI-only sentinel for *expected* journal denial. The
            -- exception rolls back inserts in this nested block before
            -- its handler returns a review-only HOLD result.
            RAISE EXCEPTION 'ci fixture journal denied'
                USING ERRCODE='PZ001';
        END IF;
    EXCEPTION WHEN SQLSTATE 'PZ001' THEN
        RETURN QUERY SELECT false, COALESCE(v_fence,0),
            ('journal-denied:' || COALESCE(v_reason,'unknown'))::text;
        RETURN;
    END;
    RETURN QUERY SELECT true,v_fence,'persisted-fixture-review-only-HOLD'::text;
END
$$;

REVOKE EXECUTE ON FUNCTION sender_review_ci.record_fixture_restricted(
    text,text,text,text,text,numeric,integer,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA sender_review_ci TO sender_review_ci_restricted;
GRANT EXECUTE ON FUNCTION sender_review_ci.record_fixture_restricted(
    text,text,text,text,text,numeric,integer,text)
    TO sender_review_ci_restricted;
