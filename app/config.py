"""Settings from environment variables, read in one place.

What it is:   The `Settings` class: the five settings the app needs, each read from an
              environment variable, with a default where one makes sense.
Why we need:  One place for settings, so no other file reads environment variables itself.
Used by:      tests: conftest.py, test_step00_setup.py.
              Planned: Step 16 backend API, `create_app(settings)`.
Uses:         environment variables AIRPORTS_DB, CHAT_DB, OPENROUTER_API_KEY,
              OPENROUTER_MODEL, ALLOWED_ORIGIN. No other project file.
Main parts:   Settings - airports_db, chat_db, openrouter_api_key, openrouter_model,
                allowed_origin.
Design:       docs/implementation-plan.md "Shared ground rules for the code" (Settings), P8.

The environment is read when `Settings()` is created, not when this module is
imported, so a changed variable is seen by the next `Settings()`.
"""

import os
from dataclasses import dataclass, field


def _env(name, default=None):
    return field(default_factory=lambda: os.environ.get(name, default))


@dataclass
class Settings:
    airports_db: str = _env("AIRPORTS_DB", "airports.duckdb")
    chat_db: str = _env("CHAT_DB", "chat.sqlite")
    openrouter_api_key: str | None = _env("OPENROUTER_API_KEY")
    openrouter_model: str | None = _env("OPENROUTER_MODEL")
    allowed_origin: str | None = _env("ALLOWED_ORIGIN")
