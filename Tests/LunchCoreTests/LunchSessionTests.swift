import Foundation
import XCTest
@testable import LunchCore

final class LunchSessionTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    func testSelectionConfirmationAndArrival() throws {
        let initial = DemoLunch.make(now: now)
        let selected = try initial.applying(.select("green-bowl"), at: now, expectedRevision: 0)
        XCTAssertEqual(selected.phase, .reviewing)
        XCTAssertEqual(selected.selectedOption?.priceCents, 1140)
        let confirmed = try selected.applying(.confirm, at: now, expectedRevision: 1)
        XCTAssertEqual(confirmed.phase, .confirmed)
        XCTAssertEqual(confirmed.selectedOption?.savingsCents, 340)
        let delivered = try confirmed.applying(.markDelivered, at: now.addingTimeInterval(3600))
        XCTAssertEqual(delivered.phase, .delivered)
        XCTAssertEqual(delivered.revision, 3)
    }

    func testCannotConfirmWithoutChoosing() {
        XCTAssertThrowsError(try DemoLunch.make(now: now).applying(.confirm, at: now)) {
            XCTAssertEqual($0 as? LunchError, .invalidTransition)
        }
    }

    func testCutoffRejectsSelectionAndConfirmationAtBoundary() throws {
        let initial = DemoLunch.make(now: now)
        let selected = try initial.applying(.select("green-bowl"), at: now)
        for (state, event) in [(initial, LunchEvent.select("green-bowl")), (selected, .confirm)] {
            XCTAssertThrowsError(try state.applying(event, at: initial.closesAt)) {
                XCTAssertEqual($0 as? LunchError, .expired)
            }
        }
    }

    func testLateConfirmCannotConfirmAChangedMeal() throws {
        let selected = try DemoLunch.make(now: now).applying(.select("green-bowl"), at: now)
        let changed = try selected.applying(.select("pesto-melt"), at: now)
        XCTAssertThrowsError(try changed.applying(.confirm, at: now, expectedRevision: selected.revision)) {
            XCTAssertEqual($0 as? LunchError, .staleAction)
        }
        XCTAssertEqual(changed.selectedOptionID, "pesto-melt")
    }

    func testDoubleConfirmAndChangesAfterConfirmationAreRejected() throws {
        let confirmed = try DemoLunch.make(now: now).applying(.select("green-bowl"), at: now).applying(.confirm, at: now)
        for event in [LunchEvent.confirm, .changeSelection, .select("pesto-melt")] {
            XCTAssertThrowsError(try confirmed.applying(event, at: now)) {
                XCTAssertEqual($0 as? LunchError, .invalidTransition)
            }
        }
        XCTAssertFalse(confirmed.isExpired(at: now.addingTimeInterval(3600)))
    }

    func testUnknownOptionRejectedAndChangeClearsChoice() throws {
        let initial = DemoLunch.make(now: now)
        XCTAssertThrowsError(try initial.applying(.select("missing"), at: now)) {
            XCTAssertEqual($0 as? LunchError, .unknownOption)
        }
        let changed = try initial.applying(.select("green-bowl"), at: now).applying(.changeSelection, at: now)
        XCTAssertEqual(changed.phase, .choosing)
        XCTAssertNil(changed.selectedOptionID)
    }

    func testExpiredSessionCanStillBeEnded() throws {
        let initial = DemoLunch.make(now: now)
        let ended = try initial.applying(.end, at: initial.closesAt)
        XCTAssertTrue(ended.isFinished)
        XCTAssertThrowsError(try ended.applying(.select("green-bowl"), at: now))
    }

    func testActivityPayloadLeavesRoomBelowFourKilobytes() throws {
        let state = try DemoLunch.make(now: now).applying(.select("green-bowl"), at: now)
        let data = try JSONEncoder().encode(state)
        XCTAssertLessThan(data.count, 3000, "Leave room for ActivityAttributes within the 4 KB budget")
        XCTAssertEqual(try JSONDecoder().decode(LunchSession.self, from: data), state)
    }

    func testSessionSurvivesRelaunchAndCorruptionIsNotSilentlyIgnored() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("session.json")
        let store = SessionFile(url: url)
        XCTAssertNil(try store.load())
        let state = try DemoLunch.make(now: now).applying(.select("green-bowl"), at: now).applying(.confirm, at: now)
        try store.save(state)
        XCTAssertEqual(try SessionFile(url: url).load(), state)
        try Data("invalid".utf8).write(to: url)
        XCTAssertThrowsError(try store.load())
    }
}

final class LunchLedgerTests: XCTestCase {
    func testConfirmedLunchIsRecordedOnceAndUpdatedOnDelivery() throws {
        var session = DemoLunch.make()
        XCTAssertNil(LunchLedger.applying(session, to: [], restaurant: "Demo", source: "demo"))   // nothing before confirm
        session = try session.applying(.select("green-bowl"))
        session = try session.applying(.confirm)
        let confirmed = try XCTUnwrap(LunchLedger.applying(session, to: [], restaurant: "The Green Table", source: "demo"))
        XCTAssertEqual(confirmed.count, 1)
        XCTAssertEqual(confirmed[0].restaurant, "The Green Table")
        XCTAssertEqual(confirmed[0].amountCents, 1140)
        XCTAssertEqual(confirmed[0].status, "confirmed")
        session = try session.applying(.markDelivered)
        let delivered = try XCTUnwrap(LunchLedger.applying(session, to: confirmed, restaurant: "The Green Table", source: "demo"))
        XCTAssertEqual(delivered.count, 1)
        XCTAssertEqual(delivered[0].status, "delivered")
        XCTAssertEqual(LunchLedger.spentCents(delivered), 1140)
    }
}
