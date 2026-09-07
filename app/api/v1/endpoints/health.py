"""
Health Check API Endpoint
=========================
This endpoint checks the operational status of the API server and its dependent services
(PostgreSQL database and Redis cache).

Beginner Concepts:
------------------
1. **APIRouter**:
   Instead of attaching all API routes directly to the main `app` object in one massive file, 
   FastAPI uses `APIRouter` to split routes into clean, modular files based on feature or version
   (e.g., health routes, auth routes, user routes).

2. **Liveness vs. Readiness Probes**:
   In cloud deployments (like Kubernetes, AWS, or Docker Swarm), health check endpoints are 
   polled every few seconds to determine if the container is healthy and able to receive traffic.
   If PostgreSQL or Redis is down, this endpoint reports "degraded" or "unhealthy".
"""

from fastapi import APIRouter
from app.core.config import settings
from app.core.redis import check_redis_health
from app.db.session import check_db_health
from app.schemas.health import HealthCheckResponse, ServiceStatus

# Create a dedicated router for health check endpoints
router = APIRouter()


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health Check",
    description="Check if the API service, PostgreSQL database, and Redis cache are alive and healthy.",
)
async def health_check() -> HealthCheckResponse:
    """
    Handler for GET /api/v1/health.
    
    Data Flow:
    1. Runs asynchronous health checks against PostgreSQL (SELECT 1) and Redis (PING).
    2. Determines overall health state ('healthy', 'degraded', or 'unhealthy').
    3. Builds and returns a validated `HealthCheckResponse` JSON object.
    """
    # 1. Ping backing services concurrently/asynchronously
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()

    # 2. Formulate individual statuses
    db_status = "healthy" if db_ok else "unhealthy"
    redis_status = "healthy" if redis_ok else "unhealthy"

    # 3. Formulate overall system status
    overall_status = (
        "healthy"
        if (db_ok and redis_ok)
        else ("degraded" if (db_ok or redis_ok) else "unhealthy")
    )

    # 4. Return serialized response
    return HealthCheckResponse(
        status=overall_status,
        app_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        services=ServiceStatus(
            database=db_status,
            redis=redis_status,
        ),
    )
