import Foundation

/// Wire contracts shared with the Python recommender (`backend/src/camp/contracts.py`).
/// camelCase keys; money in integer cents; times as ISO 8601 with offset.
public struct OfficeRef: Codable, Equatable {
    public var id: String
    public var name: String
    public var latitude: Double
    public var longitude: Double
    public var radiusMeters: Int
    public var cutoff: Int
    public var deliveryStart: Int
    public var deliveryEnd: Int
    public init(policy: OfficePolicy) {
        id = policy.id; name = policy.name; latitude = policy.latitude; longitude = policy.longitude
        radiusMeters = policy.radiusMeters; cutoff = policy.cutoff; deliveryStart = policy.deliveryStart; deliveryEnd = policy.deliveryEnd
    }
}

public struct MealContext: Codable, Equatable {
    public var contextVersion = 1
    public var userId: String?
    public var displayName: String
    public var office: OfficeRef
    public var presence: String
    public var lunchStart: Int
    public var lunchEnd: Int
    public var lunchDuration: Int
    public var dietaryStyle: String
    public var allergies: [String]
    public var dislikes: [String]
    public var budgetCents: Int
    public var meal = "lunch"
    public var tempC = 18.0
    public var raining = false
    public var nowMinutes: Int?

    /// Builds the context from local configuration. Raw coordinates for the office are policy, not the user's location.
    /// `budgetCentsOverride` is the employee's live Ramp limit when one is known: Ramp, not the office setting, is
    /// what the backend should enforce.
    public init(configuration c: CampConfiguration, userId: String?, budgetCentsOverride: Int? = nil, now: Date = .now) {
        self.userId = userId
        displayName = c.personal.displayName
        office = OfficeRef(policy: c.office)
        switch c.personal.presencePreview {
        case .office: presence = "inside"
        case .away: presence = "outside"
        case .unknown: presence = "unknown"
        }
        lunchStart = c.personal.lunchStart; lunchEnd = c.personal.lunchEnd; lunchDuration = c.personal.lunchDuration
        dietaryStyle = c.personal.dietaryStyle
        allergies = Self.split(c.personal.allergies); dislikes = Self.split(c.personal.dislikes)
        budgetCents = budgetCentsOverride ?? c.office.personBudgetCents
        let parts = Calendar.current.dateComponents([.hour, .minute], from: now)
        nowMinutes = (parts.hour ?? 10) * 60 + (parts.minute ?? 0)
    }
    static func split(_ text: String) -> [String] {
        text.split(whereSeparator: { $0 == "," || $0 == ";" || $0 == "\n" }).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
}

public struct MealOfferOption: Codable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let detail: String
    public let symbol: String
    public let priceCents: Int
    public let baselineCents: Int
    public let itemPriceCents: Int
    public let restaurant: String
    public let restaurantId: String
    public let itemId: String
    public let pricing: String
    public let score: Double
    public let novel: Bool
    public let breakdown: [String: Double]
}

public struct MealOffer: Codable, Equatable {
    public let offerId: String
    public let version: Int
    public let contextVersion: Int
    public let userId: String
    public let officeId: String
    public let groupId: String?
    public let location: String
    public let closesAt: String
    public let arrivesAt: String
    public let options: [MealOfferOption]
    public let participants: Int
    public let sharedDeliveryCents: Int
    public let separateDeliveryCents: Int
    public let suggestOnly: Bool
    public let note: String

    public var deliverySavingsCents: Int { max(0, separateDeliveryCents * participants - separateDeliveryCents) }

    /// Maps an offer onto the card model every surface already renders. Prices are all-in estimates.
    public func lunchSession(office: String, now: Date = .now) -> LunchSession? {
        guard !options.isEmpty else { return nil }
        let iso = ISO8601DateFormatter()
        let closes = iso.date(from: closesAt) ?? now.addingTimeInterval(8 * 60)
        let arrives = iso.date(from: arrivesAt) ?? now.addingTimeInterval(35 * 60)
        return LunchSession(office: office, options: options.map {
            LunchOption(id: $0.id, name: $0.name, detail: "\($0.restaurant) · \($0.detail)", symbol: $0.symbol,
                        priceCents: $0.priceCents, baselineCents: $0.baselineCents)
        }, closesAt: max(closes, now.addingTimeInterval(60)), arrivesAt: max(arrives, now.addingTimeInterval(120)))
    }
}

/// `PUT /v1/profile`: the saved preferences now live on the user row.
public struct ProfileSyncResponse: Codable, Equatable {
    public let userId: String
    public let created: Bool
    public let budgetCents: Int
}

/// Loose JSON for the developer page, so backend debug payloads can change without Swift edits.
public indirect enum JSONValue: Codable, Equatable {
    case string(String), number(Double), bool(Bool), null, array([JSONValue]), object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .null: try c.encodeNil()
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }
    public subscript(key: String) -> JSONValue? { if case .object(let o) = self { return o[key] }; return nil }
    public var array: [JSONValue]? { if case .array(let a) = self { return a }; return nil }
    public var object: [String: JSONValue]? { if case .object(let o) = self { return o }; return nil }
    public var string: String? { if case .string(let s) = self { return s }; return nil }
    public var number: Double? { if case .number(let n) = self { return n }; return nil }
    public var int: Int? { number.map { Int($0) } }
    public var scalarText: String {
        switch self {
        case .string(let s): return s
        case .number(let n): return n == n.rounded() && abs(n) < 1e9 ? String(Int(n)) : String(format: "%.3f", n)
        case .bool(let b): return b ? "true" : "false"
        case .null: return "null"
        case .array(let a): return "[\(a.count)]"
        case .object(let o): return "{\(o.count)}"
        }
    }
}
