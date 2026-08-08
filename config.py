"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for the bot."""

    discord_token: str
    groq_api_key: str | None
    groq_model: str
    github_token: str | None
    prefix: str
    database_path: Path
    log_level: str

    @classmethod
    def from_environment(cls) -> "Settings":
        """Create settings from the environment without exposing secrets."""
        database_value = os.getenv("DATABASE_PATH", "data/levels.db")
        database_path = Path(database_value)
        if not database_path.is_absolute():
            database_path = BASE_DIR / database_path

        return cls(
            discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            groq_model=os.getenv(
                "GROQ_MODEL", "llama-3.3-70b-versatile"
            ).strip(),
            github_token=os.getenv("GITHUB_TOKEN") or None,
            prefix=os.getenv("PREFIX", "!").strip() or "!",
            database_path=database_path,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def validate(self) -> None:
        """Validate settings required to start Discord connectivity."""
        if not self.discord_token:
            raise RuntimeError(
                "DISCORD_TOKEN is required. Copy .env.example to .env and set it."
            )
        if len(self.prefix) > 16:
            raise RuntimeError("PREFIX must be 16 characters or fewer.")

