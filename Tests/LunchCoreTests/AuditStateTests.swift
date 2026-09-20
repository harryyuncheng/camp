import Foundation
import XCTest
@testable import LunchCore

final class AuditStateTests: XCTestCase {
    func testCartSurvivesTransitionsAndCacheRestart() throws {
        let now = Date()
        var group = DemoLunchGroup(id: "g", name: "Place", cuisine: "Bowls", symbol: "leaf.fill", people: 2,
                                   delivery: "12:30", options: DemoLunch.make(now: now).options)
        let options = Array(group.options.prefix(2))
        group.myOptionId = options[0].id
        group.myOptionIds = options.map(\.id)
        let initial = LunchSession(office: "HQ", options: group.options, closesAt: now.addingTimeInterval(600),
                                   arrivesAt: now.addingTimeInterval(1800))
        let review = try initial.applying(.selectMany(options.map(\.id)), at: now)
        let confirmed = try review.applying(.confirm, at: now)
        XCTAssertEqual(confirmed.selectedOptions, options)
        XCTAssertEqual(confirmed.selectedOption, options.first)
        XCTAssertTrue(try review.applying(.changeSelection, at: now).selectedIDs.isEmpty)
        XCTAssertThrowsError(try initial.applying(.selectMany([options[0].id, options[0].id]), at: now))
        XCTAssertThrowsError(try initial.applying(.selectMany(["missing"]), at: now))
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = SessionFile(url: directory.appendingPathComponent("session.json"))
        try file.save(confirmed, group: group)
        XCTAssertEqual(try file.loadRecord()?.group, group)
        XCTAssertEqual(try file.load(), confirmed)
        try file.clear()
        XCTAssertNil(try file.loadRecord())
    }

    func testLegacySingleSelectionAndSessionEnvelopeStillDecode() throws {
        let chosen = try DemoLunch.make().applying(.select("green-bowl"))
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(chosen)) as? [String: NSObject])
        json.removeValue(forKey: "selectedOptionIDs")
        let legacy = try JSONDecoder().decode(LunchSession.self, from: JSONSerialization.data(withJSONObject: json))
        XCTAssertEqual(legacy.selectedIDs, ["green-bowl"])
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("session.json")
        try JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "session": json]).write(to: url)
        XCTAssertEqual(try SessionFile(url: url).load(), legacy)
        XCTAssertNil(try SessionFile(url: url).loadRecord()?.group)
    }

    func testConnectionValidationRejectsAmbiguousURLs() {
        for invalid in ["http://192.168..2", "http://10.0.0.1#token", "http://user:pass@localhost",
                        "http://10.0.0.1?token=secret", "http://example.com", "http://172.32.0.1"] {
            XCTAssertNil(CampBackendURL.parse(invalid), invalid)
        }
        for valid in ["http://[::1]:8788", "http://192.168.0.2:8788", "http://mac.local:8788",
                      "http://172.20.10.2:8788", "https://example.com/api"] {
            XCTAssertNotNil(CampBackendURL.parse(valid), valid)
        }
    }

    func testConfigurationFilesAreOwnerOnlyIncludingLegacyLoads() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("settings.json")
        let file = ConfigurationFile(url: url)
        var config = CampConfiguration()
        config.connections.recommendationToken = "test-only"
        try file.save(config)
        XCTAssertEqual((try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions]) as? Int, 0o600)
        XCTAssertEqual((try FileManager.default.attributesOfItem(atPath: directory.path)[.posixPermissions]) as? Int, 0o700)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: url.path)
        XCTAssertEqual(try file.load(), config)
        XCTAssertEqual((try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions]) as? Int, 0o600)
    }

    func testExpiredAndMalformedOffersNeverBecomeFreshInvitations() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let iso = ISO8601DateFormatter()
        let option = MealOfferOption(id: "item", name: "Lunch", detail: "", symbol: "fork.knife", priceCents: 1000,
                                     baselineCents: 1500, itemPriceCents: 800, restaurant: "Place", restaurantId: "r",
                                     itemId: "item", pricing: "estimate", score: 1, novel: false, breakdown: [:])
        func offer(_ closes: String, _ arrives: String) -> MealOffer {
            MealOffer(offerId: "o", version: 1, contextVersion: 1, userId: "u", officeId: "hq", groupId: nil,
                      location: "HQ", closesAt: closes, arrivesAt: arrives, options: [option], participants: 2,
                      sharedDeliveryCents: 100, separateDeliveryCents: 200, suggestOnly: true, note: "")
        }
        let future = iso.string(from: now.addingTimeInterval(1800))
        XCTAssertNil(offer("invalid", future).lunchSession(office: "HQ", now: now))
        XCTAssertNil(offer(iso.string(from: now), future).lunchSession(office: "HQ", now: now))
        let deadline = now.addingTimeInterval(600)
        XCTAssertEqual(offer(iso.string(from: deadline), future).lunchSession(office: "HQ", now: now)?.closesAt, deadline)
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        XCTAssertEqual(offer(iso.string(from: deadline), future).lunchSession(office: "HQ", now: now)?.closesAt, deadline)
    }
}
