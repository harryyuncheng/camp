import SwiftUI
import Combine
#if SWIFT_PACKAGE
import LunchCore
#endif

public enum CampSection: String, CaseIterable, Identifiable {
    case today = "Today", you = "You", office = "Office", spending = "Spending", connections = "Connections", debug = "Developer"
    public var id: String { rawValue }
    public var symbol: String {
        switch self {
        case .today: return "square.grid.2x2"
        case .you: return "person.crop.circle"
        case .office: return "building.2"
        case .spending: return "creditcard.fill"
        case .connections: return "point.3.connected.trianglepath.dotted"
        case .debug: return "ladybug"
        }
    }
}

@MainActor
public final class CampSettingsStore: ObservableObject {
    @Published public var draft = CampConfiguration()
    @Published public var section = CampSection.today
    @Published public var isDemoAdmin = true
    @Published public var statusMessage: String?
    @Published public var saveError: String?
    @Published public var selectedGroupID: String?
    public var requestDemoGroup: ((DemoLunchGroup) -> Void)?
    public var selectedGroup: DemoLunchGroup? { DemoLunchGroup.all.first { $0.id == selectedGroupID } }
    public func join(_ option: LunchOption, group: DemoLunchGroup) {
        guard group.options.contains(option) else { return }
        selectedGroupID = group.id
        selectedMeal = option
        groupStage = .collecting
    }
    @Published public var selectedMeal: LunchOption?
    @Published public var groupStage = DemoGroupStage.collecting
    @Published public var previewConnections: Set<String> = []
    /// Developer tools: shows the Developer page with live backend state. Persisted per device, outside the config schema.
    @Published public var developerMode: Bool { didSet { UserDefaults.standard.set(developerMode, forKey: "camp.developerMode"); if !developerMode, section == .debug { section = .connections } } }
    /// Live recommendation state from the Python recommender. Ephemeral; the backend is the authority.
    @Published public var recommenderHealth: JSONValue?
    @Published public var recommenderError: String?
    @Published public var recommenderBusy = false
    @Published public var latestOffer: MealOffer?
    @Published public var recommenderUserID: String? = UserDefaults.standard.string(forKey: "camp.recommender.userID")
    /// Set by the platform shell: hands an offer to the notch panel / Live Activity.
    public var onOffer: ((LunchSession) -> Void)?
    /// What the backend did with the last confirmed / delivered lunch (events + profile updates).
    @Published public var lastLunchReport: JSONValue?
    @Published public var lastLunchPhase: String?
    /// Every simulated lunch that was confirmed on this device (recommender offers and demo groups alike).
    /// Feeds the Spending page. Local only; nothing is charged.
    @Published public var lunchLedger: [LunchLedgerEntry] = LunchLedger.load() { didSet { LunchLedger.save(lunchLedger) } }
    public func clearLunchLedger() { lunchLedger = [] }
    #if os(macOS)
    public let location = MacOfficeLocation()
    public let lunchCalendar = MacLunchCalendar()
    #endif
    public var officePresenceLabel: String {
        #if os(macOS)
        return location.presence + " · " + (location.enabled ? "Mac location" : "tracking paused")
        #else
        return "Not connected on iPhone"
        #endif
    }
    public var lunchAvailabilityLabel: String {
        #if os(macOS)
        return lunchCalendar.summary
        #else
        return "Calendar not connected on iPhone"
        #endif
    }
    private var saved = CampConfiguration()
    private let file: ConfigurationFile

    public var sections: [CampSection] { CampSection.allCases.filter { $0 != .debug || developerMode } }

    public init(file: ConfigurationFile = .applicationDefault) {
        self.file = file
        developerMode = UserDefaults.standard.bool(forKey: "camp.developerMode")
        do {
            if let config = try file.load() { draft = config; saved = config }
        } catch { saveError = "Couldn’t restore settings. Your existing file has not been replaced. \(error.localizedDescription)" }
        #if os(macOS)
        lunchCalendar.configure(saved.personal, timezone: saved.office.timezone)
        location.configure(saved.office)
        #endif
    }

    public var savedOffice: OfficePolicy { saved.office }
    #if os(macOS)
    @discardableResult
    public func confirmOfficeBoundary(latitude: Double, longitude: Double, radius: Int) -> Bool {
        guard isDemoAdmin else { saveError = "Enable demo admin to change the office."; return false }
        var updated = saved
        updated.office.latitude = latitude
        updated.office.longitude = longitude
        updated.office.radiusMeters = radius
        guard updated.validationErrors.isEmpty else { saveError = updated.validationErrors.joined(separator: "\n"); return false }
        do {
            try file.save(updated)
            saved = updated
            draft.office.latitude = latitude
            draft.office.longitude = longitude
            draft.office.radiusMeters = radius
            location.configure(updated.office)
            location.confirmOffice()
            saveError = nil; statusMessage = "Office location saved"
            return true
        } catch { saveError = "Couldn’t save office: \(error.localizedDescription)"; return false }
    }
    #endif

    public var hasChanges: Bool { draft != saved }
    public var group: DemoGroupSummary {
        let group = selectedGroup ?? DemoLunchGroup.all[0]
        return DemoGroupSummary(selectedMeal: selectedMeal, stage: groupStage,
                                otherParticipants: group.people,
                                otherFoodCents: group.people * (group.options.first?.priceCents ?? 1140))
    }
    public var validationErrors: [String] {
        var errors = draft.validationErrors
        if !isDemoAdmin && draft.office != saved.office { errors.append("Office changes require demo-admin mode. Discard them or enable it before saving.") }
        return errors
    }

    public func save() {
        guard validationErrors.isEmpty else { saveError = validationErrors.joined(separator: "\n"); return }
        do {
            try file.save(draft)
            saved = draft
            #if os(macOS)
            lunchCalendar.configure(saved.personal, timezone: saved.office.timezone)
            location.configure(saved.office)
            #endif
            saveError = nil
            statusMessage = "Saved on this device"
        } catch { saveError = "Couldn’t save settings: \(error.localizedDescription)" }
    }

    public func discard() { draft = saved; saveError = nil; statusMessage = nil }
    public func resetGroup() { selectedGroupID = nil; selectedMeal = nil; groupStage = .collecting }
    public func join(_ option: LunchOption) {
        guard groupStage == .collecting else { return }
        selectedMeal = option
    }

    // MARK: recommender
    public func client() throws -> RecommendationClient { try RecommendationClient(urlString: draft.connections.recommendationURL) }

    public func connectRecommender() async {
        guard !recommenderBusy else { return }
        recommenderBusy = true; recommenderError = nil
        defer { recommenderBusy = false }
        do { recommenderHealth = try await client().health() }
        catch { recommenderHealth = nil; recommenderError = "\(error.localizedDescription) Start it with: cd backend && uv run uvicorn camp.api:app --port 8788" }
    }

    /// Called by the platform shell when the lunch card changes phase. Only sessions that came from
    /// the recommender (option ids match the latest offer) are reported; demo lunches are ignored.
    public func reportLunch(_ session: LunchSession) {
        recordLunch(session)
        guard let offer = latestOffer, Set(session.options.map(\.id)) == Set(offer.options.map(\.id)) else { return }
        let event: String
        switch session.phase {
        case .confirmed: event = "confirmed"
        case .delivered: event = "delivered"
        case .ended: event = "ended"
        default: return
        }
        guard lastLunchPhase != "\(offer.offerId):\(event)" else { return }
        lastLunchPhase = "\(offer.offerId):\(event)"
        Task {
            do { lastLunchReport = try await client().lunchEvent(offerId: offer.offerId, optionId: session.selectedOptionID, event: event) }
            catch { recommenderError = "Couldn’t record your lunch: \(error.localizedDescription)" }
        }
    }

    /// Writes a confirmed / delivered lunch into the local ledger, naming the restaurant from the recommender offer
    /// or the demo group the options came from.
    func recordLunch(_ session: LunchSession) {
        let fromRecommender = latestOffer.map { Set(session.options.map(\.id)) == Set($0.options.map(\.id)) } ?? false
        let restaurant: String
        if fromRecommender, let option = latestOffer?.options.first(where: { $0.id == session.selectedOptionID }) {
            restaurant = option.restaurant
        } else if let group = DemoLunchGroup.all.first(where: { g in g.options.contains { $0.id == session.selectedOptionID } }) {
            restaurant = group.name
        } else {
            restaurant = "Demo kitchen"
        }
        if let next = LunchLedger.applying(session, to: lunchLedger, restaurant: restaurant, source: fromRecommender ? "recommender" : "demo") {
            lunchLedger = next
        }
    }

    /// Asks the recommender for an offer built from the saved configuration and shows it on the lunch card.
    public func requestOffer(force: Bool = false) async {
        guard !recommenderBusy else { return }
        recommenderBusy = true; recommenderError = nil
        defer { recommenderBusy = false }
        do {
            let context = MealContext(configuration: draft, userId: recommenderUserID)
            let offer = try await client().mealOffer(context, force: force)
            latestOffer = offer
            recommenderUserID = offer.userId
            UserDefaults.standard.set(offer.userId, forKey: "camp.recommender.userID")
            if let session = offer.lunchSession(office: draft.office.name) { onOffer?(session) }
            else { recommenderError = offer.note.isEmpty ? "The recommender returned no options." : offer.note }
        } catch { recommenderError = error.localizedDescription }
    }
}
