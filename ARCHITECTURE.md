# Architecture

## Shared state and presentation

`LunchCore` contains Foundation-only value types and file persistence. `LunchSession.applying` is the sole state transition function. It returns a new value or a meaningful error; it has no UI, network, payment, or ActivityKit dependencies. Dates are injectable and amounts are integer cents.

```text
choosing → reviewing → confirmed → delivered
    ↑          │
    └─ change ─┘

choosing / reviewing / confirmed → ended
```

Expired choosing/reviewing sessions remain readable, but cannot be selected or confirmed. Expiration is derived from `closesAt`, so it doesn't depend on a background timer executing. The local UI reevaluates expiry; ActivityKit uses `staleDate`. Confirmed sessions can finish after the selection cutoff.

An incrementing revision prevents stale buttons from confirming a different meal after a newer selection. Repeated confirm cannot transition an already confirmed state. This is local protection; real order submission still requires a server-issued idempotency key and authoritative quote validation.

`LunchUI` renders the shared card. `LunchCard` accepts an action view: ordinary buttons for Mac/iPhone, App Intent buttons for Live Activities. Platform shell details stay outside the reusable card.

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

The two devices do not currently share state. A backend should become the authority before enabling cross-device confirmation or real money movement.

## Next integration steps

1. Define a backend lunch-offer response with session ID, quote IDs, explicit currency, dietary information, all-in totals, delivery window, and quote expiry.
2. Map a validated offer into `LunchSession` and call the platform's offer/start entry point. On Mac, `offer(_:)` already provides the auto-expansion seam.
3. Add a confirmation service with a submitting state, authoritative price checks, idempotency, retryable errors, and a receipt. Only show an order as placed after the provider acknowledges it.
4. Add backend event delivery and reconcile revisions across devices. APNs would handle iPhone Live Activity updates; choose a separate transport for the running Mac app.
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

`CampWorkspace` and its pages live in LunchUI and support desktop sidebar and compact bottom-tab layouts. The Mac delegate owns persistent workspace and phone-preview windows; status-item left click continues to toggle the existing notch panel. Both Mac preview windows share the same store. iOS uses the compact workspace and opens the original Live Activity controls in a sheet.

Demo group arithmetic compares N separate $6 delivery fees with one shared $6 fee. Taxes, service and tip are shown separately; displayed savings do not claim a live quote. Office policies and dietary preferences are configuration only and are not enforced against fixture meals. Preview connection states are ephemeral and never represent authenticated services.

## Ramp bridge

`backend/server.py` owns Ramp OAuth, read projections and durable sandbox allocation attempts. `CampRampView`/`CampRampModel` connect through a loopback camp endpoint and persist only the non-sensitive pending request in UserDefaults. The server enforces its own allocation cap and active employee lookup; demo office policy is not an authorization source. This local service is not suitable for remote deployment until camp authentication and office membership exist. See `backend/README.md` for its contract and limitations.

## Recommender bridge

`backend/src/camp` is the Python recommender (deterministic filters → scoring → batch optimizer, Jev/LLM only for
classification; see `backend/PLAN.md`). `RecommendationClient` (LunchCore, Foundation-only) posts a `MealContext` built
from `CampConfiguration` and maps the `MealOffer` onto `LunchSession`, so the existing card, panel and Live Activity render
it unchanged. `CampSettingsStore.onOffer` is the seam the Mac delegate uses to call `MacLunchModel.offer(_:)`. The
Developer page (`CampDebugPage`, behind a per-device toggle) renders backend debug JSON loosely via `JSONValue`.
The recommender's offline catalog is real restaurants around Ramp HQ (`backend/src/camp/catalog.py`, see `backend/PLAN.md`);
when the app's office is elsewhere the catalog geometry is re-centred on it, so demo distances stay realistic.
Every confirmed lunch (recommender offer or demo group) is also written to a local `LunchLedger` in UserDefaults by
`CampSettingsStore.recordLunch`; the Spending page derives monthly spend, savings and recent activity from it and shows
sample rows only until the first lunch is recorded. Nothing is charged.

## Mac location

`MacOfficeLocation` owns a main-actor Core Location manager for the lifetime of `CampSettingsStore`. OS delegate callbacks hop to the main actor; UI reads published state. A confirmed saved geofence is independent of editable draft coordinates. Accuracy bounds, a 20m margin, freshness expiry and a two-fix transition rule avoid turning uncertain positions into arrivals. Sleep/wake and authorization changes clear stale presence. Arrival/departure app notifications carry only office ID and observation time; meal orchestration can subscribe later. See `docs/LOCATION.md`.

## Mac calendars

`MacLunchCalendar` owns EventKit access and publishes only calendar choices, anonymous free intervals and current availability. `CampSettingsStore` configures it from successfully saved lunch preferences and office timezone and forwards observable changes. Calendar selection persists separately in UserDefaults; access is always checked against the OS. `CampCalendarView` replaces fixture calendar switches and connection previews. The service does not write events or upload event content. See `docs/CALENDAR.md` for interval rules and the macOS 14 runtime compatibility path.
