from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class Config:
    event_url: str
    signal_sender: str
    signal_recipient: str
    state_path: str
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

    return Config(
        event_url=required("RABOT_EVENT_URL"),
        signal_sender=required("RABOT_SIGNAL_SENDER"),
        signal_recipient=required("RABOT_SIGNAL_RECIPIENT"),
        state_path=env.get("RABOT_STATE_PATH", "/var/lib/rabot/state.json"),
        cooldown_seconds=int(env.get("RABOT_COOLDOWN_SECONDS", "900")),
        failure_threshold=int(env.get("RABOT_FAILURE_THRESHOLD", "5")),
        graphql_endpoint=env.get("RABOT_GRAPHQL_ENDPOINT", "https://ra.co/graphql"),
        signal_cli_path=env.get("RABOT_SIGNAL_CLI", "signal-cli"),
    )
