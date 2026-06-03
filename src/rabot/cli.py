import argparse
import sys
import time
from dataclasses import replace

from rabot.config import load_config
from rabot.state import load_state, save_state
from rabot.ra_client import fetch
from rabot.evaluator import evaluate, Action
from rabot.notifier import SignalNotifier


def build_notifier(config):
    return SignalNotifier(config.signal_cli_path, config.signal_sender, config.signal_recipient)


def run_check() -> None:
    config = load_config()
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
            print(f"rabot: Signal send failed, will retry next cycle: {exc}", file=sys.stderr)
            # Keep the prior alert-tracking state (so the alert re-fires next cycle),
            # but absorb the freshly-observed fetch-failure counter so blind-detection
            # still progresses across cycles.
            new_state = replace(state, consecutive_failures=new_state.consecutive_failures)
    save_state(config.state_path, new_state)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rabot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Run one availability check cycle")
    args = parser.parse_args(argv)
    if args.command == "check":
        run_check()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
