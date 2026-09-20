import Foundation

public struct LunchOption: Codable, Hashable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let detail: String
    public let symbol: String
    public let priceCents: Int
    public let baselineCents: Int

    public var savingsCents: Int { max(0, baselineCents - priceCents) }

    public init(id: String, name: String, detail: String, symbol: String,
                priceCents: Int, baselineCents: Int) {
        self.id = id
        self.name = name
        self.detail = detail
        self.symbol = symbol
        self.priceCents = priceCents
        self.baselineCents = baselineCents
    }
}

public enum LunchPhase: String, Codable, Sendable {
    case choosing, reviewing, confirmed, delivered, ended
}

public enum LunchEvent: Sendable {
    case select(String), changeSelection, confirm, markDelivered, end
}

public enum LunchError: LocalizedError, Equatable {
    case expired, invalidTransition, unknownOption, staleAction, missingSession, busy

    public var errorDescription: String? {
        switch self {
        case .expired: return "This lunch window has closed. Start a new demo lunch."
        case .invalidTransition: return "That action is no longer available for this lunch."
        case .unknownOption: return "This meal is no longer available."
        case .staleAction: return "Your lunch has changed. Please use the latest options."
        case .missingSession: return "This lunch is no longer active. Open camp to start another."
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
    public private(set) var phase: LunchPhase = .choosing
    public private(set) var selectedOptionID: String?
    public private(set) var revision: Int = 0

    public var selectedOption: LunchOption? { options.first { $0.id == selectedOptionID } }
    public var isFinished: Bool { phase == .delivered || phase == .ended }

    public init(id: UUID = UUID(), office: String, options: [LunchOption],
                closesAt: Date, arrivesAt: Date) {
        self.id = id
        self.office = office
        self.options = options
        self.closesAt = closesAt
        self.arrivesAt = arrivesAt
    }

    public func isExpired(at now: Date = .now) -> Bool {
        (phase == .choosing || phase == .reviewing) && now >= closesAt
    }

    /// One transition path for every surface. Checking revision rejects delayed taps
    /// from an older card, including a confirm for a meal that has since changed.
    public func applying(_ event: LunchEvent, at now: Date = .now,
                         expectedRevision: Int? = nil) throws -> LunchSession {
        if let expectedRevision, expectedRevision != revision { throw LunchError.staleAction }
        var next = self
        switch event {
        case .select(let id):
            guard phase == .choosing || phase == .reviewing else { throw LunchError.invalidTransition }
            guard !isExpired(at: now) else { throw LunchError.expired }
            guard options.contains(where: { $0.id == id }) else { throw LunchError.unknownOption }
            next.selectedOptionID = id
            next.phase = .reviewing
        case .changeSelection:
            guard phase == .reviewing else { throw LunchError.invalidTransition }
            guard !isExpired(at: now) else { throw LunchError.expired }
            next.selectedOptionID = nil
            next.phase = .choosing
        case .confirm:
            guard phase == .reviewing, selectedOption != nil else { throw LunchError.invalidTransition }
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


public struct DemoLunchGroup: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let cuisine: String
    public let symbol: String
    public let people: Int
    public let delivery: String
    public let options: [LunchOption]
    public let arrivalMinutes: Int
    public init(id: String, name: String, cuisine: String, symbol: String, people: Int,
                delivery: String, options: [LunchOption], arrivalMinutes: Int? = nil) {
        self.id = id; self.name = name; self.cuisine = cuisine; self.symbol = symbol
        self.people = people; self.delivery = delivery; self.options = options
        self.arrivalMinutes = arrivalMinutes ?? (id == "noodle-club" ? 765 : id == "sandwich-social" ? 780 : 750)
    }
    public var deliverySavingsCents: Int { max(0, people - 1) * 600 }
    public func arrival(on date: Date = .now) -> Date {
        let minutes = arrivalMinutes
        return Calendar.current.date(bySettingHour: minutes / 60, minute: minutes % 60, second: 0, of: date) ?? date
    }

    public static let all: [DemoLunchGroup] = [
        .init(id: "green-table", name: "The Green Table", cuisine: "Bowls & seasonal plates", symbol: "leaf.fill", people: 3, delivery: "12:30–12:45 PM", options: DemoLunch.make().options),
        .init(id: "noodle-club", name: "Noodle Club", cuisine: "Noodles & dumplings", symbol: "flame.fill", people: 4, delivery: "12:45–1:00 PM", options: [
            .init(id: "miso", name: "Miso ramen", detail: "Mushrooms · corn · spring onion", symbol: "flame.fill", priceCents: 1350, baselineCents: 1650),
            .init(id: "sesame", name: "Sesame noodles", detail: "Chilled noodles · cucumber", symbol: "leaf.fill", priceCents: 1150, baselineCents: 1450),
            .init(id: "dumplings", name: "Dumpling bowl", detail: "Pork dumplings · rice · slaw", symbol: "fork.knife", priceCents: 1250, baselineCents: 1550)
        ]),
        .init(id: "sandwich-social", name: "Sandwich Social", cuisine: "Sandwiches & salads", symbol: "sun.max.fill", people: 2, delivery: "1:00–1:15 PM", options: [
            .init(id: "turkey", name: "Turkey club", detail: "Avocado · tomato · sourdough", symbol: "sun.max.fill", priceCents: 1200, baselineCents: 1500),
            .init(id: "caprese", name: "Caprese baguette", detail: "Mozzarella · basil · tomato", symbol: "leaf.fill", priceCents: 1100, baselineCents: 1400),
            .init(id: "caesar", name: "Chicken Caesar", detail: "Romaine · parmesan · croutons", symbol: "fork.knife", priceCents: 1300, baselineCents: 1600)
        ])
    ]
}


/// One simulated lunch that reached "confirmed" (or later). Kept locally so the Spending page reflects what the
/// demo actually did instead of fixtures. Amounts are the all-in card price at confirmation; nothing is charged.
public struct LunchLedgerEntry: Codable, Hashable, Identifiable, Sendable {
    public let id: String                 // session id, so a later phase updates the same entry
    public var date: Date
    public var office: String
    public var restaurant: String
    public var item: String
    public var symbol: String
    public var amountCents: Int
    public var baselineCents: Int
    public var status: String             // confirmed | delivered
    public var source: String             // recommender | demo

    public var savingsCents: Int { max(0, baselineCents - amountCents) }

    public init(id: String, date: Date, office: String, restaurant: String, item: String, symbol: String,
                amountCents: Int, baselineCents: Int, status: String, source: String) {
        self.id = id; self.date = date; self.office = office; self.restaurant = restaurant; self.item = item
        self.symbol = symbol; self.amountCents = amountCents; self.baselineCents = baselineCents
        self.status = status; self.source = source
    }
}

public enum LunchLedger {
    public static let defaultsKey = "camp.lunchLedger"

    public static func load(from defaults: UserDefaults = .standard) -> [LunchLedgerEntry] {
        guard let data = defaults.data(forKey: defaultsKey) else { return [] }
        return (try? decoder.decode([LunchLedgerEntry].self, from: data)) ?? []
    }

    public static func save(_ entries: [LunchLedgerEntry], to defaults: UserDefaults = .standard) {
        if let data = try? encoder.encode(entries) { defaults.set(data, forKey: defaultsKey) }
    }

    /// Upserts the session's selected meal. Returns nil when the session has nothing to record
    /// (not yet confirmed, or ended without confirming).
    public static func applying(_ session: LunchSession, to entries: [LunchLedgerEntry], restaurant: String,
                                source: String, now: Date = .now) -> [LunchLedgerEntry]? {
        let status: String
        switch session.phase {
        case .confirmed: status = "confirmed"
        case .delivered: status = "delivered"
        default: return nil
        }
        guard let option = session.selectedOption else { return nil }
        var next = entries
        let id = session.id.uuidString
        if let i = next.firstIndex(where: { $0.id == id }) {
            next[i].status = status
            next[i].item = option.name; next[i].amountCents = option.priceCents; next[i].baselineCents = option.baselineCents
        } else {
            next.append(LunchLedgerEntry(id: id, date: now, office: session.office, restaurant: restaurant, item: option.name,
                                         symbol: option.symbol, amountCents: option.priceCents, baselineCents: option.baselineCents,
                                         status: status, source: source))
        }
        return next.sorted { $0.date > $1.date }
    }

    public static func spentCents(_ entries: [LunchLedgerEntry], inMonthOf date: Date = .now, calendar: Calendar = .current) -> Int {
        entries.filter { calendar.isDate($0.date, equalTo: date, toGranularity: .month) }.reduce(0) { $0 + $1.amountCents }
    }

    private static let encoder: JSONEncoder = { let e = JSONEncoder(); e.dateEncodingStrategy = .iso8601; return e }()
    private static let decoder: JSONDecoder = { let d = JSONDecoder(); d.dateDecodingStrategy = .iso8601; return d }()
}
