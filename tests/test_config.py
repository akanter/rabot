import json

import pytest
from rabot.config import load_config, Config, EventWatch

BASE_ENV = {
    "RABOT_EVENTS": "https://ra.co/events/1234567",
    "RABOT_SIGNAL_SENDER": "+15550000001",
    "RABOT_SIGNAL_RECIPIENT": "+15550000002",
}


def test_url_list_uses_default_target():
    env = {**BASE_ENV, "RABOT_EVENTS": "https://ra.co/events/111 https://ra.co/events/222"}
    cfg = load_config(env)
    assert [e.event_id for e in cfg.events] == ["111", "222"]
    # both fall back to the default recipient
    assert all(e.recipient == "+15550000002" and e.group_id is None for e in cfg.events)


def test_url_list_accepts_commas():
    env = {**BASE_ENV, "RABOT_EVENTS": "https://ra.co/events/111, https://ra.co/events/222"}
    assert [e.event_id for e in load_config(env).events] == ["111", "222"]


def test_json_form_with_per_event_targets():
    env = {
        "RABOT_SIGNAL_SENDER": "+1",
        "RABOT_SIGNAL_GROUP_ID": "GLOBALGROUP=",   # default target
        "RABOT_EVENTS": json.dumps([
            {"url": "https://ra.co/events/111", "group": "HOUGHTON="},
            {"url": "https://ra.co/events/222", "recipient": "+15550000009"},
            {"url": "https://ra.co/events/333"},  # falls back to default group
        ]),
    }
    cfg = load_config(env)
    assert [e.event_id for e in cfg.events] == ["111", "222", "333"]
    assert cfg.events[0].group_id == "HOUGHTON=" and cfg.events[0].recipient is None
    assert cfg.events[1].recipient == "+15550000009"
    assert cfg.events[2].group_id == "GLOBALGROUP="   # default applied


def test_event_without_target_raises():
    env = {"RABOT_SIGNAL_SENDER": "+1", "RABOT_EVENTS": "https://ra.co/events/111"}
    with pytest.raises(ValueError, match="no target"):
        load_config(env)


def test_sender_is_optional():
    # no RABOT_SIGNAL_SENDER → signal_sender None (single account auto-selected)
    cfg = load_config({"RABOT_EVENTS": "https://ra.co/events/1", "RABOT_SIGNAL_RECIPIENT": "+1"})
    assert cfg.signal_sender is None
    assert cfg.events[0].event_id == "1"


def test_no_events_is_allowed_cli_supplies():
    # neither RABOT_EVENTS set → empty; the CLI may supply URLs
    cfg = load_config({"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_RECIPIENT": "+2"})
    assert cfg.events == ()
    assert cfg.watch_for_url("https://ra.co/events/9").recipient == "+2"


def test_watch_for_url_without_default_target_raises():
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


# ---- TOML config file ----

def test_toml_config_loads_events_and_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'signal_sender = "+1"\n'
        'signal_group_id = "DEFGROUP="\n'
        'cooldown_seconds = 120\n'
        '[[events]]\n'
        'url = "https://ra.co/events/111"\n'
        '[[events]]\n'
        'url = "https://ra.co/events/222"\n'
        'recipient = "+15550000009"\n'
    )
    cfg = load_config({"RABOT_CONFIG": str(p)})
    assert cfg.signal_sender == "+1" and cfg.cooldown_seconds == 120
    assert [e.event_id for e in cfg.events] == ["111", "222"]
    assert cfg.events[0].group_id == "DEFGROUP=" and cfg.events[0].recipient is None  # default
    assert cfg.events[1].recipient == "+15550000009"                                  # override


def test_toml_config_takes_precedence_over_env(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('signal_sender = "+toml"\nsignal_recipient = "+2"\n'
                 '[[events]]\nurl = "https://ra.co/events/111"\n')
    # env also has values, but RABOT_CONFIG wins
    cfg = load_config({"RABOT_CONFIG": str(p), **BASE_ENV})
    assert cfg.signal_sender == "+toml"
    assert [e.event_id for e in cfg.events] == ["111"]


def test_toml_sender_optional(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('signal_recipient = "+1"\n[[events]]\nurl = "https://ra.co/events/111"\n')
    cfg = load_config({"RABOT_CONFIG": str(p)})
    assert cfg.signal_sender is None and cfg.events[0].event_id == "111"


def test_rabot_config_missing_file_raises():
    with pytest.raises(ValueError, match="not found"):
        load_config({"RABOT_CONFIG": "/no/such/config.toml", **BASE_ENV})
