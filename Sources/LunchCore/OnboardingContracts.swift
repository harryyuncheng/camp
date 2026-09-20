import Foundation

/// Wire contracts for `/v1/onboarding` (`backend/src/camp/onboarding.py`): the once-per-person setup, stored in the
/// laptop's database rather than on the device that filled it in, so the Mac and the phone share one answer sheet.
public struct OnboardingRequest: Codable, Equatable {
    public var context: MealContext
    public var settings: CampConfiguration
    public var completed: Bool
    public var device: String

    public init(configuration: CampConfiguration, userId: String?, completed: Bool = true, device: String = CampDevice.current) {
        context = MealContext(configuration: configuration, userId: userId)
        settings = configuration
        self.completed = completed
        self.device = device
    }
}

public struct OnboardingRecord: Codable, Equatable {
    public let userId: String
    public let displayName: String
    public let officeId: String
    public let settings: CampConfiguration?
    public let completed: Bool
    public let completedAt: String?
    public let updatedAt: String?
    public let device: String?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        userId = try c.decode(String.self, forKey: .userId)
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName) ?? ""
        officeId = try c.decodeIfPresent(String.self, forKey: .officeId) ?? ""
        completed = try c.decodeIfPresent(Bool.self, forKey: .completed) ?? false
        completedAt = try c.decodeIfPresent(String.self, forKey: .completedAt)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        device = try c.decodeIfPresent(String.self, forKey: .device)
        // settings is whatever the app that ran onboarding wrote; a blob this build can't read is ignored, not fatal.
        settings = try? c.decodeIfPresent(CampConfiguration.self, forKey: .settings)
    }

    /// Where and when the stored setup came from, e.g. "Harry · iPhone · 2026-09-20".
    public var summary: String {
        [displayName.isEmpty ? nil : displayName, device.map(CampDevice.label), updatedAt.map { String($0.prefix(10)) }]
            .compactMap { $0 }.joined(separator: " · ")
    }
}

public enum CampDevice {
    public static var current: String {
        #if os(macOS)
        return "mac"
        #elseif os(iOS)
        return "iphone"
        #else
        return "unknown"
        #endif
    }
    public static func label(_ device: String) -> String {
        switch device {
        case "mac": return "Mac"
        case "iphone": return "iPhone"
        default: return device.capitalized
        }
    }
}

public extension CampConfiguration {
    /// Adopts another device's onboarding answers. Connection settings stay local: the Mac reaches the backend on
    /// loopback while the phone reaches the same laptop over the cable's network address, so those must not travel.
    func adoptingSharedSetup(from shared: CampConfiguration) -> CampConfiguration {
        var merged = self
        merged.personal = shared.personal
        merged.office = shared.office
        merged.personal.presencePreview = personal.presencePreview
        return merged
    }
}
