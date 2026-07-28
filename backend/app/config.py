from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Agents Trading API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/agents_trading",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")

    # Binance connection
    binance_exchange_id: str = "binance"
    binance_api_key: str = Field(default="", validation_alias="BINANCE_API_KEY")
    binance_api_secret: str = Field(default="", validation_alias="BINANCE_API_SECRET")
    binance_testnet: bool = Field(default=False, validation_alias="BINANCE_TESTNET")

    # Binance base URLs — override via .env for different regions
    binance_spot_url: str = Field(
        default="https://www.binance.bh", validation_alias="BINANCE_SPOT_URL"
    )
    binance_fapi_url: str = Field(
        default="https://www.binance.bh", validation_alias="BINANCE_FAPI_URL"
    )
    binance_fallback_url: str = Field(
        default="https://data-api.binance.vision", validation_alias="BINANCE_FALLBACK_URL"
    )

    # Trading config
    trading_pairs: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
    )
    timeframes: list[str] = Field(default_factory=lambda: ["1w", "1d", "4h", "1h", "15m"])
    historical_months: int = 6
    polling_interval_seconds: int = 60
    auto_start_pipeline: bool = Field(default=True, validation_alias="AUTO_START_PIPELINE")

    # Futures settings
    default_leverage: int = Field(default=5, validation_alias="DEFAULT_LEVERAGE")
    max_leverage: int = Field(default=20, validation_alias="MAX_LEVERAGE")
    position_size_percent: float = Field(default=2.0, validation_alias="POSITION_SIZE_PERCENT")
    max_open_positions: int = Field(default=3, validation_alias="MAX_OPEN_POSITIONS")

    # PLAN_v2 P0.2 — destructive DB reset endpoint gated by this flag
    allow_db_reset: bool = Field(default=False, validation_alias="ALLOW_DB_RESET")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.

    Kunci Binance di-overlay dari encrypted store (DPAPI, Windows) bila ada,
    menggantikan nilai plaintext .env. Di non-Windows / tanpa store -> pakai .env.
    """

    s = Settings()
    try:
        from app.services.secret_store import load_binance_secrets
        sec = load_binance_secrets()
        if sec:
            s.binance_api_key, s.binance_api_secret = sec
    except Exception:
        pass
    return s
