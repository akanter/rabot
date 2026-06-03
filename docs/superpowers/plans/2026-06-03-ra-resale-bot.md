# RA Resale Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A portable Python one-shot CLI (`rabot check`) that polls a single sold-out RA event and sends a Signal message when a ticket tier flips from unavailable → available, packaged as a Nix flake with a NixOS module.

**Architecture:** A scheduler-agnostic one-shot core. Each `rabot check` invocation does one cycle (load config → load JSON state → fetch RA availability → evaluate transition → maybe notify via signal-cli → write state → exit). An external scheduler (NixOS systemd timer, macOS launchd, or cron) drives the interval. All cross-cycle state lives in a JSON file, so the process is crash-safe and needs no daemon.

**Tech Stack:** Python 3.12, `httpx`, `pytest`, native `signal-cli` (shelled out), Nix flake (`buildPythonApplication` + `nixosModules.default` + `devShell`).

---

## File Structure

```
rabot/
  pyproject.toml                  # package metadata, deps, console_scripts entry
  flake.nix                       # package + NixOS module + devShell
  README.md                       # setup: signal-cli link, NixOS module, macOS launchd
  docs/ra-api-notes.md            # captured RA GraphQL query + field findings (Task 2)
  examples/
    com.rabot.check.plist         # macOS launchd example
  src/rabot/
    __init__.py
    config.py                     # Config dataclass + load_config(env)
    state.py                      # State dataclass + load_state/save_state (atomic JSON)
    ra_client.py                  # TicketTier, FetchResult, parse_tickets, fetch
    evaluator.py                  # Action, Decision, evaluate() — pure logic
    notifier.py                   # SignalNotifier (shells out to signal-cli)
    cli.py                        # `rabot check` wiring + argparse main()
  tests/
    conftest.py
    fixtures/
      tickets_available.json      # real RA response, available (Task 2)
      tickets_soldout.json        # real RA response, sold out (Task 2)
    test_config.py
    test_state.py
    test_ra_client.py
    test_evaluator.py
    test_notifier.py
    test_smoke.py                 # end-to-end with fake RA server + fake notifier
```

**Types defined once, used everywhere (keep names exact):**
- `TicketTier(title: str, available: bool, price: str | None)`
- `FetchResult(ok: bool, tiers: list[TicketTier], error: str | None)` with `.any_available` property
- `State(last_available: bool, last_alert_ts: float | None, consecutive_failures: int, blind_alerted: bool)`
- `Action` enum: `NONE`, `ALERT_AVAILABLE`, `ALERT_BLIND`
- `Decision(action: Action, message: str | None)`
- `Config(event_url, signal_sender, signal_recipient, state_path, cooldown_seconds, failure_threshold, graphql_endpoint, signal_cli_path)` with `.event_id` property

---

## Task 1: Project scaffold + green test harness

**Files:**
- Create: `pyproject.toml`, `src/rabot/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py` (placeholder)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "rabot"
version = "0.1.0"
description = "Notify via Signal when RA resale tickets appear"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
rabot = "rabot.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package + a trivial passing test**

`src/rabot/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/test_smoke.py`:
```python
def test_harness_runs():
    assert True
```

- [ ] **Step 3: Set up venv and run the harness**

Run:
```bash
python3.12 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && pytest -q
```
Expected: 1 passed.

- [ ] **Step 4: Add `.gitignore` and commit**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
result
```

```bash
git add pyproject.toml src tests .gitignore
git commit -m "chore: project scaffold with green test harness"
```

---

## Task 2: Discovery spike — capture RA ticket query + fixtures

This is a **manual reverse-engineering task**. No code logic is guessed; you capture the real request/response and record findings. Everything downstream is TDD'd against these fixtures.

**Files:**
- Create: `docs/ra-api-notes.md`, `tests/fixtures/tickets_available.json`, `tests/fixtures/tickets_soldout.json`

- [ ] **Step 1: Capture the live ticket request**

In a desktop browser, open an RA event page that is **currently on sale / has tickets** (e.g. any `https://ra.co/events/<id>`). Open DevTools → Network → filter `graphql`. Reload. Find the POST to `https://ra.co/graphql` whose response contains ticket/price data. Copy as:
- the request payload (`operationName`, `variables`, full `query` string)
- the full JSON response

- [ ] **Step 2: Save the available fixture**

Save the response JSON verbatim to `tests/fixtures/tickets_available.json`.

- [ ] **Step 3: Capture and save a sold-out fixture**

Repeat Step 1 on a **sold-out** event and save its response to `tests/fixtures/tickets_soldout.json`.

- [ ] **Step 4: Diff the two fixtures to find the availability signal**

Compare the per-ticket objects in both fixtures. Identify:
- the JSON path to the ticket list (expected: `data.event.tickets`, confirm)
- the field name(s) for ticket title and price (expected: `title`, `priceRetail`, confirm)
- the field(s) that differ between available and sold-out (the availability discriminator)

- [ ] **Step 5: Record findings**

Write `docs/ra-api-notes.md` with: endpoint, required headers (`Referer`, `User-Agent`, `Content-Type: application/json`), the exact `operationName` + `query` string, the `variables` shape (event id goes where), the response path to tickets, and the exact availability discriminator field + values. This file is the source of truth for Task 5.

- [ ] **Step 6: Commit**

```bash
git add docs/ra-api-notes.md tests/fixtures
git commit -m "spike: capture RA ticket GraphQL query and available/sold-out fixtures"
```

---

## Task 3: Config

**Files:**
- Create: `src/rabot/config.py`, `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`:
```python
import pytest
from rabot.config import load_config, Config

BASE_ENV = {
    "RABOT_EVENT_URL": "https://ra.co/events/1234567",
    "RABOT_SIGNAL_SENDER": "+15550000001",
    "RABOT_SIGNAL_RECIPIENT": "+15550000002",
}

def test_loads_required_and_defaults():
    cfg = load_config(BASE_ENV)
    assert cfg.event_url == "https://ra.co/events/1234567"
    assert cfg.signal_sender == "+15550000001"
    assert cfg.cooldown_seconds == 900
    assert cfg.failure_threshold == 5
    assert cfg.graphql_endpoint == "https://ra.co/graphql"
    assert cfg.signal_cli_path == "signal-cli"

def test_event_id_extracted_from_url():
    assert load_config(BASE_ENV).event_id == "1234567"

def test_missing_required_raises():
    with pytest.raises(ValueError, match="RABOT_EVENT_URL"):
        load_config({})

def test_bad_event_url_raises_on_id_access():
    cfg = Config(event_url="https://ra.co/nope", signal_sender="+1",
                 signal_recipient="+2", state_path="/tmp/s.json")
    with pytest.raises(ValueError, match="event id"):
        _ = cfg.event_id

def test_overrides_from_env():
    env = {**BASE_ENV, "RABOT_COOLDOWN_SECONDS": "60", "RABOT_FAILURE_THRESHOLD": "3"}
    cfg = load_config(env)
    assert cfg.cooldown_seconds == 60 and cfg.failure_threshold == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py -q`
Expected: FAIL (`ModuleNotFoundError: rabot.config`).

- [ ] **Step 3: Implement `config.py`**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_config.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rabot/config.py tests/test_config.py
git commit -m "feat: config loading from env with event-id extraction"
```

---

## Task 4: State store (atomic JSON)

**Files:**
- Create: `src/rabot/state.py`, `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

`tests/test_state.py`:
```python
from rabot.state import State, load_state, save_state


def test_load_missing_returns_defaults(tmp_path):
    state = load_state(str(tmp_path / "nope.json"))
    assert state == State()
    assert state.last_available is False
    assert state.consecutive_failures == 0


def test_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(path, State(last_available=True, last_alert_ts=123.0,
                           consecutive_failures=2, blind_alerted=True))
    loaded = load_state(path)
    assert loaded == State(last_available=True, last_alert_ts=123.0,
                           consecutive_failures=2, blind_alerted=True)


def test_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert load_state(str(path)) == State()


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "state.json")
    save_state(path, State(last_available=True))
    assert load_state(path).last_available is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_state.py -q`
Expected: FAIL (`ModuleNotFoundError: rabot.state`).

- [ ] **Step 3: Implement `state.py`**

```python
from dataclasses import dataclass, asdict, fields
import json
import os


@dataclass
class State:
    last_available: bool = False
    last_alert_ts: float | None = None
    consecutive_failures: int = 0
    blind_alerted: bool = False


def load_state(path: str) -> State:
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return State()
    known = {f.name for f in fields(State)}
    return State(**{k: v for k, v in data.items() if k in known})


def save_state(path: str, state: State) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(asdict(state), handle)
    os.replace(tmp, path)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_state.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rabot/state.py tests/test_state.py
git commit -m "feat: atomic JSON state store"
```

---

## Task 5: RA client (parse + fetch)

Uses the fixtures and findings from Task 2. **Before writing code, open `docs/ra-api-notes.md` and adjust the three marked constants/branches in `ra_client.py` to match what you captured.**

**Files:**
- Create: `src/rabot/ra_client.py`, `tests/test_ra_client.py`

- [ ] **Step 1: Write failing tests against the real fixtures**

`tests/test_ra_client.py`:
```python
import json
from pathlib import Path

import httpx
import pytest

from rabot.config import Config
from rabot.ra_client import TicketTier, FetchResult, parse_tickets, fetch

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_available_has_a_buyable_tier():
    tiers = parse_tickets(_load("tickets_available.json"))
    assert tiers, "expected at least one tier"
    assert any(t.available for t in tiers)
    assert all(isinstance(t, TicketTier) for t in tiers)


def test_parse_soldout_has_no_buyable_tier():
    tiers = parse_tickets(_load("tickets_soldout.json"))
    assert not any(t.available for t in tiers)


def test_fetchresult_any_available():
    assert FetchResult(True, [TicketTier("GA", True, "10")], None).any_available
    assert not FetchResult(True, [TicketTier("GA", False, "10")], None).any_available


def test_fetch_ok_with_mock_transport():
    payload = _load("tickets_available.json")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path="/tmp/s.json")
    with httpx.Client(transport=transport) as client:
        result = fetch(cfg, client=client)
    assert result.ok and result.any_available and result.error is None


def test_fetch_http_error_returns_not_ok():
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="nope"))
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path="/tmp/s.json")
    with httpx.Client(transport=transport) as client:
        result = fetch(cfg, client=client)
    assert result.ok is False
    assert result.tiers == []
    assert result.error and "503" in result.error


def test_fetch_network_error_returns_not_ok():
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    transport = httpx.MockTransport(boom)
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path="/tmp/s.json")
    with httpx.Client(transport=transport) as client:
        result = fetch(cfg, client=client)
    assert result.ok is False and result.error
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ra_client.py -q`
Expected: FAIL (`ModuleNotFoundError: rabot.ra_client`).

- [ ] **Step 3: Implement `ra_client.py`** (adjust the 3 marked spots to match Task 2 findings)

```python
from dataclasses import dataclass, field
import httpx

# --- Adjust these THREE things to match docs/ra-api-notes.md (Task 2) ---
# (1) The exact query string captured from the network tab:
GET_EVENT_TICKETS_QUERY = """query GET_EVENT_TICKETS($id: ID!) {
  event(id: $id) {
    id
    tickets {
      id
      title
      priceRetail
      onSaleFrom
      isAddOn
      validType
    }
  }
}"""


def _tickets_path(payload: dict) -> list[dict]:
    # (2) Path to the ticket list in the response:
    return ((payload.get("data") or {}).get("event") or {}).get("tickets") or []


def _is_available(ticket: dict) -> bool:
    # (3) Availability discriminator found by diffing the two fixtures.
    #     Replace this with the real signal. Example placeholder logic:
    return bool(ticket.get("onSaleFrom")) and not ticket.get("isSoldOut", False)
# -----------------------------------------------------------------------

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer": "https://ra.co/events",
}


@dataclass
class TicketTier:
    title: str
    available: bool
    price: str | None = None


@dataclass
class FetchResult:
    ok: bool
    tiers: list[TicketTier] = field(default_factory=list)
    error: str | None = None

    @property
    def any_available(self) -> bool:
        return any(t.available for t in self.tiers)


def parse_tickets(payload: dict) -> list[TicketTier]:
    return [
        TicketTier(
            title=t.get("title", "Ticket"),
            available=_is_available(t),
            price=t.get("priceRetail"),
        )
        for t in _tickets_path(payload)
    ]


def fetch(config, client: httpx.Client | None = None) -> FetchResult:
    body = {
        "operationName": "GET_EVENT_TICKETS",
        "variables": {"id": config.event_id},
        "query": GET_EVENT_TICKETS_QUERY,
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.post(config.graphql_endpoint, json=body, headers=_HEADERS)
        if resp.status_code != 200:
            return FetchResult(ok=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
        return FetchResult(ok=True, tiers=parse_tickets(resp.json()))
    except httpx.HTTPError as exc:
        return FetchResult(ok=False, error=f"request failed: {exc}")
    except (ValueError, KeyError) as exc:
        return FetchResult(ok=False, error=f"parse failed: {exc}")
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ra_client.py -q`
Expected: all passed. If `test_parse_available_has_a_buyable_tier` or the sold-out test fails, your `_is_available` does not yet match reality — fix it against the fixtures (this is the intended TDD loop for the spike data).

- [ ] **Step 5: Commit**

```bash
git add src/rabot/ra_client.py tests/test_ra_client.py
git commit -m "feat: RA GraphQL client with fixture-driven ticket parsing"
```

---

## Task 6: Evaluator (pure transition logic)

**Files:**
- Create: `src/rabot/evaluator.py`, `tests/test_evaluator.py`

- [ ] **Step 1: Write failing tests**

`tests/test_evaluator.py`:
```python
from rabot.evaluator import evaluate, Action
from rabot.ra_client import FetchResult, TicketTier
from rabot.state import State

URL = "https://ra.co/events/1234567"
KW = dict(cooldown_seconds=900, failure_threshold=3, event_url=URL)


def ok(available):
    return FetchResult(True, [TicketTier("GA", available, "10")], None)


def fail():
    return FetchResult(False, [], "boom")


def test_transition_unavailable_to_available_alerts():
    decision, new = evaluate(ok(True), State(last_available=False), now=1000.0, **KW)
    assert decision.action is Action.ALERT_AVAILABLE
    assert "ra.co/events/1234567" in decision.message
    assert new.last_available is True and new.last_alert_ts == 1000.0


def test_stays_quiet_while_available():
    decision, new = evaluate(ok(True), State(last_available=True, last_alert_ts=500.0),
                             now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.last_available is True


def test_cooldown_suppresses_reflicker():
    state = State(last_available=False, last_alert_ts=900.0)
    decision, new = evaluate(ok(True), state, now=1000.0, **KW)  # 100s < 900s cooldown
    assert decision.action is Action.NONE
    assert new.last_available is True
    assert new.last_alert_ts == 900.0  # unchanged


def test_rearm_after_cooldown_elapsed():
    state = State(last_available=False, last_alert_ts=10.0)
    decision, new = evaluate(ok(True), state, now=1000.0, **KW)  # 990s > 900s
    assert decision.action is Action.ALERT_AVAILABLE
    assert new.last_alert_ts == 1000.0


def test_available_to_unavailable_resets_flag_quietly():
    decision, new = evaluate(ok(False), State(last_available=True), now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.last_available is False


def test_failure_does_not_count_as_availability():
    decision, new = evaluate(fail(), State(last_available=False), now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.consecutive_failures == 1
    assert new.last_available is False


def test_blind_alert_fires_once_at_threshold():
    state = State(consecutive_failures=2)  # threshold is 3
    decision, new = evaluate(fail(), state, now=1000.0, **KW)
    assert decision.action is Action.ALERT_BLIND
    assert new.consecutive_failures == 3 and new.blind_alerted is True


def test_blind_alert_does_not_repeat():
    state = State(consecutive_failures=5, blind_alerted=True)
    decision, new = evaluate(fail(), state, now=1000.0, **KW)
    assert decision.action is Action.NONE
    assert new.consecutive_failures == 6


def test_success_resets_failure_counter_and_blind_flag():
    state = State(consecutive_failures=5, blind_alerted=True, last_available=False)
    decision, new = evaluate(ok(False), state, now=1000.0, **KW)
    assert new.consecutive_failures == 0 and new.blind_alerted is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_evaluator.py -q`
Expected: FAIL (`ModuleNotFoundError: rabot.evaluator`).

- [ ] **Step 3: Implement `evaluator.py`**

```python
from dataclasses import dataclass, replace
from enum import Enum

from rabot.ra_client import FetchResult
from rabot.state import State


class Action(Enum):
    NONE = "none"
    ALERT_AVAILABLE = "alert_available"
    ALERT_BLIND = "alert_blind"


@dataclass
class Decision:
    action: Action
    message: str | None = None


def evaluate(result: FetchResult, state: State, *, now: float,
             cooldown_seconds: int, failure_threshold: int,
             event_url: str) -> tuple[Decision, State]:
    if not result.ok:
        failures = state.consecutive_failures + 1
        new = replace(state, consecutive_failures=failures)
        if failures >= failure_threshold and not state.blind_alerted:
            new = replace(new, blind_alerted=True)
            msg = (f"⚠️ rabot can't check {event_url} "
                   f"({failures} consecutive failures): {result.error}")
            return Decision(Action.ALERT_BLIND, msg), new
        return Decision(Action.NONE), new

    new = replace(state, consecutive_failures=0, blind_alerted=False)
    available = result.any_available

    if available and not state.last_available:
        within_cooldown = (state.last_alert_ts is not None
                           and (now - state.last_alert_ts) < cooldown_seconds)
        if within_cooldown:
            return Decision(Action.NONE), replace(new, last_available=True)
        tiers = ", ".join(t.title for t in result.tiers if t.available)
        msg = f"\U0001f3ab Tickets available for {event_url}: {tiers}"
        return Decision(Action.ALERT_AVAILABLE, msg), replace(
            new, last_available=True, last_alert_ts=now)

    return Decision(Action.NONE), replace(new, last_available=available)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_evaluator.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rabot/evaluator.py tests/test_evaluator.py
git commit -m "feat: pure evaluator with transition, cooldown, re-arm, blind-alert logic"
```

---

## Task 7: Notifier (signal-cli)

**Files:**
- Create: `src/rabot/notifier.py`, `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

`tests/test_notifier.py`:
```python
import subprocess

import pytest

from rabot.notifier import SignalNotifier


def test_builds_correct_signal_cli_command(monkeypatch):
    captured = {}

    def fake_run(cmd, check, capture_output, text):
        captured["cmd"] = cmd
        captured["check"] = check
        class R: returncode = 0; stderr = ""
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    SignalNotifier("signal-cli", "+15550000001", "+15550000002").send("hello")

    assert captured["cmd"] == [
        "signal-cli", "-u", "+15550000001", "send", "-m", "hello", "+15550000002"
    ]
    assert captured["check"] is True


def test_send_raises_on_failure(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, stderr="link expired")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        SignalNotifier("signal-cli", "+1", "+2").send("hi")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_notifier.py -q`
Expected: FAIL (`ModuleNotFoundError: rabot.notifier`).

- [ ] **Step 3: Implement `notifier.py`**

```python
import subprocess


class SignalNotifier:
    def __init__(self, signal_cli_path: str, sender: str, recipient: str):
        self.signal_cli_path = signal_cli_path
        self.sender = sender
        self.recipient = recipient

    def send(self, message: str) -> None:
        subprocess.run(
            [self.signal_cli_path, "-u", self.sender, "send", "-m", message, self.recipient],
            check=True,
            capture_output=True,
            text=True,
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_notifier.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rabot/notifier.py tests/test_notifier.py
git commit -m "feat: signal-cli notifier"
```

---

## Task 8: CLI wiring (`rabot check`)

**Files:**
- Create: `src/rabot/cli.py`
- Modify: `tests/test_smoke.py` (replace placeholder in Task 9)

- [ ] **Step 1: Write failing test**

Add to `tests/test_cli.py` (create):
```python
import time

import rabot.cli as cli
from rabot.ra_client import FetchResult, TicketTier
from rabot.config import Config
from rabot.state import State, load_state


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_run_check_alerts_and_persists(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch",
                        lambda c, client=None: FetchResult(True, [TicketTier("GA", True, "10")], None))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda c: notifier)

    cli.run_check()

    assert len(notifier.messages) == 1
    assert load_state(state_path).last_available is True


def test_run_check_no_alert_when_unavailable(tmp_path, monkeypatch):
    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "fetch",
                        lambda c, client=None: FetchResult(True, [TicketTier("GA", False, "10")], None))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda c: notifier)

    cli.run_check()

    assert notifier.messages == []
    assert load_state(state_path).last_available is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_cli.py -q`
Expected: FAIL (`ModuleNotFoundError: rabot.cli`).

- [ ] **Step 3: Implement `cli.py`**

```python
import argparse
import sys
import time

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
        build_notifier(config).send(decision.message)
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_cli.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rabot/cli.py tests/test_cli.py
git commit -m "feat: rabot check CLI wiring"
```

---

## Task 9: End-to-end smoke test

**Files:**
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Replace the placeholder smoke test**

`tests/test_smoke.py`:
```python
import json
from pathlib import Path

import httpx

import rabot.cli as cli
from rabot.config import Config
from rabot.notifier import SignalNotifier
from rabot.ra_client import fetch
from rabot.state import load_state

FIXTURES = Path(__file__).parent / "fixtures"


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_full_cycle_available_sends_alert(tmp_path, monkeypatch):
    payload = json.loads((FIXTURES / "tickets_available.json").read_text())
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))

    state_path = str(tmp_path / "state.json")
    cfg = Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                 signal_recipient="+2", state_path=state_path)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(
        cli, "fetch",
        lambda c, client=None: fetch(c, client=httpx.Client(transport=transport)))
    notifier = FakeNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda c: notifier)

    cli.run_check()

    assert len(notifier.messages) == 1
    assert "ra.co/events/1234567" in notifier.messages[0]
    assert load_state(state_path).last_available is True
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: end-to-end smoke through full check cycle"
```

---

## Task 10: Nix flake (package + NixOS module + devShell)

**Files:**
- Create: `flake.nix`

- [ ] **Step 1: Write `flake.nix`**

```nix
{
  description = "rabot - notify via Signal when RA resale tickets appear";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f nixpkgs.legacyPackages.${s});
    in
    {
      packages = forAll (pkgs: {
        default = pkgs.python312Packages.buildPythonApplication {
          pname = "rabot";
          version = "0.1.0";
          src = ./.;
          format = "pyproject";
          nativeBuildInputs = [ pkgs.python312Packages.setuptools ];
          propagatedBuildInputs = [ pkgs.python312Packages.httpx ];
          nativeCheckInputs = [ pkgs.python312Packages.pytest ];
          # signal-cli is a runtime dependency invoked via PATH; provided by the
          # NixOS module's service environment, not baked into the app closure.
        };
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python312.withPackages (ps: [ ps.httpx ps.pytest ]))
            pkgs.signal-cli
          ];
        };
      });

      nixosModules.default = { config, lib, pkgs, ... }:
        let cfg = config.services.rabot;
        in {
          options.services.rabot = {
            enable = lib.mkEnableOption "rabot RA resale ticket watcher";
            eventUrl = lib.mkOption { type = lib.types.str; };
            signalSender = lib.mkOption { type = lib.types.str; };
            signalRecipient = lib.mkOption { type = lib.types.str; };
            interval = lib.mkOption { type = lib.types.str; default = "60s"; };
            cooldownSeconds = lib.mkOption { type = lib.types.int; default = 900; };
            failureThreshold = lib.mkOption { type = lib.types.int; default = 5; };
          };
          config = lib.mkIf cfg.enable {
            systemd.services.rabot = {
              description = "rabot RA resale check";
              path = [ pkgs.signal-cli ];
              serviceConfig = {
                Type = "oneshot";
                DynamicUser = true;
                StateDirectory = "rabot";
                ExecStart = "${self.packages.${pkgs.system}.default}/bin/rabot check";
                Environment = [
                  "RABOT_EVENT_URL=${cfg.eventUrl}"
                  "RABOT_SIGNAL_SENDER=${cfg.signalSender}"
                  "RABOT_SIGNAL_RECIPIENT=${cfg.signalRecipient}"
                  "RABOT_STATE_PATH=/var/lib/rabot/state.json"
                  "RABOT_COOLDOWN_SECONDS=${toString cfg.cooldownSeconds}"
                  "RABOT_FAILURE_THRESHOLD=${toString cfg.failureThreshold}"
                ];
              };
            };
            systemd.timers.rabot = {
              wantedBy = [ "timers.target" ];
              timerConfig = {
                OnBootSec = cfg.interval;
                OnUnitActiveSec = cfg.interval;
                RandomizedDelaySec = "15s";
              };
            };
          };
        };
    };
}
```

- [ ] **Step 2: Build the package**

Run: `nix build .#default 2>&1 | tail -20`
Expected: build succeeds; tests run during build and pass; `result/bin/rabot` exists.

- [ ] **Step 3: Verify the built CLI and devShell**

Run: `./result/bin/rabot --help`
Expected: usage text showing the `check` subcommand.

Run: `nix develop -c pytest -q`
Expected: full suite passes inside the dev shell.

- [ ] **Step 4: Commit**

```bash
git add flake.nix
git commit -m "build: nix flake with package, NixOS module, and devShell"
```

---

## Task 11: macOS launchd example + README

**Files:**
- Create: `examples/com.rabot.check.plist`, `README.md`

- [ ] **Step 1: Write the launchd example**

`examples/com.rabot.check.plist` (placeholders the user edits are clearly marked):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.rabot.check</string>
  <key>ProgramArguments</key>
  <array>
    <string>/ABSOLUTE/PATH/TO/rabot</string>
    <string>check</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RABOT_EVENT_URL</key><string>https://ra.co/events/REPLACE_ID</string>
    <key>RABOT_SIGNAL_SENDER</key><string>+10000000000</string>
    <key>RABOT_SIGNAL_RECIPIENT</key><string>+10000000001</string>
    <key>RABOT_STATE_PATH</key><string>/Users/YOU/Library/Application Support/rabot/state.json</string>
    <key>PATH</key><string>/run/current-system/sw/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>/tmp/rabot.err.log</string>
  <key>StandardOutPath</key><string>/tmp/rabot.out.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Write `README.md`**

Cover, in order:
1. What it does (one-shot RA resale watcher → Signal).
2. **One-time signal-cli linking:** install (`nix profile install nixpkgs#signal-cli` or `brew install signal-cli`), then `signal-cli link -n "rabot"` and scan the QR from Signal app → Linked devices. Note the linked number becomes `RABOT_SIGNAL_SENDER`.
3. **NixOS deploy:** add the flake to inputs, import `nixosModules.default`, set `services.rabot.{enable, eventUrl, signalSender, signalRecipient, interval}`, `nixos-rebuild switch`. Logs: `journalctl -u rabot`.
4. **macOS deploy:** `nix build`, copy `result/bin/rabot` path into the plist, edit env vars, `cp examples/com.rabot.check.plist ~/Library/LaunchAgents/`, `launchctl load` it. Logs: `/tmp/rabot.*.log`.
5. **Config reference:** table of all `RABOT_*` env vars with defaults (mirror `config.py`).
6. **Tuning note:** default 60s interval; lower with care (RA may rate-limit; blind-alert will warn you after `RABOT_FAILURE_THRESHOLD` consecutive failures).

- [ ] **Step 3: Commit**

```bash
git add examples/com.rabot.check.plist README.md
git commit -m "docs: README and macOS launchd example"
```

---

## Self-Review Notes

**Spec coverage:** channel=Signal (Tasks 7, 11) ✓; one event (config event_id) ✓; resale unavailable→available trigger (Task 6) ✓; configurable cadence (NixOS `interval` / launchd `StartInterval`) ✓; once-per-transition + cooldown + re-arm (Task 6 tests) ✓; Python one-shot CLI (Task 8) ✓; Nix flake + NixOS module (Task 10) ✓; macOS launchd (Task 11) ✓; silent-failure handling / "couldn't check" ≠ "unavailable" + blind alert (Tasks 5, 6) ✓; testing strategy — evaluator units, ra_client fixtures, notifier fake, e2e smoke (Tasks 5,6,7,9) ✓.

**Known dependency:** Tasks 5, 9 depend on the Task 2 spike fixtures. The three marked spots in `ra_client.py` (query string, ticket path, availability discriminator) are filled from `docs/ra-api-notes.md`. This is the one place a human/agent must inspect live RA output rather than copy code — by design, since RA's ticket schema is not publicly documented.

**Type consistency:** `FetchResult`, `TicketTier`, `State`, `Action`, `Decision`, `Config` signatures are identical across Tasks 3–9. `build_notifier`/`fetch`/`load_config` are the three seams monkeypatched in CLI tests and they match `cli.py`.
