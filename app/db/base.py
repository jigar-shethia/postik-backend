"""
SQLAlchemy Declarative Base & Shared Mixins
===========================================
This module defines the foundational classes that all database models inherit from.

Beginner Concepts:
------------------
1. **ORM (Object-Relational Mapping)**:
   An ORM allows you to define database tables as standard Python classes.
   Instead of writing raw SQL strings like:
       `SELECT * FROM users WHERE phone = '+1234567890';`
   You can write Python code:
       `await db.scalar(select(User).where(User.phone == phone))`
   SQLAlchemy translates your Python code into optimized SQL queries for PostgreSQL.

2. **DeclarativeBase**:
   In SQLAlchemy 2.0, `DeclarativeBase` is the superclass for all models.
   It maintains a `metadata` catalog of all your tables and columns so Alembic (the migration tool)
   can automatically detect schema changes.

3. **Mixins (DRY Principle - Don't Repeat Yourself)**:
   Almost every table in a production system needs timestamp columns (`created_at` and `updated_at`).
   Rather than defining these two columns in every single table, we create a `TimestampMixin`
   and inherit from it.
"""

import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Root base class for all database tables.
    Every model in `app/models/` will inherit from this class.
    """
    pass


class TimestampMixin:
    """
    A reusable mixin that adds automated UTC timestamp tracking to any model.
    
    Attributes:
    -----------
    created_at : Timestamp when the row was first inserted (defaults to current database time).
    updated_at : Timestamp that automatically refreshes whenever the row is updated.
    """
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # Tells PostgreSQL to execute now() at insert time
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),        # Tells SQLAlchemy to refresh timestamp on updates
        nullable=False,
    )
