import json

import pytest
from rabot.config import load_config, Config, EventWatch

BASE_ENV = {
    "RABOT_EVENT_URL": "https://ra.co/events/1234567",
    "RABOT_SIGNAL_SENDER": "+15550000001",
    "RABOT_SIGNAL_RECIPIENT": "+15550000002",
}


def test_single_event_from_env():
    cfg = load_config(BASE_ENV)
    assert len(cfg.events) == 1
    ev = cfg.events[0]
    assert ev.url == "https://ra.co/events/1234567"
    assert ev.event_id == "1234567"
    assert ev.recipient == "+15550000002"
    assert ev.group_id is None
    assert cfg.signal_sender == "+15550000001"
    assert cfg.cooldown_seconds == 900 and cfg.failure_threshold == 5


def test_multi_event_json_with_per_event_targets():
    env = {
        "RABOT_SIGNAL_SENDER": "+1",
        "RABOT_SIGNAL_GROUP_ID": "GLOBALGROUP=",   # global fallback
        "RABOT_EVENTS": json.dumps([
            {"url": "https://ra.co/events/111", "group": "HOUGHTON="},
            {"url": "https://ra.co/events/222", "recipient": "+15550000009"},
            {"url": "https://ra.co/events/333"},  # falls back to global group
        ]),
    }
    cfg = load_config(env)
    assert [e.event_id for e in cfg.events] == ["111", "222", "333"]
    assert cfg.events[0].group_id == "HOUGHTON=" and cfg.events[0].recipient is None
    assert cfg.events[1].recipient == "+15550000009"
    assert cfg.events[2].group_id == "GLOBALGROUP="   # fallback applied


def test_event_without_target_raises():
    env = {"RABOT_SIGNAL_SENDER": "+1",
           "RABOT_EVENTS": json.dumps([{"url": "https://ra.co/events/111"}])}
    with pytest.raises(ValueError, match="no target"):
        load_config(env)


def test_missing_sender_raises():
    with pytest.raises(ValueError, match="RABOT_SIGNAL_SENDER"):
        load_config({"RABOT_EVENT_URL": "https://ra.co/events/1",
                     "RABOT_SIGNAL_RECIPIENT": "+1"})


def test_no_events_is_allowed_cli_supplies():
    # neither RABOT_EVENTS nor RABOT_EVENT_URL → empty; CLI may supply a URL
    cfg = load_config({"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_RECIPIENT": "+2"})
    assert cfg.events == ()
    # default target is available for ad-hoc CLI urls
    assert cfg.watch_for_url("https://ra.co/events/9").recipient == "+2"


def test_watch_for_url_without_default_target_raises():
    cfg = load_config({"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_RECIPIENT": "+2"})
    cfg = Config(events=(), signal_sender="+1")  # no default target
    with pytest.raises(ValueError, match="no target"):
        cfg.watch_for_url("https://ra.co/events/9")


def test_bad_event_url_raises_on_id_access():
    with pytest.raises(ValueError, match="event id"):
        _ = EventWatch(url="https://ra.co/nope", recipient="+2").event_id


def test_state_path_defaults_to_xdg(monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "/xdg/state")
    cfg = load_config({"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_RECIPIENT": "+2"})
    assert cfg.state_path == "/xdg/state/rabot/state.json"


def test_overrides_from_env():
    env = {**BASE_ENV, "RABOT_COOLDOWN_SECONDS": "60", "RABOT_FAILURE_THRESHOLD": "3"}
    cfg = load_config(env)
    assert cfg.cooldown_seconds == 60 and cfg.failure_threshold == 3
