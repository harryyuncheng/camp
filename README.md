# camp

**Corporate Autonomous Meal Protocol.**

## Ramp sandbox integration

The Demo tab connects to Ramp through a local Python backend, lists active sandbox employees, and can create a bounded restaurant fund with linked-card references. Credentials stay on the backend. See [setup and API details](backend/README.md).

```sh
cp backend/.env.example backend/.env
# Add your sandbox credentials to backend/.env.
(cd backend && uv run camp serve)   # the one backend, on the port the app expects (8788)
```

Open camp → Demo → **Connect / refresh sandbox**. Choose the company payer and allocation before clicking **Create sandbox fund**. No food order or charge is placed.

## Mac office location

Office and Connections now use macOS Location Services. Use **Search** or **Find me** on the map, click to place your office circle, adjust its radius, and click **Confirm office**. The location card shows in-office/away/unknown and the latest arrival details. Tracking runs while camp is open and awake. See [location setup and behavior](docs/LOCATION.md).

## Mac calendars

Open **Connections → Connect calendars**, allow full calendar access, and select the calendars that should block your orders. Google, Outlook and iCloud calendars work when already synced in the Mac Calendar app. Available windows appear in Connections. Your saved meal duration, window and meeting buffer determine which gaps fit.

camp writes to one calendar of its own, named **camp** (created in your iCloud account on first use, otherwise locally). Every group order you join becomes a block there at its arrival time, and every standing order becomes a weekly repeating event; leaving a group or removing a standing order deletes the block. camp never edits events in your other calendars, and its own blocks are ignored when it looks for free time. See [calendar setup and behavior](docs/CALENDAR.md).

## Orders, not just lunch

Everything camp coordinates is an **order** in one of two categories: **Coffee & tea** (morning coffee runs, cafés and bakeries) and **Meal**. A person holds at most one active order per category per day, so a coffee and a lunch can both be live, and the notch and the iPhone always show the nearest one first with a **Next:** link to the other. There is no time-of-day rule: schedule either category whenever you like.

- **Today** lists the office's group orders with a category filter and a badge per card. **View menu** opens the whole menu for that place with the public rating (blended Google/Yelp/other-source score and review count), your **top picks** ranked by the recommender first, then the full list; anything on it can be ordered and joins the group's option list. Items are ticked, not picked one at a time: order a main plus sides or a drink, with one delivery share for the lot. A budget bar tracks the per-person cap from **Office → Budgets**, and once the selection fills it the rest of the menu greys out (your first item always goes through, however expensive). The backend applies the same rule to `optionIds`, so nothing that greys out here can slip through another surface.
- **New order** on Today starts a group at any café or restaurant that serves the chosen category.
- **You → Standing orders** schedules a repeating order: category, label, time, weekdays, an optional place and usual item. The backend puts you in a matching group each morning (creating one if needed) and the Mac mirrors it as a repeating event in the **camp** calendar.
- The catalog now holds real Flatiron cafés and bakeries as well as restaurants (`backend/src/camp/providers/fixtures/ramp_hq_cafes.json`); bakery-cafés such as Maman, Ole & Steen and Levain belong to both categories.

## Configuration workspace

The Mac app now opens a light camp workspace with lime accents. The dark notch panel remains available through the menu-bar icon or **Preview lunch invitation**. Right-click the camp menu-bar icon for **Open camp**, **Settings**, and **iPhone layout preview**.

The shared workspace has five SwiftUI screens:

- **Today:** today's office group orders (coffee and meals) from the backend database, your confirmed orders, start an order at a catalog place, browse full menus with ratings, choose/change/leave, and live savings and participant totals.
- **You:** food preferences, standing orders, editable meal timing, calendar selection and notification preview settings.
- **Office:** demo-admin toggle, address/geofence coordinates and radius, budgets, timing, fee sharing and group rules.
- **Spending:** a credit-card-shaped preview over your confirmed orders in the backend (`/v1/ledger`); no live card connection.
- **Connections:** Mac calendars and location.
- **Demo:** recommendation service, live offer and recommender debug views, Ramp sandbox bridge, and the DoorDash ordering placeholder.

Use **Save** to persist settings on this device and sync your profile to the backend (`PUT /v1/profile`), or **Discard** to revert. Office settings become read-only when demo admin is off. Ramp makes sandbox API requests through the backend's `/v1/ramp` endpoints. Mac presence uses on-device Location Services; calendar availability uses locally synced EventKit calendars. Group orders live in the backend's `groups` and `orders` tables; no food orders or payments are made. Mac notch confirmations update the workspace’s selected group and meal. iPhone group menus now start interactive Live Activities and confirmations update its local Today page. Mac and iPhone remain independent devices.

The Mac **iPhone layout preview** uses the same compact SwiftUI workspace as the iPhone app. It is a layout preview, not an iOS simulator. Xcode 16.2 on this machine successfully builds both the simulator and physical-device app. Running on the connected phone still requires Developer Mode and signing.

## Today demo and editable timing

- **New order** picks a category, a place from the catalog (`GET /v1/restaurants?category=`), an arrival time and one or more items, then `POST /v1/groups` creates and joins it. One order per person per category per day: joining a different group in the same category leaves the previous one server-side. New groups start with just you and zero delivery savings.
- **Craving something else?** in the create-order sheet takes free text ("I want tacos", "something spicy and Thai"). `POST /v1/craving` has OpenAI turn the sentence into typed search terms (cuisine, dish format, keywords, diet, price cap) and then scores the catalog's menus against them, so the model never invents a place or a price. The matched dishes come back as the restaurant's options: pick one and the usual create-and-join path takes over. Without `OPENAI_API_KEY` a keyword reader produces the same search terms offline, so the demo still works.
- **Total savings** and **People ordering** are computed by the backend from real membership: each group shares one delivery fee (the restaurant's own fee), so savings are `(participants − 1) × fee`. Prices are all-in estimates, not live quotes.
- A day with no groups is seeded by the backend from the catalog with synthetic colleagues (flagged `seeded`), so the office is never empty on first run.
- The notch lists the same groups, including newly created ones. **Preview order invitation** opens group selection; confirmation updates Today and retracts to the menu bar after three seconds.
- **Looking for something else?** sits in the notch too, on the group list and on the order card: type a place or a dish ("I want tacos", "iced oat latte") and the same `POST /v1/craving` search answers from the catalog. Picking a result puts that place on the card with its matching dishes as the options, and confirming starts a group order there (`POST /v1/groups`). The notch only takes keyboard focus while that field is focused; the rest of the time it stays a non-key overlay.
- In **You → Meal timing**, type times such as `1pm`, `13:30` or `1330`, then press Enter or leave the field. Unsuffixed times use the 24-hour clock. Duration and buffer are typed in minutes. Invalid input leaves the last valid draft value unchanged; **Save** applies valid preferences to the calendar service.
- Groups, membership and orders persist in the database across restarts. Settings persist locally and are mirrored to your backend profile on Save. Rebuilding with the development signature may require reconnecting OS calendar/location permissions.

## Branding and layout

The supplied logo is preserved in `Branding/camp.svg`. `CampLogo` in `LunchCard.swift` caches its vector paths without the white background, fits their aspect ratio and inherits the surface color. It is used in the sidebar, compact header, notch, shared meal card and menu-bar template image. The expanded notch header uses the mark plus **camp**. The sidebar mark aligns with the wordmark baseline and navigation icons.

Spending's demo card uses a 1.586 aspect ratio, caps its width at 400 points and scales its artwork uniformly on compact layouts. Workspace pages use stable stacks; macOS office-time menus use native controls. Map views are pooled, and calendar reads run away from the UI thread. Frame-rate improvements have not been benchmarked.

## Native order assistant

A small native order assistant POC. The Mac app opens an interactive panel beneath the notch when an order arrives. Pick a group, choose one of its items, review the price, and confirm. Meal choices use fictional data; confirmation records a local choice and never places an order. Ramp sandbox account data is fetched separately on the Demo tab.

## Run the Mac app

Open **`dist/camp.app`**. It runs in the menu bar with the camp logo, without a Dock icon. **Click** the logo to toggle the panel; **right-click** it for demo controls.

- **Trigger new lunch now** creates a fresh eight-minute selection window and expands the panel.
- **Trigger lunch in 5 seconds** hides the panel, then automatically reveals the full choices. Switch to another app during the delay to try the interruption flow.
- Pick a group → pick a meal → **Confirm lunch**. **Change** returns to that menu; **‹ Groups** returns to the group list. Today’s **View menu** opens the selected group directly.
- Confirmation stays visible for three seconds, then the panel retracts completely, leaving the menu-bar icon. Click the icon to reopen your saved choice; reopening does not restart the timer. **Simulate arrival** completes the demo.
- The chevron reverses the expansion into a clickable pill; × retracts fully into the menu bar.
- The underlying meal session is saved, but workspace groups, membership and group-picker context are in memory and reset on relaunch. Do not rely on a restart to restore a joined group.

The **…** menu inside the expanded panel also exposes the new-lunch and five-second triggers.

The black panel extends to the screen edge and surrounds the notch, with all controls below the camera. When opening from hidden, it uses the display containing the pointer. Incoming offers update an already-open panel in place. On displays without a notch, it opens below the menu bar. It doesn't activate the app or take keyboard focus. It respects Reduce Motion and repositions when display configuration changes.

**Mac requirements:** macOS 13+, no iPhone, developer account, notification permission, Accessibility permission, or Tahoe upgrade needed for this custom panel. The app must be running to receive the local demo event. The POC doesn't launch at login.

## Build and iterate

Open **`Lunchline.xcodeproj`**, select **LunchlineMac → My Mac**, and run. Alternatively, from this folder:

```sh
bash scripts/build-mac.sh --open
```

The script builds a release executable, wraps it in `dist/camp.app`, and signs it locally. Requires Xcode 14.3+ with the command-line tools installed. It honors `DEVELOPER_DIR`, otherwise prefers `/Applications/Xcode.app`. The local signature is for development, not a notarized distribution release.

The native project has no external package dependencies or bundled credentials. The optional Ramp bridge uses Python’s standard library and server-side environment credentials. Existing source folder and scheme names are retained; the app is branded and packaged as camp. The Swift package provides the Mac executable and domain tests; Xcode compiles the same source files directly into its app targets.

```sh
# If xcode-select currently points to CommandLineTools, use the full Xcode:
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcrun swift test
```

## Where to change things

| Concern | File |
| --- | --- |
| Meal/group fixtures, prices, deadlines, and session transitions | `Sources/LunchCore/LunchSession.swift` |
| Meal cards, vector logo, colors, typography, confirmation layout | `Sources/LunchUI/LunchCard.swift` |
| Notch placement, animation, collapse, panel shell | `Sources/LunchMac/NotchPanel.swift` |
| Incoming lunch event and Mac persistence | `Sources/LunchMac/MacLunchModel.swift` |
| Menu-bar controls and application lifecycle | `Sources/LunchMac/LunchMacApp.swift` |
| Today feed, create-group form and summary cards | `Sources/LunchUI/CampTodayPage.swift` |
| Settings, demo group list and membership | `Sources/LunchUI/CampSettingsStore.swift` |
| Editable time parsing and shared controls | `Sources/LunchUI/CampComponents.swift` |
| iPhone ActivityKit lifecycle | `iOS/Lunchline/LunchController.swift` |
| Live Activity button intents | `iOS/Lunchline/LunchIntents.swift` |
| Lock Screen and Dynamic Island presentations | `iOS/LunchlineActivity/LunchlineLiveActivity.swift` |

For a future meal-only integration, pass a session to **`MacLunchModel.offer(_:)`** on the main actor. It saves the offer and posts the in-process `lunchReady` notification; the panel automatically expands. This is an application event, not a macOS Notification Center banner. A future backend/prediction service should call this entry point after receiving an offer. Remote push delivery and background launch aren't implemented. The current group-picker context lives separately in `MacLunchModel`; a real offer adapter must set or clear that context explicitly.

## Native iPhone companion

The native iPhone app + WidgetKit extension use the existing workspace, shared domain and camp styling. Group menus start Live Activities with select/review/confirm controls. Mac and iPhone keep independent local sessions; they do not sync yet. See [iPhone development and device setup](docs/IOS.md) for the simulator workflow, local signing configuration and push-delivery boundary.

Build for Simulator with `bash scripts/build-ios.sh` after installing Xcode 15 or newer.

1. Use Xcode 15+ to compile the iOS 17 APIs, or a newer Xcode compatible with your phone's installed iOS.
2. Open `Lunchline.xcodeproj`, select the **Lunchline** scheme.
3. Copy `Config/Local.xcconfig.example` to ignored `Config/Local.xcconfig`; set your team and unique bundle prefix.
4. Select the same signing team for **Lunchline** and **LunchlineActivity**. Enable automatic signing.
5. Connect your iPhone, enable Developer Mode if prompted, and run.
6. Tap a lunch group’s **View menu** (or **Preview lunch invitation → Start demo lunch**), then open the Lock Screen or expand the Dynamic Island.

`NSSupportsLiveActivities`, extension embedding, intents, and the `camp://` URL scheme (plus legacy `lunchline://`) are configured. No App Group or APNs entitlement is required for this local demo: `LiveActivityIntent` executes in the app process, and the extension renders ActivityKit content.

The iPhone app can also supply Apple's mirrored Live Activity on macOS Tahoe 26+, but the standalone Mac notch panel is the primary Mac experience. See [Apple's mirroring setup](https://support.apple.com/en-us/120684) if you want to compare them.

## Verification and limits

- Thirteen domain/geometry/timing tests cover state transitions, persistence, notch placement, and confirmation deadlines. Three AppKit lifecycle tests also check view identity, fixed top edge, actual window hiding, explicit reopening, and cancellation when a new offer arrives. AppKit tests require a macOS desktop session and skip without one.
- Mac build and interaction results are recorded in `VALIDATION.md`.
- Unsigned simulator and physical-device builds succeeded with Xcode 16.2. Live Activity interactions remain unverified; the connected phone needs Developer Mode enabled and a signing team configured.
- Groups, orders, spending and savings are read from the backend database; menu prices are catalog estimates. The Live Activity's default lunch and the Spending card artwork remain demo visuals. Ramp sandbox, Mac location and Mac calendar access are implemented separately. Provider checkout and real payments are not connected.
- The Mac panel is a normal floating utility window, not a system notification; Focus mode does not automatically suppress it. Add your own quiet-hours/Focus policy before real reminders.

See `ARCHITECTURE.md` for state ownership and the integration boundary.

# Recommendation core (Python, `backend/`)

Deterministic core (hard filters → per-user scoring → batch optimizer); Jev does classification,
a small LLM writes text. See `PLAN.md` for module layout, decisions and assumptions.

```bash
cd backend
uv sync --extra dev
uv run pytest
uv run camp run-batch --days 3            # office lunch batches on synthetic data
uv run camp run-home                      # single home order (argmax, full fee)
uv run camp feedback-demo                 # NL feedback → events → profile updates
uv run camp eval --backends mock          # §8 harness; add jev,llm with keys set
uv run camp serve                         # the one backend on :8788 (--reload on): recommender, groups, craving search, ledger, sync, Ramp
CAMP_TOKEN=pick-a-secret uv run camp serve --host 0.0.0.0   # also reachable from the phone
```

Database: everything server-owned lives in one Postgres database when `CAMP_DATABASE_URL` is set (in `backend/.env`
or the shell; local default `postgresql://localhost/camp`, e.g. Postgres.app), otherwise in the SQLite file named by
`CAMP_DB` (default `camp.db`). Tables (`backend/src/camp/store.py`, one JSONB document table each with generated index
columns): `users` (profile + learned preferences + the app's saved settings), `restaurants`, `items`, `orders`, `batches`,
`events` (feedback), `groups` (Today's group orders and membership), `schedules` (standing orders), `ramp_attempts`
(idempotent sandbox fund issuance) and `sync` (the active Mac ↔ iPhone orders). Tests use in-memory SQLite plus one Postgres round-trip test that skips
when no server is reachable. `uv run camp migrate --source camp.db` copies an old SQLite file into `CAMP_DATABASE_URL`.
What stays on the device on purpose: OS permissions and their choices (calendar selection, the confirmed geofence),
connection URLs, the locally cached order session, and the ids of the calendar blocks camp wrote.

Keys: `TYPESAFE_API_KEY` enables Jev (`typesafe:jev-latest` via pydantic-ai); `OPENAI_API_KEY` enables the
LLM fallback and "why this pick" text. With neither set, an offline keyword mock is used so everything still runs.

Human labels for the eval go in `src/camp/eval/labels/{feedback,modifications,menu_tags}.csv`
(templates are written next to them by `camp eval`).

## Menu sources (Uber Eats, DoorDash)

`src/camp/providers/` — one `MenuProvider` interface (search stores, get menu, quote, place order),
adapters for Uber Eats and DoorDash, a mock that emits raw JSON in each platform's shape and runs it
through the real parsers, and `sync_catalog` which de-dupes restaurants listed on both platforms,
picks the cheaper/faster platform, maps allergen and diet labels, and upserts into the store.

```bash
uv run camp sync --db camp.db            # mocks unless keys are set
uv run camp sync --fixtures --no-tag     # also writes sample raw JSON to providers/fixtures/
```

Env for real adapters: `UBER_CLIENT_ID`, `UBER_CLIENT_SECRET`; `DOORDASH_DEVELOPER_ID`, `DOORDASH_KEY_ID`,
`DOORDASH_SIGNING_SECRET`. Endpoints marked `# ASSUMED` in the adapters are partner-only and unverified:
both public APIs are merchant-facing, so browsing stores near a point and ordering on behalf of a user
need partner access.

## Native app ↔ recommender

One local service: `cd backend && uv run camp serve` (recommender, groups, craving search, ledger, sync and the
Ramp sandbox bridge at `/v1/ramp`; `backend/server.py` is retired). Every feature the app talks to lives behind that
single URL; a bare `uvicorn camp.api:app` without `--port 8788` listens on :8000, which the app is not pointed at. In the app, Demo → Recommendation
service → Connect, then **Request lunch offer**: the app sends a `MealContext` (saved preferences, allergies,
lunch window, office policy, presence preview) and gets a `MealOffer` back (up to three options with all-in
estimated prices under the office batch and an "ordered alone" baseline). On the Mac the offer opens in the notch
panel through `MacLunchModel.offer(_:)`; on both platforms it also appears on the Demo tab.

Contracts: `backend/src/camp/contracts.py` ↔ `Sources/LunchCore/RecommendationContracts.swift`; groups and ledger:
`backend/src/camp/groups.py` ↔ `Sources/LunchCore/LunchSession.swift` (`DemoLunchGroup`, `LunchLedgerResponse`).

Endpoints the app uses: `GET /v1/health`, `PUT /v1/profile`, `GET /v1/groups`, `GET /v1/restaurants`, `POST /v1/groups`,
`POST /v1/craving`, `POST /v1/groups/{id}/join`, `DELETE /v1/groups/{id}/members/{user}`, `GET /v1/ledger/{user}`, `POST /v1/meal-offers`,
`POST /v1/lunch-events`, `GET|PUT|DELETE /v1/lunch-session`, `GET /v1/ramp`, `POST /v1/ramp/allocations`, `/v1/debug/*`.
Change a row in Postgres (e.g. a group's members) and the Today page shows it on its next refresh.

## Mac ↔ iPhone sync

The recommender backend is also the authority for the *current lunch*. Whatever either device does — start a
lunch, pick a meal, confirm, simulate arrival, end — is published to `PUT /v1/lunch-session` with the revision it
started from, and the other device long-polls `GET /v1/lunch-session?since=<seq>` so the change lands within a round
trip: a group chosen in the Mac notch starts the phone's Live Activity, a tap on the Lock Screen updates the notch.
Stale writes get a 409 and the device adopts the newer record. Single user, one shared lunch; identity comes later.

To connect the phone (same Wi-Fi, or the Mac joined to the phone's Personal Hotspot):

1. Run the backend bound to the network with a token: `cd backend && CAMP_TOKEN=pick-a-secret uv run camp serve
   --host 0.0.0.0`. Never bind `0.0.0.0` without `CAMP_TOKEN`; the API fronts your keys.
2. On the Mac, Demo → Recommendation service: `http://127.0.0.1:8788`, the token, **Save**.
3. On the phone, the same card: `http://<mac-name>.local:8788` (`scutil --get LocalHostName` on the Mac; the `.local`
   name survives switching between Wi-Fi and hotspot) or the Mac's LAN IP, the same token, **Save**. iOS asks for
   local-network permission the first time. The badge reads **Live · <host>** on both devices when connected.

Plain HTTP is accepted only for loopback, `.local` names and private ranges (`10.`, `172.16–31.`, `192.168.`, hotspot
`172.20.10.x`); anything else must be HTTPS (`tailscale serve 8788` gives an HTTPS URL that needs no code change).
The phone syncs while camp is in the foreground; the Lock Screen catches up when the app returns until APNs
push-to-update is added. The backend keeps the record in the `sync` table of the shared database.

**Demo tab**: the bottom-aligned sidebar tab (above the office name) collects everything added for demoing and
testing the recommender. It shows the live offer and reads `/v1/debug/*`: the current office batch (restaurants, headcounts, fee shares, regret), your profile as the backend
sees it (learned preferences, filter rejections, top candidates with score breakdowns), the last offer, and a feedback
console that runs text through Jev/mock classification and shows the resulting events and profile updates.
