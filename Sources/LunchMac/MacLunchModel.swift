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
    @Published private(set) var session = DemoLunch.make()
    @Published var error: String?
    @Published var scheduled = false
    private let store: SessionFile
    private var scheduledLunch: Task<Void, Never>?

    init(store: SessionFile = .applicationStore(named: "LunchlineMac")) {
        self.store = store
        do { if let saved = try store.load() { session = saved } }
        catch { self.error = "Could not restore lunch: \(error.localizedDescription)" }
    }

    /// Entry point for a future prediction or notification service. Persist the
    /// offered session, then notify the presentation layer to automatically expand.
    func offer(_ lunch: LunchSession) {
        do {
            try store.save(lunch)
            session = lunch
            error = nil
            NotificationCenter.default.post(name: .lunchReady, object: self)
        } catch { self.error = error.localizedDescription }
    }

    func triggerDemo() {
        scheduledLunch?.cancel()
        scheduled = false
        offer(DemoLunch.make())
    }

    func triggerAfterDelay() {
        scheduledLunch?.cancel()
        scheduled = true
        scheduledLunch = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 5_000_000_000) }
            catch { return }
            guard let self, !Task.isCancelled else { return }
            self.scheduled = false
            self.offer(DemoLunch.make())
        }
    }

    func send(_ event: LunchEvent, revision: Int) {
        do {
            let next = try session.applying(event, expectedRevision: revision)
            try store.save(next)
            session = next
            error = nil
        } catch { self.error = error.localizedDescription }
    }
}
