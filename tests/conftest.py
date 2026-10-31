"""Shared test fixtures: the tiny database, the real database, a chat file path."""

from pathlib import Path

import pytest

from app.config import Settings
from app.db import open_airport_db
from tests.fixtures.tiny_data import build_tiny_db


@pytest.fixture
def tiny_db(tmp_path):
    """Read-only connection to a freshly built tiny database."""
    path = tmp_path / "tiny.duckdb"
    build_tiny_db(path)
    con = open_airport_db(path)
    yield con
    con.close()


@pytest.fixture
def real_db():
    """Read-only connection to the real airports.duckdb; skips when it is missing.

    AIRPORTS_DB is read here, when the test runs, not at import time.
    """
    path = Path(Settings().airports_db)
    if not path.exists():
        pytest.skip(f"real database not found: {path}")
    con = open_airport_db(path)
    yield con
    con.close()


@pytest.fixture
def tmp_chat_path(tmp_path):
    """A path for a chat.sqlite file that does not exist yet."""
    return tmp_path / "chat.sqlite"
