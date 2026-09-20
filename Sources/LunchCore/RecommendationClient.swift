import Foundation

/// Foundation-only client for the Python recommender (`uv run camp serve`).
public struct RecommendationClient {
    public let base: URL
    public var session: URLSession = .shared

    public var token: String?

    public init(urlString: String, token: String? = nil) throws {
        guard let url = CampBackendURL.parse(urlString, default: "http://127.0.0.1:8788") else {
            throw NSError(domain: "camp", code: 10, userInfo: [NSLocalizedDescriptionKey: CampBackendURL.requirement])
        }
        base = url
        self.token = token
    }

    private struct ErrorBody: Decodable { let detail: String? }

    private func send<T: Decodable>(_ path: String, method: String? = nil, body: Data? = nil, query: [String: String] = [:],
                                    decoder: JSONDecoder = JSONDecoder()) async throws -> T {
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 60
        request.httpMethod = method ?? (body == nil ? "GET" : "POST")
        request.httpBody = body
        request.setValue("camp-native", forHTTPHeaderField: "X-Camp-Client")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        CampBackendURL.applyToken(token, to: &request)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let message = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail ?? "The recommender returned an error."
            throw NSError(domain: "camp", code: 11, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return try decoder.decode(T.self, from: data)
    }

    private func json(_ object: [String: Any]) throws -> Data { try JSONSerialization.data(withJSONObject: object) }

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

    // MARK: profile, groups, ledger (all rows in the backend database)

    /// Saves the personal preferences server-side; returns the user id the row lives under.
    public func putProfile(_ context: MealContext) async throws -> ProfileSyncResponse {
        try await send("v1/profile", method: "PUT", body: JSONEncoder().encode(context))
    }
    public func groups(office: OfficeRef, userId: String?) async throws -> LunchGroupsResponse {
        var query = ["officeId": office.id, "officeName": office.name, "deliveryStart": String(office.deliveryStart),
                     "latitude": String(office.latitude), "longitude": String(office.longitude)]
        if let userId { query["userId"] = userId }
        return try await send("v1/groups", query: query)
    }
    public func restaurants(limit: Int = 12, category: OrderCategory? = nil) async throws -> [LunchRestaurant] {
        var query = ["limit": String(limit)]
        if let category { query["category"] = category.rawValue }
        return try await send("v1/restaurants", query: query)
    }
    /// Full menu with the public rating; `userId` gets personal top picks, `groupId` prices with that group's delivery share.
    public func menu(restaurantId: String, userId: String?, groupId: String?) async throws -> LunchMenu {
        var query: [String: String] = [:]
        if let userId { query["userId"] = userId }
        if let groupId { query["groupId"] = groupId }
        return try await send("v1/restaurants/\(restaurantId)/menu", query: query)
    }
    /// "I want tacos": the backend's OpenAI model turns the sentence into search terms and answers from the catalog.
    public func craving(text: String, category: OrderCategory?, userId: String?, limit: Int = 3) async throws -> LunchCravingResult {
        var body: [String: Any] = ["text": text, "limit": limit]
        if let category { body["category"] = category.rawValue }
        if let userId { body["userId"] = userId }
        return try await send("v1/craving", body: json(body))
    }
    public func createGroup(office: OfficeRef, restaurantId: String, deliveryMinutes: Int, optionId: String,
                            userId: String?, displayName: String, category: OrderCategory? = nil) async throws -> DemoLunchGroup {
        var body: [String: Any] = ["office": try officeJSON(office), "restaurantId": restaurantId, "deliveryMinutes": deliveryMinutes,
                                   "optionId": optionId, "displayName": displayName]
        if let userId { body["userId"] = userId }
        if let category { body["category"] = category.rawValue }
        return try await send("v1/groups", body: json(body))
    }

    // MARK: standing orders
    public func schedules(userId: String) async throws -> [LunchSchedule] { try await send("v1/schedules/\(userId)") }
    public func addSchedule(office: OfficeRef, userId: String?, displayName: String, category: OrderCategory, label: String,
                            restaurantId: String?, optionId: String?, timeMinutes: Int, weekdays: [Int]) async throws -> LunchSchedule {
        var body: [String: Any] = ["office": try officeJSON(office), "displayName": displayName, "category": category.rawValue, "label": label,
                                   "timeMinutes": timeMinutes, "weekdays": weekdays]
        if let userId { body["userId"] = userId }
        if let restaurantId { body["restaurantId"] = restaurantId }
        if let optionId { body["optionId"] = optionId }
        return try await send("v1/schedules", body: json(body))
    }
    public func setScheduleEvent(_ scheduleId: String, eventId: String?) async throws -> LunchSchedule {
        try await send("v1/schedules/\(scheduleId)/event", method: "PUT", body: json(["calendarEventId": eventId as Any]))
    }
    public func removeSchedule(_ scheduleId: String, userId: String) async throws -> LunchSchedule {
        try await send("v1/schedules/\(scheduleId)", method: "DELETE", query: ["userId": userId])
    }
    public func joinGroup(_ groupId: String, office: OfficeRef, optionId: String, userId: String?, displayName: String) async throws -> DemoLunchGroup {
        var body: [String: Any] = ["office": try officeJSON(office), "optionId": optionId, "displayName": displayName]
        if let userId { body["userId"] = userId }
        return try await send("v1/groups/\(groupId)/join", body: json(body))
    }
    public func leaveGroup(_ groupId: String, userId: String) async throws -> DemoLunchGroup {
        try await send("v1/groups/\(groupId)/members/\(userId)", method: "DELETE")
    }
    public func ledger(userId: String, officeName: String) async throws -> LunchLedgerResponse {
        try await send("v1/ledger/\(userId)", query: ["officeName": officeName], decoder: LunchLedgerResponse.decoder)
    }
    private func officeJSON(_ office: OfficeRef) throws -> Any { try JSONSerialization.jsonObject(with: JSONEncoder().encode(office)) }

    // MARK: Ramp sandbox (same service, /v1/ramp)
    public func ramp<T: Decodable>(_ path: String, body: Data? = nil) async throws -> T { try await send("v1/ramp" + path, body: body) }

    public func debugSnapshot() async throws -> JSONValue { try await send("v1/debug/snapshot") }
    public func debugUser(_ id: String) async throws -> JSONValue { try await send("v1/debug/user/\(id)") }
    public func debugEvents() async throws -> JSONValue { try await send("v1/debug/events") }
    public func debugFeedback(userId: String, text: String, confirm: Bool = false) async throws -> JSONValue {
        let payload: [String: Any] = ["user_id": userId, "text": text, "confirm_constraint": confirm]
        return try await send("v1/debug/feedback", body: JSONSerialization.data(withJSONObject: payload))
    }
}

