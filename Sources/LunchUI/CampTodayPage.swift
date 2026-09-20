import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

struct CampTodayPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    let previewActivity: () -> Void
    @State private var choosingMeal = false

    var body: some View {
        VStack(spacing: 20) {
            if let offer = store.latestOffer { liveOffer(offer) }
            groupHero
            HStack(spacing: 12) {
                metric("Delivery saved", value: LunchStyle.money(store.group.deliverySavingsCents), note: "fixture comparison", symbol: "arrow.down.right")
                metric("Sharing delivery", value: "\(store.group.participantCount) people", note: "one office order", symbol: "person.2")
            }
            CampCard("Your place at the table", subtitle: "An invitation to join, never an automatic purchase.") {
                if let meal = store.selectedMeal {
                    HStack(spacing: 12) {
                        Image(systemName: meal.symbol).font(.title2).foregroundStyle(CampPalette.green)
                        VStack(alignment: .leading, spacing: 5) {
                            Text(meal.name).font(.system(size: 15, weight: .semibold))
                            Text("\(LunchStyle.money(meal.priceCents)) meal · fees added at checkout")
                                .font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                        }
                        Spacer()
                        CampBadge(text: "Joined", active: true)
                    }
                    if store.groupStage == .collecting {
                        HStack {
                            Button("Change meal") { choosingMeal = true }.buttonStyle(CampActionStyle(primary: false))
                            Spacer()
                            Button("Leave demo group") { store.selectedMeal = nil }.buttonStyle(.plain).font(.caption).foregroundStyle(CampPalette.muted)
                        }
                    }
                } else {
                    Text(store.groupStage == .collecting ? "Three teammates are already in. Add your meal before the group closes." : "This demo order is closed. Start a new group below to try joining.")
                        .font(.system(size: 13)).foregroundStyle(CampPalette.muted)
                    Button("Choose a meal") { choosingMeal = true }.buttonStyle(CampActionStyle())
                        .disabled(store.groupStage != .collecting)
                }
            }
            CampCard("A little context", subtitle: "These signals will eventually help camp time your invitation.") {
                contextRow("Office presence", detail: store.draft.personal.presencePreview.rawValue, symbol: "location")
                Divider()
                contextRow("Your lunch window", detail: "\(CampTimePicker.label(store.draft.personal.lunchStart)) – \(CampTimePicker.label(store.draft.personal.lunchEnd))", symbol: "calendar")
                Divider()
                contextRow("Calendar availability", detail: store.previewConnections.contains("Calendar") ? "Demo: a free lunch window" : "Calendar not connected", symbol: "clock")
            }
            CampCard("Where the savings come from", subtitle: "Illustrative delivery-fee comparison for the same meals. Not a live quote.") {
                costRow("Separate deliveries · \(store.group.participantCount) × $6", cents: store.group.separateDeliveryCents)
                costRow("One shared delivery", cents: store.group.sharedDeliveryCents)
                Divider()
                costRow("Estimated company delivery savings", cents: store.group.deliverySavingsCents, emphasized: true)
                Text("Food, taxes, service fees, tips and discounts can affect total savings. This example compares delivery fees only.")
                    .font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                DisclosureGroup("View illustrative group total") {
                    VStack(spacing: 12) {
                        costRow("Food", cents: store.group.foodCents)
                        costRow("Estimated tax", cents: store.group.taxCents)
                        costRow("Delivery", cents: store.group.sharedDeliveryCents)
                        costRow("Service fee", cents: store.group.serviceCents)
                        costRow("Tip", cents: store.group.tipCents)
                        costRow("Group total", cents: store.group.totalCents, emphasized: true)
                    }.padding(.top, 12)
                }.font(.system(size: 12))
            }
            CampCard("Try the flow", subtitle: "Local preview controls. No order is placed or payment taken.") {
                Picker("Group state", selection: $store.groupStage) {
                    ForEach(DemoGroupStage.allCases) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented)
                HStack {
                    Button("Preview activity", action: previewActivity).buttonStyle(CampActionStyle(primary: false))
                    Spacer()
                    Button("Reset group") { store.resetGroup() }.buttonStyle(.plain).font(.caption)
                }
                Text("The existing notch / Live Activity demo is a separate local preview. It isn’t linked to this group cart yet.")
                    .font(.system(size: 11)).foregroundStyle(CampPalette.muted)
            }
        }.sheet(isPresented: $choosingMeal) { mealChooser }
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

    private var groupHero: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Label("OFFICE GROUP ORDER", systemImage: "bag").font(.system(size: 10, weight: .semibold)).tracking(1)
                Spacer()
                CampBadge(text: "Demo · \(store.groupStage.rawValue.lowercased())", active: true)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(store.groupStage == .delivered ? "Lunch has landed." : "The Green Table")
                    .font(.system(size: compact ? 27 : 32, weight: .semibold, design: .rounded)).tracking(-0.7)
                Text("A fictional neighborhood kitchen. One delivery to \(store.draft.office.name).")
                    .font(.system(size: 12)).foregroundStyle(CampPalette.ink.opacity(0.7))
            }
            HStack(spacing: 8) {
                ForEach(["S", "J", "M"], id: \.self) { letter in
                    Text(letter).font(.system(size: 12, weight: .semibold)).frame(width: 30, height: 30)
                        .background(.white.opacity(0.55)).clipShape(Circle())
                }
                Text(store.selectedMeal == nil ? "+ your seat" : "+ you’re in")
                    .font(.system(size: 12, weight: .medium)).padding(.leading, 4)
                Spacer()
            }
            Rectangle().fill(CampPalette.ink.opacity(0.12)).frame(height: 1)
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("ORDER CUTOFF").font(.system(size: 9, weight: .medium)).tracking(1)
                    Text(CampTimePicker.label(store.draft.office.cutoff)).font(.system(size: 17, weight: .semibold, design: .rounded))
                }
                Spacer()
                VStack(alignment: .leading, spacing: 5) {
                    Text("DELIVERY WINDOW").font(.system(size: 9, weight: .medium)).tracking(1)
                    Text("\(CampTimePicker.label(store.draft.office.deliveryStart))–\(CampTimePicker.label(store.draft.office.deliveryEnd))")
                        .font(.system(size: compact ? 12 : 17, weight: .semibold, design: .rounded))
                }
            }
        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
            .background(CampPalette.lime).clipShape(RoundedRectangle(cornerRadius: 23))
    }

    private func metric(_ title: String, value: String, note: String, symbol: String) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Image(systemName: symbol).foregroundStyle(CampPalette.green)
            Text(value).font(.system(size: compact ? 22 : 27, weight: .semibold, design: .rounded)).minimumScaleFactor(0.8).lineLimit(1)
            Text(title).font(.system(size: 11, weight: .medium))
            Text(note).font(.system(size: 10)).foregroundStyle(CampPalette.muted)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(18).background(.white)
            .clipShape(RoundedRectangle(cornerRadius: 18))
    }

    private func contextRow(_ title: String, detail: String, symbol: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).frame(width: 22).foregroundStyle(CampPalette.green)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 12, weight: .medium))
                Text(detail).font(.system(size: 11)).foregroundStyle(CampPalette.muted)
            }
            Spacer()
        }
    }

    private func costRow(_ title: String, cents: Int, emphasized: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(.system(size: 12, weight: emphasized ? .semibold : .regular))
            Spacer(minLength: 12)
            Text(LunchStyle.money(cents)).font(.system(size: 13, weight: .semibold)).monospacedDigit()
        }.foregroundStyle(emphasized ? CampPalette.green : CampPalette.ink)
    }

    private var mealChooser: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("Find your lunch.").font(.system(size: 25, weight: .semibold, design: .rounded))
                Spacer()
                Button { choosingMeal = false } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(CampPalette.muted) }.buttonStyle(.plain)
            }
            Text("Demo meals from the same kitchen, delivered together. Dietary preferences aren’t applied to these fixtures.")
                .font(.system(size: 12)).foregroundStyle(CampPalette.muted)
            ForEach(DemoLunch.make().options) { option in
                Button {
                    store.join(option)
                    choosingMeal = false
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: option.symbol).foregroundStyle(CampPalette.green).frame(width: 28)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(option.name).font(.system(size: 14, weight: .semibold))
                            Text(option.detail).font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                        }
                        Spacer()
                        Text(LunchStyle.money(option.priceCents)).font(.system(size: 13, weight: .semibold))
                    }.padding(17).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 13))
                }.buttonStyle(.plain)
            }
            Text("Selecting a meal joins the local demo group. No checkout takes place.")
                .font(.system(size: 11)).foregroundStyle(CampPalette.muted)
        }.padding(26).frame(maxWidth: 480).foregroundStyle(CampPalette.ink).background(.white)
        #if os(macOS)
        .frame(width: 450)
        #endif
    }
}
