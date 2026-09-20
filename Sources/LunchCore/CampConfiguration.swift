import Foundation

public enum GroupFallback: String, Codable, CaseIterable, Identifiable {
    case ask = "Ask me first", wait = "Wait for the next group", skip = "Skip this order"
    public var id: String { rawValue }
}

public enum FeeSharing: String, Codable, CaseIterable, Identifiable {
    case equal = "Split equally", proportional = "By meal subtotal"
    public var id: String { rawValue }
}

public enum PresencePreview: String, Codable, CaseIterable, Identifiable {
    case unknown = "Not connected", office = "Demo: at the office", away = "Demo: away"
    public var id: String { rawValue }
}

public struct PersonalPreferences: Codable, Equatable {
    public var displayName = "You"
    public var dietaryStyle = "No preference"
    public var allergies = ""
    public var dislikes = ""
    public var lunchStart = 690
    public var lunchEnd = 870
    public var lunchDuration = 30
    public var meetingBuffer = 5
    public var workCalendar = true
    public var personalCalendar = false
    public var holidayCalendar = false
    public var lunchInvitations = true
    public var orderUpdates = true
    public var coffeeInvitations = false
    public var snoozeMinutes = 15
    public var presencePreview = PresencePreview.unknown
    public init() {}
}

public struct OfficePolicy: Codable, Equatable {
    public var id = "demo-office"
    public var name = "HackMIT HQ"
    public var address = ""
    public var latitude = 42.36
    public var longitude = -71.09
    public var radiusMeters = 200
    public var timezone = "America/New_York"
    public var cutoff = 725
    public var deliveryStart = 750
    public var deliveryEnd = 780
    public var personBudgetCents = 2000
    public var groupBudgetCents = 15000
    public var minimumParticipants = 2
    public var minimumSavingsCents = 300
    public var feeSharing = FeeSharing.equal
    public var fallback = GroupFallback.ask
    public var preferExistingGroups = true
    public init() {}
}

public struct ConnectionPreferences: Codable, Equatable {
    public var backendURL = ""
    public var recommendationURL = ""
    /// Sent as X-Camp-Token; required once the backend runs with CAMP_TOKEN set (i.e. whenever it is reachable
    /// from the phone). Optional so settings files saved before this field decode unchanged.
    public var recommendationToken: String?
    public var rampEmployeeReference = ""
    public var orderingProvider = "Mock provider"
    public init() {}
}

public struct CampConfiguration: Codable, Equatable {
    public var schemaVersion = 1
    public var personal = PersonalPreferences()
    public var office = OfficePolicy()
    public var connections = ConnectionPreferences()
    public init() {}

    public var validationErrors: [String] {
        var errors: [String] = []
        if personal.displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            errors.append("Add a name for your profile.")
        }
        if office.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            errors.append("Add an office name.")
        }
        if !(0..<1440).contains(personal.lunchStart) || !(0..<1440).contains(personal.lunchEnd)
            || personal.lunchStart >= personal.lunchEnd {
            errors.append("Your meal window must end after it starts, on the same day.")
        }
        if personal.lunchDuration < 15 || personal.lunchDuration > personal.lunchEnd - personal.lunchStart {
            errors.append("Allow at least 15 minutes to eat within your meal window.")
        }
        if personal.meetingBuffer < 0 || personal.meetingBuffer > 60 { errors.append("Meeting buffer must be between 0 and 60 minutes.") }
        if !office.latitude.isFinite || !(-90...90).contains(office.latitude)
            || !office.longitude.isFinite || !(-180...180).contains(office.longitude) {
            errors.append("Enter a valid office latitude and longitude.")
        }
        if !(50...5000).contains(office.radiusMeters) { errors.append("Office radius must be between 50 and 5,000 meters.") }
        if TimeZone(identifier: office.timezone) == nil { errors.append("Choose a valid office timezone.") }
        if !(0..<1440).contains(office.cutoff) || !(0..<1440).contains(office.deliveryStart)
            || !(0..<1440).contains(office.deliveryEnd)
            || office.cutoff >= office.deliveryStart || office.deliveryStart >= office.deliveryEnd {
            errors.append("Set the cutoff before delivery, and the delivery end after its start.")
        }
        if office.personBudgetCents < 100 || office.groupBudgetCents < office.personBudgetCents
            || office.groupBudgetCents > 1_000_000 {
            errors.append("Budgets must be positive, with the group cap at least the per-person cap (maximum $10,000).")
        }
        if !(2...50).contains(office.minimumParticipants) { errors.append("Choose between 2 and 50 people for a group.") }
        if office.minimumSavingsCents < 0 { errors.append("Minimum savings cannot be negative.") }
        for (label, value) in [("Backend", connections.backendURL), ("Recommendation service", connections.recommendationURL)] {
            if !value.isEmpty, CampBackendURL.parse(value) == nil {
                errors.append("\(label): \(CampBackendURL.requirement)")
            }
        }
        return errors
    }
}

public struct ConfigurationFile {
    public let url: URL
    public init(url: URL) { self.url = url }
    public static var applicationDefault: ConfigurationFile {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return ConfigurationFile(url: base.appendingPathComponent("Camp/settings.json"))
    }
    public func load() throws -> CampConfiguration? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        let config = try JSONDecoder().decode(CampConfiguration.self, from: Data(contentsOf: url))
        guard config.schemaVersion == 1, config.validationErrors.isEmpty else { throw CocoaError(.coderReadCorrupt) }
        return config
    }
    public func save(_ config: CampConfiguration) throws {
        guard config.validationErrors.isEmpty else { throw CocoaError(.coderInvalidValue) }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: url.deletingLastPathComponent().path)
        try JSONEncoder().encode(config).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}

public enum DemoGroupStage: String, CaseIterable, Identifiable {
    case collecting = "Collecting", placed = "Placed", delivered = "Delivered"
    public var id: String { rawValue }
}
