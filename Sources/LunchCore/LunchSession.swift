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
