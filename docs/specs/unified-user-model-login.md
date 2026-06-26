# Unify NEX Ledger user record + login to the NEX Studio vzor — spec (Dedo, 2026-06-15)

Director-approved 2026-06-15 (Zoltán = Ri → this approval is the Schema-Governance sign-off for the
structural `"user"` change). Follow-up to the unified Settings kit (CR-NS-078..081).

## Goal
NEX Ledger logs in by **username** (not email) and the user record carries **username + first_name +
last_name**, matching NEX Studio. Email is **kept** as a field (still required + unique), just no longer
the login key. Ledger keeps its own 2-tier role enum (accountant/admin).

## Target `"user"` table (after change)
id (UUID PK) · **username VARCHAR(50) NOT NULL UNIQUE — the NEW login key** · email VARCHAR(255) NOT NULL
UNIQUE (kept) · first_name VARCHAR(100) NULL · last_name VARCHAR(100) NULL · password_hash · role
(accountant|admin) · active · must_change_password · created_at · token_version (from 002).

## Approved decisions
- **Login key = username.** Backfill the existing admin's username = `split_part(email,'@',1)` → `admin`
  (its password is unchanged; **after deploy it logs in with `admin`, not the email**).
- Names **optional (NULL) + editable** post-create (add to UserUpdate + the updatable allowlist, for Studio parity).
- Email **stays NOT NULL UNIQUE** (audit denormalizes user_email; dedup relies on it).
- Failed-login-by-unknown-username: write the attempted username into `audit_log.user_email` (a denormalized label).
- **Adopt the shared nex-shared `LoginForm`** (username mode) — not a bespoke in-place switch.
- `SEED_ADMIN_USERNAME` env added (fresh-DB seed only; irrelevant to the existing UAT row, set it anyway).

## Migration plan — `backend/migrations/004_add_user_identity.sql` (Ledger = asyncpg raw-SQL, re-applied EVERY startup → MUST be idempotent)
One file, three phases: (1) `ADD COLUMN IF NOT EXISTS` username VARCHAR(50) NULLABLE + first_name/last_name
VARCHAR NULL; (2) BACKFILL `UPDATE "user" SET username = split_part(email,'@',1) WHERE username IS NULL`
(idempotent — once set, no longer NULL); (3) promote: `ALTER COLUMN username SET NOT NULL` (no-op if already)
+ add UNIQUE constraint inside a `DO $$ ... IF NOT EXISTS (pg_constraint) $$` guard (so re-apply does NOT
error). Sorts after 002/003 (correct). Optional CHECK char_length 1..50.

## CR breakdown (Implementer-sized; Ledger style: asyncpg raw-SQL, no ORM/Alembic)
- **CR-NS-082** — migration `004` (3-phase idempotent + backfill) + test_migrations/test_compliance for the 3 new
  columns + the username NOT NULL UNIQUE. No app logic yet. *(KB `DATABASE_SCHEMAS.md` user-table delta + RAG
  reindex = Dedo, in parallel — outside Implementer write-scope.)*
- **CR-NS-083** — `user_repository` (UserRecord/_COLUMNS/_to_record + `get_by_username` replacing get_by_email +
  insert(username,first_name,last_name)); `schemas/user.py` (User/UserCreate/to_user_schema gain username+names);
  `schemas/auth.py` (LoginRequest.email→username); `config.py` SEED_ADMIN_USERNAME (required env); conftest default.
- **CR-NS-084** — `auth_service.login` (username + get_by_username; preserve the 3-failures-same-401 verbatim; audit
  user_email = attempted identity on failure); `seed_admin` passes username; `user_service.create_user` threads
  username + maps BOTH duplicate-email AND duplicate-username UniqueViolation → 409; `api/v1/auth.py` body.username.
- **CR-NS-085** — Frontend login: adopt nex-shared `LoginForm` (username mode) in LoginPage (thin adapter — owns
  only auth-store + navigate); `api/endpoints.ts` login body {username}; `api/types.ts` User+UserCreate+username;
  SK error text.
- **CR-NS-086** — Frontend Settings: `USER_FIELD_SCHEMA` username:true + names:true; `settingsAdapter.toKitUser`
  real username + first/last (+ fix stale "no username" comments + flip the test assertion); SettingsPage
  handleCreateUser passes username+names; Sessions `resolveUsername` id→username.

## Risks (carry into every CR)
- **LOGIN-KEY FLIP locks out the admin if the backfill value is wrong** — deterministic backfill + verify the
  `admin` login in UAT BEFORE relying on it (UAT acceptance gate). seed_admin won't re-fire (table not empty).
- **Idempotency on re-apply** — the UNIQUE-constraint add MUST be guarded (IF NOT EXISTS in pg_constraint) or the
  2nd boot aborts; SET NOT NULL is a no-op; the backfill UPDATE is naturally idempotent.
- **Duplicate-username 409** — after the UNIQUE add, create_user must map the NEW constraint violation to 409 (not 500).
- **FE/BE contract drift** — LoginRequest email→username across BE + FE in lockstep; Ledger FE is a prod nginx bundle
  → rebuild+redeploy together; incognito-check if login 422s post-deploy (stale bundle).
- **token_version**: the login switch does NOT bump tv — the admin's current 8h session keeps working; no forced logout.
- **Schema Governance**: doc + Ri sign-off precede the migration (sign-off = this approval; doc = Dedo CR-082-parallel).
