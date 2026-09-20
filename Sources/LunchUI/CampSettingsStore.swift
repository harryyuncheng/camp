import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

public enum CampSection: String, CaseIterable, Identifiable {
    case today = "Today", you = "You", office = "Office", connections = "Connections", debug = "Developer"
    public var id: String { rawValue }
    public var symbol: String {
        switch self {
        case .today: return "square.grid.2x2"
        case .you: return "person.crop.circle"
        case .office: return "building.2"
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
    private var saved = CampConfiguration()
    private let file: ConfigurationFile

    public var sections: [CampSection] { CampSection.allCases.filter { $0 != .debug || developerMode } }

    public init(file: ConfigurationFile = .applicationDefault) {
        self.file = file
        developerMode = UserDefaults.standard.bool(forKey: "camp.developerMode")
        do {
            if let config = try file.load() { draft = config; saved = config }
        } catch { saveError = "Couldn’t restore settings. Your existing file has not been replaced. \(error.localizedDescription)" }
    }

    public var hasChanges: Bool { draft != saved }
    public var group: DemoGroupSummary { DemoGroupSummary(selectedMeal: selectedMeal, stage: groupStage) }
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
            saveError = nil
            statusMessage = "Saved on this device"
        } catch { saveError = "Couldn’t save settings: \(error.localizedDescription)" }
    }

    public func discard() { draft = saved; saveError = nil; statusMessage = nil }
    public func resetGroup() { selectedMeal = nil; groupStage = .collecting }
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
