"""Settings from environment variables, read in one place.

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
