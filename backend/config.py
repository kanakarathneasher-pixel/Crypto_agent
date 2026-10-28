"""Validated local configuration. Live execution is separately gated and off by default."""
from decimal import Decimal
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./crypto_agent.db"
    trading_mode: Literal["paper"] = "paper"
    trading_enabled: bool = False
    trading_pair: Literal["XRP-USDC"] = "XRP-USDC"
    max_trades_per_day: int = Field(5, ge=1, le=50)
    max_position_usdc: Decimal = Field(Decimal("25"), gt=0, le=10000)
    initial_paper_balance_usdc: Decimal = Field(Decimal("1000"), gt=0, le=1000000)
    estimated_fee_rate: Decimal = Field(Decimal("0.006"), ge=0, le=Decimal("0.05"))
    estimated_slippage_rate: Decimal = Field(Decimal("0.001"), ge=0, le=Decimal("0.05"))
    max_daily_loss_usdc: Decimal = Field(Decimal("25"), gt=0, le=10000)
    model_path: str = "models/approved.json"
    live_execution_enabled: bool = False
    live_owner_user_id: int | None = None
    coinbase_key_name: str = ''
    coinbase_private_key: str = ''
    # Separate credentials for the owner's read-only account test; never used by execution.
    coinbase_readonly_owner_user_id: int | None = None
    coinbase_readonly_key_name: str = ''
    coinbase_readonly_private_key: str = ''
    openai_api_key: str = ""
    openai_model: str = ""
    worker_enabled: bool = True
    worker_poll_seconds: int = Field(2, ge=2, le=3600)
    cookie_secure: bool = False  # True behind HTTPS outside local development.
    allowed_origin: str = "http://localhost:3000"
    google_client_id: str = ''


config = Config()
