from datetime import datetime, timezone

from hyper_agent.models import DecisionAction, Side


class DiscordNotifier:
    def __init__(self, webhook_url: str, *, http_client=None):
        self.webhook_url = webhook_url
        if http_client is None:
            import httpx

            http_client = httpx.Client()
        self.http_client = http_client

    def send(self, title: str, description: str, *, color: int = 0x00FF00, fields: list[dict] | None = None) -> None:
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Hyper Agent"},
        }
        if fields:
            embed["fields"] = fields
        response = self.http_client.post(self.webhook_url, json={"embeds": [embed]}, timeout=10)
        response.raise_for_status()

    def signal(self, action: DecisionAction, *, symbol: str, price: float) -> None:
        color = 0x00FF00 if action == DecisionAction.LONG else 0xFF0000
        self.send(
            f"{action.value.upper()} Signal",
            f"{symbol} at ${price:,.4f}",
            color=color,
        )

    def entry(self, side: Side, *, symbol: str, size_base: float, price: float, leverage) -> None:
        notional = size_base * price
        color = 0x00FF00 if side == Side.LONG else 0xFF0000
        self.send(
            "Position Opened",
            f"{side.value.upper()} {size_base:.4f} {symbol}",
            color=color,
            fields=[
                {"name": "Entry", "value": f"${price:,.4f}", "inline": True},
                {"name": "Size", "value": f"${notional:,.2f}", "inline": True},
                {"name": "Leverage", "value": f"{leverage}x", "inline": True},
            ],
        )

    def exit(self, *, symbol: str, exit_price: float, reason: str, pnl_pct: float) -> None:
        color = 0x00FF00 if pnl_pct > 0 else 0xFF0000
        self.send(
            "Position Closed",
            f"{symbol}: {reason}; PnL {pnl_pct:+.2f}%",
            color=color,
            fields=[{"name": "Exit", "value": f"${exit_price:,.4f}", "inline": True}],
        )

    def error(self, message: str) -> None:
        self.send("Bot Error", message, color=0xFF0000)
