# rabot

rabot watches one or more [Resident Advisor](https://ra.co) events and sends a [Signal](https://signal.org) message the moment tickets become available. It is built for catching resales and returns on a sold-out event.

## What it does

rabot is a one-shot CLI: `rabot check` queries RA's public GraphQL API for each watched event to see whether any **non-add-on** ticket tier is currently buyable. It reads both of RA's ticketing systems — the legacy per-tier `validType` (a tier flips `SOLDOUT → VALID`) and the newer `isAnyTicketTierAvailable` flag — so it works for festivals like Houghton (legacy) as well as newer events. When an event flips from unavailable to available, it sends a Signal message — to a phone number, a group, or both, **per event**.

- Alerts fire **once per transition**, then go quiet. If the event sells out and tickets reappear, the bot **re-arms** and alerts again. A cooldown prevents repeat messages within one availability window.
- **Per-event state and targets:** each event tracks its own availability/cooldown and can route to its own recipient/group (falling back to a global default).
- Per-event state plus observability (last check time, last HTTP status, failure/alert counters) is persisted to a JSON file, so it survives restarts. `rabot status` prints it.
- After `RABOT_FAILURE_THRESHOLD` consecutive fetch failures on an event it sends a "can't check" heads-up, so silence is never ambiguous.

rabot keeps no process running between checks. A scheduler (systemd timer on NixOS, a launchd job on macOS) runs `rabot check` on an interval. The Nix flake provides modules that wire all of this up for you.

## CLI

```
rabot check [URL ...]   # one check cycle; URLs override the configured events
rabot status            # per-event health/stats dashboard from the state file
rabot link [NAME]       # one-time: link this device to your Signal account
```

`rabot link` runs signal-cli's device linking, renders the QR right in your terminal (via `qrencode`), and waits — scan it with **Signal → Settings → Linked Devices → +**. `NAME` defaults to `rabot-<hostname>`.

## Deploy with the Nix flake (recommended)

The flake provides `nixosModules.default` (systemd) and `darwinModules.default` (launchd), plus the `rabot` package. Add it to your system flake inputs:

```nix
inputs.rabot.url = "github:akanter/rabot";
inputs.rabot.inputs.nixpkgs.follows = "nixpkgs";
```

Both modules run as a real **`user`** (not a throwaway DynamicUser) so signal-cli's linked-account data lives in that user's home and persists. With `withCliTools` (default on), the module also puts `rabot`, `signal-cli`, and `qrencode` on `PATH`, and after a rebuild it prints a reminder if the account isn't linked yet.

### NixOS

```nix
{
  imports = [ inputs.rabot.nixosModules.default ];

  services.rabot = {
    enable = true;
    user = "ak";                                   # runs as this user; link signal-cli in their home
    signalSender = "+10000000000";                 # your linked Signal number

    # Default target — used by any event that doesn't override it. Set at least one:
    signalGroupId = "BASE64GROUPID=";
    # signalRecipient = "+10000000001";

    # Events to watch. Each may override the default target with its own
    # recipient/groupId; omit to fall back to the default above.
    events = [
      { url = "https://ra.co/events/2287366"; }                                # → default target
      # { url = "https://ra.co/events/2345415"; recipient = "+10000000001"; }  # → you instead
    ];

    # interval = "60s";          # check cadence (default 60s)
    # receiveInterval = "6h";    # signal-cli receive housekeeping (default 6h; null to disable)
    # cooldownSeconds = 900;
    # failureThreshold = 5;
  };
}
```

```bash
sudo nixos-rebuild switch
# if it says rabot isn't linked yet:
sudo -u ak rabot link
# logs:
journalctl -u rabot.service        # the checks
systemctl list-timers rabot.timer  # cadence
```

### macOS (nix-darwin)

```nix
{
  imports = [ inputs.rabot.darwinModules.default ];

  services.rabot = {
    enable = true;
    user = "you";                                  # LaunchDaemon runs as this user
    eventUrl = "https://ra.co/events/2287366";
    signalSender = "+10000000000";
    signalGroupId = "BASE64GROUPID=";
    # intervalSeconds = 60;            # check cadence (default 60)
    # receiveIntervalSeconds = 21600;  # receive housekeeping (default 6h; null to disable)
  };
}
```

```bash
sudo darwin-rebuild switch
rabot link               # if prompted that it isn't linked
# logs: /tmp/rabot.out.log, /tmp/rabot.err.log
```

A LaunchDaemon with `UserName` (not a LaunchAgent) is used deliberately: it suits `sudo darwin-rebuild`, needs no GUI-login bootstrap, and runs 24/7.

> Finding a group ID: `signal-cli -u <sender> listGroups` prints each group's base64 `Id:`. To alert a group, signal-cli must have **received** the group at least once (the receive timer handles this).

## Config file (alternative to env vars)

Instead of env vars you can use a TOML file — nicer for hand-editing, especially with several events. rabot reads it from `$RABOT_CONFIG`, or `~/.config/rabot/config.toml` by default. **If a config file is present it is authoritative; otherwise rabot falls back to the env vars.** (The Nix modules generate this file for you and point `RABOT_CONFIG` at it, so the systemd unit / launchd plist carries just `RABOT_CONFIG` + `HOME`.)

```toml
signal_sender = "+12066597096"
signal_group_id = "BASE64GROUPID="     # default target (set recipient and/or group)
# signal_recipient = "+10000000001"
# cooldown_seconds = 900
# failure_threshold = 5

[[events]]
url = "https://ra.co/events/2287366"          # → default target

[[events]]
url = "https://ra.co/events/2345415"
recipient = "+10000000001"                     # per-event override
```

## Manual / non-Nix run

`rabot` only needs `signal-cli` on `PATH` (or `RABOT_SIGNAL_CLI` pointed at it). Provide a config file (above) or the env vars, then run `rabot check` from cron, a systemd timer, or the example `examples/com.rabot.check.plist` launchd job.

## Account housekeeping (`signal-cli receive`)

A linked device must `receive` periodically to refresh prekeys, rotate keys, and pick up group/session state — otherwise a later send (to a group especially) can fail. Because rabot sends rarely, the modules run `signal-cli receive` on a timer (`receiveInterval` / `receiveIntervalSeconds`, default 6h) to keep the device healthy. Set it to `null` to disable.

## Configuration reference

The CLI reads environment variables; the modules set them for you from the options above.

| Variable | Required | Default | Description |
|---|---|---|---|
| `RABOT_EVENTS` | yes¹ | — | Events to watch: a plain space/comma-separated URL list (all on the default target), **or** JSON `[{"url","recipient"?,"group"?}, …]` for per-event target overrides. |
| `RABOT_SIGNAL_SENDER` | yes | — | Phone number of the linked signal-cli account |
| `RABOT_SIGNAL_RECIPIENT` | yes² | — | Default recipient phone number (per-event target falls back to this) |
| `RABOT_SIGNAL_GROUP_ID` | yes² | — | Default Signal group (base64 id) (per-event target falls back to this) |
| `RABOT_STATE_PATH` | no | `$XDG_STATE_HOME/rabot/state.json` (else `~/.local/state/…`) | Per-event JSON state file |
| `RABOT_COOLDOWN_SECONDS` | no | `900` | Min seconds between repeat alerts in one window |
| `RABOT_FAILURE_THRESHOLD` | no | `5` | Consecutive fetch failures before a "blind" alert |
| `RABOT_GRAPHQL_ENDPOINT` | no | `https://ra.co/graphql` | RA GraphQL endpoint |
| `RABOT_SIGNAL_CLI` | no | `signal-cli` | Path to the signal-cli binary (the Nix package bakes in a working one) |

¹ Provide events via `RABOT_EVENTS` or `rabot check <url> …`. ² Each event needs a target — set it per-event in `RABOT_EVENTS`, or set a global `RABOT_SIGNAL_RECIPIENT` / `RABOT_SIGNAL_GROUP_ID`.

## Monitoring & tuning

Two views into what the bot is doing:

- **`rabot status`** — a per-event dashboard: when each event was last checked, ok/fail, current availability, consecutive failures, and lifetime check/failure/alert counts.
- **Per-check log line** — each cycle logs one line per event to stderr (→ `journalctl -u rabot.service` on NixOS, `/tmp/rabot.out.log`/`.err.log` on macOS):
  ```
  2026-06-08T06:46:06+00:00 event=2287366 ok=True status=200 available=False consecutive_failures=0
  ```

**Rate-limiting / blocking** shows up directly in that `status=` field and in `state.json`'s `last_http_status`: `200` is healthy, **`429` = throttled**, **`403` = blocked** (a `RATE-LIMITED` tag is added to the log line for those). A healthy-but-quiet bot (`available=False`, `last_http_status=200`, `consecutive_failures=0`) is *correct* silence — there's just nothing to alert on yet.

**Poll cadence** (`interval` / `intervalSeconds`) defaults to 60s. To go faster, lower it and watch `rabot status` / the log for any non-200 status. If `429`/`403` appear, back off; after `RABOT_FAILURE_THRESHOLD` consecutive failures the bot Signals you that it's gone blind, so you are never left guessing.

See [`docs/ra-api-notes.md`](docs/ra-api-notes.md) for how availability is detected via the RA GraphQL API.
