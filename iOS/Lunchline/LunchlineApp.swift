import SwiftUI

@main
struct LunchlineApp: App {
    @StateObject private var model = LunchController.shared
    @StateObject private var settings = CampSettingsStore()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            CampWorkspace(store: settings, compact: true, activityError: model.errorMessage)
            .task {
                settings.requestDemoGroup = { group in
                    settings.section = .today
                    run { try await model.start(group: group, office: settings.savedOffice.name) }
                }
                settings.requestConfirmedDemoGroup = { group, _ in
                    settings.section = .today
                    run {
                        try await model.presentConfirmed(group, office: settings.savedOffice.name)
                    }
                }
                settings.requestEndDemoGroup = {
                    guard let session = model.session, !session.isFinished else { return }
                    run { try await model.handle(.end, sessionID: session.id.uuidString, revision: session.revision) }
                }
                settings.requestLeftGroup = { groupID in run { try await model.forgetGroup(groupID) } }
                model.onRemoteLunch = { settings.section = .today }
                model.onConfirm = { options, group in try await settings.joinConfirmed(options, group: group) }
                model.sync.onStatus = { status in settings.syncStatus = status }
                settings.onConnectionsChanged = { connections in
                    model.sync.configure(urlString: connections.recommendationURL, token: connections.recommendationToken)
                    if scenePhase == .active { model.sync.start() }
                }
                await model.refresh()
                await settings.refreshAll()
                syncMembership()
            }
            .onReceive(model.$session) { _ in
                // @Published emits before the property changes; reconcile next turn.
                Task { @MainActor in syncMembership() }
            }
            .onChange(of: scenePhase) { _, phase in
                // The long-poll only runs while the app is on screen; iOS suspends it otherwise, and the
                // first fetch after returning catches up on anything the Mac did meanwhile.
                if phase == .active { model.sync.start(); Task { await model.refresh(); syncMembership() } }
                else { model.sync.stop() }
            }
            .onOpenURL { url in
                guard ["camp", "lunchline"].contains(url.scheme ?? ""), url.host == "lunch" else { return }
                settings.section = .today
                // There is one session in this POC; refresh the current session even
                // if an old, ended activity was used to open the app.
                Task { await model.refresh(); syncMembership() }
            }
        }
    }

    private func syncMembership() {
        Task { await settings.refreshGroups(); await settings.refreshLedger() }
    }

    private func run(_ action: @escaping @MainActor () async throws -> Void) {
        Task {
            do { try await action() }
            catch { model.errorMessage = error.localizedDescription }
        }
    }
}
