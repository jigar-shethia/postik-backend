# Cloud Kitchen Auth API - Implementation Epics & Stories (v1 Production Ready)

This specification defines the production-ready phone-first OTP authentication and onboarding flow for a FastAPI + PostgreSQL + Redis stack, incorporating hardened security, token revocation, atomic dispatch order, and rate-limiting safeguards.

---

## Architecture Overview & Flow State Machine

```
[User Phone Input]
       │
       ▼
[POST /auth/otp/send] ──► Checks:
       │                   1. Cooldown (60s lock: cooldown:otp:{phone})
       │                   2. Phone limit (3 / 10m: rate:otp_phone:{phone})
       │                   3. IP limit (20 / 10m: rate:otp_ip:{ip})
       │                 Dispatch SMS -> On Gateway 200 OK -> Store SHA-256(OTP) in Redis (TTL 5m)
       │
       ▼
[POST /auth/otp/verify] ──► Compare SHA-256(Input OTP) against Redis hash
       │                    Max 5 attempts -> Delete OTP on success/failure limit
       │
       ├─► [User Exists in PostgreSQL?]
       │         │
       │         ├─► YES: Issue JWT Access Token + Refresh Token
       │         │        Insert row in `refresh_sessions` (token_hash, device_id)
       │         │        Return: { is_new_user: false, access_token, refresh_token }
       │         │
       │         └─► NO:  Issue Temporary Registration Token:
       │                  Claims: { sub: phone, scope: "register", jti: UUID, exp: +10m }
       │                  Return: { is_new_user: true, registration_token }
       ▼
[POST /auth/register] ◄─── Requires Header: Authorization: Bearer <registration_token>
       │
       ├── Validate signature, scope == "register", and expiration
       ├── Atomic Redis Check: `SET consumed:jti:{jti} 1 NX EX 600` (Fails if already consumed)
       ├── Insert customer: `users (phone, name, email)` (Unique constraints on phone & email)
       ├── Create initial `refresh_sessions` row
       └── Return: JWT access_token, refresh_token, and user profile
```

---

## Story Index

- **STORY-01:** Project Setup, Database Configuration & Core Environment Config
- **STORY-02:** Database Models (Users & Refresh Sessions) & Alembic Migrations
- **STORY-03:** Redis Engine — OTP Hashing, Multi-Tier Rate Limiting & Cooldowns
- **STORY-04:** SMS Provider Abstraction & Safe Dispatch Service
- **STORY-05:** Security Core — Scoped JWT Tokens, Session Hashes & Replay Guard
- **STORY-06:** Pydantic Validation Schemas & Response DTOs
- **STORY-07:** API Route — `POST /api/v1/auth/otp/send`
- **STORY-08:** API Route — `POST /api/v1/auth/otp/verify`
- **STORY-09:** API Route — `POST /api/v1/auth/register` (One-Time Token Enforced)
- **STORY-10:** API Route — `POST /api/v1/auth/refresh` (Rotation & Revocation) & `GET /api/v1/auth/me`
- **STORY-11:** End-to-End Automated Test Suite & Attack Simulation

---

### STORY-01: Project Setup, Database Configuration & Core Environment Config

- **Goal:** Initialize application structure, async PostgreSQL connection pool, and configuration parsing.
- **Dependencies:** None.
- **Tasks:**
  1. Initialize folder structure:
     ```
     app/
     ├── api/v1/endpoints/
     ├── core/
     ├── db/
     ├── models/
     ├── schemas/
     └── services/sms/
     ```
  2. Implement `app/core/config.py` using `pydantic-settings`:
     - `DATABASE_URL`: Postgres async DSN (`postgresql+asyncpg://...`)
     - `REDIS_URL`: Redis connection string (`redis://...`)
     - `JWT_SECRET_KEY`: High-entropy 256-bit string
     - `JWT_ALGORITHM`: `"HS256"`
     - `ACCESS_TOKEN_EXPIRE_MINUTES`: Default `60`
     - `REFRESH_TOKEN_EXPIRE_DAYS`: Default `30`
     - `REGISTRATION_TOKEN_EXPIRE_MINUTES`: Default `10`
     - `OTP_EXPIRE_SECONDS`: Default `300`
     - `OTP_COOLDOWN_SECONDS`: Default `60`
     - `SMS_MOCK_MODE`: Boolean flag (default `True` in development)
     - `SMS_GATEWAY_API_KEY`: String
  3. Create async SQLAlchemy session manager in `app/db/session.py`.
  4. Build dependency `get_db()` yielding `AsyncSession` with automatic rollback on unhandled exceptions.
- **Acceptance Criteria:**
  - `GET /health` returns HTTP 200 with DB ping confirmation.
  - Missing mandatory environment variables raise early initialization errors.

---

### STORY-02: Database Models (Users & Refresh Sessions) & Alembic Migrations

- **Goal:** Define database schema for users and server-side refresh sessions with cascading revocations.
- **Dependencies:** STORY-01.
- **Tasks:**
  1. Create `app/models/user.py`:
     - `id`: UUID (Primary Key, default `uuid.uuid4`)
     - `phone`: VARCHAR(16), unique, indexed, non-nullable (E.164 format)
     - `name`: VARCHAR(100), non-nullable (Customer full name for delivery labels)
     - `email`: VARCHAR(255), unique, indexed, nullable
     - `is_active`: BOOLEAN, default `True`, non-nullable
     - `created_at`: TIMESTAMPTZ, default `now()`
     - `updated_at`: TIMESTAMPTZ, default `now()`, onupdate `now()`
  2. Create `app/models/session.py` (`refresh_sessions` table):
     - `id`: UUID (Primary Key, default `uuid.uuid4`)
     - `user_id`: UUID, ForeignKey(`users.id`, ondelete=`CASCADE`), indexed, non-nullable
     - `token_hash`: VARCHAR(64), indexed, non-nullable (SHA-256 of refresh token)
     - `device_id`: VARCHAR(100), nullable (device identification header)
     - `expires_at`: TIMESTAMPTZ, non-nullable
     - `revoked_at`: TIMESTAMPTZ, nullable
     - `replaced_by`: UUID, ForeignKey(`refresh_sessions.id`), nullable
     - `created_at`: TIMESTAMPTZ, default `now()`
  3. Initialize Alembic async environment and generate migration `0001_create_users_and_sessions.py`.
- **Acceptance Criteria:**
  - `alembic upgrade head` runs cleanly.
  - Foreign key cascading deletes refresh sessions when a user is deleted.

---

### STORY-03: Redis Engine — OTP Hashing, Multi-Tier Rate Limiting & Cooldowns

- **Goal:** Build Redis caching, hashing layer, and multi-tier rate limiting for brute-force and toll fraud defense.
- **Dependencies:** STORY-01.
- **Tasks:**
  1. Configure connection pool in `app/core/redis.py` using `redis.asyncio`.
  2. Implement `app/services/otp_service.py`:
     - `hash_secret(value: str) -> str`: Return SHA-256 digest of input.
     - `generate_otp() -> str`: Generate cryptographically secure 6-digit number (`secrets.choice`).
     - `check_send_limits(phone: str, ip: str) -> tuple[bool, Optional[str], int]`:
       - Check key `cooldown:otp:{phone}`. If exists, block request (return remaining TTL).
       - Increment and inspect `rate:otp_phone:{phone}` (limit: 3 per 600s).
       - Increment and inspect `rate:otp_ip:{ip}` (limit: 20 per 600s).
       - Return `(True, None, 0)` or `(False, reason, retry_after)`.
     - `save_otp_hash(phone: str, otp: str, ttl: int = 300) -> None`:
       - Store `otp:{phone}` = `hash_secret(otp)` with TTL.
       - Set `cooldown:otp:{phone}` = `1` with TTL = 60s.
       - Initialize `otp_attempts:{phone}` = `0` with TTL = 300s.
     - `verify_otp_hash(phone: str, submitted_otp: str) -> tuple[bool, str]`:
       - Fetch stored hash from `otp:{phone}`. If missing, return `(False, "EXPIRED_OR_NOT_FOUND")`.
       - Fetch and increment `otp_attempts:{phone}`.
       - If attempts > 5: delete `otp:{phone}`, return `(False, "MAX_ATTEMPTS_EXCEEDED")`.
       - Compare `hash_secret(submitted_otp)` with stored hash.
       - If match: delete `otp:{phone}` and `otp_attempts:{phone}`, return `(True, "VALID")`.
       - If mismatch: return `(False, "INVALID_OTP")`.
- **Acceptance Criteria:**
  - Raw OTP is never stored in Redis plaintext.
  - Multiple rapid requests for the same phone trigger 60s cooldown lock.
  - Exceeding 5 failed verification attempts wipes the OTP key immediately.

---

### STORY-04: SMS Provider Abstraction & Safe Dispatch Service

- **Goal:** Implement an SMS provider interface that only stores OTPs upon successful gateway dispatch.
- **Dependencies:** STORY-01, STORY-03.
- **Tasks:**
  1. Create `app/services/sms/base.py` defining `BaseSMSProvider(ABC)`.
  2. Implement `MockSMSProvider` in `app/services/sms/mock.py`:
     - Logs OTP to console/logger with formatting `[MOCK SMS] To: {phone} | Code: {otp}`.
     - Returns `True`.
  3. Implement `HttpSMSProvider` in `app/services/sms/provider.py` (Twilio/AWS SNS/Fast2SMS client via `httpx.AsyncClient`).
  4. Create factory `get_sms_provider() -> BaseSMSProvider`.
  5. Implement `send_and_store_otp(phone: str, ip: str)` orchestrator:
     - Check rate limits and cooldowns first.
     - Generate OTP.
     - Call SMS provider dispatch.
     - **Only upon successful dispatch (HTTP 200 / True):** execute `save_otp_hash` in Redis.
     - If provider fails, abort and return failure without persisting OTP.
- **Acceptance Criteria:**
  - Failed SMS gateway calls leave no phantom OTP keys in Redis.
  - Mock provider operates seamlessly during local development and testing.

---

### STORY-05: Security Core — Scoped JWT Tokens, Session Hashes & Replay Guard

- **Goal:** Build JWT generation, scope isolation, one-time JTI consumption, and session-rotation utilities.
- **Dependencies:** STORY-01, STORY-02, STORY-03.
- **Tasks:**
  1. Create `app/core/security.py`.
  2. Implement token issuance:
     - `create_access_token(user_id: str) -> str`: JWT with `sub=user_id`, `scope="access"`, exp=60m.
     - `create_refresh_token() -> tuple[str, str]`: Return raw random token and its SHA-256 hash.
     - `create_registration_token(phone: str) -> str`: JWT with `sub=phone`, `scope="register"`, `jti=uuid4()`, exp=10m.
  3. Implement one-time-use token consumption in Redis:
     - `mark_jti_consumed(jti: str, ttl_seconds: int) -> bool`:
       - Execute `redis.set(f"consumed:jti:{jti}", 1, ex=ttl_seconds, nx=True)`.
       - If key already existed, returns `False` (token replay attempt).
  4. Implement dependencies:
     - `get_current_user`: Decodes Bearer token, validates `scope == "access"`, verifies user in DB.
     - `get_verified_registration_claims`: Decodes Bearer token, validates `scope == "register"`, returns `{sub, jti, exp}`.
- **Acceptance Criteria:**
  - Registration token cannot authenticate against protected `/me` endpoint.
  - Attempting to consume a registration token with an existing `jti` is rejected.

---

### STORY-06: Pydantic Validation Schemas & Response DTOs

- **Goal:** Enforce E.164 phone formats, validate names, handle optional emails, and structure API payloads.
- **Dependencies:** None.
- **Tasks:**
  1. Create `app/schemas/auth.py`:
     - `SendOTPRequest`:
       - `phone`: String validated against E.164 regex `^\+[1-9]\d{7,14}$`.
     - `SendOTPResponse`:
       - `message`: str
       - `retry_in_seconds`: int
     - `VerifyOTPRequest`:
       - `phone`: str (E.164)
       - `otp`: str (Regex `^\d{6}$`)
     - `VerifyOTPResponse`:
       - `is_new_user`: bool
       - `registration_token`: Optional[str] = None
       - `access_token`: Optional[str] = None
       - `refresh_token`: Optional[str] = None
       - `token_type`: Optional[str] = "bearer"
     - `RegisterRequest`:
       - `name`: str (min 2, max 100 characters; stripped of leading/trailing whitespace)
       - `email`: Optional[EmailStr] = None
     - `TokenRefreshRequest`:
       - `refresh_token`: str
     - `UserResponse`:
       - `id`: UUID, `phone`: str, `name`: str, `email`: Optional[str], `created_at`: datetime
- **Acceptance Criteria:**
  - Non-numeric or 5-digit OTP submissions fail with HTTP 422 immediately.
  - Names containing only whitespace or invalid email formats are rejected by Pydantic.

---

### STORY-07: API Route — `POST /api/v1/auth/otp/send`

- **Goal:** Endpoint to trigger SMS OTP delivery subject to phone/IP limits and cooldown enforcement.
- **Dependencies:** STORY-03, STORY-04, STORY-06.
- **Tasks:**
  1. Implement handler in `app/api/v1/endpoints/auth.py`:
     - Extract client IP from `request.client.host` (or `X-Forwarded-For` header if behind proxy).
     - Run `check_send_limits(phone, ip)`.
     - If blocked: return HTTP 429 Too Many Requests with header `Retry-After: {retry_in_seconds}`.
     - Dispatch SMS via `send_and_store_otp`.
     - Return HTTP 200:
       ```json
       {
         "message": "OTP sent successfully",
         "retry_in_seconds": 60
       }
       ```
- **Acceptance Criteria:**
  - Requests before 60-second cooldown expires receive HTTP 429.
  - Over 20 requests from the same IP across different numbers receive HTTP 429.

---

### STORY-08: API Route — `POST /api/v1/auth/otp/verify`

- **Goal:** Verify OTP, branch based on user existence, and issue either active login sessions or a scoped registration token.
- **Dependencies:** STORY-02, STORY-03, STORY-05, STORY-06.
- **Tasks:**
  1. Implement handler in `app/api/v1/endpoints/auth.py`:
     - Call `verify_otp_hash(request.phone, request.otp)`.
     - If failure: return HTTP 400 Bad Request with error detail code.
     - Query PostgreSQL: `SELECT * FROM users WHERE phone = :phone`.
     - **Branch A (Existing User):**
       - Issue access token.
       - Generate refresh token and store SHA-256 hash in `refresh_sessions`.
       - Return HTTP 200:
         ```json
         {
           "is_new_user": false,
           "access_token": "...",
           "refresh_token": "...",
           "token_type": "bearer"
         }
         ```
     - **Branch B (New User):**
       - Issue temporary registration token containing `phone` and `jti`.
       - Return HTTP 200:
         ```json
         {
           "is_new_user": true,
           "registration_token": "..."
         }
         ```
- **Acceptance Criteria:**
  - Valid OTP for registered phone logs user in and records session in DB.
  - Valid OTP for unregistered phone returns `is_new_user: true` with registration token.

---

### STORY-09: API Route — `POST /api/v1/auth/register` (One-Time Token Enforced)

- **Goal:** Onboard new customer by validating registration token, verifying JTI was not previously consumed, and creating database profile.
- **Dependencies:** STORY-02, STORY-05, STORY-06.
- **Tasks:**
  1. Implement handler in `app/api/v1/endpoints/auth.py`.
  2. Extract registration claims using `get_verified_registration_claims` dependency.
  3. Validate JTI with `mark_jti_consumed(jti, remaining_ttl)`.
     - If `False`, return HTTP 401 Unauthorized (`"Token has already been consumed"`).
  4. Validate email uniqueness if email provided. If taken: return HTTP 409 Conflict.
  5. Check phone uniqueness (defensive concurrency check). If taken: return HTTP 409 Conflict.
  6. Insert customer record into `users` (`phone`, `name`, `email`).
  7. Generate access token, refresh token, and create record in `refresh_sessions`.
  8. Return HTTP 201 Created with tokens and user profile.
- **Acceptance Criteria:**
  - Submitting the same registration token a second time fails with HTTP 401.
  - Submitting without `Authorization: Bearer <registration_token>` fails with HTTP 401.

---

### STORY-10: API Route — `POST /api/v1/auth/refresh` (Rotation & Revocation) & `GET /api/v1/auth/me`

- **Goal:** Rotate refresh tokens, detect token reuse/theft, and provide user profile access.
- **Dependencies:** STORY-02, STORY-05, STORY-06.
- **Tasks:**
  1. Implement `POST /api/v1/auth/refresh`:
     - Hash the incoming refresh token using SHA-256.
     - Find session in `refresh_sessions` by `token_hash`.
     - **Theft Detection:** If record found but `revoked_at` is NOT NULL (already rotated or revoked), immediately revoke ALL active sessions for that `user_id` and return HTTP 401 Unauthorized.
     - If not found or expired (`expires_at < now()`): return HTTP 401 Unauthorized.
     - Generate new refresh token + access token.
     - Atomically mark old session `revoked_at = now()`, `replaced_by = new_session_id`.
     - Insert new session record in `refresh_sessions`.
     - Return HTTP 200 with new tokens.
  2. Implement `GET /api/v1/auth/me`:
     - Return profile information for authenticated user via `get_current_user`.
- **Acceptance Criteria:**
  - Using an already-rotated refresh token revokes all family sessions and denies access.
  - Successful refresh returns brand new access and refresh tokens.

---

### STORY-11: End-to-End Automated Test Suite & Attack Simulation

- **Goal:** Write integration tests covering all happy paths, security barriers, and abuse vectors.
- **Dependencies:** STORIES 01 through 10.
- **Tasks:**
  1. Configure `tests/conftest.py` with async test DB engine and mock Redis client.
  2. Implement test suite:
     - `test_full_signup_flow`: OTP send -> verify -> register -> access `/me`.
     - `test_existing_user_login`: Direct login without hitting register.
     - `test_cooldown_enforcement`: Two send requests within 10s trigger HTTP 429.
     - `test_ip_rate_limiting`: Exceeding 20 sends triggers HTTP 429.
     - `test_brute_force_otp_wipe`: 5 invalid attempts invalidate code in Redis.
     - `test_registration_token_replay_blocked`: Re-using consumed registration token fails (HTTP 401).
     - `test_refresh_token_theft_revocation`: Re-using an old refresh token invalidates all sessions.
- **Acceptance Criteria:**
  - `pytest tests/` passes with 100% assertions green.
