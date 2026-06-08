from dataclasses import dataclass
import json
import os
import re


def default_state_path() -> str:
    """Portable per-user state path (honors XDG_STATE_HOME, else ~/.local/state).

    Works on both Linux and macOS without hardcoding a user. The NixOS module
    overrides this with /var/lib/rabot via RABOT_STATE_PATH.
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "rabot", "state.json")


@dataclass(frozen=True)
class EventWatch:
    """A single watched event and where its alerts go."""
    url: str
    recipient: str | None = None
    group_id: str | None = None

    @property
    def event_id(self) -> str:
        match = re.search(r"/events/(\d+)", self.url)
        if not match:
            raise ValueError(f"Could not extract event id from {self.url!r}")
        return match.group(1)


@dataclass(frozen=True)
class Config:
    events: tuple[EventWatch, ...]
    signal_sender: str
    # Defaults used when building a watch from a bare CLI url / RABOT_EVENT_URL.
    default_recipient: str | None = None
    default_group_id: str | None = None
    state_path: str = ""
    cooldown_seconds: int = 900
    failure_threshold: int = 5
    graphql_endpoint: str = "https://ra.co/graphql"
    signal_cli_path: str = "signal-cli"

    def watch_for_url(self, url: str) -> EventWatch:
        """Build a watch for an ad-hoc URL using the global default target."""
        return _make_watch(url, self.default_recipient, self.default_group_id)


def _make_watch(url: str, recipient: str | None, group_id: str | None) -> EventWatch:
    if not recipient and not group_id:
        raise ValueError(
            f"event {url!r} has no target: set a recipient/group on it, "
            "or a global RABOT_SIGNAL_RECIPIENT / RABOT_SIGNAL_GROUP_ID"
        )
    return EventWatch(url=url, recipient=recipient, group_id=group_id)


def load_config(env=None) -> Config:
    env = os.environ if env is None else env

    def required(key: str) -> str:
        value = env.get(key)
        if not value:
            raise ValueError(f"Missing required env var {key}")
        return value

    default_recipient = env.get("RABOT_SIGNAL_RECIPIENT") or None
    default_group_id = env.get("RABOT_SIGNAL_GROUP_ID") or None

    # Events come from RABOT_EVENTS (JSON list) or a single RABOT_EVENT_URL.
    # Each event may carry its own recipient/group; otherwise it falls back to
    # the global default. An empty set is allowed here — the CLI may supply a URL.
    raw = env.get("RABOT_EVENTS")
    if raw:
        entries = json.loads(raw)
    elif env.get("RABOT_EVENT_URL"):
        entries = [{"url": env["RABOT_EVENT_URL"]}]
    else:
        entries = []

    events = tuple(
        _make_watch(
            e["url"],
            e.get("recipient") or default_recipient,
            e.get("group") or default_group_id,
        )
        for e in entries
    )

    return Config(
        events=events,
        signal_sender=required("RABOT_SIGNAL_SENDER"),
        default_recipient=default_recipient,
        default_group_id=default_group_id,
        state_path=env.get("RABOT_STATE_PATH") or default_state_path(),
        cooldown_seconds=int(env.get("RABOT_COOLDOWN_SECONDS", "900")),
        failure_threshold=int(env.get("RABOT_FAILURE_THRESHOLD", "5")),
        graphql_endpoint=env.get("RABOT_GRAPHQL_ENDPOINT", "https://ra.co/graphql"),
        signal_cli_path=env.get("RABOT_SIGNAL_CLI", "signal-cli"),
    )
