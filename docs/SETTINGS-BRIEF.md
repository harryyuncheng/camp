# Next task: camp settings and group-order overview

Build a native SwiftUI window beside the existing menu-bar/notch experience. This is the configuration and visibility surface for Corporate Autonomous Meal Protocol. The product's central workflow is joining a pending office group order to reduce firm-wide delivery costs.

## Scope

Four sidebar destinations:

1. **Today:** current office group, restaurant, participant count, cutoff/countdown, delivery window, the user's chosen meal, and estimated shared delivery cost. Show whether the user has joined, and whether the group is still collecting or has actually been placed. Include a fixture scenario with three people sharing one cart. Show company savings with a labelled comparison baseline; never invent realized savings.
2. **You:** office selection, dietary/allergy requirements and dislikes, usual lunch window, minimum lunch duration, meeting buffer, selected calendars, reminder/snooze preference, and a visible manual office-presence override for demos.
3. **Office:** delivery address and coordinates/radius; timezone, group cutoff and delivery windows; per-person and group budget caps; fee-sharing rule; minimum useful group savings; fallback when batching fails (ask, wait for another group, or skip). Policy changes are admin-only in the connected design. Fixture demo-admin controls must be visibly labelled.
4. **Connections:** backend and Ramp sandbox status, calendar permission and selection, location permission/current presence, recommendation service mode, and ordering provider state (mock, unavailable, connected). No credential entry for Ramp client secrets. Initially implement honest mock/not-configured states with interfaces that later integration agents can replace.

## Interaction requirements

- Open the window from the menu-bar context menu, with a clear “Open camp” / “Settings…” action. Preserve left-click toggle for the notch panel.
- One app-level observable configuration store with versioned persistence and validation. Use stable IDs so changing a display name does not break membership/configuration.
- Separate personal preferences from authoritative office policy. Prevent an employee setting from increasing a server-approved budget.
- Keep business rules outside view code; use the same typed values in future service adapters.
- A permission toggle does not grant OS permission. Show a request action and truthful status. No automatic location/calendar permission prompts before the relevant integration is implemented.
- Label fixtures and simulated connections. Save preferences across restart. Invalid caps, radius, or time ranges should produce inline errors.
- The window should not steal focus when a lunch invitation arrives; only open it on explicit user action.
- Preserve the persistent notch hosting view, smooth reverse animation, and three-second retraction. The future group flow retracts after a successful join acknowledgment, not before the backend accepts membership.

## Data and integration boundary

Use `UserPreferences`, `OfficePolicy`, `ConnectionStatus`, and a read-only `GroupSessionSummary`. Refer to `INTEGRATION-PLAN.md` for the proposed shared contracts. Begin with fixtures; do not implement Ramp, provider checkout, or recommendation logic in this UI task.

Suggested ownership: new `Sources/LunchMac/Settings/` views/store and shared configuration models. Coordinate changes to `LunchMacApp`, project/package source membership, and shared domain files with the integration owner. Existing source and target names still use Lunchline internally; user-facing branding is camp.

## Acceptance

Open from the menu bar → configure a fixture office and personal lunch window → save → relaunch → values persist. Today shows one collecting group with three participants and a distinct simulated placed-order state. Non-admin policy controls are read-only, disconnected services look disconnected, and existing notch interactions still work.
