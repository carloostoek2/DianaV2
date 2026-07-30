"""E2E: Alembic migrations apply cleanly."""
import pytest
import subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.db
def test_alembic_upgrade_head_applies_cleanly(alembic_applied):
    """Alembic head migration applies without errors (validated by fixture)."""
    assert alembic_applied is None  # Fixture already ran


@pytest.mark.db
def test_alembic_current_shows_head(alembic_database_url):
    """After upgrade, alembic current shows the head revision."""
    import os
    env = os.environ.copy()
    env["DATABASE_URL"] = alembic_database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=str(PROJECT_ROOT), env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "head" in result.stdout.lower() or "(head)" in result.stdout


@pytest.mark.db
def test_alembic_history_has_expected_revisions(alembic_database_url):
    """Alembic history shows migration revisions."""
    import os
    env = os.environ.copy()
    env["DATABASE_URL"] = alembic_database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "history"],
        cwd=str(PROJECT_ROOT), env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    # Should have at least the F1 foundation migrations
    assert len(result.stdout.strip().splitlines()) >= 10
