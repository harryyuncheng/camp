import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import LunchCore

private final class AuditSyncProtocol: URLProtocol {
    static var respond: ((AuditSyncProtocol) -> Void)?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { Self.respond?(self) }
    override func stopLoading() {}

    func reply(_ snapshot: LunchSyncSnapshot, status: Int = 200) {
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONEncoder().encode(snapshot))
        client?.urlProtocolDidFinishLoading(self)
    }
}

@MainActor
final class AuditSyncTests: XCTestCase {
    private func coordinator() -> LunchSyncCoordinator {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [AuditSyncProtocol.self]
        let coordinator = LunchSyncCoordinator(device: "test", session: URLSession(configuration: config))
        coordinator.configure(urlString: "http://localhost:8788", token: nil)
        return coordinator
    }

    func testPublishDeliversAllRecordsAndForgetDeliversEmptySnapshot() async throws {
        let coordinator = coordinator()
        let lunch = DemoLunch.make()
        let other = LunchSyncRecord(session: DemoLunch.make(), group: nil, device: "phone")
        let record = LunchSyncRecord(session: lunch, group: nil, device: "mac")
        var received: [[LunchSyncRecord]] = []
        coordinator.applyAll = { received.append($0) }
        AuditSyncProtocol.respond = { request in
            if request.request.httpMethod == "DELETE" { request.reply(LunchSyncSnapshot(seq: 2, record: nil, records: [])) }
            else { request.reply(LunchSyncSnapshot(seq: 1, record: record, records: [record, other])) }
        }
        let publishError = await coordinator.publish(lunch, group: nil, previous: nil)
        XCTAssertNil(publishError)
        XCTAssertEqual(received, [[record, other]])
        let forgetError = await coordinator.forget(sessionId: record.sessionId)
        XCTAssertNil(forgetError)
        XCTAssertEqual(received.last, [])
    }

    func testConflictDeliversAuthoritativeSnapshotButFailureDoesNot() async throws {
        let coordinator = coordinator()
        let original = DemoLunch.make()
        let authoritative = LunchSyncRecord(session: try original.applying(.select("green-bowl")), group: nil, device: "phone")
        var received: [[LunchSyncRecord]] = []
        coordinator.applyAll = { received.append($0) }
        AuditSyncProtocol.respond = { $0.reply(LunchSyncSnapshot(seq: 4, record: authoritative), status: 409) }
        let conflict = await coordinator.publish(original, group: nil, previous: nil)
        XCTAssertTrue(conflict is LunchSyncConflict)
        XCTAssertEqual(received, [[authoritative]])
        AuditSyncProtocol.respond = { $0.reply(LunchSyncSnapshot(seq: 5, record: nil), status: 500) }
        let failure = await coordinator.publish(original, group: nil, previous: nil)
        XCTAssertNotNil(failure)
        XCTAssertEqual(received, [[authoritative]])
    }

    func testReconfigurationDiscardsInflightCompletionAndResetsCursor() async {
        let coordinator = coordinator()
        let started = expectation(description: "write started")
        var held: AuditSyncProtocol?
        AuditSyncProtocol.respond = { request in held = request; started.fulfill() }
        let write = Task { await coordinator.publish(DemoLunch.make(), group: nil, previous: nil) }
        await fulfillment(of: [started], timeout: 2)
        let overlap = await coordinator.publish(DemoLunch.make(), group: nil, previous: nil)
        XCTAssertEqual(overlap as? LunchError, .busy)
        var received: [[LunchSyncRecord]] = []
        coordinator.applyAll = { received.append($0) }
        coordinator.configure(urlString: "http://localhost:8789", token: "new")
        held?.reply(LunchSyncSnapshot(seq: 99, record: nil))
        let cancelled = await write.value
        XCTAssertTrue(cancelled is CancellationError)
        XCTAssertTrue(received.isEmpty)
        let fetched = expectation(description: "fresh backend fetched")
        AuditSyncProtocol.respond = { request in
            XCTAssertNil(URLComponents(url: request.request.url!, resolvingAgainstBaseURL: false)?.query)
            XCTAssertEqual(request.request.value(forHTTPHeaderField: "X-Camp-Token"), "new")
            fetched.fulfill()
        }
        coordinator.start()
        await fulfillment(of: [fetched], timeout: 2)
        coordinator.stop()
    }

    func testBackendSequenceResetIsDelivered() async {
        let coordinator = coordinator()
        let first = LunchSyncRecord(session: DemoLunch.make(), group: nil, device: "mac")
        let reset = expectation(description: "reset applied")
        var received: [[LunchSyncRecord]] = []
        coordinator.applyAll = {
            received.append($0)
            if received.count == 2 { reset.fulfill() }
        }
        var requests = 0
        AuditSyncProtocol.respond = { request in
            requests += 1
            if requests == 1 { request.reply(LunchSyncSnapshot(seq: 10, record: first)) }
            if requests == 2 {
                XCTAssertTrue(request.request.url!.query!.contains("since=10"))
                request.reply(LunchSyncSnapshot(seq: 1, record: nil))
            }
        }
        coordinator.start()
        await fulfillment(of: [reset], timeout: 2)
        coordinator.stop()
        XCTAssertEqual(received, [[first], []])
    }

    func testLatePollCannotRollBackSuccessfulWrite() async {
        let coordinator = coordinator()
        let polled = expectation(description: "old poll started")
        var held: AuditSyncProtocol?
        let newest = LunchSyncRecord(session: DemoLunch.make(), group: nil, device: "phone")
        AuditSyncProtocol.respond = { request in
            if request.request.httpMethod == "PUT" { request.reply(LunchSyncSnapshot(seq: 8, record: newest)) }
            else if held == nil { held = request; polled.fulfill() }
        }
        var received: [[LunchSyncRecord]] = []
        coordinator.applyAll = { received.append($0) }
        coordinator.start()
        await fulfillment(of: [polled], timeout: 2)
        let error = await coordinator.publish(newest.session, group: nil, previous: nil)
        XCTAssertNil(error)
        let nextPoll = expectation(description: "next poll uses latest cursor")
        AuditSyncProtocol.respond = { request in
            XCTAssertTrue(request.request.url!.query!.contains("since=8"))
            nextPoll.fulfill()
        }
        held?.reply(LunchSyncSnapshot(seq: 2, record: nil))
        await fulfillment(of: [nextPoll], timeout: 2)
        coordinator.stop()
        XCTAssertEqual(received, [[newest]])
    }

    func testNewBackendAndResumeFetchImmediatelyWithoutOldSequence() async {
        let coordinator = coordinator()
        AuditSyncProtocol.respond = { $0.reply(LunchSyncSnapshot(seq: 100, record: nil)) }
        let error = await coordinator.publish(DemoLunch.make(), group: nil, previous: nil)
        XCTAssertNil(error)
        coordinator.configure(urlString: "http://localhost:8789", token: nil)
        let fetched = expectation(description: "new backend applied")
        coordinator.applyAll = { _ in fetched.fulfill() }
        AuditSyncProtocol.respond = { request in
            if request.request.url!.query == nil { request.reply(LunchSyncSnapshot(seq: 1, record: nil)) }
        }
        coordinator.start()
        await fulfillment(of: [fetched], timeout: 2)
        coordinator.stop()
        let resumed = expectation(description: "unchanged snapshot applied on resume")
        coordinator.applyAll = { _ in resumed.fulfill() }
        coordinator.start()
        await fulfillment(of: [resumed], timeout: 2)
        coordinator.stop()
    }

    func testInvalidBackendCannotAcknowledgeWrites() async {
        let coordinator = coordinator()
        coordinator.configure(urlString: "http://public.example", token: nil)
        let publish = await coordinator.publish(DemoLunch.make(), group: nil, previous: nil)
        let forget = await coordinator.forget(sessionId: UUID().uuidString)
        XCTAssertEqual((publish as? URLError)?.code, .badURL)
        XCTAssertEqual((forget as? URLError)?.code, .badURL)
    }
}
