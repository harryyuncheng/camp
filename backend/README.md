# camp backend

One FastAPI service (`uv run camp serve`, i.e. `uvicorn camp.api:app --port 8788 --reload`) fronts one database. It serves the recommender,
Today's lunch groups, the natural-language craving search, the spending ledger, the Mac ↔ iPhone lunch session and the Ramp sandbox bridge. The former
stand-alone bridge `server.py` is retired; its endpoints moved to `/v1/ramp` unchanged and its SQLite ledger became
the `ramp_attempts` table.

## Start

```sh
cd backend
cp .env.example .env        # RAMP_CLIENT_ID / RAMP_CLIENT_SECRET, CAMP_DATABASE_URL (Postgres) …
uv sync --extra dev
uv run camp serve            # :8788 with --reload; `--host 0.0.0.0` for the phone, `--no-reload` for a daemon
```

Every endpoint the app uses (recommender, groups, `/v1/craving`, ledger, Ramp) is on this one process and one URL.
Running `uvicorn camp.api:app` by hand without `--port 8788` listens on :8000, which the app is not pointed at, and
any process still holding :8788 keeps answering the app with an older route table (a `Not Found` from a new feature
is the symptom); stop it with `lsof -ti :8788 | xargs kill`.

`CAMP_DATABASE_URL=postgresql://localhost/camp` (Postgres.app) is the intended setup; unset it to fall back to the
`camp.db` SQLite file. Tables are created on startup. In the app, Demo → Recommendation service → `http://127.0.0.1:8788`
→ Save; the same URL and token also serve the Ramp card.

## Orders (`/v1/groups`, `/v1/restaurants`, `/v1/schedules`, `/v1/lunch-session`)

- The catalog (`src/camp/providers/fixtures/ramp_hq_restaurants.json` + `ramp_hq_cafes.json`) covers ~310 places with full menus (~6 k dishes): everything within walking distance of Ramp HQ plus destination picks across Manhattan and north Brooklyn inside the 6 km delivery radius (Katz's, Via Carota, Peter Luger, Joe's Shanghai, Los Tacos No. 1, …). Bakery-cafés such as Maman, Ole & Steen and Levain belong to both categories. It is generated from `tools/catalog/*.menu` by `tools/build_catalog.py`; see `PLAN.md` → "Catalog expansion".
- `GET /v1/restaurants?category=coffee|meal&limit=` best-rated catalog places serving that category (rating shrunk towards 4.2 by review count).
- `GET /v1/restaurants/{id}/menu?userId=&groupId=` the whole menu priced with that group's delivery share, the public rating (`rating`, `reviewCount`, per-source `ratings`) and `top`: the user's three best items by recommender score.
- `POST /v1/craving` (`text`, optional `category`, `userId`, `limit`) free text such as "I want tacos": OpenAI (`OPENAI_API_KEY`; an offline keyword reader otherwise) extracts cuisine, dish format, keywords, diet and price cap, and the catalog's menus are scored against them. Each match is a `RestaurantWire` whose `options` are the dishes that matched, ready for `POST /v1/groups`; `backend` says whether the sentence was read by `llm` or `keywords`.
- `POST /v1/groups` (`category` optional, defaults to the place's primary one), `POST /v1/groups/{id}/join` with any menu item, `DELETE /v1/groups/{id}/members/{user}`. One order per person per category per day.
- Both take `optionIds` (up to 8 items; `optionId` is still accepted for one). A member's whole selection is replaced on each join, one confirmed `Order` is written per item, and the delivery share is charged once per person, on their first item. The first item always goes through; every extra must keep the person inside their per-order budget (`budget_cents`, as `PUT /v1/profile` sets it), otherwise the request is refused with 422. The group wire carries `myOptionIds` and `budgetCents` so the menu can grey out what no longer fits.
- `GET /v1/schedules/{user}`, `POST /v1/schedules` (`category`, `label`, `timeMinutes`, `weekdays` 0 = Monday, optional `restaurantId`/`optionId`), `PUT /v1/schedules/{id}/event` (`userId` required, `calendarEventId` optional; checks the schedule owner), `DELETE /v1/schedules/{id}?userId=`. `GET /v1/groups?userId=` materialises due schedules into groups.
- `GET/PUT/DELETE /v1/lunch-session`: the shared list of active orders (`records`) with `record` = the nearest; `DELETE ?sessionId=` forgets one.

## Ramp sandbox (`/v1/ramp`)

Enable the client-credentials grant and `business:read`, `users:read`, `funds:read`, `funds:write`, `limits:read` in the Ramp sandbox
developer application. Tokens are scoped per operation and kept in memory. The app never receives the client secret,
access tokens, full card numbers or CVVs. Requests must carry `X-Camp-Client: camp-native` and no browser `Origin`
(no CORS); `X-Camp-Token` applies when `CAMP_TOKEN` is set.

- `GET /v1/ramp`: company identity, active employees, server allocation cap, funds named by camp, and how many
  allocation attempts the database holds. Linked cards expose only IDs and last four digits.
- `POST /v1/ramp/allocations`: `{ "requestID": "UUID", "userID": "UUID", "amountCents": 6000 }` creates one sandbox fund
  for a chosen active employee. Cap: $150 by default; `CAMP_SANDBOX_GROUP_CAP_CENTS` can lower it. Funds allow virtual
  cards only, restrict the Ramp category to Restaurants (19), use a non-resetting TOTAL limit plus an equal
  per-transaction cap, and lock after 24 hours.
- `GET /v1/ramp/limits/{employee}`: the employee's live Ramp limits, the binding one, and their overage requests.
  `perOrderCents` — what is left in the current interval, or Ramp's smaller per-transaction ceiling — is the cap the
  app shows on Today and sends with the profile, so the office per-person setting is only a fallback for when Ramp
  holds no limit. The one-off `camp · …` allocations are excluded: they are lunch money for one order, not a limit.
- `POST /v1/ramp/overages`: `{ "requestID": "UUID", "userID": "UUID", "requestedCents": 7500, "reason": "", "requester": "" }`
  files a request to raise that limit. Idempotent on `requestID`, one pending request per employee, and it must ask
  for more than Ramp currently allows. Nothing changes in Ramp until someone decides.
- `POST /v1/ramp/overages/{id}/decision`: `{ "approve": true, "approver": "" }`. Approving PATCHes the limit in Ramp to
  the requested ceiling on top of what is already spent; the row keeps `baseline_cents`, the ceiling it had before. A
  decision is final, and denial touches nothing in Ramp. Who may approve is the app's call (it gates on demo-admin).
- Idempotency: the `ramp_attempts` row (request fingerprint, immutable payload, state) is written before the remote
  POST. Retries return the existing result; an interrupted attempt is marked `unknown` on restart and reconciled by the
  unique fund name, never blindly re-issued. The Ramp POST also carries `X-Idempotency-Key`.

This is a sandbox spending-allocation flow: no DoorDash order, no charge, no payment credentials. A fund is spending
permission, not a purchase. Do not expose the service beyond your machine or LAN without camp authentication, HTTPS and
authoritative payer/office mappings.

## Everything else

See [`PLAN.md`](PLAN.md) for the recommender design and the repository's
[`ARCHITECTURE.md`](../ARCHITECTURE.md) for what the native apps read and write.

## Correctness checks

From `backend`:

```bash
uv run --frozen --extra dev pytest -q
uv run --frozen --extra dev ruff check src tests
uv run --frozen --extra dev mypy
uv run --frozen --extra dev python -m compileall -q src tests
```

Ruff is pinned to the correctness-only `E9,F63,F7,F82` rules; mypy is pinned and checks the wire contracts
and persisted models. Set `CAMP_INTEGRATION_DATABASE_URL` to a disposable PostgreSQL admin database URL
to also run the integration regressions against PostgreSQL. Those tests create and drop a unique database
per case; SQLite always runs. The existing catalog PostgreSQL smoke test uses `CAMP_TEST_DATABASE_URL`.

Offers, their wire snapshots and lifecycle state live in the `offers` table and are included by
`Store.copy_from`. Lifecycle/order/profile/event writes commit together; event IDs are claimed atomically.
`Store.transaction()` is synchronous and must not span an `await` or remote request. PostgreSQL uses a
transaction-scoped single-writer advisory lock; SQLite uses `BEGIN IMMEDIATE`. Run one backend worker:
sync notifications and Ramp mutation coordination still use process-local state.
