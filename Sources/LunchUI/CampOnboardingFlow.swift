import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

extension CampSettingsStore {
    /// Opens the setup flow and starts it from whatever the laptop's database already holds, so a phone that has
    /// never been set up adopts the Mac's answers (and vice versa) instead of asking everything twice.
    public func startOnboarding() async {
        onboardingStep = 0
        showOnboarding = true
        onboardingBusy = true
        defer { onboardingBusy = false }
        await loadOnboarding()
    }

    public func loadOnboarding() async {
        do {
            let record = try await client().onboarding(userId: recommenderUserID, displayName: draft.personal.displayName,
                                                       officeId: draft.office.id)
            onboardingRecord = record
            if let record {
                remember(userId: record.userId)
                if let shared = record.settings { draft = draft.adoptingSharedSetup(from: shared) }
                onboardingStatus = "Starting from the setup in the laptop database · \(record.summary)"
            } else {
                onboardingStatus = "Nothing set up in the laptop database yet — these answers will be the first."
            }
        } catch {
            onboardingRecord = nil
            onboardingStatus = "The laptop database is unreachable, so this setup will only be saved on this device (\(error.localizedDescription))"
        }
    }

    /// Saves the answers on this device and in the laptop's database (`PUT /v1/onboarding`, which also applies them
    /// to the profile the recommender reads). The flow closes either way: a demo shouldn't get stuck behind the
    /// network, and everything remains editable in the normal settings pages.
    @discardableResult
    public func finishOnboarding() async -> Bool {
        guard validationErrors.isEmpty else { saveError = validationErrors.joined(separator: "\n"); return false }
        onboardingBusy = true
        defer { onboardingBusy = false }
        save()
        do {
            let record = try await client().putOnboarding(OnboardingRequest(configuration: draft, userId: recommenderUserID))
            onboardingRecord = record
            remember(userId: record.userId)
            onboardingStatus = "Setup saved in the laptop database · \(record.summary)"
            statusMessage = "Setup saved · shared with your other device"
            showOnboarding = false
            await refreshAll()
            return true
        } catch {
            onboardingStatus = "Saved on this device · the laptop database rejected it (\(error.localizedDescription))"
            showOnboarding = false
            return false
        }
    }

    /// Clears the finished flag so the flow can be demoed again from the same answers.
    public func replayOnboarding() async {
        guard let userId = onboardingRecord?.userId ?? recommenderUserID else {
            onboardingStatus = "No setup is stored yet, so there is nothing to reset."
            return
        }
        onboardingBusy = true
        defer { onboardingBusy = false }
        do { onboardingRecord = try await client().resetOnboarding(userId: userId); onboardingStatus = "Setup marked unfinished; the answers were kept." }
        catch { onboardingStatus = "Couldn’t reset the setup: \(error.localizedDescription)" }
    }
}

/// The once-per-person setup: the answers people give at the start and then rarely touch — who they are and what they
/// can eat, when they can eat it, their calendars, the office policy and how this device reaches the laptop. Shown
/// only when the Demo tab asks for it, identical on the Mac and the phone, and saved to the laptop's database.
struct CampOnboardingFlow: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool

    enum Step: CaseIterable {
        case welcome, link, you, timing, calendars, office, notifications, review
        var title: String {
            switch self {
            case .welcome: return "Welcome to camp"
            case .link: return "Link this device"
            case .you: return "What you eat"
            case .timing: return "When you eat"
            case .calendars: return "Your calendars"
            case .office: return "Your office"
            case .notifications: return "Nudges"
            case .review: return "All set"
            }
        }
        var caption: String {
            switch self {
            case .welcome: return "Five minutes now, then camp orders lunch around your day."
            case .link: return "Both devices read and write the one database on the laptop."
            case .you: return "Hard rules for the recommender: allergies never get suggested."
            case .timing: return "The window camp looks inside for a free slot."
            case .calendars: return "Busy blocks camp works around, and where orders are written."
            case .office: return "Where deliveries go, and what the company pays for."
            case .notifications: return "When camp is allowed to interrupt you."
            case .review: return "Everything here stays editable in the normal settings."
            }
        }
    }

    private var steps: [Step] { Step.allCases }
    private var step: Step { steps[min(store.onboardingStep, steps.count - 1)] }
    private var index: Int { min(store.onboardingStep, steps.count - 1) }
    private var isLast: Bool { index == steps.count - 1 }

    /// Only the rules for the current step block Continue; the rest are caught before finishing.
    private var stepError: String? {
        let errors = store.validationErrors
        switch step {
        case .you: return errors.first { $0.contains("name for your profile") }
        case .timing: return errors.first { $0.contains("meal window") || $0.contains("minutes to eat") || $0.contains("Meeting buffer") }
        case .office: return errors.first { $0.contains("office") || $0.contains("Office") || $0.contains("cutoff") || $0.contains("Budgets") || $0.contains("timezone") }
        case .link: return errors.first { $0.contains("Recommendation service") }
        case .review: return errors.first
        default: return nil
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 7) {
                        Text(step.title).font(.system(size: compact ? 27 : 33, weight: .semibold, design: .rounded)).tracking(-0.8)
                        Text(step.caption).font(.system(size: 13)).foregroundStyle(CampPalette.muted)
                    }
                    content
                }.padding(compact ? 18 : 32).frame(maxWidth: 760).frame(maxWidth: .infinity)
            }
            footer
        }
        .background(CampPalette.background)
        .foregroundStyle(CampPalette.ink)
        .task { if store.onboardingRecord == nil { await store.loadOnboarding() } }
    }

    @ViewBuilder
    private var content: some View {
        switch step {
        case .welcome: welcome
        case .link: link
        case .you: you
        case .timing: timing
        case .calendars: calendars
        case .office: office
        case .notifications: notifications
        case .review: review
        }
    }

    // MARK: steps

    private var welcome: some View {
        VStack(spacing: 20) {
            CampCard("What camp needs from you once") {
                Label("What you can and can’t eat", systemImage: "fork.knife").font(.callout)
                Label("The window a meal has to fit in", systemImage: "clock").font(.callout)
                Label("The calendars that say when you’re busy", systemImage: "calendar").font(.callout)
                Label("Your office, its delivery window and budget", systemImage: "building.2").font(.callout)
                Text("Day to day you only tap the lunch card; these answers stay put until you change them in settings.")
                    .font(.caption).foregroundStyle(CampPalette.muted)
            }
            storageCard
        }
    }

    private var storageCard: some View {
        CampCard("Where this is saved", subtitle: "The laptop runs the database; this device writes straight into it.") {
            HStack {
                CampBadge(text: "Setting up on \(CampDevice.label(CampDevice.current))", active: true)
                if let record = store.onboardingRecord {
                    CampBadge(text: record.completed ? "Existing setup: \(record.summary)" : "Unfinished setup: \(record.summary)")
                }
                Spacer()
            }
            if let status = store.onboardingStatus {
                Text(status).font(.caption).foregroundStyle(CampPalette.muted).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var link: some View {
        VStack(spacing: 20) {
            CampCard("Recommendation service", subtitle: "The laptop's backend, `uv run uvicorn camp.api:app --port 8788`.") {
                CampField("Address") { CampTextField(title: "http://127.0.0.1:8788", text: $store.draft.connections.recommendationURL) }
                CampField("Token") {
                    CampTextField(title: "X-Camp-Token (only when the backend sets CAMP_TOKEN)",
                                  text: Binding(get: { store.draft.connections.recommendationToken ?? "" },
                                                set: { store.draft.connections.recommendationToken = $0.isEmpty ? nil : $0 }))
                }
                HStack {
                    Button(store.recommenderBusy ? "Checking…" : "Test connection") { Task { await store.connectRecommender(); await store.loadOnboarding() } }
                        .buttonStyle(CampActionStyle()).disabled(store.recommenderBusy)
                    if store.recommenderHealth != nil { CampBadge(text: "Reachable", active: true) }
                    Spacer()
                }
                if let error = store.recommenderError { Text(error).font(.caption).foregroundStyle(.red) }
                Text(compact ? "On the phone this is the laptop's address on the cable's network, e.g. http://172.20.10.2:8788 — not 127.0.0.1, which is the phone itself."
                     : "On the Mac the backend is on this machine: http://127.0.0.1:8788. The phone needs this machine's address instead.")
                    .font(.caption).foregroundStyle(CampPalette.muted).fixedSize(horizontal: false, vertical: true)
            }
            storageCard
        }
    }

    private var you: some View {
        CampCard("Food preferences", subtitle: "Allergies are hard filters; dislikes only push things down the list.") {
            CampField("Your name") { CampTextField(title: "Your name", text: $store.draft.personal.displayName) }
            Picker("Dietary preference", selection: $store.draft.personal.dietaryStyle) {
                ForEach(["No preference", "Vegetarian", "Vegan", "Pescatarian", "Halal", "Gluten-free"], id: \.self) { Text($0).tag($0) }
            }
            CampField("Allergies") { CampTextField(title: "e.g. peanuts, sesame", text: $store.draft.personal.allergies) }
            CampField("Rather skip") { CampTextField(title: "Ingredients or meals you dislike", text: $store.draft.personal.dislikes) }
        }
    }

    private var timing: some View {
        CampCard("Meal timing", subtitle: "camp finds a free slot of “time to eat” inside this window.") {
            CampPair(compact: compact) {
                CampField("Earliest meal") { CampTimingField(label: "Earliest meal", value: $store.draft.personal.lunchStart, kind: .time) }
                CampField("Latest meal") { CampTimingField(label: "Latest meal", value: $store.draft.personal.lunchEnd, kind: .time) }
            }
            CampPair(compact: compact) {
                CampField("Time to eat") { CampTimingField(label: "Time to eat", value: $store.draft.personal.lunchDuration, kind: .duration(15...120)) }
                CampField("Meeting buffer") { CampTimingField(label: "Meeting buffer", value: $store.draft.personal.meetingBuffer, kind: .duration(0...60)) }
            }
        }
    }

    private var calendars: some View {
        VStack(spacing: 20) {
            CampCard("Which calendars count") {
                CampToggle(title: "Work calendar", detail: "Meetings that block a meal", value: $store.draft.personal.workCalendar)
                CampToggle(title: "Personal calendar", value: $store.draft.personal.personalCalendar)
                CampToggle(title: "Holidays", detail: "Skip ordering on days off", value: $store.draft.personal.holidayCalendar)
                Text(calendarNote).font(.caption).foregroundStyle(CampPalette.muted).fixedSize(horizontal: false, vertical: true)
            }
            CampCalendarView(store: store)
        }
    }

    private var calendarNote: String {
        #if os(macOS)
        return "Grant access below; camp reads busy blocks and writes the orders you join to a separate “camp” calendar."
        #else
        return "These choices travel with your setup. Calendar permission itself is granted in the Mac app, which reads the events."
        #endif
    }

    private var office: some View {
        VStack(spacing: 20) {
            CampCard("Office", subtitle: store.isDemoAdmin ? "Delivery address and policy for everyone at this office." : "Read-only: turn on demo admin to change office policy.") {
                CampField("Office name") { CampTextField(title: "Office name", text: $store.draft.office.name) }
                CampField("Delivery address") { CampTextField(title: "Delivery address", text: $store.draft.office.address) }
                CampField("Timezone") { CampTextField(title: "America/New_York", text: $store.draft.office.timezone) }
                CampField("Order cutoff") { CampTimePicker(label: "Order cutoff", minutes: $store.draft.office.cutoff) }
                CampPair(compact: compact) {
                    CampField("Delivery from") { CampTimePicker(label: "Delivery from", minutes: $store.draft.office.deliveryStart) }
                    CampField("Delivery until") { CampTimePicker(label: "Delivery until", minutes: $store.draft.office.deliveryEnd) }
                }
                CampField("Per-person budget") { CampNumberStepper(label: "Per-person budget", value: $store.draft.office.personBudgetCents, range: 100...100000, step: 100, money: true) }
            }.disabled(!store.isDemoAdmin)
            CampLocationView(store: store)
        }
    }

    private var notifications: some View {
        CampCard("Notifications", subtitle: "Preview settings · notifications aren’t scheduled yet.") {
            CampToggle(title: "Meal invitations", value: $store.draft.personal.lunchInvitations)
            CampToggle(title: "Order updates", value: $store.draft.personal.orderUpdates)
            CampToggle(title: "Coffee invitations", value: $store.draft.personal.coffeeInvitations)
            CampField("Snooze for") { CampNumberStepper(label: "Snooze", value: $store.draft.personal.snoozeMinutes, range: 5...60, step: 5, suffix: " min") }
        }
    }

    private var review: some View {
        VStack(spacing: 20) {
            CampCard("Your setup") {
                summary("You", "\(store.draft.personal.displayName) · \(store.draft.personal.dietaryStyle)")
                summary("Allergies", store.draft.personal.allergies.isEmpty ? "none" : store.draft.personal.allergies)
                summary("Rather skip", store.draft.personal.dislikes.isEmpty ? "nothing" : store.draft.personal.dislikes)
                summary("Meal window", "\(CampTimePicker.label(store.draft.personal.lunchStart)) – \(CampTimePicker.label(store.draft.personal.lunchEnd)) · \(store.draft.personal.lunchDuration) min to eat")
                summary("Calendars", [store.draft.personal.workCalendar ? "work" : nil, store.draft.personal.personalCalendar ? "personal" : nil,
                                      store.draft.personal.holidayCalendar ? "holidays" : nil].compactMap { $0 }.joined(separator: ", ").ifEmpty("none"))
                summary("Office", "\(store.draft.office.name) · delivery \(CampTimePicker.label(store.draft.office.deliveryStart))–\(CampTimePicker.label(store.draft.office.deliveryEnd)) · \(LunchStyle.money(store.draft.office.personBudgetCents)) per person")
                summary("Backend", store.draft.connections.recommendationURL.isEmpty ? "http://127.0.0.1:8788" : store.draft.connections.recommendationURL)
            }
            if let error = store.validationErrors.first {
                Text(error).font(.callout).foregroundStyle(.red)
            }
            storageCard
        }
    }

    private func summary(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label).font(.system(size: 12, weight: .medium)).foregroundStyle(CampPalette.muted).frame(width: 110, alignment: .leading)
            Text(value).font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }

    // MARK: chrome

    private var header: some View {
        HStack(spacing: 12) {
            HStack(spacing: 8) {
                CampLogo().fill(CampPalette.green).frame(width: 30, height: 18).accessibilityHidden(true)
                Text("Setting up").font(.system(size: 15, weight: .semibold, design: .rounded))
            }
            Spacer()
            HStack(spacing: 6) {
                ForEach(steps.indices, id: \.self) { i in
                    Capsule().fill(i <= index ? CampPalette.green : CampPalette.border)
                        .frame(width: i == index ? 18 : 7, height: 7)
                }
            }.accessibilityLabel("Step \(index + 1) of \(steps.count)")
            Spacer()
            Button("Close") { store.showOnboarding = false }.buttonStyle(.plain).font(.system(size: 12)).foregroundStyle(CampPalette.muted)
        }.padding(.horizontal, compact ? 18 : 24).padding(.vertical, 14).background(.white)
            .overlay(alignment: .bottom) { CampPalette.border.frame(height: 1) }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let stepError { Text(stepError).font(.caption).foregroundStyle(.red) }
            HStack {
                if index > 0 { Button("Back") { store.onboardingStep -= 1 }.buttonStyle(CampActionStyle(primary: false)) }
                Spacer()
                Text("\(index + 1) / \(steps.count)").font(.system(size: 11)).foregroundStyle(CampPalette.muted).monospacedDigit()
                if isLast {
                    Button(store.onboardingBusy ? "Saving…" : "Finish setup") { Task { await store.finishOnboarding() } }
                        .buttonStyle(CampActionStyle()).disabled(store.onboardingBusy || stepError != nil)
                } else {
                    Button("Continue") { store.onboardingStep += 1 }.buttonStyle(CampActionStyle()).disabled(stepError != nil)
                }
            }
        }.padding(.horizontal, compact ? 18 : 24).padding(.vertical, 14).background(.white)
            .overlay(alignment: .top) { CampPalette.border.frame(height: 1) }
    }
}

private extension String {
    func ifEmpty(_ fallback: String) -> String { isEmpty ? fallback : self }
}
