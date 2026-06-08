from dataclasses import dataclass, field

import httpx

# RA has two ticketing systems and the availability signal differs:
#   - LEGACY events: per-tier `tickets[].validType` ("VALID" == buyable). The V2
#     `isAnyTicketTierAvailable` is structurally false for these, so we must read
#     the tier list. Add-ons (parking/vehicle passes) are excluded via
#     ticketTierType: TICKETS and an isAddOn guard.
#   - ENTIRE/V2 events: `ticketing.isAnyTicketTierAvailable`; the legacy tickets
#     list is empty.
# We read both and treat available as either signal firing.
GET_EVENT_AVAILABILITY_QUERY = (
    "query GetEventAvailability($id: ID!) { "
    "event(id: $id) { id title ticketingSystem "
    "ticketing { isAnyTicketTierAvailable } "
    "tickets(queryType: AVAILABLE, ticketTierType: TICKETS) { title validType isAddOn } } }"
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
    available_tiers: tuple[str, ...] = ()   # named tiers buyable (legacy); empty for V2
    error: str | None = None
    # 200 on success/graphql-errors, the code (429/403/…) on HTTP error, None on
    # transport error. The rate-limit/block signal.
    status_code: int | None = None


def _event(payload: dict) -> dict:
    return (payload.get("data") or {}).get("event") or {}


def _tier_is_available(ticket: dict) -> bool:
    return ticket.get("validType") == "VALID" and not ticket.get("isAddOn")


def parse_available_tiers(payload: dict) -> tuple[str, ...]:
    return tuple(
        (t.get("title") or "ticket")
        for t in (_event(payload).get("tickets") or [])
        if _tier_is_available(t)
    )


def parse_availability(payload: dict) -> bool:
    event = _event(payload)
    if (event.get("ticketing") or {}).get("isAnyTicketTierAvailable"):
        return True  # V2 / ENTIRE ticketing
    return any(_tier_is_available(t) for t in (event.get("tickets") or []))  # legacy


def parse_title(payload: dict) -> str | None:
    return _event(payload).get("title")


def fetch(event_id: str, graphql_endpoint: str,
          client: httpx.Client | None = None) -> FetchResult:
    body = {
        "operationName": "GetEventAvailability",
        "variables": {"id": event_id},
        "query": GET_EVENT_AVAILABILITY_QUERY,
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
                           event_title=parse_title(payload),
                           available_tiers=parse_available_tiers(payload))
    except httpx.HTTPError as exc:
        return FetchResult(ok=False, error=f"request failed: {exc}")
    except (ValueError, KeyError) as exc:  # JSONDecodeError <: ValueError → 200-with-non-JSON body
        return FetchResult(ok=False, status_code=200, error=f"parse failed: {exc}")
    finally:
        if owns_client:
            client.close()
