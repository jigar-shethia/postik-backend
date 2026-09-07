"""
User Database Model
===================
This module defines the 'users' table in PostgreSQL for customer profiles.

Beginner Concepts:
------------------
1. **Phone-First Identity**:
   In this system, a user's mobile phone number in E.164 format (e.g., "+1234567890")
   is the primary unique identifier for login. Email is optional.

2. **Database Indexes (`index=True`)**:
   An index is like an alphabetical index at the back of a textbook. Instead of scanning 
   every single row in a table of 1,000,000 users (O(N) full table scan), an index allows 
   PostgreSQL to locate a user by phone or email in microseconds (O(log N)).

3. **Unique Constraints (`unique=True`)**:
   Ensures at the database engine level that no two user rows can ever have the same phone 
   number or email address.

4. **ORM Relationships (`relationship(...)`)**:
   SQLAlchemy allows you to navigate between related tables in Python objects.
   For example, `user.sessions` will return a list of all active/past refresh sessions 
   belonging to that user.
"""

import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.session import RefreshSession


class User(Base, TimestampMixin):
    """
    SQLAlchemy Model representing the 'users' table in PostgreSQL.
    
    Columns:
    --------
    id         : UUID Primary Key.
    phone      : Customer mobile number in E.164 format (e.g. +1234567890). Unique & indexed.
    name       : Customer full name (used for orders and delivery labels).
    email      : Customer email address. Optional, unique & indexed.
    is_active  : Boolean flag allowing administrators to suspend or deactivate accounts.
    created_at : Automatically populated timestamp (from TimestampMixin).
    updated_at : Automatically refreshed timestamp (from TimestampMixin).
    """
    __tablename__ = "users"

    # UUID Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Phone Number (E.164 standard, max 16 chars including '+')
    phone: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        index=True,
        nullable=False,
    )

    # Customer Name (up to 100 characters)
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Optional Email Address
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
    )

    # Account Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationship to user's refresh sessions (cascades deletion)
    sessions: Mapped[List["RefreshSession"]] = relationship(
        "RefreshSession",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
