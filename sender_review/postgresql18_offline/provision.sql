-- REVIEW-ONLY package for a dedicated, offline PostgreSQL 18 test server.
-- Do not run during review. Never use on CI, Supabase, or a trading database.
\set ON_ERROR_STOP on

BEGIN;

DO $guard$
BEGIN
    IF current_database() <> 'sender_review_test' THEN
        RAISE EXCEPTION 'offline PostgreSQL 18 test database required';
    END IF;
    IF current_setting('server_version_num')::integer < 180000
       OR current_setting('server_version_num')::integer >= 190000 THEN
        RAISE EXCEPTION 'PostgreSQL 18 is required';
    END IF;
    IF current_setting('listen_addresses') <> '' THEN
        RAISE EXCEPTION 'TCP listening must remain disabled';
    END IF;
    IF current_setting('unix_socket_permissions') <> '0770'
       OR current_setting('unix_socket_group') = ''
       OR current_setting('unix_socket_directories') = '' THEN
        RAISE EXCEPTION 'restricted Unix socket mode, group, and directory required';
    END IF;
    IF session_user <> 'postgres'
       OR NOT (SELECT rolsuper FROM pg_catalog.pg_roles
               WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'run only as the local postgres administrator';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_namespace
               WHERE nspname = 'sender_review_ci') THEN
        RAISE EXCEPTION 'fresh dedicated database required; schema already exists';
    END IF;
END
$guard$;

CREATE ROLE sender_review_pg18_owner
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT;
CREATE ROLE sender_review_pg18_daily
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT;
CREATE ROLE sender_review_pg18_intraday
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT;
CREATE ROLE sender_review_pg18_aggressive
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT;
CREATE ROLE sender_review_ci_untrusted
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT;
CREATE ROLE sender_review_ci_restricted
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT;

GRANT CREATE ON DATABASE sender_review_test TO sender_review_pg18_owner;
GRANT sender_review_pg18_owner TO postgres;
SET ROLE sender_review_pg18_owner;

-- Reuse the reviewed, review-only journal and restricted fixture SQL verbatim.
\ir ../ci_only_journal.sql
\ir ../ci_only_restricted_role.sql

RESET ROLE;
REVOKE sender_review_pg18_owner FROM postgres;
REVOKE CREATE ON DATABASE sender_review_test FROM sender_review_pg18_owner;

-- No public or bot role can connect to this dedicated database or access its
-- journal. The fixture-only restricted role retains only its reviewed wrapper.
REVOKE CONNECT, TEMPORARY ON DATABASE sender_review_test FROM PUBLIC;
REVOKE ALL ON DATABASE sender_review_test FROM
    sender_review_pg18_owner, sender_review_pg18_daily,
    sender_review_pg18_intraday, sender_review_pg18_aggressive,
    sender_review_ci_untrusted, sender_review_ci_restricted;
-- Preserve privileges of the disconnected NOLOGIN object owner; revoking
-- owner ACLs would contradict ownership assertions while adding no bot isolation.
-- No owner role has database CONNECT or membership grants.
REVOKE ALL ON SCHEMA sender_review_ci FROM PUBLIC,
    sender_review_pg18_daily,
    sender_review_pg18_intraday, sender_review_pg18_aggressive,
    sender_review_ci_untrusted, sender_review_ci_restricted;
REVOKE ALL ON ALL TABLES IN SCHEMA sender_review_ci FROM PUBLIC,
    sender_review_pg18_daily,
    sender_review_pg18_intraday, sender_review_pg18_aggressive,
    sender_review_ci_untrusted, sender_review_ci_restricted;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA sender_review_ci FROM PUBLIC,
    sender_review_pg18_daily,
    sender_review_pg18_intraday, sender_review_pg18_aggressive,
    sender_review_ci_untrusted, sender_review_ci_restricted;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA sender_review_ci FROM PUBLIC,
    sender_review_pg18_daily, sender_review_pg18_intraday,
    sender_review_pg18_aggressive, sender_review_ci_untrusted,
    sender_review_ci_restricted;
GRANT USAGE ON SCHEMA sender_review_ci TO sender_review_ci_restricted;
GRANT EXECUTE ON FUNCTION sender_review_ci.record_fixture_restricted(
    text,text,text,text,text,numeric,integer,text)
    TO sender_review_ci_restricted;

COMMIT;
