# Postik Backend (FastAPI + PostgreSQL + Redis)

Production-ready, phone-first OTP authentication, user onboarding, and session rotation backend built with **FastAPI**, **PostgreSQL** (Async SQLAlchemy 2.0), and **Redis**.

---

## 📁 Project Structure

```text
postik-backend/
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration version scripts
│   │   └── 0001_create_users_and_sessions.py
│   ├── env.py                    # Alembic runtime config
│   └── script.py.mako            # Migration file template
├── app/
│   ├── api/
│   │   ├── deps.py               # Dependency injection (SessionDep, RedisDep, CurrentUserDep)
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py       # Full OTP authentication and onboarding routes
│   │       │   └── health.py     # Multi-service health check endpoint
│   │       └── router.py         # API v1 Master Router
│   ├── core/
│   │   ├── config.py             # App configuration & Pydantic settings
│   │   ├── redis.py              # Async Redis connection pool & health check
│   │   └── security.py           # Scoped JWTs, hashing & JTI replay guard
│   ├── db/
│   │   ├── base.py               # SQLAlchemy Declarative Base & TimestampMixin
│   │   └── session.py            # Async PostgreSQL engine & sessionmaker (asyncpg)
│   ├── models/                   # Database ORM models (User, RefreshSession, Post)
│   ├── schemas/                  # Pydantic validation schemas & DTOs
│   │   ├── auth.py
│   │   └── health.py
│   ├── services/                 # Business logic & SMS dispatcher
│   │   ├── otp_service.py        # OTP hashing, 60s cooldown & rate limiting
│   │   └── sms/                  # SMS Provider abstraction (Mock & HTTP)
│   └── main.py                   # FastAPI app instance, CORS & lifespan cleanup
├── tests/                        # Automated test suite
│   ├── conftest.py               # In-memory test DB, FakeRedis & AsyncClient fixtures
│   └── test_auth_flow.py         # Comprehensive E2E tests & attack simulations
├── .env.example                  # Environment configuration template
├── .gitignore
├── alembic.ini                   # Alembic configuration
├── pytest.ini                    # Pytest configuration
├── requirements.txt              # Project dependencies
├── ARCHITECTURE_AND_DATA_FLOW.md # Beginner architectural guide
└── README.md
```

---

## 🚀 Quick Start

### 1. Create and Activate Virtual Environment

```bash
# Navigate to the backend folder
cd postik-backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment (macOS / Linux):
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Setup Environment Variables

```bash
cp .env.example .env
```
Edit `.env` to configure your credentials:
```env
POSTGRES_SERVER=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postik_db

REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=your-secure-jwt-secret-key-at-least-32-chars
SMS_MOCK_MODE=True
```

### 4. Database Migrations (Alembic)

```bash
# Apply migrations to PostgreSQL:
alembic upgrade head
```

### 5. Run the Development Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 🧪 Running Automated Tests

Run the full end-to-end test suite (uses in-memory test database and FakeRedis):

```bash
pytest
```

---

## 📖 API Documentation & Endpoints

Once the server is running:
* **Interactive Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc UI:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **Health Check:** `GET /api/v1/health` (or `GET /health`)
* **Send OTP:** `POST /api/v1/auth/otp/send`
* **Verify OTP:** `POST /api/v1/auth/otp/verify`
* **Register Profile:** `POST /api/v1/auth/register` (Bearer `<registration_token>`)
* **Rotate Tokens:** `POST /api/v1/auth/refresh`
* **Current Profile:** `GET /api/v1/auth/me` (Bearer `<access_token>`)
