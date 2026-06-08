import argparse
import os
import socket
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone

from rabot.config import load_config
from rabot.state import EventState, load_states, save_states
from rabot.ra_client import fetch
from rabot.evaluator import evaluate, Action
from rabot.notifier import SignalNotifier, link as signal_link


def build_notifier(config, watch):
    return SignalNotifier(
        config.signal_cli_path,
        config.signal_sender,
        recipient=watch.recipient,
        group_id=watch.group_id,
    )


def _log_check(watch, result, state) -> None:
    flag = " RATE-LIMITED" if result.status_code in (429, 403) else ""
    line = (f"{state.last_checked} event={watch.event_id} ok={result.ok} "
            f"status={result.status_code} available={result.available} "
            f"consecutive_failures={state.consecutive_failures}{flag}")
    if result.error:
        line += f" error={result.error!r}"
    print(line, file=sys.stderr)


def run_check(event_urls: list[str] | None = None) -> None:
    config = load_config()
    watches = (
        [config.watch_for_url(u) for u in event_urls] if event_urls else list(config.events)
    )
    if not watches:
        raise SystemExit(
            "No events: pass `rabot check <url> [<url>…]` or set "
            "RABOT_EVENT_URL / RABOT_EVENTS"
        )

    states = load_states(config.state_path)
    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for watch in watches:
        eid = watch.event_id
        prev = states.get(eid, EventState())
        result = fetch(eid, config.graphql_endpoint)
        decision, new_state = evaluate(
            result, prev,
            now=now, now_iso=now_iso,
            cooldown_seconds=config.cooldown_seconds,
            failure_threshold=config.failure_threshold,
            event_url=watch.url,
        )
        if decision.action is not Action.NONE:
            try:
                build_notifier(config, watch).send(decision.message)
                new_state = replace(new_state, alerts=new_state.alerts + 1)
            except Exception as exc:  # send failed; don't record the alert as delivered
                print(
                    f"rabot: Signal send failed for {watch.url}, will retry next cycle "
                    f"(run `rabot link` if this device isn't linked): {exc}",
                    file=sys.stderr,
                )
                # Keep the fresh observability + failure counters, but undo the
                # "delivered" markers so the alert re-fires next cycle.
                new_state = replace(
                    new_state,
                    last_alert_ts=prev.last_alert_ts,
                    blind_alerted=prev.blind_alerted,
                    last_available=prev.last_available,
                )
        states[eid] = new_state
        _log_check(watch, result, new_state)

    save_states(config.state_path, states)


def run_status() -> int:
    config = load_config()
    states = load_states(config.state_path)
    if not config.events and not states:
        print("rabot: no events configured and no state yet.")
        return 0
    now = datetime.now(timezone.utc)
    # Show configured events first, then any others present in state.
    ids = [w.event_id for w in config.events]
    ids += [eid for eid in states if eid not in ids]
    for eid in ids:
        st = states.get(eid)
        if st is None:
            print(f"event {eid}: no checks yet")
            continue
        ago = "?"
        if st.last_checked:
            try:
                delta = now - datetime.fromisoformat(st.last_checked)
                ago = f"{int(delta.total_seconds())}s ago"
            except ValueError:
                ago = st.last_checked
        health = "ok" if st.last_ok else f"FAIL (status={st.last_http_status})"
        print(
            f"event {eid}: checked {ago} · {health} · available={st.last_available} · "
            f"consecutive_failures={st.consecutive_failures} · "
            f"checks={st.checks} failures={st.failures} alerts={st.alerts}"
            + (f" · last_error={st.last_error!r}" if st.last_error else "")
        )
    return 0


def run_link(name: str | None = None) -> int:
    signal_cli = os.environ.get("RABOT_SIGNAL_CLI", "signal-cli")
    device = name or f"rabot-{socket.gethostname()}"
    return signal_link(signal_cli, device)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rabot")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Run one availability check cycle")
    check.add_argument("event_urls", nargs="*", default=None,
                       help="RA event URL(s) to check (override configured events)")
    sub.add_parser("status", help="Show per-event health/stats from the state file")
    linkp = sub.add_parser("link", help="Link this device to your Signal account (one-time)")
    linkp.add_argument("name", nargs="?", default=None,
                       help="Device name shown in Signal (default: rabot-<hostname>)")
    args = parser.parse_args(argv)
    if args.command == "check":
        run_check(event_urls=args.event_urls or None)
        return 0
    if args.command == "status":
        return run_status()
    if args.command == "link":
        return run_link(args.name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
