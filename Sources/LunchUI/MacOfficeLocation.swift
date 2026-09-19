#if os(macOS)
import AppKit
import Combine
import CoreLocation
import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

public extension Notification.Name {
    static let campOfficeArrived = Notification.Name("camp.office.arrived")
    static let campOfficeDeparted = Notification.Name("camp.office.departed")
}

/// Device-local presence. Coordinates are neither uploaded nor written to an activity log.
@MainActor
public final class MacOfficeLocation: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published public private(set) var enabled: Bool
    @Published public private(set) var presence = "Unknown"
    @Published public private(set) var detail = "Enable location to detect this Mac at the office."
    @Published public private(set) var permission = "Not requested"
    @Published public private(set) var distanceMeters: Double?
    @Published public private(set) var accuracyMeters: Double?
    @Published public private(set) var observedAt: Date?
    @Published public private(set) var arrivedAt: Date?
    @Published public private(set) var departedAt: Date?
    @Published public private(set) var officeConfirmed = false
    private let manager = CLLocationManager()
    private var office = OfficePolicy()
    private var latest: CLLocation?
    private var stable: String?
    private var candidate: (state: String, since: Date)?
    private var timer: Timer?
    private var subscriptions = Set<AnyCancellable>()
    private var sleeping = false
    private var lastRefresh = Date.distantPast
    private let enabledKey = "camp.location.enabled.v1"
    private let boundaryKey = "camp.location.confirmed-boundary.v1"

    public override init() {
        enabled = UserDefaults.standard.bool(forKey: "camp.location.enabled.v1")
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.tick() }
        }
        NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.willSleepNotification).sink { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.sleeping = true; self.manager.stopUpdatingLocation()
                self.clear("Mac is asleep; waiting for a fresh reading.")
            }
        }.store(in: &subscriptions)
        NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didWakeNotification).sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.sleeping = false; self?.refresh() }
        }.store(in: &subscriptions)
        NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification).sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.refresh() }
        }.store(in: &subscriptions)
    }

    private var boundarySignature: String {
        "\(office.id)|\(office.latitude)|\(office.longitude)|\(office.radiusMeters)"
    }
    public var canUseCurrentLocation: Bool {
        guard let latest else { return false }
        return Date().timeIntervalSince(latest.timestamp) < 120 && latest.horizontalAccuracy >= 0 && latest.horizontalAccuracy <= 100
    }
    public var currentCoordinate: (latitude: Double, longitude: Double)? {
        guard canUseCurrentLocation, let latest else { return nil }
        return (latest.coordinate.latitude, latest.coordinate.longitude)
    }
    public func configure(_ office: OfficePolicy) {
        let old = boundarySignature
        self.office = office
        officeConfirmed = UserDefaults.standard.string(forKey: boundaryKey) == boundarySignature
        if old != boundarySignature {
            stable = nil; candidate = nil; arrivedAt = nil; departedAt = nil
            presence = "Unknown"; distanceMeters = nil
        }
        if enabled { evaluate(newFix: false) }
    }
    public func confirmOffice() {
        UserDefaults.standard.set(boundarySignature, forKey: boundaryKey)
        officeConfirmed = true; stable = nil; candidate = nil
        evaluate(newFix: false)
    }
    public func enable() {
        enabled = true; UserDefaults.standard.set(true, forKey: enabledKey)
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        refresh()
    }
    public func disable() {
        enabled = false; UserDefaults.standard.set(false, forKey: enabledKey)
        manager.stopUpdatingLocation(); clear("Location tracking is paused.")
    }
    public func openSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices") { NSWorkspace.shared.open(url) }
    }
    public func refresh() {
        guard enabled, !sleeping else { return }
        updateAuthorization()
        guard authorized, CLLocationManager.locationServicesEnabled() else { return }
        manager.stopUpdatingLocation()
        manager.startUpdatingLocation()
        lastRefresh = Date()
        evaluate(newFix: false)
    }
    private var authorized: Bool {
        manager.authorizationStatus == .authorizedAlways
    }
    private func updateAuthorization() {
        guard CLLocationManager.locationServicesEnabled() else {
            permission = "Location Services off"; manager.stopUpdatingLocation()
            clear("Turn on Location Services in System Settings → Privacy & Security."); return
        }
        switch manager.authorizationStatus {
        case .authorizedAlways: permission = "Allowed"
        case .denied: permission = "Denied"; clear("Allow camp in System Settings → Privacy & Security → Location Services.")
        case .restricted: permission = "Restricted"; clear("Location access is restricted on this Mac.")
        case .notDetermined: permission = "Not requested"; clear("Click Enable location, then allow the macOS permission request.")
        @unknown default: permission = "Unavailable"; clear("Location authorization is unavailable.")
        }
        if !authorized { manager.stopUpdatingLocation() }
    }
    nonisolated public func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor [weak self] in self?.authorizationChanged() }
    }
    private func authorizationChanged() {
        updateAuthorization()
        if enabled && authorized && CLLocationManager.locationServicesEnabled() && !sleeping { refresh() }
    }
    nonisolated public func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor [weak self] in self?.receive(locations) }
    }
    private func receive(_ locations: [CLLocation]) {
        guard enabled, !sleeping, authorized,
              let fix = locations.filter({ CLLocationCoordinate2DIsValid($0.coordinate) && $0.horizontalAccuracy >= 0 }).max(by: { $0.timestamp < $1.timestamp }),
              fix.timestamp > (latest?.timestamp ?? .distantPast),
              fix.timestamp.timeIntervalSinceNow <= 5 else { return }
        latest = fix; observedAt = fix.timestamp; accuracyMeters = fix.horizontalAccuracy
        evaluate(newFix: true)
    }
    nonisolated public func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor [weak self] in self?.failed(error) }
    }
    private func failed(_ error: Error) {
        guard enabled else { return }
        if let failure = error as? CLError, failure.code == .denied { updateAuthorization() }
        else { clear("No reliable location yet. Keep Wi-Fi enabled and try Refresh.") }
    }
    private func clear(_ reason: String) {
        latest = nil; stable = nil; candidate = nil
        presence = "Unknown"; detail = reason
        distanceMeters = nil; accuracyMeters = nil; observedAt = nil
    }
    private func tick() {
        guard enabled, !sleeping else { return }
        updateAuthorization()
        guard authorized, CLLocationManager.locationServicesEnabled() else { return }
        evaluate(newFix: false)
        if Date().timeIntervalSince(lastRefresh) >= 60 { refresh() }
    }
    private func evaluate(newFix: Bool) {
        guard enabled, !sleeping else { return }
        guard let fix = latest, Date().timeIntervalSince(fix.timestamp) <= 120 else {
            clear("Waiting for a fresh location. Keep Wi-Fi enabled."); return
        }
        guard officeConfirmed else {
            presence = "Unknown"; detail = "Location is available. Confirm your saved office boundary below."; return
        }
        let distance = fix.distance(from: CLLocation(latitude: office.latitude, longitude: office.longitude))
        distanceMeters = distance
        let radius = Double(office.radiusMeters)
        // A 20m buffer plus the reported error circle avoids toggling at the boundary.
        let classification: String
        if fix.horizontalAccuracy > min(radius, 200) {
            classification = "Unknown"
        } else if distance + fix.horizontalAccuracy <= radius - 20 {
            classification = "In office"
        } else if distance - fix.horizontalAccuracy >= radius + 20 {
            classification = "Away"
        } else { classification = "Unknown" }
        guard classification != "Unknown" else {
            candidate = nil; presence = "Unknown"
            detail = "Reading overlaps the office boundary or is too imprecise. Waiting for a clearer fix."; return
        }
        guard let previous = stable else {
            stable = classification; presence = classification; candidate = nil
            detail = classification == "In office" ? "This Mac is inside the saved office boundary." : "This Mac is outside the saved office boundary."
            return
        }
        if previous == classification {
            presence = classification; candidate = nil
            detail = classification == "In office" ? "This Mac is inside the saved office boundary." : "This Mac is outside the saved office boundary."
            return
        }
        presence = "Unknown"; detail = "Confirming \(classification == "In office" ? "arrival" : "departure") with another location reading…"
        guard newFix else { return }
        if let candidate, candidate.state == classification, fix.timestamp.timeIntervalSince(candidate.since) >= 8 {
            stable = classification; self.candidate = nil; presence = classification
            let now = Date()
            if classification == "In office" { arrivedAt = now; detail = "Arrival detected." }
            else { departedAt = now; detail = "Departure detected." }
            NotificationCenter.default.post(name: classification == "In office" ? .campOfficeArrived : .campOfficeDeparted,
                                            object: self, userInfo: ["officeID": office.id, "observedAt": now])
        } else if candidate == nil { candidate = (classification, fix.timestamp) }
    }
}
#endif
