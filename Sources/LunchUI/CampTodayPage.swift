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
    @State private var refreshing = false

    private var todaysOrders: [LunchLedgerEntry] {
        (store.ledger?.entries ?? []).filter { Calendar.current.isDateInToday($0.date) }
    }
    private var visibleGroups: [DemoLunchGroup] {
        store.lunchGroups.filter { filter == nil || $0.kind == filter }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            if !todaysOrders.isEmpty {
                DisclosureGroup("Your recorded items today · \(todaysOrders.count)") {
                    ForEach(todaysOrders) { entry in
                        HStack(spacing: 12) {
                            Image(systemName: entry.symbol).foregroundStyle(CampPalette.green)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(entry.item).font(.callout.weight(.semibold))
                                Text("\(entry.restaurant) · \(LunchStyle.money(entry.amountCents)) · \(entry.status)")
                                    .font(.caption).foregroundStyle(CampPalette.muted)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
                            .accessibilityElement(children: .combine)
                    }
                }
            }

            CampPair(compact: compact) {
                Text("Group orders").font(.system(size: 22, weight: .semibold, design: .rounded))
                Button { creatingGroup = true } label: {
                    Label("New order", systemImage: "plus").labelStyle(.titleAndIcon)
                }.buttonStyle(CampActionStyle())
                    .disabled(store.restaurants.isEmpty)
                    .accessibilityLabel("Start a new group order")
            }.padding(.top, 6)
            categoryFilter
            if store.restaurants.isEmpty {
                Text(refreshing ? "Loading places for new orders…" : "No places loaded. Refresh to start a new order.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
            }
            if let error = store.groupsError {
                VStack(alignment: .leading, spacing: 10) {
                    Label("Orders could not be updated", systemImage: "exclamationmark.triangle")
                        .font(.callout.weight(.semibold))
                    Text(error).font(.callout).textSelection(.enabled)
                    if !store.lunchGroups.isEmpty {
                        Text("Showing the last loaded orders.").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                    Button(refreshing ? "Refreshing…" : "Retry") { Task { await refresh() } }
                        .buttonStyle(CampActionStyle(primary: false)).disabled(refreshing)
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
                let mine = store.myOptions(in: group)
                CampCard(group.name, subtitle: group.cuisine) {
                    HStack(spacing: 16) {
                        CampBadge(text: group.kind.label, active: group.kind == .coffee)
                        Label("\(store.participantCount(for: group)) people", systemImage: "person.2")
                        Spacer()
                        Label(group.delivery, systemImage: group.kind == .coffee ? "cup.and.saucer" : "bag")
                    }.font(.system(size: 12)).foregroundStyle(CampPalette.muted)
                    if !mine.isEmpty {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("Your selection · \(LunchStyle.money(store.selectionTotalCents(mine))) estimated")
                                .font(.callout.weight(.semibold))
                            Text(mine.map(\.name).joined(separator: ", ")).font(.caption)
                        }.foregroundStyle(CampPalette.green)
                    }
                    CampPair(compact: compact) {
                        Text("\(LunchStyle.money(store.savingsCents(for: group))) shared delivery savings")
                            .font(.system(size: 12, weight: .medium)).foregroundStyle(CampPalette.green)
                        HStack {
                            Button(mine.isEmpty ? "View menu" : "Change order") { choosingGroup = group }
                                .buttonStyle(CampActionStyle())
                            if !mine.isEmpty {
                                Button("Leave") { store.leave(group) }.buttonStyle(CampActionStyle(primary: false))
                                    .accessibilityLabel("Leave \(group.name)")
                            }
                        }
                    }
                }
            }
            if store.groupsSummary != nil {
                Text("\(LunchStyle.money(store.totalSavingsCents)) shared delivery savings · \(store.peopleOrdering) people ordering")
                    .font(.callout).foregroundStyle(CampPalette.muted)
            }
            CampPair(compact: compact) {
                Text("Orders saved in camp · prices are estimates. No purchases.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
                HStack {
                    Button(refreshing ? "Refreshing…" : "Refresh") { Task { await refresh() } }
                        .buttonStyle(CampActionStyle(primary: false)).disabled(refreshing)
                    Button("Preview invitation", action: previewActivity).buttonStyle(CampActionStyle(primary: false))
                }
            }
            Text("One coffee group and one meal group per person each day. Choose multiple items within your budget.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }
        .task { await refresh() }
        .sheet(isPresented: $creatingGroup) { CampCreateGroupSheet(store: store, category: filter ?? .meal) }
        .sheet(item: $choosingGroup) { group in
            CampGroupMenuSheet(store: store, group: group)
        }
    }

    private func refresh() async {
        guard !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        await store.refreshAll()
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
                .padding(.horizontal, 12).frame(minWidth: 44, minHeight: 44)
                .background(filter == category ? CampPalette.lime.opacity(0.6) : .white)
                .clipShape(Capsule()).overlay(Capsule().stroke(CampPalette.border))
        }.buttonStyle(.plain)
            .accessibilityAddTraits(filter == category ? [.isSelected] : [])
    }
}

/// The group-order sheet: the place's public rating, your top picks, then the full menu. Anything on the menu can be
/// ordered, as many items as the budget allows; the backend adds them to the group's list.
private struct CampGroupMenuSheet: View {
    @ObservedObject var store: CampSettingsStore
    let group: DemoLunchGroup
    @State private var selection: [LunchOption] = []
    @State private var loadingMenu = true
    @State private var menuLoadError: String?
    @Environment(\.dismiss) private var dismiss
    private var menu: LunchMenu? { store.menu(for: group) }
    private var topIDs: Set<String> { Set(menu?.top.map(\.id) ?? []) }
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
                Button("Done") { dismiss() }.buttonStyle(CampActionStyle(primary: false))
            }
            if let sources = menu?.ratings, !sources.isEmpty {
                Text(sources.sorted { $0.key < $1.key }.map { "\($0.key.capitalized) \(String(format: "%.1f", $0.value))" }.joined(separator: " · "))
                    .font(.caption2).foregroundStyle(CampPalette.muted)
            }
            if let note = menu?.recommendations?.first { Text(note).font(.caption).foregroundStyle(CampPalette.muted).lineLimit(2) }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if loadingMenu {
                        ProgressView("Loading the menu…").font(.callout)
                    }
                    if let error = menuLoadError {
                        Text(error).font(.callout).foregroundStyle(.red)
                        if menu != nil {
                            Text("Showing the last loaded menu.").font(.caption).foregroundStyle(CampPalette.muted)
                        }
                        if group.restaurantId != nil {
                            Button("Retry menu") { Task { await loadMenu() } }
                                .buttonStyle(CampActionStyle(primary: false)).disabled(loadingMenu)
                        }
                    }
                    if let menu {
                        section("Top picks for you", items: menu.top, reasons: true)
                        section("Full menu", items: menu.items.filter { !topIDs.contains($0.id) }, reasons: false)
                        if menu.top.isEmpty && menu.items.isEmpty {
                            Text("No menu items available for this group.").font(.callout).foregroundStyle(CampPalette.muted)
                        }
                    } else {
                        Text("Existing group picks").font(.caption.weight(.semibold)).foregroundStyle(CampPalette.muted)
                        VStack(spacing: 8) { ForEach(group.options) { option in row(option, reason: nil) } }
                    }
                }
            }
            CampCartSummary(store: store, selection: selection)
            Text("Menu prices are estimates. Camp calculates shared delivery when your order is recorded. No purchase.")
                .font(.caption).foregroundStyle(CampPalette.muted)
            Button(confirmTitle) {
                store.join(selection, group: group); dismiss()
            }.buttonStyle(CampActionStyle()).disabled(selection.isEmpty)
        }.padding(24).frame(idealWidth: 460, maxWidth: 520, idealHeight: 700).foregroundStyle(CampPalette.ink).background(.white)
            .onAppear { selection = store.myOptions(in: group) }
            .task { await loadMenu() }
    }

    private var confirmTitle: String {
        store.myOption(in: group) == nil ? "Confirm & join group" : "Confirm order change"
    }

    private func loadMenu() async {
        loadingMenu = true
        defer { loadingMenu = false }
        guard group.restaurantId != nil else {
            menuLoadError = "A full menu is unavailable for this group."
            return
        }
        await store.loadMenu(for: group)
        menuLoadError = store.menuError
    }

    private func toggle(_ option: LunchOption) {
        if let i = selection.firstIndex(where: { $0.id == option.id }) { selection.remove(at: i) }
        else if store.fitsBudget(option, with: selection) { selection.append(option) }
    }

    private func section(_ title: String, items: [LunchMenuItem], reasons: Bool) -> some View {
        Group {
            if !items.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text(title).font(.caption.weight(.semibold)).foregroundStyle(CampPalette.muted)
                    ForEach(items) { item in row(item.option, reason: reasons ? item.reason : nil, popular: item.popular ?? false) }
                }
            }
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
            }.padding(12).frame(minHeight: 44).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 12)).contentShape(Rectangle())
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
    @State private var creationError: String?
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
                Button("Cancel") { dismiss() }.buttonStyle(CampActionStyle(primary: false)).disabled(working)
            }
            ScrollView { form.disabled(working) }
            CampCartSummary(store: store, selection: meals)
            if let creationError { Text(creationError).font(.callout).foregroundStyle(.red) }
            Button(working ? "Creating…" : "Create & join") {
                guard !working, let restaurant, !meals.isEmpty, let minutes = deliveryMinutes else { return }
                working = true
                creationError = nil
                Task {
                    if await store.createGroup(restaurant: restaurant, arrivalMinutes: minutes, meals: meals, category: category) {
                        dismiss()
                    } else {
                        creationError = store.groupsError ?? "The order could not be created. Check your selection and try again."
                    }
                    working = false
                }
            }.buttonStyle(CampActionStyle()).disabled(meals.isEmpty || deliveryMinutes == nil || working || store.cravingBusy)
        }.padding(24).frame(idealWidth: 440, maxWidth: 480, idealHeight: 700)
            .foregroundStyle(CampPalette.ink).background(.white)
            .interactiveDismissDisabled(working)
            .onAppear {
                if restaurantID.isEmpty { restaurantID = choices.first?.id ?? "" }
                store.clearCraving()
            }
            .onChange(of: restaurantID) { _ in mealIDs = [] }
            .onChange(of: category) { next in
                cravingPick = nil
                store.clearCraving()
                restaurantID = store.restaurants(for: next).first?.id ?? ""; mealIDs = []
                delivery = CampTimePicker.label(next.defaultMinutes)
            }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 20) {
            CampField("Order") {
                Picker("Order", selection: $category) {
                    ForEach(OrderCategory.allCases) { Text($0.label).tag($0) }
                }.pickerStyle(.segmented).labelsHidden().disabled(store.cravingBusy)
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
                        Button("Browse all") { cravingPick = nil; mealIDs = [] }.buttonStyle(CampActionStyle(primary: false))
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
            CampField("Choose items") {
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
                            .accessibilityLabel("\(option.name), \(LunchStyle.money(option.priceCents))")
                            .accessibilityAddTraits(picked ? [.isSelected] : [])
                    }
                    if let restaurant, restaurant.options.isEmpty {
                        Text("No items available here. Choose another place.").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                }
            }
            Text("Saved to the camp database and visible to the office. This replaces your current \(category.label.lowercased()) order. Added to your camp calendar on Mac. No purchase.")
                .font(.caption).foregroundStyle(CampPalette.muted)
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
                    Text(result.interpretation).font(.caption).foregroundStyle(CampPalette.green)
                }
                if result.matches.isEmpty { Text("No matches. Try another craving or browse the places below.").font(.caption) }
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
                            .accessibilityAddTraits(cravingPick?.id == match.id ? [.isSelected] : [])
                    }
                }
            }
        }
    }

    private func search() {
        guard !store.cravingBusy else { return }
        let query = cravingText
        let requestedCategory = category
        Task {
            await store.searchCraving(query, category: requestedCategory)
            guard query == cravingText, requestedCategory == category else { return }
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

private struct CampCartSummary: View {
    @ObservedObject var store: CampSettingsStore
    let selection: [LunchOption]
    private var total: Int { store.selectionTotalCents(selection) }
    private var budget: Int { store.personBudgetCents }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(selection.isEmpty ? "Choose at least one item" : "\(selection.count) item\(selection.count == 1 ? "" : "s") · estimated total")
                    .font(.callout)
                Spacer()
                Text(LunchStyle.money(total)).font(.headline).monospacedDigit()
            }
            ProgressView(value: Double(max(0, min(total, budget))), total: Double(max(1, budget)))
                .tint(total > budget ? .orange : CampPalette.green)
            if total > budget {
                Text("\(LunchStyle.money(total - budget)) over the \(LunchStyle.money(budget)) cap. A single item can exceed the cap; additional items must fit.")
                    .font(.caption).foregroundStyle(.orange)
            } else {
                Text("\(LunchStyle.money(max(0, budget - total))) left of \(LunchStyle.money(budget))")
                    .font(.caption).foregroundStyle(CampPalette.muted)
            }
            Text(store.personBudgetSource).font(.caption).foregroundStyle(CampPalette.muted)
            if let error = store.rampLimitError {
                Text(error).font(.caption).foregroundStyle(.red)
            }
        }.accessibilityElement(children: .combine)
    }
}
