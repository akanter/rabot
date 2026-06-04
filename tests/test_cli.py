import time

import rabot.cli as cli
from rabot.ra_client import FetchResult
from rabot.config import Config
from rabot.state import State, load_state


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_link_command_invokes_linker(monkeypatch):
    calls = {}
    monkeypatch.setenv("RABOT_SIGNAL_CLI", "/store/signal-cli")
    monkeypatch.setattr(
        cli, "signal_link",
        lambda cli_path, device: calls.update(cli=cli_path, device=device) or 0)

    rc = cli.main(["link", "rabot-cage"])

    assert rc == 0
    assert calls == {"cli": "/store/signal-cli", "device": "rabot-cage"}


def test_link_command_defaults_device_to_hostname(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli, "signal_link",
                        lambda cli_path, device: calls.update(device=device) or 0)
    cli.main(["link"])
    assert calls["device"].startswith("rabot-")


def test_run_check_alerts_and_persists(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch",
                        lambda c, client=None: FetchResult(ok=True, available=True, event_title="Test Event"))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda c: notifier)

    cli.run_check()

    assert len(notifier.messages) == 1
    assert load_state(state_path).last_available is True


def test_run_check_no_alert_when_unavailable(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch",
                        lambda c, client=None: FetchResult(ok=True, available=False, event_title="Test Event"))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda c: notifier)

    cli.run_check()

    assert notifier.messages == []
    assert load_state(state_path).last_available is False


def test_event_url_cli_arg_overrides_config(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="", signal_sender="+1", signal_recipient="+2",
                 state_path=state_path)  # no event in config
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    seen = {}

    def fake_fetch(c, client=None):
        seen["event_url"] = c.event_url
        return FetchResult(ok=True, available=False, event_title=None)

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli, "build_notifier", lambda c: FakeNotifier())

    cli.run_check(event_url="https://ra.co/events/9999999")

    assert seen["event_url"] == "https://ra.co/events/9999999"


def test_no_event_url_anywhere_exits(tmp_path, monkeypatch):
    import pytest
    cfg = Config(event_url="", signal_sender="+1", signal_recipient="+2",
                 state_path=str(tmp_path / "s.json"))
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    with pytest.raises(SystemExit):
        cli.run_check()


def test_send_failure_persists_failure_counter_and_retries(tmp_path, monkeypatch):
    import rabot.cli as cli
    from rabot.ra_client import FetchResult
    from rabot.config import Config
    from rabot.state import State, save_state, load_state

    state_path = str(tmp_path / "state.json")
    # Start already at threshold-1 so this failed fetch should trigger a blind alert
    save_state(state_path, State(consecutive_failures=4))
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path, failure_threshold=5)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch",
                        lambda c, client=None: FetchResult(ok=False, error="boom"))

    class FailingNotifier:
        def send(self, message):
            raise RuntimeError("signal-cli down")

    monkeypatch.setattr(cli, "build_notifier", lambda c: FailingNotifier())

    cli.run_check()  # must NOT raise

    persisted = load_state(state_path)
    assert persisted.consecutive_failures == 5      # counter progressed despite send failure
    assert persisted.blind_alerted is False          # alert not recorded as delivered -> retries
