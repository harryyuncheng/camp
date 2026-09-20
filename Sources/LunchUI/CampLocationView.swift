import SwiftUI
#if os(macOS)
import MapKit

struct CampLocationView: View {
    @ObservedObject var store: CampSettingsStore
    @ObservedObject private var location: MacOfficeLocation
    @State private var latitude: Double
    @State private var longitude: Double
    @State private var radius: Double
    @State private var placed: Bool
    @State private var focus = UUID()
    @State private var mapActive = false
    @State private var mapReady = false
    @State private var query = ""
    @State private var results: [MKMapItem] = []
    @State private var searching = false
    @State private var message: String?
    @State private var waitingForLocation = false
    @State private var searchTask: Task<Void, Never>?

    init(store: CampSettingsStore) {
        self.store = store
        self.location = store.location
        let office = store.savedOffice
        _latitude = State(initialValue: office.latitude)
        _longitude = State(initialValue: office.longitude)
        _radius = State(initialValue: Double(office.radiusMeters))
        _placed = State(initialValue: store.location.officeConfirmed)
    }
    private var changed: Bool {
        let office = store.savedOffice
        return !location.officeConfirmed || latitude != office.latitude || longitude != office.longitude || Int(radius) != office.radiusMeters
    }
    var body: some View {
        CampCard("Your office", subtitle: "Click the map to place your office circle. Adjust its size, then confirm.") {
            HStack {
                CampTextField(title: "Search an address or place", text: $query).onSubmit { search() }
                Button(searching ? "Searching…" : "Search") { search() }.disabled(searching || query.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            if !results.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(results.enumerated()), id: \.offset) { _, item in
                        Button {
                            place(item.placemark.coordinate); results = []; query = item.name ?? query
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.name ?? "Place").font(.callout.weight(.medium))
                                Text(item.placemark.title ?? "").font(.caption).foregroundStyle(CampPalette.muted)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }.buttonStyle(.plain)
                    }
                }
            }
            Group {
                if mapReady {
                    OfficeBoundaryMap(latitude: latitude, longitude: longitude, radius: radius, placed: placed,
                              userCoordinate: location.mapCoordinate, focus: focus, focusPoint: mapFocusPoint, active: $mapActive, editable: store.isDemoAdmin) { point in place(point, recenter: false) }
                } else {
                    ZStack { CampPalette.background; ProgressView("Loading office map…") }
                }
            }
                .task {
                    // Let navigation commit before initializing MapKit on the main thread.
                    try? await Task.sleep(nanoseconds: 20_000_000)
                    guard !Task.isCancelled else { return }
                    mapReady = true
                }
                .frame(height: 340)
                .overlay(alignment: .topTrailing) {
                    if mapActive {
                        Button("Done with map") { mapActive = false }.buttonStyle(CampActionStyle(primary: false)).padding(10)
                    }
                }
                .overlay(alignment: .bottom) {
                    Text(mapActive ? "Click to place your office · Move the pointer off the map to scroll the page" : "Click to interact with map")
                        .font(.caption.weight(.medium)).padding(9).background(.regularMaterial).clipShape(Capsule()).padding(10).allowsHitTesting(false)
                }
                .clipShape(RoundedRectangle(cornerRadius: 14))
                .accessibilityLabel("Office map. Click to place the office boundary; drag to pan and use plus or minus to zoom.")
            HStack {
                Button { locateMe() } label: { Label(waitingForLocation ? "Locating…" : "Find me", systemImage: "location.fill") }
                    .buttonStyle(CampActionStyle(primary: false))
                Spacer()
                Text("\(Int(radius)) m radius").font(.callout.weight(.semibold)).monospacedDigit()
            }
            Slider(value: $radius, in: 50...5000, step: 25).disabled(!store.isDemoAdmin).accessibilityLabel("Office circle radius in meters")
            HStack {
                Label(location.presence, systemImage: location.presence == "In office" ? "building.2.fill" : "location")
                    .font(.callout)
                Spacer()
                Button(changed ? "Confirm office" : "Office confirmed") {
                    if store.confirmOfficeBoundary(latitude: latitude, longitude: longitude, radius: Int(radius)) {
                        message = "Office saved. Your circle is now active."
                        if !location.enabled { location.enable() }
                    } else { message = store.saveError }
                }.buttonStyle(CampActionStyle()).disabled(!placed || !store.isDemoAdmin || !changed)
            }
            if let message { Text(message).font(.caption).foregroundStyle(CampPalette.muted) }
            DisclosureGroup("Location details") {
                VStack(alignment: .leading, spacing: 10) {
                    Text(location.detail)
                    Text("Permission: \(location.permission)")
                    if let accuracy = location.accuracyMeters { Text("Accuracy: ±\(Int(accuracy)) m") }
                    if let arrival = location.arrivedAt { HStack { Text("Last arrival"); Text(arrival, style: .time) } }
                    HStack {
                        Button(location.enabled ? "Pause tracking" : "Enable location") {
                            if location.enabled { location.disable() } else { location.enable() }
                        }
                        Button("Location settings") { location.openSettings() }
                    }
                    Text("Runs while camp is open and this Mac is awake.")
                }.font(.caption).foregroundStyle(CampPalette.muted).padding(.top, 8)
            }
        }.onChange(of: location.permission) { permission in
            if ["Denied", "Restricted", "Location Services off"].contains(permission) {
                waitingForLocation = false
                message = "Enable camp in Location details → Location settings to see your position."
            }
        }.onChange(of: location.observedAt) { _ in
            if waitingForLocation, let point = location.mapCoordinate {
                mapFocusPoint = point; focus = UUID()
                waitingForLocation = false
                message = "Blue marker is your Mac. Click your office on the map to place its circle."
            }
        }.onDisappear { searchTask?.cancel(); waitingForLocation = false }
    }
    private func place(_ point: CLLocationCoordinate2D, recenter: Bool = true) {
        guard store.isDemoAdmin else { return }
        latitude = point.latitude; longitude = point.longitude; placed = true; message = nil; mapFocusPoint = nil
        waitingForLocation = false
        if recenter { focus = UUID() }
    }
    private func locateMe() {
        if !location.enabled { location.enable() }
        if let point = location.mapCoordinate {
            // Camera and selected boundary must remain separate: finding yourself doesn't move the office.
            mapFocusPoint = point
            focus = UUID()
        } else { waitingForLocation = true; location.refresh(); message = "Allow Location Services to show your position." }
    }
    @State private var mapFocusPoint: CLLocationCoordinate2D?
    private func search() {
        searchTask?.cancel(); searching = true; message = nil
        let request = MKLocalSearch.Request(); request.naturalLanguageQuery = query
        searchTask = Task { @MainActor in
            defer { searching = false }
            do {
                let response = try await MKLocalSearch(request: request).start()
                guard !Task.isCancelled else { return }
                results = Array(response.mapItems.prefix(5))
                if results.isEmpty { message = "No places found. Try a more specific address." }
            } catch { if !Task.isCancelled { message = "Search unavailable. You can still place the circle on the map." } }
        }
    }
}

private struct OfficeBoundaryMap: NSViewRepresentable {
    let latitude: Double
    let longitude: Double
    let radius: Double
    let placed: Bool
    let userCoordinate: CLLocationCoordinate2D?
    let focus: UUID
    var focusPoint: CLLocationCoordinate2D? = nil
    @Binding var active: Bool
    let editable: Bool
    let onPlace: (CLLocationCoordinate2D) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> OfficeMapContainer {
        let container = OfficeMapPool.take()
        let map = container.map
        container.onActivation = { value in context.coordinator.parent.active = value }
        map.delegate = context.coordinator
        map.showsZoomControls = true; map.showsCompass = true
        map.isRotateEnabled = false; map.isPitchEnabled = false
        let click = NSClickGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.clicked(_:)))
        click.numberOfClicksRequired = 1
        container.placementGesture = click
        map.addGestureRecognizer(click)
        return container
    }
    static func dismantleNSView(_ container: OfficeMapContainer, coordinator: Coordinator) {
        container.onActivation = nil
        container.active = false
        container.map.delegate = nil
        if let gesture = container.placementGesture {
            container.map.removeGestureRecognizer(gesture)
            container.placementGesture = nil
        }
        container.map.removeAnnotations(container.map.annotations)
        container.map.removeOverlays(container.map.overlays)
        OfficeMapPool.recycle(container)
    }
    func updateNSView(_ container: OfficeMapContainer, context: Context) {
        let map = container.map
        container.active = active
        let coordinator = context.coordinator; coordinator.parent = self
        if coordinator.focus != focus {
            coordinator.focus = focus
            map.setRegion(MKCoordinateRegion(center: focusPoint ?? CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
                                            latitudinalMeters: max(radius * 5, 1500), longitudinalMeters: max(radius * 5, 1500)), animated: false)
        }
        let signature = "\(latitude)|\(longitude)|\(radius)|\(placed)"
        if coordinator.boundary != signature {
            coordinator.boundary = signature
            map.removeOverlays(map.overlays)
            if placed { map.addOverlay(MKCircle(center: CLLocationCoordinate2D(latitude: latitude, longitude: longitude), radius: radius)) }
        }
        if let point = userCoordinate {
            coordinator.user.coordinate = point
            if !map.annotations.contains(where: { $0 === coordinator.user }) { map.addAnnotation(coordinator.user) }
        } else { map.removeAnnotation(coordinator.user) }
    }
    final class Coordinator: NSObject, MKMapViewDelegate {
        var parent: OfficeBoundaryMap
        var focus: UUID?
        var boundary = ""
        let user = MKPointAnnotation()
        init(_ parent: OfficeBoundaryMap) { self.parent = parent; user.title = "Your Mac" }
        @objc func clicked(_ gesture: NSClickGestureRecognizer) {
            guard parent.editable, let map = gesture.view as? MKMapView else { return }
            let point = gesture.location(in: map)
            // Ignore clicks on MapKit's controls and attribution.
            if let hit = map.hitTest(point), hit is NSControl { return }
            parent.onPlace(map.convert(point, toCoordinateFrom: map))
        }
        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            guard let circle = overlay as? MKCircle else { return MKOverlayRenderer(overlay: overlay) }
            let renderer = MKCircleRenderer(circle: circle)
            renderer.fillColor = NSColor.systemGreen.withAlphaComponent(0.16)
            renderer.strokeColor = NSColor.systemGreen; renderer.lineWidth = 3
            return renderer
        }
        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            guard annotation === user else { return nil }
            let view = MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: "mac-location")
            view.markerTintColor = .systemBlue; view.glyphImage = NSImage(systemSymbolName: "laptopcomputer", accessibilityDescription: "Your Mac")
            view.canShowCallout = true
            return view
        }
    }
}
/// Keep a bounded set of detached maps warm across Office/Connections navigation.
/// A map is returned only after SwiftUI dismantles its previous owner.
private enum OfficeMapPool {
    private static var available: [OfficeMapContainer] = []
    static func take() -> OfficeMapContainer { available.popLast() ?? OfficeMapContainer() }
    static func recycle(_ container: OfficeMapContainer) {
        if available.count < 2 { available.append(container) }
    }
}

/// Inactive maps route wheel events to the page before MapKit can consume them.
private final class OfficeMapContainer: NSView {
    let map = MKMapView()
    var placementGesture: NSClickGestureRecognizer?
    var active = false
    var onActivation: ((Bool) -> Void)?
    private var area: NSTrackingArea?
    override init(frame: NSRect) {
        super.init(frame: frame)
        map.frame = bounds; map.autoresizingMask = [.width, .height]; addSubview(map)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func hitTest(_ point: NSPoint) -> NSView? {
        guard bounds.contains(convert(point, from: superview)) else { return nil }
        return active ? super.hitTest(point) : self
    }
    override func mouseDown(with event: NSEvent) { active = true; onActivation?(true) }
    override func scrollWheel(with event: NSEvent) {
        if let scroll = enclosingScrollView { scroll.scrollWheel(with: event) }
        else { nextResponder?.scrollWheel(with: event) }
    }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let area { removeTrackingArea(area) }
        let next = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect], owner: self)
        addTrackingArea(next); area = next
    }
    override func mouseExited(with event: NSEvent) { active = false; onActivation?(false) }
}

#else
struct CampLocationView: View {
    @ObservedObject var store: CampSettingsStore
    var body: some View {
        CampCard("Office presence") { Text("Set your office on the map in the Mac app.") }
    }
}
#endif
