"""
Health Check Pydantic Schemas (Data Transfer Objects)
=====================================================
This module defines the response structure for health check endpoints.

Beginner Concepts:
------------------
1. **Pydantic Schemas / DTOs (Data Transfer Objects)**:
   In FastAPI, we use Pydantic models to define the exact shape of incoming JSON request bodies 
   and outgoing JSON responses.
   - For incoming requests: Pydantic validates data types (e.g. valid email, 6-digit integer string).
   - For outgoing responses: Pydantic serializes your Python objects to JSON and guarantees the frontend 
     always receives consistent, typed JSON keys.

2. **OpenAPI / Swagger Generation**:
   FastAPI reads these Pydantic models to automatically generate interactive API documentation 
   at `/docs` and `/redoc`.
"""

from pydantic import BaseModel


class ServiceStatus(BaseModel):
    """
    Sub-schema detailing the connection health of individual backing services.
    Values are typically 'healthy' or 'unhealthy'.
    """
    database: str
    redis: str


class HealthCheckResponse(BaseModel):
    """
    Top-level response model returned by GET /health and GET /api/v1/health.
    
    Example JSON Output:
    --------------------
    {
      "status": "healthy",
      "app_name": "Postik API",
      "version": "0.1.0",
      "environment": "development",
      "services": {
        "database": "healthy",
        "redis": "healthy"
      }
    }
    """
    status: str
    app_name: str
    version: str
    environment: str
    services: ServiceStatus
