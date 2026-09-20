import SwiftUI
import Combine
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
    #if os(macOS)
    public let location = MacOfficeLocation()
    public let lunchCalendar = MacLunchCalendar()
    #endif
    public var officePresenceLabel: String {
        #if os(macOS)
        return location.presence + " · " + (location.enabled ? "Mac location" : "tracking paused")
        #else
        return "Not connected on iPhone"
        #endif
    }
    public var lunchAvailabilityLabel: String {
        #if os(macOS)
        return lunchCalendar.summary
        #else
        return "Calendar not connected on iPhone"
        #endif
    }
    private var saved = CampConfiguration()
    private let file: ConfigurationFile

    public init(file: ConfigurationFile = .applicationDefault) {
        self.file = file
        do {
            if let config = try file.load() { draft = config; saved = config }
        } catch { saveError = "Couldn’t restore settings. Your existing file has not been replaced. \(error.localizedDescription)" }
        #if os(macOS)
        lunchCalendar.configure(saved.personal, timezone: saved.office.timezone)
        location.configure(saved.office)
        #endif
    }

    public var savedOffice: OfficePolicy { saved.office }
    #if os(macOS)
    @discardableResult
    public func confirmOfficeBoundary(latitude: Double, longitude: Double, radius: Int) -> Bool {
        guard isDemoAdmin else { saveError = "Enable demo admin to change the office."; return false }
        var updated = saved
        updated.office.latitude = latitude
        updated.office.longitude = longitude
        updated.office.radiusMeters = radius
        guard updated.validationErrors.isEmpty else { saveError = updated.validationErrors.joined(separator: "\n"); return false }
        do {
            try file.save(updated)
            saved = updated
            draft.office.latitude = latitude
            draft.office.longitude = longitude
            draft.office.radiusMeters = radius
            location.configure(updated.office)
            location.confirmOffice()
            saveError = nil; statusMessage = "Office location saved"
            return true
        } catch { saveError = "Couldn’t save office: \(error.localizedDescription)"; return false }
    }
    #endif

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
            #if os(macOS)
            lunchCalendar.configure(saved.personal, timezone: saved.office.timezone)
            location.configure(saved.office)
            #endif
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
