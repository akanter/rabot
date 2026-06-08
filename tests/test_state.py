from rabot.state import EventState, load_states, save_states


def test_load_missing_returns_empty(tmp_path):
    assert load_states(str(tmp_path / "nope.json")) == {}


def test_round_trip_per_event(tmp_path):
    path = str(tmp_path / "state.json")
    states = {
        "111": EventState(last_available=True, last_alert_ts=123.0,
                          consecutive_failures=2, blind_alerted=True,
                          last_checked="2026-06-08T00:00:00+00:00", last_ok=True,
                          last_http_status=200, checks=10, failures=1, alerts=1),
        "222": EventState(last_available=False, last_ok=False,
                          last_http_status=429, last_error="HTTP 429"),
    }
    save_states(path, states)
    assert load_states(path) == states


def test_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert load_states(str(path)) == {}


def test_old_flat_format_loads_as_empty(tmp_path):
    # pre-multi-event single-event file (no "events" key) → start fresh, no crash
    path = tmp_path / "state.json"
    path.write_text('{"last_available": false, "consecutive_failures": 0}')
    assert load_states(str(path)) == {}


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "state.json")
    save_states(path, {"111": EventState(last_available=True)})
    assert load_states(path)["111"].last_available is True
