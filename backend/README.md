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

## Onboarding (`/v1/onboarding`)

The once-per-person setup lives in the `onboarding` table so the Mac and the phone share one answer set through this
database instead of each keeping their own.

- `PUT /v1/onboarding`: `{ context, settings, completed, device }`. `context` is the usual `MealContext`, applied to
  the `User` row exactly as `PUT /v1/profile` applies it (diet and allergy restrictions, budget, meal window).
  `settings` is the native app's whole configuration document, stored verbatim and never interpreted here.
- `GET /v1/onboarding?userId=&displayName=&officeId=`: the row for that user, else the newest row with that display
  name in the office, else the office's newest completed row. `404` when nobody has set up yet.
- `DELETE /v1/onboarding/{user_id}`: clears `completed` and keeps the answers, so the flow can be demoed again.

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
