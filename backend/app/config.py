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
    binance_exchange_id: str = "binance"
    trading_pairs: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"]
    )
    timeframes: list[str] = Field(default_factory=lambda: ["1w", "1d", "4h", "1h", "15m"])
    historical_months: int = 6
    polling_interval_seconds: int = 60
    auto_start_pipeline: bool = Field(default=True, validation_alias="AUTO_START_PIPELINE")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
