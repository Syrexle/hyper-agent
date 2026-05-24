from decimal import Decimal

from pydantic import Field, computed_field
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
    venice_model: str = Field(default="deepseek-v4-flash", alias="VENICE_MODEL")
    venice_sweep_model: str = Field(default="qwen3-235b-a22b-thinking-2507", alias="VENICE_SWEEP_MODEL")
    confirm_first_n_trades: int = Field(default=5, alias="CONFIRM_FIRST_N_TRADES")
    fixed_notional_usd: Decimal = Field(default=Decimal("10"), alias="FIXED_NOTIONAL_USD")
    max_leverage: Decimal = Field(default=Decimal("10"), alias="MAX_LEVERAGE")
    local_timezone: str = Field(default="America/New_York", alias="LOCAL_TIMEZONE")
    end_of_day_flatten_time: str = Field(default="23:30", alias="END_OF_DAY_FLATTEN_TIME")
    rootai_mcp_url: str = Field(default="https://mcp.rootai.wtf/mcp", alias="ROOTAI_MCP_URL")
    symbol: str = Field(default="NEAR-USDC", alias="SYMBOL")
    symbols_raw: str = Field(
        default=(
            "BTC-USDC,ETH-USDC,SOL-USDC,XRP-USDC,DOGE-USDC,"
            "BNB-USDC,AVAX-USDC,SUI-USDC,LINK-USDC,HYPE-USDC,"
            "ARB-USDC,INJ-USDC,APT-USDC,TON-USDC,WIF-USDC,"
            "kPEPE-USDC,kBONK-USDC,TAO-USDC,ENA-USDC,JUP-USDC,"
            "TIA-USDC,OP-USDC,ADA-USDC,TRX-USDC,NEAR-USDC"
        ),
        alias="SYMBOLS",
    )

    @computed_field
    @property
    def symbols(self) -> list[str]:
        return [s.strip() for s in self.symbols_raw.split(",") if s.strip()]

    primary_timeframe: str = Field(default="1h", alias="PRIMARY_TIMEFRAME")
    confirm_timeframe: str = Field(default="4h", alias="CONFIRM_TIMEFRAME")
    ema_fast: int = Field(default=9, alias="EMA_FAST")
    ema_slow: int = Field(default=21, alias="EMA_SLOW")
    atr_period: int = Field(default=14, alias="ATR_PERIOD")
    volatility_target_pct: Decimal = Field(default=Decimal("2"), alias="VOLATILITY_TARGET_PCT")
    trailing_start_pct: Decimal = Field(default=Decimal("8"), alias="TRAILING_START_PCT")
    trailing_distance_pct: Decimal = Field(default=Decimal("0.5"), alias="TRAILING_DISTANCE_PCT")
    initial_stop_pct: Decimal = Field(default=Decimal("5"), alias="INITIAL_STOP_PCT")
    backtest_days: int = Field(default=90, alias="BACKTEST_DAYS")
    backtest_fee_bps: Decimal = Field(default=Decimal("5"), alias="BACKTEST_FEE_BPS")
    backtest_slippage_bps: Decimal = Field(default=Decimal("10"), alias="BACKTEST_SLIPPAGE_BPS")
    backtest_funding_bps: Decimal = Field(default=Decimal("2"), alias="BACKTEST_FUNDING_BPS")
    min_atr_pct: Decimal = Field(default=Decimal("0.75"), alias="MIN_ATR_PCT")
    min_ema_spread_pct: Decimal = Field(default=Decimal("0.35"), alias="MIN_EMA_SPREAD_PCT")
    max_extension_pct: Decimal = Field(default=Decimal("8"), alias="MAX_EXTENSION_PCT")
    discord_webhook_url: str | None = Field(default=None, alias="DISCORD_WEBHOOK_URL")
    rsi_period: int = Field(default=14, alias="RSI_PERIOD")
    rsi_overbought: Decimal = Field(default=Decimal("70"), alias="RSI_OVERBOUGHT")
    rsi_oversold: Decimal = Field(default=Decimal("30"), alias="RSI_OVERSOLD")
    funding_rate_threshold: Decimal = Field(default=Decimal("0.001"), alias="FUNDING_RATE_THRESHOLD")
    max_open_positions: int = Field(default=3, alias="MAX_OPEN_POSITIONS")
    max_total_notional_usd: Decimal = Field(default=Decimal("100"), alias="MAX_TOTAL_NOTIONAL_USD")

    def validate_for_startup(self) -> None:
        if not self.symbols:
            raise ValueError("SYMBOLS must contain at least one symbol")
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
        if self.backtest_fee_bps < 0:
            raise ValueError("BACKTEST_FEE_BPS must be zero or greater")
        if self.backtest_slippage_bps < 0:
            raise ValueError("BACKTEST_SLIPPAGE_BPS must be zero or greater")
        if self.backtest_funding_bps < 0:
            raise ValueError("BACKTEST_FUNDING_BPS must be zero or greater")
        if self.min_atr_pct < 0:
            raise ValueError("MIN_ATR_PCT must be zero or greater")
        if self.min_ema_spread_pct < 0:
            raise ValueError("MIN_EMA_SPREAD_PCT must be zero or greater")
        if self.max_extension_pct <= 0:
            raise ValueError("MAX_EXTENSION_PCT must be greater than zero")
        if self.llm_provider not in {"openai", "venice", "disabled"}:
            raise ValueError("LLM_PROVIDER must be openai, venice, or disabled")
        if self.llm_required:
            if self.llm_provider == "openai" and not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai and LLM_REQUIRED=true")
            if self.llm_provider == "venice" and not self.venice_api_key:
                raise ValueError("VENICE_API_KEY is required when LLM_PROVIDER=venice and LLM_REQUIRED=true")
        if self.rsi_period <= 1:
            raise ValueError("RSI_PERIOD must be greater than one")
        if not (0 < self.rsi_oversold < self.rsi_overbought < 100):
            raise ValueError("RSI_OVERSOLD must be less than RSI_OVERBOUGHT, both between 0 and 100")
        if self.funding_rate_threshold <= 0:
            raise ValueError("FUNDING_RATE_THRESHOLD must be greater than zero")
        if self.max_open_positions <= 0:
            raise ValueError("MAX_OPEN_POSITIONS must be greater than zero")
        if self.max_total_notional_usd <= 0:
            raise ValueError("MAX_TOTAL_NOTIONAL_USD must be greater than zero")
        if self.live_trading:
            missing = []
            if not self.hyperliquid_private_key:
                missing.append("HYPERLIQUID_PRIVATE_KEY")
            if not self.hyperliquid_account_address:
                missing.append("HYPERLIQUID_ACCOUNT_ADDRESS")
            if missing:
                raise ValueError(f"Missing required live trading settings: {', '.join(missing)}")
