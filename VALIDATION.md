# Validation — September 19, 2026

Environment: Apple Silicon, macOS 15.1, Xcode 14.3.1 / Swift 5.8. The default command-line-tools toolchain had a SwiftPM manifest-linking mismatch; selecting the full Xcode toolchain resolved it. The build script selects that toolchain without changing the global Xcode setting.

## Passed

- Swift package debug build of the shared domain, shared SwiftUI card, and native Mac panel app.
- All **9 domain/persistence tests**, zero failures.
- Xcode **LunchlineMac** scheme build, including app bundle generation. Xcode needed normal access to its build services outside the command sandbox.
- Release packaging through `bash scripts/build-mac.sh`.
- Local app code-signature verification.
- Xcode project and all Info.plist files pass plist validation.
- Launched the release `dist/Lunchline.app` and visually inspected the panel. All three meal buttons, prices, timer, collapse/dismiss controls, and footer fit without clipping.
- Clicked a meal → review shows the correct price/savings → Confirm saves the choice and shows the confirmed state.
- Collapsed to the small pill, then reopened to the saved confirmed state.
- Stopped and relaunched the development app; the confirmed meal was restored.
- Used the five-second demo event: the panel disappeared, then automatically reopened to the three new meal choices.
- Selected an alternate meal and used Change to return to all three choices.

The final release was rebuilt after adding the in-panel demo menu and state-specific collapsed labels, then launched for the persistence and delayed-event checks.

## Not verified on hardware

- iPhone/iOS 17 build and Live Activity intent execution. Installed Xcode only includes iOS 16.4 SDK; use Xcode 15+ or a version compatible with the phone.
- Mirrored Live Activities on macOS Tahoe. This is optional and separate from the native Mac panel.
- Placement across multiple external displays, changing display configuration during animation, full-screen Spaces, VoiceOver, and Reduce Motion behavior. Code handles these paths, but they need checks on the intended demo hardware.
- Keyboard focus preservation under all foreground applications. The panel uses `nonactivatingPanel`, never becomes key/main, and does not call app activation.
- Simulated-arrival button was not clicked during the final UI pass; its transition is covered by a domain test.

No real provider ordering, payment, backend notifications, or meal predictions were attempted.


## camp branding and notch attachment update

- Renamed the visible app, wordmark, menus, accessibility labels, and app bundle to **camp**, with **Corporate Autonomous Meal Protocol** in the expanded header.
- Reproduced the notch gap with the production placement helper: for a screen ending at y=982 and a 32-point notch, the old panel ended at y=952. The regression failed for both expanded and collapsed sizes.
- Fixed placement to keep the black shell's top at the screen edge and reserve the camera band inside the content. Overrode AppKit's default window constraint so it cannot move this intentional overlay beneath the menu bar.
- Added concave top shoulders and removed the nested green background on Mac. Entrance now expands from a notch-sized frame with the same top edge rather than moving the panel vertically.
- All **11 tests pass** (nine session/persistence tests plus two geometry tests). The release app rebuilt and its signature verified.
- Visually checked the new expanded choices and collapsed state through the running app; confirmed all three meals fit and the camp header is visible. Collapsed and reopened successfully. Left the app expanded for review.
- `dist/camp.app` is the current build. The previous Lunchline bundle is archived under the task's work folder to avoid launching the stale design.


## Confirmation retraction and transition update

- Replaced per-update hosting-view construction with a single mounted SwiftUI view. Both expanded and compact content stay mounted and crossfade inside one animated, clipped shell.
- Expansion and collapse now interpolate through the same shell dimensions and corner radius with a fixed top edge. A generation token cancels obsolete completion tasks during interruptions; the native window only contracts after the visual transition completes.
- New menus and meal selections resize the current panel rather than re-anchoring to the pointer or replaying entrance.
- A successful confirmation schedules full retraction after three seconds. The menu-bar icon remains available. Left-click toggles the panel; right-click opens demo controls.
- Confirmation timers are scoped to session/revision and cancelled by a new offer or explicit interaction. Reopening an already-confirmed meal does not rearm the timer.
- **13 domain/geometry/timing tests passed.**
- **3 AppKit lifecycle tests passed with actual desktop access**, zero skipped: confirmed window hides after the delay and stays open when explicitly reopened; a replacement offer prevents old-timer dismissal; hosted-view identity and the top edge remain stable through selection/collapse/replacement.
- The AppKit tests initially skipped inside the command sandbox because it had no desktop session; rerunning with desktop access executed and passed all three in about 16 seconds. Tests use isolated temporary stores, not the user's saved lunch.
- Manually inspected the release panel through expand/collapse, new offer, selection, and confirmation. The UI tool times out once the utility has no visible windows; actual hidden state was independently asserted by the AppKit lifecycle tests.
- Release bundle rebuilt after the checks. Menu-bar left/right-click wiring is implemented; the UI automation tool did not expose the status item for a direct click check.


## Configuration workspace update

- Mac release build and app packaging completed successfully with the installed Xcode toolchain.
- New shared configuration and UI files are included in both Mac and iPhone Xcode app targets; the widget extension remains independent of configuration UI.
- No tests or interactive verification were run for this update.
- iPhone source is implemented, but its iOS 17 target was not built: installed Xcode 14.3.1 only provides iOS 16.4 SDK. The Mac compact window is a layout preview, not device validation.

## Ramp integration update

- Authenticated against the real Ramp sandbox for business/user/fund/card read scopes and fund-write scope.
- Loaded company details and 41 active employees through the local camp backend.
- Mac release build succeeded after wiring the shared Ramp view into app target memberships.
- Fund creation, issuer enforcement and checkout have not been exercised. No automated tests were added or run for this update.
- iPhone build remains blocked by installed Xcode 14.3.1; localhost bridge supports the Mac or simulator, not a physical phone.

## 2026-09-19 · recommender integration

Python backend: `cd backend && uv run pytest` → 14 passed. `/v1/meal-offers` and `/v1/debug/*` exercised with FastAPI's
TestClient. Swift changes (RecommendationContracts, RecommendationClient, CampRecommendationView, CampDemoPage (then named CampDebugPage),
store/workspace/Today/Mac-app edits, pbxproj wiring) compiled with Xcode 27.0: `swift build --product LunchMac` clean,
`swift test` 13 passed, `scripts/build-mac.sh` produced `dist/camp.app`. The app was launched against the recommender on
port 8788; the in-app flow (Connect → Request lunch offer → Demo tab) was not exercised by automation.

## Mac location update

- Mac release app compiled and packaged with the Core Location service and UI.
- No automated tests or live location permission/movement checks were run. User must enable Location Services and configure the actual office for an on-device walkthrough.
- iPhone tracking remains explicitly unavailable; the shared UI compiles its Mac implementation conditionally.


## Map office picker update

- Replaced the coordinate form with an AppKit MapKit map, place search, current-Mac marker, click-to-place circle, radius slider and one-step boundary save/confirmation.
- Mac release build succeeded. No automated or interactive UI tests were run for this update.

## Calendar integration update

- Mac release build succeeds with EventKit, the public modern full-access selector compatibility path, calendar selection and free-window calculation.
- No tests or live permission/event reads were run. Actual account permissions and availability require an on-device walkthrough.
- Only Mac calendar access is implemented; iPhone shows an explicit unsupported message.


## Map scroll focus and day calendar UI

- Mac release build succeeded with the map scroll gate, calendar dropdown multiselector, hourly busy timeline and exact-duration suggested lunch block.
- No interactive or automated tests were run for this update.


## Calendar scroll focus

- Calendar viewport now matches the map at 340 points and requires a click before consuming scrolling. Pointer exit or Done returns control to the page.
- Mac release build completed; no interactive or automated tests were run.

## Navigation responsiveness — September 19

- Reproduced the original sidebar padding click missing its action before editing.
- Expanded sidebar/button content shapes; widened the sidebar so Connections fits.
- A navigation process sample showed MapKit initialization and EventKit reads on the main thread. Calendar snapshots now run in a separate actor; service updates are observed by their own panels instead of invalidating the whole workspace.
- Office/Connections recycle up to two detached native map views, clearing delegates, gestures, overlays and annotations between owners. First map construction is deferred until after navigation begins; page cards are lazy.
- macOS build succeeded. Relaunched the built app and opened Office then Connections; both rendered their office map and controls.
- No automated tests were added or run. End-to-end latency has not been quantified. Coordinate-based sidebar verification was unavailable through UI automation; accessibility navigation worked. Calendar access needs reconnecting in the rebuilt copy, so the live calendar path was not rechecked.

## Scrolling layout — September 19

- Captured a process sample while scrolling Office down and back. It contains SwiftUI layout/text work and accessibility sampling overhead; it does not provide a reliable frame-rate benchmark.
- Replaced lazy stacks on the finite workspace pages with stable stacks to avoid deferred card layout while scrolling. Map initialization remains deferred and pooled.
- macOS time pickers now construct native menu entries once per control instead of contributing 181 SwiftUI labels per picker. Values, five-minute increments, accessibility labels and disabled admin state are preserved.
- Card backgrounds draw a rounded shape without masking all child views. The map keeps its in-visible-rect tracking area rather than removing/recreating it on each layout; inactive pointer exits no longer publish redundant state.
- Release build succeeded and the rebuilt app was relaunched. Repeated Office down/up scrolling reached both ends with the map, policy cards and selected time values present.
- No automated tests were added or run. Smoothness improvement is not quantified; iOS and the permission-gated live calendar were not exercised.

## Workspace copy cleanup — September 19

- Reviewed Today, You, Office, Spending and Connections plus shared map, calendar and Ramp cards.
- Removed repeated header kickers/taglines, the global prototype badge, metric footnotes and redundant helper paragraphs. Simplified card titles and notification toggles; removed the explanatory-only spending card.
- Kept actionable map/scroll instructions, permission and error messages, demo/live connection distinctions, dietary limitations and sandbox fund consequences. Backend setup retains the default URL without a hardcoded connection-status badge.
- macOS release build succeeded. No automated tests were added or run; iPhone build is not supported by the installed Xcode version.

## Editable lunch timing — September 19

- Replaced the four controls in You → Lunch timing with text fields. Enter or leaving a field commits valid input and formats it as a clock time or minutes.
- Clock parsing accepts AM/PM, 24-hour times and compact digits; unsuffixed hours use 24-hour interpretation. Duration stays within 15–120 minutes and buffer within 0–60 minutes. Invalid text remains visible with a hint and does not replace the last valid draft value. Escape restores the previous value on macOS.
- Existing Save/Discard and cross-field lunch-window validation remain in use. Office time dropdowns are unchanged.
- macOS release build succeeded. No automated tests were added or run; iOS was not built.

## Today group-order demo — September 19

- Today now starts with a clickable completed coffee order and a demo receipt, followed by three lunch groups with distinct menus, participant counts and delivery windows.
- Preview lunch invitation opens group choices in the notch. Choosing a group leads to meals, review and confirmation; confirmation updates Today through the shared settings store. Existing delayed trigger and confirmation retraction remain in use.
- Today’s View menu opens the chosen group in the Mac notch. Other workspace hosts without the Mac callback use an in-app menu sheet with explicit confirmation. One lunch choice is active at a time; choosing another group replaces it. Leave clears it.
- Fixture spending totals use the chosen group’s participants and sample food subtotal. Coffee, menus, delivery windows and prices are demo fixtures; no ordering or payments occur. Demo join state is in-memory, not synced or restored across launches.
- macOS release build succeeded. No automated tests were added or run; iOS was not built.

## SVG logo trial — September 19

- Preserved the supplied SVG in Branding/camp.svg. Its three vector paths are cached in CampLogo; the white background and surrounding whitespace are omitted for template-style use. The original file is unchanged.
- Replaced the tent symbol in the sidebar, compact workspace header, shared lunch card, unconfirmed notch pill and macOS menu-bar icon. Kept the camp wordmark and confirmation checkmark. The menu-bar image is a system template for light/dark appearance.
- macOS release build succeeded; relaunched and visually inspected the sidebar logo at its displayed size. Other surfaces share the vector but have not all been visually inspected. iOS was not built. No automated tests were run.

## Today summaries and group creation — September 19

- Added Total savings and People ordering cards at the bottom of Today. Values sum the lunch groups and update on join, leave and creation; savings use the demo $6 separate-delivery vs $6 shared-delivery model. Labels explicitly scope these estimates to lunch groups (coffee is excluded).
- Create group opens a restaurant, editable delivery time and meal form. Valid submission adds a unique group and joins with the selected meal, replacing the user's previous lunch choice. Newly created groups have no simulated other members or savings until others join.
- Group lists and the user's joined-group ID are shared with the notch. The notch group list has a bounded scroll area so adding groups does not make the panel grow indefinitely.
- Groups remain local in-memory demo data and reset on relaunch. No ordering, invitations or payments are sent.
- macOS release build succeeded. No automated tests were added or run; iOS was not built.

## Documentation refresh — September 19

- README and architecture now describe five tabs, coffee history, group creation, shared Mac notch joining, lunch-only summary estimates, typed timing, the SVG mark and spending-card proportions.
- Corrected stale claims that calendar/location were disconnected, Today embedded their panels, or workspace membership survived restart. Marked the original settings brief/integration plan as historical.
- User reported the latest sidebar logo alignment looks good. Its release build succeeded; the agent did not restart it after automatic approval blocked potential loss of in-memory demo state.
- Documentation-only follow-up; no build or tests run.


## Native iPhone companion — 2026-09-19

- Connected Today group menus and create/join/leave to ActivityKit, restored group context from active activity attributes, and added activity deep-link routing.
- Added a compact interactive Lock Screen/Dynamic Island layout and bounded incoming-offer entry point.
- Added unsigned simulator build helper and ignored local signing overrides.
- Invoked `scripts/build-ios.sh`: stopped at explicit preflight because installed Xcode is 14.3.1; iOS 17 APIs require Xcode 15+. No successful iOS build, simulator/device interaction or automated tests claimed.
- Mac app was not restarted. Automatic cross-device delivery/APNs remains future work; see `docs/IOS.md`.


## Xcode 16.2 setup — 2026-09-19

- Confirmed selected Xcode is 16.2 (16C5032a) at `/Applications/Xcode_16.2.app`.
- Fixed iOS build helper to respect `xcode-select` instead of defaulting to the old Xcode.app. Explicit DEVELOPER_DIR overrides still work.
- Retried iOS build: exit 69, Xcode license not accepted. No compilation or simulator run occurred. User must complete Xcode first-launch setup.


## Notch branding fix — 2026-09-19

- Cause: the expanded notch owns a camp header, while its embedded LunchCard also rendered one. Embedded cards now omit only their logo/name; demo status and countdown remain. Standalone phone/in-app cards retain branding.
- Release Mac build succeeded. No automated tests or app restart performed; running app needs relaunch to display the change.


## Notch header spacing — 2026-09-19

- Removed the entire embedded meal-card header row, including DEMO and countdown. The notch content no longer reserves space for the removed branding. Standalone card headers remain.
- Release Mac build succeeded. No tests or app restart performed.


## Notch group transition — 2026-09-19

- Group selection reserved a taller scrolling area than meal selection and triggered an extra measured panel resize during navigation.
- Added a shared 260-point content stage for expanded screens, shortened the group list to three 52-point rows with 8-point gaps, and crossfade contents over 0.24 seconds while keeping header/footer anchored. Additional groups scroll. Reduce Motion disables the content animation.
- Removed the competing meal-action animation. Release Mac build succeeded; no tests or live UI restart performed. Visual review remains pending relaunch.


## iPhone build and connection check — 2026-09-19

- Xcode 16.2 (16C5032a), macOS 15.1. Prior license blocker resolved.
- `scripts/build-ios.sh` succeeded outside the tool sandbox for arm64/x86_64 Simulator, including the embedded activity extension.
- Generic iOS device build with CODE_SIGNING_ALLOWED=NO also succeeded, including the extension. No source changes were needed.
- Connected iPhone 16 Pro on iOS 26.6.2 is wired and paired, but reports Developer Mode disabled and no mounted developer image. Device installation/runtime verification blocked pending phone setup and signing team. No local signing override exists.
- No macOS upgrade requirement established by this attempt. Existing SwiftUI deprecation and ActivityKit concurrency warnings remain.
- No app installed, no phone reboot triggered, no simulator/UI interaction or automated tests run. Updated docs/IOS.md with partner handoff steps.

## 2026-09-20 · single database

Backend: `uv run pytest` → 28 passed (new `tests/test_groups.py` covers seeding, join/create/leave with consistent
orders, the HTTP contract for profile/groups/ledger/restaurants, the Ramp native-client guard and the attempt ledger
across restarts; `test_sync.py` now persists through the store). Against the live Postgres.app database, `/v1/health`
reports `database: postgres` and the `groups`, `ramp_attempts` and `sync` tables were created on startup; a curl
end-to-end run (PUT profile → GET groups → join → GET ledger → psql shows the member and confirmed order → leave)
passed. Swift: `swift build` clean, `swift test` 17 passed (ledger test replaced by a backend-payload decoding test),
`scripts/build-ios.sh` succeeded. Not verified: the Mac app driven interactively against the new Today page. Ramp
`/v1/ramp` returned "Ramp returned HTTP 400" with the configured sandbox credentials; the retired `server.py` from git
returned the same, so this is the sandbox application's scopes/credentials, not the port.

## Notch panel auto-resizes to each screen — 2026-09-20

- Replaced the fixed 260-point expanded stage with per-screen height measurement. Each screen (group picker, choosing, reviewing, confirmed, delivered, ended) reports its natural height; the stage adopts the incoming screen's height only, so the shell animates directly to the new size rather than growing to the taller of the two crossfading screens and settling afterwards.
- Header and footer remain anchored; contents still crossfade over 0.24 seconds; Reduce Motion still disables the content animation. Group list keeps its capped scrolling height.
- `swift build` and `swift test` pass (14 tests). Visual review on the notch pending relaunch.
