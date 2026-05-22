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
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_required: bool = Field(default=False, alias="LLM_REQUIRED")
    confirm_first_n_trades: int = Field(default=5, alias="CONFIRM_FIRST_N_TRADES")
    fixed_notional_usd: Decimal = Field(default=Decimal("10"), alias="FIXED_NOTIONAL_USD")
    max_leverage: Decimal = Field(default=Decimal("2"), alias="MAX_LEVERAGE")
    local_timezone: str = Field(default="America/New_York", alias="LOCAL_TIMEZONE")
    end_of_day_flatten_time: str = Field(default="23:30", alias="END_OF_DAY_FLATTEN_TIME")
    rootai_mcp_url: str = Field(default="https://mcp.rootai.wtf/mcp", alias="ROOTAI_MCP_URL")
    symbol: str = Field(default="NEAR-USDC", alias="SYMBOL")

    def validate_for_startup(self) -> None:
        if self.symbol != "NEAR-USDC":
            raise ValueError("SYMBOL must be NEAR-USDC")
        if self.fixed_notional_usd <= 0:
            raise ValueError("FIXED_NOTIONAL_USD must be greater than zero")
        if self.max_leverage > Decimal("2"):
            raise ValueError("MAX_LEVERAGE must be at or below 2")
        if self.max_leverage <= 0:
            raise ValueError("MAX_LEVERAGE must be greater than zero")
        if self.confirm_first_n_trades < 0:
            raise ValueError("CONFIRM_FIRST_N_TRADES must be zero or greater")
        if self.live_trading:
            missing = []
            if not self.hyperliquid_private_key:
                missing.append("HYPERLIQUID_PRIVATE_KEY")
            if not self.hyperliquid_account_address:
                missing.append("HYPERLIQUID_ACCOUNT_ADDRESS")
            if missing:
                raise ValueError(f"Missing required live trading settings: {', '.join(missing)}")
