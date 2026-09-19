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
