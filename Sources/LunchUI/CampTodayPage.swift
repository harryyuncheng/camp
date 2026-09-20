import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

struct CampTodayPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    let previewActivity: () -> Void
    @State private var showingCoffee = false
    @State private var creatingGroup = false
    @State private var choosingGroup: DemoLunchGroup?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Button { showingCoffee = true } label: {
                HStack(spacing: 16) {
                    Image(systemName: "cup.and.saucer.fill").font(.title2)
                        .foregroundStyle(CampPalette.green).frame(width: 52, height: 52)
                        .background(CampPalette.lime.opacity(0.4)).clipShape(RoundedRectangle(cornerRadius: 14))
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Morning coffee").font(.system(size: 17, weight: .semibold, design: .rounded))
                        Text("Corner Coffee · Today, 9:15 AM").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                    Spacer()
                    CampBadge(text: "Completed", active: true)
                    Image(systemName: "chevron.right").font(.caption).foregroundStyle(CampPalette.muted)
                }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 20).fill(.white))
                    .overlay(RoundedRectangle(cornerRadius: 20).stroke(CampPalette.border))
                    .contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityLabel("Morning coffee, completed today at 9:15 AM. View demo order")

            HStack {
                Text("Lunch groups").font(.system(size: 22, weight: .semibold, design: .rounded))
                Spacer()
                Button("Create group") { creatingGroup = true }.buttonStyle(CampActionStyle(primary: false))
            }.padding(.top, 6)
            if let group = store.selectedGroup, let meal = store.selectedMeal {
                HStack(spacing: 12) {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(CampPalette.green)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("You’re joining \(group.name)").font(.callout.weight(.semibold))
                        Text("\(meal.name) · \(LunchStyle.money(meal.priceCents))").font(.caption).foregroundStyle(CampPalette.muted)
                    }
                    Spacer()
                    Button("Leave") { store.resetGroup() }.buttonStyle(.plain).font(.caption)
                }.padding(18).background(CampPalette.lime.opacity(0.35)).clipShape(RoundedRectangle(cornerRadius: 14))
            }
            ForEach(store.lunchGroups) { group in
                CampCard(group.name, subtitle: group.cuisine) {
                    HStack(spacing: 16) {
                        Label("\(store.participantCount(for: group)) people", systemImage: "person.2")
                        Spacer()
                        Label(group.delivery, systemImage: "bag")
                    }.font(.system(size: 12)).foregroundStyle(CampPalette.muted)
                    HStack {
                        Text("\(LunchStyle.money(store.savingsCents(for: group))) shared delivery savings")
                            .font(.system(size: 12, weight: .medium)).foregroundStyle(CampPalette.green)
                        Spacer(minLength: 12)
                        Button(store.selectedGroupID == group.id ? "Change meal" : "View menu") {
                            if let request = store.requestDemoGroup { request(group) }
                            else { choosingGroup = group }
                        }.buttonStyle(CampActionStyle())
                    }
                }
            }
            HStack {
                Text("Sample orders and prices. No purchases.").font(.caption).foregroundStyle(CampPalette.muted)
                Spacer()
                #if os(macOS)
                Button("Preview lunch invitation", action: previewActivity).buttonStyle(CampActionStyle(primary: false))
                #endif
            }
            CampPair(compact: compact) {
                summaryCard("Total savings", value: LunchStyle.money(store.totalSavingsCents), symbol: "arrow.down.right")
                summaryCard("People ordering", value: "\(store.peopleOrdering)", symbol: "person.2.fill")
            }
            Text("Today’s lunch groups · demo delivery estimates").font(.caption).foregroundStyle(CampPalette.muted)
        }
        .sheet(isPresented: $creatingGroup) { CampCreateGroupSheet(store: store) }
        .sheet(isPresented: $showingCoffee) { coffeeDetail }
        .sheet(item: $choosingGroup) { group in
            CampDemoGroupMenu(store: store, group: group)
        }
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

    private var coffeeDetail: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack {
                Label("Morning coffee", systemImage: "cup.and.saucer.fill").font(.title2.weight(.semibold))
                Spacer()
                Button("Done") { showingCoffee = false }.buttonStyle(.plain)
            }
            CampBadge(text: "Completed · Demo", active: true)
            Text("Corner Coffee").font(.headline)
            Text("Today, 9:15 AM · \(store.draft.office.name)").font(.callout).foregroundStyle(CampPalette.muted)
            Divider()
            Group {
            row("Oat latte", "US$5.50")
            row("Butter croissant", "US$3.00")
            row("Your shared delivery fee", "US$1.00")
            Divider()
            row("Your total", "US$9.50")
            }
            Text("4 teammates · one delivery").font(.callout).foregroundStyle(CampPalette.green)
            Text("Demo receipt · no payment was taken.").font(.caption).foregroundStyle(CampPalette.muted)
        }.padding(26).frame(idealWidth: 440, maxWidth: 480)
            .foregroundStyle(CampPalette.ink).background(CampPalette.background)
    }
    private func row(_ title: String, _ value: String) -> some View {
        HStack { Text(title); Spacer(); Text(value).monospacedDigit() }.font(.callout)
    }
}

private struct CampDemoGroupMenu: View {
    @ObservedObject var store: CampSettingsStore
    let group: DemoLunchGroup
    @State private var selection: LunchOption?
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text(group.name).font(.title2.weight(.semibold))
                Spacer()
                Button("Done") { dismiss() }.buttonStyle(.plain)
            }
            Text("\(group.people) joining · \(group.delivery)").font(.caption).foregroundStyle(CampPalette.muted)
            ForEach(group.options) { option in
                Button { selection = option } label: {
                    HStack(spacing: 12) {
                        Image(systemName: selection?.id == option.id ? "checkmark.circle.fill" : "circle").foregroundStyle(CampPalette.green)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(option.name).font(.callout.weight(.semibold))
                            Text(option.detail).font(.caption).foregroundStyle(CampPalette.muted)
                        }
                        Spacer()
                        Text(LunchStyle.money(option.priceCents)).font(.callout)
                    }.padding(14).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 12)).contentShape(Rectangle())
                }.buttonStyle(.plain)
            }
            Text("Demo menu · dietary preferences aren’t applied. No purchase.").font(.caption).foregroundStyle(CampPalette.muted)
            Button(store.selectedGroupID == nil ? "Confirm & join group" : "Confirm lunch choice") {
                if let selection { store.join(selection, group: group); dismiss() }
            }.buttonStyle(CampActionStyle()).disabled(selection == nil)
        }.padding(24).frame(idealWidth: 440, maxWidth: 480).foregroundStyle(CampPalette.ink).background(.white)
    }
}

private struct CampCreateGroupSheet: View {
    @ObservedObject var store: CampSettingsStore
    @Environment(\.dismiss) private var dismiss
    @State private var restaurantID = DemoLunchGroup.all[0].id
    @State private var delivery = "12:30 PM"
    @State private var mealID = ""
    private var restaurant: DemoLunchGroup { DemoLunchGroup.all.first { $0.id == restaurantID } ?? DemoLunchGroup.all[0] }
    private var meal: LunchOption? { restaurant.options.first { $0.id == mealID } }
    private var deliveryMinutes: Int? {
        guard let minutes = CampTimingField.Kind.time.parse(delivery), (360...1260).contains(minutes) else { return nil }
        return minutes
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("Create a lunch group").font(.title2.weight(.semibold))
                Spacer()
                Button("Cancel") { dismiss() }.buttonStyle(.plain)
            }
            CampField("Restaurant") {
                Picker("Restaurant", selection: $restaurantID) {
                    ForEach(DemoLunchGroup.all) { Text($0.name).tag($0.id) }
                }.labelsHidden()
            }
            CampField("Delivery time") {
                CampTextField(title: "e.g. 12:30 PM", text: $delivery)
                    .onSubmit { if let minutes = deliveryMinutes { delivery = CampTimePicker.label(minutes) } }
                if deliveryMinutes == nil {
                    Text("Enter a time between 6 AM and 9 PM.").font(.caption).foregroundStyle(.red)
                }
            }
            CampField("Your meal") {
                VStack(spacing: 8) {
                    ForEach(restaurant.options) { option in
                        Button { mealID = option.id } label: {
                            HStack(spacing: 10) {
                                Image(systemName: mealID == option.id ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(CampPalette.green)
                                Text(option.name).font(.callout)
                                Spacer()
                                Text(LunchStyle.money(option.priceCents)).font(.callout)
                            }.padding(14).background(CampPalette.background)
                                .clipShape(RoundedRectangle(cornerRadius: 10)).contentShape(Rectangle())
                        }.buttonStyle(.plain)
                    }
                }
            }
            Text("Demo group · no purchase. This replaces your current lunch choice.")
                .font(.caption).foregroundStyle(CampPalette.muted)
            Button("Create & join") {
                if let meal, let minutes = deliveryMinutes,
                   store.createGroup(restaurant: restaurant, arrivalMinutes: minutes, meal: meal) { dismiss() }
            }.buttonStyle(CampActionStyle()).disabled(meal == nil || deliveryMinutes == nil)
        }.padding(24).frame(idealWidth: 440, maxWidth: 480)
            .foregroundStyle(CampPalette.ink).background(.white)
            .onChange(of: restaurantID) { _ in mealID = "" }
    }
}
