import Foundation

/// App-owned persistence; the widget reads ActivityKit content instead of this file.
/// An injectable URL keeps file access out of the domain and allows isolated tests.
public struct SessionFile {
    private let url: URL
    private struct Envelope: Codable {
        let schemaVersion: Int
        let session: LunchSession
    }

    public init(url: URL) { self.url = url }

    public static func applicationStore(named name: String) -> SessionFile {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return SessionFile(url: base.appendingPathComponent(name).appendingPathComponent("session.json"))
    }

    public func load() throws -> LunchSession? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let envelope = try JSONDecoder().decode(Envelope.self, from: Data(contentsOf: url))
        guard envelope.schemaVersion == 1 else {
            throw CocoaError(.coderReadCorrupt)
        }
        return envelope.session
    }

    public func save(_ session: LunchSession) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(Envelope(schemaVersion: 1, session: session))
        try data.write(to: url, options: .atomic)
    }
}

// MARK: - Backend reachability
// This file is compiled into the app, the Mac app and the Live Activity extension, so everything the
// controllers need for the shared session lives here; the recommender client stays app-only.

/// Where the native apps may talk to the camp backend over plain HTTP: this Mac, or a machine on the same
/// private network (the phone reaching the Mac over Wi-Fi or a hotspot). Anything else needs HTTPS.
public enum CampBackendURL {
    public static let requirement = "Use http://127.0.0.1:8788 on this Mac, http://<mac-name>.local:8788 or a private LAN address from the phone, or an HTTPS URL."

    public static func parse(_ string: String, default fallback: String? = nil) -> URL? {
        var raw = string.trimmingCharacters(in: .whitespacesAndNewlines)
        if raw.isEmpty, let fallback { raw = fallback }
        guard let url = URL(string: raw), let host = url.host?.lowercased(),
              url.user == nil, url.password == nil, url.query == nil else { return nil }
        switch url.scheme {
        case "https": return url
        case "http": return isPrivateHost(host) ? url : nil
        default: return nil
        }
    }

    /// Loopback, mDNS names and RFC 1918 / link-local ranges. Hotspots hand out 172.20.10.x, home routers 192.168.x.
    public static func isPrivateHost(_ host: String) -> Bool {
        if host == "localhost" || host == "127.0.0.1" || host == "::1" || host.hasSuffix(".local") { return true }
        let parts = host.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4, parts.allSatisfy({ (0...255).contains($0) }) else { return false }
        switch (parts[0], parts[1]) {
        case (10, _), (192, 168), (169, 254): return true
        case (172, 16...31): return true
        default: return false
        }
    }

    static func applyToken(_ token: String?, to request: inout URLRequest) {
        if let token = token?.trimmingCharacters(in: .whitespacesAndNewlines), !token.isEmpty {
            request.setValue(token, forHTTPHeaderField: "X-Camp-Token")
        }
    }
}

// MARK: - Shared orders (Mac ↔ iPhone)

/// What one device publishes after a local transition: the whole session plus the group it came from, so the other
/// device can render the same card and Live Activity. `sessionId`/`revision` are duplicated at the top level for the
/// backend's compare-and-swap; the backend treats the rest as opaque. Several records can be active at once (a
/// coffee and a meal); `LunchSyncSnapshot.records` lists them all and `record` is the nearest one.
public struct LunchSyncRecord: Codable, Equatable, Sendable {
    public var sessionId: String
    public var revision: Int
    public var session: LunchSession
    public var group: DemoLunchGroup?
    public var device: String?
    public var updatedAt: String?

    public init(session: LunchSession, group: DemoLunchGroup?, device: String) {
        sessionId = session.id.uuidString; revision = session.revision
        self.session = session; self.group = group; self.device = device
    }
}

public struct LunchSyncSnapshot: Codable, Equatable, Sendable {
    public var seq: Int
    public var record: LunchSyncRecord?
    /// Every active order; absent from backends older than the orders generalisation.
    public var records: [LunchSyncRecord]?
    public init(seq: Int, record: LunchSyncRecord?, records: [LunchSyncRecord]? = nil) { self.seq = seq; self.record = record; self.records = records }
    /// All records, oldest backends included.
    public var all: [LunchSyncRecord] { records ?? (record.map { [$0] } ?? []) }
}

extension Array where Element == LunchSyncRecord {
    /// The order a single-card surface should show: the unfinished one that arrives soonest, else the latest touched.
    public var nearest: LunchSyncRecord? {
        let active = filter { !$0.session.isFinished }
        if let soonest = active.min(by: { $0.session.arrivesAt < $1.session.arrivesAt }) { return soonest }
        return self.max { ($0.updatedAt ?? "") < ($1.updatedAt ?? "") }
    }
}

/// Another device moved the order first; `snapshot` is what the backend has now.
public struct LunchSyncConflict: LocalizedError {
    public let snapshot: LunchSyncSnapshot
    public var errorDescription: String? { "Your order changed on another device." }
}


public struct LunchSyncClient: Sendable {
    public let base: URL
    public let token: String?
    public let device: String

    public init(urlString: String, token: String?, device: String) throws {
        guard let url = CampBackendURL.parse(urlString, default: "http://127.0.0.1:8788") else {
            throw NSError(domain: "camp", code: 10, userInfo: [NSLocalizedDescriptionKey: CampBackendURL.requirement])
        }
        base = url; self.token = token; self.device = device
    }

    private struct Publish: Encodable {
        let record: LunchSyncRecord
        let expectedSessionId: String?
        let expectedRevision: Int?
        let device: String
    }
    private struct ErrorBody: Decodable { let detail: String? }

    /// `since == nil` returns immediately; otherwise the backend holds the request until `seq` changes
    /// (up to `wait` seconds), so a change on the other device arrives within a round trip.
    public func fetch(since: Int?, wait: Int = 0) async throws -> LunchSyncSnapshot {
        var query = [String: String]()
        if let since { query["since"] = String(since); query["wait"] = String(wait) }
        let (data, http) = try await send("GET", "v1/lunch-session", query: query, timeout: TimeInterval(wait + 15))
        guard (200..<300).contains(http.statusCode) else { throw error(from: data, status: http.statusCode) }
        return try JSONDecoder().decode(LunchSyncSnapshot.self, from: data)
    }

    public func publish(_ record: LunchSyncRecord, expectedSessionId: String?, expectedRevision: Int?) async throws -> LunchSyncSnapshot {
        let body = try JSONEncoder().encode(Publish(record: record, expectedSessionId: expectedSessionId,
                                                    expectedRevision: expectedRevision, device: device))
        let (data, http) = try await send("PUT", "v1/lunch-session", body: body, timeout: 15)
        if http.statusCode == 409 { throw LunchSyncConflict(snapshot: try JSONDecoder().decode(LunchSyncSnapshot.self, from: data)) }
        guard (200..<300).contains(http.statusCode) else { throw error(from: data, status: http.statusCode) }
        return try JSONDecoder().decode(LunchSyncSnapshot.self, from: data)
    }

    /// Drops one order from the shared list (e.g. the user left the group).
    public func forget(sessionId: String) async throws -> LunchSyncSnapshot {
        let (data, http) = try await send("DELETE", "v1/lunch-session", query: ["sessionId": sessionId], timeout: 15)
        guard (200..<300).contains(http.statusCode) else { throw error(from: data, status: http.statusCode) }
        return try JSONDecoder().decode(LunchSyncSnapshot.self, from: data)
    }

    private func send(_ method: String, _ path: String, body: Data? = nil, query: [String: String] = [:],
                      timeout: TimeInterval) async throws -> (Data, HTTPURLResponse) {
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = timeout
        request.setValue("camp-native", forHTTPHeaderField: "X-Camp-Client")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        CampBackendURL.applyToken(token, to: &request)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        return (data, http)
    }

    private func error(from data: Data, status: Int) -> Error {
        let message = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail
            ?? (status == 401 ? "The backend rejected the sync token." : "The backend returned \(status).")
        return NSError(domain: "camp", code: 12, userInfo: [NSLocalizedDescriptionKey: message])
    }
}

/// Runs one long-poll loop per app and pushes local changes. Platform models plug in `apply`, which receives
/// every record the backend has whenever the shared list changes (including echoes of this device's own writes,
/// which the models ignore by revision), and `applyAll` for the whole list. Main-actor because the models it drives are.
@MainActor
public final class LunchSyncCoordinator {
    public private(set) var client: LunchSyncClient?
    public var apply: ((LunchSyncRecord) -> Void)?
    /// The complete active list after every change; lets a model drop orders that were forgotten elsewhere.
    public var applyAll: (([LunchSyncRecord]) -> Void)?
    /// Human-readable state for the Connections page: "Live · iPhone", an error, or nil when unconfigured.
    public var onStatus: ((String?) -> Void)?
    private var loop: Task<Void, Never>?
    private var seq: Int?
    private let device: String

    public init(device: String) { self.device = device }

    public var isConfigured: Bool { client != nil }

    /// Reconfigures from the saved connection settings; an unusable URL stops syncing rather than failing loudly.
    public func configure(urlString: String, token: String?) {
        let next = try? LunchSyncClient(urlString: urlString, token: token, device: device)
        guard next?.base != client?.base || next?.token != client?.token else { return }
        stop()
        client = next
        if client == nil { onStatus?(nil) }
    }

    public func start() {
        guard loop == nil, let client else { return }
        loop = Task { [weak self] in
            var failures = 0
            while !Task.isCancelled {
                do {
                    let snapshot = try await client.fetch(since: self?.seq, wait: 25)
                    guard let self, !Task.isCancelled else { return }
                    failures = 0
                    self.onStatus?("Live · \(client.base.host ?? "backend")")
                    if snapshot.seq != self.seq {
                        self.seq = snapshot.seq
                        self.deliver(snapshot)
                    }
                } catch is CancellationError {
                    return
                } catch {
                    guard let self, !Task.isCancelled else { return }
                    failures += 1
                    self.onStatus?("Reconnecting · \(error.localizedDescription)")
                    try? await Task.sleep(nanoseconds: UInt64(min(10, Double(failures)) * 1_000_000_000))
                }
            }
        }
    }

    public func stop() { loop?.cancel(); loop = nil }

    private func deliver(_ snapshot: LunchSyncSnapshot) {
        let records = snapshot.all
        applyAll?(records)
        for record in records { apply?(record) }
    }

    /// Removes an order from the shared list; the loop's `since` skips the echo.
    public func forget(sessionId: String) async {
        guard let client else { return }
        if let snapshot = try? await client.forget(sessionId: sessionId) { seq = snapshot.seq; applyAll?(snapshot.all) }
    }

    /// Publishes a local change. On a conflict the backend's record is applied locally and the error returned,
    /// so the caller can show it; the loop's `since` skips ahead so the echo isn't applied twice.
    public func publish(_ session: LunchSession, group: DemoLunchGroup?, previous: LunchSession?) async -> Error? {
        guard let client else { return nil }
        let record = LunchSyncRecord(session: session, group: group, device: device)
        // A transition must build on the revision this device last saw; a brand-new lunch simply replaces
        // whatever is there, so starting one never fails because the other device was ahead.
        let previous = previous?.id == session.id ? previous : nil
        do {
            let snapshot = try await client.publish(record, expectedSessionId: previous?.id.uuidString,
                                                    expectedRevision: previous?.revision)
            seq = snapshot.seq
            return nil
        } catch let conflict as LunchSyncConflict {
            seq = conflict.snapshot.seq
            deliver(conflict.snapshot)
            return conflict
        } catch {
            onStatus?("Offline · \(error.localizedDescription)")
            return error
        }
    }
}
