import ActivityKit
import SwiftUI

/// Lives in the iPhone app process, including when a LiveActivityIntent executes.
/// The extension renders ActivityKit content and never reads the app's disk store.
@MainActor
final class LunchController: ObservableObject {
    static let shared = LunchController()

    @Published private(set) var session: LunchSession?
    @Published private(set) var isWorking = false
    @Published private(set) var hasLiveActivity = false
    @Published var errorMessage: String?

    private let store = SessionFile.applicationStore(named: "Lunchline")
    private var observation: Task<Void, Never>?

    private init() {
        do { session = try store.load() }
        catch { errorMessage = "Couldn't restore your lunch: \(error.localizedDescription)" }
    }

    private var activity: Activity<LunchAttributes>? {
        Activity<LunchAttributes>.activities.first {
            $0.attributes.sessionID == session?.id &&
            ($0.activityState == .active || $0.activityState == .stale)
        }
    }

    func start() async throws {
        guard !isWorking else { throw LunchError.busy }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            throw ActivitySetupError.disabled
        }
        isWorking = true
        defer { isWorking = false }
        let next = DemoLunch.make()
        // Keep the prototype to one session, including after relaunch.
        for existing in Activity<LunchAttributes>.activities {
            await existing.end(nil, dismissalPolicy: .immediate)
        }
        hasLiveActivity = false
        let created = try Activity.request(
            attributes: LunchAttributes(sessionID: next.id),
            content: content(for: next), pushType: nil
        )
        do { try store.save(next) }
        catch {
            await created.end(nil, dismissalPolicy: .immediate)
            throw error
        }
        session = next
        errorMessage = nil
        observe(created)
    }

    func handle(_ event: LunchEvent, sessionID: String, revision: Int) async throws {
        guard !isWorking else { throw LunchError.busy }
        guard let current = session, current.id.uuidString == sessionID else {
            throw LunchError.missingSession
        }
        isWorking = true
        defer { isWorking = false }
        let next = try current.applying(event, expectedRevision: revision)
        // Persist before publishing. Confirm only records a demo choice: no provider
        // calls or payment side effects belong in this local state transition.
        try store.save(next)
        session = next
        errorMessage = nil
        if let activity {
            if next.isFinished {
                let policy: ActivityUIDismissalPolicy = next.phase == .delivered
                    ? .after(.now.addingTimeInterval(60)) : .immediate
                await activity.end(content(for: next), dismissalPolicy: policy)
                hasLiveActivity = false
            } else {
                await activity.update(content(for: next))
            }
        }
    }

    /// Reattach to the existing activity after launch or return from mirroring.
    /// Persisted state wins if the process stopped between saving and publishing.
    func refresh() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        guard let activity, let session else {
            hasLiveActivity = false
            return
        }
        if session.isFinished {
            await activity.end(content(for: session), dismissalPolicy: .immediate)
            hasLiveActivity = false
        } else {
            await activity.update(content(for: session))
            observe(activity)
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
    case disabled
    var errorDescription: String? {
        "Live Activities are disabled. Enable them for camp in iPhone Settings, then try again."
    }
}
