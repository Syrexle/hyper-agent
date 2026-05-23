from hyper_agent.models import DecisionAction, Side
from hyper_agent.notifications import DiscordNotifier


class FakeHttpClient:
    def __init__(self):
        self.posts = []

    def post(self, url, *, json, timeout):
        self.posts.append((url, json, timeout))
        return FakeResponse()


class FakeResponse:
    def raise_for_status(self):
        return None


def test_discord_notifier_posts_near_signal_embed():
    http = FakeHttpClient()
    notifier = DiscordNotifier("https://discord.example/webhook", http_client=http)

    notifier.signal(DecisionAction.LONG, symbol="NEAR-USDC", price=2.25)

    assert http.posts[0][0] == "https://discord.example/webhook"
    embed = http.posts[0][1]["embeds"][0]
    assert "NEAR-USDC" in embed["description"]
    assert "LONG" in embed["title"]


def test_discord_notifier_posts_entry_embed():
    http = FakeHttpClient()
    notifier = DiscordNotifier("https://discord.example/webhook", http_client=http)

    notifier.entry(Side.SHORT, symbol="NEAR-USDC", size_base=4.5, price=2.2, leverage=2)

    embed = http.posts[0][1]["embeds"][0]
    assert "Position Opened" in embed["title"]
    assert embed["fields"][2]["value"] == "2x"
