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
        LunchCard(session: session, expired: context.isStale || session.isExpired()) {
            if session.phase == .choosing {
                VStack(spacing: 5) {
                    ForEach(session.options) { option in
                        Button(intent: SelectLunchIntent(session: session, optionID: option.id)) {
                            MealLabel(option: option)
                        }.buttonStyle(MealButtonStyle())
                    }
                }
            } else if session.phase == .reviewing {
                HStack(spacing: 12) {
                    Button("Change", intent: ChangeLunchIntent(session: session))
                        .font(.caption.weight(.semibold)).buttonStyle(.plain)
                    Button(intent: ConfirmLunchIntent(session: session)) {
                        ConfirmLabel()
                    }.buttonStyle(.plain)
                }
            }
        }
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
