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

    # Upbit public market data (P7) - ticker/trade/orderbook/candles need no
    # API key at all.
    upbit_ws_url: str = "wss://api.upbit.com/websocket/v1"
    upbit_rest_base_url: str = "https://api.upbit.com"

    # Upbit authenticated endpoints (P15: order placement/cancel/status) -
    # see docs/UPBIT_NOTES.md. Same "empty means not configured, never
    # pretend" rule as KIS/Toss.
    upbit_access_key: str = ""
    upbit_secret_key: str = ""

    @property
    def upbit_configured(self) -> bool:
        return bool(self.upbit_access_key and self.upbit_secret_key)

    # Kakao Login + "send to me" notification (P12) - see docs/KAKAO_SETUP.md.
    # `kakao_client_secret` is intentionally not required for `kakao_configured`:
    # Kakao's client secret is an optional, separately-toggled setting for a
    # REST API key, unlike KIS/Toss where the secret is mandatory.
    kakao_client_id: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = ""
    kakao_auth_base_url: str = "https://kauth.kakao.com"
    kakao_api_base_url: str = "https://kapi.kakao.com"

    @property
    def kakao_configured(self) -> bool:
        return bool(self.kakao_client_id and self.kakao_redirect_uri)

    # Kakao's OAuth2 authorization_code grant needs a real user's browser
    # consent - there is no client_credentials equivalent to automate it, so
    # unlike KIS/Toss's app-only credentials, the real-connection integration
    # test (test_kakao_integration.py) additionally needs a refresh token
    # obtained once by hand through the real login flow. Solely for that
    # test; the running application never reads this - see docs/KAKAO_SETUP.md.
    kakao_test_refresh_token: str = ""

    # Secure approval UX (P13) - see docs/MASTER_SPEC.md sections C-E.
    # 120-300s window per the master spec; 180s is the midpoint default.
    approval_token_ttl_seconds: int = 180
    # PBKDF2-HMAC-SHA256 hash of the app PIN, as "<salt_hex>$<hash_hex>" (see
    # app/approval/pin.py's hash_pin()) - never the plaintext PIN. Empty
    # means "not configured", which fails approval closed (PinNotConfiguredError)
    # rather than silently skipping the re-check the master spec requires.
    app_pin_hash: str = ""
    # Base URL the approval link sent via Kakao points to, e.g.
    # "https://app.example.com" -> "https://app.example.com/approve/{token}".
    approval_base_url: str = "http://localhost:5173"

    @property
    def pin_configured(self) -> bool:
        return bool(self.app_pin_hash)


@lru_cache
def get_settings() -> Settings:
    return Settings()
