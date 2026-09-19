import AppIntents

// Compiled into BOTH targets so WidgetKit can discover the intent metadata.
// LiveActivityIntent routes execution to the containing app process.
struct SelectLunchIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Select lunch"
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Session") var sessionID: String
    @Parameter(title: "Meal") var optionID: String
    @Parameter(title: "Revision") var revision: Int

    init() {}
    init(session: LunchSession, optionID: String) {
        self.sessionID = session.id.uuidString
        self.optionID = optionID
        self.revision = session.revision
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        try await LunchController.shared.handle(.select(optionID), sessionID: sessionID, revision: revision)
        return .result()
    }
}

struct ConfirmLunchIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Confirm demo lunch"
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Session") var sessionID: String
    @Parameter(title: "Revision") var revision: Int

    init() {}
    init(session: LunchSession) {
        self.sessionID = session.id.uuidString
        self.revision = session.revision
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        try await LunchController.shared.handle(.confirm, sessionID: sessionID, revision: revision)
        return .result()
    }
}

struct ChangeLunchIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Change lunch selection"
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Session") var sessionID: String
    @Parameter(title: "Revision") var revision: Int

    init() {}
    init(session: LunchSession) {
        self.sessionID = session.id.uuidString
        self.revision = session.revision
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        try await LunchController.shared.handle(.changeSelection, sessionID: sessionID, revision: revision)
        return .result()
    }
}
