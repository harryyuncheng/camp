# Mac calendar availability

## Setup

1. Quit an older camp copy and open the rebuilt `dist/camp.app`.
2. Open **Connections → Connect calendars** and allow full calendar access. macOS calls this full/read-write access; camp only reads events and contains no event-writing operations.
3. Open the **Select calendars** dropdown and check the calendars that should block lunch. The dropdown stays open for multiple selections. Names include the calendar's account/source. Selections save immediately on this Mac. None are selected automatically.
4. In **You**, set the lunch window, time to eat and meeting buffer, then **Save changes**. Computation uses saved preferences and the saved office timezone.
5. View today’s hourly timeline below the selector. Blue-gray blocks represent merged busy time including your buffer. A light-green block marks the earliest remaining gap for exactly your saved lunch duration. This is a suggestion, not a booked event; no lunch block appears if no gap fits. Use **Refresh** or the **…** menu for settings and pause.

This reads calendars already present in the Mac Calendar app, including synced Google, Microsoft and iCloud accounts. It does not implement direct Google/Microsoft OAuth. If no calendars appear, add/sync the account in Calendar first. It sees locally synced events, not an independently refreshed server calendar. iPhone calendar integration is not implemented.

## Calculation

The service queries selected calendars for today in the office timezone, including the meeting buffer around the day. Recurrences are expanded by EventKit. Cancelled events, events marked free and invitations declined by the current user are ignored. Tentative and unknown availability are treated as busy. All-day events block time by default unless **All-day events block lunch** is switched off; events marked free are still ignored.

Busy intervals are expanded by the saved buffer, sorted and merged. Remaining gaps are clipped to the preferred lunch window and the current time, then filtered for the required meal duration. `busyNow` is calculated separately (including buffer); being free now does not necessarily mean there is enough time for lunch.

No access, no selected calendars, a missing selected calendar, sleep and an ended lunch window have explicit states. A missing selected calendar blocks availability until restored or deselected. Disconnection is never interpreted as an empty calendar. Calendar changes, wake, activation, timezone/day changes and a minute timer refresh results.

## Privacy and integration boundary

Only calendar identifiers, the enable setting and the all-day preference persist in UserDefaults. Event titles, attendee details and event history are never displayed, persisted, logged or sent to camp's backend. EventKit necessarily supplies event objects to inspect timing, attendance status and availability; the service only publishes anonymous free intervals, busy-now status, and a freshness timestamp.

`MacLunchCalendar` is owned by `CampSettingsStore`. It is available to future meal orchestration through `freeWindows`, `busyNow`, `checkedAt`, `summary` and `permission`. This integration does not automatically order meals, create lunch events or change the notch demo's timing. The eventual coordinator must recheck availability before recommending or confirming an order.

## Toolchain compatibility

The installed Xcode 14.3.1 SDK does not declare the modern calendar-access method. On macOS 14+, the service uses guarded Objective-C runtime dispatch to the public `requestFullAccessToEventsWithCompletion:` selector. It does not fall back to a write-only request. On macOS 13 it uses `requestAccess(to: .event)`. `NSCalendarsUsageDescription` and `NSCalendarsFullAccessUsageDescription` are included. The app is not App Sandbox-enabled; if enabling sandbox later, include `com.apple.security.personal-information.calendars`.

## Validation

Mac release build succeeded. No automated tests or live calendar permission/read checks were run during implementation. Grant permission and select your actual calendars for an on-device walkthrough. iPhone builds remain subject to the existing newer-Xcode requirement.

Apple references: [Accessing the event store](https://developer.apple.com/documentation/eventkit/accessing-the-event-store), [full-access request](https://developer.apple.com/documentation/eventkit/ekeventstore/requestfullaccesstoevents(completion:)), [EventKit API migration](https://developer.apple.com/documentation/technotes/tn3153-adopting-api-changes-for-eventkit-in-ios-macos-and-watchos).

The timeline uses the office timezone and actual day length, including daylight-saving transitions. Blockers are labelled Busy without meeting titles. A red line indicates the last refresh time.

The calendar viewport is 340 points high, matching the map. It forwards scrolling to the page until clicked. Moving the pointer outside or clicking **Done with calendar** returns to page scrolling.
