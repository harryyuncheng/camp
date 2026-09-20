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

The panel's visibility is independent of lunch state: collapsing or hiding does not cancel a choice. An incoming offer expands even if the last card was collapsed. The current prototype handles one active session, so a new offer replaces the previous one. Confirmation schedules a three-second retraction, scoped to the session ID and revision. Reopening, manual dismissal, or a new offer cancels it. The menu-bar icon remains; left-click toggles the panel and right-click exposes controls.

## iPhone state ownership

`LunchController` owns the app session, persists it before publication, and requests/updates/ends ActivityKit activities. It reconnects to an existing activity after returning to the foreground. If the app stops between writing state and updating ActivityKit, foreground reconciliation publishes the persisted state.

The intent types are included in both app and extension for metadata discovery; `LiveActivityIntent` executes in the containing app process. The extension reads `ActivityViewContext` and does not access the file store. No App Group is required for this arrangement.

The controller rejects concurrent commands while publishing an update. Buttons embed session ID and revision so delayed intent execution cannot act on a replacement lunch. Local confirmation is deliberately distinct from provider order placement.

## Persistence

`SessionFile` atomically writes a versioned JSON envelope. Unknown versions and corruption produce errors rather than silently replacing a saved choice. Mac data lives in Application Support/LunchlineMac; iPhone data is inside the app container. No credentials are stored.

Server-owned state lives in the backend database (`backend/src/camp/store.py`: Postgres via `CAMP_DATABASE_URL`, SQLite otherwise): users and their saved preferences, the catalog, orders, batches, feedback events, lunch groups, Ramp allocation attempts and the shared lunch session. The Swift app never caches these beyond the current screen; every Today/Spending render reads them back through the API, so a change in the database is what the UI shows. Device-only state stays on the device deliberately: calendar selection, the confirmed geofence, connection URLs and the locally persisted lunch session.

The two devices share one lunch through the recommender backend (`LunchSyncCoordinator` in `SessionFile.swift`, `backend/src/camp/sync.py`, persisted in the `sync` table). `LunchSession.applying` stays the single transition implementation; a device publishes the resulting session plus its demo group as a `LunchSyncRecord` with the revision it started from, and the backend compare-and-swaps: same lunch → the expected revision must match and move forward, different lunch → it replaces the current one. A 409 carries the newer record, which the device adopts. Each app long-polls `GET /v1/lunch-session?since=<seq>` (held up to 25 s server-side) and applies records through `MacLunchModel.applyRemote` / `LunchController.applyRemote`; echoes of a device's own write have an equal revision and are ignored. The Mac's group-picker placeholder (`triggerDemo`) is deliberately not published; the phone hears about the lunch when a group is chosen. Identity is a single implicit user for now; real money still needs a server-issued idempotency key and authoritative quotes.

## Next integration steps

1. Define a backend lunch-offer response with session ID, quote IDs, explicit currency, dietary information, all-in totals, delivery window, and quote expiry.
2. Map a validated offer into `LunchSession` and call the platform's offer/start entry point. On Mac, `offer(_:)` already provides the auto-expansion seam.
3. Add a confirmation service with a submitting state, authoritative price checks, idempotency, retryable errors, and a receipt. Only show an order as placed after the provider acknowledges it.
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

`CampWorkspace` and its pages live in LunchUI and support desktop sidebar and compact bottom-tab layouts. The Mac delegate owns persistent workspace and phone-preview windows; status-item left click continues to toggle the existing notch panel. Both Mac preview windows share the same store. iOS uses the compact workspace and opens Live Activity controls in a sheet. Group-menu requests start ActivityKit sessions; confirmed meals reconcile into Today. Group creation and leaving have optional platform callbacks for starting a confirmed activity and ending it. See `docs/IOS.md` for lifecycle and delivery limitations.

Demo group arithmetic compares N separate $6 delivery fees with one shared $6 fee for each nonempty lunch group. Taxes, service and tip are shown separately; displayed savings do not claim a live quote. Office policies and dietary preferences are configuration only and are not enforced against fixture meals. Preview connection states are ephemeral and never represent authenticated services.

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

`MacLunchCalendar` owns EventKit access and publishes only calendar choices, anonymous free intervals and current availability. `CampSettingsStore` configures it from successfully saved lunch preferences and office timezone and exposes it to directly observing calendar views. Calendar selection persists separately in UserDefaults; access is always checked against the OS. `CampCalendarView` replaces fixture calendar switches and connection previews. The service does not write events or upload event content. See `docs/CALENDAR.md` for interval rules and the macOS 14 runtime compatibility path.


## Shared group flow

`CampSettingsStore.lunchGroups` is `GET /v1/groups` for the saved office and today (`backend/src/camp/groups.py`, `groups` table). Creation is `POST /v1/groups` at a catalog restaurant; joining is `POST /v1/groups/{id}/join`, which the backend treats as one lunch per person per day (it leaves any other group) and which upserts a confirmed `Order` for the member; leaving is a `DELETE` that cancels it. Participant counts, delivery-fee shares, per-option prices, `peopleOrdering` and `totalSavingsCents` are computed server-side from real membership. `DemoLunchGroup` keeps its historical name as the Swift shape of a group row; `people` excludes the current user so the optimistic local join still renders correctly.

The Mac delegate subscribes the model to the workspace group list and joined-group ID. Today routes View menu through `requestDemoGroup` to `MacLunchModel.chooseGroup`. The notch first offers groups, then uses the existing revision-checked meal session for selection/review/confirmation. Successful confirmation calls `onJoin`, updating the workspace. The list scrolls within a bounded height. Compact hosts without this callback use a menu sheet and explicit local confirmation.

Groups and membership persist in the database; after relaunch the group picker and Today reload them and membership comes back with `myOptionId`. `SessionFile` still persists the local meal session for the notch and Live Activity.

## Rendering and input

Location/calendar views observe their own services instead of forwarding every update through the workspace store. EventKit reads use the private `CampCalendarReader` actor and publish anonymous snapshots guarded against stale refreshes. Native map containers are pooled with delegate/gesture cleanup. The map and calendar are 340 points high and capture scrolling only after being clicked.

Finite workspace pages use stable stacks. Card backgrounds avoid masking all their child views. macOS office time pickers build native menu entries once per control; personal lunch timing uses `CampTimingField` with local text drafts, validation, Return/focus-loss commit and formatted values. Save/Discard continues to operate on `CampSettingsStore.draft`.

`CampLogo` caches paths from the preserved SVG and fits them uniformly; it does not load raster assets or require resource-bundle lookup. Changes to the source SVG must be reflected in those cached paths. Spending artwork has a fixed design canvas scaled to a 1.586 aspect ratio.
