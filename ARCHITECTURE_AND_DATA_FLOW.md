# Postik Backend: Architecture & Data Flow Guide

Welcome to the **Postik Backend**! This document is designed for beginners to understand how a modern production-grade backend works, what each file is responsible for, how data travels through the system, and why each design pattern was chosen.

---

## 🏛️ 1. High-Level Architecture

The backend consists of four primary components:

```
                      ┌──────────────────────────────────────────────┐
                      │            Frontend Mobile & Web App         │
                      │               (iOS, Android, Web)            │
                      └──────────────────────┬───────────────────────┘
                                             │ HTTP REST / JSON
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              FastAPI Application             │
                      │  - CORS Middleware                          │
                      │  - Pydantic Validation (Incoming / Outgoing) │
                      │  - Dependency Injection (Sessions, Redis)    │
                      │  - Route Controllers & Business Logic        │
                      └──────────────┬────────────────┬──────────────┘
                                     │                │
                    SQL Queries via  │                │ Key-Value Fast Ops
                    AsyncPG & Engine │                │ (OTPs, Rate Limits)
                                     ▼                ▼
                      ┌──────────────────────┐ ┌─────────────────────┐
                      │ PostgreSQL Database  │ │     Redis Cache     │
                      │  - Permanent Data    │ │  - In-Memory RAM    │
                      │  - Users & Sessions  │ │  - 5-min OTP store  │
                      │  - Relational Schema │ │  - Rate Limiting    │
                      └──────────────────────┘ └─────────────────────┘
```

1. **FastAPI (Web Framework):** Handles incoming HTTP requests, runs asynchronous logic, validates data with Pydantic, and generates automatic OpenAPI documentation (`/docs`).
2. **PostgreSQL (Persistent Database):** The permanent SQL relational database storing users, sessions, posts, and relational domain data.
3. **Redis (In-Memory Data Store):** Fast, volatile RAM storage used for OTP codes (5-minute TTL), cooldown timers (60s), rate limiting counters, and one-time token replay prevention.
4. **Alembic (Database Migrations):** Tracks database schema changes over time (creating tables, adding columns) through versioned Python migration scripts.

---

## 📂 2. File & Directory Map

Here is the exact purpose of every file and folder in `postik-backend/`:

```text
postik-backend/
├── alembic/                         # Database Migration Engine
│   ├── env.py                        # Configures Alembic to read our settings & SQLAlchemy models
│   ├── script.py.mako               # Template for newly generated migration files
│   └── versions/                    # Folder where migration history (.py scripts) is saved
│
├── app/                             # Core Application Source Code
│   ├── api/                         # API Layer (Routing & Dependencies)
│   │   ├── deps.py                  # Reusable Dependency Injections (SessionDep, RedisDep)
│   │   └── v1/                      # Version 1 of our API
│   │       ├── router.py            # Master router combining all v1 feature endpoints
│   │       └── endpoints/           # 
│   │           └── health.py        # GET /api/v1/health (DB + Redis liveness checks)
│   │
│   ├── core/                        # System Configurations & Singletons
│   │   ├── config.py                # Pydantic Settings reading .env variables
│   │   └── r edis.py                 # Async Redis connection pool and health checks
│   │
│   ├── db/                          # Database Core Setup
│   │   ├── base.py                  # Declarative Base class & TimestampMixin
│   │   └── session.py               # Async PostgreSQL Engine & get_db() session generator
│   │
│   ├── models/                      # Database ORM Models (SQLAlchemy)
│   │   ├── __init__.py              # Exports models for Alembic auto-detection
│   │   └── post.py                  # Example model representing a database table
│   │
│   ├── schemas/                     # Data Transfer Objects (Pydantic Schemas)
│   │   └── health.py                # Validates incoming/outgoing JSON structure for health checks
│   │
│   ├── services/                    # Business Logic Layer
│   │   └── sms/                     # SMS Provider integrations (Mock & HTTP SMS)
│   │
│   └── main.py                      # Root FastAPI entry point, lifespan events & middleware
│
├── .env.example                     # Template showing required environment variables
├── .gitignore                       # Tells Git which files to ignore (e.g. .venv, .env, __pycache__)
├── alembic.ini                      # Configuration file for Alembic CLI
├── requirements.txt                 # List of Python library dependencies
└── README.md                        # Quickstart instructions to run the project
```

---

## 🔄 3. End-to-End Request & Data Flow

When a client (like an iOS/Android app) makes a request (e.g., `GET /api/v1/health`), here is the step-by-step lifecycle:

```
[1. Client Request]
       │  (e.g., GET http://localhost:8000/api/v1/health)
       ▼
[2. CORS Middleware in main.py]
       │  Checks if client origin (e.g., localhost:3000) is allowed.
       ▼
[3. FastAPI Routing (main.py -> v1/router.py -> endpoints/health.py)]
       │  Matches URL path to the `health_check()` handler function.
       ▼
[4. Dependency Injection (api/deps.py)]
       │  (If the endpoint needs DB or Redis, get_db() or get_redis()
       │   automatically borrows an active connection from the pool).
       ▼
[5. Controller Logic & Backing Services]
       ├── Executes `check_db_health()` (runs `SELECT 1` on PostgreSQL).
       └── Executes `check_redis_health()` (runs `PING` on Redis).
       ▼
[6. Pydantic Response Serialization (schemas/health.py)]
       │  Converts the Python dictionaries into a strictly validated `HealthCheckResponse`.
       ▼
[7. Lifecycle Cleanup]
       │  `get_db()` automatically commits or rolls back, and returns the DB connection.
       ▼
[8. HTTP 200 JSON Response Sent to Client]
```

---

## 🧠 4. Core Backend Concepts Explained Simply

### A. Async / Await & Asynchronous I/O
* **Synchronous (Blocking):** The server pauses and waits whenever it queries PostgreSQL or Redis. If a query takes 50ms, that server thread cannot do anything else during those 50ms.
* **Asynchronous (`async` / `await`):** When code calls `await session.execute(...)`, Python pauses *only that specific request task* and continues processing other incoming requests. Once the database responds, Python resumes the task. This allows a single FastAPI process to handle thousands of concurrent users.

### B. Dependency Injection (DI)
Instead of hardcoding connections inside every function:
```python
# ❌ Without DI (Messy, difficult to test, connection leaks)
@router.get("/users")
async def get_users():
    db = create_new_database_connection() # Slow and risky
    users = db.query(...)
    db.close()
    return users
```
FastAPI uses **Dependency Injection**:
```python
# ✅ With DI (Clean, pooled, automatic error rollback)
@router.get("/users")
async def get_users(db: SessionDep):
    # db is automatically provided, managed, and closed for you!
    return await db.scalars(select(User))
```

### C. Schemas vs. Models (Pydantic vs. SQLAlchemy)
* **SQLAlchemy Models (`app/models/`):** Define how data is stored in **PostgreSQL tables** (columns, foreign keys, indexes, table names).
* **Pydantic Schemas (`app/schemas/`):** Define how data is transferred over the **network via JSON** (validating input format, sanitizing outputs, hiding sensitive fields like passwords or internal hashes).

### D. Connection Pooling
Opening a new TCP network handshake to PostgreSQL for every user click takes 10-30 milliseconds. A **Connection Pool** keeps a pool (e.g. 10 connections) permanently open. When a request starts, it borrows a connection; when the request finishes, it returns the connection back to the pool instantly.

---

## 🔐 5. How Upcoming Authentication Stories Work (Preview)

Our authentication system is designed as a **Phone-first, OTP-based flow** with enterprise-grade security:

```
Step 1: User enters Phone Number
  │
  ├─► POST /api/v1/auth/otp/send
  │     1. Redis checks Rate Limits (max 3 sends per 10 mins per phone, max 20 per IP).
  │     2. Redis checks 60-second Cooldown lock.
  │     3. Safe Dispatch: SMS is sent via provider.
  │     4. ONLY upon HTTP 200 from SMS gateway -> SHA-256(OTP) is saved in Redis (TTL: 5m).
  │
Step 2: User submits 6-digit OTP
  │
  ├─► POST /api/v1/auth/otp/verify
  │     1. Hashes user input with SHA-256 and compares against Redis hash.
  │     2. Max 5 failed attempts allowed (wipes OTP on limit to block brute-force).
  │     3. Checks if user exists in PostgreSQL:
  │         ├─ Existing User: Issues Access Token + Refresh Token (Login Complete).
  │         └─ New User: Issues a short-lived `registration_token` (Scope: "register", TTL: 10m).
  │
Step 3: New User Completes Profile
  │
  └─► POST /api/v1/auth/register (Headers: Bearer <registration_token>)
        1. Validates cryptographic signature and verifies scope == "register".
        2. Atomic Redis check (`SET NX`) ensures this registration token has never been used before.
        3. Inserts customer into PostgreSQL `users` table.
        4. Issues Access Token + Refresh Token (Onboarding Complete).
```

---

## 📚 6. Beginner Glossary

| Term | Meaning |
| :--- | :--- |
| **Endpoint / Route** | A specific URL path and HTTP method (e.g. `POST /api/v1/auth/otp/send`) that triggers server logic. |
| **DTO (Data Transfer Object)** | A Pydantic schema used to send or receive structured JSON data over the network. |
| **ORM** | Object-Relational Mapper (SQLAlchemy) that translates Python objects into SQL queries. |
| **TTL (Time to Live)** | An expiration timer (in seconds) after which Redis automatically deletes a key. |
| **JWT (JSON Web Token)** | A digitally signed token carrying user claims (e.g. user ID, expiration time) that the client sends in the `Authorization: Bearer <token>` header. |
| **CORS** | Cross-Origin Resource Sharing — browser security mechanism controlling which websites can talk to your backend. |
| **Alembic Revision** | A Python script that applies schema changes (like `CREATE TABLE`) to the database in a version-controlled way. |
