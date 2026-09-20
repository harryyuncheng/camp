import ActivityKit
import SwiftUI

/// Lives in the iPhone app process, including when a LiveActivityIntent executes.
/// The extension renders ActivityKit content and never reads the app's disk store.
@MainActor
final class LunchController: ObservableObject {
    static let shared = LunchController()

    @Published private(set) var group: DemoLunchGroup?
    @Published private(set) var session: LunchSession?
    @Published private(set) var isWorking = false
    @Published private(set) var hasLiveActivity = false
    @Published var errorMessage: String?

    /// Shared session through the backend: local offers/transitions are published, and the Mac's arrive
    /// through `applyRemote`. The app shell configures it from saved settings and runs it while foregrounded.
    let sync = LunchSyncCoordinator(device: "iphone")
    var onRemoteLunch: (() -> Void)?
    var onRecords: (([LunchSyncRecord]) -> Void)?
    var onConfirm: (([LunchOption], DemoLunchGroup) async throws -> DemoLunchGroup)?

    private let store = SessionFile.applicationStore(named: "Lunchline")
    private var observation: Task<Void, Never>?
    private var pushToStartWatch: Task<Void, Never>?
    /// Update-token observers keyed by activity id: one per activity on the phone, including ones a
    /// push-to-start raised while camp was closed.
    private var pushWatchers: [String: Task<Void, Never>] = [:]
    private var pendingRemote: [LunchSyncRecord]?
    private var records: [LunchSyncRecord] = []

    private init() {
        do { let cached = try store.loadRecord(); session = cached?.session; group = cached?.group }
        catch { errorMessage = "Couldn't restore your lunch: \(error.localizedDescription)" }
        do {
            let configuration = try ConfigurationFile.applicationDefault.load() ?? CampConfiguration()
            sync.configure(urlString: configuration.connections.recommendationURL, token: configuration.connections.recommendationToken)
        } catch { errorMessage = "Couldn't load your connection settings: \(error.localizedDescription)" }
        sync.applyAll = { [weak self] records in self?.applySnapshot(records) }
        startPushBridge()
    }

    private var activity: Activity<LunchAttributes>? {
        Activity<LunchAttributes>.activities.first {
            $0.attributes.sessionID == session?.id &&
            ($0.activityState == .active || $0.activityState == .stale)
        }
    }

    func start(group: DemoLunchGroup? = nil, office: String = "HackMIT HQ") async throws {
        let next = group.map {
            LunchSession(office: office, options: $0.options,
                         closesAt: .now.addingTimeInterval(8 * 60),
                         arrivesAt: $0.arrival(), category: $0.kind, place: $0.name)
        } ?? DemoLunch.make()
        try await present(next, group: group)
    }

    /// Foreground entry point for a future recommendation/order transport.
    /// The transport must supply a bounded, fresh menu; no payment happens here.
    func present(_ next: LunchSession, group: DemoLunchGroup? = nil) async throws {
        guard !isWorking else { throw LunchError.busy }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        guard !next.options.isEmpty,
              next.phase == .choosing, !next.isExpired(),
              Set(next.options.map(\.id)).count == next.options.count,
              group == nil || group?.options == next.options else {
            throw ActivitySetupError.invalidOffer
        }
        let previous = session
        if let failure = await sync.publish(next, group: group, previous: previous) { throw failure }
        try await display(next, group: group)
    }

    func presentConfirmed(_ group: DemoLunchGroup, office: String) async throws {
        guard !isWorking else { throw LunchError.busy }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        let now = Date()
        let initial = LunchSession(office: office, options: group.options, closesAt: now.addingTimeInterval(8 * 60),
                                   arrivesAt: group.arrival(on: now), category: group.kind, place: group.name)
        let selected = try initial.applying(.selectMany(group.myOptionIdList), at: now)
        let confirmed = try selected.applying(.confirm, at: now)
        if let failure = await sync.publish(confirmed, group: group, previous: session) { throw failure }
        try await display(confirmed, group: group)
    }

    func forgetGroup(_ groupID: String) async throws {
        guard !isWorking else { throw LunchError.busy }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        var ids = Set(records.filter { $0.group?.id == groupID }.map(\.sessionId))
        if group?.id == groupID, let session { ids.insert(session.id.uuidString) }
        for id in ids {
            if let failure = await sync.forget(sessionId: id) { throw failure }
        }
    }

    /// Deletes one shared order everywhere (backend list, both devices' cards, this Live Activity).
    func forgetSession(_ sessionID: String) async throws {
        guard !isWorking else { throw LunchError.busy }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        if let failure = await sync.forget(sessionId: sessionID) { throw failure }
    }

    func handle(_ event: LunchEvent, sessionID: String, revision: Int) async throws {
        guard !isWorking else { throw LunchError.busy }
        guard let current = session, current.id.uuidString == sessionID else {
            throw LunchError.missingSession
        }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        let next = try current.applying(event, expectedRevision: revision)
        if next.phase == .confirmed, current.phase != .confirmed, let group {
            if let onConfirm {
                self.group = try await onConfirm(next.selectedOptions, group)
            } else {
                let configuration = try ConfigurationFile.applicationDefault.load() ?? CampConfiguration()
                let client = try RecommendationClient(urlString: configuration.connections.recommendationURL,
                                                       token: configuration.connections.recommendationToken)
                self.group = try await client.joinGroup(group.id, office: OfficeRef(policy: configuration.office),
                                                        optionIds: next.selectedIDs,
                                                        userId: UserDefaults.standard.string(forKey: "camp.recommender.userID"),
                                                        displayName: configuration.personal.displayName)
                if let userID = self.group?.userId { UserDefaults.standard.set(userID, forKey: "camp.recommender.userID") }
            }
        }
        if let offerID = next.offerID {
            let lifecycle: String?
            switch next.phase {
            case .confirmed: lifecycle = "confirmed"
            case .delivered: lifecycle = "delivered"
            case .ended: lifecycle = "ended"
            default: lifecycle = nil
            }
            if let lifecycle {
                let configuration = try ConfigurationFile.applicationDefault.load() ?? CampConfiguration()
                let client = try RecommendationClient(urlString: configuration.connections.recommendationURL,
                                                       token: configuration.connections.recommendationToken)
                _ = try await client.lunchEvent(offerId: offerID, optionId: next.selectedOptionID, event: lifecycle)
            }
        }
        if let failure = await sync.publish(next, group: group, previous: current) { throw failure }
        try store.save(next, group: group)
        session = next
        errorMessage = nil
        await pushToActivity(next)
    }

    /// Reattach to the existing activity after launch or return from mirroring.
    /// Persisted state wins if the process stopped between saving and publishing.
    func refresh() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        startPushBridge()
        guard let activity, let session else {
            hasLiveActivity = false
            return
        }
        if group == nil { group = activity.attributes.group }
        if session.isFinished {
            await activity.end(content(for: session), dismissalPolicy: .immediate)
            hasLiveActivity = false
        } else {
            await activity.update(content(for: session))
            observe(activity)
        }
    }

    // MARK: sync

    /// A record the Mac published. Same lunch and newer revision → adopt the transition and update the
    /// Live Activity; a different lunch → replace the activity as if it had been started here. Echoes of
    /// this phone's own writes have an equal revision and are ignored. While a local command is still
    /// finishing, the record waits and is applied right after.
    private func applySnapshot(_ records: [LunchSyncRecord]) {
        guard !isWorking else { pendingRemote = records; return }
        self.records = records
        onRecords?(records)
        guard let record = records.nearest else {
            isWorking = true
            Task {
                defer { isWorking = false; drainPendingRemote() }
                for existing in Activity<LunchAttributes>.activities { await existing.end(nil, dismissalPolicy: .immediate) }
                hasLiveActivity = false
                session = nil
                group = nil
                do { try store.clear() } catch { errorMessage = error.localizedDescription }
            }
            return
        }
        applyRemote(record)
    }

    private func applyRemote(_ record: LunchSyncRecord) {
        let incoming = record.session
        if let current = session, current.id == incoming.id {
            guard incoming != current || record.group != group else { return }
            isWorking = true
            Task {
                defer { isWorking = false; drainPendingRemote() }
                do { try store.save(incoming, group: record.group) } catch { errorMessage = error.localizedDescription }
                session = incoming
                self.group = record.group
                await pushToActivity(incoming)
            }
        } else {
            isWorking = true
            Task {
                defer { isWorking = false; drainPendingRemote() }
                do {
                    try await display(incoming, group: record.group)
                    if !incoming.isFinished { onRemoteLunch?() }
                } catch { errorMessage = error.localizedDescription }
            }
        }
    }

    private func drainPendingRemote() {
        guard let records = pendingRemote else { return }
        pendingRemote = nil
        applySnapshot(records)
    }

    private func display(_ next: LunchSession, group: DemoLunchGroup?) async throws {
        try store.save(next, group: group)
        self.session = next
        self.group = group
        errorMessage = nil
        if next.isFinished || !ActivityAuthorizationInfo().areActivitiesEnabled {
            for existing in Activity<LunchAttributes>.activities { await existing.end(nil, dismissalPolicy: .immediate) }
            hasLiveActivity = false
            errorMessage = next.isFinished ? nil : "Order synced. Live Activities are disabled in iPhone Settings."
        } else {
            do { try await replaceActivity(with: next, group: group) }
            catch { errorMessage = "Order synced; Live Activity unavailable: \(error.localizedDescription)" }
        }
    }

    // MARK: ActivityKit

    /// Ends whatever activity exists and starts one for `next` in its current phase. Used both for lunches
    /// started here and for lunches that arrive from the Mac mid-flight.
    private func replaceActivity(with next: LunchSession, group: DemoLunchGroup?) async throws {
        let attributes = LunchAttributes(sessionID: next.id, group: nil)
        // ActivityKit limits combined static and dynamic payloads to 4 KB.
        guard try JSONEncoder().encode(attributes).count + JSONEncoder().encode(next).count < 4_000 else {
            throw ActivitySetupError.invalidOffer
        }
        // Keep the prototype to one session, including after relaunch.
        for existing in Activity<LunchAttributes>.activities {
            await existing.end(nil, dismissalPolicy: .immediate)
        }
        hasLiveActivity = false
        // `.token` makes ActivityKit mint an APNs token, which is what lets a Mac-side change reach this
        // activity while camp is backgrounded or the phone is locked (the long-poll in `sync` is stopped
        // there). A tokenized request without the `aps-environment` entitlement fails outright, so a
        // push-enabled build that isn't signed for it still gets the activity, just without push.
        // See `pushToUpdateEnabled`.
        let created: Activity<LunchAttributes>
        do {
            created = try Activity.request(
                attributes: attributes,
                content: content(for: next), pushType: Self.pushToUpdateEnabled ? .token : nil
            )
        } catch {
            guard Self.pushToUpdateEnabled else { throw error }
            created = try Activity.request(attributes: attributes, content: content(for: next), pushType: nil)
        }
        do { try store.save(next, group: group) }
        catch {
            await created.end(nil, dismissalPolicy: .immediate)
            throw error
        }
        self.group = group
        session = next
        errorMessage = nil
        observe(created)
    }

    private func pushToActivity(_ next: LunchSession) async {
        guard let activity else { return }
        if next.isFinished {
            let policy: ActivityUIDismissalPolicy = next.phase == .delivered
                ? .after(.now.addingTimeInterval(60)) : .immediate
            await activity.end(content(for: next), dismissalPolicy: policy)
            hasLiveActivity = false
        } else {
            await activity.update(content(for: next))
        }
    }

    private func content(for session: LunchSession) -> ActivityContent<LunchSession> {
        let staleDate = (session.phase == .choosing || session.phase == .reviewing)
            ? session.closesAt : nil
        return ActivityContent(state: session, staleDate: staleDate)
    }

    private func observe(_ activity: Activity<LunchAttributes>) {
        observation?.cancel()
        hasLiveActivity = activity.activityState == .active || activity.activityState == .stale
        let sessionID = activity.attributes.sessionID.uuidString
        observation = Task { [weak self] in
            for await state in activity.activityStateUpdates {
                guard !Task.isCancelled else { return }
                self?.hasLiveActivity = state == .active || state == .stale
                if state == .ended || state == .dismissed {
                    await self?.sync.dropPushToken(sessionId: sessionID)
                }
            }
        }
        observePushToken(of: activity)
    }

    /// Both halves of the push bridge. Without `CAMP_PUSH` there is nothing to register, so this stays
    /// off; the foreground long-poll in `sync` is unaffected by the flag.
    private func startPushBridge() {
        guard Self.pushToUpdateEnabled else { return }
        // The push-to-start token lets the backend raise a Live Activity for a Mac-side order while camp
        // is closed entirely. iOS can rotate it, so the sequence stays open for the app's life.
        if pushToStartWatch == nil, #available(iOS 17.2, *) {
            pushToStartWatch = Task { [weak self] in
                for await data in Activity<LunchAttributes>.pushToStartTokenUpdates {
                    guard !Task.isCancelled else { return }
                    await self?.sync.registerStartToken(Self.hex(data), environment: Self.apnsEnvironment)
                }
            }
        }
        // Any activity already alive — e.g. one a push started while the app was closed — relays its own
        // update token so later Mac writes reach it without opening camp.
        for activity in Activity<LunchAttributes>.activities { observePushToken(of: activity) }
    }

    /// Relays one activity's push token to the backend. iOS delivers the token asynchronously and can
    /// rotate it at any time, so the sequence stays open for the life of the activity rather than reading
    /// a token once. Without `pushType: .token` at request time there is no token to receive.
    private func observePushToken(of activity: Activity<LunchAttributes>) {
        guard Self.pushToUpdateEnabled, pushWatchers[activity.id] == nil else { return }
        let sessionID = activity.attributes.sessionID.uuidString
        pushWatchers[activity.id] = Task { [weak self] in
            for await data in activity.pushTokenUpdates {
                guard !Task.isCancelled else { return }
                await self?.sync.registerPushToken(Self.hex(data), sessionId: sessionID,
                                                   environment: Self.apnsEnvironment)
            }
        }
    }

    private static func hex(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
    }

    /// Live Activity push (both update and push-to-start). The backend half is always on (`camp.apns`);
    /// the phone side compiles in under CAMP_PUSH because it needs the Push Notifications capability,
    /// which requires a *paid* Apple Developer membership. Setting `CAMP_PUSH_ENTITLEMENTS` and the flag
    /// in `Config/Local.xcconfig` wires both; without them the phone syncs by long-poll while foregrounded.
    #if CAMP_PUSH
    static let pushToUpdateEnabled = true
    #else
    static let pushToUpdateEnabled = false
    #endif

    /// A development build's push token is only valid against APNs sandbox; a TestFlight/App Store build
    /// needs production. DEBUG is the signal available without an entitlement read.
    private static var apnsEnvironment: String {
        #if DEBUG
        return "sandbox"
        #else
        return "production"
        #endif
    }
}

private enum ActivitySetupError: LocalizedError {
    case disabled, invalidOffer
    var errorDescription: String? {
        switch self {
        case .disabled: return "Live Activities are disabled. Enable them for camp in iPhone Settings, then try again."
        case .invalidOffer: return "This lunch invitation is unavailable. Try a fresh menu with up to three meals."
        }
    }
}
