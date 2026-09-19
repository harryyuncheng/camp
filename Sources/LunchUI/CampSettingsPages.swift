import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

struct CampPersonalPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    var body: some View {
        VStack(spacing: 20) {
            CampCard("Your usual", subtitle: "Help camp learn what a good lunch looks like for you.") {
                CampTextField(title: "Your name", text: $store.draft.personal.displayName)
                Picker("Dietary preference", selection: $store.draft.personal.dietaryStyle) {
                    ForEach(["No preference", "Vegetarian", "Vegan", "Pescatarian", "Halal", "Gluten-free"], id: \.self) { Text($0).tag($0) }
                }
                CampField("Allergies") { CampTextField(title: "e.g. peanuts, sesame", text: $store.draft.personal.allergies) }
                CampField("Rather skip") { CampTextField(title: "Ingredients or meals you dislike", text: $store.draft.personal.dislikes) }
                Text("Preferences are saved for a future recommendation service. Demo meals are not filtered.").font(.caption).foregroundStyle(CampPalette.muted)
            }
            CampCard("Make room for lunch", subtitle: "Your preferred window, with breathing room around meetings.") {
                CampPair(compact: compact) {
                    CampField("Earliest lunch") { CampTimePicker(label: "Earliest lunch", minutes: $store.draft.personal.lunchStart) }
                    CampField("Latest lunch") { CampTimePicker(label: "Latest lunch", minutes: $store.draft.personal.lunchEnd) }
                }
                CampField("Time to eat") { CampNumberStepper(label: "Time to eat", value: $store.draft.personal.lunchDuration, range: 15...120, step: 5, suffix: " min") }
                CampField("Meeting buffer") { CampNumberStepper(label: "Meeting buffer", value: $store.draft.personal.meetingBuffer, range: 0...60, step: 5, suffix: " min") }
                CampToggle(title: "Work calendar", detail: "Demo calendar selection", value: $store.draft.personal.workCalendar)
                CampToggle(title: "Personal calendar", detail: "Demo calendar selection", value: $store.draft.personal.personalCalendar)
                CampToggle(title: "Holidays", detail: "Demo calendar selection", value: $store.draft.personal.holidayCalendar)
            }
            CampCard("A well-timed nudge") {
                CampToggle(title: "Lunch invitations", detail: "An invitation when a compatible group is collecting", value: $store.draft.personal.lunchInvitations)
                CampToggle(title: "Order updates", detail: "Cutoff, delivery and arrival updates", value: $store.draft.personal.orderUpdates)
                CampToggle(title: "Coffee invitations", detail: "Join a nearby coffee run", value: $store.draft.personal.coffeeInvitations)
                CampField("Snooze for") { CampNumberStepper(label: "Snooze", value: $store.draft.personal.snoozeMinutes, range: 5...60, step: 5, suffix: " min") }
                Text("These controls do not schedule notifications yet. Manage live Mac location under Connections.").font(.caption).foregroundStyle(CampPalette.muted)
            }
        }
    }
}

struct CampOfficePage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    var body: some View {
        VStack(spacing: 20) {
            CampCard("Office controls", subtitle: "A demo role switch, available on both devices. Real roles will be enforced by the backend.") {
                CampToggle(title: "Demo admin", detail: store.isDemoAdmin ? "Office policy is editable" : "Office policy is read-only", value: $store.isDemoAdmin)
            }
            CampLocationView(store: store)
            policy.disabled(!store.isDemoAdmin)
        }
    }
    private var policy: some View {
        VStack(spacing: 20) {
            CampCard("Where we gather", subtitle: "Save these coordinates and radius, then confirm the boundary above.") {
                CampTextField(title: "Office name", text: $store.draft.office.name)
                CampTextField(title: "Delivery address", text: $store.draft.office.address)
                ZStack {
                    RoundedRectangle(cornerRadius: 16).fill(CampPalette.background)
                    Circle().fill(CampPalette.lime.opacity(0.3)).frame(width: 140, height: 140)
                    Circle().stroke(CampPalette.green.opacity(0.5), style: StrokeStyle(lineWidth: 1, dash: [5])).frame(width: 140, height: 140)
                    VStack(spacing: 8) { Image(systemName: "building.2.fill").font(.title); Text("\(store.draft.office.radiusMeters) m boundary").font(.caption) }
                }.frame(height: 170).accessibilityLabel("Illustrative office boundary")
                Text("Boundary illustration · live status is shown above").font(.caption).foregroundStyle(CampPalette.muted)
                CampPair(compact: compact) {
                    CampField("Latitude") { TextField("Latitude", value: $store.draft.office.latitude, format: .number).textFieldStyle(.roundedBorder) }
                    CampField("Longitude") { TextField("Longitude", value: $store.draft.office.longitude, format: .number).textFieldStyle(.roundedBorder) }
                }
                CampNumberStepper(label: "Office radius", value: $store.draft.office.radiusMeters, range: 50...5000, step: 50, suffix: " m")
                CampField("Office timezone") { CampTextField(title: "America/New_York", text: $store.draft.office.timezone) }
            }
            CampCard("One delivery. More people.", subtitle: "Rules for finding a useful group before opening another cart.") {
                CampToggle(title: "Prefer an existing group", detail: "Join a compatible restaurant and delivery window first", value: $store.draft.office.preferExistingGroups)
                CampField("Minimum people") { CampNumberStepper(label: "Minimum participants", value: $store.draft.office.minimumParticipants, range: 2...50) }
                CampField("Minimum delivery savings") { CampNumberStepper(label: "Minimum savings", value: $store.draft.office.minimumSavingsCents, range: 0...10000, step: 100, money: true) }
                Picker("Share delivery fees", selection: $store.draft.office.feeSharing) { ForEach(FeeSharing.allCases) { Text($0.rawValue).tag($0) } }
                Picker("When there is no group", selection: $store.draft.office.fallback) { ForEach(GroupFallback.allCases) { Text($0.rawValue).tag($0) } }
                CampField("Order cutoff") { CampTimePicker(label: "Order cutoff", minutes: $store.draft.office.cutoff) }
                CampPair(compact: compact) {
                    CampField("Delivery from") { CampTimePicker(label: "Delivery from", minutes: $store.draft.office.deliveryStart) }
                    CampField("Delivery until") { CampTimePicker(label: "Delivery until", minutes: $store.draft.office.deliveryEnd) }
                }
            }
            CampCard("Spend with a plan", subtitle: "Proposed caps for the future Ramp integration; no card is issued or charged.") {
                CampField("Per-person cap") { CampNumberStepper(label: "Per-person budget", value: $store.draft.office.personBudgetCents, range: 100...100000, step: 100, money: true) }
                CampField("Whole-group cap") { CampNumberStepper(label: "Group budget", value: $store.draft.office.groupBudgetCents, range: 100...1000000, step: 500, money: true) }
                Text("Rules are saved locally. The demo cart does not enforce office policy yet.").font(.caption).foregroundStyle(CampPalette.muted)
            }
        }
    }
}

struct CampConnectionsPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    var body: some View {
        VStack(spacing: 20) {
            CampCard("Your connections", subtitle: "Configuration placeholders. Preview buttons only change the demo status on this device.") {
                connection("Calendar", symbol: "calendar", detail: "Find a lunch window around your meetings.")
            }
            CampLocationView(store: store)
            CampRampView(store: store)
            CampCard("Recommendation service", subtitle: "A place for your partner’s model to plug in.") {
                CampTextField(title: "https://recommendations.example.com", text: $store.draft.connections.recommendationURL)
                CampBadge(text: "Not connected")
                Text("Future input: preferences, presence, free time, budget and open groups. Future output: ranked meal options with reasons.").font(.callout).foregroundStyle(CampPalette.muted)
            }
            CampCard("Ordering", subtitle: "Start with a simulated shared cart.") {
                Picker("Provider", selection: $store.draft.connections.orderingProvider) {
                    Text("Mock provider").tag("Mock provider")
                    Text("DoorDash · planned").tag("DoorDash")
                }
                CampBadge(text: store.draft.connections.orderingProvider == "Mock provider" ? "Demo only" : "Not connected")
                Text("No orders are submitted. DoorDash ordering and checkout still need an integration.").font(.callout).foregroundStyle(CampPalette.muted)
            }
            CampCard("camp backend", subtitle: "One home for group carts, office policy and future integrations.") {
                CampTextField(title: "http://127.0.0.1:8787", text: $store.draft.connections.backendURL)
                CampBadge(text: "Not connected")
                Text("Ramp uses this URL through the local bridge. Location runs on-device. Other integrations remain placeholders. Mac and iPhone settings do not sync yet.").font(.caption).foregroundStyle(CampPalette.muted)
            }
        }
    }
    private func connection(_ title: String, symbol: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Label(title, systemImage: symbol).font(.headline); Spacer(); CampBadge(text: store.previewConnections.contains(title) ? "Demo preview" : "Not connected", active: store.previewConnections.contains(title)) }
            Text(detail).font(.callout).foregroundStyle(CampPalette.muted)
            Button(store.previewConnections.contains(title) ? "Clear preview" : "Preview connection") {
                if store.previewConnections.contains(title) { store.previewConnections.remove(title) }
                else { store.previewConnections.insert(title) }
            }.buttonStyle(CampActionStyle(primary: false))
        }
    }
}
