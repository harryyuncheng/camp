#if os(macOS)
import AppKit
import Combine
import EventKit
#if SWIFT_PACKAGE
import LunchCore
#endif

public struct CampCalendarChoice: Identifiable, Sendable {
    public let id: String
    public let name: String
    public let account: String
}

/// Reads local calendar events; only anonymous busy/free intervals leave this object.
@MainActor
public final class MacLunchCalendar: ObservableObject {
    @Published public private(set) var enabled: Bool
    @Published public private(set) var requesting = false
    @Published public private(set) var permission = "Not connected"
    @Published public private(set) var calendars: [CampCalendarChoice] = []
    @Published public private(set) var selected: Set<String>
    @Published public private(set) var blockAllDay: Bool
    @Published public private(set) var summary = "Calendar not connected"
    @Published public private(set) var detail = "Connect your Mac calendars to find time for lunch."
    @Published public private(set) var freeWindows: [DateInterval] = []
    @Published public private(set) var busyBlocks: [DateInterval] = []
    @Published public private(set) var timelineDay: DateInterval?
    public var suggestedLunch: DateInterval? {
        guard let window = freeWindows.first else { return nil }
        return DateInterval(start: window.start, duration: Double(preferences.lunchDuration * 60))
    }
    @Published public private(set) var busyNow: Bool?
    @Published public private(set) var checkedAt: Date?
    @Published public private(set) var timezone = "America/New_York"
    private let events = EKEventStore()
    private let reader = CampCalendarReader()
    private var refreshTask: Task<Void, Never>?
    private var revision = 0
    private let labelFormatter: DateFormatter = {
        let formatter = DateFormatter(); formatter.dateStyle = .none; formatter.timeStyle = .short
        return formatter
    }()
    private var preferences = PersonalPreferences()
    private var subscriptions = Set<AnyCancellable>()
    private var sleeping = false
    private let enabledKey = "camp.calendar.enabled.v1"
    private let selectedKey = "camp.calendar.selection.v1"
    private let allDayKey = "camp.calendar.all-day.v1"

    public init() {
        enabled = UserDefaults.standard.bool(forKey: "camp.calendar.enabled.v1")
        selected = Set(UserDefaults.standard.stringArray(forKey: "camp.calendar.selection.v1") ?? [])
        blockAllDay = UserDefaults.standard.object(forKey: "camp.calendar.all-day.v1") as? Bool ?? true
        NotificationCenter.default.publisher(for: .EKEventStoreChanged).debounce(for: .milliseconds(400), scheduler: RunLoop.main).sink { [weak self] _ in
            self?.refresh()
        }.store(in: &subscriptions)
        for name in [NSApplication.didBecomeActiveNotification, .NSSystemTimeZoneDidChange, .NSCalendarDayChanged] {
            NotificationCenter.default.publisher(for: name).sink { [weak self] _ in
                Task { @MainActor [weak self] in self?.refresh() }
            }.store(in: &subscriptions)
        }
        NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.willSleepNotification).sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.sleeping = true; self?.clear("Refreshing after wake", "Calendar availability is paused while the Mac sleeps.") }
        }.store(in: &subscriptions)
        NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didWakeNotification).sink { [weak self] _ in
            Task { @MainActor [weak self] in self?.sleeping = false; self?.refresh() }
        }.store(in: &subscriptions)
        Timer.publish(every: 60, on: .main, in: .common).autoconnect().sink { [weak self] _ in self?.refresh() }.store(in: &subscriptions)
    }
    public var canRead: Bool { EKEventStore.authorizationStatus(for: .event) == .authorized }
    public var missingSelections: Set<String> { selected.subtracting(Set(calendars.map(\.id))) }
    public func configure(_ preferences: PersonalPreferences, timezone: String) {
        self.preferences = preferences; self.timezone = timezone; refresh()
    }
    public func select(_ id: String, enabled: Bool) {
        if enabled { selected.insert(id) } else { selected.remove(id) }
        UserDefaults.standard.set(Array(selected).sorted(), forKey: selectedKey)
        refresh()
    }
    public func setBlockAllDay(_ value: Bool) {
        blockAllDay = value; UserDefaults.standard.set(value, forKey: allDayKey); refresh()
    }
    public func pause() {
        refreshTask?.cancel(); revision += 1
        enabled = false; UserDefaults.standard.set(false, forKey: enabledKey)
        calendars = []; clear("Calendar paused", "Resume to check your selected calendars.")
    }
    public func connect() {
        guard !requesting else { return }
        enabled = true; UserDefaults.standard.set(true, forKey: enabledKey)
        if canRead { refresh(); return }
        requesting = true
        // Runtime dispatch keeps the current Xcode 14/macOS 13 SDK build usable on
        // macOS 14+, where the legacy request grants write-only access.
        let completion: @convention(block) (Bool, NSError?) -> Void = { [weak self] granted, error in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.requesting = false
                if granted { self.events.reset(); await self.reader.reset() }
                self.refresh()
                if error != nil { self.detail = "Calendar permission could not be completed. Open Calendar settings to allow full access." }
            }
        }
        if #available(macOS 14, *) {
            let selector = NSSelectorFromString("requestFullAccessToEventsWithCompletion:")
            guard events.responds(to: selector) else {
                requesting = false; clear("Calendar unavailable", "This macOS version could not provide full calendar access."); return
            }
            _ = events.perform(selector, with: completion as AnyObject)
        } else {
            events.requestAccess(to: .event) { granted, error in completion(granted, error as NSError?) }
        }
    }
    public func openSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars") { NSWorkspace.shared.open(url) }
    }
    private func clear(_ title: String, _ reason: String) {
        summary = title; detail = reason; freeWindows = []; busyBlocks = []; timelineDay = nil; busyNow = nil; checkedAt = nil
    }
    public func refresh() {
        refreshTask?.cancel(); revision += 1
        guard !sleeping else { return }
        guard enabled else { clear("Calendar not connected", "Connect your Mac calendars to find time for lunch."); return }
        switch EKEventStore.authorizationStatus(for: .event) {
        case .authorized: permission = "Full access"
        case .denied: permission = "Denied"
        case .restricted: permission = "Restricted"
        case .notDetermined: permission = "Not requested"
        @unknown default: permission = "Full access required"
        }
        guard canRead else {
            calendars = []; clear("Calendar access needed", "Allow full calendar access in macOS settings. camp only reads availability and never changes events."); return
        }
        var calendar = Calendar(identifier: .gregorian)
        guard let zone = TimeZone(identifier: timezone) else { clear("Invalid timezone", "Set the office timezone in Office."); return }
        calendar.timeZone = zone
        let now = Date(); let day = calendar.startOfDay(for: now)
        guard let tomorrow = calendar.date(byAdding: .day, value: 1, to: day),
              let start = calendar.date(bySettingHour: preferences.lunchStart / 60, minute: preferences.lunchStart % 60, second: 0, of: day),
              let end = calendar.date(bySettingHour: preferences.lunchEnd / 60, minute: preferences.lunchEnd % 60, second: 0, of: day), start < end else {
            clear("Invalid lunch window", "Save a valid lunch window in You."); return
        }
        let buffer = Double(preferences.meetingBuffer * 60)
        let expectedRevision = revision
        let selectedIDs = selected
        let includeAllDay = blockAllDay
        refreshTask = Task { [weak self, reader] in
            let result = await reader.read(selected: selectedIDs, blockAllDay: includeAllDay,
                                           from: day.addingTimeInterval(-buffer), to: tomorrow.addingTimeInterval(buffer), buffer: buffer)
            guard let self, !Task.isCancelled, self.revision == expectedRevision, self.enabled, !self.sleeping else { return }
            guard self.canRead else {
                self.calendars = []; self.clear("Calendar access needed", "Calendar permission changed. Reconnect before using availability."); return
            }
            self.calendars = result.calendars
            guard !self.selected.isEmpty else { self.clear("Choose calendars", "Select the calendars that should block lunch."); return }
            guard self.missingSelections.isEmpty else { self.clear("Calendar unavailable", "A selected calendar is missing. Restore it in Calendar or remove it below."); return }
            let busy = result.busy
            var merged: [DateInterval] = []
            for interval in busy {
                if let last = merged.last, interval.start <= last.end {
                    merged[merged.count - 1] = DateInterval(start: last.start, end: max(last.end, interval.end))
                } else { merged.append(interval) }
            }
            timelineDay = DateInterval(start: day, end: tomorrow)
            busyBlocks = merged.compactMap { block in
                let from = max(day, block.start), until = min(tomorrow, block.end)
                return until > from ? DateInterval(start: from, end: until) : nil
            }
            busyNow = merged.contains { $0.start <= now && now < $0.end }
            var cursor = max(start, now)
            var gaps: [DateInterval] = []
            for interval in merged where interval.end > cursor && interval.start < end {
                if interval.start > cursor { gaps.append(DateInterval(start: cursor, end: min(interval.start, end))) }
                cursor = max(cursor, interval.end)
            }
            if cursor < end { gaps.append(DateInterval(start: cursor, end: end)) }
            freeWindows = gaps.filter { $0.duration >= Double(self.preferences.lunchDuration * 60) }
            checkedAt = now
            if now >= end { summary = "Today’s lunch window has ended" }
            else if freeWindows.isEmpty { summary = "No lunch window available" }
            else { summary = "\(freeWindows.count) lunch \(freeWindows.count == 1 ? "window" : "windows") available" }
            detail = "\(preferences.lunchDuration) minutes to eat · \(preferences.meetingBuffer)-minute meeting buffer · \(zone.identifier)"
        }
    }
    public func label(_ interval: DateInterval) -> String {
        labelFormatter.timeZone = TimeZone(identifier: timezone)
        return "\(labelFormatter.string(from: interval.start)) – \(labelFormatter.string(from: interval.end))"
    }
}
private struct CampCalendarRead: Sendable {
    let calendars: [CampCalendarChoice]
    let busy: [DateInterval]
}

/// Owns all event queries on an actor executor, separate from the main/UI actor.
private actor CampCalendarReader {
    private lazy var events = EKEventStore()
    func reset() { events.reset() }
    func read(selected: Set<String>, blockAllDay: Bool, from: Date, to: Date, buffer: TimeInterval) -> CampCalendarRead {
        guard !Task.isCancelled, EKEventStore.authorizationStatus(for: .event) == .authorized else {
            return CampCalendarRead(calendars: [], busy: [])
        }
        let sources = events.calendars(for: .event)
        let calendars = sources.map { CampCalendarChoice(id: $0.calendarIdentifier, name: $0.title, account: $0.source.title) }
            .sorted { ($0.account, $0.name, $0.id) < ($1.account, $1.name, $1.id) }
        let chosen = sources.filter { selected.contains($0.calendarIdentifier) }
        guard !Task.isCancelled, !chosen.isEmpty, chosen.count == selected.count else { return CampCalendarRead(calendars: calendars, busy: []) }
        let predicate = events.predicateForEvents(withStart: from, end: to, calendars: chosen)
        let busy = events.events(matching: predicate).compactMap { event -> DateInterval? in
            guard event.status != .canceled, event.availability != .free,
                  !(event.attendees?.contains { $0.isCurrentUser && $0.participantStatus == .declined } ?? false),
                  !event.isAllDay || blockAllDay,
                  let start = event.startDate, let end = event.endDate, end > start else { return nil }
            return DateInterval(start: start.addingTimeInterval(-buffer), end: end.addingTimeInterval(buffer))
        }.sorted { $0.start < $1.start }
        return CampCalendarRead(calendars: calendars, busy: busy)
    }
}

#endif
