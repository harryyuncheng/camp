# Development guide

This repository contains native Swift clients and one Python backend. For device rehearsal steps and network setup, see the [demo runbook](DEMO.md). For state ownership and platform details, see the [architecture notes](../ARCHITECTURE.md).

## Build the native apps

Open `Lunchline.xcodeproj`, choose **LunchlineMac → My Mac**, and run. Or build and open the Mac app from the repository root:

```sh
bash scripts/build-mac.sh --open
```

The Mac build helper requires Xcode 14.3 or newer with command-line tools installed. It creates `dist/camp.app` and applies a local development signature; the signature is not for distribution. Set `DEVELOPER_DIR` if the desired Xcode is not selected by default.

For the iPhone app, choose the **Lunchline** scheme. Simulator builds, signing setup, and phone deployment are documented in [iPhone development](IOS.md). Both apps share the Swift sources and domain model; the iOS target also embeds the ActivityKit presentation extension.

The native project has no external Swift package dependencies. Existing `Lunchline` source and scheme names remain while the app is branded and packaged as camp.

## Code map

| Concern | Source |
| --- | --- |
| Meal/group fixtures, prices, deadlines, and session transitions | `Sources/LunchCore/LunchSession.swift` |
| Meal cards, vector logo, colors, typography, confirmation layout | `Sources/LunchUI/LunchCard.swift` |
| Notch placement, animation, collapse, panel shell | `Sources/LunchMac/NotchPanel.swift` |
| Incoming lunch event and Mac persistence | `Sources/LunchMac/MacLunchModel.swift` |
| Menu-bar controls and application lifecycle | `Sources/LunchMac/LunchMacApp.swift` |
| Today feed, create-group form, and summary cards | `Sources/LunchUI/CampTodayPage.swift` |
| Settings, demo group list, and membership | `Sources/LunchUI/CampSettingsStore.swift` |
| Editable time parsing and shared controls | `Sources/LunchUI/CampComponents.swift` |
| iPhone ActivityKit lifecycle | `iOS/Lunchline/LunchController.swift` |
| Live Activity button intents | `iOS/Lunchline/LunchIntents.swift` |
| Lock Screen and Dynamic Island presentations | `iOS/LunchlineActivity/LunchlineLiveActivity.swift` |

## Integration seams

- **Recommendations:** the Swift client sends a `MealContext` to the Python service and receives a `MealOffer`. On Mac, `MacLunchModel.offer(_:)` is the entry point that saves an offer and expands the notch panel. The backend contracts and service setup are in [backend/README.md](../backend/README.md); the design is in [backend/PLAN.md](../backend/PLAN.md).
- **Groups and orders:** the backend database is authoritative for group membership and the order ledger. The clients update their views after acknowledged API mutations.
- **Mac and iPhone sync:** active orders are shared through the backend, long-polled while camp is foregrounded and — with the `CAMP_PUSH` build flag plus `CAMP_APNS_*` backend credentials — pushed via APNs while backgrounded or closed (update and push-to-start). See the [architecture notes](../ARCHITECTURE.md).
- **Location and calendars:** macOS uses on-device Location Services and EventKit; the app does not upload calendar event content. See [location behavior](LOCATION.md) and [calendar behavior](CALENDAR.md).

Build history and device checks are recorded in [VALIDATION.md](../VALIDATION.md). Use the [demo runbook](DEMO.md) for the current end-to-end acceptance flow.
