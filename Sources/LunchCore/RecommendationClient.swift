import Foundation

/// Foundation-only client for the Python recommender (`uv run uvicorn camp.api:app --port 8788`).
public struct RecommendationClient {
    public let base: URL
    public var session: URLSession = .shared

    public init(urlString: String) throws {
        let raw = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: raw.isEmpty ? "http://127.0.0.1:8788" : raw), let host = url.host,
              url.user == nil, url.password == nil, url.query == nil,
              url.scheme == "https" || (url.scheme == "http" && ["localhost", "127.0.0.1"].contains(host)) else {
            throw NSError(domain: "camp", code: 10, userInfo: [NSLocalizedDescriptionKey: "Use http://127.0.0.1:8788 for the local recommender, or an HTTPS URL."])
        }
        base = url
    }

    private struct ErrorBody: Decodable { let detail: String? }

    private func send<T: Decodable>(_ path: String, body: Data? = nil, query: [String: String] = [:]) async throws -> T {
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 60
        request.httpMethod = body == nil ? "GET" : "POST"
        request.httpBody = body
        request.setValue("camp-native", forHTTPHeaderField: "X-Camp-Client")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let message = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail ?? "The recommender returned an error."
            throw NSError(domain: "camp", code: 11, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    public func health() async throws -> JSONValue { try await send("v1/health") }
    public func mealOffer(_ context: MealContext, force: Bool = false) async throws -> MealOffer {
        try await send("v1/meal-offers", body: JSONEncoder().encode(context), query: force ? ["force": "true"] : [:])
    }
    /// Reports the card's lifecycle so the pick becomes an order and feedback (§6.1 taps).
    public func lunchEvent(offerId: String, optionId: String?, event: String, rating: Int? = nil) async throws -> JSONValue {
        var payload: [String: Any] = ["offerId": offerId, "event": event]
        if let optionId { payload["optionId"] = optionId }
        if let rating { payload["rating"] = rating }
        return try await send("v1/lunch-events", body: JSONSerialization.data(withJSONObject: payload))
    }
    public func debugSnapshot() async throws -> JSONValue { try await send("v1/debug/snapshot") }
    public func debugUser(_ id: String) async throws -> JSONValue { try await send("v1/debug/user/\(id)") }
    public func debugEvents() async throws -> JSONValue { try await send("v1/debug/events") }
    public func debugFeedback(userId: String, text: String, confirm: Bool = false) async throws -> JSONValue {
        let payload: [String: Any] = ["user_id": userId, "text": text, "confirm_constraint": confirm]
        return try await send("v1/debug/feedback", body: JSONSerialization.data(withJSONObject: payload))
    }
}
