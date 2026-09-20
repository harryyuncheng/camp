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
                        Text("Demo meals, prices, savings, and arrival times. Confirm saves your selection locally; it doesn't place an order.")
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
                    run { try await model.start(group: group, office: settings.draft.office.name) }
                }
                settings.requestConfirmedDemoGroup = { group, meal in
                    showingActivity = true
                    run {
                        try await model.start(group: group, office: settings.draft.office.name)
                        guard let session = model.session else { return }
                        try await model.handle(.select(meal.id), sessionID: session.id.uuidString, revision: session.revision)
                        guard let review = model.session else { return }
                        try await model.handle(.confirm, sessionID: review.id.uuidString, revision: review.revision)
                    }
                }
                settings.requestEndDemoGroup = {
                    guard let session = model.session, !session.isFinished else { return }
                    run { try await model.handle(.end, sessionID: session.id.uuidString, revision: session.revision) }
                }
                await model.refresh()
                syncMembership()
            }
            .onReceive(model.$session) { _ in
                // @Published emits before the property changes; reconcile next turn.
                Task { @MainActor in syncMembership() }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { Task { await model.refresh(); syncMembership() } }
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
        guard let session = model.session, let group = model.group else { return }
        if session.phase == .confirmed || session.phase == .delivered, let option = session.selectedOption {
            if !settings.lunchGroups.contains(where: { $0.id == group.id }) { settings.lunchGroups.append(group) }
            settings.join(option, group: group)
        } else if session.phase == .ended, settings.selectedGroupID == group.id {
            settings.resetGroup()
        }
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
