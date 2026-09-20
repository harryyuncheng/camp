import Foundation
import Combine
#if SWIFT_PACKAGE
import LunchCore
#endif

extension Notification.Name {
    static let lunchReady = Notification.Name("Lunchline.lunchReady")
}

@MainActor
final class MacLunchModel: ObservableObject {
    /// The order the notch shows: the nearest active one. Other active orders wait in `others`.
    @Published private(set) var session = DemoLunch.make()
    /// Every shared order besides `session`, nearest first (a meal waiting behind the morning coffee, say).
    @Published private(set) var others: [LunchSyncRecord] = []
    @Published var groups: [DemoLunchGroup] = []
    @Published var joinedGroupID: String?
    @Published var choosingGroup = true
    @Published private(set) var demoGroup: DemoLunchGroup?
    var officeName = "HackMIT HQ"
    var onJoin: (([LunchOption], DemoLunchGroup) async throws -> DemoLunchGroup)?
    var onRemoteChange: (() -> Void)?
    var onRecords: (([LunchSyncRecord]) -> Void)?
    @Published private(set) var isWorking = false
    private var pendingRecords: [LunchSyncRecord]?
    private var localDemo = true

    // MARK: looking for something else
    /// What was typed into the notch when none of today's orders appeal ("I want tacos", "iced oat latte"). The
    /// search itself runs on the backend through the settings store; the results land in `cravingResult`.
    @Published var cravingText = ""
    @Published var cravingBusy = false
    @Published var cravingResult: LunchCravingResult?
    @Published var cravingError: String?
    @Published var cravingOpen = false
    /// What the card is showing after a search ("Matches for “I want tacos”"), so it is obvious the options on the
    /// card are no longer the group's.
    @Published var cravingHeadline: String?
    /// Where each option on a searched card comes from, keyed by option id: the place, and the untouched option to
    /// send back to the backend (the displayed one carries the place's name in its detail line).
    private var cravingItems: [String: (place: LunchRestaurant, option: LunchOption)] = [:]
    private var cravingArrivalMinutes = OrderCategory.meal.defaultMinutes
    private var cravingCategory = OrderCategory.meal
    var onCravingSearch: ((String, OrderCategory) async -> Void)?
    var onCravingOrder: ((LunchRestaurant, LunchOption, Int, OrderCategory) async -> DemoLunchGroup?)?

    /// Searches the catalog and puts what came back on the card, in place of whatever was there. The panel stays
    /// open throughout: a search replaces the order on screen, it does not start a separate one.
    func searchCraving() async {
        let text = cravingText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !cravingBusy, !isWorking else { return }
        await onCravingSearch?(text, choosingGroup ? .meal : session.kind)
        if let result = cravingResult { applyCraving(result, text: text) }
    }

    private func applyCraving(_ result: LunchCravingResult, text: String) {
        var options: [LunchOption] = []
        var items: [String: (place: LunchRestaurant, option: LunchOption)] = [:]
        for match in result.matches {
            guard let dish = match.restaurant.options.first, items[dish.id] == nil else { continue }
            let detail = dish.detail.isEmpty ? match.restaurant.name : "\(match.restaurant.name) · \(dish.detail)"
            options.append(LunchOption(id: dish.id, name: dish.name, detail: detail, symbol: dish.symbol,
                                       priceCents: dish.priceCents, baselineCents: dish.baselineCents,
                                       deliveryShareCents: dish.deliveryShareCents))
            items[dish.id] = (match.restaurant, dish)
        }
        guard let first = options.first, let place = items[first.id]?.place else {
            cravingHeadline = "Nothing on the catalog’s menus matches that."
            return
        }
        scheduledLunch?.cancel(); scheduled = false
        cravingItems = items
        cravingCategory = place.serves(.meal) ? .meal : .coffee
        cravingArrivalMinutes = demoGroup?.arrivalMinutes ?? cravingCategory.defaultMinutes
        cravingHeadline = "Matches for “\(text)”"
        demoGroup = nil
        choosingGroup = false
        let now = Date()
        let arrival = Calendar.current.date(bySettingHour: cravingArrivalMinutes / 60, minute: cravingArrivalMinutes % 60,
                                            second: 0, of: now) ?? now.addingTimeInterval(35 * 60)
        // Kept on this Mac until it is confirmed: a search is a look around, not an order the phone should show.
        offer(LunchSession(office: officeName, options: options, closesAt: now.addingTimeInterval(8 * 60),
                           arrivesAt: arrival, category: cravingCategory), shared: false)
    }

    func chooseGroup(_ group: DemoLunchGroup) {
        guard !isWorking else { return }
        scheduledLunch?.cancel(); scheduled = false
        clearCraving()
        demoGroup = group; choosingGroup = false
        let now = Date()
        offer(LunchSession(office: officeName, options: group.options,
                           closesAt: now.addingTimeInterval(8 * 60), arrivesAt: group.arrival(on: now),
                           category: group.kind, place: group.name))
    }
    /// Brings one of the waiting orders to the front of the notch.
    func show(_ record: LunchSyncRecord) {
        guard !isWorking, record.session.id != session.id else { return }
        stash(current: session, group: demoGroup)
        others.removeAll { $0.sessionId == record.sessionId }
        adopt(record, announce: !record.session.isFinished)
    }
    @Published var error: String?
    @Published var scheduled = false
    private let store: SessionFile
    private var scheduledLunch: Task<Void, Never>?
    /// Fires after every successful transition (confirm, delivered, end) so the shell can report it.
    var onTransition: ((LunchSession) -> Void)?
    var onBackendTransition: ((LunchSession) async throws -> Void)?
    /// Shared session through the backend. Every local offer/transition is published; records from the
    /// phone arrive through `applyRemote`. The delegate configures it from the saved connection settings.
    let sync = LunchSyncCoordinator(device: "mac")

    init(store: SessionFile = .applicationStore(named: "LunchlineMac")) {
        self.store = store
        do {
            if let saved = try store.loadRecord() {
                session = saved.session
                demoGroup = saved.group
                localDemo = false
                choosingGroup = saved.group == nil && saved.session.phase == .choosing
            }
        }
        catch { self.error = "Could not restore your order: \(error.localizedDescription)" }
        sync.applyAll = { [weak self] records in self?.reconcile(records) }
    }

    /// Entry point for a future prediction or notification service. Persist the
    /// offered session, then notify the presentation layer to automatically expand.
    func offer(_ lunch: LunchSession) {
        guard !isWorking else { return }
        choosingGroup = false
        offer(lunch, shared: true)
    }

    /// `shared: false` keeps a lunch on this Mac: the group picker's placeholder session is not a lunch the
    /// phone should show; the phone hears about the real one from `chooseGroup`.
    private func offer(_ lunch: LunchSession, shared: Bool) {
        guard !isWorking else { return }
        let previous = session
        do {
            try store.save(lunch, group: demoGroup)
            localDemo = !shared
            session = lunch
            error = nil
            NotificationCenter.default.post(name: .lunchReady, object: self)
            if shared { publish(previous: previous) }
        } catch { self.error = error.localizedDescription }
    }

    func triggerDemo() {
        guard !isWorking else { return }
        scheduledLunch?.cancel()
        scheduled = false
        choosingGroup = true; demoGroup = nil
        clearCraving()
        offer(DemoLunch.make(), shared: false)
    }

    private func clearCraving() {
        cravingItems = [:]
        cravingHeadline = nil
        cravingOpen = false
    }

    func triggerAfterDelay() {
        scheduledLunch?.cancel()
        scheduled = true
        scheduledLunch = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 5_000_000_000) }
            catch { return }
            guard let self, !Task.isCancelled else { return }
            self.scheduled = false
            self.triggerDemo()
        }
    }

    func send(_ event: LunchEvent, revision: Int) {
        guard !isWorking else { error = LunchError.busy.localizedDescription; return }
        let previous = session
        do {
            let next = try session.applying(event, expectedRevision: revision)
            let confirmingCraving = localDemo && !cravingItems.isEmpty && next.phase == .confirmed
            if localDemo && !confirmingCraving {
                try store.save(next, group: demoGroup)
                session = next
                onTransition?(next)
                error = nil
                return
            }
            isWorking = true
            Task {
                defer { finishWrite() }
                do {
                    var group = demoGroup
                    if next.phase == .confirmed, previous.phase != .confirmed {
                        if let option = next.selectedOption, let found = cravingItems[option.id] {
                            guard let created = await onCravingOrder?(found.place, found.option, cravingArrivalMinutes, cravingCategory) else {
                                error = "Couldn’t create this group order. Check Today for the backend error."
                                return
                            }
                            group = created
                        } else if let currentGroup = group {
                            guard let onJoin else { throw LunchError.missingSession }
                            group = try await onJoin(next.selectedOptions, currentGroup)
                        }
                    }
                    if next.offerID != nil {
                        guard let onBackendTransition else { throw LunchError.missingSession }
                        try await onBackendTransition(next)
                    }
                    if let failure = await sync.publish(next, group: group, previous: confirmingCraving ? nil : previous) { throw failure }
                    try store.save(next, group: group)
                    demoGroup = group
                    localDemo = false
                    session = next
                    onTransition?(next)
                    error = nil
                } catch { self.error = error.localizedDescription }
            }
        } catch { self.error = error.localizedDescription }
    }

    func showConfirmed(_ group: DemoLunchGroup) {
        guard !isWorking else { error = LunchError.busy.localizedDescription; return }
        do {
            let now = Date()
            let initial = LunchSession(office: officeName, options: group.options, closesAt: now.addingTimeInterval(8 * 60),
                                       arrivesAt: group.arrival(on: now), category: group.kind, place: group.name)
            let selected = try initial.applying(.selectMany(group.myOptionIdList), at: now)
            let confirmed = try selected.applying(.confirm, at: now)
            demoGroup = group
            choosingGroup = false
            clearCraving()
            offer(confirmed)
        } catch { self.error = error.localizedDescription }
    }

    /// Deletes one shared order from the backend; the snapshot echo removes it from every device.
    func forgetSession(_ sessionID: String) {
        guard !isWorking else { error = LunchError.busy.localizedDescription; return }
        isWorking = true
        Task {
            defer { finishWrite() }
            if let failure = await sync.forget(sessionId: sessionID) { error = failure.localizedDescription }
        }
    }

    func forgetGroup(_ groupID: String) {
        guard !isWorking else { error = LunchError.busy.localizedDescription; return }
        let matching = others.filter { $0.group?.id == groupID }.map(\.sessionId)
            + (demoGroup?.id == groupID ? [session.id.uuidString] : [])
        guard !matching.isEmpty else { return }
        isWorking = true
        Task {
            defer { finishWrite() }
            for id in matching {
                if let failure = await sync.forget(sessionId: id) { error = failure.localizedDescription; return }
            }
        }
    }

    /// A record the phone (or the backend's list) holds. Same order and newer revision → adopt the transition. A
    /// different order → show it when it is nearer than the one on screen (or the screen one is finished),
    /// otherwise keep it waiting in `others`. Echoes of this Mac's own writes have an equal revision and are ignored.
    private func applyRemote(_ record: LunchSyncRecord) {
        let incoming = record.session
        if incoming.id == session.id {
            guard incoming != session || record.group != demoGroup else { return }
            do { try store.save(incoming, group: record.group) } catch { self.error = error.localizedDescription }
            session = incoming
            demoGroup = record.group
            return
        }
        if let i = others.firstIndex(where: { $0.sessionId == record.sessionId }) {
            if record.revision > others[i].revision { others[i] = record }
        } else {
            others.append(record)
        }
        others.sort { $0.session.arrivesAt < $1.session.arrivesAt }
        let showing = choosingGroup ? nil : session
        let nearer = !incoming.isFinished && (showing == nil || showing!.isFinished || showing!.isExpired() || incoming.arrivesAt < showing!.arrivesAt)
        guard nearer else { return }
        if let showing, !showing.isFinished { stash(current: showing, group: demoGroup) }
        others.removeAll { $0.sessionId == record.sessionId }
        adopt(record, announce: true)
    }

    /// The backend's complete list: drop waiting orders that were forgotten elsewhere and, when the order on screen
    /// is gone too, fall back to the nearest remaining one.
    private func reconcile(_ records: [LunchSyncRecord]) {
        guard !isWorking else { pendingRecords = records; return }
        onRecords?(records)
        others = records.filter { $0.session.id != session.id }
        if let current = records.first(where: { $0.session.id == session.id }) {
            applyRemote(current)
        } else if let next = records.nearest {
            others.removeAll { $0.sessionId == next.sessionId }
            adopt(next, announce: next.session.id != session.id)
        } else if !choosingGroup && cravingItems.isEmpty {
            triggerDemo()
        }
        onRemoteChange?()
    }

    private func stash(current: LunchSession, group: DemoLunchGroup?) {
        guard !current.isFinished, !current.isExpired() else { return }
        others.removeAll { $0.sessionId == current.id.uuidString }
        others.append(LunchSyncRecord(session: current, group: group, device: "mac"))
        others.sort { $0.session.arrivesAt < $1.session.arrivesAt }
    }

    private func adopt(_ record: LunchSyncRecord, announce: Bool) {
        let incoming = record.session
        scheduledLunch?.cancel(); scheduled = false
        do { try store.save(incoming, group: record.group); error = nil } catch { self.error = error.localizedDescription }
        demoGroup = record.group
        localDemo = false
        choosingGroup = false
        session = incoming
        if announce && !incoming.isFinished { NotificationCenter.default.post(name: .lunchReady, object: self) }
    }

    private func publish(previous: LunchSession) {
        let current = session, group = demoGroup
        isWorking = true
        Task { [weak self] in
            guard let self else { return }
            defer { finishWrite() }
            if let failure = await self.sync.publish(current, group: group, previous: previous) {
                self.error = failure.localizedDescription
            }
        }
    }

    private func finishWrite() {
        isWorking = false
        if let records = pendingRecords {
            pendingRecords = nil
            reconcile(records)
        }
    }
}
