import threading

import pytest

import rabot.cli as cli
from rabot.ra_client import FetchResult
from rabot.config import Config, EventWatch
from rabot.state import EventState, load_states, save_states


def cfg(state_path, events=None, **kw):
    if events is None:
        events = [EventWatch("https://ra.co/events/1234567", recipient="+2")]
    return Config(events=tuple(events), signal_sender="+1",
                  default_recipient="+2", state_path=state_path, **kw)


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


# ---- link ----

def test_link_command_invokes_linker(monkeypatch):
    calls = {}
    monkeypatch.setenv("RABOT_SIGNAL_CLI", "/store/signal-cli")
    monkeypatch.setattr(
        cli, "signal_link",
        lambda cli_path, device: calls.update(cli=cli_path, device=device) or 0)
    assert cli.main(["link", "rabot-cage"]) == 0
    assert calls == {"cli": "/store/signal-cli", "device": "rabot-cage"}


def test_link_command_defaults_device_to_hostname(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli, "signal_link",
                        lambda cli_path, device: calls.update(device=device) or 0)
    cli.main(["link"])
    assert calls["device"].startswith("rabot-")


# ---- check ----

def test_run_check_alerts_and_persists(tmp_path, monkeypatch):
    sp = str(tmp_path / "state.json")
    monkeypatch.setattr(cli, "load_config", lambda: cfg(sp))
    monkeypatch.setattr(cli, "fetch",
                        lambda eid, ep, client=None: FetchResult(ok=True, available=True,
                                                                 event_title="T", status_code=200))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda config, watch: notifier)

    cli.run_check()

    assert len(notifier.messages) == 1
    st = load_states(sp)["1234567"]
    assert st.last_available is True and st.alerts == 1 and st.last_ok is True


def test_run_check_no_alert_when_unavailable(tmp_path, monkeypatch):
    sp = str(tmp_path / "state.json")
    monkeypatch.setattr(cli, "load_config", lambda: cfg(sp))
    monkeypatch.setattr(cli, "fetch",
                        lambda eid, ep, client=None: FetchResult(ok=True, available=False,
                                                                 status_code=200))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda config, watch: notifier)

    cli.run_check()

    assert notifier.messages == []
    st = load_states(sp)["1234567"]
    assert st.last_available is False and st.alerts == 0


def test_event_urls_cli_override(tmp_path, monkeypatch):
    sp = str(tmp_path / "state.json")
    # config has a different event; CLI args should override it
    monkeypatch.setattr(cli, "load_config",
                        lambda: cfg(sp, events=[EventWatch("https://ra.co/events/111", recipient="+2")]))
    seen = []
    monkeypatch.setattr(cli, "fetch",
                        lambda eid, ep, client=None: seen.append(eid) or
                        FetchResult(ok=True, available=False, status_code=200))
    monkeypatch.setattr(cli, "build_notifier", lambda config, watch: FakeNotifier())

    cli.run_check(event_urls=["https://ra.co/events/9999999"])

    assert seen == ["9999999"]


def test_multi_event_per_event_targets(tmp_path, monkeypatch):
    sp = str(tmp_path / "state.json")
    events = [
        EventWatch("https://ra.co/events/111", group_id="GROUP=="),   # available → group
        EventWatch("https://ra.co/events/222", recipient="+15550000009"),  # unavailable → quiet
    ]
    monkeypatch.setattr(cli, "load_config", lambda: cfg(sp, events=events))
    monkeypatch.setattr(cli, "fetch",
                        lambda eid, ep, client=None: FetchResult(
                            ok=True, available=(eid == "111"), event_title=f"E{eid}", status_code=200))
    sent = []

    def factory(config, watch):
        class N:
            def send(self, m):
                sent.append((watch.event_id, watch.recipient, watch.group_id, m))
        return N()

    monkeypatch.setattr(cli, "build_notifier", factory)

    cli.run_check()

    # only the available event (111) alerted, and it went to its group target
    assert len(sent) == 1
    eid, recipient, group, msg = sent[0]
    assert eid == "111" and group == "GROUP==" and recipient is None
    states = load_states(sp)
    assert states["111"].last_available is True
    assert states["222"].last_available is False


def test_no_events_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: cfg(str(tmp_path / "s.json"), events=[]))
    with pytest.raises(SystemExit):
        cli.run_check()


def test_send_failure_preserves_observability_and_retries(tmp_path, monkeypatch):
    sp = str(tmp_path / "state.json")
    # event already at threshold-1 so this failed fetch triggers a blind alert
    save_states(sp, {"1234567": EventState(consecutive_failures=4, failures=4)})
    monkeypatch.setattr(cli, "load_config", lambda: cfg(sp, failure_threshold=5))
    monkeypatch.setattr(cli, "fetch",
                        lambda eid, ep, client=None: FetchResult(ok=False, error="boom", status_code=429))

    class FailingNotifier:
        def send(self, message):
            raise RuntimeError("signal-cli down")

    monkeypatch.setattr(cli, "build_notifier", lambda config, watch: FailingNotifier())

    cli.run_check()  # must NOT raise

    st = load_states(sp)["1234567"]
    assert st.consecutive_failures == 5      # progressed despite send failure
    assert st.blind_alerted is False          # not recorded as delivered → retries
    assert st.last_http_status == 429         # observability preserved through rollback
    assert st.alerts == 0


# ---- status ----

# ---- daemon ----

def test_daemon_loops_then_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: cfg(str(tmp_path / "s.json"), poll_seconds=0))
    stop = threading.Event()
    calls = []

    def fake_cycle(config, watches):
        calls.append(1)
        if len(calls) >= 3:
            stop.set()

    monkeypatch.setattr(cli, "_check_cycle", fake_cycle)
    assert cli.run_daemon(stop_event=stop) == 0
    assert len(calls) == 3


def test_daemon_continues_after_cycle_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: cfg(str(tmp_path / "s.json"), poll_seconds=0))
    stop = threading.Event()
    calls = []

    def fake_cycle(config, watches):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")        # must not kill the loop
        if len(calls) >= 3:
            stop.set()

    monkeypatch.setattr(cli, "_check_cycle", fake_cycle)
    cli.run_daemon(stop_event=stop)           # must not raise
    assert len(calls) >= 3


def test_daemon_no_events_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: cfg(str(tmp_path / "s.json"), events=[]))
    with pytest.raises(SystemExit):
        cli.run_daemon(stop_event=threading.Event())


def test_status_prints_per_event_summary_without_sender(tmp_path, monkeypatch, capsys):
    sp = str(tmp_path / "state.json")
    save_states(sp, {"1234567": EventState(last_available=False, last_ok=True,
                                           last_http_status=200, checks=42)})
    # status only needs the state path — no RABOT_SIGNAL_SENDER / full config
    monkeypatch.setenv("RABOT_STATE_PATH", sp)
    monkeypatch.delenv("RABOT_CONFIG", raising=False)
    monkeypatch.delenv("RABOT_SIGNAL_SENDER", raising=False)
    assert cli.run_status() == 0
    out = capsys.readouterr().out
    assert "1234567" in out and "available=False" in out and "checks=42" in out
