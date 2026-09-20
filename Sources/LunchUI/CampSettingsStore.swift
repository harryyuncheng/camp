import SwiftUI
import Combine
#if SWIFT_PACKAGE
import LunchCore
#endif

public enum CampSection: String, CaseIterable, Identifiable {
    case today = "Today", you = "You", office = "Office", spending = "Spending", connections = "Connections", demo = "Demo"
    public var id: String { rawValue }
    /// Sections in the main sidebar list. `.demo` sits on its own, bottom-aligned above the office footer.
    public static var main: [CampSection] { allCases.filter { $0 != .demo } }
    public var symbol: String {
        switch self {
        case .today: return "square.grid.2x2"
        case .you: return "person.crop.circle"
        case .office: return "building.2"
        case .spending: return "creditcard.fill"
        case .connections: return "point.3.connected.trianglepath.dotted"
        case .demo: return "sparkles"
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
    /// Today's group orders (coffee runs and meals) for the saved office, straight from the backend's `groups` table.
    @Published public var lunchGroups: [DemoLunchGroup] = []
    @Published public var groupsSummary: LunchGroupsResponse?
    @Published public var groupsError: String?
    @Published public var groupsBusy = false
    /// Places the create-order sheet and the scheduler can start an order at (`GET /v1/restaurants`, both categories).
    @Published public var restaurants: [LunchRestaurant] = []
    /// The last free-text craving search (`POST /v1/craving`): for when none of today's places appeal.
    @Published public var craving: LunchCravingResult?
    @Published public var cravingBusy = false
    @Published public var cravingError: String?
    /// Full menus by "restaurantId|groupId" (`GET /v1/restaurants/{id}/menu`).
    @Published public var menus: [String: LunchMenu] = [:]
    @Published public var menuError: String?
    /// Standing orders from `GET /v1/schedules/{user}`.
    @Published public var schedules: [LunchSchedule] = []
    @Published public var scheduleError: String?
    @Published public var scheduleBusy = false
    public var peopleOrdering: Int { groupsSummary?.peopleOrdering ?? lunchGroups.reduce(0) { $0 + participantCount(for: $1) } }
    public var totalSavingsCents: Int { groupsSummary?.totalSavingsCents ?? lunchGroups.reduce(0) { $0 + savingsCents(for: $1) } }
    /// Every group the user is in today, one per category at most, nearest arrival first.
    public var myGroups: [DemoLunchGroup] { lunchGroups.filter { $0.myOptionId != nil || ($0.id == selectedGroupID && selectedMeal != nil) }.sorted { $0.arrivalMinutes < $1.arrivalMinutes } }
    public func myOption(in group: DemoLunchGroup) -> LunchOption? {
        if group.id == selectedGroupID, let selectedMeal { return selectedMeal }
        return group.options.first { $0.id == group.myOptionId }
    }
    public func participantCount(for group: DemoLunchGroup) -> Int {
        group.people + (myOption(in: group) != nil ? 1 : 0)
    }
    public func restaurants(for category: OrderCategory) -> [LunchRestaurant] { restaurants.filter { $0.serves(category) } }
    public func savingsCents(for group: DemoLunchGroup) -> Int { max(0, participantCount(for: group) - 1) * (group.deliveryFeeCents ?? 600) }

    private var officeRef: OfficeRef { OfficeRef(policy: saved.office) }

    /// Reloads today's groups; membership (which group and meal are yours) comes back with them.
    public func refreshGroups() async {
        groupsBusy = true
        defer { groupsBusy = false }
        do {
            let response = try await client().groups(office: officeRef, userId: recommenderUserID)
            apply(groups: response)
            groupsError = nil
        } catch { groupsError = "Couldn’t load group orders: \(error.localizedDescription)" }
    }

    public func loadRestaurants() async {
        guard restaurants.isEmpty else { return }
        do {
            let client = try client()
            async let meals = client.restaurants(limit: 24, category: .meal)
            async let cafes = client.restaurants(limit: 24, category: .coffee)
            var seen = Set<String>()
            restaurants = (try await cafes + meals).filter { seen.insert($0.id).inserted }
        } catch { groupsError = "Couldn’t load restaurants: \(error.localizedDescription)" }
    }

    /// "I want tacos" → places from the catalog that serve it, read by the backend's OpenAI model. The matched
    /// dishes come back as the restaurant's options, so picking one starts a group order on the usual path.
    public func searchCraving(_ text: String, category: OrderCategory?) async {
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty, !cravingBusy else { return }
        cravingBusy = true
        defer { cravingBusy = false }
        do {
            craving = try await client().craving(text: query, category: category, userId: recommenderUserID)
            cravingError = nil
        } catch {
            craving = nil
            cravingError = "Couldn’t search that craving: \(error.localizedDescription)"
        }
    }

    public func clearCraving() { craving = nil; cravingError = nil }

    /// The full menu for a group's restaurant, priced with that group's delivery share and ranked for this user.
    public func menu(for group: DemoLunchGroup) -> LunchMenu? { group.restaurantId.flatMap { menus["\($0)|\(group.id)"] } }
    public func loadMenu(for group: DemoLunchGroup) async {
        guard let restaurantId = group.restaurantId else { return }
        do { menus["\(restaurantId)|\(group.id)"] = try await client().menu(restaurantId: restaurantId, userId: recommenderUserID, groupId: group.id); menuError = nil }
        catch { menuError = "Couldn’t load the menu: \(error.localizedDescription)" }
    }

    private func apply(groups response: LunchGroupsResponse) {
        groupsSummary = response
        lunchGroups = response.groups.sorted { ($0.arrivalMinutes, $0.name) < ($1.arrivalMinutes, $1.name) }
        // The "selected" group is the nearest upcoming order the user is in; the notch shows that one first.
        let now = Calendar.current.component(.hour, from: .now) * 60 + Calendar.current.component(.minute, from: .now)
        let mine = lunchGroups.filter { $0.myOptionId != nil }
        if let next = mine.first(where: { $0.arrivalMinutes >= now - 30 }) ?? mine.first {
            selectedGroupID = next.id
            selectedMeal = next.options.first { $0.id == next.myOptionId }
            groupStage = .collecting
        } else {
            selectedGroupID = nil; selectedMeal = nil
        }
        syncOrderEvents()
    }

    private func remember(userId: String) {
        guard recommenderUserID != userId else { return }
        recommenderUserID = userId
        UserDefaults.standard.set(userId, forKey: "camp.recommender.userID")
    }

    /// Replaces one group in the list with what the backend returned and re-derives membership from it. Joining a
    /// group leaves only the other groups in the same category; a coffee and a meal stay active together.
    private func merge(_ group: DemoLunchGroup) {
        if let i = lunchGroups.firstIndex(where: { $0.id == group.id }) { lunchGroups[i] = group } else { lunchGroups.append(group) }
        if group.myOptionId != nil {
            for i in lunchGroups.indices where lunchGroups[i].id != group.id && lunchGroups[i].kind == group.kind { lunchGroups[i].myOptionId = nil }
            selectedGroupID = group.id
            selectedMeal = group.options.first { $0.id == group.myOptionId }
        } else if selectedGroupID == group.id {
            selectedGroupID = nil; selectedMeal = nil
        }
        lunchGroups.removeAll { $0.status == "cancelled" }
        lunchGroups.sort { ($0.arrivalMinutes, $0.name) < ($1.arrivalMinutes, $1.name) }
        syncOrderEvents()
    }

    /// Starts a group order at a catalog place and joins it (`POST /v1/groups`). The backend leaves any other group in
    /// the same category first.
    @discardableResult
    public func createGroup(restaurant: LunchRestaurant, arrivalMinutes: Int, meal: LunchOption, category: OrderCategory) async -> Bool {
        guard restaurant.options.contains(meal), (300...1320).contains(arrivalMinutes), restaurant.serves(category) else { return false }
        do {
            let group = try await client().createGroup(office: officeRef, restaurantId: restaurant.id, deliveryMinutes: arrivalMinutes,
                                                       optionId: meal.id, userId: recommenderUserID, displayName: saved.personal.displayName,
                                                       category: category)
            if let me = group.userId { remember(userId: me) }
            merge(group)
            groupsError = nil
            requestConfirmedDemoGroup?(group, meal)
            await refreshGroups()
            return true
        } catch { groupsError = "Couldn’t create the order: \(error.localizedDescription)"; return false }
    }

    // MARK: calendar mirroring (Mac): one event per joined group, in the "camp" calendar
    private let orderEventsKey = "camp.calendar.order-events.v1"
    private var orderEvents: [String: String] {
        get { UserDefaults.standard.dictionary(forKey: orderEventsKey) as? [String: String] ?? [:] }
        set { UserDefaults.standard.set(newValue, forKey: orderEventsKey) }
    }
    /// Adds a block for every group the user is in and removes blocks for groups they left. Keyed by group id, so a
    /// refresh after a restart neither duplicates nor drops anything. No-op until calendars are connected.
    private func syncOrderEvents() {
        #if os(macOS)
        guard lunchCalendar.canWrite else { return }
        var events = orderEvents
        let mine = Dictionary(uniqueKeysWithValues: lunchGroups.filter { $0.myOptionId != nil }.map { ($0.id, $0) })
        for (groupId, eventId) in events where mine[groupId] == nil {
            lunchCalendar.removeOrderEvent(id: eventId); events[groupId] = nil
        }
        for (groupId, group) in mine where events[groupId] == nil {
            let item = group.options.first { $0.id == group.myOptionId }?.name ?? ""
            let order = CampOrderEvent(title: "\(group.kind.label) · \(group.name)",
                                       start: lunchCalendar.date(minutes: group.arrivalMinutes),
                                       durationMinutes: group.kind == .coffee ? 15 : saved.personal.lunchDuration,
                                       notes: item.isEmpty ? "Group order via camp" : "\(item) · group order via camp")
            if let id = try? lunchCalendar.addOrderEvent(order) { events[groupId] = id }
        }
        orderEvents = events
        #endif
    }

    // MARK: standing orders (You → Schedule a new order)
    public func refreshSchedules() async {
        guard let userId = recommenderUserID else { schedules = []; return }
        do { schedules = try await client().schedules(userId: userId); scheduleError = nil }
        catch { scheduleError = "Couldn’t load your standing orders: \(error.localizedDescription)" }
    }

    /// Saves a standing order on the backend, then mirrors it as a recurring event in the camp calendar (Mac only)
    /// and records the event id so removing the schedule removes the event too.
    @discardableResult
    public func addSchedule(category: OrderCategory, label: String, restaurant: LunchRestaurant?, option: LunchOption?,
                            timeMinutes: Int, weekdays: [Int]) async -> Bool {
        guard !scheduleBusy, (300...1320).contains(timeMinutes), !weekdays.isEmpty else { return false }
        scheduleBusy = true
        defer { scheduleBusy = false }
        do {
            var schedule = try await client().addSchedule(office: officeRef, userId: recommenderUserID, displayName: saved.personal.displayName,
                                                          category: category, label: label, restaurantId: restaurant?.id, optionId: option?.id,
                                                          timeMinutes: timeMinutes, weekdays: weekdays)
            #if os(macOS)
            if lunchCalendar.canWrite {
                let title = restaurant.map { "\(schedule.label) · \($0.name)" } ?? schedule.label
                let order = CampOrderEvent(title: title, start: lunchCalendar.nextOccurrence(minutes: timeMinutes, weekdays: weekdays),
                                           durationMinutes: category == .coffee ? 15 : saved.personal.lunchDuration,
                                           notes: "Standing \(category.label.lowercased()) order via camp", weekdays: weekdays)
                if let eventId = try? lunchCalendar.addOrderEvent(order) {
                    schedule = (try? await client().setScheduleEvent(schedule.id, eventId: eventId)) ?? schedule
                    if schedule.calendarEventId == nil { schedule.calendarEventId = eventId }
                }
            }
            #endif
            schedules.append(schedule)
            schedules.sort { $0.timeMinutes < $1.timeMinutes }
            scheduleError = nil
            await refreshSchedules()
            await refreshGroups()          // the backend materialises today's occurrence into a group straight away
            return true
        } catch { scheduleError = "Couldn’t schedule the order: \(error.localizedDescription)"; return false }
    }

    public func removeSchedule(_ schedule: LunchSchedule) async {
        guard let userId = recommenderUserID else { return }
        #if os(macOS)
        if let eventId = schedule.calendarEventId { lunchCalendar.removeOrderEvent(id: eventId) }
        #endif
        do { _ = try await client().removeSchedule(schedule.id, userId: userId); schedules.removeAll { $0.id == schedule.id }; scheduleError = nil }
        catch { scheduleError = "Couldn’t remove the standing order: \(error.localizedDescription)" }
    }
    @Published public var selectedGroupID: String?
    public var requestConfirmedDemoGroup: ((DemoLunchGroup, LunchOption) -> Void)?
    public var requestEndDemoGroup: (() -> Void)?
    public var requestDemoGroup: ((DemoLunchGroup) -> Void)?
    public var selectedGroup: DemoLunchGroup? { lunchGroups.first { $0.id == selectedGroupID } }
    /// Joins (or changes the meal in) a group. Optimistic locally, then `POST /v1/groups/{id}/join` makes it the
    /// backend's truth: the member row and a confirmed Order for this lunch.
    public func join(_ option: LunchOption, group: DemoLunchGroup) {
        guard group.options.contains(option) else { return }
        if !lunchGroups.contains(where: { $0.id == group.id }) { lunchGroups.append(group) }
        selectedGroupID = group.id
        selectedMeal = option
        groupStage = .collecting
        Task {
            do {
                let updated = try await client().joinGroup(group.id, office: officeRef, optionId: option.id,
                                                           userId: recommenderUserID, displayName: saved.personal.displayName)
                if let me = updated.userId { remember(userId: me) }
                merge(updated)
                groupsError = nil
                await refreshGroups()
                await refreshLedger()
            } catch { groupsError = "Couldn’t join \(group.name): \(error.localizedDescription)" }
        }
    }
    @Published public var selectedMeal: LunchOption?
    @Published public var groupStage = DemoGroupStage.collecting
    @Published public var previewConnections: Set<String> = []
    /// Live recommendation state from the Python recommender. Ephemeral; the backend is the authority.
    @Published public var recommenderHealth: JSONValue?
    @Published public var recommenderError: String?
    @Published public var recommenderBusy = false
    @Published public var latestOffer: MealOffer?
    @Published public var recommenderUserID: String? = UserDefaults.standard.string(forKey: "camp.recommender.userID")
    /// Set by the platform shell: hands an offer to the notch panel / Live Activity.
    public var onOffer: ((LunchSession) -> Void)?
    /// Set by the platform shell; called with the saved connection settings now and after every save, so the
    /// shared-lunch sync points at the same backend as the recommender.
    public var onConnectionsChanged: ((ConnectionPreferences) -> Void)? { didSet { onConnectionsChanged?(saved.connections) } }
    /// Shared-lunch sync state reported by the platform shell ("Live · 192.168.1.4", an error, or nil when off).
    @Published public var syncStatus: String?
    /// What the backend did with the last confirmed / delivered lunch (events + profile updates).
    @Published public var lastLunchReport: JSONValue?
    @Published public var lastLunchPhase: String?
    /// Confirmed lunches from the backend's `orders` table (recommender picks and group joins alike). Feeds the
    /// Spending page. Nothing is charged; the rows are the record of what was ordered.
    @Published public var ledger: LunchLedgerResponse?
    @Published public var ledgerError: String?
    public func refreshLedger() async {
        guard let userId = recommenderUserID else { ledger = nil; return }
        do { ledger = try await client().ledger(userId: userId, officeName: saved.office.name); ledgerError = nil }
        catch { ledgerError = "Couldn’t load spending: \(error.localizedDescription)" }
    }
    /// Everything the Today, You and Spending pages show, in one go.
    public func refreshAll() async {
        await refreshGroups()
        await loadRestaurants()
        await refreshLedger()
        await refreshSchedules()
    }
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

    public init(file: ConfigurationFile = .applicationDefault) {
        self.file = file
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
            onConnectionsChanged?(saved.connections)
            saveError = nil
            statusMessage = "Saved on this device · syncing profile…"
            Task { await syncProfile() }
        } catch { saveError = "Couldn’t save settings: \(error.localizedDescription)" }
    }

    /// `PUT /v1/profile`: the saved preferences become the user row's settings, so the recommender, the groups and
    /// any other device read the same profile.
    public func syncProfile() async {
        do {
            let result = try await client().putProfile(MealContext(configuration: saved, userId: recommenderUserID))
            remember(userId: result.userId)
            statusMessage = "Saved · profile synced to the backend"
            await refreshAll()
        } catch { statusMessage = "Saved on this device · backend offline (\(error.localizedDescription))" }
    }

    public func discard() { draft = saved; saveError = nil; statusMessage = nil }
    /// Leaves the nearest joined group (the one the notch shows).
    public func resetGroup() {
        if let group = selectedGroup { leave(group) }
        else { selectedGroupID = nil; selectedMeal = nil; groupStage = .collecting; requestEndDemoGroup?() }
    }
    /// Leaves one group (`DELETE /v1/groups/{id}/members/{me}`): the member row goes, the order is cancelled and the
    /// calendar block is removed. Other categories' orders are untouched.
    public func leave(_ group: DemoLunchGroup) {
        if selectedGroupID == group.id { selectedGroupID = nil; selectedMeal = nil; groupStage = .collecting; requestEndDemoGroup?() }
        if let i = lunchGroups.firstIndex(where: { $0.id == group.id }) { lunchGroups[i].myOptionId = nil }
        syncOrderEvents()
        guard let userId = recommenderUserID else { return }
        Task {
            do { merge(try await client().leaveGroup(group.id, userId: userId)); groupsError = nil; await refreshGroups(); await refreshLedger() }
            catch { groupsError = "Couldn’t leave the group: \(error.localizedDescription)" }
        }
    }
    public func join(_ option: LunchOption) {
        guard groupStage == .collecting else { return }
        selectedMeal = option
    }

    // MARK: recommender
    public func client() throws -> RecommendationClient {
        try RecommendationClient(urlString: draft.connections.recommendationURL, token: draft.connections.recommendationToken)
    }

    public func connectRecommender() async {
        guard !recommenderBusy else { return }
        recommenderBusy = true; recommenderError = nil
        defer { recommenderBusy = false }
        do { recommenderHealth = try await client().health() }
        catch { recommenderHealth = nil; recommenderError = "\(error.localizedDescription) Start it with: cd backend && uv run camp serve" }
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
            do { lastLunchReport = try await client().lunchEvent(offerId: offer.offerId, optionId: session.selectedOptionID, event: event); await refreshLedger() }
            catch { recommenderError = "Couldn’t record your order: \(error.localizedDescription)" }
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
            remember(userId: offer.userId)
            if let session = offer.lunchSession(office: draft.office.name) { onOffer?(session) }
            else { recommenderError = offer.note.isEmpty ? "The recommender returned no options." : offer.note }
        } catch { recommenderError = error.localizedDescription }
    }
}
