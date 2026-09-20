import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

struct RampEmployee: Decodable, Identifiable { let id: String; let name: String }
struct RampCardReference: Decodable, Identifiable { let id: String; let lastFour: String }
struct RampFundSummary: Decodable, Identifiable {
    let id: String; let name: String; let state: String
    let amountCents: Int; let currency: String; let cards: [RampCardReference]
}
struct RampSnapshot: Decodable {
    let environment: String; let company: String; let companyID: String
    let groupCapCents: Int; let users: [RampEmployee]; let funds: [RampFundSummary]
    let attempts: Int?
}
struct RampAllocation: Decodable { let requestID: String; let fund: RampFundSummary }
/// One live Ramp spending limit. `perOrderCents` is what a single order may cost: what is left in the current
/// interval, or the per-transaction ceiling when Ramp holds a smaller one.
struct RampLimit: Decodable, Identifiable {
    let id: String; let name: String; let state: String; let interval: String
    let limitCents: Int; let spentCents: Int; let remainingCents: Int
    let perOrderCents: Int; let transactionLimitCents: Int; let resetsAt: String; let currency: String
}
struct RampOverage: Decodable, Identifiable {
    let id: String; let userID: String; let limitID: String; let limitName: String
    let requester: String; let baselineCents: Int; let requestedCents: Int
    let reason: String; let state: String; let decidedBy: String
}
/// `GET /v1/ramp/limits/{employee}`: every active limit, the binding one, and the overage requests filed against it.
struct RampSpendLimits: Decodable {
    let userID: String; let limits: [RampLimit]; let limit: RampLimit?
    let perOrderCents: Int?; let overages: [RampOverage]; let pendingOverages: Int
}
private struct RampPending: Codable {
    let requestID: String; let userID: String; let amountCents: Int; let backend: String
}

@MainActor
final class CampRampModel: ObservableObject {
    @Published var snapshot: RampSnapshot?
    @Published var allocation: RampAllocation?
    @Published var busy = false
    @Published var error: String?
    @Published var ownerID = ""
    @Published var amountCents = 6000
    @Published private var pending: RampPending?
    private let pendingKey = "camp.ramp.pending-allocation.v1"
    private var connectedBackend: String?
    private var connectionRevision = 0
    var hasPending: Bool { pending != nil }
    var pendingAmount: Int? { pending?.amountCents }
    var requestID: String? { pending?.requestID }

    init() {
        if let data = UserDefaults.standard.data(forKey: pendingKey) {
            pending = try? JSONDecoder().decode(RampPending.self, from: data)
        }
    }

    /// The Ramp bridge is part of the recommender service now (`/v1/ramp`), so it shares its URL and token.
    private func client(_ url: String, token: String?) throws -> (RecommendationClient, String) {
        let client = try RecommendationClient(urlString: url, token: token)
        return (client, client.base.absoluteString)
    }

    func connect(_ backend: String, token: String?) async {
        guard !busy else { return }
        busy = true; error = nil; snapshot = nil; connectedBackend = nil
        connectionRevision += 1
        let revision = connectionRevision
        defer { busy = false }
        do {
            let (client, base) = try client(backend, token: token)
            let result: RampSnapshot = try await client.ramp("")
            guard result.environment == "sandbox" else { throw URLError(.badServerResponse) }
            guard revision == connectionRevision else { return }
            snapshot = result; connectedBackend = base
        } catch { self.error = "\(error.localizedDescription) Start the camp backend (cd backend && uv run camp serve) if it isn’t running." }
    }

    func prepare(_ backend: String, token: String?) async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false }
        do {
            let (client, base) = try client(backend, token: token)
            if pending == nil {
                guard let snapshot, connectedBackend == base,
                      snapshot.users.contains(where: { $0.id == ownerID }),
                      (100...snapshot.groupCapCents).contains(amountCents) else {
                    throw NSError(domain: "camp", code: 3, userInfo: [NSLocalizedDescriptionKey: "Connect to this backend and choose an active sandbox employee and valid amount first."])
                }
                let attempt = RampPending(requestID: UUID().uuidString, userID: ownerID, amountCents: amountCents, backend: base)
                let data = try JSONEncoder().encode(attempt)
                UserDefaults.standard.set(data, forKey: pendingKey)
                pending = attempt
            }
            guard let attempt = pending, attempt.backend == base else {
                throw NSError(domain: "camp", code: 4, userInfo: [NSLocalizedDescriptionKey: "Reconnect to the backend used for the pending allocation before reconciling it."])
            }
            let payload: [String: Any] = ["requestID": attempt.requestID, "userID": attempt.userID, "amountCents": attempt.amountCents]
            let body = try JSONSerialization.data(withJSONObject: payload)
            allocation = try await client.ramp("/allocations", body: body)
        } catch { self.error = error.localizedDescription }
    }

    func invalidateConnection() { connectionRevision += 1; snapshot = nil; connectedBackend = nil }

    func newAllocation() {
        guard allocation != nil, !busy else { return }
        UserDefaults.standard.removeObject(forKey: pendingKey)
        pending = nil; allocation = nil; error = nil
    }
}

struct CampRampView: View {
    @ObservedObject var store: CampSettingsStore
    @StateObject private var ramp = CampRampModel()
    /// nil until the stepper is touched: the ask then starts just above whatever Ramp currently allows.
    @State private var overageCents: Int?
    @State private var overageReason = ""
    var body: some View {
        CampCard("Ramp sandbox") {
            if let snapshot = ramp.snapshot {
                HStack { Label(snapshot.company, systemImage: "creditcard").font(.headline); Spacer(); CampBadge(text: "Sandbox connected", active: true) }
                Text("Server allocation cap: \(LunchStyle.money(snapshot.groupCapCents)). Office demo settings cannot raise this cap. Allocation attempts are recorded in the camp database (\(snapshot.attempts ?? 0) so far).").font(.caption).foregroundStyle(CampPalette.muted)
            } else {
                CampBadge(text: "Not connected")
            }
            Button(ramp.busy ? "Working…" : "Connect / refresh sandbox") {
                Task {
                    await ramp.connect(store.draft.connections.recommendationURL, token: store.draft.connections.recommendationToken)
                    if ramp.ownerID.isEmpty { ramp.ownerID = store.rampEmployeeID }
                    await store.refreshRampLimits()
                }
            }.buttonStyle(CampActionStyle()).disabled(ramp.busy)
            if let error = ramp.error { Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled) }
            if let snapshot = ramp.snapshot {
                Divider()
                CampField("Ramp employee") {
                    Picker("Ramp employee", selection: $ramp.ownerID) {
                        Text("Choose a sandbox employee").tag("")
                        ForEach(snapshot.users) { Text($0.name).tag($0.id) }
                    }.labelsHidden()
                }
                spendingLimit
            }
            if let snapshot = ramp.snapshot, !ramp.hasPending {
                Divider()
                Text("Prepare a sandbox lunch fund").font(.headline)
                CampField("All-in allocation") {
                    CampNumberStepper(label: "Sandbox allocation", value: $ramp.amountCents, range: 100...snapshot.groupCapCents, step: 100, money: true)
                }
                if let group = store.selectedGroup, let total = group.totalCents, total >= 100 {
                    Button("Use \(group.name) group total · \(LunchStyle.money(total))") { ramp.amountCents = min(total, snapshot.groupCapCents) }
                        .buttonStyle(.plain).font(.caption)
                }
                Text("Restaurant-only sandbox fund, capped per purchase and in total. Locks after 24 hours. No food order or charge.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
                Button("Create sandbox fund") { Task { await ramp.prepare(store.draft.connections.recommendationURL, token: store.draft.connections.recommendationToken) } }
                    .buttonStyle(CampActionStyle()).disabled(ramp.busy || ramp.ownerID.isEmpty || ramp.amountCents > snapshot.groupCapCents)
            }
            if ramp.hasPending {
                Divider()
                Text(ramp.allocation == nil ? "Allocation awaiting confirmation" : "Sandbox fund prepared").font(.headline)
                if let amount = ramp.pendingAmount { Text("Allocation: \(LunchStyle.money(amount))").font(.callout) }
                if let id = ramp.requestID { Text("Attempt: \(id)").font(.caption).textSelection(.enabled) }
                if let allocation = ramp.allocation {
                    fund(allocation.fund)
                    Button("Start another sandbox allocation") { ramp.newAllocation() }.buttonStyle(CampActionStyle(primary: false))
                    Text("Starting another allocation leaves this fund in Ramp. Manage or terminate sandbox funds in the Ramp dashboard.").font(.caption).foregroundStyle(CampPalette.muted)
                } else {
                    Text("Keep this attempt until its status is resolved. Reconciliation reuses the same ID; it will not blindly create a second fund.").font(.caption).foregroundStyle(CampPalette.muted)
                    Button("Reconcile allocation") { Task { await ramp.prepare(store.draft.connections.recommendationURL, token: store.draft.connections.recommendationToken) } }.buttonStyle(CampActionStyle()).disabled(ramp.busy)
                }
            }
            if let snapshot = ramp.snapshot, !snapshot.funds.isEmpty {
                DisclosureGroup("camp sandbox funds · \(snapshot.funds.count)") {
                    ForEach(snapshot.funds) { item in fund(item).padding(.vertical, 8) }
                }
            }
        }.onChange(of: store.draft.connections.recommendationURL) { _ in ramp.invalidateConnection() }
            .onChange(of: ramp.ownerID) { id in
                store.draft.connections.rampEmployeeReference = id
                overageCents = nil
                Task { await store.refreshRampLimits() }
            }
    }
    /// The employee's real Ramp limit — the number the rest of the app budgets against — and the way to ask for more.
    @ViewBuilder private var spendingLimit: some View {
        if store.rampEmployeeID.isEmpty {
            Text("Choose an employee to read their Ramp spending limit.").font(.caption).foregroundStyle(CampPalette.muted)
        } else if let limit = store.rampLimits?.limit {
            HStack { Text("Spending limit").font(.headline); Spacer(); CampBadge(text: "Live from Ramp", active: true) }
            Text("\(limit.name) · \(LunchStyle.money(limit.limitCents)) \(limit.interval.lowercased()) · \(LunchStyle.money(limit.remainingCents)) left")
                .font(.callout.weight(.semibold))
            Text("Today's orders are capped at \(LunchStyle.money(limit.perOrderCents)), which is what the budget bar and the recommender use. The office per-person cap only applies when Ramp holds no limit.")
                .font(.caption).foregroundStyle(CampPalette.muted)
            CampField("Ask for a higher ceiling") {
                CampNumberStepper(label: "Requested ceiling", value: overageBinding(limit), range: 100...100_000, step: 500, money: true)
            }
            CampTextField(title: "Why do you need more? (optional)", text: $overageReason)
            Button(store.rampOverageBusy ? "Working…" : "Request overage") {
                let amount = overageCents ?? defaultOverage(limit)
                Task {
                    await store.requestOverage(cents: amount, reason: overageReason)
                    overageReason = ""; overageCents = nil
                }
            }
            .buttonStyle(CampActionStyle())
            .disabled(store.rampOverageBusy || (overageCents ?? defaultOverage(limit)) <= limit.perOrderCents
                      || (store.rampLimits?.pendingOverages ?? 0) > 0)
            if (store.rampLimits?.pendingOverages ?? 0) > 0 {
                Text("A request is already waiting for a decision.").font(.caption).foregroundStyle(CampPalette.muted)
            }
        } else if store.rampLimitError == nil {
            Text("Ramp holds no active limit for this employee, so the office per-person cap applies.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }
        if let error = store.rampLimitError { Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled) }
        if let requests = store.rampLimits?.overages, !requests.isEmpty {
            Divider()
            Text("Overage requests").font(.headline)
            ForEach(requests) { request in overage(request) }
        }
    }

    private func defaultOverage(_ limit: RampLimit) -> Int { min(100_000, limit.perOrderCents + 1000) }
    private func overageBinding(_ limit: RampLimit) -> Binding<Int> {
        Binding(get: { overageCents ?? defaultOverage(limit) }, set: { overageCents = $0 })
    }

    private func overage(_ request: RampOverage) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("\(LunchStyle.money(request.baselineCents)) → \(LunchStyle.money(request.requestedCents))")
                    .font(.callout.weight(.semibold)).monospacedDigit()
                Spacer()
                CampBadge(text: request.state.capitalized, active: request.state == "approved")
            }
            Text(request.limitName + (request.requester.isEmpty ? "" : " · asked by \(request.requester)"))
                .font(.caption).foregroundStyle(CampPalette.muted)
            if !request.reason.isEmpty { Text(request.reason).font(.caption).foregroundStyle(CampPalette.muted) }
            if request.state == "pending", store.isDemoAdmin {
                HStack(spacing: 10) {
                    Button("Approve") { Task { await store.decideOverage(request.id, approve: true) } }
                        .buttonStyle(CampActionStyle()).disabled(store.rampOverageBusy)
                    Button("Deny") { Task { await store.decideOverage(request.id, approve: false) } }
                        .buttonStyle(CampActionStyle(primary: false)).disabled(store.rampOverageBusy)
                }
                Text("Approving raises the limit in Ramp for this interval. The ceiling it had before is kept on the request.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
            } else if request.state == "pending" {
                Text("Waiting for an approver.").font(.caption).foregroundStyle(CampPalette.muted)
            } else if !request.decidedBy.isEmpty {
                Text("\(request.state.capitalized) by \(request.decidedBy)").font(.caption).foregroundStyle(CampPalette.muted)
            }
        }.padding(.vertical, 6)
    }

    private func fund(_ value: RampFundSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(value.state) · \(value.currency) \(String(format: "%.2f", Double(value.amountCents) / 100))").font(.callout.weight(.semibold))
            Text("Fund: \(value.id)").font(.caption).textSelection(.enabled)
            if value.cards.isEmpty { Text("No linked card returned.").font(.caption) }
            ForEach(value.cards) { card in Text("Linked virtual card · •••• \(card.lastFour)").font(.caption) }
        }.foregroundStyle(CampPalette.muted)
    }
}
