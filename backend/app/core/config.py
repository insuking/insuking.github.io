from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment variables / .env.

    Trading is disabled by default per the project's absolute safety rule:
    LIVE_TRADING must be explicitly enabled and is never assumed.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Multi-Asset Pre-Breakout Radar"
    environment: str = "dev"

    database_url: str = "postgresql+asyncpg://radar:radar@localhost:5432/radar"
    redis_url: str = "redis://localhost:6379/0"

    live_trading: bool = False
    trading_mode: str = "PAPER_APPROVAL"
    live_auto: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
