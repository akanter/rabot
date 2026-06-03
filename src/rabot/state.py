from dataclasses import dataclass, asdict, fields
import json
import os


@dataclass
class State:
    last_available: bool = False
    last_alert_ts: float | None = None
    consecutive_failures: int = 0
    blind_alerted: bool = False


def load_state(path: str) -> State:
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return State()
    known = {f.name for f in fields(State)}
    return State(**{k: v for k, v in data.items() if k in known})


def save_state(path: str, state: State) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(asdict(state), handle)
    os.replace(tmp, path)
