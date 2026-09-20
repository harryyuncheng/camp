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
                Text("Saved to your profile on the backend; the recommender and group orders use them.").font(.caption).foregroundStyle(CampPalette.muted)
            }
            CampScheduleCard(store: store, compact: compact)
            CampCard("Meal timing", subtitle: "When a meal fits between meetings. Coffee orders can be scheduled at any time.") {
                CampPair(compact: compact) {
                    CampField("Earliest meal") { CampTimingField(label: "Earliest meal", value: $store.draft.personal.lunchStart, kind: .time) }
                    CampField("Latest meal") { CampTimingField(label: "Latest meal", value: $store.draft.personal.lunchEnd, kind: .time) }
                }
                CampField("Time to eat") { CampTimingField(label: "Time to eat", value: $store.draft.personal.lunchDuration, kind: .duration(15...120)) }
                CampField("Meeting buffer") { CampTimingField(label: "Meeting buffer", value: $store.draft.personal.meetingBuffer, kind: .duration(0...60)) }

            }
            CampCard("Notifications", subtitle: "Preview settings · notifications aren’t scheduled yet.") {
                CampToggle(title: "Meal invitations", value: $store.draft.personal.lunchInvitations)
                CampToggle(title: "Order updates", value: $store.draft.personal.orderUpdates)
                CampToggle(title: "Coffee invitations", value: $store.draft.personal.coffeeInvitations)
                CampField("Snooze for") { CampNumberStepper(label: "Snooze", value: $store.draft.personal.snoozeMinutes, range: 5...60, step: 5, suffix: " min") }
            }
        }
    }
}

/// You → Schedule a new order: standing coffee or meal orders on chosen weekdays. Saved on the backend, which puts you
/// in a matching group each day, and mirrored as a recurring event in the "camp" calendar on Mac.
struct CampScheduleCard: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    @State private var category = OrderCategory.coffee
    @State private var label = ""
    @State private var restaurantID = ""
    @State private var optionID = ""
    @State private var time = CampTimePicker.label(OrderCategory.coffee.defaultMinutes)
    @State private var weekdays: Set<Int> = [0, 1, 2, 3, 4]
    private var choices: [LunchRestaurant] { store.restaurants(for: category) }
    private var restaurant: LunchRestaurant? { choices.first { $0.id == restaurantID } }
    private var timeMinutes: Int? {
        guard let minutes = CampTimingField.Kind.time.parse(time), (300...1320).contains(minutes) else { return nil }
        return minutes
    }
    private var calendarNote: String {
        #if os(macOS)
        return store.lunchCalendar.canWrite ? "Added to your “camp” calendar as a repeating event." : "Connect calendars in Connections to mirror it to your “camp” calendar."
        #else
        return "Calendar events are written from the Mac app."
        #endif
    }
    var body: some View {
        CampCard("Standing orders", subtitle: "Schedule a coffee or a meal on the days you want it. camp joins a group for you each morning.") {
            ForEach(store.schedules) { schedule in
                HStack(spacing: 12) {
                    Image(systemName: schedule.kind.symbol).foregroundStyle(CampPalette.green).frame(width: 20)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("\(schedule.label) · \(CampTimePicker.label(schedule.timeMinutes))").font(.callout.weight(.semibold))
                        Text("\(schedule.weekdayLabel) · \(schedule.restaurantName?.isEmpty == false ? schedule.restaurantName! : "camp picks the place")")
                            .font(.caption).foregroundStyle(CampPalette.muted)
                    }
                    Spacer()
                    Button("Remove") { Task { await store.removeSchedule(schedule) } }.buttonStyle(.plain).font(.caption)
                }.padding(12).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 12))
            }
            if store.schedules.isEmpty { Text(store.recommenderUserID == nil ? "Save your profile first so the backend knows who you are." : "No standing orders yet.").font(.caption).foregroundStyle(CampPalette.muted) }
            Divider()
            Text("Schedule a new order").font(.headline)
            CampField("Order") {
                Picker("Order", selection: $category) { ForEach(OrderCategory.allCases) { Text($0.label).tag($0) } }
                    .pickerStyle(.segmented).labelsHidden()
            }
            CampPair(compact: compact) {
                CampField("Label") { CampTextField(title: category == .coffee ? "Morning coffee" : "Lunch", text: $label) }
                CampField("Time") {
                    CampTextField(title: "e.g. 9:00 AM", text: $time)
                        .onSubmit { if let minutes = timeMinutes { time = CampTimePicker.label(minutes) } }
                    if timeMinutes == nil { Text("Enter a time between 5 AM and 10 PM.").font(.caption).foregroundStyle(.red) }
                }
            }
            CampField("Days") {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 44))], spacing: 8) {
                    ForEach(0..<7, id: \.self) { day in
                        Button {
                            if weekdays.contains(day) { weekdays.remove(day) } else { weekdays.insert(day) }
                        } label: {
                            Text(LunchSchedule.weekdayNames[day])
                                .font(.caption.weight(weekdays.contains(day) ? .semibold : .regular))
                                .frame(maxWidth: .infinity, minHeight: 44)
                                .background(weekdays.contains(day) ? CampPalette.lime.opacity(0.6) : .white)
                                .clipShape(Capsule()).overlay(Capsule().stroke(CampPalette.border))
                                .contentShape(Capsule())
                        }.buttonStyle(.plain)
                            .accessibilityAddTraits(weekdays.contains(day) ? [.isSelected] : [])
                    }
                }
            }
            CampField(category == .coffee ? "Café" : "Restaurant") {
                Picker("Place", selection: $restaurantID) {
                    Text("Let camp pick the best-rated place").tag("")
                    ForEach(choices) { r in Text(r.rating.map { "\(r.name) · \(String(format: "%.1f", $0))★" } ?? r.name).tag(r.id) }
                }.labelsHidden()
                if let restaurant {
                    Picker("Usual order", selection: $optionID) {
                        Text("Usual order: camp’s pick").tag("")
                        ForEach(restaurant.options) { Text("\($0.name) · \(LunchStyle.money($0.priceCents))").tag($0.id) }
                    }.labelsHidden()
                }
            }
            HStack {
                Text(calendarNote).font(.caption).foregroundStyle(CampPalette.muted)
                Spacer()
                Button(store.scheduleBusy ? "Scheduling…" : "Schedule order") {
                    guard let minutes = timeMinutes else { return }
                    let option = restaurant?.options.first { $0.id == optionID }
                    Task {
                        if await store.addSchedule(category: category, label: label, restaurant: restaurant, option: option,
                                                   timeMinutes: minutes, weekdays: weekdays.sorted()) { label = "" }
                    }
                }.buttonStyle(CampActionStyle()).disabled(timeMinutes == nil || weekdays.isEmpty || store.scheduleBusy || store.recommenderUserID == nil)
            }
            if let error = store.scheduleError { Text(error).font(.caption).foregroundStyle(.red) }
        }
        .task { await store.loadRestaurants(); await store.refreshSchedules() }
        .onChange(of: category) { next in restaurantID = ""; optionID = ""; time = CampTimePicker.label(next.defaultMinutes) }
        .onChange(of: restaurantID) { _ in optionID = "" }
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
            CampCard("Budgets", subtitle: "Per-person cap is sent with your profile and bounds recommender offers. Connect an employee in Demo to use their Ramp sandbox limit.") {
                CampField("Per-person cap") { CampNumberStepper(label: "Per-person budget", value: $store.draft.office.personBudgetCents, range: 100...100000, step: 100, money: true) }
                if let limit = store.rampLimits?.limit {
                    Text("In use now: \(LunchStyle.money(limit.perOrderCents)) per order, from Ramp · \(limit.name).")
                        .font(.caption).foregroundStyle(CampPalette.muted)
                }
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
        }
    }
}

/// Employee spending surface. The card itself is a demo visual; spend and activity are the user's confirmed orders in the
/// backend database (`GET /v1/ledger/{user}`), whether they came from the recommender card or a Today group order.
struct CampSpendingPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    @State private var refreshing = false

    private var ledger: LunchLedgerResponse? { store.ledger }
    private var entries: [LunchLedgerEntry] { ledger?.entries ?? [] }
    private var monthlySpendCents: Int { ledger?.spentMonthCents ?? 0 }
    /// 20 working lunches at the user's per-meal budget, as the backend computed it.
    private var monthlyBudgetCents: Int { max(ledger?.monthlyBudgetCents ?? 0, 0) }
    private var savingsThisMonthCents: Int { ledger?.savedMonthCents ?? 0 }
    private var transactions: [CampDemoTransaction] {
        entries.prefix(8).map { entry in
            CampDemoTransaction(id: entry.id, name: entry.restaurant, detail: "\(Self.day(entry.date)) · \(entry.item) · \(entry.source)",
                                amountCents: entry.amountCents, symbol: entry.symbol)
        }
    }
    var body: some View {
        VStack(spacing: 20) {
            CampCard("Order estimates", subtitle: "Recorded in camp. No purchases or card charges are made.") {
                if let error = store.ledgerError {
                    Text(error).font(.callout).foregroundStyle(.red)
                    if ledger != nil {
                        Text("Showing the last loaded amounts.").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                }
                if refreshing { ProgressView("Loading order estimates…").font(.callout) }
                if ledger != nil {
                    spendingSummary
                } else if !refreshing {
                    Text(store.recommenderUserID == nil
                         ? "Save your preferences or join a group to create your profile."
                         : "Spending is unavailable until the ledger loads.")
                        .font(.callout).foregroundStyle(CampPalette.muted)
                    if store.recommenderUserID == nil {
                        Button("Your preferences") { store.section = .you }.buttonStyle(CampActionStyle(primary: false))
                    }
                }
                Button(refreshing ? "Refreshing…" : store.ledgerError == nil ? "Refresh" : "Retry") {
                    Task { await refresh() }
                }.buttonStyle(CampActionStyle(primary: false)).disabled(refreshing || store.recommenderUserID == nil)
                DisclosureGroup("Demo card preview · not a payment card") { lunchCard.padding(.top, 12) }
            }

            if ledger != nil {
                CampCard("Recent activity", subtitle: "Latest recorded items. Amounts are estimates, not payments.") {
                    ForEach(Array(transactions.enumerated()), id: \.element.id) { index, transaction in
                        if index > 0 { Divider() }
                        transactionRow(transaction)
                    }
                    if entries.isEmpty {
                        Text("No recorded orders yet. Join a group on Today to get started.")
                            .font(.callout).foregroundStyle(CampPalette.muted)
                        Button("See today’s groups") { store.section = .today }.buttonStyle(CampActionStyle(primary: false))
                    }
                }
            }
        }
        .task { await refresh() }
    }

    private func refresh() async {
        guard !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        await store.refreshLedger()
    }

    private var spendingSummary: some View {
        VStack(alignment: .leading, spacing: 10) {
            CampPair(compact: compact) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("ORDERS THIS MONTH").font(.caption.weight(.semibold)).foregroundStyle(CampPalette.muted)
                    Text(LunchStyle.money(monthlySpendCents)).font(.system(size: 25, weight: .semibold, design: .rounded)).monospacedDigit()
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("MONTHLY ESTIMATE").font(.caption.weight(.semibold)).foregroundStyle(CampPalette.muted)
                    Text(LunchStyle.money(monthlyBudgetCents)).font(.system(size: 14, weight: .semibold, design: .rounded)).monospacedDigit()
                }
            }
            ProgressView(value: Double(max(0, min(monthlySpendCents, monthlyBudgetCents))), total: Double(max(1, monthlyBudgetCents)))
                .tint(monthlySpendCents > monthlyBudgetCents ? .orange : CampPalette.green)
            VStack(alignment: .leading, spacing: 6) {
                Text(monthlySpendCents > monthlyBudgetCents
                     ? "\(LunchStyle.money(monthlySpendCents - monthlyBudgetCents)) over the estimate"
                     : "\(LunchStyle.money(monthlyBudgetCents - monthlySpendCents)) below the estimate")
                    .foregroundStyle(monthlySpendCents > monthlyBudgetCents ? .orange : CampPalette.muted)
                if savingsThisMonthCents > 0 {
                    Text("\(LunchStyle.money(savingsThisMonthCents)) saved by sharing delivery").foregroundStyle(CampPalette.green)
                }
            }.font(.caption).foregroundStyle(CampPalette.muted)
            Text("The monthly estimate assumes 20 orders at your lunch budget in camp. It is not an available card balance.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }
    }

    private static func day(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) { return "Today" }
        if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }

    private var lunchCard: some View {
        GeometryReader { proxy in
            cardArtwork
                .scaleEffect(proxy.size.width / 360, anchor: .topLeading)
        }
        .aspectRatio(1.586, contentMode: .fit)
        .frame(maxWidth: 400)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Demo camp company order card ending in 4821")
    }

    private var cardArtwork: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 19)
                .fill(LinearGradient(colors: [Color(red: 0.10, green: 0.17, blue: 0.12), CampPalette.green], startPoint: .topLeading, endPoint: .bottomTrailing))
            Circle().fill(CampPalette.lime.opacity(0.15)).frame(width: 230).offset(x: 205, y: -118)
            Circle().stroke(.white.opacity(0.08), lineWidth: 1).frame(width: 265).offset(x: 183, y: -136)
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("camp").font(.system(size: 23, weight: .bold, design: .rounded)).tracking(-0.7)
                        Text("CORPORATE ORDERS").font(.system(size: 8, weight: .semibold)).tracking(1.2).foregroundStyle(.white.opacity(0.68))
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
            .padding(22)
        }
        .frame(width: 360, height: 360 / 1.586)
        .clipShape(RoundedRectangle(cornerRadius: 15))
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
            Text(LunchStyle.money(transaction.amountCents)).font(.system(size: 12, weight: .semibold)).monospacedDigit()
        }
    }
}

private struct CampDemoTransaction: Identifiable {
    let id: String
    let name: String
    let detail: String
    let amountCents: Int
    let symbol: String
}
