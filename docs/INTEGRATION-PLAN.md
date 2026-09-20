# camp integration plan

> Historical planning document. For implemented behavior, see [README](../README.md) and [architecture](../ARCHITECTURE.md). The workspace now has five tabs, shared Mac notch/group joining, group creation, typed lunch timing, Ramp sandbox, Mac location and Mac calendars. Production orchestration, checkout and cross-device sync remain future work.

Goal: make it easy for employees to join a compatible pending office group order, reducing company delivery costs and coordination time. Presence, calendars, and preferences determine who can join and when; recommendations fill a shared cart. Group ordering is core scope, not a later enhancement.

This is an implementation handoff, not implemented functionality. Current Mac confirmation only saves a local demo choice. Work in this project; preserve the existing notch panel, persistent hosting view, and three-second confirmation retraction.

## Build order and ownership

| Task | Owner | Dependency | Done when |
| --- | --- | --- | --- |
| 0. Shared contracts + backend skeleton | Integration agent | None | Office policy, preferences, group sessions, offers, and joins share versioned contracts |
| S. Settings + Today window | Mac UI agent | Configuration contracts from 0 | Office rules and personal preferences persist; Today displays a fixture group session |
| G. Pending group order service | Group-order agent | Contract 0 | Compatible employees can join/edit/leave before a cutoff; one submit attempt per group |
| 1. Ramp sandbox adapter | Ramp agent | Contract 0 | A bounded sandbox spending allocation is linked to the group checkout, with company payer and per-person budget accounting |
| 2. Office presence | Location agent | Contract 0 | Inside/outside/unknown works with real location and deterministic fixtures |
| 3. Lunch availability | Calendar agent | Contract 0 | Busy intervals produce realistic lunch windows, including permission-denied behavior |
| 4. Recommendation bridge | Partner + integration agent | Contract 0; fixtures initially | Partner response recommends meals compatible with the pending group cart and each participant |
| 5. Eligibility + group checkout orchestration | Integration agent | S, G, 1–4 | Multiple participants join; cutoff produces one mocked-provider checkout backed by Ramp sandbox |
| 6. DoorDash adapter | Ordering agent | Approved CLI account + contract 0 | Actual quote/order/status map to the same provider interface |

Build order: 0 → S → G → 1 → 2 → 3 → 4 → 5. Once the contracts are agreed, the provider adapters can also proceed independently. Do not make DoorDash access a prerequisite. Start with a single office, company-funded meals, and one restaurant/cart per group; only support broader aggregation when a provider demonstrably supports it.

## 0 — Shared contracts and backend

Use the partner's existing backend if available; otherwise a small TypeScript HTTP service is sufficient. Add a durable local database for order attempts and deduplication. Keep Ramp client credentials on this service. The Mac authenticates to camp; the server maps the authenticated identity to the Ramp user and office policy, rather than trusting client-supplied IDs or budgets.

Agree these versioned shapes before the agents implement their adapters:

- `OfficePresence`: office ID, `inside | outside | unknown`, observed time, expiry, reason, `live | manual | fixture` source.
- `LunchAvailability`: permission/data status, `busyNow`, free intervals, observed time. Missing access is not an empty/fully-free calendar.
- `OfficePolicy`: version, office address/geofence, timezone, group cutoff/delivery windows, per-person and group caps, fee-allocation rule, minimum worthwhile savings, fallback behavior, company payer reference. Admin-managed and authoritative on the server.
- `UserPreferences`: selected office/calendars, dietary requirements, usual lunch window, lunch duration, notification preferences. Permission states come from the OS; switches cannot pretend access was granted.
- `GroupSession`: group ID/version, office, provider/store/cart references, cutoff, delivery window, participants, cart version, quote status, company payer, and `collecting | locked | submitting | placed | failed | statusUnknown` state.
- `MealContext`: office ID, presence, lunch windows, user preferences, dietary constraints, budget currency/cents, requested arrival window, context version, compatible pending groups and their estimated marginal cost.
- `MealOffer`: offer ID/version, expiry, office/group ID, up to three options. Each option has a stable ID, provider/item references, total cents/currency, delivery window, explanation, and `estimated | quoted | fixture` pricing. Include quote ID/expiry when real; comparison baseline and its provenance when displaying savings.
- `JoinGroup`: group/offer ID and version, option ID, approved all-in per-person ceiling, client request ID. The server resolves policy, price, identity, and membership; this reserves a spot in a pending cart, not a placed order.
- `OrderAttempt`: attempt ID, stable provider idempotency key, group/cart version and participant allocations, status, Ramp fund/card references, provider order ID, error/retry status, receipt reference.

Proposed camp endpoints: `GET /office-policy`, `PUT /preferences`, `GET /group-sessions`, `POST /meal-offers`, `POST /group-sessions/{id}/participants`, participant update/leave operations, and `GET /order-attempts/{id}`. Group checkout is a server-owned operation after cutoff, not a charge triggered by every participant click. Start with polling. A transport adapter converts an offer to the current `LunchSession`; `MacLunchModel.offer(_:)` already opens or updates the panel.

## S — Settings and Today window (next UI task)

Build a normal SwiftUI app window opened from camp's menu bar. Keep the notch panel for quick invitations and confirmations. See `SETTINGS-BRIEF.md` for the agent's scoped UI task.

Sections: Today (pending office group, joined meal, cutoff, estimated/actual savings), You (dietary needs, lunch window, calendars, notifications), Office (address/geofence, group schedule, budgets, sharing/fallback rules), and Connections (Ramp sandbox/backend, calendar, location, recommendation endpoint, ordering provider status). Office policy is admin-editable; employee clients cannot raise their own company budgets. For the standalone fixture demo, provide an explicitly labelled demo-admin mode.

Use typed/versioned settings with one observable store and mock connection states first. Integrations replace mocks through interfaces. Offer a separate permission button, connection status, and retry action. A user-visible toggle must never claim that an unimplemented integration is connected. Do not put Ramp client secrets or full card numbers in this window.

## G — Pending group order service

Prefer a compatible collecting session at the same office, provider/store, delivery window, and cutoff. If none exists, create a candidate session under office policy. The group service determines compatibility and validates constraints; the model ranks options within them. A submitted/placed order is closed to joins unless a provider explicitly supports amendment.

Each person's confirmation atomically joins or updates their membership, with a per-person price ceiling and budget reservation. Permit edits/withdrawals before cutoff. Deduplicate participants and requests; recheck cutoff and group version in the same transaction as the join. At cutoff, lock a snapshot, refresh the combined quote, check every allocation and the total cap, prepare the group's Ramp spending permission, then submit once. An unresolved submission is reconciled before retrying.

The final shared fee can change when someone joins/leaves. Show pre-cutoff figures as estimates. If the final per-person total exceeds someone's approved ceiling, request a new confirmation or use the explicitly selected fallback; do not silently raise it. Default fallback: ask whether to order individually or skip. Do not silently turn a group opt-in into a more expensive individual purchase.

Track food, tax, delivery, service fee, tip, and discounts separately. Split shared costs using the configured rule and deterministic cent rounding; allocated totals must sum to the actual group total. Keep company subsidy and employee payment separate if introducing split funding later.

Savings benchmark: compare separate-order quotes for the same meals/address/time/service level against the combined group quote. Report delivery-fee savings separately from total company savings; higher food costs, service fees, tips, or lost discounts can erase an apparent delivery saving. Until actual quotes exist, label estimates and retain their provenance.

Acceptance: three fixture employees join one cart; edits/withdrawals update allocations; incompatible restaurant/window does not join; a cutoff race rejects late changes; one checkout occurs; stale retries cannot duplicate it; below-threshold groups follow the configured fallback; arithmetic reconciles to the receipt.

## 1 — Ramp sandbox

Agent task: implement `BudgetService`/`RampClient` on the backend, with fixtures and sandbox-only configuration. First verify the existing sandbox application's credentials, allowed scopes, test user, and supported card/fund endpoints. Use a configured test budget for the first iteration; do not invent a Ramp remaining-budget field.

At group checkout, enforce each participant allocation and the all-in group amount against office policy, then issue or reuse a tightly bounded fund/card for the company-funded group attempt. Reserve individual budgets when people join; do not create a separate checkout/card for every click. Maintain the participant allocation ledger alongside the single group charge. Save non-sensitive identifiers and status. Card issuance is spending permission, not an order or a completed charge.

Ramp documents a Funds-backed virtual-card flow and a Vault option (`POST /developer/v1/cards/vault`) for server-side payment details. Vault is available in sandbox; production needs separate approval. Its guide currently lists `cards:read_vault` and `limits:write`, with `funds:write` for backing-fund termination. Verify the specific path and scopes against the account. Keep card numbers/CVV out of logs, the model, and the Mac UI. [Virtual Cards guide](https://docs.ramp.com/developer-api/v1/virtual-cards)

Acceptance: approved amount succeeds in sandbox; camp rejects over-budget attempts; duplicate confirmation creates no duplicate allocation; expired quotes fail before issuance; credentials missing/expired produce actionable errors. Separately test issuer enforcement with supported sandbox simulation—do not label a local camp rejection as a Ramp issuer decline.

Ramp sandbox uses separate credentials and `https://demo-api.ramp.com`; it cannot process real money. A sandbox card cannot pay for a real DoorDash meal. [Sandbox setup](https://support.ramp.com/accessing-the-developer-api)

## 2 — Office location

Agent task: add `OfficePresenceService` under `Sources/LunchMac/Services/Location/`. Use `CLLocationManager` and office latitude/longitude/radius. Refresh while the app is running, around the lunch window, and after wake; region monitoring may supplement this when supported, but a fresh reading should establish current presence.

Evaluate horizontal accuracy and reading age, not just distance. A reading overlapping the boundary, stale reading, disabled location, or denied access yields `unknown`. Add hysteresis/debouncing to avoid repeated arrival prompts at the boundary. Keep raw coordinates on-device; send office ID and derived presence to the recommendation service.

Add an explicit permission/setup screen and a visible manual office override for the demo. Add the macOS location usage description; include the location entitlement if enabling App Sandbox. This detects the Mac's location, so do not represent a laptop left at the office as proof the person is there. [Apple location setup](https://developer.apple.com/documentation/corelocation/configuring-your-app-to-use-location-services)

Acceptance: inside, outside, uncertain boundary, stale reading, denied permission, and wake-up refresh are covered by fixtures. An unknown result offers manual input rather than silently assuming presence.

## 3 — Calendar availability

Agent task: add `LunchAvailabilityService` under `Sources/LunchMac/Services/Calendar/`. Start with EventKit calendars already connected to macOS. Let the user choose work calendars; Google/Microsoft OAuth can be a later adapter if their calendar is not synced locally.

Merge overlapping busy events and find, initially, a configurable 30-minute free lunch window between 11:30 and 14:30, with a five-minute meeting buffer. Ignore cancelled, declined, and explicitly free events. Treat tentative/unknown availability conservatively; make the treatment of all-day events explicit. Distinguish “busy now, defer the prompt” from “no lunch window, suppress this offer.” Fit the delivery estimate and eating time into the chosen window.

Recompute on calendar changes, timezone changes, wake, and before an offer is accepted. Send free/busy intervals to the model, not meeting titles or attendees. EventKit requires full access to read events; camp can still behave as read-only. Add the required usage strings and calendar entitlement if sandboxed. [EventKit access](https://developer.apple.com/documentation/eventkit/accessing-the-event-store)

Toolchain caveat: the project was built here with Xcode 14.3.1. `requestFullAccessToEvents` is a macOS 14+ API requiring a newer SDK; use Xcode 15+ and a macOS 13 fallback if retaining that deployment target. An availability check alone cannot expose APIs missing from the compiler's SDK.

Acceptance: overlapping meetings, timezone/DST boundaries, declined/free events, all-day policy, selected calendars, permission denial, and no available lunch window have deterministic cases.

## 4 — Partner recommendation bridge

Agent task: agree the `MealContext → MealOffer` contract with the partner. Prefer meals in an already viable shared cart and recommend a compatible new group only when needed. Optimize company all-in cost and employee convenience subject to dietary/time constraints. The model ranks and explains; deterministic code validates availability, dietary constraints, quote freshness, and budget. If only one or two feasible options exist, show fewer rather than inventing meals.

Support captured JSON fixtures so the Mac can iterate while the model changes. A response for an old context/version must not replace a newer offer. Keep estimated prices visibly estimated until the provider returns an actual all-in quote.

## 5 — Orchestration and UI wiring

Agent task: implement `MealCoordinator`, the only owner of offer timing and integration into `MacLunchModel`.

Flow: verify office/context → match a compatible pending group → request meal recommendations → validate response → display group invitation → confirm membership → collect until cutoff → lock/requote/check caps → prepare group Ramp spending permission → submit once → reconcile receipt and allocations.

Add separate membership and group-checkout states: `joining`, `joined`, `locked`, `submitting`, `placed`, `failed`, and `statusUnknown`. After the server acknowledges membership, show “You’re in · order closes at 12:05” and retract after three seconds. Later display checkout/delivery updates. Only the provider acknowledgment means “order placed.” Mock/sandbox outcomes remain labelled simulated. Errors stay visible; do not retract on an unacknowledged join.

Use one active lunch participation per employee/window, context and group versions, offer expiry, and durable membership and checkout records. If provider submission times out, reconcile before retrying; never blindly place a second order. Recheck context before submission, but do not automatically cancel an already placed order when someone leaves the office.

One integration owner edits `LunchSession`, `MacLunchModel`, `LunchMacApp`, the panel, project file, package target wiring, entitlements, and Info.plist. Other agents own their service folders and document required config changes. This avoids parallel edits breaking the app.

## 6 — DoorDash, when access arrives

Define `OrderingProvider` now: search/menu, quote, submit, status, receipt. Use a mock implementation first. Later wrap the official `dd-cli`, validating its installed version and command help, with structured arguments, timeouts, and bounded output.

The official CLI is waitlist-only. Its README documents saved card payment methods, pricing previews, checkout, status, and receipts; do not assume it can attach a freshly issued Ramp card. Prove that payment handoff separately. [Official CLI](https://github.com/doordash-oss/doordash-cli)

## Demo and follow-on tasks

First demo: three employees at one office with compatible calendars → recommendations from one restaurant → each confirms “Join office order” → camp retracts after join acknowledgment → cutoff → one group Ramp sandbox spending allocation → one simulated provider checkout → receipt with per-person allocations and firm-wide fee savings. Show the actual quote comparison used for savings; label any time-saved estimate as estimated.

Inputs to configure: office coordinates/radius, selected calendars, lunch window/buffer, test employee mapping, budget/currency, backend URL/app authentication, Ramp sandbox credentials and scopes, partner endpoint or fixture. Keep secrets in local/backend environment configuration, not agent prompts.

Later tasks: production provider access, richer preference learning, cross-device state, split company/employee funding, cancellation/refunds, multiple offices, and launch-at-login. Keep these separate from the first complete flow.
