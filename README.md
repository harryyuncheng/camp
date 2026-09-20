# camp

**Corporate Autonomous Meal Protocol.**

camp makes workplace food ordering easier. It recommends menu items from your preferences and order history, helps coworkers find a match from a craving, and groups orders from the same place to share delivery fees. The Mac notch panel and iPhone Live Activity keep the current order close at hand and in sync.

**Your order, on your time.**

## Quick start

Start the local backend:

```sh
cd backend
uv sync --frozen --extra dev
uv run camp serve
```

In another terminal, from the repository root, build and open the Mac app:

```sh
bash scripts/build-mac.sh --open
```

Connect the app to `http://127.0.0.1:8788` in **Demo → Recommendation service**. For iPhone setup, local signing, Ramp sandbox credentials, and device networking, use the [demo runbook](docs/DEMO.md).

## Project docs

| Start here | What it covers |
| --- | --- |
| [App guide](docs/APP-GUIDE.md) | Main screens, ordering flow, group savings, and current limits |
| [Demo runbook](docs/DEMO.md) | Local setup, Mac/iPhone connection, rehearsal, and validation boundaries |
| [Development guide](docs/DEVELOPMENT.md) | Build entry points, source map, and integration seams |
| [Architecture](ARCHITECTURE.md) | State ownership, persistence, syncing, and platform design |
| [iPhone development](docs/IOS.md) | Simulator/device setup and Live Activity behavior |
| [Office location](docs/LOCATION.md) · [Calendars](docs/CALENDAR.md) | macOS permission setup and behavior |
| [Backend guide](backend/README.md) · [Recommender plan](backend/PLAN.md) | Service setup, API, and recommendation design |
| [Validation notes](VALIDATION.md) | Recorded build and device checks |

## Prototype boundaries

Menu prices are estimates. The app groups and tracks orders, but restaurant checkout and food payments are not connected. Ramp access is sandbox-only, and iPhone background updates need APNs push delivery (`CAMP_PUSH` plus `CAMP_APNS_*` credentials; see docs/IOS.md).
