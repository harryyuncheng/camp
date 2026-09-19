import AppKit
import XCTest
import LunchCore
@testable import LunchMac

final class PanelLifecycleTests: XCTestCase {
    @MainActor
    private func fixture() throws -> (MacLunchModel, NotchPanelController, URL) {
        _ = NSApplication.shared
        guard !NSScreen.screens.isEmpty else { throw XCTSkip("Requires a macOS desktop session") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let model = MacLunchModel(store: SessionFile(url: directory.appendingPathComponent("session.json")))
        return (model, NotchPanelController(model: model), directory)
    }

    @MainActor
    func testSelectionCollapseAndReplacementKeepTheSameHostedViewAndTopEdge() async throws {
        let (model, panel, directory) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        panel.show()
        try await Task.sleep(nanoseconds: 500_000_000)
        let identity = panel.hostedViewIdentifier
        let top = panel.windowFrame.maxY
        let expandedWidth = panel.windowFrame.width
        model.send(.select("green-bowl"), revision: model.session.revision)
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(panel.hostedViewIdentifier, identity)
        XCTAssertEqual(panel.windowFrame.maxY, top, accuracy: 0.5)
        panel.collapse()
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(panel.hostedViewIdentifier, identity)
        XCTAssertLessThan(panel.windowFrame.width, expandedWidth)
        XCTAssertEqual(panel.windowFrame.maxY, top, accuracy: 0.5)
        panel.show()
        model.offer(DemoLunch.make())
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertEqual(panel.hostedViewIdentifier, identity)
        XCTAssertTrue(panel.isExpanded)
        XCTAssertEqual(panel.windowFrame.maxY, top, accuracy: 0.5)
        panel.hide()
        try await Task.sleep(nanoseconds: 400_000_000)
        XCTAssertFalse(panel.windowIsVisible)
    }

    @MainActor
    func testConfirmedLunchRetractsAndExplicitReopenStaysOpen() async throws {
        let (model, panel, directory) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        panel.show()
        try await Task.sleep(nanoseconds: 400_000_000)
        model.send(.select("green-bowl"), revision: model.session.revision)
        model.send(.confirm, revision: model.session.revision)
        try await Task.sleep(nanoseconds: 1_000_000_000)
        XCTAssertTrue(panel.windowIsVisible, "Confirmation must remain readable before retracting")
        try await Task.sleep(nanoseconds: 2_600_000_000)
        XCTAssertFalse(panel.windowIsVisible)
        XCTAssertEqual(model.session.phase, .confirmed)
        panel.show()
        try await Task.sleep(nanoseconds: 3_600_000_000)
        XCTAssertTrue(panel.windowIsVisible, "Explicitly reopening a saved order must not rearm dismissal")
        panel.hide()
        try await Task.sleep(nanoseconds: 400_000_000)
    }

    @MainActor
    func testNewOfferCancelsPendingConfirmationRetraction() async throws {
        let (model, panel, directory) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        panel.show()
        try await Task.sleep(nanoseconds: 400_000_000)
        model.send(.select("green-bowl"), revision: model.session.revision)
        model.send(.confirm, revision: model.session.revision)
        try await Task.sleep(nanoseconds: 500_000_000)
        model.offer(DemoLunch.make())
        try await Task.sleep(nanoseconds: 3_600_000_000)
        XCTAssertTrue(panel.windowIsVisible)
        XCTAssertTrue(panel.isExpanded)
        XCTAssertEqual(model.session.phase, .choosing)
        panel.hide()
        try await Task.sleep(nanoseconds: 400_000_000)
    }
}
