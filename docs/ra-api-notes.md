# RA GraphQL API — Findings (Task 2 spike)

Captured 2026-06-03 by direct `POST https://ra.co/graphql` probing (no browser needed).

## Endpoint & headers

- **URL:** `https://ra.co/graphql`
- **Method:** `POST`, body `{"operationName", "variables", "query"}`
- **Required headers:** `Content-Type: application/json`, a browser-like `User-Agent`,
  and `Referer: https://ra.co/events`. No auth, no cookie, no Cloudflare challenge for
  read queries. GraphQL **introspection is enabled** (used to discover all of the below).

## The availability signal (CONFIRMED)

Anonymous requests **cannot** read per-tier ticket data:
- `event.tickets[]` (legacy `Ticket` type) returns `[]` for all anonymous requests
  (admin/promoter-gated; fields like `totalSold` return `AUTH_NOT_AUTHORIZED`).
- `Ticketing_ticketTiersV2` returns `401 UNAUTHENTICATED`.
- `event.ticketing.ticketListingItems` returns `[]` anonymously.

The **one** anonymously-readable availability signal is a single boolean:

```
event(id: $id) { ticketing { isAnyTicketTierAvailable } }
```

`isAnyTicketTierAvailable` is `true` when any tier is buyable, `false` otherwise
(sold out, not yet on sale, or externally ticketed). For a sold-out event gaining
resale/returns, this flips `false → true` — exactly the bot's trigger.

Verified across 133 events: exactly the on-sale ones report `true`
(e.g. event 2345415 "Waterworks Extended 2026" → `true`; sold-out event 2384759 → `false`).

## The query the bot uses

```graphql
query GetEventTicketing($id: ID!) {
  event(id: $id) {
    id
    title
    ticketing {
      isAnyTicketTierAvailable
      ticketStatus
    }
  }
}
```

- `variables`: `{"id": "<numeric event id>"}` (the id from `https://ra.co/events/<id>`).
- Response path to the signal: `data.event.ticketing.isAnyTicketTierAvailable` (boolean).
- `data.event.title` gives a human label for the notification.
- `ticketStatus` (enum: `approved` / `pending` / `stopped` / `cancelled` / `deleted`)
  is captured for context/logging; `approved` is the normal selling state.

## Design implication

`ra_client.fetch()` returns a single availability boolean, not a list of tiers.
`FetchResult` carries `ok`, `available`, `event_title`, `error`. The evaluator keys off
`result.available`. (Original plan assumed a per-tier list via `validType`; that path is
not anonymously accessible, so the boolean model replaces it.)

## Fixtures

- `tests/fixtures/tickets_available.json` — real response, `isAnyTicketTierAvailable: true`.
- `tests/fixtures/tickets_soldout.json` — real response, `isAnyTicketTierAvailable: false`.

## Aside (out of scope)

RA has a native "notify me when tickets are available" feature
(`event.canSubscribeToTicketNotifications`, `ticketNotificationSubscriptions`). We build
our own poller instead, but this confirms RA models the exact event we watch for.
