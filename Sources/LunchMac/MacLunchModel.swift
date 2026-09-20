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
    var onJoin: ((LunchOption, DemoLunchGroup) -> Void)?
    func chooseGroup(_ group: DemoLunchGroup) {
        scheduledLunch?.cancel(); scheduled = false
        demoGroup = group; choosingGroup = false
        let now = Date()
        offer(LunchSession(office: officeName, options: group.options,
                           closesAt: now.addingTimeInterval(8 * 60), arrivesAt: group.arrival(on: now),
                           category: group.kind, place: group.name))
    }
    /// Brings one of the waiting orders to the front of the notch.
    func show(_ record: LunchSyncRecord) {
        guard record.session.id != session.id else { return }
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
    /// Shared session through the backend. Every local offer/transition is published; records from the
    /// phone arrive through `applyRemote`. The delegate configures it from the saved connection settings.
    let sync = LunchSyncCoordinator(device: "mac")

    init(store: SessionFile = .applicationStore(named: "LunchlineMac")) {
        self.store = store
        do { if let saved = try store.load() { session = saved } }
        catch { self.error = "Could not restore your order: \(error.localizedDescription)" }
        sync.apply = { [weak self] record in self?.applyRemote(record) }
        sync.applyAll = { [weak self] records in self?.reconcile(records) }
    }

    /// Entry point for a future prediction or notification service. Persist the
    /// offered session, then notify the presentation layer to automatically expand.
    func offer(_ lunch: LunchSession) { offer(lunch, shared: true) }

    /// `shared: false` keeps a lunch on this Mac: the group picker's placeholder session is not a lunch the
    /// phone should show; the phone hears about the real one from `chooseGroup`.
    private func offer(_ lunch: LunchSession, shared: Bool) {
        let previous = session
        do {
            try store.save(lunch)
            session = lunch
            error = nil
            NotificationCenter.default.post(name: .lunchReady, object: self)
        } catch { self.error = error.localizedDescription }
        if shared { publish(previous: previous) }
    }

    func triggerDemo() {
        scheduledLunch?.cancel()
        scheduled = false
        choosingGroup = true; demoGroup = nil
        offer(DemoLunch.make(), shared: false)
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
        let previous = session
        do {
            let next = try session.applying(event, expectedRevision: revision)
            try store.save(next)
            session = next
            didTransition(next)
            error = nil
        } catch { self.error = error.localizedDescription }
        if session.revision != previous.revision { publish(previous: previous) }
    }

    /// A record the phone (or the backend's list) holds. Same order and newer revision → adopt the transition. A
    /// different order → show it when it is nearer than the one on screen (or the screen one is finished),
    /// otherwise keep it waiting in `others`. Echoes of this Mac's own writes have an equal revision and are ignored.
    private func applyRemote(_ record: LunchSyncRecord) {
        let incoming = record.session
        if incoming.id == session.id {
            guard incoming.revision > session.revision else { return }
            do { try store.save(incoming) } catch { self.error = error.localizedDescription }
            session = incoming
            if let group = record.group { demoGroup = group }
            didTransition(incoming)
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
        let ids = Set(records.map(\.sessionId))
        others.removeAll { !ids.contains($0.sessionId) }
        let current = session.id.uuidString
        if !choosingGroup, !ids.contains(current), sync.isConfigured, !session.isFinished, let next = others.nearest {
            others.removeAll { $0.sessionId == next.sessionId }
            adopt(next, announce: true)
        }
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
        do { try store.save(incoming) } catch { self.error = error.localizedDescription }
        demoGroup = record.group
        choosingGroup = false
        session = incoming
        error = nil
        if announce && !incoming.isFinished { NotificationCenter.default.post(name: .lunchReady, object: self) }
        else { onTransition?(incoming) }
    }

    private func didTransition(_ next: LunchSession) {
        if next.phase == .confirmed, let option = next.selectedOption, let group = demoGroup {
            onJoin?(option, group)
        }
        onTransition?(next)
    }

    private func publish(previous: LunchSession) {
        guard sync.isConfigured else { return }
        let current = session, group = demoGroup
        Task { [weak self] in
            guard let self, let failure = await self.sync.publish(current, group: group, previous: previous) else { return }
            if failure is LunchSyncConflict { self.error = failure.localizedDescription }
        }
    }
}
