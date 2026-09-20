# camp

**Corporate Autonomous Meal Protocol.**

## Ramp sandbox integration

The Connections screen now connects to Ramp through a local Python backend, lists active sandbox employees, and can create a bounded restaurant fund with linked-card references. Credentials stay on the backend. See [setup and API details](backend/README.md).

```sh
cp backend/.env.example backend/.env
# Add your sandbox credentials to backend/.env.
python3 backend/server.py
```

Open camp → Connections → **Connect / refresh sandbox**. Choose the company payer and allocation before clicking **Create sandbox fund**. No food order or charge is placed.

## Mac office location

Office and Connections now use macOS Location Services. Use **Search** or **Find me** on the map, click to place your office circle, adjust its radius, and click **Confirm office**. The location card shows in-office/away/unknown and the latest arrival details. Tracking runs while camp is open and awake. See [location setup and behavior](docs/LOCATION.md).

## Mac calendars

Open **Connections → Connect calendars**, allow full calendar access, and select the calendars that should block lunch. Google, Outlook and iCloud calendars work when already synced in the Mac Calendar app. Available windows appear in You and Connections. Your saved lunch duration, window and meeting buffer determine which gaps fit. camp does not create or edit events. See [calendar setup and behavior](docs/CALENDAR.md).

## Configuration workspace

The Mac app now opens a light camp workspace with lime accents. The dark notch panel remains available through the menu-bar icon or **Preview lunch invitation**. Right-click the camp menu-bar icon for **Open camp**, **Settings**, and **iPhone layout preview**.

The shared workspace has five SwiftUI screens:

- **Today:** open a completed coffee receipt, browse three demo lunch groups, create a group, choose/change/leave a meal, and see lunch-group savings and participant totals.
- **You:** food preferences, editable lunch timing, calendar selection and notification preview settings.
- **Office:** demo-admin toggle, address/geofence coordinates and radius, budgets, timing, fee sharing and group rules.
- **Spending:** a credit-card-shaped preview, sample budget and transactions; no live card connection.
- **Connections:** live Ramp sandbox bridge, Mac location and calendars, plus placeholders for recommendations and DoorDash.

Use **Save** to persist settings on this device, or **Discard** to revert. Office settings become read-only when demo admin is off. There is no cross-device sync. Ramp makes sandbox API requests through the local bridge. Mac presence uses on-device Location Services; calendar availability uses locally synced EventKit calendars. Group orders and other connections are simulated; no food orders or payments are made. Mac notch confirmations update the workspace’s selected group and meal. The original iPhone Live Activity flow remains separate.

The Mac **iPhone layout preview** uses the same compact SwiftUI workspace as the iPhone app. It is a layout preview, not an iOS simulator. The installed Xcode 14.3.1 cannot build this project's iOS 17 Live Activity target; use Xcode 15 or newer with an appropriate device SDK and signing team.

## Today demo and editable timing

- **Create group** selects a demo restaurant, delivery time and meal, then adds and joins a new group. One lunch choice is active at a time; joining a different group replaces it. New groups start with just you and zero delivery savings.
- **Total savings** and **People ordering** summarize today's lunch groups, excluding coffee. Savings compare a $6 delivery for each person with one $6 shared delivery per nonempty group. They are demo estimates, not live quotes.
- The notch lists the same groups, including newly created ones. **Preview lunch invitation** opens group selection; confirmation updates Today and retracts to the menu bar after three seconds.
- In **You → Lunch timing**, type times such as `1pm`, `13:30` or `1330`, then press Enter or leave the field. Unsuffixed times use the 24-hour clock. Duration and buffer are typed in minutes. Invalid input leaves the last valid draft value unchanged; **Save** applies valid preferences to the calendar service.
- Demo groups reset on restart. Settings persist locally. Rebuilding with the development signature may require reconnecting OS calendar/location permissions.

## Branding and layout

The supplied logo is preserved in `Branding/camp.svg`. `CampLogo` in `LunchCard.swift` caches its vector paths without the white background, fits their aspect ratio and inherits the surface color. It is used in the sidebar, compact header, notch, shared meal card and menu-bar template image. The expanded notch header uses the mark plus **camp**. The sidebar mark aligns with the wordmark baseline and navigation icons.

Spending's demo card uses a 1.586 aspect ratio, caps its width at 400 points and scales its artwork uniformly on compact layouts. Workspace pages use stable stacks; macOS office-time menus use native controls. Map views are pooled, and calendar reads run away from the UI thread. Frame-rate improvements have not been benchmarked.

## Native lunch assistant

A small native lunch assistant POC. The Mac app opens an interactive panel beneath the notch when a lunch event arrives. Pick a lunch group, choose one of its meals, review the price, and confirm. Meal choices use fictional data; confirmation records a local choice and never places an order. Ramp sandbox account data is fetched separately in Connections.

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

## Optional iPhone Live Activity

The original iPhone app + WidgetKit extension remain included, using the same domain and card layout. Mac and iPhone currently keep independent local sessions; they don't sync to one another.

1. Use Xcode 15+ to compile the iOS 17 APIs, or a newer Xcode compatible with your phone's installed iOS.
2. Open `Lunchline.xcodeproj`, select the **Lunchline** scheme.
3. Change `BUNDLE_ID_PREFIX` in `Config/Shared.xcconfig` to your own identifier.
4. Select the same signing team for **Lunchline** and **LunchlineActivity**. Enable automatic signing.
5. Connect your iPhone, enable Developer Mode if prompted, and run.
6. Tap **Start demo lunch**, then open the Lock Screen or expand the Dynamic Island.

`NSSupportsLiveActivities`, extension embedding, intents, and the `lunchline://` URL scheme are configured. No App Group or APNs entitlement is required for this local demo: `LiveActivityIntent` executes in the app process, and the extension renders ActivityKit content.

The iPhone app can also supply Apple's mirrored Live Activity on macOS Tahoe 26+, but the standalone Mac notch panel is the primary Mac experience. See [Apple's mirroring setup](https://support.apple.com/en-us/120684) if you want to compare them.

## Verification and limits

- Thirteen domain/geometry/timing tests cover state transitions, persistence, notch placement, and confirmation deadlines. Three AppKit lifecycle tests also check view identity, fixed top edge, actual window hiding, explicit reopening, and cancellation when a new offer arrives. AppKit tests require a macOS desktop session and skip without one.
- Mac build and interaction results are recorded in `VALIDATION.md`.
- iOS 17 compilation and physical-device Live Activity interactions need a newer Xcode than the 14.3.1 installed on this machine. The iOS portion is scaffolded, not device-validated.
- Meals, coffee history, spending transactions, savings and arrival windows are demo fixtures. Ramp sandbox, Mac location and Mac calendar access are implemented separately. Recommendations, provider checkout and real payments are not connected.
- The Mac panel is a normal floating utility window, not a system notification; Focus mode does not automatically suppress it. Add your own quiet-hours/Focus policy before real reminders.

See `ARCHITECTURE.md` for state ownership and the integration boundary.
