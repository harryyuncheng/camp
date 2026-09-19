import SwiftUI

struct CampLocationView: View {
    @ObservedObject var store: CampSettingsStore
    var body: some View {
        #if os(macOS)
        CampCard("Office presence", subtitle: "Location Services · this Mac only") {
            Group {
            HStack {
                Label(store.location.presence, systemImage: "location.fill").font(.headline)
                Spacer()
                CampBadge(text: store.location.enabled ? store.location.permission : "Paused", active: store.location.permission == "Allowed" && store.location.enabled)
            }
            Text(store.location.detail).font(.callout).foregroundStyle(CampPalette.muted)
            if let distance = store.location.distanceMeters, let accuracy = store.location.accuracyMeters {
                Text("\(Int(distance.rounded())) m from office · accuracy ±\(Int(accuracy.rounded())) m").font(.caption).monospacedDigit()
            }
            if let observed = store.location.observedAt {
                HStack { Text("Last reading"); Text(observed, style: .relative); Text("ago") }.font(.caption).foregroundStyle(CampPalette.muted)
            }
            if let arrival = store.location.arrivedAt {
                HStack { Text("Last arrival"); Text(arrival, style: .time) }.font(.caption)
            }
            if let departure = store.location.departedAt {
                HStack { Text("Last departure"); Text(departure, style: .time) }.font(.caption)
            }
            }
            HStack {
                Button(store.location.enabled ? "Pause tracking" : "Enable location") {
                    if store.location.enabled { store.location.disable() } else { store.location.enable() }
                }.buttonStyle(CampActionStyle())
                if store.location.enabled { Button("Refresh") { store.location.refresh() }.buttonStyle(CampActionStyle(primary: false)) }
            }
            Button("Open Location Services settings") { store.location.openSettings() }.buttonStyle(.plain).font(.caption)
            Divider()
            Text(store.location.officeConfirmed ? "Saved office boundary is active" : "Set your office boundary").font(.headline)
            Text("In Office, enter coordinates and radius, then Save changes. If you’re at the office now, use your current location instead.").font(.caption).foregroundStyle(CampPalette.muted)
            if store.isDemoAdmin {
                Button("Use current location for office") {
                    if let point = store.location.currentCoordinate {
                        store.draft.office.latitude = point.latitude
                        store.draft.office.longitude = point.longitude
                        store.section = .office
                        store.statusMessage = nil
                    }
                }.buttonStyle(CampActionStyle(primary: false)).disabled(!store.location.canUseCurrentLocation)
                if !store.location.officeConfirmed {
                    Button("Confirm saved office boundary") { store.location.confirmOffice() }
                        .buttonStyle(CampActionStyle(primary: false)).disabled(store.hasChanges)
                }
                if store.hasChanges { Text("Save your changes before confirming the office boundary.").font(.caption).foregroundStyle(CampPalette.muted) }
            }
            Text("Tracking runs while camp is open and the Mac is awake. Your Mac’s position stays on-device. Location does not prove you are with your laptop.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }
        #else
        CampCard("Office presence", subtitle: "Available in the Mac app") {
            Text("Enable Location Services on your Mac to detect office presence. iPhone location tracking is not connected yet.").font(.callout).foregroundStyle(CampPalette.muted)
        }
        #endif
    }
}
