from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and secrets.env."""

    app_name: str = "Survival of the Fittest"
    app_env: str = "local"
    debug: bool = True
    log_level: str = "INFO"

    database_url: str = "sqlite:///data/survival.db"
    data_dir: Path = Path("data")
    audio_dir: Path = Path("data/audio")
    recordings_dir: Path = Path("data/recordings")

    google_api_key: str = Field(default="", repr=False)
    cartesia_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-3.1-flash-lite-preview"
    cartesia_tts_model: str = "sonic-3"
    cartesia_voice_id: str = "f786b574-daa5-4673-aa0c-cbe3e8534c02"
    cartesia_api_version: str = "2024-11-13"
    cartesia_language: str = "en"

    min_population: int = 12
    max_population: int = 30
    evolution_win_threshold: int = 3
    extinction_loss_threshold: int = 5
    rival_dominance_threshold: int = 7
    commentary_interval: int = 5
    commentary_min_interval_s: int = 30

    model_config = SettingsConfigDict(
        env_file="secrets.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
