import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

public enum CampSection: String, CaseIterable, Identifiable {
    case today = "Today", you = "You", office = "Office", connections = "Connections"
    public var id: String { rawValue }
    public var symbol: String {
        switch self {
        case .today: return "square.grid.2x2"
        case .you: return "person.crop.circle"
        case .office: return "building.2"
        case .connections: return "point.3.connected.trianglepath.dotted"
        }
    }
}

@MainActor
public final class CampSettingsStore: ObservableObject {
    @Published public var draft = CampConfiguration()
    @Published public var section = CampSection.today
    @Published public var isDemoAdmin = true
    @Published public var statusMessage: String?
    @Published public var saveError: String?
    @Published public var selectedMeal: LunchOption?
    @Published public var groupStage = DemoGroupStage.collecting
    @Published public var previewConnections: Set<String> = []
    private var saved = CampConfiguration()
    private let file: ConfigurationFile

    public init(file: ConfigurationFile = .applicationDefault) {
        self.file = file
        do {
            if let config = try file.load() { draft = config; saved = config }
        } catch { saveError = "Couldn’t restore settings. Your existing file has not been replaced. \(error.localizedDescription)" }
    }

    public var hasChanges: Bool { draft != saved }
    public var group: DemoGroupSummary { DemoGroupSummary(selectedMeal: selectedMeal, stage: groupStage) }
    public var validationErrors: [String] {
        var errors = draft.validationErrors
        if !isDemoAdmin && draft.office != saved.office { errors.append("Office changes require demo-admin mode. Discard them or enable it before saving.") }
        return errors
    }

    public func save() {
        guard validationErrors.isEmpty else { saveError = validationErrors.joined(separator: "\n"); return }
        do {
            try file.save(draft)
            saved = draft
            saveError = nil
            statusMessage = "Saved on this device"
        } catch { saveError = "Couldn’t save settings: \(error.localizedDescription)" }
    }

    public func discard() { draft = saved; saveError = nil; statusMessage = nil }
    public func resetGroup() { selectedMeal = nil; groupStage = .collecting }
    public func join(_ option: LunchOption) {
        guard groupStage == .collecting else { return }
        selectedMeal = option
    }
}
