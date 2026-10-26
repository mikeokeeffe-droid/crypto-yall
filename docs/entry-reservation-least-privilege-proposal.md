# Entry reservation least-privilege redesign (staging proposal)

**Not a deployable migration.** Do not apply to live Supabase or enable bots.

## Current problem

The staging entry RPCs are `SECURITY INVOKER`, so `service_role` receives direct table INSERT/UPDATE/DELETE grants. A caller with those privileges can change reservations or durable intents without the serialized RPC checks.

## Proposed isolated design

1. Create a separate, **non-login executor role** with only schema USAGE, selected read permissions, and EXECUTE on narrowly scoped reservation/claim/release functions. No direct INSERT/UPDATE/DELETE on the two entry tables.
2. Migrate the reservation and claim routines to audited `SECURITY DEFINER` functions owned by a dedicated, non-login migration owner. Use a fixed `search_path`, schema-qualified objects, strict argument checks, and the same per-coin transaction advisory lock.
3. Treat the existing Supabase `service_role` as **privileged infrastructure**: its bypass-RLS capability and potential table ownership privileges mean these grants alone cannot sandbox a leaked service key. Do not claim least privilege while routine executors use the service-role key. Design a distinct authenticated execution identity or trusted server-side proxy that invokes only allowlisted RPCs.
4. Give intent resolution and verified ownership release only to a separately authenticated reconciler identity. Never trust boolean evidence parameters as exchange proof; the reconciler must obtain independent order/fill/position evidence.
5. Add isolated PostgreSQL tests that set the actual executor/reconciler roles, verify allowed RPC calls, deny direct DML, reject unauthorized release, and exercise conflicting claims and ambiguous fills.
6. Keep the production executor unchanged and all trading workflows halted until explicit deployment/cutover approval.

## Acceptance gate

Do not approve production integration until the role separation is implemented, isolated permission and concurrency tests pass, and the authentication model is reviewed. Existing staging tests that expect `service_role` direct DML document current exposure, **not** the desired final contract.
