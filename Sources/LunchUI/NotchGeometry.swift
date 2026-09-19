import Foundation

/// Window placement in AppKit screen coordinates (origin at bottom left).
public enum NotchGeometry {
    public static func frame(size: CGSize, screenFrame: CGRect, visibleTop: CGFloat,
                             notchHeight: CGFloat, centerX: CGFloat) -> CGRect {
        // Cover the camera band's background so the panel is one continuous black
        // silhouette with the hardware notch. Content reserves that band separately.
        let top = notchHeight > 0 ? screenFrame.maxY : visibleTop
        return CGRect(x: centerX - size.width / 2, y: top - size.height,
                      width: size.width, height: size.height)
    }
}

/// A delayed retraction only belongs to the exact confirmation that scheduled it.
/// A replacement lunch or later state must never be hidden by an old timer.
public struct ConfirmationRetraction {
    public let sessionID: UUID
    public let revision: Int
    public let deadline: Date

    public init(sessionID: UUID, revision: Int, now: Date = .now) {
        self.sessionID = sessionID
        self.revision = revision
        self.deadline = now.addingTimeInterval(3)
    }

    public func isDue(sessionID: UUID, revision: Int, confirmed: Bool, at now: Date = .now) -> Bool {
        confirmed && self.sessionID == sessionID && self.revision == revision && now >= deadline
    }
}
