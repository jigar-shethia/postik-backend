"""
API Version 1 (v1) Aggregated Router
====================================
This file aggregates all individual endpoint routers (health, auth, users, etc.) 
under the `/api/v1` namespace.

Beginner Concepts:
------------------
1. **API Versioning (`/v1`, `/v2`)**:
   As mobile apps and web clients evolve, breaking changes may be introduced.
   Versioning your API allows older app versions (e.g. running v1) to continue working
   uninterrupted while newer versions use `/v2`.

2. **Router Aggregation**:
   Each sub-module (like `health.py` or `auth.py`) has its own `APIRouter`.
   This master router includes them all and organizes them with OpenAPI tags for Swagger UI.
"""

from fastapi import APIRouter
from app.api.v1.endpoints import auth, health

# Create the top-level v1 router
api_router = APIRouter()

# Include health endpoints under the "Health" OpenAPI tag
api_router.include_router(health.router, tags=["Health"])

# Include authentication endpoints under the "Authentication" OpenAPI tag
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
