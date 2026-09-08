"""Async PostgreSQL access.

SQLAlchemy ORM models for the Phase-1 tables arrive with the migrations (Phase 1,
Unit 3); this module provides the engine, session, and transaction plumbing they
will use.
"""

from __future__ import annotations

from .engine import build_engine
from .session import Database

__all__ = ["Database", "build_engine"]
