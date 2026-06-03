# rabot

rabot watches a single [Resident Advisor](https://ra.co) event and sends you a [Signal](https://signal.org) message the moment tickets become available. It is built for catching resales and returns on a sold-out event.

## What it does

rabot is a one-shot CLI: run `rabot check` on an interval and it will query RA's public GraphQL API (`event.ticketing.isAnyTicketTierAvailable`) to determine whether any ticket tier is currently on sale. When availability flips from unavailable to available, it fires a Signal message to your phone.

Alerts fire once per transition, then go quiet. If the event sells out again and tickets reappear later, the bot re-arms and alerts again. A configurable cooldown prevents repeat messages during a single availability window.

State (last seen availability, cooldown timestamp, consecutive failure count) is persisted in a local JSON file, so the bot survives restarts without losing context. After `RABOT_FAILURE_THRESHOLD` consecutive fetch failures it sends a "can't check" heads-up so silence is never ambiguous — you always know whether the bot is working.

rabot does not keep a process running between checks. Schedule it with systemd (NixOS) or launchd (macOS) at whatever interval you want.

## One-time signal-cli linking

rabot delegates all Signal sending to [signal-cli](https://github.com/AsamK/signal-cli). You need to link signal-cli to your Signal account once before anything works.

**Install signal-cli:**

```bash
# Nix / NixOS
nix profile install nixpkgs#signal-cli

# macOS (Homebrew)
brew install signal-cli
```

**Link to your phone:**

```bash
signal-cli link -n "rabot"
```

This prints a `tsdevice:/...` URI. Paste it into any QR code generator (e.g. a browser-based one), then in the Signal app on your phone go to **Settings → Linked devices** and scan the code.

After linking:

- `RABOT_SIGNAL_SENDER` is the phone number of the Signal account you linked (the number on the phone you scanned from).
- `RABOT_SIGNAL_RECIPIENT` is the destination for alerts. Setting it to the same number as the sender delivers alerts to your own "Note to Self" conversation, which works well.

## NixOS deploy

The flake ships a NixOS module. Add rabot to your system flake inputs:

```nix
# flake.nix (your system flake)
inputs.rabot.url = "github:YOU/rabot";  # local repo for now — adjust when published
```

Import the module in your NixOS configuration:

```nix
imports = [ inputs.rabot.nixosModules.default ];
```

Configure and enable the service:

```nix
services.rabot = {
  enable = true;
  eventUrl = "https://ra.co/events/2345415";
  signalSender = "+10000000000";
  signalRecipient = "+10000000001";
  interval = "60s";        # systemd timer interval; jittered by RandomizedDelaySec
  # cooldownSeconds = 900; # optional, default 900
  # failureThreshold = 5;  # optional, default 5
};
```

Then rebuild:

```bash
sudo nixos-rebuild switch
```

**Logs:**

```bash
journalctl -u rabot
```

The module wires a systemd oneshot service and a timer. `signal-cli` is placed on the service's `PATH` automatically.

**signal-cli linking for the NixOS service:** the module sets `DynamicUser = true` and `HOME=/var/lib/rabot`, so signal-cli reads and writes its linked-account data under `/var/lib/rabot/.local/share/signal-cli`. The `StateDirectory = "rabot"` directive ensures `/var/lib/rabot` is created and persisted across runs. You must perform the one-time link so the data ends up there — for example:

```bash
sudo HOME=/var/lib/rabot signal-cli link -n "rabot"
# then chown the result to the service's state directory if needed:
sudo chown -R root:root /var/lib/rabot   # DynamicUser owns it at runtime; root is fine for storage
```

Alternatively, link elsewhere and copy the resulting `~/.local/share/signal-cli` directory into `/var/lib/rabot/.local/share/signal-cli`. Verify signal-cli can send a test message before relying on the bot.

## macOS deploy

Build the binary:

```bash
nix build
# result/bin/rabot is the built binary

# or run directly without installing:
nix run .# -- check
```

Edit the example plist:

```bash
cp examples/com.rabot.check.plist ~/Library/LaunchAgents/com.rabot.check.plist
```

Open it and replace the placeholders:

- `/ABSOLUTE/PATH/TO/rabot` — paste the absolute path to `result/bin/rabot`
- `RABOT_EVENT_URL` — the RA event URL
- `RABOT_SIGNAL_SENDER` / `RABOT_SIGNAL_RECIPIENT` — your phone numbers
- `RABOT_STATE_PATH` — a writable path, e.g. `/Users/you/Library/Application Support/rabot/state.json` (create the directory first)

Load the agent:

```bash
launchctl load ~/Library/LaunchAgents/com.rabot.check.plist
```

**Logs:** `/tmp/rabot.out.log` and `/tmp/rabot.err.log`

`StartInterval` in the plist (seconds) controls the poll cadence.

## Configuration reference

All configuration is via environment variables.

| Variable | Required | Default | Description |
|---|---|---|---|
| `RABOT_EVENT_URL` | yes | — | RA event URL, e.g. `https://ra.co/events/2345415` |
| `RABOT_SIGNAL_SENDER` | yes | — | Phone number of the linked signal-cli account |
| `RABOT_SIGNAL_RECIPIENT` | yes | — | Destination phone number for alerts |
| `RABOT_STATE_PATH` | no | `/var/lib/rabot/state.json` | Path to the JSON state file |
| `RABOT_COOLDOWN_SECONDS` | no | `900` | Minimum seconds between repeat alerts within one availability window |
| `RABOT_FAILURE_THRESHOLD` | no | `5` | Consecutive fetch failures before a "blind" alert is sent |
| `RABOT_GRAPHQL_ENDPOINT` | no | `https://ra.co/graphql` | RA GraphQL endpoint |
| `RABOT_SIGNAL_CLI` | no | `signal-cli` | Path to the signal-cli binary |

## Tuning

The default poll interval is 60 seconds. Lower values increase responsiveness but may trigger rate-limiting from RA — if you see sustained fetch failures, back off. After `RABOT_FAILURE_THRESHOLD` consecutive failures the bot will Signal you that it has gone blind, so you will not be left wondering if it is still working.

See [`docs/ra-api-notes.md`](docs/ra-api-notes.md) for details on how ticket availability is detected via the RA GraphQL API.
