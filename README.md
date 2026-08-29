# Postik Backend (FastAPI + PostgreSQL)

Base FastAPI backend setup with PostgreSQL (Async SQLAlchemy 2.0) and Alembic migrations for the Postik application.

## Project Structure

```text
Backend/
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration version scripts
│   ├── env.py                    # Alembic runtime config
│   └── script.py.mako            # Migration file template
├── app/
│   ├── api/
│   │   ├── deps.py               # SessionDep and dependency injection
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   └── health.py     # Health check endpoint
│   │       └── router.py         # API v1 Router aggregation
│   ├── core/
│   │   └── config.py             # App configuration & Postgres URI
│   ├── db/
│   │   ├── base.py               # SQLAlchemy Declarative Base & Mixins
│   │   └── session.py            # Async engine & sessionmaker (asyncpg)
│   ├── models/                   # Database ORM models (e.g. post.py)
│   ├── schemas/                  # Pydantic schemas (DTOs)
│   │   └── health.py
│   ├── services/                 # Business logic layer
│   └── main.py                   # FastAPI app instance and middleware
├── .env.example                  # Sample environment variables (PostgreSQL config)
├── .gitignore
├── alembic.ini                   # Alembic configuration
├── requirements.txt              # FastAPI, SQLAlchemy, asyncpg, Alembic
└── README.md
```

## Quick Start

### 1. Create and activate a Virtual Environment

```bash
# Navigate to the Backend folder
cd /Users/jigarshethia/Documents/Postik/Backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
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
Edit `.env` to match your local PostgreSQL credentials:
```env
POSTGRES_SERVER=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postik_db
```

### 4. Database Migrations (Alembic)

```bash
# Generate a new migration after creating/updating models:
alembic revision --autogenerate -m "initial migration"

# Apply migrations to PostgreSQL:
alembic upgrade head
```

### 5. Run the Development Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Documentation

Once the server is running, visit:
- **Interactive Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc UI:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check Endpoint:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

