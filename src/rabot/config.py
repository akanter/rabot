from dataclasses import dataclass
import json
import os
import re
import tomllib


def default_state_path() -> str:
    """Portable per-user state path (honors XDG_STATE_HOME, else ~/.local/state)."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "rabot", "state.json")


def default_config_path() -> str:
    """Default config file location (honors XDG_CONFIG_HOME, else ~/.config)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "rabot", "config.toml")


def resolve_state_path(env=None) -> str:
    """Where the state file lives — without requiring the full config.

    Used by `rabot status`, which only reads state and needs no Signal settings.
    Mirrors load_config's precedence: a TOML config's state_path if a config file
    is in play, else RABOT_STATE_PATH, else the default.
    """
    env = os.environ if env is None else env
    cfg_path = env.get("RABOT_CONFIG")
    if cfg_path and os.path.exists(cfg_path):
        with open(cfg_path, "rb") as handle:
            return tomllib.load(handle).get("state_path") or default_state_path()
    return env.get("RABOT_STATE_PATH") or default_state_path()


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
    # Optional: with a single linked signal-cli account it's auto-selected, so
    # this is only needed for multi-account setups.
    signal_sender: str | None = None
    # Defaults used when building a watch from a bare CLI url.
    default_recipient: str | None = None
    default_group_id: str | None = None
    state_path: str = ""
    cooldown_seconds: int = 900
    failure_threshold: int = 5
    graphql_endpoint: str = "https://ra.co/graphql"
    signal_cli_path: str = "signal-cli"

    def watch_for_url(self, url: str) -> EventWatch:
        return _make_watch(url, self.default_recipient, self.default_group_id)


def _make_watch(url: str, recipient: str | None, group_id: str | None) -> EventWatch:
    if not recipient and not group_id:
        raise ValueError(
            f"event {url!r} has no target: set a recipient/group on it, "
            "or a default recipient/group"
        )
    return EventWatch(url=url, recipient=recipient, group_id=group_id)


def load_config(env=None) -> Config:
    """Load config from a TOML file if present, else from environment variables.

    A config file is used when RABOT_CONFIG points at one, or (for a real run,
    i.e. env is None) when ~/.config/rabot/config.toml exists. Otherwise the
    RABOT_* environment variables are read.
    """
    use_default_path = env is None
    env = os.environ if env is None else env

    cfg_path = env.get("RABOT_CONFIG")
    if cfg_path:
        if not os.path.exists(cfg_path):
            raise ValueError(f"RABOT_CONFIG file not found: {cfg_path}")
    elif use_default_path:
        dp = default_config_path()
        cfg_path = dp if os.path.exists(dp) else None

    if cfg_path:
        return _from_toml(cfg_path, env)
    return _from_env(env)


def _signal_cli(env) -> str:
    # The Nix wrapper sets RABOT_SIGNAL_CLI to the bundled signal-cli; honor it
    # even in TOML mode unless the file overrides it.
    return env.get("RABOT_SIGNAL_CLI", "signal-cli")


def _from_toml(path: str, env) -> Config:
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    sender = data.get("signal_sender")  # optional — single account auto-selected
    default_recipient = data.get("signal_recipient")
    default_group_id = data.get("signal_group_id")
    events = tuple(
        _make_watch(e["url"], e.get("recipient") or default_recipient,
                    e.get("group") or default_group_id)
        for e in data.get("events", [])
    )
    return Config(
        events=events,
        signal_sender=sender,
        default_recipient=default_recipient,
        default_group_id=default_group_id,
        state_path=data.get("state_path") or default_state_path(),
        cooldown_seconds=int(data.get("cooldown_seconds", 900)),
        failure_threshold=int(data.get("failure_threshold", 5)),
        graphql_endpoint=data.get("graphql_endpoint", "https://ra.co/graphql"),
        signal_cli_path=data.get("signal_cli") or _signal_cli(env),
    )


def _from_env(env) -> Config:
    sender = env.get("RABOT_SIGNAL_SENDER") or None  # optional — single account auto-selected
    default_recipient = env.get("RABOT_SIGNAL_RECIPIENT") or None
    default_group_id = env.get("RABOT_SIGNAL_GROUP_ID") or None

    # RABOT_EVENTS is a plain whitespace/comma-separated URL list (all on the
    # default target) or a JSON list of {url, recipient?, group?} for overrides.
    raw = (env.get("RABOT_EVENTS") or "").strip()
    if raw.startswith("["):
        entries = json.loads(raw)
    elif raw:
        entries = [{"url": u} for u in raw.replace(",", " ").split()]
    else:
        entries = []

    events = tuple(
        _make_watch(e["url"], e.get("recipient") or default_recipient,
                    e.get("group") or default_group_id)
        for e in entries
    )
    return Config(
        events=events,
        signal_sender=sender,
        default_recipient=default_recipient,
        default_group_id=default_group_id,
        state_path=env.get("RABOT_STATE_PATH") or default_state_path(),
        cooldown_seconds=int(env.get("RABOT_COOLDOWN_SECONDS", "900")),
        failure_threshold=int(env.get("RABOT_FAILURE_THRESHOLD", "5")),
        graphql_endpoint=env.get("RABOT_GRAPHQL_ENDPOINT", "https://ra.co/graphql"),
        signal_cli_path=_signal_cli(env),
    )
