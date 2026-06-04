import argparse
import os
import socket
import sys
import time
from dataclasses import replace

from rabot.config import load_config
from rabot.state import load_state, save_state
from rabot.ra_client import fetch
from rabot.evaluator import evaluate, Action
from rabot.notifier import SignalNotifier, link as signal_link


def build_notifier(config):
    return SignalNotifier(
        config.signal_cli_path,
        config.signal_sender,
        recipient=config.signal_recipient,
        group_id=config.signal_group_id,
    )


def run_check(event_url: str | None = None) -> None:
    config = load_config()
    if event_url:  # CLI argument overrides RABOT_EVENT_URL
        config = replace(config, event_url=event_url)
    if not config.event_url:
        raise SystemExit(
            "No event URL: pass it as `rabot check <url>` or set RABOT_EVENT_URL"
        )
    state = load_state(config.state_path)
    result = fetch(config)
    decision, new_state = evaluate(
        result, state,
        now=time.time(),
        cooldown_seconds=config.cooldown_seconds,
        failure_threshold=config.failure_threshold,
        event_url=config.event_url,
    )
    if decision.action is not Action.NONE:
        try:
            build_notifier(config).send(decision.message)
        except Exception as exc:  # signal-cli failed; don't record the alert as delivered
            print(
                "rabot: Signal send failed, will retry next cycle "
                f"(if this device isn't linked yet, run `rabot link`): {exc}",
                file=sys.stderr,
            )
            # Keep the prior alert-tracking state (so the alert re-fires next cycle),
            # but absorb the freshly-observed fetch-failure counter so blind-detection
            # still progresses across cycles.
            new_state = replace(state, consecutive_failures=new_state.consecutive_failures)
    save_state(config.state_path, new_state)


def run_link(name: str | None = None) -> int:
    """One-time: link this device to your Signal account (renders a QR to scan)."""
    signal_cli = os.environ.get("RABOT_SIGNAL_CLI", "signal-cli")
    device = name or f"rabot-{socket.gethostname()}"
    return signal_link(signal_cli, device)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rabot")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Run one availability check cycle")
    check.add_argument("event_url", nargs="?", default=None,
                       help="RA event URL to check (overrides RABOT_EVENT_URL)")
    linkp = sub.add_parser("link", help="Link this device to your Signal account (one-time)")
    linkp.add_argument("name", nargs="?", default=None,
                       help="Device name shown in Signal (default: rabot-<hostname>)")
    args = parser.parse_args(argv)
    if args.command == "check":
        run_check(event_url=args.event_url)
        return 0
    if args.command == "link":
        return run_link(args.name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
