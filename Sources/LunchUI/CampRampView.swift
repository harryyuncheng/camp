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
}
struct RampAllocation: Decodable { let requestID: String; let fund: RampFundSummary }
private struct RampErrorBody: Decodable { let error: String }
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

    private func base(_ input: String) throws -> URL {
        let raw = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: raw.isEmpty ? "http://127.0.0.1:8787" : raw),
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.scheme == "http", ["localhost", "127.0.0.1"].contains(url.host ?? ""),
              url.path.isEmpty || url.path == "/" else {
            throw NSError(domain: "camp", code: 1, userInfo: [NSLocalizedDescriptionKey: "Use http://127.0.0.1:8787 for this local sandbox bridge. Remote deployment needs camp authentication first."])
        }
        return url
    }

    private func request<T: Decodable>(_ backend: URL, path: String, body: Data? = nil) async throws -> T {
        var request = URLRequest(url: backend.appendingPathComponent(path))
        request.timeoutInterval = 90
        request.httpMethod = body == nil ? "GET" : "POST"
        request.httpBody = body
        request.setValue("camp-native", forHTTPHeaderField: "X-Camp-Client")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let message = (try? JSONDecoder().decode(RampErrorBody.self, from: data))?.error ?? "The camp backend could not complete this request."
            throw NSError(domain: "camp", code: 2, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func connect(_ backend: String) async {
        guard !busy else { return }
        busy = true; error = nil; snapshot = nil; connectedBackend = nil
        connectionRevision += 1
        let revision = connectionRevision
        defer { busy = false }
        do {
            let url = try base(backend)
            let result: RampSnapshot = try await request(url, path: "v1/ramp")
            guard result.environment == "sandbox" else { throw URLError(.badServerResponse) }
            guard revision == connectionRevision else { return }
            snapshot = result; connectedBackend = url.absoluteString
        } catch { self.error = "\(error.localizedDescription) Start the local camp backend if it isn’t running." }
    }

    func prepare(_ backend: String) async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false }
        do {
            let url = try base(backend)
            if pending == nil {
                guard let snapshot, connectedBackend == url.absoluteString,
                      snapshot.users.contains(where: { $0.id == ownerID }),
                      (100...snapshot.groupCapCents).contains(amountCents) else {
                    throw NSError(domain: "camp", code: 3, userInfo: [NSLocalizedDescriptionKey: "Connect to this backend and choose an active sandbox employee and valid amount first."])
                }
                let attempt = RampPending(requestID: UUID().uuidString, userID: ownerID, amountCents: amountCents, backend: url.absoluteString)
                let data = try JSONEncoder().encode(attempt)
                UserDefaults.standard.set(data, forKey: pendingKey)
                pending = attempt
            }
            guard let attempt = pending, attempt.backend == url.absoluteString else {
                throw NSError(domain: "camp", code: 4, userInfo: [NSLocalizedDescriptionKey: "Reconnect to the backend used for the pending allocation before reconciling it."])
            }
            let payload: [String: Any] = ["requestID": attempt.requestID, "userID": attempt.userID, "amountCents": attempt.amountCents]
            let body = try JSONSerialization.data(withJSONObject: payload)
            allocation = try await request(url, path: "v1/ramp/allocations", body: body)
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
    var body: some View {
        CampCard("Ramp sandbox") {
            if let snapshot = ramp.snapshot {
                HStack { Label(snapshot.company, systemImage: "creditcard").font(.headline); Spacer(); CampBadge(text: "Sandbox connected", active: true) }
                Text("Server allocation cap: \(LunchStyle.money(snapshot.groupCapCents)). Office demo settings cannot raise this cap.").font(.caption).foregroundStyle(CampPalette.muted)
            } else {
                CampBadge(text: "Not connected")
            }
            Button(ramp.busy ? "Working…" : "Connect / refresh sandbox") {
                Task { await ramp.connect(store.draft.connections.backendURL) }
            }.buttonStyle(CampActionStyle()).disabled(ramp.busy)
            if let error = ramp.error { Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled) }
            if let snapshot = ramp.snapshot, !ramp.hasPending {
                Divider()
                Text("Prepare a sandbox lunch fund").font(.headline)
                Picker("Company payer", selection: $ramp.ownerID) {
                    Text("Choose a sandbox employee").tag("")
                    ForEach(snapshot.users) { Text($0.name).tag($0.id) }
                }
                CampField("All-in allocation") {
                    CampNumberStepper(label: "Sandbox allocation", value: $ramp.amountCents, range: 100...snapshot.groupCapCents, step: 100, money: true)
                }
                Button("Use demo group total · \(LunchStyle.money(store.group.totalCents))") { ramp.amountCents = store.group.totalCents }
                    .buttonStyle(.plain).font(.caption)
                Text("Restaurant-only sandbox fund, capped per purchase and in total. Locks after 24 hours. No food order or charge.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
                Button("Create sandbox fund") { Task { await ramp.prepare(store.draft.connections.backendURL) } }
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
                    Button("Reconcile allocation") { Task { await ramp.prepare(store.draft.connections.backendURL) } }.buttonStyle(CampActionStyle()).disabled(ramp.busy)
                }
            }
            if let snapshot = ramp.snapshot, !snapshot.funds.isEmpty {
                DisclosureGroup("camp sandbox funds · \(snapshot.funds.count)") {
                    ForEach(snapshot.funds) { item in fund(item).padding(.vertical, 8) }
                }
            }
        }.onChange(of: store.draft.connections.backendURL) { _ in ramp.invalidateConnection() }
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
