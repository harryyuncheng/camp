import SwiftUI

@main
struct LunchlineApp: App {
    @StateObject private var model = LunchController.shared
    @StateObject private var settings = CampSettingsStore()
    @State private var showingActivity = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            CampWorkspace(store: settings, compact: true) { showingActivity = true }
            .sheet(isPresented: $showingActivity) {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("A little less\nlunch admin.")
                                .font(.system(size: 36, weight: .semibold, design: .rounded))
                            Text("Pick a meal. Get back to your day.")
                                .foregroundStyle(.secondary)
                        }
                        if let session = model.session {
                            LocalLunchCard(session: session) { event in
                                run {
                                    try await model.handle(event, sessionID: session.id.uuidString,
                                                           revision: session.revision)
                                }
                            }.disabled(model.isWorking)
                            Label(model.hasLiveActivity ? "Live Activity is running" : "Live Activity is not running",
                                  systemImage: model.hasLiveActivity ? "dot.radiowaves.left.and.right" : "circle.dashed")
                                .font(.caption).foregroundStyle(.secondary)
                        } else {
                            ContentPlaceholder()
                        }
                        VStack(spacing: 12) {
                            Button { run { try await model.start() } } label: {
                                Text(model.session == nil ? "Start demo lunch" : "Start a new demo lunch")
                                    .frame(maxWidth: .infinity).padding(.vertical, 7)
                            }.buttonStyle(.borderedProminent).tint(LunchStyle.ink)
                            if let session = model.session, !session.isFinished {
                                HStack {
                                    if session.phase == .confirmed {
                                        Button("Simulate arrival") {
                                            run { try await model.handle(.markDelivered, sessionID: session.id.uuidString, revision: session.revision) }
                                        }
                                    }
                                    Spacer()
                                    Button("End lunch", role: .destructive) {
                                        run { try await model.handle(.end, sessionID: session.id.uuidString, revision: session.revision) }
                                    }
                                }.font(.subheadline)
                            }
                        }.disabled(model.isWorking)
                        if let error = model.errorMessage {
                            Label(error, systemImage: "exclamationmark.circle")
                                .font(.callout).foregroundStyle(.red)
                        }
                        Text("Demo meals, prices, savings, and arrival times. Confirm records your selection in camp; no purchase is made.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }.padding(24)
                }
                .background(Color(red: 0.96, green: 0.96, blue: 0.92))
                .navigationTitle("camp").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showingActivity = false } } }
            }
            }
            .task {
                settings.requestDemoGroup = { group in
                    showingActivity = true
                    run { try await model.start(group: group, office: settings.savedOffice.name) }
                }
                settings.requestConfirmedDemoGroup = { group, _ in
                    showingActivity = true
                    run {
                        try await model.presentConfirmed(group, office: settings.savedOffice.name)
                    }
                }
                settings.requestEndDemoGroup = {
                    guard let session = model.session, !session.isFinished else { return }
                    run { try await model.handle(.end, sessionID: session.id.uuidString, revision: session.revision) }
                }
                settings.requestLeftGroup = { groupID in run { try await model.forgetGroup(groupID) } }
                model.onRemoteLunch = { showingActivity = true }
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
                showingActivity = true
                // There is one session in this POC; refresh the current session even
                // if an old, ended activity was used to open the app.
                Task { await model.refresh() }
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

private struct ContentPlaceholder: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "fork.knife.circle.fill").font(.largeTitle)
            Text("Three good options.\nOne quick decision.").font(.title2.weight(.semibold))
            Text("Start a lunch to try the interactive Live Activity.").font(.callout)
        }.foregroundStyle(LunchStyle.lime).padding(24).frame(maxWidth: .infinity, alignment: .leading)
            .background(LunchStyle.ink).clipShape(RoundedRectangle(cornerRadius: 22))
    }
}
