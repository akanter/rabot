import json
from pathlib import Path

import httpx

from rabot.ra_client import (
    parse_availability, parse_title, parse_available_tiers, fetch,
)

FIXTURES = Path(__file__).parent / "fixtures"
ENDPOINT = "https://ra.co/graphql"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


# ---- parsing: the two ticketing systems ----

def test_v2_available_via_isAnyTicketTierAvailable():
    payload = _load("v2_available.json")   # Waterworks, ENTIRE system
    assert parse_availability(payload) is True
    assert parse_available_tiers(payload) == ()   # V2 exposes no per-tier names to us


def test_legacy_soldout_is_not_available():
    payload = _load("legacy_soldout.json")  # Houghton, all festival tiers SOLDOUT
    assert parse_availability(payload) is False
    assert parse_available_tiers(payload) == ()


def test_legacy_available_when_a_tier_is_valid():
    payload = _load("legacy_available.json")  # Tier 1 flipped VALID (resale)
    assert parse_availability(payload) is True
    assert parse_available_tiers(payload) == ("Tier 1",)


def test_addons_do_not_count_as_available():
    # a VALID tier that is an add-on must NOT make the event "available"
    payload = {"data": {"event": {
        "title": "X", "ticketing": {"isAnyTicketTierAvailable": False},
        "tickets": [
            {"title": "Car Park", "validType": "VALID", "isAddOn": True},
            {"title": "Tier 1", "validType": "SOLDOUT", "isAddOn": False},
        ]}}}
    assert parse_availability(payload) is False
    assert parse_available_tiers(payload) == ()


def test_parse_title():
    assert parse_title(_load("v2_available.json")) == "Waterworks Extended 2026"


# ---- fetch ----

def test_fetch_legacy_available_names_tiers():
    payload = _load("legacy_available.json")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        result = fetch("2287366", ENDPOINT, client=client)
    assert result.ok and result.available is True
    assert result.available_tiers == ("Tier 1",)
    assert result.status_code == 200


def test_fetch_soldout():
    payload = _load("legacy_soldout.json")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        result = fetch("2287366", ENDPOINT, client=client)
    assert result.ok is True and result.available is False


def test_fetch_sends_expected_graphql_body():
    seen = {}

    def handler(req):
        seen["json"] = json.loads(req.content)
        seen["headers"] = req.headers
        return httpx.Response(200, json=_load("legacy_soldout.json"))

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        fetch("2287366", ENDPOINT, client=client)
    assert seen["json"]["variables"] == {"id": "2287366"}
    assert "isAnyTicketTierAvailable" in seen["json"]["query"]
    assert "validType" in seen["json"]["query"]
    assert seen["headers"]["referer"] == "https://ra.co/events"


def test_fetch_http_error_captures_status_code():
    transport = httpx.MockTransport(lambda req: httpx.Response(429, text="slow down"))
    with httpx.Client(transport=transport) as client:
        result = fetch("1", ENDPOINT, client=client)
    assert result.ok is False and result.available is False
    assert result.status_code == 429
    assert result.error and "429" in result.error


def test_fetch_graphql_errors_returns_not_ok():
    body = {"errors": [{"message": "unauthorized"}], "data": None}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        result = fetch("1", ENDPOINT, client=client)
    assert result.ok is False and result.error and "unauthorized" in result.error


def test_fetch_network_error_no_status():
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    transport = httpx.MockTransport(boom)
    with httpx.Client(transport=transport) as client:
        result = fetch("1", ENDPOINT, client=client)
    assert result.ok is False and result.error and result.status_code is None
