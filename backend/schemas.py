from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_trades_per_day: int = Field(5, ge=1, le=50)
    sizing_mode: Literal["automatic", "manual"] = "automatic"
    manual_size_usdc: Decimal = Field(Decimal("10"), gt=0, le=10000, decimal_places=8)
    max_position_usdc: Decimal = Field(Decimal("25"), gt=0, le=10000, decimal_places=8)
    max_allocation: Decimal = Field(Decimal("0.10"), gt=0, le=Decimal("0.25"), decimal_places=8)
    max_daily_loss_usdc: Decimal = Field(Decimal("25"), gt=0, le=10000, decimal_places=8)
    buy_threshold: Decimal = Field(Decimal("0.02"), ge=Decimal("0.001"), le=Decimal("0.5"), decimal_places=8)
    sell_threshold: Decimal = Field(Decimal("0.02"), ge=Decimal("0.001"), le=Decimal("0.5"), decimal_places=8)
    fee_rate: Decimal = Field(Decimal("0.006"), ge=0, le=Decimal("0.05"), decimal_places=8)
    slippage_rate: Decimal = Field(Decimal("0.001"), ge=0, le=Decimal("0.05"), decimal_places=8)
    emergency_stop: bool = False


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
