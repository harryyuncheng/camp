import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

@main
struct LunchlineWidgets: WidgetBundle {
    var body: some Widget { LunchlineLiveActivity() }
}

struct LunchlineLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: LunchAttributes.self) { context in
            InteractiveLunchCard(context: context)
                .activityBackgroundTint(LunchStyle.ink)
                .activitySystemActionForegroundColor(.white)
                .widgetURL(context.attributes.url)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.bottom) {
                    InteractiveLunchCard(context: context)
                }
            } compactLeading: {
                Label("Lunch", systemImage: "fork.knife").font(.caption).foregroundStyle(LunchStyle.lime)
            } compactTrailing: {
                CompactStatus(session: context.state, stale: context.isStale)
            } minimal: {
                Image(systemName: context.state.phase == .confirmed ? "checkmark" : "fork.knife")
                    .foregroundStyle(LunchStyle.lime)
            }
            .widgetURL(context.attributes.url)
            .keylineTint(LunchStyle.lime)
        }
    }
}

private struct InteractiveLunchCard: View {
    let context: ActivityViewContext<LunchAttributes>
    private var session: LunchSession { context.state }

    var body: some View {
        // Lock Screen Live Activities have a limited height. Keep the same camp
        // styling, but do not embed the taller desktop card inside WidgetKit.
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                CampLogo().fill(LunchStyle.lime).frame(width: 26, height: 16)
                Text("camp").font(.headline)
                Spacer()
                Text("DEMO").font(.caption2).foregroundStyle(LunchStyle.muted)
                CompactStatus(session: session, stale: context.isStale)
            }
            if context.isStale || session.isExpired() {
                Text("Lunch window closed").font(.subheadline.weight(.semibold))
                Text("Open camp for a fresh invitation.").font(.caption)
            } else if session.phase == .choosing {
                Text(context.attributes.group?.name ?? "Choose your lunch").font(.subheadline.weight(.semibold)).lineLimit(1)
                HStack(spacing: 6) {
                    ForEach(session.options) { option in
                        Button(intent: SelectLunchIntent(session: session, optionID: option.id)) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(option.name).font(.caption.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.8)
                                Text(LunchStyle.money(option.priceCents)).font(.caption2).foregroundStyle(LunchStyle.lime)
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(9)
                                .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                        }.buttonStyle(.plain)
                    }
                }
            } else if session.phase == .reviewing {
                Text(session.selectedOption?.name ?? "Review lunch").font(.subheadline.weight(.semibold)).lineLimit(1)
                HStack(spacing: 12) {
                    Button("Change", intent: ChangeLunchIntent(session: session)).font(.caption).buttonStyle(.plain)
                    Button(intent: ConfirmLunchIntent(session: session)) { ConfirmLabel() }.buttonStyle(.plain)
                }
            } else {
                Text(session.phase == .confirmed ? "You’re on the list." : session.phase == .delivered ? "Lunch has landed." : "Lunch ended")
                    .font(.subheadline.weight(.semibold))
                HStack {
                    Text(session.selectedOption?.name ?? "Demo complete").lineLimit(1)
                    Spacer()
                    if session.phase == .confirmed { Text(session.arrivesAt, style: .time) }
                }.font(.caption).foregroundStyle(LunchStyle.muted)
            }
        }.foregroundStyle(.white).padding(12)
    }
}

private struct CompactStatus: View {
    let session: LunchSession
    let stale: Bool
    var body: some View {
        Group {
            if stale || session.isExpired() {
                Image(systemName: "clock.badge.exclamationmark")
            } else if session.phase == .confirmed || session.phase == .delivered {
                Image(systemName: "checkmark.circle.fill")
            } else if session.phase == .ended {
                Image(systemName: "xmark")
            } else {
                Text(timerInterval: min(Date.now, session.closesAt)...session.closesAt, countsDown: true)
                    .monospacedDigit().frame(width: 38)
            }
        }.font(.caption).foregroundStyle(LunchStyle.lime)
    }
}

#Preview("Choose lunch", as: .content, using: LunchAttributes(sessionID: UUID())) {
    LunchlineLiveActivity()
} contentStates: {
    DemoLunch.make()
}

#Preview("Confirm lunch", as: .dynamicIsland(.expanded), using: LunchAttributes(sessionID: UUID())) {
    LunchlineLiveActivity()
} contentStates: {
    try! DemoLunch.make().applying(.select("green-bowl"))
}

#Preview("Confirmed", as: .content, using: LunchAttributes(sessionID: UUID())) {
    LunchlineLiveActivity()
} contentStates: {
    try! DemoLunch.make().applying(.select("green-bowl")).applying(.confirm)
}
