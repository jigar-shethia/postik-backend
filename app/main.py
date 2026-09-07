"""
FastAPI Main Application Entry Point
====================================
This is the root application file where the FastAPI app instance is created, 
middleware is configured, lifecycle hooks are defined, and routers are mounted.

Beginner Concepts:
------------------
1. **Application Lifespan (`@asynccontextmanager`)**:
   Code before `yield` runs ONCE when the server boots up (e.g. initializing caches).
   Code after `yield` runs ONCE when the server shuts down (e.g. closing database & Redis connection pools).
   This ensures clean resource management with no memory or socket leaks.

2. **Middleware (CORS)**:
   Middleware is a piece of code that intercepts every incoming HTTP request BEFORE it reaches 
   your route handler, and intercepts every HTTP response BEFORE it returns to the client.
   CORS middleware adds necessary security headers allowing cross-origin requests from web/mobile frontends.

3. **Routing Architecture**:
   - Root URL `/` -> redirects to `/docs` (Interactive Swagger UI).
   - Root `/health` -> returns instant health check.
   - Versioned `/api/v1/...` -> routes all v1 API endpoints.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.v1.endpoints.health import health_check
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.redis import close_redis_connection
from app.db.session import close_db_connection


# ------------------------------------------------------------------------------
# 1. Application Lifespan Hook
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown events cleanly.
    """
    # === STARTUP ===
    # (e.g., warm up connections, start background workers)
    yield
    # === SHUTDOWN ===
    # Close open network pools gracefully
    await close_redis_connection()
    await close_db_connection()


# ------------------------------------------------------------------------------
# 2. FastAPI App Instance
# ------------------------------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",      # Interactive Swagger UI URL
    redoc_url="/redoc",    # Alternative ReDoc documentation URL
    lifespan=lifespan,
)

# ------------------------------------------------------------------------------
# 3. CORS Middleware Configuration
# ------------------------------------------------------------------------------
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],    # Allow GET, POST, PUT, DELETE, OPTIONS, etc.
        allow_headers=["*"],    # Allow all headers (Authorization, Content-Type, etc.)
    )

# ------------------------------------------------------------------------------
# 4. Route Registration
# ------------------------------------------------------------------------------
# Register top-level /health endpoint (useful for load balancers and container probes)
app.add_api_route(
    "/health", 
    health_check, 
    methods=["GET"], 
    tags=["Health"], 
    include_in_schema=False
)

# Mount all version 1 endpoints under /api/v1 prefix
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", include_in_schema=False)
async def root_redirect():
    """
    Redirects root visitors directly to the interactive OpenAPI Swagger documentation.
    """
    return RedirectResponse(url="/docs")
