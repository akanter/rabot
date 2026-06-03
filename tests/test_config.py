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
    assert cfg.cooldown_seconds == 900
    assert cfg.failure_threshold == 5
    assert cfg.graphql_endpoint == "https://ra.co/graphql"
    assert cfg.signal_cli_path == "signal-cli"

def test_event_id_extracted_from_url():
    assert load_config(BASE_ENV).event_id == "1234567"

def test_missing_required_raises():
    with pytest.raises(ValueError, match="RABOT_EVENT_URL"):
        load_config({})

def test_bad_event_url_raises_on_id_access():
    cfg = Config(event_url="https://ra.co/nope", signal_sender="+1",
                 signal_recipient="+2", state_path="/tmp/s.json")
    with pytest.raises(ValueError, match="event id"):
        _ = cfg.event_id

def test_overrides_from_env():
    env = {**BASE_ENV, "RABOT_COOLDOWN_SECONDS": "60", "RABOT_FAILURE_THRESHOLD": "3"}
    cfg = load_config(env)
    assert cfg.cooldown_seconds == 60 and cfg.failure_threshold == 3
