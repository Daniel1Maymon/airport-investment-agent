"""Opens the airport database read-only, so the app can never change it.

What it is:   One function that opens the DuckDB airport file in read-only mode.
Why we need:  The app must never change airport data. Read-only makes every write fail,
              even if a bug or a tricky question tried one.
Used by:      app/agent/cli.py.
              tests: conftest.py, test_step00_setup.py, test_step05_build.py,
              test_step06_measures.py, test_step09_resolver.py.
              Planned: Step 16 backend API.
Uses:         the airport database file (`airports.duckdb`, built by loader/build.py).
Main parts:   open_airport_db(path) - a read-only DuckDB connection to the file at `path`.
Design:       docs/decisions.md 7.20; docs/agent.md "Safety".
"""

import duckdb


def open_airport_db(path):
    """Return a read-only DuckDB connection to the airport database at `path`."""
    return duckdb.connect(str(path), read_only=True)
