import Foundation
import XCTest
@testable import LunchCore

/// The orders generalisation: categories decode with a default, snapshots list every active order, and the nearest
/// unfinished order wins.
final class OrdersTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func session(_ category: OrderCategory, arrivesIn minutes: Double, phase: LunchPhase = .choosing) throws -> LunchSession {
        var s = LunchSession(office: "HQ", options: DemoLunch.make(now: now).options, closesAt: now.addingTimeInterval(600),
                             arrivesAt: now.addingTimeInterval(minutes * 60), category: category, place: "Place")
        if phase == .ended { s = try s.applying(.end, at: now) }
        return s
    }

    func testCategoryDefaultsToMealForOlderRecords() throws {
        let legacy = """
        {"id":"7B6E6B3B-0F1E-4C45-9B0E-9A2F0D9F0001","office":"HQ","options":[],"closesAt":0,"arrivesAt":0,"phase":"choosing","revision":0}
        """
        let decoded = try JSONDecoder().decode(LunchSession.self, from: Data(legacy.utf8))
        XCTAssertEqual(decoded.kind, .meal)
        XCTAssertNil(decoded.category)
        let coffee = try session(.coffee, arrivesIn: 30)
        let round = try JSONDecoder().decode(LunchSession.self, from: JSONEncoder().encode(coffee))
        XCTAssertEqual(round.kind, .coffee)
        XCTAssertEqual(round.place, "Place")
        XCTAssertEqual(OrderCategory(wire: "nonsense"), .meal)
        XCTAssertEqual(OrderCategory(wire: nil), .meal)
    }

    func testSnapshotListsAllRecordsAndOlderBackendsStillWork() throws {
        let meal = LunchSyncRecord(session: try session(.meal, arrivesIn: 180), group: nil, device: "mac")
        let coffee = LunchSyncRecord(session: try session(.coffee, arrivesIn: 20), group: nil, device: "iphone")
        let modern = LunchSyncSnapshot(seq: 3, record: coffee, records: [meal, coffee])
        XCTAssertEqual(modern.all.count, 2)
        let legacy = LunchSyncSnapshot(seq: 1, record: meal)
        XCTAssertEqual(legacy.all, [meal])
        XCTAssertTrue(LunchSyncSnapshot(seq: 0, record: nil).all.isEmpty)
        // wire shape without `records` decodes too
        let json = try JSONEncoder().encode(legacy)
        XCTAssertEqual(try JSONDecoder().decode(LunchSyncSnapshot.self, from: json).all.count, 1)
    }

    func testNearestPrefersSoonestUnfinishedOrder() throws {
        let meal = LunchSyncRecord(session: try session(.meal, arrivesIn: 180), group: nil, device: "mac")
        let coffee = LunchSyncRecord(session: try session(.coffee, arrivesIn: 20), group: nil, device: "iphone")
        var done = LunchSyncRecord(session: try session(.coffee, arrivesIn: 5, phase: .ended), group: nil, device: "iphone")
        done.updatedAt = "2026-09-20T09:00:00+00:00"
        XCTAssertEqual([meal, coffee].nearest?.sessionId, coffee.sessionId)
        XCTAssertEqual([meal, done].nearest?.sessionId, meal.sessionId)      // finished orders never win over active ones
        XCTAssertEqual([done].nearest?.sessionId, done.sessionId)            // ...unless nothing else is there
        XCTAssertNil([LunchSyncRecord]().nearest)
    }

    func testMultiItemMembershipDecodesAndFallsBackToTheSingleItemForm() throws {
        let multi = """
        {"id":"g1","name":"Dig","cuisine":"Bowls","symbol":"leaf.fill","people":3,"delivery":"12:30–12:45","options":[],
         "arrivalMinutes":750,"myOptionId":"i_a","myOptionIds":["i_a","i_b"],"budgetCents":2500}
        """
        let group = try JSONDecoder().decode(DemoLunchGroup.self, from: Data(multi.utf8))
        XCTAssertEqual(group.myOptionIdList, ["i_a", "i_b"])
        XCTAssertEqual(group.budgetCents, 2500)
        let legacy = """
        {"id":"g2","name":"Dig","cuisine":"Bowls","symbol":"leaf.fill","people":3,"delivery":"12:30–12:45","options":[],
         "arrivalMinutes":750,"myOptionId":"i_a"}
        """
        XCTAssertEqual(try JSONDecoder().decode(DemoLunchGroup.self, from: Data(legacy.utf8)).myOptionIdList, ["i_a"])
        let none = """
        {"id":"g3","name":"Dig","cuisine":"Bowls","symbol":"leaf.fill","people":3,"delivery":"12:30–12:45","options":[],"arrivalMinutes":750}
        """
        XCTAssertTrue(try JSONDecoder().decode(DemoLunchGroup.self, from: Data(none.utf8)).myOptionIdList.isEmpty)
    }

    func testScheduleLabels() throws {
        let json = """
        {"id":"sch_1","category":"coffee","label":"Morning coffee","timeMinutes":540,"weekdays":[0,1,2,3,4],"active":true}
        """
        let s = try JSONDecoder().decode(LunchSchedule.self, from: Data(json.utf8))
        XCTAssertEqual(s.kind, .coffee)
        XCTAssertEqual(s.weekdayLabel, "Weekdays")
        let mwf = """
        {"id":"sch_2","category":"meal","label":"Lunch","timeMinutes":750,"weekdays":[4,0,2],"active":true}
        """
        XCTAssertEqual(try JSONDecoder().decode(LunchSchedule.self, from: Data(mwf.utf8)).weekdayLabel, "Mon Wed Fri")
        let menu = LunchMenu(restaurantId: "r", name: "Dig", cuisine: "Bowls", rating: 4.42, reviewCount: 1200, top: [], items: [])
        XCTAssertEqual(menu.ratingLabel, "4.4★ · 1200 reviews")
    }
}
