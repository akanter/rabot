from dataclasses import dataclass, replace
from enum import Enum

from rabot.ra_client import FetchResult
from rabot.state import State


class Action(Enum):
    NONE = "none"
    ALERT_AVAILABLE = "alert_available"
    ALERT_BLIND = "alert_blind"


@dataclass
class Decision:
    action: Action
    message: str | None = None


def evaluate(result: FetchResult, state: State, *, now: float,
             cooldown_seconds: int, failure_threshold: int,
             event_url: str) -> tuple[Decision, State]:
    if not result.ok:
        failures = state.consecutive_failures + 1
        new = replace(state, consecutive_failures=failures)
        if failures >= failure_threshold and not state.blind_alerted:
            new = replace(new, blind_alerted=True)
            msg = (f"⚠️ rabot can't check {event_url} "
                   f"({failures} consecutive failures): {result.error}")
            return Decision(Action.ALERT_BLIND, msg), new
        return Decision(Action.NONE), new

    new = replace(state, consecutive_failures=0, blind_alerted=False)
    available = result.available

    if available and not state.last_available:
        within_cooldown = (state.last_alert_ts is not None
                           and (now - state.last_alert_ts) < cooldown_seconds)
        if within_cooldown:
            return Decision(Action.NONE), replace(new, last_available=True)
        label = result.event_title or event_url
        msg = f"\U0001f3ab Tickets available for {label}: {event_url}"
        return Decision(Action.ALERT_AVAILABLE, msg), replace(
            new, last_available=True, last_alert_ts=now)

    return Decision(Action.NONE), replace(new, last_available=available)
