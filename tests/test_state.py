from rabot.state import State, load_state, save_state


def test_load_missing_returns_defaults(tmp_path):
    state = load_state(str(tmp_path / "nope.json"))
    assert state == State()
    assert state.last_available is False
    assert state.consecutive_failures == 0


def test_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(path, State(last_available=True, last_alert_ts=123.0,
                           consecutive_failures=2, blind_alerted=True))
    loaded = load_state(path)
    assert loaded == State(last_available=True, last_alert_ts=123.0,
                           consecutive_failures=2, blind_alerted=True)


def test_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert load_state(str(path)) == State()


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "state.json")
    save_state(path, State(last_available=True))
    assert load_state(path).last_available is True
