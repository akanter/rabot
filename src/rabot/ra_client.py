from dataclasses import dataclass

import httpx

GET_EVENT_TICKETING_QUERY = (
    "query GetEventTicketing($id: ID!) { "
    "event(id: $id) { id title ticketing { isAnyTicketTierAvailable ticketStatus } } }"
)

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer": "https://ra.co/events",
}


@dataclass
class FetchResult:
    ok: bool
    available: bool = False
    event_title: str | None = None
    error: str | None = None
    # HTTP status of the GraphQL response: 200 on success or graphql-errors,
    # the code (e.g. 429/403) on an HTTP error, None on a network/transport error.
    # This is the rate-limit/block signal: 429 = throttled, 403 = blocked.
    status_code: int | None = None


def _event(payload: dict) -> dict:
    return (payload.get("data") or {}).get("event") or {}


def parse_availability(payload: dict) -> bool:
    ticketing = _event(payload).get("ticketing") or {}
    return bool(ticketing.get("isAnyTicketTierAvailable"))


def parse_title(payload: dict) -> str | None:
    return _event(payload).get("title")


def fetch(event_id: str, graphql_endpoint: str,
          client: httpx.Client | None = None) -> FetchResult:
    body = {
        "operationName": "GetEventTicketing",
        "variables": {"id": event_id},
        "query": GET_EVENT_TICKETING_QUERY,
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.post(graphql_endpoint, json=body, headers=_HEADERS)
        if resp.status_code != 200:
            return FetchResult(ok=False, status_code=resp.status_code,
                               error=f"HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        if payload.get("errors"):
            return FetchResult(ok=False, status_code=200,
                               error=f"graphql errors: {payload['errors']}")
        return FetchResult(ok=True, status_code=200,
                           available=parse_availability(payload),
                           event_title=parse_title(payload))
    except httpx.HTTPError as exc:
        return FetchResult(ok=False, error=f"request failed: {exc}")
    except (ValueError, KeyError) as exc:  # JSONDecodeError <: ValueError → covers 200-with-non-JSON body
        return FetchResult(ok=False, status_code=200, error=f"parse failed: {exc}")
    finally:
        if owns_client:
            client.close()
