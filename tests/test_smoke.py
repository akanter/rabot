import json
from pathlib import Path

import httpx

import rabot.cli as cli
from rabot.config import Config
from rabot.notifier import SignalNotifier
from rabot.ra_client import fetch
from rabot.state import load_state

FIXTURES = Path(__file__).parent / "fixtures"


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_full_cycle_available_sends_alert(tmp_path, monkeypatch):
    payload = json.loads((FIXTURES / "tickets_available.json").read_text())
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))

    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(
        cli, "fetch",
        lambda c, client=None: fetch(c, client=httpx.Client(transport=transport)))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda c: notifier)

    cli.run_check()

    assert len(notifier.messages) == 1
    assert "ra.co/events/1234567" in notifier.messages[0]
    assert load_state(state_path).last_available is True
