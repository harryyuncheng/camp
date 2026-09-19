# camp Ramp sandbox bridge

A local Python 3 service for the Mac app and iOS simulator. There is deliberately no production Ramp endpoint. No third-party dependencies are needed.

## Start

From the repository root:

```sh
cp backend/.env.example backend/.env
# Fill in RAMP_CLIENT_ID and RAMP_CLIENT_SECRET in backend/.env.
python3 backend/server.py
```

Alternatively use `--env-file /path/to/private.env`. The server only listens on `127.0.0.1:8787`. In camp, leave the backend URL blank or use `http://127.0.0.1:8787`, then open Connections → Connect / refresh sandbox. Credential rotation requires restarting the service. `.env` and `.state` are ignored by Git.

Enable the client-credentials grant and `business:read`, `users:read`, `funds:read`, `funds:write` in the Ramp sandbox developer application. This implementation uses scoped tokens per operation and keeps tokens in memory. The app never receives the client secret, access tokens, full card numbers or CVVs.

## Implemented

- `GET /v1/ramp`: company identity, active employees, server allocation cap and funds named by camp. Linked cards expose only IDs and last four digits.
- `POST /v1/ramp/allocations`: `{ "requestID": "UUID", "userID": "UUID", "amountCents": 6000 }` creates one sandbox fund for a chosen active employee.
- The server applies a $150 maximum per allocation by default. `CAMP_SANDBOX_GROUP_CAP_CENTS` can lower this cap. Client office settings cannot increase it.
- Funds allow virtual cards only, restrict the Ramp category to Restaurants (19), use a non-resetting TOTAL limit plus an equal per-transaction cap, and set a lock date 24 hours later.
- SQLite stores the request fingerprint, immutable payload and result before/after remote issuance. Retries return the existing result. Interrupted or uncertain writes reconcile the exact fund name before returning; they never blindly repeat a POST. The original Ramp POST also includes `X-Idempotency-Key`.
- The app persists its pending attempt and keeps its owner/amount frozen. It allows a new attempt only after a successful result. An unresolved attempt with no matching remote fund requires manual investigation; there is no force-retry button.

For native calls use `X-Camp-Client: camp-native` and JSON for POSTs. Browser Origins and unexpected Host headers are rejected, with no CORS support. This header is **not user authentication**. The bridge assumes a trusted local development machine; do not expose or tunnel it. Before deploying for a physical iPhone, add authenticated camp identities, authoritative payer/office mappings, HTTPS, roles, and a shared backend. A physical iPhone cannot reach the Mac through its own localhost.

## What this does not do

This is an explicit sandbox spending-allocation flow. It does not submit a DoorDash order, charge a card, retrieve payment credentials, issue single-use Agent Cards, or enforce group membership/per-person budget accounting. A fund is spending permission, not a completed purchase. The API may return linked card references; the UI does not claim a card exists if none was returned. Existing funds remain in Ramp when starting another allocation; manage them through the sandbox dashboard.

The next integration is the server-owned group checkout: freeze the cart, validate each participant's allocation and quote expiry, bind one immutable order-attempt ID to this adapter, then hand off payment through an approved provider flow. Restaurant categorization must be checked against the eventual provider; this prototype does not assume every delivery service uses that category.

## Observed on 2026-09-19

Authentication succeeded for company/user/fund/card reads and fund writes. A real read through the running bridge loaded the sandbox company and 41 active employees. No fund creation or checkout was performed during implementation, and no automated tests were run. Mac release build succeeded; iOS remains unbuilt with the installed Xcode 14.3.1.

Ramp's downloaded OpenAPI describes the token request as JSON, but the live sandbox requires `application/x-www-form-urlencoded`. A descriptive User-Agent is also supplied because the gateway rejected Python's default user agent.

Official references: [Funds API](https://docs.ramp.com/developer-api/v1/api/funds), [Virtual cards guide](https://docs.ramp.com/developer-api/v1/virtual-cards), [OpenAPI schema](https://docs.ramp.com/openapi/developer-api.json).
