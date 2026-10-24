"""Typed contracts for persistent spot execution. Monetary fields are decimals."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    product: Literal['XRP-USDC'] = 'XRP-USDC'
    fee_rate: Decimal = Field(Decimal('.006'), ge=0, le=Decimal('.05'))
    slippage: Decimal = Field(Decimal('.001'), ge=0, le=Decimal('.02'))
    uncertainty_buffer: Decimal = Field(Decimal('.005'), ge=0, le=Decimal('.5'))
    min_net_return: Decimal = Field(Decimal('.005'), ge=0, le=Decimal('.5'))
    probability_threshold: Decimal = Field(Decimal('.6'), ge=Decimal('.5'), le=1)
    max_position_usdc: Decimal = Field(Decimal('25'), gt=0, le=10000)
    max_exposure_fraction: Decimal = Field(Decimal('.1'), gt=0, le=Decimal('.25'))
    risk_per_trade_fraction: Decimal = Field(Decimal('.005'), gt=0, le=Decimal('.02'))
    max_daily_loss: Decimal = Field(Decimal('25'), gt=0, le=10000)
    reset_timezone: str = 'UTC'
    max_drawdown: Decimal = Field(Decimal('.1'), gt=0, le=Decimal('.5'))
    max_positions: Literal[1] = 1
    max_trades_per_day: int = Field(5, ge=1, le=50)
    cooldown_seconds: int = Field(3600, ge=0, le=86400)
    max_spread: Decimal = Field(Decimal('.003'), gt=0, le=Decimal('.02'))
    max_quote_age_seconds: int = Field(120, ge=1, le=300)
    stop_loss: Decimal = Field(Decimal('.03'), gt=0, le=Decimal('.5'))
    take_profit: Decimal = Field(Decimal('.06'), gt=0, le=1)
    max_holding_seconds: int = Field(86400, ge=60, le=2592000)
    emergency_cancel_entries: bool = True
    emergency_flatten: bool = False

    @field_validator('reset_timezone')
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError('Unknown daily-reset timezone.') from None
        return value


class PredictionContract(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    model_version: str | None = None
    product: str = 'XRP-USDC'
    candle_interval_seconds: int = 3600
    horizon_seconds: int = 3600
    input_timestamp: datetime | None = None
    prediction_timestamp: datetime
    output_kind: Literal['return', 'direction_probability', 'unavailable']
    predicted_return: Decimal | None = None
    predicted_price: Decimal | None = None
    probability_up: Decimal | None = None
    probability_calibrated: bool = False
    uncertainty: Decimal | None = None
    validated_for_orders: bool = False
    data_quality: Literal['valid', 'invalid', 'stale', 'missing']
    reason_codes: list[str] = []


class ConfigureAgent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['paper', 'live'] = 'paper'
    settings: StrategyConfig = Field(default_factory=StrategyConfig)


class AgentCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['start', 'pause', 'resume', 'cancel_entries', 'emergency_stop', 'close_position']
    request_id: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
