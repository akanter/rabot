from dataclasses import dataclass
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
class Config:
    event_url: str
    signal_sender: str
    signal_recipient: str | None = None
    signal_group_id: str | None = None
    state_path: str = ""
    cooldown_seconds: int = 900
    failure_threshold: int = 5
    graphql_endpoint: str = "https://ra.co/graphql"
    signal_cli_path: str = "signal-cli"

    @property
    def event_id(self) -> str:
        match = re.search(r"/events/(\d+)", self.event_url)
        if not match:
            raise ValueError(f"Could not extract event id from {self.event_url!r}")
        return match.group(1)


def load_config(env=None) -> Config:
    env = os.environ if env is None else env

    def required(key: str) -> str:
        value = env.get(key)
        if not value:
            raise ValueError(f"Missing required env var {key}")
        return value

    recipient = env.get("RABOT_SIGNAL_RECIPIENT") or None
    group_id = env.get("RABOT_SIGNAL_GROUP_ID") or None
    if not recipient and not group_id:
        raise ValueError(
            "Must set RABOT_SIGNAL_RECIPIENT (phone number) or "
            "RABOT_SIGNAL_GROUP_ID (group), or both"
        )

    return Config(
        # event_url may be empty here and supplied as a CLI argument instead;
        # presence is validated in cli.run_check before use.
        event_url=env.get("RABOT_EVENT_URL", ""),
        signal_sender=required("RABOT_SIGNAL_SENDER"),
        signal_recipient=recipient,
        signal_group_id=group_id,
        state_path=env.get("RABOT_STATE_PATH") or default_state_path(),
        cooldown_seconds=int(env.get("RABOT_COOLDOWN_SECONDS", "900")),
        failure_threshold=int(env.get("RABOT_FAILURE_THRESHOLD", "5")),
        graphql_endpoint=env.get("RABOT_GRAPHQL_ENDPOINT", "https://ra.co/graphql"),
        signal_cli_path=env.get("RABOT_SIGNAL_CLI", "signal-cli"),
    )
