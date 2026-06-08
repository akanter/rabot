import json
from pathlib import Path

import httpx

import rabot.cli as cli
from rabot.config import Config, EventWatch
from rabot.ra_client import fetch
from rabot.state import load_states

FIXTURES = Path(__file__).parent / "fixtures"


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_full_cycle_available_sends_alert(tmp_path, monkeypatch):
    payload = json.loads((FIXTURES / "legacy_available.json").read_text())
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))

    state_path = str(tmp_path / "state.json")
    cfg = Config(events=(EventWatch("https://ra.co/events/1234567", recipient="+2"),),
                 signal_sender="+1", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    # drive the real fetch/parse through a mocked transport (no network)
    monkeypatch.setattr(
        cli, "fetch",
        lambda eid, ep, client=None: fetch(eid, ep, client=httpx.Client(transport=transport)))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda config, watch: notifier)

    cli.run_check()

    assert len(notifier.messages) == 1
    assert "ra.co/events/1234567" in notifier.messages[0]
    st = load_states(state_path)["1234567"]
    assert st.last_available is True and st.alerts == 1
