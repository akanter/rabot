from rabot.evaluator import evaluate, Action
from rabot.ra_client import FetchResult
from rabot.state import EventState

URL = "https://ra.co/events/1234567"
NOW_ISO = "2026-06-08T00:00:00+00:00"
KW = dict(now_iso=NOW_ISO, cooldown_seconds=900, failure_threshold=3, event_url=URL)


def ok(available):
    return FetchResult(ok=True, available=available, event_title="Test Event", status_code=200)


def fail(status=None):
    return FetchResult(ok=False, error="boom", status_code=status)


def test_transition_unavailable_to_available_alerts():
    decision, new = evaluate(ok(True), EventState(last_available=False), now=1000.0, **KW)
    assert decision.action is Action.ALERT_AVAILABLE
    assert "ra.co/events/1234567" in decision.message
    assert new.last_available is True and new.last_alert_ts == 1000.0


def test_stays_quiet_while_available():
    decision, new = evaluate(ok(True), EventState(last_available=True, last_alert_ts=500.0),
                             now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.last_available is True


def test_cooldown_suppresses_reflicker():
    state = EventState(last_available=False, last_alert_ts=900.0)
    decision, new = evaluate(ok(True), state, now=1000.0, **KW)  # 100s < 900s cooldown
    assert decision.action is Action.NONE
    assert new.last_available is True
    assert new.last_alert_ts == 900.0  # unchanged


def test_rearm_after_cooldown_elapsed():
    state = EventState(last_available=False, last_alert_ts=10.0)
    decision, new = evaluate(ok(True), state, now=1000.0, **KW)  # 990s > 900s
    assert decision.action is Action.ALERT_AVAILABLE
    assert new.last_alert_ts == 1000.0


def test_available_to_unavailable_resets_flag_quietly():
    decision, new = evaluate(ok(False), EventState(last_available=True), now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.last_available is False


def test_failure_does_not_count_as_availability():
    decision, new = evaluate(fail(), EventState(last_available=False), now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.consecutive_failures == 1
    assert new.last_available is False


def test_blind_alert_fires_once_at_threshold():
    state = EventState(consecutive_failures=2)  # threshold is 3
    decision, new = evaluate(fail(), state, now=1000.0, **KW)
    assert decision.action is Action.ALERT_BLIND
    assert new.consecutive_failures == 3 and new.blind_alerted is True


def test_blind_alert_does_not_repeat():
    state = EventState(consecutive_failures=5, blind_alerted=True)
    decision, new = evaluate(fail(), state, now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.consecutive_failures == 6


def test_success_resets_failure_counter_and_blind_flag():
    state = EventState(consecutive_failures=5, blind_alerted=True, last_available=False)
    decision, new = evaluate(ok(False), state, now=1000.0, **KW)
    assert new.consecutive_failures == 0 and new.blind_alerted is False


def test_stamps_observability_each_cycle():
    decision, new = evaluate(ok(False), EventState(checks=4), now=1000.0, **KW)
    assert new.last_checked == NOW_ISO
    assert new.last_ok is True
    assert new.last_http_status == 200
    assert new.last_error is None
    assert new.checks == 5


def test_failure_records_status_and_increments_failure_counters():
    decision, new = evaluate(fail(status=429), EventState(failures=2), now=1000.0, **KW)
    assert new.last_ok is False
    assert new.last_http_status == 429
    assert new.last_error == "boom"
    assert new.failures == 3
