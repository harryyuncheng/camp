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

final class BackendContractTests: XCTestCase {
    func testGroupAndLedgerPayloadsDecode() throws {
        let group = """
        {"id":"g_1","name":"CAVA","cuisine":"Mediterranean","symbol":"leaf.fill","people":4,"delivery":"12:30–12:45 PM","arrivalMinutes":750,
         "options":[{"id":"i_1","name":"Greens bowl","detail":"x","symbol":"leaf.fill","priceCents":1881,"baselineCents":2331,"itemPriceCents":1295}],
         "restaurantId":"r_1","participants":5,"savingsCents":1796,"deliveryFeeCents":449,"totalCents":9405,"status":"collecting","seeded":true,
         "members":[{"userId":"u_1","displayName":"Ana","optionId":"i_1"}],"myOptionId":"i_1","userId":"u_me"}
        """
        let g = try JSONDecoder().decode(DemoLunchGroup.self, from: Data(group.utf8))
        XCTAssertEqual(g.options[0].priceCents, 1881)
        XCTAssertEqual(g.deliverySavingsCents, 1796)
        XCTAssertEqual(g.myOptionId, "i_1")
        XCTAssertEqual(g.userId, "u_me")
        // a group written by an older build (no server fields) still decodes, e.g. from a sync record
        let legacy = try JSONDecoder().decode(DemoLunchGroup.self, from: JSONEncoder().encode(
            DemoLunchGroup(id: "x", name: "n", cuisine: "c", symbol: "s", people: 2, delivery: "d", options: g.options)))
        XCTAssertEqual(legacy.deliverySavingsCents, 600)

        let ledger = """
        {"userId":"u_me","month":"2026-09","spentMonthCents":1881,"savedMonthCents":450,"monthlyBudgetCents":40000,
         "entries":[{"id":"o_1","date":"2026-09-20T16:02:11+00:00","office":"HQ","restaurant":"CAVA","item":"Greens bowl","symbol":"leaf.fill",
                     "amountCents":1881,"baselineCents":2331,"status":"confirmed","source":"group"}]}
        """
        let l = try LunchLedgerResponse.decoder.decode(LunchLedgerResponse.self, from: Data(ledger.utf8))
        XCTAssertEqual(l.entries[0].savingsCents, 450)
        XCTAssertEqual(Calendar(identifier: .gregorian).component(.year, from: l.entries[0].date), 2026)
    }
}
