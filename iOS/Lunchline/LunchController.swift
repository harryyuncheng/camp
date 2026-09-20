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
    /// A lunch started on the Mac just arrived; the shell opens the lunch sheet so it is visible immediately.
    var onRemoteLunch: (() -> Void)?

    private let store = SessionFile.applicationStore(named: "Lunchline")
    private var observation: Task<Void, Never>?
    private var pendingRemote: LunchSyncRecord?

    private init() {
        do { session = try store.load() }
        catch { errorMessage = "Couldn't restore your lunch: \(error.localizedDescription)" }
        sync.apply = { [weak self] record in self?.applyRemote(record) }
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
                         arrivesAt: max($0.arrival(), .now.addingTimeInterval(35 * 60)))
        } ?? DemoLunch.make()
        try await present(next, group: group)
    }

    /// Foreground entry point for a future recommendation/order transport.
    /// The transport must supply a bounded, fresh menu; no payment happens here.
    func present(_ next: LunchSession, group: DemoLunchGroup? = nil) async throws {
        guard !isWorking else { throw LunchError.busy }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            throw ActivitySetupError.disabled
        }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        guard !next.options.isEmpty, next.options.count <= 3,
              next.phase == .choosing, !next.isExpired(),
              Set(next.options.map(\.id)).count == next.options.count,
              group == nil || group?.options == next.options else {
            throw ActivitySetupError.invalidOffer
        }
        let previous = session
        try await replaceActivity(with: next, group: group)
        publish(previous: previous)
    }

    func handle(_ event: LunchEvent, sessionID: String, revision: Int) async throws {
        guard !isWorking else { throw LunchError.busy }
        guard let current = session, current.id.uuidString == sessionID else {
            throw LunchError.missingSession
        }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        group = activity?.attributes.group ?? group
        let next = try current.applying(event, expectedRevision: revision)
        // Persist before publishing. Confirm only records a demo choice: no provider
        // calls or payment side effects belong in this local state transition.
        try store.save(next)
        session = next
        errorMessage = nil
        await pushToActivity(next)
        publish(previous: current)
    }

    /// Reattach to the existing activity after launch or return from mirroring.
    /// Persisted state wins if the process stopped between saving and publishing.
    func refresh() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false; drainPendingRemote() }
        guard let activity, let session else {
            hasLiveActivity = false
            return
        }
        group = activity.attributes.group
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
    private func applyRemote(_ record: LunchSyncRecord) {
        guard !isWorking else { pendingRemote = record; return }
        let incoming = record.session
        if let current = session, current.id == incoming.id {
            guard incoming.revision > current.revision else { return }
            isWorking = true
            Task {
                defer { isWorking = false; drainPendingRemote() }
                do { try store.save(incoming) } catch { errorMessage = error.localizedDescription }
                session = incoming
                if let group = record.group { self.group = group }
                await pushToActivity(incoming)
            }
        } else {
            isWorking = true
            Task {
                defer { isWorking = false; drainPendingRemote() }
                do {
                    if incoming.isFinished || !ActivityAuthorizationInfo().areActivitiesEnabled {
                        // Nothing to put on the Lock Screen; keep the app's view of the lunch current.
                        for existing in Activity<LunchAttributes>.activities { await existing.end(nil, dismissalPolicy: .immediate) }
                        hasLiveActivity = false
                        try store.save(incoming)
                        group = record.group
                        session = incoming
                    } else {
                        try await replaceActivity(with: incoming, group: record.group)
                    }
                    errorMessage = nil
                    if !incoming.isFinished { onRemoteLunch?() }
                } catch { errorMessage = error.localizedDescription }
            }
        }
    }

    private func drainPendingRemote() {
        guard let record = pendingRemote else { return }
        pendingRemote = nil
        applyRemote(record)
    }

    private func publish(previous: LunchSession?) {
        guard sync.isConfigured, let current = session else { return }
        let group = group
        Task { [weak self] in
            guard let self, let failure = await self.sync.publish(current, group: group, previous: previous) else { return }
            if failure is LunchSyncConflict { self.errorMessage = failure.localizedDescription }
        }
    }

    // MARK: ActivityKit

    /// Ends whatever activity exists and starts one for `next` in its current phase. Used both for lunches
    /// started here and for lunches that arrive from the Mac mid-flight.
    private func replaceActivity(with next: LunchSession, group: DemoLunchGroup?) async throws {
        let attributes = LunchAttributes(sessionID: next.id, group: group)
        // ActivityKit limits combined static and dynamic payloads to 4 KB.
        guard try JSONEncoder().encode(attributes).count + JSONEncoder().encode(next).count < 4_000 else {
            throw ActivitySetupError.invalidOffer
        }
        // Keep the prototype to one session, including after relaunch.
        for existing in Activity<LunchAttributes>.activities {
            await existing.end(nil, dismissalPolicy: .immediate)
        }
        hasLiveActivity = false
        let created = try Activity.request(
            attributes: attributes,
            content: content(for: next), pushType: nil
        )
        do { try store.save(next) }
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
        observation = Task { [weak self] in
            for await state in activity.activityStateUpdates {
                guard !Task.isCancelled else { return }
                self?.hasLiveActivity = state == .active || state == .stale
            }
        }
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
