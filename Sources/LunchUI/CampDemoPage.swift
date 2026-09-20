import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

/// Demo page: everything added for demoing and testing the recommender and the service bridges — the
/// recommendation service, Ramp sandbox, ordering provider placeholder, then the live offer, the backend's
/// filters, scores, office batch and feedback loop. Lives in its own sidebar tab; not employee-facing.
struct CampDemoPage: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    @State private var snapshot: JSONValue?
    @State private var user: JSONValue?
    @State private var feedbackText = ""
    @State private var feedbackResult: JSONValue?
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        VStack(spacing: 20) {
            CampRecommendationView(store: store)
            if let offer = store.latestOffer { liveOffer(offer) }
            CampCard("Recommender debug", subtitle: "GET /v1/health and /v1/debug/snapshot") {
                HStack {
                    Button(busy ? "Loading…" : "Refresh") { Task { await refresh() } }.buttonStyle(CampActionStyle()).disabled(busy)
                    Button("Re-run batch") { Task { await store.requestOffer(force: true); await refresh() } }.buttonStyle(CampActionStyle(primary: false)).disabled(busy || store.recommenderBusy)
                    Spacer()
                    if let h = snapshot?["health"] { CampBadge(text: "\(h["classifier"]?.string ?? "?") · \(h["providers"]?.array?.compactMap { $0.string }.joined(separator: "+") ?? "")", active: true) }
                }
                if let error { Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled) }
                if let seeded = snapshot?["seeded"]?.array, !seeded.isEmpty {
                    ForEach(seeded.indices, id: \.self) { Text(seeded[$0].scalarText).font(.caption).foregroundStyle(CampPalette.muted) }
                }
            }
            if let batch = snapshot?["batch"], batch != .null { batchCard(batch) }
            if let offer = store.latestOffer { offerCard(offer) }
            if let user { userCard(user) }
            feedbackCard
            if let snapshot { CampCard("Raw snapshot") { JSONTree(value: snapshot, depth: 0) } }
            CampRampView(store: store)
            CampCard("Ordering", subtitle: "Placeholder · no ordering provider is integrated yet.") {
                Picker("Provider", selection: $store.draft.connections.orderingProvider) {
                    Text("Mock provider").tag("Mock provider")
                    Text("DoorDash · planned").tag("DoorDash")
                }
                CampBadge(text: store.draft.connections.orderingProvider == "Mock provider" ? "Demo only" : "Not connected")
                Text("No orders are submitted.").font(.callout).foregroundStyle(CampPalette.muted)
            }
            CampCard("Ramp bridge URL", subtitle: "The local Python server that holds the Ramp sandbox credentials.") {
                CampTextField(title: "http://127.0.0.1:8787", text: $store.draft.connections.backendURL)
                Text("Leave blank to use http://127.0.0.1:8787.").font(.caption).foregroundStyle(CampPalette.muted)
            }
        }.task { await refresh() }
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

    private func refresh() async {
        busy = true; error = nil
        defer { busy = false }
        do {
            let client = try store.client()
            snapshot = try await client.debugSnapshot()
            if let id = store.recommenderUserID { user = try await client.debugUser(id) }
        } catch { self.error = error.localizedDescription }
    }

    private func batchCard(_ b: JSONValue) -> some View {
        CampCard("Office batch", subtitle: "solver \(b["solver"]?.string ?? "?") · objective \(b["objective"]?.scalarText ?? "?") · company cost \(LunchStyle.money(b["totalCostCents"]?.int ?? 0)) · \(b["orders"]?.int ?? 0) orders") {
            ForEach((b["restaurants"]?.array ?? []).indices, id: \.self) { i in
                let r = b["restaurants"]!.array![i]
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(r["name"]?.string ?? "?").font(.system(size: 13, weight: .semibold))
                        Text((r["users"]?.array ?? []).compactMap { $0.string }.joined(separator: ", ")).font(.system(size: 10)).foregroundStyle(CampPalette.muted)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 3) {
                        Text("\(r["headcount"]?.int ?? 0) people").font(.system(size: 12, weight: .medium))
                        Text("fee \(LunchStyle.money(r["deliveryFeeCents"]?.int ?? 0)) → \(LunchStyle.money(r["feeShareCents"]?.int ?? 0)) each").font(.system(size: 10)).foregroundStyle(CampPalette.muted)
                    }
                }.padding(10).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 10))
            }
            if let reg = b["regret"] {
                Text("Regret mean \(reg["mean"]?.scalarText ?? "-") · max \(reg["max"]?.scalarText ?? "-") · above δ: \(reg["above_delta"]?.int ?? 0)").font(.caption)
            }
            let so = (b["suggestOnly"]?.array ?? []).compactMap { $0.string }
            let un = (b["unassigned"]?.array ?? []).compactMap { $0.string }
            if !so.isEmpty { Text("Suggest-only: \(so.joined(separator: ", "))").font(.caption).foregroundStyle(CampPalette.muted) }
            if !un.isEmpty { Text("Unassigned: \(un.joined(separator: ", "))").font(.caption).foregroundStyle(.red) }
        }
    }

    private func offerCard(_ offer: MealOffer) -> some View {
        CampCard("Last offer for you", subtitle: "\(offer.offerId) · \(offer.location) · group \(offer.groupId ?? "none")") {
            ForEach(offer.options) { o in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("\(o.name) · \(o.restaurant)").font(.system(size: 13, weight: .semibold))
                        if o.novel { CampBadge(text: "novel") }
                        Spacer()
                        Text("score \(String(format: "%.3f", o.score))").font(.system(size: 11)).monospacedDigit()
                    }
                    Text(o.breakdown.sorted { $0.key < $1.key }.map { "\($0.key) \(String(format: "%+.2f", $0.value))" }.joined(separator: "   "))
                        .font(.system(size: 10, design: .monospaced)).foregroundStyle(CampPalette.muted)
                    Text("item \(LunchStyle.money(o.itemPriceCents)) · all-in \(LunchStyle.money(o.priceCents)) · alone \(LunchStyle.money(o.baselineCents)) · \(o.pricing)")
                        .font(.system(size: 10)).foregroundStyle(CampPalette.muted)
                }.padding(10).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private func userCard(_ u: JSONValue) -> some View {
        CampCard("Your profile on the backend", subtitle: "\(u["feasibleCount"]?.int ?? 0) items pass the hard filters") {
            if let learned = u["learned"]?.object {
                ForEach(learned.keys.sorted(), id: \.self) { k in
                    HStack(alignment: .top) {
                        Text(k).font(.system(size: 11, weight: .medium)).frame(width: 90, alignment: .leading)
                        Text((learned[k]?.array ?? []).map { $0.scalarText }.joined(separator: " · ")).font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                    }
                }
            }
            if let rej = u["filterRejections"]?.object, !rej.isEmpty {
                Divider()
                Text("Filter rejections").font(.system(size: 12, weight: .medium))
                Text(rej.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value.scalarText)" }.joined(separator: "   ")).font(.system(size: 10, design: .monospaced)).foregroundStyle(CampPalette.muted)
            }
            if let top = u["topCandidates"]?.array, !top.isEmpty {
                Divider()
                Text("Top candidates (global, before batching)").font(.system(size: 12, weight: .medium))
                ForEach(top.indices, id: \.self) { i in
                    let c = top[i]
                    HStack { Text("\(c["item"]?.string ?? "") · \(c["restaurant"]?.string ?? "")").font(.system(size: 11)); Spacer(); Text(c["score"]?.scalarText ?? "").font(.system(size: 11)).monospacedDigit() }
                }
            }
        }
    }

    private var feedbackCard: some View {
        CampCard("Feedback console", subtitle: "Natural language → Jev/mock classification → structured events → profile updates") {
            HStack {
                CampTextField(title: "e.g. \"Great but too salty\" or \"I'm allergic to shellfish\"", text: $feedbackText)
                Button("Send") { Task { await sendFeedback() } }.buttonStyle(CampActionStyle()).disabled(feedbackText.isEmpty || store.recommenderUserID == nil)
            }
            if store.recommenderUserID == nil { Text("Request a meal offer first so the backend has a profile for you.").font(.caption).foregroundStyle(CampPalette.muted) }
            if let r = feedbackResult {
                ForEach((r["events"]?.array ?? []).indices, id: \.self) { i in
                    let e = r["events"]!.array![i]
                    HStack(alignment: .top) {
                        CampBadge(text: "\(e["type"]?.string ?? "?") / \(e["scope"]?.string ?? "")", active: true)
                        Text("conf \(e["confidence"]?.scalarText ?? "") · \(e["payload"].map { JSONTree.inline($0) } ?? "")").font(.system(size: 10, design: .monospaced))
                        if e["needsConfirmation"] == .bool(true) { CampBadge(text: "needs confirmation") }
                    }
                }
                if let clarify = r["clarify"]?.string { Text("Backend asks: \(clarify)").font(.callout) }
                ForEach((r["profileUpdates"]?.array ?? []).indices, id: \.self) { i in
                    Text("→ \(r["profileUpdates"]!.array![i].scalarText)").font(.system(size: 11)).foregroundStyle(CampPalette.green)
                }
            }
        }
    }

    private func sendFeedback() async {
        guard let id = store.recommenderUserID else { return }
        do {
            feedbackResult = try await store.client().debugFeedback(userId: id, text: feedbackText)
            feedbackText = ""
            await refresh()
        } catch { self.error = error.localizedDescription }
    }
}

/// Collapsible JSON tree for arbitrary debug payloads.
struct JSONTree: View {
    let value: JSONValue
    let depth: Int
    @State private var open = false
    var body: some View {
        switch value {
        case .object(let o):
            DisclosureGroup(isExpanded: $open) {
                ForEach(o.keys.sorted(), id: \.self) { k in
                    HStack(alignment: .top, spacing: 6) {
                        Text(k).font(.system(size: 11, design: .monospaced)).foregroundStyle(CampPalette.green)
                        JSONTree(value: o[k]!, depth: depth + 1)
                    }
                }
            } label: { Text("{\(o.count)}").font(.system(size: 11, design: .monospaced)) }
        case .array(let a):
            DisclosureGroup(isExpanded: $open) {
                ForEach(a.indices, id: \.self) { i in JSONTree(value: a[i], depth: depth + 1) }
            } label: { Text("[\(a.count)]").font(.system(size: 11, design: .monospaced)) }
        default:
            Text(value.scalarText).font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
        }
    }
    static func inline(_ v: JSONValue) -> String {
        switch v {
        case .object(let o): return "{" + o.keys.sorted().map { "\($0): \(inline(o[$0]!))" }.joined(separator: ", ") + "}"
        case .array(let a): return "[" + a.map(inline).joined(separator: ", ") + "]"
        default: return v.scalarText
        }
    }
}
