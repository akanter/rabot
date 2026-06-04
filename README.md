# rabot

rabot watches a single [Resident Advisor](https://ra.co) event and sends a [Signal](https://signal.org) message the moment tickets become available. It is built for catching resales and returns on a sold-out event.

## What it does

rabot is a one-shot CLI: `rabot check` queries RA's public GraphQL API (`event.ticketing.isAnyTicketTierAvailable`) to see whether any ticket tier is currently buyable. When availability flips from unavailable to available, it sends a Signal message — to a phone number, a group, or both.

- Alerts fire **once per transition**, then go quiet. If the event sells out and tickets reappear, the bot **re-arms** and alerts again. A cooldown prevents repeat messages within one availability window.
- State (last availability, cooldown timestamp, failure count) is persisted to a JSON file, so it survives restarts.
- After `RABOT_FAILURE_THRESHOLD` consecutive fetch failures it sends a "can't check" heads-up, so silence is never ambiguous.

rabot keeps no process running between checks. A scheduler (systemd timer on NixOS, a launchd job on macOS) runs `rabot check` on an interval. The Nix flake provides modules that wire all of this up for you.

## CLI

```
rabot check [EVENT_URL]   # one check cycle; EVENT_URL overrides RABOT_EVENT_URL
rabot link [NAME]         # one-time: link this device to your Signal account
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
    eventUrl = "https://ra.co/events/2287366";
    signalSender = "+10000000000";                 # your linked Signal number
    signalGroupId = "BASE64GROUPID=";              # alert a group …
    # signalRecipient = "+10000000001";            # … and/or a phone number (set at least one)
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

## Manual / non-Nix run

`rabot` only needs `signal-cli` on `PATH` (or `RABOT_SIGNAL_CLI` pointed at it). Set the env vars and run `rabot check` from cron, a systemd timer, or the example `examples/com.rabot.check.plist` launchd job.

## Account housekeeping (`signal-cli receive`)

A linked device must `receive` periodically to refresh prekeys, rotate keys, and pick up group/session state — otherwise a later send (to a group especially) can fail. Because rabot sends rarely, the modules run `signal-cli receive` on a timer (`receiveInterval` / `receiveIntervalSeconds`, default 6h) to keep the device healthy. Set it to `null` to disable.

## Configuration reference

The CLI reads environment variables; the modules set them for you from the options above.

| Variable | Required | Default | Description |
|---|---|---|---|
| `RABOT_EVENT_URL` | yes¹ | — | RA event URL, e.g. `https://ra.co/events/2287366` |
| `RABOT_SIGNAL_SENDER` | yes | — | Phone number of the linked signal-cli account |
| `RABOT_SIGNAL_RECIPIENT` | yes² | — | Destination phone number for alerts |
| `RABOT_SIGNAL_GROUP_ID` | yes² | — | Destination Signal group (base64 id) for alerts |
| `RABOT_STATE_PATH` | no | `$XDG_STATE_HOME/rabot/state.json` (else `~/.local/state/…`) | JSON state file |
| `RABOT_COOLDOWN_SECONDS` | no | `900` | Min seconds between repeat alerts in one window |
| `RABOT_FAILURE_THRESHOLD` | no | `5` | Consecutive fetch failures before a "blind" alert |
| `RABOT_GRAPHQL_ENDPOINT` | no | `https://ra.co/graphql` | RA GraphQL endpoint |
| `RABOT_SIGNAL_CLI` | no | `signal-cli` | Path to the signal-cli binary (the Nix package bakes in a working one) |

¹ Optional if you pass the URL as `rabot check <url>`. ² Set **at least one** of `RABOT_SIGNAL_RECIPIENT` / `RABOT_SIGNAL_GROUP_ID`.

## Tuning

The default poll interval is 60s. Lower is more responsive but risks RA rate-limiting; after `RABOT_FAILURE_THRESHOLD` consecutive failures the bot Signals you that it has gone blind, so you are never left guessing.

See [`docs/ra-api-notes.md`](docs/ra-api-notes.md) for how availability is detected via the RA GraphQL API.
