"""Central configuration. All values come from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./idp.db"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10
    max_pdf_pages: int = 20
    stale_job_minutes: int = 15  # Queued/Processing longer than this may be retried (lost task / dead worker)
    queue_mode: str = "celery"  # "celery" (Redis worker) | "inline" (tests / local debugging)
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"

    # Optional AI extractor (primary). Rule-based extractor is always the fallback.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    llm_timeout_s: float = 30.0

    # Quality thresholds (0-100 OCR confidence scale)
    ocr_min_confidence: float = 60.0
    field_min_confidence: float = 70.0
    amount_tolerance: str = "0.01"


@lru_cache
def get_settings() -> Settings:
    return Settings()
