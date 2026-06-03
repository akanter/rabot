import json
from pathlib import Path

import httpx

from rabot.config import Config
from rabot.ra_client import FetchResult, parse_availability, parse_title, fetch

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _cfg():
    return Config(event_url="https://ra.co/events/1234567", signal_sender="+1",
                  signal_recipient="+2", state_path="/tmp/s.json")


def test_parse_available_fixture_is_available():
    assert parse_availability(_load("tickets_available.json")) is True


def test_parse_soldout_fixture_is_not_available():
    assert parse_availability(_load("tickets_soldout.json")) is False


def test_parse_title():
    assert parse_title(_load("tickets_available.json")) == "Waterworks Extended 2026"


def test_fetch_ok_available():
    payload = _load("tickets_available.json")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        result = fetch(_cfg(), client=client)
    assert result.ok is True
    assert result.available is True
    assert result.event_title == "Waterworks Extended 2026"
    assert result.error is None


def test_fetch_ok_soldout():
    payload = _load("tickets_soldout.json")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        result = fetch(_cfg(), client=client)
    assert result.ok is True and result.available is False


def test_fetch_sends_expected_graphql_body():
    seen = {}

    def handler(req):
        seen["json"] = json.loads(req.content)
        seen["headers"] = req.headers
        return httpx.Response(200, json=_load("tickets_available.json"))

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        fetch(_cfg(), client=client)
    assert seen["json"]["variables"] == {"id": "1234567"}
    assert "isAnyTicketTierAvailable" in seen["json"]["query"]
    assert seen["headers"]["referer"] == "https://ra.co/events"


def test_fetch_http_error_returns_not_ok():
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="nope"))
    with httpx.Client(transport=transport) as client:
        result = fetch(_cfg(), client=client)
    assert result.ok is False
    assert result.available is False
    assert result.error and "503" in result.error


def test_fetch_graphql_errors_returns_not_ok():
    body = {"errors": [{"message": "unauthorized"}], "data": None}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        result = fetch(_cfg(), client=client)
    assert result.ok is False and result.available is False
    assert result.error and "unauthorized" in result.error


def test_fetch_network_error_returns_not_ok():
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    transport = httpx.MockTransport(boom)
    with httpx.Client(transport=transport) as client:
        result = fetch(_cfg(), client=client)
    assert result.ok is False and result.error
