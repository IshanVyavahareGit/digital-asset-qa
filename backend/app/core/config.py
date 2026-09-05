"""Application configuration.

All environment-driven settings live in ONE typed object so the rest of the code
never touches os.environ directly. Values are read from a local `.env` file
(see .env.example) and validated by pydantic-settings at startup.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo layout anchors (…/backend/app/core/config.py -> backend/ -> repo root)
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- AI ---
    gemini_api_key: str = ""       # required for AI checks; empty -> checks report `failed`
    gemini_model: str = ""         # native 0-1000 bounding boxes + strong OCR

    # --- Auth ---
    jwt_secret: str = ""            # override in .env for anything real
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12     # 12h; comfortable for a demo session

    # --- Persistence ---
    # Both the SQLite file and uploaded images live under data/ (mounted as a
    # docker volume) so they survive restarts and page refreshes.
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'app.db'}"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"

    # --- Asset pack (roster, sponsors, brand guide, safe zones) ---
    assets_dir: Path = REPO_ROOT / "assets"

    # --- CORS (Next.js dev + docker) ---
    # cors_origins: list[str] = ["*"]
    # --- CORS (Next.js dev + docker) ---
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]

    def ensure_dirs(self) -> None:
        """Create writable dirs on boot (idempotent)."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        Path(self.database_url.replace("sqlite:///", "")).parent.mkdir(
            parents=True, exist_ok=True
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so every import shares one parsed config."""
    return Settings()


settings = get_settings()
