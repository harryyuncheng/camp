import Foundation
import XCTest
@testable import LunchCore

final class IntegrationContractTests: XCTestCase {
    func testOfferIdentitySurvivesSessionAndSyncSerialization() throws {
        let now = Date()
        let session = LunchSession(office: "HQ", options: DemoLunch.make(now: now).options,
                                   closesAt: now.addingTimeInterval(600), arrivesAt: now.addingTimeInterval(1800),
                                   offerID: "offer-durable")
        let selected = try session.applying(.select(session.options[0].id), at: now)
        let confirmed = try selected.applying(.confirm, at: now)
        let record = LunchSyncRecord(session: confirmed, group: nil, device: "integration")
        let decoded = try JSONDecoder().decode(LunchSyncRecord.self, from: JSONEncoder().encode(record))
        XCTAssertEqual(decoded.session.offerID, "offer-durable")
        XCTAssertEqual(decoded.session.selectedIDs, confirmed.selectedIDs)
        XCTAssertNil(DemoLunch.make(now: now).offerID)
    }

    func testMenuDeliveryShareSurvivesOptionConversion() throws {
        let data = Data("""
            {"id":"side","name":"Side","detail":"","symbol":"leaf","priceCents":725,
             "itemPriceCents":600,"deliveryShareCents":125,"popular":false,"drink":false}
            """.utf8)
        let item = try JSONDecoder().decode(LunchMenuItem.self, from: data)
        XCTAssertEqual(item.option.deliveryShareCents, 125)
        XCTAssertEqual(item.option.priceCents - (item.option.deliveryShareCents ?? 0), 600)
        let legacy = Data("""
            {"id":"main","name":"Main","detail":"","symbol":"leaf","priceCents":1000,"baselineCents":1200}
            """.utf8)
        XCTAssertNil(try JSONDecoder().decode(LunchOption.self, from: legacy).deliveryShareCents)
    }
}
