import Foundation
import XCTest
import LunchUI

final class NotchGeometryTests: XCTestCase {
    func testConfirmationWaitsThreeSeconds() {
        let id = UUID()
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let ticket = ConfirmationRetraction(sessionID: id, revision: 2, now: now)
        XCTAssertFalse(ticket.isDue(sessionID: id, revision: 2, confirmed: true, at: now.addingTimeInterval(2.99)))
        XCTAssertTrue(ticket.isDue(sessionID: id, revision: 2, confirmed: true, at: now.addingTimeInterval(3)))
    }

    func testOldConfirmationCannotHideNewLunchOrLaterState() {
        let id = UUID()
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let ticket = ConfirmationRetraction(sessionID: id, revision: 2, now: now)
        let later = now.addingTimeInterval(10)
        XCTAssertFalse(ticket.isDue(sessionID: UUID(), revision: 2, confirmed: true, at: later))
        XCTAssertFalse(ticket.isDue(sessionID: id, revision: 3, confirmed: true, at: later))
        XCTAssertFalse(ticket.isDue(sessionID: id, revision: 2, confirmed: false, at: later))
    }

    func testPanelJoinsScreenEdgeAboveNotchInBothStates() {
        let screen = CGRect(x: 0, y: 0, width: 1512, height: 982)
        for size in [CGSize(width: 420, height: 360), CGSize(width: 230, height: 64)] {
            let frame = NotchGeometry.frame(size: size, screenFrame: screen,
                                            visibleTop: 950, notchHeight: 32, centerX: 756)
            XCTAssertEqual(frame.maxY, screen.maxY, "The black shell must cover the notch band, not start below it")
            XCTAssertEqual(frame.midX, 756)
        }
    }

    func testExternalScreenOriginAndMenuBarFallback() {
        let screen = CGRect(x: -1920, y: 220, width: 1920, height: 1080)
        let frame = NotchGeometry.frame(size: CGSize(width: 420, height: 320), screenFrame: screen,
                                        visibleTop: 1276, notchHeight: 0, centerX: -960)
        XCTAssertEqual(frame.maxY, 1276)
        XCTAssertEqual(frame.midX, -960)
    }
}
