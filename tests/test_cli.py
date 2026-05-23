from typer.testing import CliRunner

from near_agent.cli import app


runner = CliRunner()


def test_init_creates_env_example_and_database(tmp_path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / ".env.example").exists()
    assert (tmp_path / "near-agent.sqlite").exists()


def test_check_passes_in_dry_run_mode(tmp_path):
    result = runner.invoke(app, ["check", "--db", str(tmp_path / "agent.sqlite")])

    assert result.exit_code == 0
    assert "config ok" in result.output


def test_status_shows_confirmation_count(tmp_path):
    result = runner.invoke(app, ["status", "--db", str(tmp_path / "agent.sqlite")])

    assert result.exit_code == 0
    assert "confirmations: 0" in result.output


def test_once_can_run_offline_without_live_secrets(tmp_path):
    result = runner.invoke(app, ["once", "--offline", "--db", str(tmp_path / "agent.sqlite")])

    assert result.exit_code == 0
    assert "no_candidate_provider" in result.output


def test_daemon_can_run_one_offline_cycle(tmp_path):
    result = runner.invoke(
        app,
        ["daemon", "--offline", "--cycles", "1", "--interval-seconds", "0", "--db", str(tmp_path / "agent.sqlite")],
    )

    assert result.exit_code == 0
    assert "cycle 1: no_candidate_provider" in result.output
