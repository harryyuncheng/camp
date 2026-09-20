import Foundation

public struct LunchOption: Codable, Hashable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let detail: String
    public let symbol: String
    public let priceCents: Int
    public let baselineCents: Int
    public var deliveryShareCents: Int?

    public var savingsCents: Int { max(0, baselineCents - priceCents) }

    public init(id: String, name: String, detail: String, symbol: String,
                priceCents: Int, baselineCents: Int, deliveryShareCents: Int? = nil) {
        self.id = id
        self.name = name
        self.detail = detail
        self.symbol = symbol
        self.priceCents = priceCents
        self.baselineCents = baselineCents
        self.deliveryShareCents = deliveryShareCents
    }
}

/// What an order is for. Two categories for now; a place can serve both.
public enum OrderCategory: String, Codable, CaseIterable, Identifiable, Sendable {
    case coffee, meal
    public var id: String { rawValue }
    public var label: String { self == .coffee ? "Coffee & tea" : "Meal" }
    public var symbol: String { self == .coffee ? "cup.and.saucer.fill" : "fork.knife" }
    /// Default arrival time when the user hasn't typed one, minutes from midnight.
    public var defaultMinutes: Int { self == .coffee ? 9 * 60 : 12 * 60 + 30 }
    public init(wire: String?) { self = OrderCategory(rawValue: wire ?? "") ?? .meal }
}

public enum LunchPhase: String, Codable, Sendable {
    case choosing, reviewing, confirmed, delivered, ended
}

public enum LunchEvent: Sendable {
    case select(String), selectMany([String]), changeSelection, confirm, markDelivered, end
}

public enum LunchError: LocalizedError, Equatable {
    case expired, invalidTransition, unknownOption, staleAction, missingSession, busy

    public var errorDescription: String? {
        switch self {
        case .expired: return "This order window has closed. Start a new demo order."
        case .invalidTransition: return "That action is no longer available for this order."
        case .unknownOption: return "This item is no longer available."
        case .staleAction: return "Your order has changed. Please use the latest options."
        case .missingSession: return "This order is no longer active. Open camp to start another."
        case .busy: return "Your last action is still finishing. Try again in a moment."
        }
    }
}

/// Small, Codable state shared by the app, Live Activity, and desktop preview.
/// Prices are integer cents. Real quotes should carry currency and quote expiry too.
public struct LunchSession: Codable, Hashable, Identifiable, Sendable {
    public let id: UUID
    public let office: String
    public let options: [LunchOption]
    public let closesAt: Date
    public let arrivesAt: Date
    /// "coffee" or "meal". Optional so sessions saved by older builds decode; read `kind`.
    public var category: String?
    /// Where the order is from ("Dig", "Blue Bottle"), when known.
    public var place: String?
    public var offerID: String?
    public var kind: OrderCategory { OrderCategory(wire: category) }
    public private(set) var phase: LunchPhase = .choosing
    public private(set) var selectedOptionID: String?
    public private(set) var selectedOptionIDs: [String]?
    public private(set) var revision: Int = 0

    public var selectedOption: LunchOption? { options.first { $0.id == selectedOptionID } }
    public var selectedIDs: [String] { selectedOptionIDs ?? selectedOptionID.map { [$0] } ?? [] }
    public var selectedOptions: [LunchOption] { selectedIDs.compactMap { id in options.first { $0.id == id } } }
    public var isFinished: Bool { phase == .delivered || phase == .ended }

    public init(id: UUID = UUID(), office: String, options: [LunchOption],
                closesAt: Date, arrivesAt: Date, category: OrderCategory = .meal, place: String? = nil, offerID: String? = nil) {
        self.id = id
        self.office = office
        self.options = options
        self.closesAt = closesAt
        self.arrivesAt = arrivesAt
        self.category = category.rawValue
        self.place = place
        self.offerID = offerID
    }

    public func isExpired(at now: Date = .now) -> Bool {
        (phase == .choosing || phase == .reviewing) && now >= closesAt
    }

    /// A confirmed order nobody marked delivered counts as dead this long after `arrivesAt`.
    public static let deliveryGrace: TimeInterval = 2 * 60 * 60

    /// Still worth showing: not finished, not expired, and (if confirmed) not hours past its arrival.
    /// Same rule as `camp.sync.is_dead` on the backend.
    public func isLive(at now: Date = .now) -> Bool {
        if isFinished || isExpired(at: now) { return false }
        if phase == .confirmed { return now < arrivesAt.addingTimeInterval(Self.deliveryGrace) }
        return true
    }

    /// One transition path for every surface. Checking revision rejects delayed taps
    /// from an older card, including a confirm for a meal that has since changed.
    public func applying(_ event: LunchEvent, at now: Date = .now,
                         expectedRevision: Int? = nil) throws -> LunchSession {
        if let expectedRevision, expectedRevision != revision { throw LunchError.staleAction }
        var next = self
        switch event {
        case .select(let id):
            return try applying(.selectMany([id]), at: now, expectedRevision: expectedRevision)
        case .selectMany(let ids):
            guard phase == .choosing || phase == .reviewing else { throw LunchError.invalidTransition }
            guard !isExpired(at: now) else { throw LunchError.expired }
            guard !ids.isEmpty, Set(ids).count == ids.count,
                  ids.allSatisfy({ id in options.contains { $0.id == id } }) else { throw LunchError.unknownOption }
            next.selectedOptionID = ids.first
            next.selectedOptionIDs = ids
            next.phase = .reviewing
        case .changeSelection:
            guard phase == .reviewing else { throw LunchError.invalidTransition }
            guard !isExpired(at: now) else { throw LunchError.expired }
            next.selectedOptionID = nil
            next.selectedOptionIDs = nil
            next.phase = .choosing
        case .confirm:
            guard phase == .reviewing, !selectedIDs.isEmpty, selectedOptions.count == selectedIDs.count else { throw LunchError.invalidTransition }
            guard !isExpired(at: now) else { throw LunchError.expired }
            next.phase = .confirmed
        case .markDelivered:
            guard phase == .confirmed else { throw LunchError.invalidTransition }
            next.phase = .delivered
        case .end:
            guard !isFinished else { throw LunchError.invalidTransition }
            next.phase = .ended
        }
        next.revision += 1
        return next
    }
}

public enum DemoLunch {
    public static func make(now: Date = .now) -> LunchSession {
        LunchSession(office: "HackMIT HQ", options: [
            LunchOption(id: "green-bowl", name: "Green bowl", detail: "Roasted veg · tahini",
                        symbol: "leaf.fill", priceCents: 1140, baselineCents: 1480),
            LunchOption(id: "chicken-rice", name: "Chicken & rice", detail: "Ginger · sesame · crunch",
                        symbol: "flame.fill", priceCents: 1260, baselineCents: 1620),
            LunchOption(id: "pesto-melt", name: "Pesto melt", detail: "Mozzarella · tomato",
                        symbol: "sun.max.fill", priceCents: 1020, baselineCents: 1390)
        ], closesAt: now.addingTimeInterval(8 * 60), arrivesAt: now.addingTimeInterval(35 * 60))
    }
}


/// A pending office lunch group as the backend serves it (`GET /v1/groups`). The name is historical: groups used to be
/// Swift fixtures. Every field the card renders comes from the `groups` table; `people` excludes the current user so
/// the notch and Today page can add themselves while a join is in flight.
public struct DemoLunchGroup: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let cuisine: String
    public let symbol: String
    public let people: Int
    public let delivery: String
    public let options: [LunchOption]
    public let arrivalMinutes: Int
    /// "coffee" or "meal"; absent in records written by older builds.
    public var category: String?
    public var kind: OrderCategory { OrderCategory(wire: category) }
    // Server-only fields (absent when a group is rebuilt locally, e.g. from a sync record written by an older build).
    public var restaurantId: String?
    public var participants: Int?
    public var savingsCents: Int?
    public var deliveryFeeCents: Int?
    public var totalCents: Int?
    public var status: String?
    public var seeded: Bool?
    public var myOptionId: String?
    /// Every item the current user ordered here (a main plus sides/drinks). `myOptionId` is the first of them and
    /// is all that older builds wrote, so read this through `myOptionIdList`.
    public var myOptionIds: [String]?
    /// The user's per-order cap as the backend holds it, so the menu can grey out what no longer fits.
    public var budgetCents: Int?
    /// The backend's id for the requesting user; set on join/create so a first-time user learns their row id.
    public var userId: String?

    public init(id: String, name: String, cuisine: String, symbol: String, people: Int,
                delivery: String, options: [LunchOption], arrivalMinutes: Int? = nil, category: OrderCategory = .meal) {
        self.id = id; self.name = name; self.cuisine = cuisine; self.symbol = symbol
        self.people = people; self.delivery = delivery; self.options = options
        self.arrivalMinutes = arrivalMinutes ?? 750
        self.category = category.rawValue
    }
    public var myOptionIdList: [String] { myOptionIds ?? myOptionId.map { [$0] } ?? [] }
    /// Delivery-fee savings from sharing one delivery, as the backend computed them from real membership.
    public var deliverySavingsCents: Int { savingsCents ?? max(0, people - 1) * (deliveryFeeCents ?? 600) }
    public func arrival(on date: Date = .now) -> Date {
        let minutes = arrivalMinutes
        return Calendar.current.date(bySettingHour: minutes / 60, minute: minutes % 60, second: 0, of: date) ?? date
    }
}

/// `GET /v1/groups` for one office and day.
public struct LunchGroupsResponse: Codable, Equatable, Sendable {
    public let date: String
    public let officeId: String
    public let userId: String?
    public let groups: [DemoLunchGroup]
    public let peopleOrdering: Int
    public let totalSavingsCents: Int
}

/// A restaurant from the catalog with the three items a new group would offer (`GET /v1/restaurants`).
public struct LunchRestaurant: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let cuisine: String
    public let symbol: String
    public let rating: Double?
    public var reviewCount: Int?
    public var categories: [String]?
    public let options: [LunchOption]
    public func serves(_ category: OrderCategory) -> Bool { (categories ?? ["meal"]).contains(category.rawValue) }
}

/// One place that serves what the person said they were craving (`POST /v1/craving`). `options` are the dishes
/// that matched, best first.
public struct LunchCravingMatch: Codable, Identifiable, Hashable, Sendable {
    public let restaurant: LunchRestaurant
    public let reason: String
    public let score: Double
    public var id: String { restaurant.id }
}

/// `POST /v1/craving`: free text ("I want tacos") read by the backend's OpenAI model, answered from the catalog.
public struct LunchCravingResult: Codable, Hashable, Sendable {
    public let text: String
    public let summary: String
    public let interpretation: String
    public let backend: String
    public let matches: [LunchCravingMatch]
    public var note: String?
    /// The sentence was read by OpenAI rather than the offline keyword reader the backend falls back to.
    public var readByLLM: Bool { backend == "llm" }
}

/// One line of a full menu (`GET /v1/restaurants/{id}/menu`). Prices are all-in with the group's delivery share.
public struct LunchMenuItem: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let detail: String
    public let symbol: String
    public let priceCents: Int
    public let itemPriceCents: Int
    public var deliveryShareCents: Int?
    public var popular: Bool?
    public var drink: Bool?
    public var score: Double?
    public var reason: String?
    /// The same item as a group option, so joining off the short list reuses the join path.
    public var option: LunchOption { LunchOption(id: id, name: name, detail: detail, symbol: symbol, priceCents: priceCents, baselineCents: priceCents, deliveryShareCents: deliveryShareCents) }
}

/// A place's full menu with its public rating and the user's top picks first.
public struct LunchMenu: Codable, Hashable, Sendable {
    public let restaurantId: String
    public let name: String
    public let cuisine: String
    public var category: String?
    public let rating: Double?
    public var reviewCount: Int?
    public var ratings: [String: Double]?
    public var recommendations: [String]?
    public var address: String?
    public let top: [LunchMenuItem]
    public let items: [LunchMenuItem]
    public var ratingLabel: String? {
        guard let rating else { return nil }
        let count = reviewCount ?? 0
        return count > 0 ? String(format: "%.1f★ · %d reviews", rating, count) : String(format: "%.1f★", rating)
    }
}

/// A standing order (`/v1/schedules`): a category, a place and a time on chosen weekdays, mirrored to the camp calendar.
public struct LunchSchedule: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let category: String
    public let label: String
    public var restaurantId: String?
    public var restaurantName: String?
    public var optionId: String?
    public let timeMinutes: Int
    public let weekdays: [Int]        // 0 = Monday, as the backend stores them
    public let active: Bool
    public var calendarEventId: String?
    public var kind: OrderCategory { OrderCategory(wire: category) }
    public static let weekdayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    public var weekdayLabel: String {
        let days = weekdays.sorted()
        if days == [0, 1, 2, 3, 4] { return "Weekdays" }
        if days == [0, 1, 2, 3, 4, 5, 6] { return "Every day" }
        return days.compactMap { Self.weekdayNames.indices.contains($0) ? Self.weekdayNames[$0] : nil }.joined(separator: " ")
    }
}


/// One confirmed lunch from the `orders` table (`GET /v1/ledger/{user}`), whichever surface confirmed it.
public struct LunchLedgerEntry: Codable, Hashable, Identifiable, Sendable {
    public let id: String                 // order id
    public let date: Date
    public let office: String
    public let restaurant: String
    public let item: String
    public let symbol: String
    public let amountCents: Int
    public let baselineCents: Int
    public let status: String             // confirmed | manual
    public let source: String             // recommender | group | manual

    public var savingsCents: Int { max(0, baselineCents - amountCents) }
}

public struct LunchLedgerResponse: Codable, Hashable, Sendable {
    public let userId: String
    public let entries: [LunchLedgerEntry]
    public let spentMonthCents: Int
    public let savedMonthCents: Int
    public let monthlyBudgetCents: Int
    public let month: String

    public static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        let iso = ISO8601DateFormatter()
        d.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            if let date = iso.date(from: raw) { return date }
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "bad date \(raw)"))
        }
        return d
    }()
}
