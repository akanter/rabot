import pytest
from rabot.config import load_config, Config

BASE_ENV = {
    "RABOT_EVENT_URL": "https://ra.co/events/1234567",
    "RABOT_SIGNAL_SENDER": "+15550000001",
    "RABOT_SIGNAL_RECIPIENT": "+15550000002",
}

def test_loads_required_and_defaults():
    cfg = load_config(BASE_ENV)
    assert cfg.event_url == "https://ra.co/events/1234567"
    assert cfg.signal_sender == "+15550000001"
    assert cfg.signal_recipient == "+15550000002"
    assert cfg.signal_group_id is None
    assert cfg.cooldown_seconds == 900
    assert cfg.failure_threshold == 5
    assert cfg.graphql_endpoint == "https://ra.co/graphql"
    assert cfg.signal_cli_path == "signal-cli"

def test_event_id_extracted_from_url():
    assert load_config(BASE_ENV).event_id == "1234567"

def test_missing_sender_raises():
    env = {"RABOT_EVENT_URL": "https://ra.co/events/1", "RABOT_SIGNAL_RECIPIENT": "+1"}
    with pytest.raises(ValueError, match="RABOT_SIGNAL_SENDER"):
        load_config(env)

def test_missing_recipient_and_group_raises():
    env = {"RABOT_SIGNAL_SENDER": "+1"}
    with pytest.raises(ValueError, match="RABOT_SIGNAL_RECIPIENT"):
        load_config(env)

def test_group_id_loads_and_recipient_optional():
    env = {"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_GROUP_ID": "GROUP=="}
    cfg = load_config(env)
    assert cfg.signal_group_id == "GROUP=="
    assert cfg.signal_recipient is None

def test_event_url_optional_at_load_time():
    # event_url may come from a CLI arg instead; load_config tolerates its absence.
    env = {"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_RECIPIENT": "+2"}
    assert load_config(env).event_url == ""

def test_state_path_defaults_to_xdg(monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "/xdg/state")
    env = {"RABOT_SIGNAL_SENDER": "+1", "RABOT_SIGNAL_RECIPIENT": "+2"}
    assert load_config(env).state_path == "/xdg/state/rabot/state.json"

def test_bad_event_url_raises_on_id_access():
    cfg = Config(event_url="https://ra.co/nope", signal_sender="+1",
                 signal_recipient="+2", state_path="/tmp/s.json")
    with pytest.raises(ValueError, match="event id"):
        _ = cfg.event_id

def test_overrides_from_env():
    env = {**BASE_ENV, "RABOT_COOLDOWN_SECONDS": "60", "RABOT_FAILURE_THRESHOLD": "3"}
    cfg = load_config(env)
    assert cfg.cooldown_seconds == 60 and cfg.failure_threshold == 3
