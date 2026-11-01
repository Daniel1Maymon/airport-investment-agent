"""Settings from environment variables, read in one place.

What it is:   The `Settings` class: the six settings the app needs, each read from an
              environment variable, with a default where one makes sense.
Why we need:  One place for settings, so no other file reads environment variables itself.
Used by:      app/agent/cli.py.
              tests: conftest.py, test_step00_setup.py.
              app/api.py (`create_app(settings)`, `main_app()`).
              app/admin.py (admin_token, for the admin token check, Step 19).
              tests: test_step19_admin.py.
Uses:         environment variables AIRPORTS_DB, CHAT_DB, OPENROUTER_API_KEY,
              OPENROUTER_MODEL, ALLOWED_ORIGIN, ADMIN_TOKEN. No other project file.
              Online, the Dockerfile sets AIRPORTS_DB and CHAT_DB (P118); the rest are
              Railway settings (P121).
Main parts:   Settings - airports_db, chat_db, openrouter_api_key, openrouter_model,
                allowed_origin, admin_token.
Design:       docs/implementation-plan.md "Shared ground rules for the code" (Settings), P8;
              P123 (ADMIN_TOKEN).

The environment is read when `Settings()` is created, not when this module is
imported, so a changed variable is seen by the next `Settings()`.
"""

import os
from dataclasses import dataclass, field


def _env(name, default=None):
    """A dataclass field filled from environment variable `name` when Settings() is made."""
    return field(default_factory=lambda: os.environ.get(name, default))


@dataclass
class Settings:
    airports_db: str = _env("AIRPORTS_DB", "airports.duckdb")
    chat_db: str = _env("CHAT_DB", "chat.sqlite")
    openrouter_api_key: str | None = _env("OPENROUTER_API_KEY")
    openrouter_model: str | None = _env("OPENROUTER_MODEL")
    allowed_origin: str | None = _env("ALLOWED_ORIGIN")
    # The admin dashboard's password (P123). Not set = the dashboard is locked (P124).
    admin_token: str | None = _env("ADMIN_TOKEN")
