"""Tier-2 fixtures — all DB fixtures moved to tests/e2e/conftest.py (parent).

This file remains as a placeholder so the package exists on disk.
All DB infrastructure (pg_container, database_url, engine, etc.) is
inherited via pytest's conftest cascade from tests/e2e/conftest.py.
"""
