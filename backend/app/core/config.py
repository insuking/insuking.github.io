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

    # KIS (Korea Investment Securities) Open API - see docs/KIS_SETUP.md.
    # Left blank until the user provisions real credentials; every KIS
    # integration must treat an empty key as "not configured" and refuse to
    # pretend a connection succeeded (docs/MASTER_SPEC.md P3 acceptance).
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    kis_rest_base_url: str = "https://openapi.koreainvestment.com:9443"
    kis_ws_url: str = "wss://ops.koreainvestment.com:21000"

    @property
    def kis_configured(self) -> bool:
        return bool(self.kis_app_key and self.kis_app_secret)

    # Toss Securities Open API - see docs/TOSS_SETUP.md. Same "empty means
    # not configured, never pretend" rule as KIS above.
    toss_client_id: str = ""
    toss_client_secret: str = ""
    toss_rest_base_url: str = "https://openapi.tossinvest.com"

    @property
    def toss_configured(self) -> bool:
        return bool(self.toss_client_id and self.toss_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
