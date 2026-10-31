"""Opens the airport database read-only, so the app can never change it."""

import duckdb


def open_airport_db(path):
    """Return a read-only DuckDB connection to the airport database at `path`."""
    return duckdb.connect(str(path), read_only=True)
