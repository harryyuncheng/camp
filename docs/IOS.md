# camp for iPhone

The native iPhone app and embedded WidgetKit extension share camp’s existing workspace, meal model, branding and App Intents. iOS 17 is the minimum for interactive meal buttons. This is a local demo companion; there is no Mac-to-phone synchronization yet.

## Develop on this Mac

1. Install Xcode 15 or newer, choosing a release compatible with your Mac and eventual phone OS. This machine now has Xcode 16.2 selected; complete its first-launch setup and license agreement before building. Install an iOS 17+ Simulator runtime in Xcode Settings → Platforms (Components in newer releases).
2. Open `Lunchline.xcodeproj`. Choose the **Lunchline** scheme (the app displays as **camp**), then an iPhone simulator. Run the app; Xcode embeds **LunchlineActivity** automatically.
3. An unsigned simulator build is also available through `bash scripts/build-ios.sh`. It uses the machine’s selected Xcode without changing that selection. Override `DEVELOPER_DIR` if the newer Xcode has a different location.
4. Today → a group’s **View menu** starts that group’s Live Activity and opens the existing lunch sheet. Select, review and confirm either in the app or on the activity. Create group → Create & join also starts a confirmed activity. Leave ends the current activity.
5. **Preview lunch invitation** opens the existing demo controls. **Start demo lunch** starts a fresh sample. Close the sheet, background camp and lock the simulator to inspect the Lock Screen. On a Dynamic Island simulator, long-press the island for meal controls. Apple controls when the island expands; camp cannot force it open.
6. **Simulate arrival** completes the activity. **End lunch** dismisses it. Tapping the activity body opens the lunch sheet through `camp://lunch/<session-id>`; legacy `lunchline://` links still work.

No Apple account, push certificate or Ramp credentials are needed for local simulator development. The build helper exits with an actionable message when Xcode is too old. It does not install Xcode or run tests.

## Run on your phone later

- Use Xcode with SDK/device support matching your phone’s installed iOS.
- Add your Apple account in Xcode Settings → Accounts.
- Copy `Config/Local.xcconfig.example` to `Config/Local.xcconfig`; set your development team and a unique bundle prefix. The local file is ignored by Git. Both app and extension inherit it, with `.activity` appended for the extension.
- Connect/trust the phone, enable Developer Mode when requested, select the phone in Xcode, and Run. Automatic signing must succeed for both targets.
- Enable Live Activities for camp in iPhone Settings if disabled. Start a lunch while camp is foregrounded, then lock the phone.

## Lifecycle and integration boundary

`LunchController.present(_:group:)` is the main-actor entry point for a future incoming invitation. It requires a fresh choosing session with one to three unique options, checks the combined ActivityKit payload size, and replaces the previous local activity. `start(group:office:)` creates fixture invitations. For demos outside lunch hours, arrival is at least 35 minutes in the future.

The controller persists the meal session before publishing changes. Revision checks reject outdated buttons. App Intents execute in the containing app process; the extension renders ActivityKit state without accessing the app’s files. Group context travels in activity attributes, so returning to an active activity restores its group and confirmation into Today. Created group lists are otherwise in-memory; after the activity ends and the process restarts, complete group history is not restored.

The app supports Lock Screen and compact, minimal and expanded Dynamic Island presentations. The activity uses a short, phone-specific composition of the existing camp styling; the desktop card is too tall for the Lock Screen’s limited height. No notification permission is requested for locally started activities.

Automatic invitations while the phone app is closed are a separate integration: use ActivityKit push-to-start (iOS 17.2+), per-device token registration, an authenticated backend and APNs credentials/capability. Server reconciliation must also propagate phone confirmations back to the shared order. Those services and push entitlements are deliberately not represented as connected in this local build. No background polling is used.

## Current verification limit

The initial build stopped at the Xcode 14.3.1 version preflight. After upgrading, Xcode 16.2 is selected, but SDK/build commands are blocked until its license agreement is accepted. No successful iOS compilation, simulator launch or device interaction is claimed. Device signing, final layout and intent execution still need checking once a supported Xcode is installed.

## Apple references

- [Displaying live data with Live Activities](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)
- [LiveActivityIntent](https://developer.apple.com/documentation/appintents/liveactivityintent)
- [Starting and updating Live Activities with push notifications](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications)
