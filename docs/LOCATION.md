# Mac office presence

## Enable it

1. Run the rebuilt `dist/camp.app` (quit an older running copy first).
2. Open **Office** or **Connections → Office presence** and click **Enable location**. Allow camp in the macOS location prompt. If denied, use **Open Location Services settings**.
3. In **Office**, enter your office latitude, longitude and radius. Or, while at the office, wait for an accurate fix and click **Use current location for office**.
4. Click **Save changes**, then **Confirm saved office boundary**. Default demo coordinates are never silently treated as your office.
5. **Today** shows the live Mac state; Office/Connections show accuracy, distance, last reading and arrival/departure times.

The address text is not geocoded. The entered coordinates define the boundary. Changing saved coordinates or radius requires confirmation again. Unsaved edits do not affect tracking. Office editing uses the existing demo-admin toggle; it is not server authorization.

## Behavior

- Uses Apple's `CLLocationManager` standard location updates, while camp runs and the Mac is awake. Tracking preference resumes on relaunch if already enabled and authorized. It does not launch the app at login or monitor a closed app.
- Inside requires the reported accuracy circle to fit within the radius minus a 20-meter buffer. Outside requires it to lie beyond the radius plus 20 meters. Accuracy worse than the smaller of the radius or 200 meters produces unknown.
- Readings older than two minutes produce unknown. A 15-second watchdog expires stale state. Location updates restart every minute for a fresh fix and on wake/activation.
- Initial presence sets in-office or away without inventing an arrival. Later transitions need two qualifying fixes at least eight seconds apart. A boundary-overlapping reading cancels a pending transition. Sleep, stale data, errors and lost permission invalidate the stable state.
- Arrival/departure publish `Notification.Name.campOfficeArrived` / `.campOfficeDeparted` on the main actor. `userInfo` contains only `officeID` and `observedAt`. These are app events for future orchestration; they do not order food or display a Notification Center alert.
- Latest coordinates exist only in memory. Explicitly setting the office from the current fix stores that office coordinate when settings are saved. No movement history is stored or sent to the backend.
- Mac positioning can be imprecise; keep Wi-Fi enabled. The detected position is the laptop's, not proof that its owner is present.

The bundled Mac app is not App Sandbox-enabled. `NSLocationUsageDescription` and `NSLocationWhenInUseUsageDescription` are supplied. If enabling App Sandbox later, add the location entitlement (`com.apple.security.personal-information.location`). iPhone tracking remains unimplemented and is labelled accordingly.

## Implementation

`Sources/LunchUI/MacOfficeLocation.swift` owns the macOS service, authorization, wake lifecycle, geofence classification and transition events. It is conditionally compiled for Mac. `CampSettingsStore` owns its lifetime and forwards observable changes; only successfully saved office policy configures it. `CampLocationView` is shared between Office and Connections. Today reads live presence instead of the old demo override.

## Validation status

The Mac release app builds successfully. No automated tests or live permission/movement checks were run for this change. Real arrival detection still needs an on-device walkthrough after the user grants location access and sets the actual office.

Apple references: [CLLocationManager](https://developer.apple.com/documentation/corelocation/cllocationmanager), [requesting authorization](https://developer.apple.com/documentation/corelocation/requesting-authorization-to-use-location-services).
