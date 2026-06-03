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
