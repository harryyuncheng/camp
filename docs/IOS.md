# camp for iPhone

The native iPhone app and embedded WidgetKit extension share camp’s existing workspace, meal model, branding and App Intents. iOS 17 is the minimum for interactive meal buttons. Lunches sync with the Mac through the recommender backend while camp is in the foreground (see the [architecture notes](../ARCHITECTURE.md)); a lunch chosen in the Mac notch starts the phone's Live Activity, and Lock Screen taps update the notch.

## Develop on this Mac

1. Install Xcode 15 or newer, choosing a release compatible with your Mac and eventual phone OS. The historical Xcode 16.2 results below apply to that revision and machine. Install an iOS 17+ Simulator runtime in Xcode Settings → Platforms (Components in newer releases).
2. Open `Lunchline.xcodeproj`. Choose the **Lunchline** scheme (the app displays as **camp**), then an iPhone simulator. Run the app; Xcode embeds **LunchlineActivity** automatically.
3. An unsigned simulator build is also available through `bash scripts/build-ios.sh`. It uses the machine’s selected Xcode without changing that selection. Override `DEVELOPER_DIR` if the newer Xcode has a different location.
4. Today → a group’s **View menu** opens its full menu. Choose one or more items and join; a successful backend response starts a confirmed activity. Existing activity controls also support selection, review and confirmation. Create group → Create & join starts a confirmed activity. Leave removes that group's shared session.
5. After joining or creating an order in Today, background camp and lock the simulator to inspect the Lock Screen. On a Dynamic Island simulator, long-press the island for order controls. Apple controls when the island expands; camp cannot force it open.
6. Tapping the activity body returns to Today through `camp://lunch/<session-id>`; legacy `lunchline://` links still work. Manage the order with **Change order** or **Leave** in Today. The iPhone has no separate demo/activity control screen; **Simulate arrival** remains available in the Mac notch for demoing delivery.

No Apple account, push certificate or Ramp credentials are needed for local simulator development. The build helper exits with an actionable message when Xcode is too old. It does not install Xcode or run tests.

## Run on your phone later

- Use Xcode with SDK/device support matching your phone’s installed iOS.
- Add your Apple account in Xcode Settings → Accounts.
- Copy `Config/Local.xcconfig.example` to `Config/Local.xcconfig`; set your development team and a unique bundle prefix. The local file is ignored by Git. Both app and extension inherit it, with `.activity` appended for the extension.
- Connect/trust the phone, enable Developer Mode when requested, select the phone in Xcode, and Run. Automatic signing must succeed for both targets.
- Enable Live Activities for camp in iPhone Settings if disabled. Start a lunch while camp is foregrounded, then lock the phone.
- For real-time updates while camp is backgrounded or closed (APNs push-to-update and push-to-start), the Apple account needs a *paid* Developer membership: uncomment `CAMP_PUSH_ENTITLEMENTS` and the `CAMP_PUSH` compilation condition in `Config/Local.xcconfig`, then run once on the phone so it registers its push tokens with the backend. The backend needs `CAMP_APNS_KEY`, `CAMP_APNS_KEY_ID`, `CAMP_APNS_TEAM_ID` and `CAMP_APNS_BUNDLE_ID` (see `backend/src/camp/apns.py`). Without them the phone still syncs in real time while camp is open and catches up on foreground.

## If an order does not appear while the phone is locked

The current build receives Mac orders only while camp is open on the phone. Locking the phone or switching apps stops its long-poll connection. A new order chosen on the Mac therefore cannot start a Live Activity until camp returns to the foreground.

For the current demo, keep camp open on the phone while choosing the order on the Mac. Wait for it to appear on the phone, then lock the phone to show the existing Live Activity. Later Mac changes will catch up when camp is opened again.

There are two separate push paths:

- **Update an existing activity:** backend support exists in `backend/src/camp/apns.py`, but `LunchController.pushToUpdateEnabled` is false and `Config/App.entitlements` is not connected to the app target. Enabling it requires a signing team that supports Push Notifications and backend APNs credentials.
- **Start an activity while locked:** this also requires ActivityKit push-to-start token registration and a backend `start` push containing `LunchAttributes` and the order state. That path is not implemented. Flipping the update flag alone will not make a new Mac order appear on a locked phone.

See Apple's [starting and updating Live Activities with push notifications](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications). These are delivery limitations; a successful simulator build does not verify locked-phone behavior.

## Lifecycle and integration boundary

`LunchController.present(_:group:)` is the main-actor entry point for an incoming invitation. It requires a fresh choosing session with unique options, publishes it through the backend, then displays it locally. The ActivityKit projection checks the combined payload size against 4 KB. Activity and sync failures appear in Today; acknowledged group membership remains visible there. `presentConfirmed(_:office:)` preserves all item IDs from an acknowledged group join.

The controller waits for membership and session acknowledgements before advancing local confirmation state, then persists the session and group context in `SessionFile`. Revision checks reject outdated buttons. App Intents execute in the containing app process; the extension renders ActivityKit state without accessing the app’s files. Static activity attributes carry the session ID; group context is restored from the app's cache and backend. Groups, multi-item orders and historical receipts persist in the database and are refreshed through the API after launch.

Membership and session publication are separate requests. If membership succeeds and publication fails, Today can already contain the order while the activity reports a retryable failure; refresh before retrying. A future operation/outbox API should make that recovery automatic.

The app supports Lock Screen and compact, minimal and expanded Dynamic Island presentations. The activity uses a short, phone-specific composition of the existing camp styling; the desktop card is too tall for the Lock Screen’s limited height. No notification permission is requested for locally started activities.

Automatic invitations while the phone app is closed use ActivityKit push-to-start (iOS 17.2+): the phone registers its push-to-start token at `POST /v1/lunch-session/push-start-token`, and each running activity registers its own update token at `POST /v1/lunch-session/push-token`. An accepted write pushes `update`/`end` to a registered activity, or `start` when the device has never seen the session; `started` markers keep a second write from raising a duplicate. Forgetting an order pushes `end` to every activity rendering it. All of it compiles in only under the `CAMP_PUSH` flag (see above); without it the shared-lunch long-poll still covers the phone while the app is active, but nothing polls in the background. One residual case: an activity raised purely by push gets its own update token registered the next time camp runs, so Mac edits made between the remote start and the next launch appear on that launch rather than mid-flight.

## Historical verification and partner handoff

On September 19, both the unsigned simulator build (arm64/x86_64) and the unsigned physical-device build succeeded with Xcode 16.2 on macOS 15.1 for the revision tested then. These results do not validate subsequent changes. There were deprecation and ActivityKit concurrency warnings under Swift 5 language mode; these did not block that compilation.

A connected iPhone 16 Pro running iOS 26.6.2 was detected and paired. Developer Mode was disabled, preventing developer services from becoming available. No local signing team is configured. No app installation, simulator launch or on-device interaction is claimed. This evidence does not establish a need to upgrade macOS: enable Developer Mode and configure signing first, then retry device preparation. If preparation subsequently rejects the available developer image, use a compatible newer Xcode/macOS combination.

For a partner to continue:

1. Pull `main` from the camp repository and open `Lunchline.xcodeproj` at the repository root.
2. Copy `Config/Local.xcconfig.example` to `Config/Local.xcconfig`, and fill in their team and unique bundle prefix. Never commit the local file.
3. Select the **Lunchline** scheme and their trusted, unlocked phone with Developer Mode enabled. Let Xcode prepare the device and resolve automatic signing for both targets.
4. Run, open Today → View menu, select items and confirm, then lock the phone to inspect the activity. Tap the activity to reopen Today. Also try New order, Change order and Leave; use the Mac notch's Simulate arrival for the delivery demo.
5. Follow the [USB-C demo runbook](DEMO.md) to establish an actual network interface, start a token-protected backend and configure both devices. With `CAMP_PUSH` off, keep camp open on the phone when choosing a group in the Mac notch; with it on, background and closed delivery work too, including a new order raising the Live Activity by push-to-start.

The first sandboxed attempt could not access CoreDevice/Simulator services or compiler preview plugins; repeating outside that sandbox allowed both builds to succeed. This is distinct from an Xcode compatibility failure.

## Apple references

- [Displaying live data with Live Activities](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)
- [LiveActivityIntent](https://developer.apple.com/documentation/appintents/liveactivityintent)
- [Starting and updating Live Activities with push notifications](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications)
