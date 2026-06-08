from dataclasses import dataclass, asdict, fields
import json
import os


@dataclass
class EventState:
    # transition tracking
    last_available: bool = False
    last_alert_ts: float | None = None
    consecutive_failures: int = 0
    blind_alerted: bool = False
    # observability
    last_checked: str | None = None      # ISO8601 of the most recent check
    last_ok: bool | None = None          # did the most recent fetch succeed
    last_http_status: int | None = None  # 200 / 429 / 403 / … (rate-limit signal)
    last_error: str | None = None        # most recent fetch error, else None
    checks: int = 0                      # lifetime checks for this event
    failures: int = 0                    # lifetime fetch failures
    alerts: int = 0                      # lifetime alerts actually sent


_KNOWN = {f.name for f in fields(EventState)}


def load_states(path: str) -> dict[str, EventState]:
    """Load per-event state keyed by event id. Missing/corrupt/old-format → {}."""
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    events = data.get("events")
    if not isinstance(events, dict):  # missing or pre-multi-event flat file → start fresh
        return {}
    return {
        eid: EventState(**{k: v for k, v in es.items() if k in _KNOWN})
        for eid, es in events.items()
        if isinstance(es, dict)
    }


def save_states(path: str, states: dict[str, EventState]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    data = {"events": {eid: asdict(es) for eid, es in states.items()}}
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)
