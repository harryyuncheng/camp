import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

struct CampPersonalPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    var body: some View {
        VStack(spacing: 20) {
            CampCard("Food preferences") {
                CampTextField(title: "Your name", text: $store.draft.personal.displayName)
                Picker("Dietary preference", selection: $store.draft.personal.dietaryStyle) {
                    ForEach(["No preference", "Vegetarian", "Vegan", "Pescatarian", "Halal", "Gluten-free"], id: \.self) { Text($0).tag($0) }
                }
                CampField("Allergies") { CampTextField(title: "e.g. peanuts, sesame", text: $store.draft.personal.allergies) }
                CampField("Rather skip") { CampTextField(title: "Ingredients or meals you dislike", text: $store.draft.personal.dislikes) }
                Text("Demo meals don’t use these preferences yet.").font(.caption).foregroundStyle(CampPalette.muted)
            }
            CampCard("Lunch timing") {
                CampPair(compact: compact) {
                    CampField("Earliest lunch") { CampTimePicker(label: "Earliest lunch", minutes: $store.draft.personal.lunchStart) }
                    CampField("Latest lunch") { CampTimePicker(label: "Latest lunch", minutes: $store.draft.personal.lunchEnd) }
                }
                CampField("Time to eat") { CampNumberStepper(label: "Time to eat", value: $store.draft.personal.lunchDuration, range: 15...120, step: 5, suffix: " min") }
                CampField("Meeting buffer") { CampNumberStepper(label: "Meeting buffer", value: $store.draft.personal.meetingBuffer, range: 0...60, step: 5, suffix: " min") }

            }
            CampCalendarView(store: store)
            CampCard("Notifications", subtitle: "Preview settings · notifications aren’t scheduled yet.") {
                CampToggle(title: "Lunch invitations", value: $store.draft.personal.lunchInvitations)
                CampToggle(title: "Order updates", value: $store.draft.personal.orderUpdates)
                CampToggle(title: "Coffee invitations", value: $store.draft.personal.coffeeInvitations)
                CampField("Snooze for") { CampNumberStepper(label: "Snooze", value: $store.draft.personal.snoozeMinutes, range: 5...60, step: 5, suffix: " min") }
            }
        }
    }
}

struct CampOfficePage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    var body: some View {
        VStack(spacing: 20) {
            CampCard("Office controls") {
                CampToggle(title: "Demo admin", detail: store.isDemoAdmin ? "Office policy is editable" : "Office policy is read-only", value: $store.isDemoAdmin)
            }
            CampLocationView(store: store)
            policy.disabled(!store.isDemoAdmin)
        }
    }
    private var policy: some View {
        VStack(spacing: 20) {
            CampCard("Office details") {
                CampTextField(title: "Office name", text: $store.draft.office.name)
                CampTextField(title: "Delivery address", text: $store.draft.office.address)
                CampField("Office timezone") { CampTextField(title: "America/New_York", text: $store.draft.office.timezone) }
            }
            CampCard("Group orders") {
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
            CampCard("Budgets", subtitle: "Saved locally · not enforced on demo orders.") {
                CampField("Per-person cap") { CampNumberStepper(label: "Per-person budget", value: $store.draft.office.personBudgetCents, range: 100...100000, step: 100, money: true) }
                CampField("Whole-group cap") { CampNumberStepper(label: "Group budget", value: $store.draft.office.groupBudgetCents, range: 100...1000000, step: 500, money: true) }
            }
        }
    }
}

struct CampConnectionsPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    var body: some View {
        VStack(spacing: 20) {
            CampCalendarView(store: store)
            CampLocationView(store: store)
            CampRampView(store: store)
            CampCard("Recommendations") {
                CampTextField(title: "https://recommendations.example.com", text: $store.draft.connections.recommendationURL)
                CampBadge(text: "Not connected")
            }
            CampCard("Ordering") {
                Picker("Provider", selection: $store.draft.connections.orderingProvider) {
                    Text("Mock provider").tag("Mock provider")
                    Text("DoorDash · planned").tag("DoorDash")
                }
                CampBadge(text: store.draft.connections.orderingProvider == "Mock provider" ? "Demo only" : "Not connected")
                Text("No orders are submitted.").font(.callout).foregroundStyle(CampPalette.muted)
            }
            CampCard("Backend") {
                CampTextField(title: "http://127.0.0.1:8787", text: $store.draft.connections.backendURL)
                Text("Ramp server URL. Leave blank to use http://127.0.0.1:8787.").font(.caption).foregroundStyle(CampPalette.muted)
            }
        }
    }

}

/// Visual-only mock of the employee spending surface. All amounts and activity are fixtures.
struct CampSpendingPage: View {
    let compact: Bool

    private let monthlySpendCents = 4_285
    private let monthlyBudgetCents = 30_000
    private let transactions = [
        CampDemoTransaction(name: "The Green Table", detail: "Today · Team lunch", amountCents: 1_425, symbol: "fork.knife"),
        CampDemoTransaction(name: "Corner Coffee", detail: "Sep 18 · Coffee run", amountCents: 861, symbol: "cup.and.saucer.fill"),
        CampDemoTransaction(name: "Fresh Bowl", detail: "Sep 16 · Lunch", amountCents: 1_999, symbol: "leaf.fill")
    ]

    var body: some View {
        VStack(spacing: 20) {
            CampCard("Lunch card", subtitle: "Sample spending · no live card connected.") {
                lunchCard
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("SPENT THIS MONTH").font(.system(size: 9, weight: .semibold)).tracking(0.8).foregroundStyle(CampPalette.muted)
                            Text(LunchStyle.money(monthlySpendCents)).font(.system(size: 25, weight: .semibold, design: .rounded)).monospacedDigit()
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 4) {
                            Text("MONTHLY BUDGET").font(.system(size: 9, weight: .semibold)).tracking(0.5).foregroundStyle(CampPalette.muted)
                            Text(LunchStyle.money(monthlyBudgetCents)).font(.system(size: 14, weight: .semibold, design: .rounded)).monospacedDigit()
                        }
                    }
                    ProgressView(value: Double(monthlySpendCents), total: Double(monthlyBudgetCents)).tint(CampPalette.green)
                    Text("\(LunchStyle.money(monthlyBudgetCents - monthlySpendCents)) available")
                        .font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                }
            }

            CampCard("Recent activity") {
                ForEach(Array(transactions.enumerated()), id: \.element.id) { index, transaction in
                    if index > 0 { Divider() }
                    transactionRow(transaction)
                }
            }


        }
    }

    private var lunchCard: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 19)
                .fill(LinearGradient(colors: [Color(red: 0.10, green: 0.17, blue: 0.12), CampPalette.green], startPoint: .topLeading, endPoint: .bottomTrailing))
            Circle().fill(CampPalette.lime.opacity(0.15)).frame(width: 230).offset(x: compact ? 185 : 300, y: -118)
            Circle().stroke(.white.opacity(0.08), lineWidth: 1).frame(width: 265).offset(x: compact ? 163 : 278, y: -136)
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("camp").font(.system(size: 23, weight: .bold, design: .rounded)).tracking(-0.7)
                        Text("CORPORATE LUNCH").font(.system(size: 8, weight: .semibold)).tracking(1.2).foregroundStyle(.white.opacity(0.68))
                    }
                    Spacer()
                    Text("DEMO ONLY").font(.system(size: 8, weight: .bold)).tracking(0.6)
                        .padding(.horizontal, 9).padding(.vertical, 6)
                        .background(.white.opacity(0.13)).clipShape(Capsule())
                }
                Spacer(minLength: 12)
                HStack(spacing: 10) {
                    RoundedRectangle(cornerRadius: 6).fill(CampPalette.lime.opacity(0.86))
                        .frame(width: 39, height: 28)
                        .overlay(Image(systemName: "cpu").font(.system(size: 15)).foregroundStyle(CampPalette.green))
                    Image(systemName: "wave.3.right").font(.system(size: 15, weight: .medium)).foregroundStyle(.white.opacity(0.72))
                    Text("••••  ••••  ••••  4821").font(.system(size: 12, weight: .medium, design: .monospaced)).monospacedDigit()
                }
                Spacer(minLength: 12)
                HStack(alignment: .bottom) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("CARDHOLDER").font(.system(size: 7, weight: .semibold)).tracking(1).foregroundStyle(.white.opacity(0.62))
                        Text("CAMP MEMBER").font(.system(size: 10, weight: .semibold)).tracking(0.6)
                    }
                    Spacer()
                    Image(systemName: "leaf.fill").font(.system(size: 19)).foregroundStyle(CampPalette.lime)
                }
            }
            .foregroundStyle(.white)
            .padding(compact ? 18 : 22)
        }
        .frame(maxWidth: .infinity)
        .frame(height: compact ? 178 : 196)
        .clipShape(RoundedRectangle(cornerRadius: 19))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Demo camp company lunch card ending in 4821")
    }

    private func transactionRow(_ transaction: CampDemoTransaction) -> some View {
        HStack(spacing: 12) {
            Image(systemName: transaction.symbol).font(.system(size: 14, weight: .medium))
                .foregroundStyle(CampPalette.green).frame(width: 38, height: 38)
                .background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 11))
            VStack(alignment: .leading, spacing: 4) {
                Text(transaction.name).font(.system(size: 12, weight: .semibold))
                Text(transaction.detail).font(.system(size: 10)).foregroundStyle(CampPalette.muted)
            }
            Spacer()
            Text("−\(LunchStyle.money(transaction.amountCents))").font(.system(size: 12, weight: .semibold)).monospacedDigit()
        }
    }
}

private struct CampDemoTransaction: Identifiable {
    let name: String
    let detail: String
    let amountCents: Int
    let symbol: String
    var id: String { name }
}
