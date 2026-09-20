# Architecture

## Shared state and presentation

`LunchCore` contains Foundation-only value types and file persistence. `LunchSession.applying` is the meal-session state transition function; demo group membership is managed separately by `CampSettingsStore`. It returns a new value or a meaningful error; it has no UI, network, payment, or ActivityKit dependencies. Dates are injectable and amounts are integer cents.

```text
choosing → reviewing → confirmed → delivered
    ↑          │
    └─ change ─┘

choosing / reviewing / confirmed → ended
```

Expired choosing/reviewing sessions remain readable, but cannot be selected or confirmed. Expiration is derived from `closesAt`, so it doesn't depend on a background timer executing. The local UI reevaluates expiry; ActivityKit uses `staleDate`. Confirmed sessions can finish after the selection cutoff.

An incrementing revision prevents stale buttons from confirming a different meal after a newer selection. Repeated confirm cannot transition an already confirmed state. This is local protection; real order submission still requires a server-issued idempotency key and authoritative quote validation.

`LunchUI` renders the shared in-app card. The Live Activity uses a shorter composition of camp branding and confirmation controls to fit the Lock Screen, with App Intent buttons. Platform shell details stay outside reusable components.

## Mac event → panel

`MacLunchModel` is main-actor isolated and owns the local session. `offer(_:)` saves a new session and posts `.lunchReady`. `NotchPanelController` receives that signal and automatically expands. The five-second demo uses this exact path.

`NotchPanelController` owns a borderless, nonactivating `NSPanel`, a single persistent SwiftUI hosting view, screen placement, and transition scheduling. SwiftUI animates the shell dimensions, corner radius, and the opacity of permanently mounted expanded/compact content in both directions. The native window temporarily encloses the old and new shell sizes, then contracts after the transition; stale completion tasks are cancelled. Meal-state updates are measured and resize the existing shell without re-entering or re-anchoring it. The black shell starts at the screen edge and fills the band around the physical notch; a reserved top inset keeps all controls below the camera. Its concave shoulders join the screen edge, and expansion preserves that fixed top edge. It uses `safeAreaInsets` and the auxiliary top screen areas to find the notch, with a menu-bar fallback for other displays. It supports multiple Spaces and opts into appearing alongside full-screen apps. Those behaviors should be tried on the specific demo setup, especially external displays and full-screen presentations.

The app is an `LSUIElement` menu-bar utility. It can reveal the panel without foreground activation. The current mouse-only panel does not take keyboard focus; keyboard navigation and richer accessibility should be addressed when adding text input or turning this into a shipping product.

The panel's visibility is independent of lunch state: collapsing or hiding does not cancel a choice. An incoming offer expands even if the last card was collapsed. Several shared orders can coexist; the panel shows one and keeps the others available to switch to. Confirmation schedules a three-second retraction, scoped to the session ID and revision. Reopening, manual dismissal, or a new offer cancels it. The menu-bar icon remains; left-click toggles the panel and right-click exposes controls.

## iPhone state ownership

`LunchController` owns the app session and requests/updates/ends ActivityKit activities. A shared transition waits for the backend acknowledgement, then persists the session and group context and updates ActivityKit. Foreground reconciliation adopts the backend snapshot and reconnects to the activity. Group membership and session publication are separate requests; a publication failure after a successful join requires refresh/retry.

The intent types are included in both app and extension for metadata discovery; `LiveActivityIntent` executes in the containing app process. The extension reads `ActivityViewContext` and does not access the file store. No App Group is required for this arrangement.

The controller rejects concurrent commands while publishing an update. Buttons embed session ID and revision so delayed intent execution cannot act on a replacement lunch. Local confirmation is deliberately distinct from provider order placement.

## Persistence

`SessionFile` atomically writes a versioned JSON envelope. Unknown versions and corruption produce errors rather than silently replacing a saved choice. Mac data lives in Application Support/LunchlineMac; iPhone data is inside the app container. No credentials are stored.

Server-owned state lives in the backend database (`backend/src/camp/store.py`: Postgres via `CAMP_DATABASE_URL`, SQLite otherwise): users and saved preferences, the catalog, orders, batches, feedback events, lunch groups, standing schedules, durable offers, Ramp allocation/overage attempts and shared sessions. Swift stores retain API snapshots for display; refreshes and acknowledged mutations update them, and failed refreshes can leave explicitly stale data visible. Device-only state stays on the device deliberately: calendar selection and event IDs, the confirmed geofence, connection settings and the persisted session cache. Connection tokens are currently in the permission-restricted configuration file; migrating them to Keychain remains future work.

`Store.transaction()` covers synchronous read/modify/write operations with SQLite `BEGIN IMMEDIATE` and nested savepoints, or PostgreSQL transactions and a single-writer advisory lock. Do not hold this context across an `await` or a remote API call. Offers persist their option mapping and terminal lifecycle, and event IDs are claimed atomically so a repeated confirmation does not apply feedback twice. Run one backend process: sync wakeups and Ramp coordination still use process-local state.

The two devices share their active orders through the recommender backend (`LunchSyncCoordinator` in `SessionFile.swift`, `backend/src/camp/sync.py`, persisted in the `sync` table). The shared state is a list of records keyed by session id, one per active order, so a morning coffee and a lunch coexist; the snapshot's `record` is the nearest one (soonest `arrivesAt` among unfinished orders) and `records` is the whole list. `LunchSession.applying` stays the single transition implementation; a device publishes the resulting session plus its group as a `LunchSyncRecord` with the revision it started from, and the backend compare-and-swaps per session: same order → the expected revision must match and move forward, new order → it is added. A 409 carries the newer record and the full list, which the device adopts. `MacLunchModel` keeps the nearest order on screen and the rest in `others`; a nearer incoming order takes the stage and the current one waits. Finished records are pruned after two hours, everything after twenty. `LunchSession.category` and `DemoLunchGroup.category` are optional on the wire so records from older builds decode as meals. Each app long-polls `GET /v1/lunch-session?since=<seq>` (held up to 25 s server-side) and applies records through `MacLunchModel.applyRemote` / `LunchController.applyRemote`; echoes of a device's own write have an equal revision and are ignored. The Mac's group-picker placeholder (`triggerDemo`) is deliberately not published; the phone hears about the lunch when a group is chosen. Identity is a single implicit user for now; real money still needs a server-issued idempotency key and authoritative quotes.

## Next integration steps

1. Add device pairing and an explicit employee identity namespace to the shared-session API.
2. Combine membership and session publication behind a durable operation ID so disconnect recovery can reconcile one operation.
3. Extend the existing durable meal offers into provider-authoritative quotes and checkout: currency, fee breakdown, quote expiry, idempotent submission, reconciliation and receipts. Only show an order as placed after the provider acknowledges it.
4. Add APNs push-to-update for the iPhone Live Activity so the Lock Screen changes while camp is backgrounded; today the phone syncs only while foregrounded. The Mac already receives changes through the long-poll.
5. Add reminder preferences, quiet hours, and a rule for incoming offers when one is already confirmed.

## Primary Apple references

- [NSPanel](https://developer.apple.com/documentation/appkit/nspanel)
- [Nonactivating panel](https://developer.apple.com/documentation/appkit/nswindow/stylemask-swift.struct/nonactivatingpanel)
- [Screen safe-area insets](https://developer.apple.com/documentation/appkit/nsscreen/safeareainsets)
- [Screen areas beside the notch](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytopleftarea)
- [Displaying Live Activities](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)
- [Interactive widgets and Live Activities](https://developer.apple.com/documentation/widgetkit/adding-interactivity-to-widgets-and-live-activities)


## Local configuration workspace

`CampConfiguration` holds separate personal, office and connection preferences, with validation and versioned atomic JSON persistence through `ConfigurationFile`. `CampSettingsStore` owns the editable draft, explicit save/discard, demo role and ephemeral group/connection previews. Mac settings are stored at Application Support/Camp/settings.json; iOS uses the app's Application Support container.

`CampWorkspace` and its pages live in LunchUI and support desktop sidebar and compact bottom-tab layouts. The Mac delegate owns persistent workspace and phone-preview windows; status-item left click continues to toggle the existing notch panel. Both Mac preview windows share the same store. iOS manages orders in Today; incoming sessions and activity deep links select that tab. Acknowledged joins and group creation start confirmed ActivityKit sessions, and leaving removes the group's shared sessions. Activity and sync errors are shown in Today. The workspace's optional preview callback keeps invitation previews available on the Mac. See `docs/IOS.md` for lifecycle and delivery limitations.

Group arithmetic allocates the restaurant's delivery fee once per member, including remainder cents; additional items do not add another share. Saved dietary restrictions and the multi-item budget rule are enforced on joins. Displayed savings and totals are estimates, not provider quotes. Some office policy controls remain configuration-only; the demo-admin toggle is not server authorization. Preview connection states are ephemeral and never represent authenticated services.

## Ramp bridge

`backend/src/camp/ramp.py` (mounted at `/v1/ramp` in the FastAPI service; `backend/server.py` is retired) owns Ramp OAuth, read projections and durable sandbox allocation attempts in the `ramp_attempts` table. `CampRampView`/`CampRampModel` use the recommender URL and token and persist only the non-sensitive pending request in UserDefaults. The server enforces its own allocation cap and active employee lookup; demo office policy is not an authorization source. This local service is not suitable for remote deployment until camp authentication and office membership exist. See `backend/README.md` for its contract and limitations.

## Recommender bridge

`backend/src/camp` is the Python recommender (deterministic filters → scoring → batch optimizer, Jev/LLM only for
classification; see `backend/PLAN.md`). `RecommendationClient` (LunchCore, Foundation-only) posts a `MealContext` built
from `CampConfiguration` and maps the `MealOffer` onto `LunchSession`, so the existing card, panel and Live Activity render
it unchanged. `CampSettingsStore.onOffer` is the seam the Mac delegate uses to call `MacLunchModel.offer(_:)`. The
Demo tab (`CampDemoPage`, bottom-aligned in the sidebar) shows the live offer and renders backend debug JSON loosely via `JSONValue`.
The recommender's offline catalog is real restaurants around Ramp HQ (`backend/src/camp/catalog.py`, see `backend/PLAN.md`);
when the app's office is elsewhere the catalog geometry is re-centred on it, so demo distances stay realistic.
Every confirmed lunch is an `Order` row: recommender picks through `POST /v1/lunch-events`, group lunches through the
group join. The Spending page reads `GET /v1/ledger/{user}` (monthly spend, delivery savings versus ordering alone,
budget = 20 × the user's per-meal budget, recent activity). Saving settings calls `PUT /v1/profile`, which stores the
app's preferences on the user row and applies them the same way an offer request does. Nothing is charged.

## Mac location

`MacOfficeLocation` owns a main-actor Core Location manager for the lifetime of `CampSettingsStore`. OS delegate callbacks hop to the main actor; UI reads published state. A confirmed saved geofence is independent of editable draft coordinates. Accuracy bounds, a 20m margin, freshness expiry and a two-fix transition rule avoid turning uncertain positions into arrivals. Sleep/wake and authorization changes clear stale presence. Arrival/departure app notifications carry only office ID and observation time; meal orchestration can subscribe later. See `docs/LOCATION.md`.

## Mac calendars

`MacLunchCalendar` owns EventKit access and publishes only calendar choices, anonymous free intervals and current availability. `CampSettingsStore` configures it from saved meal preferences and office timezone. Calendar selection and event mappings persist locally in UserDefaults; access is always checked against the OS. The service never uploads event content and only writes to its dedicated **camp** calendar. `addOrderEvent` writes a one-off or weekly recurring block; removal first verifies that the event belongs to camp. The reader skips that calendar so camp's own blocks never count as busy. Group and standing-order mutations reach the backend before calendar cleanup. Legacy schedule event IDs are imported only when the local calendar owns them. See `docs/CALENDAR.md`.


## Shared group flow

`CampSettingsStore.lunchGroups` is `GET /v1/groups` for the saved office and today (`backend/src/camp/groups.py`, `groups` table). Every group carries a `category` (`coffee` | `meal`). Creation is `POST /v1/groups`; joining is `POST /v1/groups/{id}/join` with item IDs from that restaurant's full menu. One member can select several items, represented by confirmed `Order` rows, while joining another group leaves only other groups in the same category. Leaving cancels the member's items. Mutations validate office, catalog/category, dietary restrictions, lifecycle and budget before committing atomically.

Standing orders (`/v1/schedules`, `schedules` table) are materialized by `GroupService.today` on refresh, with dates recorded to prevent replaying a skipped occurrence. There is no background scheduler. Restaurant rankings use a review-count-shrunk rating; seeded meal groups skip cafés. Membership drives participant counts and exact delivery-fee allocation. `DemoLunchGroup` is the historical Swift name for the backend shape; `people` excludes the current user. Historical orders retain name, symbol and fee snapshots so catalog removal does not rewrite the ledger.

Today opens a full-menu sheet on both platforms. It keeps errors and the selected cart visible until `joinConfirmed` receives an acknowledgement, then invokes the platform confirmation callback. The Mac notch also offers groups and uses the revision-checked session for selection/review/confirmation. The Mac model calls its asynchronous `onJoin` callback before advancing to confirmed; applying a remote snapshot refreshes membership without issuing another join.

Groups and membership persist in the database; after relaunch Today reloads them with `myOptionIds` and the legacy first-item `myOptionId`. `SessionFile` persists the session and group context for the notch and Live Activity, including all selected item IDs.

## Rendering and input

Location/calendar views observe their own services instead of forwarding every update through the workspace store. EventKit reads use the private `CampCalendarReader` actor and publish anonymous snapshots guarded against stale refreshes. Native map containers are pooled with delegate/gesture cleanup. The map and calendar are 340 points high and capture scrolling only after being clicked.

Finite workspace pages use stable stacks. Card backgrounds avoid masking all their child views. macOS office time pickers build native menu entries once per control; personal lunch timing uses `CampTimingField` with local text drafts, validation, Return/focus-loss commit and formatted values. Save/Discard continues to operate on `CampSettingsStore.draft`.

`CampLogo` caches paths from the preserved SVG and fits them uniformly; it does not load raster assets or require resource-bundle lookup. Changes to the source SVG must be reflected in those cached paths. Spending artwork has a fixed design canvas scaled to a 1.586 aspect ratio.
