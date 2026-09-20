import Foundation
import XCTest
import LunchCore
@testable import LunchMac

final class OrderAcknowledgementTests: XCTestCase {
    @MainActor
    func testCravingConfirmationCallsBackendAndKeepsReviewOnFailure() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = SessionFile(url: directory.appendingPathComponent("session.json"))
        let model = MacLunchModel(store: file)
        let result = try JSONDecoder().decode(LunchCravingResult.self, from: Data("""
            {"text":"rice","summary":"Rice","interpretation":"","backend":"keywords","matches":[
              {"restaurant":{"id":"r","name":"Lunch","cuisine":"thai","symbol":"leaf",
                "options":[{"id":"rice","name":"Rice","detail":"","symbol":"leaf","priceCents":725,
                            "baselineCents":900,"deliveryShareCents":125}]},
               "reason":"Rice","score":1}
            ]}
            """.utf8))
        model.cravingResult = result
        model.cravingText = "rice"
        await model.searchCraving()
        model.send(.select("rice"), revision: model.session.revision)
        let previous = model.session
        XCTAssertEqual(previous.phase, .reviewing)
        XCTAssertEqual(previous.selectedOption?.deliveryShareCents, 125)
        let attempted = expectation(description: "backend group creation attempted")
        model.onCravingOrder = { _, _, _, _ in
            attempted.fulfill()
            return nil
        }
        model.send(.confirm, revision: previous.revision)
        await fulfillment(of: [attempted], timeout: 2)
        XCTAssertEqual(model.session, previous)
        XCTAssertEqual(try file.loadRecord()?.session, previous)
        XCTAssertNotNil(model.error)
    }
}
