# RA Resale Bot — Design Spec

**Date:** 2026-06-03
**Status:** Approved (pending spec review)

## Purpose

Poll a single sold-out [Resident Advisor](https://ra.co) event on a configurable
interval and send a Signal message the moment a ticket tier flips from
unavailable → available (resale / returns). The user is typically watching one
sold-out event and wants to be alerted the instant returned tickets reappear.

## Core decisions

| Decision | Choice |
|----------|--------|
| Notification channel | Signal (via native `signal-cli`) |
| Events watched | One at a time |
| Trigger scenario | Resale on a sold-out event (unavailable → available) |
| Poll cadence | Configurable, default 60s, with jitter |
| Alert behavior | Once per transition, with cooldown; re-arm if it sells out and reappears |
| Language | Python 3.12 |
| Run model | One-shot CLI (`rabot check`) fired by an external scheduler |
| Packaging | Nix flake (package + NixOS module); macOS supported via launchd/cron |

## Architecture

The design separates a **portable core** from **platform-specific scheduling
glue**. This split is what makes the bot portable: because the core is a
one-shot command, any scheduler (systemd timer, launchd, cron) can drive it
without the core knowing or caring.

### Portable core

A one-shot CLI: `rabot check` performs exactly one cycle —
poll → evaluate → maybe notify → write state → exit. Pure Python; its only
external runtime dependency is a `signal-cli` binary on `PATH`. Runs identically
on NixOS, generic Linux, and macOS.

There is no long-running daemon. All state that must survive between cycles
(last-known availability, cooldown timing, consecutive-failure count) lives in a
JSON state file. This makes the process crash-safe and memory-leak-proof, and
means the schedule lives in the (more reliable) OS scheduler rather than an
in-process sleep loop.

### Scheduling glue (per platform, interchangeable)

- **NixOS (first-class):** a Nix flake provides the app as a package and a
  NixOS module that declaratively wires up a `systemd` service + timer and pulls
  `signal-cli` from nixpkgs. The user adds the module to their config, sets
  options, and runs `nixos-rebuild`. No manual unit files, no manual
  Java/signal-cli install. `RandomizedDelaySec` supplies poll jitter for free.
- **macOS (works, lightly supported):** the same flake package runs via
  `nix run` (or pip). Scheduling via an example `launchd` plist or cron;
  `signal-cli` from nixpkgs or Homebrew. Only the few-line scheduler wrapper
  differs from Linux.

## Components

Each component has one purpose, a well-defined interface, and is independently
testable.

### `ra_client`
Given the event URL / ID, returns structured availability: a list of tiers, each
`{title, price, available: bool}`. Encapsulates **all** RA-specific detail
(GraphQL endpoint, query, response parsing) so no other component touches HTTP
or parsing.

> **Discovery spike required.** RA's site (ra.co) is a React app that pulls event
> data from a GraphQL endpoint. Confirming the exact query and fields is the one
> genuine unknown in this project and must be spiked early. Risk: if RA blocks
> unauthenticated GraphQL, we may need a session cookie or, as a last resort, a
> headless-browser fallback. The `ra_client` interface isolates this risk from
> the rest of the system.

### `evaluator`
Pure logic, no I/O. Takes current availability + persisted last-known state and
decides whether this cycle is an alert-worthy transition. Applies:
- **Transition detection:** alert only on unavailable → available.
- **Quiet-while-available:** no repeat alerts while a tier stays available.
- **Cooldown:** suppress flicker spam.
- **Re-arm:** if a tier sells out and later reappears, alert again.

### `notifier`
Sends a Signal message by shelling out to `signal-cli`. Behind a small interface
so it can be faked in tests and swapped later if needed.

### `state store`
A small JSON file (on a path the scheduler/module configures). Persists
last-known availability, cooldown timestamps, and the consecutive-failure
counter. Survives restarts and redeploys so we never re-alert spuriously or lose
cooldown timing.

### `main` (one cycle)
Wires the above for a single `rabot check` invocation: load config → load state →
`ra_client` fetch → `evaluator` decide → (maybe) `notifier` send → write state.

### `config`
Reads configuration from env vars / a config file: event URL, poll interval,
cooldown duration, consecutive-failure threshold, Signal sender + recipient
numbers, state-file path. On NixOS these are surfaced as module options.

## Data flow

```
scheduler tick
  → rabot check
      → config load
      → state load (JSON)
      → ra_client.fetch(event)        # GraphQL → structured tiers
      → evaluator.decide(current, state)
          → alert-worthy & not in cooldown?
              → notifier.send(signal)
      → state write (JSON)
  → exit
```

## Error handling

A resale bot's worst failure is **silent** failure — treating "couldn't check"
as "no tickets," which makes the user miss the drop while believing the bot is
watching. Rules:

- **"Couldn't check" is a distinct state from "confirmed unavailable."** A failed
  or unparseable fetch is never interpreted as availability data.
- **Failures are counted in the state file.** After N consecutive failures
  (configurable), the bot sends the *user* a Signal heads-up that it is blind —
  likely rate-limited or RA changed their schema — so silence is never ambiguous.
- **Transient network errors** just log and are retried on the next scheduled
  tick; a single failure does not alarm.
- The fetch-failure counter resets on the next successful fetch.

## Testing

- **`evaluator`** (unit): every transition path — unavailable→available alerts;
  available→available stays quiet; cooldown suppresses; sell-out→reappear
  re-arms; failure does not count as availability.
- **`ra_client`** (against fixtures): recorded JSON samples of real RA responses
  for both an available and a sold-out event; assert correct parsing.
- **`notifier`** (fake/mock): assert the correct Signal payload/command.
- **End-to-end smoke:** one test against a fake RA server returning canned
  responses, exercising a full `rabot check` cycle through a fake notifier.

## Stack

- Python 3.12
- `httpx` (HTTP/GraphQL requests)
- `pytest` (tests)
- Nix flake: `buildPythonApplication` with deps from nixpkgs (no
  poetry2nix/uv2nix), `nixosModules.default`, `devShell`
- `signal-cli` (native, from nixpkgs or Homebrew) — external runtime dependency
- No database; JSON state file only

## Deliverable

A Python one-shot CLI **+** a Nix flake (package + NixOS module) **+** an example
macOS `launchd` plist **+** a setup README.

## Out of scope (YAGNI)

- Watching multiple events / a watchlist.
- Channels other than Signal.
- A long-running daemon (only needed for sub-30s polling).
- Auto-purchasing tickets.
- A web UI or dashboard.
