"""
Refresh Session Database Model
==============================
This module defines the 'refresh_sessions' table in PostgreSQL for tracking long-lived 
authentication refresh tokens on the server side.

Beginner Concepts:
------------------
1. **Access Tokens vs. Refresh Tokens**:
   - **Access Token (JWT)**: Short-lived (e.g. 60 minutes). Sent in every API request header 
     (`Authorization: Bearer <token>`). The server validates its digital signature without hitting 
     the database.
   - **Refresh Token**: Long-lived (e.g. 30 days). Used ONLY when the access token expires to obtain 
     a new access token without asking the user to re-enter an OTP.

2. **Why Store Hashes (`token_hash`) Instead of Raw Tokens?**:
   Just like passwords should never be stored in plaintext, storing raw refresh tokens in the database 
   is a security risk. If an attacker dumps the database, they cannot impersonate active users because 
   we only store the irreversible cryptographic SHA-256 digest (`token_hash`).

3. **Cascading Deletions (`ondelete="CASCADE"`)**:
   When a user account is deleted from the `users` table, PostgreSQL automatically purges all of their 
   associated refresh sessions immediately, preventing orphan records.

4. **Token Rotation & Theft Detection (`replaced_by` & `revoked_at`)**:
   Every time a refresh token is used, it is rotated (revoked and replaced by a new session).
   If an old, already-revoked refresh token is ever submitted again, the system recognizes a token 
   theft attempt and can immediately invalidate the entire session family for that user.
"""

import datetime
import uuid
from typing import TYPE_CHECKING, Optional
from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class RefreshSession(Base):
    """
    SQLAlchemy Model representing the 'refresh_sessions' table in PostgreSQL.
    """
    __tablename__ = "refresh_sessions"

    # UUID Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Foreign Key linking to the User who owns this session
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # SHA-256 hash of the refresh token (64 hexadecimal characters)
    token_hash: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )

    # Optional client device identifier (e.g., "iPhone 15 Pro iOS 17.4" or UUID)
    device_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    # Timestamp when this refresh session will expire (typically 30 days from creation)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Timestamp when this token was revoked/rotated (NULL if still active)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Pointer to the new session ID that replaced this one during token rotation
    replaced_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("refresh_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timestamp when the session was created
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship back to the User model
    user: Mapped["User"] = relationship(
        "User",
        back_populates="sessions",
    )
