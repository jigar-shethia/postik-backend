"""
Pydantic Schemas Package (Data Transfer Objects)
================================================
This package exports all request validation models and response DTOs.
"""

from app.schemas.auth import (
    AuthResponse,
    RegisterRequest,
    SendOTPRequest,
    SendOTPResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserResponse,
    VerifyOTPRequest,
    VerifyOTPResponse,
)
from app.schemas.health import HealthCheckResponse, ServiceStatus

__all__ = [
    "HealthCheckResponse",
    "ServiceStatus",
    "SendOTPRequest",
    "SendOTPResponse",
    "VerifyOTPRequest",
    "VerifyOTPResponse",
    "RegisterRequest",
    "TokenRefreshRequest",
    "TokenRefreshResponse",
    "UserResponse",
    "AuthResponse",
]
