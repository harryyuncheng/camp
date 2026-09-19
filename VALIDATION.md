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
