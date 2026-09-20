import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

/// Today: the office's pending group orders (coffee runs and meals) and your own orders, all read from the backend
/// database (`/v1/groups`, `/v1/ledger`). Joining, creating and leaving write back through the same API.
struct CampTodayPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    let previewActivity: () -> Void
    @State private var creatingGroup = false
    @State private var choosingGroup: DemoLunchGroup?
    @State private var filter: OrderCategory?

    private var todaysOrders: [LunchLedgerEntry] {
        (store.ledger?.entries ?? []).filter { Calendar.current.isDateInToday($0.date) }
    }
    private var visibleGroups: [DemoLunchGroup] {
        store.lunchGroups.filter { filter == nil || $0.kind == filter }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ForEach(todaysOrders.prefix(2)) { entry in
                HStack(spacing: 16) {
                    Image(systemName: entry.symbol).font(.title2)
                        .foregroundStyle(CampPalette.green).frame(width: 52, height: 52)
                        .background(CampPalette.lime.opacity(0.4)).clipShape(RoundedRectangle(cornerRadius: 14))
                    VStack(alignment: .leading, spacing: 5) {
                        Text(entry.item).font(.system(size: 17, weight: .semibold, design: .rounded))
                        Text("\(entry.restaurant) · \(LunchStyle.money(entry.amountCents)) · via \(entry.source)").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                    Spacer()
                    CampBadge(text: entry.status.capitalized, active: true)
                }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 20).fill(.white))
                    .overlay(RoundedRectangle(cornerRadius: 20).stroke(CampPalette.border))
                    .accessibilityLabel("Your order today: \(entry.item) from \(entry.restaurant), \(entry.status)")
            }

            HStack {
                Text("Group orders").font(.system(size: 22, weight: .semibold, design: .rounded))
                Spacer()
                Button { creatingGroup = true } label: {
                    Label("New order", systemImage: "plus").labelStyle(.titleAndIcon)
                }.buttonStyle(CampActionStyle())
                    .disabled(store.restaurants.isEmpty)
                    .accessibilityLabel("Start a new group order")
            }.padding(.top, 6)
            categoryFilter
            ForEach(store.myGroups) { group in
                let mine = store.myOptions(in: group)
                if !mine.isEmpty {
                    HStack(spacing: 12) {
                        Image(systemName: group.kind.symbol).foregroundStyle(CampPalette.green)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("You’re in \(group.name) · \(group.delivery)").font(.callout.weight(.semibold))
                            Text("\(group.kind.label) · \(mine.map(\.name).joined(separator: ", ")) · \(LunchStyle.money(store.selectionTotalCents(mine)))")
                                .font(.caption).foregroundStyle(CampPalette.muted)
                        }
                        Spacer()
                        Button("Leave") { store.leave(group) }.buttonStyle(.plain).font(.caption)
                    }.padding(18).background(CampPalette.lime.opacity(0.35)).clipShape(RoundedRectangle(cornerRadius: 14))
                }
            }
            if let error = store.groupsError {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Text(error).font(.callout).textSelection(.enabled)
                    Spacer()
                    Button("Retry") { Task { await store.refreshAll() } }.buttonStyle(CampActionStyle(primary: false))
                }.padding(16).background(.white).clipShape(RoundedRectangle(cornerRadius: 14))
                    .overlay(RoundedRectangle(cornerRadius: 14).stroke(CampPalette.border))
            } else if visibleGroups.isEmpty {
                HStack(spacing: 12) {
                    if store.groupsBusy { ProgressView().controlSize(.small) }
                    Text(store.groupsBusy ? "Loading today’s orders from the backend…"
                         : filter == nil ? "No group orders yet today. Start one." : "No \(filter!.label.lowercased()) orders yet today. Start one.")
                        .font(.callout).foregroundStyle(CampPalette.muted)
                }.padding(16)
            }
            ForEach(visibleGroups) { group in
                CampCard(group.name, subtitle: group.cuisine) {
                    HStack(spacing: 16) {
                        CampBadge(text: group.kind.label, active: group.kind == .coffee)
                        Label("\(store.participantCount(for: group)) people", systemImage: "person.2")
                        Spacer()
                        Label(group.delivery, systemImage: group.kind == .coffee ? "cup.and.saucer" : "bag")
                    }.font(.system(size: 12)).foregroundStyle(CampPalette.muted)
                    HStack {
                        Text("\(LunchStyle.money(store.savingsCents(for: group))) shared delivery savings")
                            .font(.system(size: 12, weight: .medium)).foregroundStyle(CampPalette.green)
                        Spacer(minLength: 12)
                        Button(store.myOption(in: group) != nil ? "Change order" : "View menu") { choosingGroup = group }
                            .buttonStyle(CampActionStyle())
                    }
                }
            }
            HStack {
                Text(store.groupsSummary == nil ? "Orders and prices come from the camp backend." : "Live from the camp database · all-in price estimates. No purchases.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
                Spacer()
                Button("Preview order invitation", action: previewActivity).buttonStyle(CampActionStyle(primary: false))
            }
            CampPair(compact: compact) {
                summaryCard("Total savings", value: LunchStyle.money(store.totalSavingsCents), symbol: "arrow.down.right")
                summaryCard("People ordering", value: "\(store.peopleOrdering)", symbol: "person.2.fill")
            }
            Text("Today’s group orders · shared delivery, one fee per place · one coffee and one meal per person").font(.caption).foregroundStyle(CampPalette.muted)
        }
        .task { await store.refreshAll() }
        .sheet(isPresented: $creatingGroup) { CampCreateGroupSheet(store: store, category: filter ?? .meal) }
        .sheet(item: $choosingGroup) { group in
            CampGroupMenuSheet(store: store, group: group)
        }
    }

    private var categoryFilter: some View {
        HStack(spacing: 8) {
            filterChip(nil, label: "All")
            ForEach(OrderCategory.allCases) { category in filterChip(category, label: category.label) }
            Spacer()
        }
    }
    private func filterChip(_ category: OrderCategory?, label: String) -> some View {
        Button { filter = category } label: {
            Text(label).font(.system(size: 12, weight: filter == category ? .semibold : .regular))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(filter == category ? CampPalette.lime.opacity(0.6) : .white)
                .clipShape(Capsule()).overlay(Capsule().stroke(CampPalette.border))
        }.buttonStyle(.plain)
    }

    private func summaryCard(_ title: String, value: String, symbol: String) -> some View {
        CampCard(title) {
            HStack {
                Text(value).font(.system(size: 30, weight: .semibold, design: .rounded)).monospacedDigit()
                Spacer()
                Image(systemName: symbol).foregroundStyle(CampPalette.green)
            }
        }
    }
}

/// The group-order sheet: the place's public rating, your top picks, then the full menu. Anything on the menu can be
/// ordered, as many items as the budget allows; the backend adds them to the group's list.
private struct CampGroupMenuSheet: View {
    @ObservedObject var store: CampSettingsStore
    let group: DemoLunchGroup
    @State private var selection: [LunchOption] = []
    @Environment(\.dismiss) private var dismiss
    private var menu: LunchMenu? { store.menu(for: group) }
    private var topIDs: Set<String> { Set(menu?.top.map(\.id) ?? []) }
    private var spentCents: Int { store.selectionTotalCents(selection) }
    private var remainingCents: Int { max(0, store.personBudgetCents - spentCents) }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(group.name).font(.title2.weight(.semibold))
                    HStack(spacing: 8) {
                        CampBadge(text: group.kind.label, active: group.kind == .coffee)
                        if let rating = menu?.ratingLabel { Text(rating).font(.caption.weight(.medium)) }
                        Text("\(group.people) joining · \(group.delivery)").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                }
                Spacer()
                Button("Done") { dismiss() }.buttonStyle(.plain)
            }
            if let sources = menu?.ratings, !sources.isEmpty {
                Text(sources.sorted { $0.key < $1.key }.map { "\($0.key.capitalized) \(String(format: "%.1f", $0.value))" }.joined(separator: " · "))
                    .font(.caption2).foregroundStyle(CampPalette.muted)
            }
            if let note = menu?.recommendations?.first { Text(note).font(.caption).foregroundStyle(CampPalette.muted).lineLimit(2) }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let menu {
                        section("Top picks for you", items: menu.top, reasons: true)
                        section("Full menu", items: menu.items.filter { !topIDs.contains($0.id) }, reasons: false)
                    } else if let error = store.menuError {
                        Text(error).font(.callout).foregroundStyle(.red)
                        VStack(spacing: 8) { ForEach(group.options) { option in row(option, reason: nil) } }
                    } else {
                        HStack(spacing: 10) { ProgressView().controlSize(.small); Text("Loading the menu…").font(.callout).foregroundStyle(CampPalette.muted) }
                        VStack(spacing: 8) { ForEach(group.options) { option in row(option, reason: nil) } }
                    }
                }
            }.frame(maxHeight: 420)
            budgetBar
            Text("Public rating from review sites · all-in estimate with the delivery fee shared once, however many items you pick. No purchase.")
                .font(.caption).foregroundStyle(CampPalette.muted)
            Button(confirmTitle) {
                store.join(selection, group: group); dismiss()
            }.buttonStyle(CampActionStyle()).disabled(selection.isEmpty)
        }.padding(24).frame(idealWidth: 460, maxWidth: 520).foregroundStyle(CampPalette.ink).background(.white)
            .onAppear { selection = store.myOptions(in: group) }
            .task { await store.loadMenu(for: group) }
    }

    private var confirmTitle: String {
        let verb = store.myOption(in: group) == nil ? "Confirm & join group" : "Confirm order change"
        guard !selection.isEmpty else { return verb }
        let items = selection.count == 1 ? "1 item" : "\(selection.count) items"
        return "\(verb) · \(items) · \(LunchStyle.money(spentCents))"
    }

    /// The per-order cap — the employee's live Ramp limit when the Ramp card is connected, otherwise the office
    /// setting. Once the selection fills it, everything else on the menu greys out, so the budget is visible as a
    /// limit rather than an error after the fact.
    private var budgetBar: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("\(LunchStyle.money(spentCents)) of \(LunchStyle.money(store.personBudgetCents)) budget")
                    .font(.caption.weight(.medium)).monospacedDigit()
                Spacer()
                Text(remainingCents == 0 ? "Budget used · other items are greyed out" : "\(LunchStyle.money(remainingCents)) left")
                    .font(.caption).foregroundStyle(remainingCents == 0 ? .orange : CampPalette.muted)
            }
            ProgressView(value: Double(min(spentCents, store.personBudgetCents)), total: Double(max(1, store.personBudgetCents)))
                .tint(remainingCents == 0 ? .orange : CampPalette.green)
            Text(store.personBudgetSource).font(.caption2).foregroundStyle(CampPalette.muted)
        }.accessibilityElement(children: .combine)
            .accessibilityLabel("\(LunchStyle.money(spentCents)) of \(LunchStyle.money(store.personBudgetCents)) budget used")
    }

    private func toggle(_ option: LunchOption) {
        if let i = selection.firstIndex(where: { $0.id == option.id }) { selection.remove(at: i) }
        else if store.fitsBudget(option, with: selection) { selection.append(option) }
    }

    private func section(_ title: String, items: [LunchMenuItem], reasons: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased()).font(.system(size: 10, weight: .semibold)).tracking(0.8).foregroundStyle(CampPalette.muted)
            ForEach(items) { item in row(item.option, reason: reasons ? item.reason : nil, popular: item.popular ?? false) }
        }
    }
    private func row(_ option: LunchOption, reason: String?, popular: Bool = false) -> some View {
        let picked = selection.contains { $0.id == option.id }
        let affordable = store.fitsBudget(option, with: selection)
        return Button { toggle(option) } label: {
            HStack(spacing: 12) {
                Image(systemName: picked ? "checkmark.square.fill" : "square")
                    .foregroundStyle(picked ? CampPalette.green : (affordable ? CampPalette.muted : CampPalette.muted.opacity(0.5)))
                Image(systemName: option.symbol).font(.caption).foregroundStyle(CampPalette.muted).frame(width: 16)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(option.name).font(.callout.weight(.semibold))
                        if popular { Text("Popular").font(.system(size: 9, weight: .semibold)).padding(.horizontal, 6).padding(.vertical, 2).background(CampPalette.lime.opacity(0.5)).clipShape(Capsule()) }
                    }
                    if !option.detail.isEmpty { Text(option.detail).font(.caption).foregroundStyle(CampPalette.muted).lineLimit(1) }
                    if let reason, !reason.isEmpty { Text(reason.capitalized).font(.caption2).foregroundStyle(CampPalette.green) }
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text(LunchStyle.money(option.priceCents)).font(.callout).monospacedDigit()
                    if !affordable { Text("Over budget").font(.caption2).foregroundStyle(.orange) }
                }
            }.padding(12).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 12)).contentShape(Rectangle())
        }.buttonStyle(.plain).disabled(!affordable).opacity(affordable ? 1 : 0.45)
            .accessibilityLabel("\(option.name), \(LunchStyle.money(option.priceCents))\(affordable ? "" : ", over your remaining budget")")
            .accessibilityAddTraits(picked ? [.isSelected] : [])
    }
}

private struct CampCreateGroupSheet: View {
    @ObservedObject var store: CampSettingsStore
    @Environment(\.dismiss) private var dismiss
    @State private var category: OrderCategory
    @State private var restaurantID = ""
    @State private var delivery: String
    @State private var mealIDs: [String] = []
    @State private var working = false
    @State private var cravingText = ""
    @State private var cravingPick: LunchCravingMatch?
    init(store: CampSettingsStore, category: OrderCategory) {
        self.store = store
        _category = State(initialValue: category)
        _delivery = State(initialValue: CampTimePicker.label(category.defaultMinutes))
    }
    private var choices: [LunchRestaurant] { store.restaurants(for: category) }
    /// A craving match wins over the picker: its options are the dishes that matched what was asked for.
    private var restaurant: LunchRestaurant? { cravingPick?.restaurant ?? choices.first { $0.id == restaurantID } ?? choices.first }
    private var meals: [LunchOption] { mealIDs.compactMap { id in restaurant?.options.first { $0.id == id } } }
    private var deliveryMinutes: Int? {
        guard let minutes = CampTimingField.Kind.time.parse(delivery), (300...1320).contains(minutes) else { return nil }
        return minutes
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("New group order").font(.title2.weight(.semibold))
                Spacer()
                Button("Cancel") { dismiss() }.buttonStyle(.plain)
            }
            CampField("Order") {
                Picker("Order", selection: $category) {
                    ForEach(OrderCategory.allCases) { Text($0.label).tag($0) }
                }.pickerStyle(.segmented).labelsHidden()
            }
            cravingSearch
            if let pick = cravingPick {
                CampField("From your craving") {
                    HStack(spacing: 12) {
                        Image(systemName: pick.restaurant.symbol).foregroundStyle(CampPalette.green)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(pick.restaurant.name).font(.callout.weight(.semibold))
                            Text(pick.reason).font(.caption).foregroundStyle(CampPalette.muted)
                        }
                        Spacer()
                        Button("Browse all") { cravingPick = nil; mealIDs = [] }.buttonStyle(.plain).font(.caption)
                    }.padding(12).background(CampPalette.lime.opacity(0.35)).clipShape(RoundedRectangle(cornerRadius: 12))
                }
            } else {
                CampField(category == .coffee ? "Café" : "Restaurant") {
                    Picker("Place", selection: $restaurantID) {
                        ForEach(choices) { r in
                            Text(r.rating.map { "\(r.name) · \(String(format: "%.1f", $0))★" } ?? r.name).tag(r.id)
                        }
                    }.labelsHidden()
                    if let restaurant { Text(restaurant.cuisine).font(.caption).foregroundStyle(CampPalette.muted) }
                    if choices.isEmpty { Text("No places for this category yet.").font(.caption).foregroundStyle(.red) }
                }
            }
            CampField("Arrival time") {
                CampTextField(title: "e.g. 12:30 PM", text: $delivery)
                    .onSubmit { if let minutes = deliveryMinutes { delivery = CampTimePicker.label(minutes) } }
                if deliveryMinutes == nil {
                    Text("Enter a time between 5 AM and 10 PM.").font(.caption).foregroundStyle(.red)
                }
            }
            CampField("Your pick · tick as many as your budget allows") {
                VStack(spacing: 8) {
                    ForEach(restaurant?.options ?? []) { option in
                        let picked = mealIDs.contains(option.id)
                        let affordable = store.fitsBudget(option, with: meals)
                        Button { toggle(option) } label: {
                            HStack(spacing: 10) {
                                Image(systemName: picked ? "checkmark.square.fill" : "square")
                                    .foregroundStyle(picked ? CampPalette.green : CampPalette.muted)
                                Text(option.name).font(.callout)
                                Spacer()
                                if !affordable { Text("Over budget").font(.caption2).foregroundStyle(.orange) }
                                Text(LunchStyle.money(option.priceCents)).font(.callout)
                            }.padding(14).background(CampPalette.background)
                                .clipShape(RoundedRectangle(cornerRadius: 10)).contentShape(Rectangle())
                        }.buttonStyle(.plain).disabled(!affordable).opacity(affordable ? 1 : 0.45)
                    }
                    HStack {
                        Text("\(LunchStyle.money(store.selectionTotalCents(meals))) of \(LunchStyle.money(store.personBudgetCents)) budget")
                            .font(.caption).foregroundStyle(CampPalette.muted).monospacedDigit()
                        Spacer()
                    }
                }
            }
            Text("Saved to the camp database and visible to the office. This replaces your current \(category.label.lowercased()) order. Added to your camp calendar on Mac. No purchase.")
                .font(.caption).foregroundStyle(CampPalette.muted)
            Button(working ? "Creating…" : "Create & join") {
                guard let restaurant, !meals.isEmpty, let minutes = deliveryMinutes else { return }
                working = true
                Task {
                    if await store.createGroup(restaurant: restaurant, arrivalMinutes: minutes, meals: meals, category: category) { dismiss() }
                    working = false
                }
            }.buttonStyle(CampActionStyle()).disabled(meals.isEmpty || deliveryMinutes == nil || working)
        }.padding(24).frame(idealWidth: 440, maxWidth: 480)
            .foregroundStyle(CampPalette.ink).background(.white)
            .onAppear {
                if restaurantID.isEmpty { restaurantID = choices.first?.id ?? "" }
                store.clearCraving()
            }
            .onChange(of: restaurantID) { _ in mealIDs = [] }
            .onChange(of: category) { next in
                cravingPick = nil
                restaurantID = store.restaurants(for: next).first?.id ?? ""; mealIDs = []
                delivery = CampTimePicker.label(next.defaultMinutes)
            }
    }

    /// None of the places appeal: say what you want instead ("I want tacos") and the backend's OpenAI model
    /// searches the catalog's menus for it.
    private var cravingSearch: some View {
        CampField("Craving something else?") {
            HStack(spacing: 8) {
                CampTextField(title: category == .coffee ? "e.g. iced oat latte" : "e.g. I want tacos", text: $cravingText)
                    .onSubmit { search() }
                Button(store.cravingBusy ? "Searching…" : "Find it", action: search)
                    .buttonStyle(CampActionStyle(primary: false))
                    .disabled(store.cravingBusy || cravingText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if let error = store.cravingError { Text(error).font(.caption).foregroundStyle(.red) }
            if let result = store.craving {
                if !result.interpretation.isEmpty {
                    HStack(spacing: 8) { CampBadge(text: result.interpretation, active: true) }
                }
                if let note = result.note, !note.isEmpty { Text(note).font(.caption).foregroundStyle(CampPalette.muted) }
                VStack(spacing: 8) {
                    ForEach(result.matches) { match in
                        Button { choose(match) } label: {
                            HStack(spacing: 10) {
                                Image(systemName: cravingPick?.id == match.id ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(CampPalette.green)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(match.restaurant.name).font(.callout.weight(.semibold))
                                    Text(match.reason).font(.caption).foregroundStyle(CampPalette.muted).lineLimit(2)
                                }
                                Spacer()
                                if let first = match.restaurant.options.first { Text(LunchStyle.money(first.priceCents)).font(.callout).monospacedDigit() }
                            }.padding(12).background(CampPalette.background)
                                .clipShape(RoundedRectangle(cornerRadius: 10)).contentShape(Rectangle())
                        }.buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func search() {
        Task {
            await store.searchCraving(cravingText, category: category)
            if let first = store.craving?.matches.first { choose(first) }
        }
    }

    private func choose(_ match: LunchCravingMatch) {
        cravingPick = match
        mealIDs = match.restaurant.options.first.map { [$0.id] } ?? []
    }

    private func toggle(_ option: LunchOption) {
        if let i = mealIDs.firstIndex(of: option.id) { mealIDs.remove(at: i) }
        else if store.fitsBudget(option, with: meals) { mealIDs.append(option.id) }
    }
}
