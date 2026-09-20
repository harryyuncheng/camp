# camp backend

One FastAPI service (`uv run uvicorn camp.api:app --port 8788`) fronts one database. It serves the recommender,
Today's lunch groups, the spending ledger, the Mac ↔ iPhone lunch session and the Ramp sandbox bridge. The former
stand-alone bridge `server.py` is retired; its endpoints moved to `/v1/ramp` unchanged and its SQLite ledger became
the `ramp_attempts` table.

## Start

```sh
cd backend
cp .env.example .env        # RAMP_CLIENT_ID / RAMP_CLIENT_SECRET, CAMP_DATABASE_URL (Postgres) …
uv sync --extra dev
uv run uvicorn camp.api:app --port 8788
```

`CAMP_DATABASE_URL=postgresql://localhost/camp` (Postgres.app) is the intended setup; unset it to fall back to the
`camp.db` SQLite file. Tables are created on startup. In the app, Demo → Recommendation service → `http://127.0.0.1:8788`
→ Save; the same URL and token also serve the Ramp card.

## Orders (`/v1/groups`, `/v1/restaurants`, `/v1/schedules`, `/v1/lunch-session`)

- `GET /v1/restaurants?category=coffee|meal&limit=` best-rated catalog places serving that category (rating shrunk towards 4.2 by review count).
- `GET /v1/restaurants/{id}/menu?userId=&groupId=` the whole menu priced with that group's delivery share, the public rating (`rating`, `reviewCount`, per-source `ratings`) and `top`: the user's three best items by recommender score.
- `POST /v1/craving` (`text`, optional `category`, `userId`, `limit`) free text such as "I want tacos": OpenAI (`OPENAI_API_KEY`; an offline keyword reader otherwise) extracts cuisine, dish format, keywords, diet and price cap, and the catalog's menus are scored against them. Each match is a `RestaurantWire` whose `options` are the dishes that matched, ready for `POST /v1/groups`; `backend` says whether the sentence was read by `llm` or `keywords`.
- `POST /v1/groups` (`category` optional, defaults to the place's primary one), `POST /v1/groups/{id}/join` with any menu item, `DELETE /v1/groups/{id}/members/{user}`. One order per person per category per day.
- `GET /v1/schedules/{user}`, `POST /v1/schedules` (`category`, `label`, `timeMinutes`, `weekdays` 0 = Monday, optional `restaurantId`/`optionId`), `PUT /v1/schedules/{id}/event` (store the device's calendar event id), `DELETE /v1/schedules/{id}?userId=`. `GET /v1/groups?userId=` materialises due schedules into groups.
- `GET/PUT/DELETE /v1/lunch-session`: the shared list of active orders (`records`) with `record` = the nearest; `DELETE ?sessionId=` forgets one.

## Ramp sandbox (`/v1/ramp`)

Enable the client-credentials grant and `business:read`, `users:read`, `funds:read`, `funds:write` in the Ramp sandbox
developer application. Tokens are scoped per operation and kept in memory. The app never receives the client secret,
access tokens, full card numbers or CVVs. Requests must carry `X-Camp-Client: camp-native` and no browser `Origin`
(no CORS); `X-Camp-Token` applies when `CAMP_TOKEN` is set.

- `GET /v1/ramp`: company identity, active employees, server allocation cap, funds named by camp, and how many
  allocation attempts the database holds. Linked cards expose only IDs and last four digits.
- `POST /v1/ramp/allocations`: `{ "requestID": "UUID", "userID": "UUID", "amountCents": 6000 }` creates one sandbox fund
  for a chosen active employee. Cap: $150 by default; `CAMP_SANDBOX_GROUP_CAP_CENTS` can lower it. Funds allow virtual
  cards only, restrict the Ramp category to Restaurants (19), use a non-resetting TOTAL limit plus an equal
  per-transaction cap, and lock after 24 hours.
- Idempotency: the `ramp_attempts` row (request fingerprint, immutable payload, state) is written before the remote
  POST. Retries return the existing result; an interrupted attempt is marked `unknown` on restart and reconciled by the
  unique fund name, never blindly re-issued. The Ramp POST also carries `X-Idempotency-Key`.

This is a sandbox spending-allocation flow: no DoorDash order, no charge, no payment credentials. A fund is spending
permission, not a purchase. Do not expose the service beyond your machine or LAN without camp authentication, HTTPS and
authoritative payer/office mappings.

## Everything else

See the repository `README.md` ("Recommendation core") for the recommender, the `PLAN.md` for its design, and
`ARCHITECTURE.md` for what the native apps read and write. Tests: `uv run pytest`.
