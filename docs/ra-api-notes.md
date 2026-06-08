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

### CRITICAL: two ticketing systems, two signals

RA events use one of two ticketing systems (`event.ticketingSystem`), and the
availability signal differs. **Reading only one is wrong** — it was the original
bug (rabot polled only `isAnyTicketTierAvailable` and was blind to LEGACY events
like Houghton, which is the actual target).

- **LEGACY events** (`ticketingSystem: "LEGACY"`): availability is per-tier in
  the **legacy `tickets` list**, each `Ticket` having a `validType`
  (`VALID` = buyable, `SOLDOUT`, `NOTYETONSALE`, …). For these, the V2
  `isAnyTicketTierAvailable` is **structurally `false`** (the V2 object is empty),
  so it must NOT be relied on. The website itself renders LEGACY availability from
  this tier list ("the ticket tier will be lit up"). The legacy `tickets` field
  **is readable anonymously** when queried with `queryType: AVAILABLE`.
- **ENTIRE / V2 events** (`ticketingSystem: "ENTIRE"`, e.g. Waterworks 2345415):
  `ticketing.isAnyTicketTierAvailable` is the signal; the legacy `tickets` list is
  empty.

**Add-ons must be excluded.** Parking/vehicle/locker passes are separate tiers
with `isAddOn: true` and are often always `VALID` even on a sold-out event
(Houghton has 3 such VALID add-ons while all 6 festival tiers are `SOLDOUT`).
`tickets(queryType: AVAILABLE, ticketTierType: TICKETS)` excludes add-ons; we also
guard on `isAddOn` in code.

**rabot's availability rule:** available =
`ticketing.isAnyTicketTierAvailable` **OR** any non-add-on tier with
`validType == "VALID"`.

## The query the bot uses

```graphql
query GetEventAvailability($id: ID!) {
  event(id: $id) {
    id
    title
    ticketingSystem
    ticketing { isAnyTicketTierAvailable }
    tickets(queryType: AVAILABLE, ticketTierType: TICKETS) { title validType isAddOn }
  }
}
```

- `variables`: `{"id": "<numeric event id>"}` (the id from `https://ra.co/events/<id>`).
- Available tier titles (legacy) feed the alert message, e.g. "… (Tier 1)".
- Verified live: Houghton 2287366 (LEGACY, 6 festival tiers SOLDOUT + 3 VALID
  add-ons) → `available = false` (add-ons correctly ignored); Waterworks 2345415
  (ENTIRE) → `available = true` via `isAnyTicketTierAvailable`.

## Design implication

`ra_client.fetch()` returns an availability boolean plus the names of any buyable
(non-add-on) tiers.
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
