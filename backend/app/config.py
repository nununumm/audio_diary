"""Application configuration, loaded from environment variables / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Security ---
    secret_key: str = Field("dev-insecure-change-me", alias="DIARY_SECRET_KEY")
    password: str = Field("diary", alias="DIARY_PASSWORD")

    # --- Storage ---
    data_dir: Path = Field(Path("./data"), alias="DIARY_DATA_DIR")

    # --- Transcription ---
    # "gemini" | "google_stt"
    transcriber: str = Field("gemini", alias="DIARY_TRANSCRIBER")
    stt_language: str = Field("ja-JP", alias="DIARY_STT_LANGUAGE")

    # --- Gemini ---
    gemini_api_key: str | None = Field(None, alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.5-flash", alias="GEMINI_MODEL")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "diary.db"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
