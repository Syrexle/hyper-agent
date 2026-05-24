from hyper_agent.sweep_env import apply_env_mapping


def test_apply_env_mapping_updates_existing_keys_and_adds_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EMA_FAST=9\nEMA_SLOW=21\n# comment\n")

    backup = apply_env_mapping(env, {"EMA_FAST": "12", "MIN_ATR_PCT": "0.75"})

    assert backup is not None
    assert backup.exists()
    assert backup.read_text() == "EMA_FAST=9\nEMA_SLOW=21\n# comment\n"
    assert "EMA_FAST=12" in env.read_text()
    assert "MIN_ATR_PCT=0.75" in env.read_text()


def test_apply_env_mapping_creates_env_when_missing(tmp_path):
    env = tmp_path / ".env"

    backup = apply_env_mapping(env, {"EMA_FAST": "12"})

    assert backup is None
    assert env.read_text() == "EMA_FAST=12\n"
