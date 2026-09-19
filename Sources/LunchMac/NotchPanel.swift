import AppKit
import Combine
import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
import LunchUI
#endif

final class LunchPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect { frameRect }
}

private enum PanelMode { case expanded, compact, hidden }

/// One mounted SwiftUI tree. Only its pose changes during a transition.
@MainActor
private final class PanelMotion: ObservableObject {
    @Published var size = CGSize(width: 238, height: 1)
    @Published var notchHeight: CGFloat = 0
    @Published var mode = PanelMode.hidden
    @Published var alpha: Double = 0
    var radius: CGFloat { mode == .expanded ? 25 : 14 }
}

@MainActor
final class NotchPanelController {
    private let panel: LunchPanel
    private let model: MacLunchModel
    private let motion = PanelMotion()
    private var cancellables = Set<AnyCancellable>()
    private var screen: NSScreen?
    private var visible = false
    private var generation = 0
    private var expandedHeight: CGFloat = 320
    private var completion: Task<Void, Never>?
    private var confirmationRetraction: Task<Void, Never>?
    private var lastSession: LunchSession

    var isExpanded: Bool { visible && motion.mode == .expanded }

    #if DEBUG
    // Read-only lifecycle inspection for AppKit regression tests.
    var hostedViewIdentifier: ObjectIdentifier? { panel.contentView.map(ObjectIdentifier.init) }
    var windowFrame: CGRect { panel.frame }
    var windowIsVisible: Bool { panel.isVisible }
    #endif

    init(model: MacLunchModel) {
        self.model = model
        self.lastSession = model.session
        panel = LunchPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel],
                           backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.animationBehavior = .none
        panel.isMovable = false
        panel.setAccessibilityLabel("camp lunch choices")

        let host = NSHostingView(rootView: NotchContent(
            model: model, motion: motion,
            expand: { [weak self] in self?.show() },
            collapse: { [weak self] in self?.collapse() },
            hide: { [weak self] in self?.hide() },
            measured: { [weak self] height in self?.contentHeightChanged(height) }))
        host.sizingOptions = []
        panel.contentView = host

        NotificationCenter.default.publisher(for: .lunchReady, object: model)
            .sink { [weak self] _ in self?.show() }.store(in: &cancellables)
        NotificationCenter.default.publisher(for: NSApplication.didChangeScreenParametersNotification)
            .sink { [weak self] _ in
                guard let self, self.visible else { return }
                self.chooseScreen()
                self.transition(to: self.motion.mode, animated: false)
            }.store(in: &cancellables)
        model.$session.removeDuplicates().receive(on: RunLoop.main)
            .sink { [weak self] session in self?.sessionChanged(session) }
            .store(in: &cancellables)
    }

    func show(expanded: Bool = true, chooseScreen: Bool = false) {
        confirmationRetraction?.cancel()
        // An incoming lunch while open updates in place. It must not re-anchor
        // to the pointer's new display or replay the entrance animation.
        if !visible || chooseScreen || screen == nil { self.chooseScreen() }
        transition(to: expanded ? .expanded : .compact)
    }

    func toggle() {
        if isExpanded { hide() } else { show() }
    }

    func collapse() {
        confirmationRetraction?.cancel()
        transition(to: .compact)
    }

    func hide() {
        confirmationRetraction?.cancel()
        transition(to: .hidden)
    }

    private func chooseScreen() {
        screen = NSScreen.screens.first { NSMouseInRect(NSEvent.mouseLocation, $0.frame, false) }
            ?? NSScreen.main ?? NSScreen.screens.first
        motion.notchHeight = screen?.safeAreaInsets.top ?? 0
    }

    private func contentHeightChanged(_ height: CGFloat) {
        guard height > 0, abs(height - expandedHeight) > 0.5 else { return }
        expandedHeight = height
        if isExpanded { transition(to: .expanded, duration: 0.22) }
    }

    private func sessionChanged(_ session: LunchSession) {
        let previous = lastSession
        lastSession = session
        guard previous != session else { return }
        confirmationRetraction?.cancel()
        guard session.phase == .confirmed,
              previous.id != session.id || previous.phase != .confirmed else { return }
        let ticket = ConfirmationRetraction(sessionID: session.id, revision: session.revision)
        confirmationRetraction = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 3_000_000_000) }
            catch { return }
            guard let self, !Task.isCancelled, self.isExpanded,
                  ticket.isDue(sessionID: self.model.session.id, revision: self.model.session.revision,
                               confirmed: self.model.session.phase == .confirmed) else { return }
            self.transition(to: .hidden)
        }
    }

    /// SwiftUI animates one clipped shell in a stationary window. The native
    /// window temporarily encloses both poses, then shrinks after the animation.
    /// Reversals continue from the currently rendered pose; content stays mounted.
    private func transition(to mode: PanelMode, duration: Double = 0.32, animated: Bool = true) {
        guard let screen else { return }
        if mode == .hidden && !visible { return }
        let left = screen.auxiliaryTopLeftArea
        let right = screen.auxiliaryTopRightArea
        let centerX = (left != nil && right != nil) ? (left!.maxX + right!.minX) / 2 : screen.frame.midX
        let notchWidth = (left != nil && right != nil) ? right!.minX - left!.maxX : 0
        let compactWidth = max(210, notchWidth + 12) + 28
        let seed = CGSize(width: compactWidth, height: max(1, motion.notchHeight))
        let target: CGSize
        switch mode {
        case .expanded: target = CGSize(width: 448, height: motion.notchHeight + expandedHeight)
        case .compact: target = CGSize(width: compactWidth, height: motion.notchHeight + 32)
        case .hidden: target = seed
        }
        if visible && motion.mode == mode && motion.size == target { return }
        generation += 1
        let token = generation
        completion?.cancel()
        let time = animated && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? duration : 0
        if !visible {
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                motion.size = seed
                motion.mode = .hidden
                motion.alpha = 0
            }
        }
        func frame(_ size: CGSize) -> CGRect {
            NotchGeometry.frame(size: size, screenFrame: screen.frame,
                                visibleTop: screen.visibleFrame.maxY,
                                notchHeight: motion.notchHeight, centerX: centerX)
        }
        // Keep the larger current native canvas during rapid reversals too.
        let canvas = CGSize(width: max(visible ? panel.frame.width : seed.width, target.width),
                            height: max(visible ? panel.frame.height : seed.height, target.height))
        panel.setFrame(frame(canvas), display: true)
        if !visible {
            panel.orderFrontRegardless()
            visible = true
            panel.contentView?.layoutSubtreeIfNeeded()
        }
        withAnimation(time == 0 ? nil : .easeInOut(duration: time)) {
            motion.size = target
            motion.mode = mode
            motion.alpha = mode == .hidden ? 0 : 1
        }
        let finalFrame = frame(target)
        completion = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(time * 1_000_000_000)) }
            catch { return }
            guard let self, !Task.isCancelled, token == self.generation else { return }
            if mode == .hidden {
                self.panel.orderOut(nil)
                self.visible = false
            }
            self.panel.setFrame(finalFrame, display: true)
        }
    }
}

private struct BodyHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

private struct NotchContent: View {
    @ObservedObject var model: MacLunchModel
    @ObservedObject var motion: PanelMotion
    let expand: () -> Void
    let collapse: () -> Void
    let hide: () -> Void
    let measured: (CGFloat) -> Void

    var body: some View {
        // Both presentations remain mounted. Opacity changes and the shell's
        // dimensions interpolate together in either direction.
        ZStack(alignment: .top) {
            expandedBody
                .frame(width: 420).fixedSize(horizontal: false, vertical: true)
                .background(GeometryReader { proxy in
                    Color.clear.preference(key: BodyHeightKey.self, value: proxy.size.height)
                })
                .padding(.top, motion.notchHeight)
                .opacity(motion.mode == .expanded ? 1 : 0)
                .allowsHitTesting(motion.mode == .expanded)
                .accessibilityHidden(motion.mode != .expanded)
            compactBody
                .frame(width: max(0, motion.size.width - 28), height: 32)
                .padding(.top, motion.notchHeight)
                .opacity(motion.mode == .compact ? 1 : 0)
                .allowsHitTesting(motion.mode == .compact)
                .accessibilityHidden(motion.mode != .compact)
        }
        .frame(width: motion.size.width, height: motion.size.height, alignment: .top)
        .background(.black)
        .clipShape(PanelSilhouette(shoulder: 14, radius: motion.radius))
        .opacity(motion.alpha)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .ignoresSafeArea()
        .preferredColorScheme(.dark)
        .onPreferenceChange(BodyHeightKey.self) { height in
            DispatchQueue.main.async { measured(height) }
        }
    }

    private var expandedBody: some View {
        VStack(spacing: 0) {
            HStack(spacing: 7) {
                Circle().fill(LunchStyle.lime).frame(width: 5, height: 5)
                Text("CORPORATE AUTONOMOUS MEAL PROTOCOL")
                    .font(.system(size: 8, weight: .medium)).tracking(0.65)
                Spacer()
                Button(action: collapse) { Image(systemName: "chevron.up").frame(width: 24, height: 22) }
                    .help("Collapse lunch").accessibilityLabel("Collapse lunch")
                Button(action: hide) { Image(systemName: "xmark").frame(width: 24, height: 22) }
                    .help("Return to menu bar").accessibilityLabel("Return to menu bar")
            }.foregroundStyle(.white.opacity(0.65)).buttonStyle(.plain)
                .padding(.horizontal, 18).padding(.top, 8)
            LocalLunchCard(session: model.session, embedded: true) { event in
                // Only the meal card changes; the hosting view and shell survive.
                withAnimation(.easeInOut(duration: 0.18)) {
                    model.send(event, revision: model.session.revision)
                }
            }.padding(.horizontal, 8).padding(.top, 4)
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.orange).padding(.horizontal, 20).padding(.top, 8)
            }
            HStack {
                Text(model.session.phase == .confirmed ? "Saved · available in the menu bar" :
                     model.scheduled ? "Next demo arrives in 5 seconds" : "\(model.session.office) · sample prices")
                    .font(.system(size: 10)).foregroundStyle(.white.opacity(0.45))
                Spacer()
                if model.session.phase == .confirmed {
                    Button("Simulate arrival") { model.send(.markDelivered, revision: model.session.revision) }
                        .font(.system(size: 10, weight: .medium)).foregroundStyle(LunchStyle.lime)
                }
                Menu {
                    Button("New demo lunch") { model.triggerDemo() }
                    Button("Lunch in 5 seconds") { hide(); model.triggerAfterDelay() }
                    Divider()
                    Button("Quit camp") { NSApplication.shared.terminate(nil) }
                } label: {
                    Image(systemName: "ellipsis.circle").foregroundStyle(.white.opacity(0.6))
                }.menuStyle(.borderlessButton).fixedSize().help("Demo controls")
                    .accessibilityLabel("Demo controls")
            }.buttonStyle(.plain).padding(.horizontal, 20).padding(.top, 10).padding(.bottom, 15)
        }
    }

    private var compactBody: some View {
        Button(action: expand) {
            HStack(spacing: 9) {
                Image(systemName: model.session.phase == .confirmed ? "checkmark.circle.fill" : "tent.fill")
                    .foregroundStyle(LunchStyle.lime)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(pillTitle(at: context.date)).font(.system(size: 11, weight: .medium))
                }
                Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold))
                    .foregroundStyle(.white.opacity(0.45))
            }.foregroundStyle(.white).frame(maxWidth: .infinity).frame(height: 32)
                .contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityLabel("Expand lunch choices")
    }

    private func pillTitle(at now: Date) -> String {
        if model.session.isExpired(at: now) { return "Lunch window closed" }
        switch model.session.phase {
        case .choosing: return "Lunch is ready"
        case .reviewing: return "Confirm your lunch"
        case .confirmed: return "Lunch confirmed"
        case .delivered: return "Lunch has landed"
        case .ended: return "Lunch ended"
        }
    }
}

/// Concave shoulders flow out of the screen edge into rounded lower corners.
private struct PanelSilhouette: Shape {
    var shoulder: CGFloat
    var radius: CGFloat
    var animatableData: CGFloat {
        get { radius }
        set { radius = newValue }
    }

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addQuadCurve(to: CGPoint(x: rect.maxX - shoulder, y: rect.minY + shoulder),
                          control: CGPoint(x: rect.maxX - shoulder, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - shoulder, y: rect.maxY - radius))
        path.addQuadCurve(to: CGPoint(x: rect.maxX - shoulder - radius, y: rect.maxY),
                          control: CGPoint(x: rect.maxX - shoulder, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + shoulder + radius, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.minX + shoulder, y: rect.maxY - radius),
                          control: CGPoint(x: rect.minX + shoulder, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + shoulder, y: rect.minY + shoulder))
        path.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.minY),
                          control: CGPoint(x: rect.minX + shoulder, y: rect.minY))
        path.closeSubpath()
        return path
    }
}
