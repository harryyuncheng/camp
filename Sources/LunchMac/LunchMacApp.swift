import AppKit
import SwiftUI
#if SWIFT_PACKAGE
import LunchUI
#endif

@main
@MainActor
enum LunchMacApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = LunchMacDelegate()
        app.setActivationPolicy(.accessory)
        app.delegate = delegate
        app.run()
        withExtendedLifetime(delegate) {}
    }
}

@MainActor
final class LunchMacDelegate: NSObject, NSApplicationDelegate {
    private let model = MacLunchModel()
    private let settings = CampSettingsStore()
    private var workspaceWindow: NSWindow?
    private var phoneWindow: NSWindow?
    private var panel: NotchPanelController!
    private var statusItem: NSStatusItem!
    private var statusMenu: NSMenu!

    func applicationDidFinishLaunching(_ notification: Notification) {
        settings.$lunchGroups.assign(to: &model.$groups)
        settings.$selectedGroupID.assign(to: &model.$joinedGroupID)
        model.onJoin = { [weak self] option, group in self?.settings.join(option, group: group) }
        settings.requestDemoGroup = { [weak self] group in
            guard let self else { return }
            self.model.officeName = self.settings.draft.office.name
            self.model.chooseGroup(group)
        }
        panel = NotchPanelController(model: model)
        settings.onOffer = { [weak self] session in self?.model.offer(session) }
        model.onTransition = { [weak self] session in self?.settings.reportLunch(session) }
        model.sync.onStatus = { [weak self] status in self?.settings.syncStatus = status }
        settings.onConnectionsChanged = { [weak self] connections in
            guard let self else { return }
            self.model.sync.configure(urlString: connections.recommendationURL, token: connections.recommendationToken)
            self.model.sync.start()
        }
        Task { await settings.refreshAll() }     // groups + ledger from the backend for the notch picker and Today
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        let logo = NSImage(size: NSSize(width: 22, height: 16), flipped: true) { rect in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.addPath(CampLogo().path(in: rect.insetBy(dx: 1, dy: 1)).cgPath)
            context.setFillColor(NSColor.black.cgColor)
            context.fillPath()
            return true
        }
        logo.isTemplate = true
        logo.accessibilityDescription = "camp"
        statusItem.button?.image = logo
        let menu = NSMenu()
        add("Open camp", action: #selector(openWorkspace), to: menu)
        add("Settings", action: #selector(openSettings), to: menu)
        add("iPhone layout preview", action: #selector(openPhonePreview), to: menu)
        menu.addItem(.separator())
        add("Show order", action: #selector(show), to: menu)
        add("Trigger new order now", action: #selector(trigger), to: menu)
        add("Trigger order in 5 seconds", action: #selector(schedule), to: menu)
        menu.addItem(.separator())
        add("Collapse to pill", action: #selector(collapse), to: menu)
        add("Hide panel", action: #selector(hide), to: menu)
        menu.addItem(.separator())
        add("Quit camp", action: #selector(quit), key: "q", to: menu)
        statusMenu = menu
        statusItem.button?.target = self
        statusItem.button?.action = #selector(statusClicked)
        statusItem.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        statusItem.button?.toolTip = "camp · click to show your order, right-click for controls"
        openWorkspace()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWorkspace()
        return false
    }

    private func add(_ title: String, action: Selector, key: String = "", to menu: NSMenu) {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        menu.addItem(item)
    }

    @objc private func openWorkspace() {
        if workspaceWindow == nil { workspaceWindow = makeWorkspace(compact: false) }
        workspaceWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc private func openSettings() { settings.section = .you; openWorkspace() }
    @objc private func openPhonePreview() {
        if phoneWindow == nil { phoneWindow = makeWorkspace(compact: true) }
        phoneWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    private func makeWorkspace(compact: Bool) -> NSWindow {
        let size = compact ? NSSize(width: 390, height: 780) : NSSize(width: 1080, height: 780)
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = compact ? "camp · iPhone layout preview" : "camp"
        window.minSize = compact ? NSSize(width: 375, height: 600) : NSSize(width: 900, height: 620)
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: CampWorkspace(store: settings, compact: compact) { [weak self] in self?.trigger() })
        window.center()
        return window
    }

    @objc private func show() { panel.show(expanded: true, chooseScreen: true) }
    @objc private func statusClicked() {
        if let event = NSApp.currentEvent, event.type == .rightMouseUp, let button = statusItem.button {
            NSMenu.popUpContextMenu(statusMenu, with: event, for: button)
        } else {
            panel.toggle()
        }
    }
    @objc private func trigger() { model.officeName = settings.draft.office.name; model.triggerDemo() }
    @objc private func schedule() { panel.hide(); model.triggerAfterDelay() }
    @objc private func collapse() { panel.collapse() }
    @objc private func hide() { panel.hide() }
    @objc private func quit() { NSApplication.shared.terminate(nil) }
}
