import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

struct CampTodayPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    let previewActivity: () -> Void
    @State private var showingCoffee = false
    @State private var choosingGroup: DemoLunchGroup?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            if let offer = store.latestOffer { liveOffer(offer) }
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
                CampBadge(text: "Demo")
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
            ForEach(DemoLunchGroup.all) { group in
                CampCard(group.name, subtitle: group.cuisine) {
                    HStack(spacing: 16) {
                        Label("\(group.people + (store.selectedGroupID == group.id ? 1 : 0)) people", systemImage: "person.2")
                        Spacer()
                        Label(group.delivery, systemImage: "bag")
                    }.font(.system(size: 12)).foregroundStyle(CampPalette.muted)
                    HStack {
                        Text("\(LunchStyle.money(group.deliverySavingsCents)) shared delivery savings")
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
        }
        .sheet(isPresented: $showingCoffee) { coffeeDetail }
        .sheet(item: $choosingGroup) { group in
            CampDemoGroupMenu(store: store, group: group)
        }
    }

    private func liveOffer(_ offer: MealOffer) -> some View {
        CampCard("Live recommendation", subtitle: offer.location == "office" ? "From the recommender · you are batched with \(offer.participants) people at this restaurant" : "From the recommender · home delivery, full fee") {
            ForEach(offer.options) { option in
                HStack(spacing: 12) {
                    Image(systemName: option.symbol).foregroundStyle(CampPalette.green).frame(width: 28)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(option.name).font(.system(size: 14, weight: .semibold))
                        Text("\(option.restaurant) · \(option.detail)").font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(LunchStyle.money(option.priceCents)).font(.system(size: 13, weight: .semibold))
                        Text("alone \(LunchStyle.money(option.baselineCents))").font(.system(size: 10)).foregroundStyle(CampPalette.muted)
                    }
                }.padding(12).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 12))
            }
            HStack {
                CampBadge(text: offer.suggestOnly ? "Suggest only · confirm yourself" : "Estimated all-in prices", active: !offer.suggestOnly)
                Spacer()
                Button(store.recommenderBusy ? "Working…" : "Refresh offer") { Task { await store.requestOffer(force: true) } }
                    .buttonStyle(CampActionStyle(primary: false)).disabled(store.recommenderBusy)
            }
            if !offer.note.isEmpty { Text(offer.note).font(.caption).foregroundStyle(.red) }
            if let report = store.lastLunchReport {
                Divider()
                Text("Recorded: \(report["status"]?.string ?? "-") · \((report["events"]?.array ?? []).compactMap { $0["type"]?.string }.joined(separator: ", "))")
                    .font(.system(size: 12, weight: .medium))
                ForEach((report["profileUpdates"]?.array ?? []).indices, id: \.self) { i in
                    Text("→ \(report["profileUpdates"]!.array![i].scalarText)").font(.system(size: 11)).foregroundStyle(CampPalette.green)
                }
                if let learned = report["learned"] {
                    Text("Now liking: \((learned["liking"]?.array ?? []).map { $0.scalarText }.joined(separator: " · "))").font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                }
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
