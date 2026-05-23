from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    hyperliquid_private_key: str | None = Field(default=None, alias="HYPERLIQUID_PRIVATE_KEY")
    hyperliquid_account_address: str | None = Field(default=None, alias="HYPERLIQUID_ACCOUNT_ADDRESS")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_required: bool = Field(default=False, alias="LLM_REQUIRED")
    venice_api_key: str | None = Field(default=None, alias="VENICE_API_KEY")
    venice_base_url: str = Field(default="https://api.venice.ai/api/v1", alias="VENICE_BASE_URL")
    venice_model: str = Field(default="llama-3.3-70b", alias="VENICE_MODEL")
    confirm_first_n_trades: int = Field(default=5, alias="CONFIRM_FIRST_N_TRADES")
    fixed_notional_usd: Decimal = Field(default=Decimal("10"), alias="FIXED_NOTIONAL_USD")
    max_leverage: Decimal = Field(default=Decimal("10"), alias="MAX_LEVERAGE")
    local_timezone: str = Field(default="America/New_York", alias="LOCAL_TIMEZONE")
    end_of_day_flatten_time: str = Field(default="23:30", alias="END_OF_DAY_FLATTEN_TIME")
    rootai_mcp_url: str = Field(default="https://mcp.rootai.wtf/mcp", alias="ROOTAI_MCP_URL")
    symbol: str = Field(default="NEAR-USDC", alias="SYMBOL")
    primary_timeframe: str = Field(default="1h", alias="PRIMARY_TIMEFRAME")
    confirm_timeframe: str = Field(default="4h", alias="CONFIRM_TIMEFRAME")
    ema_fast: int = Field(default=9, alias="EMA_FAST")
    ema_slow: int = Field(default=21, alias="EMA_SLOW")
    atr_period: int = Field(default=14, alias="ATR_PERIOD")
    volatility_target_pct: Decimal = Field(default=Decimal("2"), alias="VOLATILITY_TARGET_PCT")
    trailing_start_pct: Decimal = Field(default=Decimal("1"), alias="TRAILING_START_PCT")
    trailing_distance_pct: Decimal = Field(default=Decimal("0.5"), alias="TRAILING_DISTANCE_PCT")
    initial_stop_pct: Decimal = Field(default=Decimal("2"), alias="INITIAL_STOP_PCT")
    backtest_days: int = Field(default=90, alias="BACKTEST_DAYS")
    discord_webhook_url: str | None = Field(default=None, alias="DISCORD_WEBHOOK_URL")

    def validate_for_startup(self) -> None:
        if self.symbol != "NEAR-USDC":
            raise ValueError("SYMBOL must be NEAR-USDC")
        if self.fixed_notional_usd <= 0:
            raise ValueError("FIXED_NOTIONAL_USD must be greater than zero")
        if self.max_leverage > Decimal("10"):
            raise ValueError("MAX_LEVERAGE must be at or below 10")
        if self.max_leverage <= 0:
            raise ValueError("MAX_LEVERAGE must be greater than zero")
        if self.confirm_first_n_trades < 0:
            raise ValueError("CONFIRM_FIRST_N_TRADES must be zero or greater")
        supported_timeframes = {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "8h", "12h", "1d"}
        if self.primary_timeframe not in supported_timeframes:
            raise ValueError("PRIMARY_TIMEFRAME is unsupported")
        if self.confirm_timeframe not in supported_timeframes:
            raise ValueError("CONFIRM_TIMEFRAME is unsupported")
        if self.ema_fast <= 0 or self.ema_slow <= 0 or self.ema_fast >= self.ema_slow:
            raise ValueError("EMA_FAST must be greater than zero and less than EMA_SLOW")
        if self.atr_period <= 1:
            raise ValueError("ATR_PERIOD must be greater than one")
        if self.trailing_start_pct < 0 or self.trailing_distance_pct <= 0 or self.initial_stop_pct <= 0:
            raise ValueError("Trailing and initial stop percentages must be positive")
        if self.backtest_days <= 0:
            raise ValueError("BACKTEST_DAYS must be greater than zero")
        if self.llm_provider not in {"openai", "venice", "disabled"}:
            raise ValueError("LLM_PROVIDER must be openai, venice, or disabled")
        if self.llm_required:
            if self.llm_provider == "openai" and not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai and LLM_REQUIRED=true")
            if self.llm_provider == "venice" and not self.venice_api_key:
                raise ValueError("VENICE_API_KEY is required when LLM_PROVIDER=venice and LLM_REQUIRED=true")
        if self.live_trading:
            missing = []
            if not self.hyperliquid_private_key:
                missing.append("HYPERLIQUID_PRIVATE_KEY")
            if not self.hyperliquid_account_address:
                missing.append("HYPERLIQUID_ACCOUNT_ADDRESS")
            if missing:
                raise ValueError(f"Missing required live trading settings: {', '.join(missing)}")
