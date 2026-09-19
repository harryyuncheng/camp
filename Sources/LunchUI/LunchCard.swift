import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

public enum LunchStyle {
    public static let ink = Color(red: 0.08, green: 0.12, blue: 0.10)
    public static let lime = Color(red: 0.79, green: 0.95, blue: 0.43)
    public static let muted = Color.white.opacity(0.62)

    public static func money(_ cents: Int) -> String {
        (Double(cents) / 100).formatted(.currency(code: "USD"))
    }
}

/// Actions are injected: ordinary buttons in the app/preview, intent buttons in
/// the Live Activity. All surfaces use exactly the same meal and status layout.
public struct LunchCard<Actions: View>: View {
    let session: LunchSession
    let expired: Bool
    let embedded: Bool
    let actions: Actions

    public init(session: LunchSession, expired: Bool = false, embedded: Bool = false, @ViewBuilder actions: () -> Actions) {
        self.session = session
        self.expired = expired
        self.embedded = embedded
        self.actions = actions()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "tent.fill").foregroundStyle(LunchStyle.lime)
                Text("camp").font(.system(size: 22, weight: .bold, design: .rounded)).tracking(-0.8)
                Spacer(minLength: 4)
                Text("DEMO").font(.system(size: 9, weight: .bold)).foregroundStyle(LunchStyle.muted)
                if !expired && (session.phase == .choosing || session.phase == .reviewing) {
                    Text(timerInterval: min(Date.now, session.closesAt)...session.closesAt, countsDown: true)
                        .monospacedDigit().font(.caption.weight(.semibold)).frame(width: 42)
                        .accessibilityLabel("Time left to choose")
                }
            }
            if expired {
                status("This lunch window closed", detail: "Open camp to start a fresh demo.", symbol: "clock")
            } else {
                switch session.phase {
                case .choosing:
                    HStack(alignment: .firstTextBaseline) {
                        Text("Lunch, sorted.").font(.system(size: 21, weight: .semibold, design: .rounded))
                        Spacer(minLength: 4)
                        arrival
                    }
                    actions
                case .reviewing:
                    if let option = session.selectedOption {
                        HStack(spacing: 8) {
                            MealLabel(option: option)
                        }
                        HStack {
                            Text("Save \(LunchStyle.money(option.savingsCents)) in this demo")
                                .foregroundStyle(LunchStyle.lime)
                            Spacer(minLength: 4)
                            arrival
                        }.font(.caption)
                        actions
                    }
                case .confirmed:
                    status("You're on the list.", detail: session.selectedOption?.name ?? "Lunch confirmed", symbol: "checkmark.circle.fill")
                    HStack {
                        Text("Demo choice saved · no order placed")
                        Spacer(minLength: 4)
                        arrival
                    }.font(.caption2).foregroundStyle(LunchStyle.muted)
                case .delivered:
                    status("Lunch has landed.", detail: "Demo complete. Enjoy your break.", symbol: "bag.fill")
                case .ended:
                    status("Lunch ended", detail: "Start a new session whenever you're ready.", symbol: "moon.fill")
                }
            }
        }
        .foregroundStyle(.white)
        .padding(16)
        .background(embedded ? Color.clear : LunchStyle.ink)
        .clipShape(RoundedRectangle(cornerRadius: 22))
    }

    private var arrival: some View {
        HStack(spacing: 3) {
            Image(systemName: "bag")
            Text(session.arrivesAt, style: .time)
        }.font(.caption2).foregroundStyle(LunchStyle.muted)
    }

    private func status(_ title: String, detail: String, symbol: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).font(.title2).foregroundStyle(LunchStyle.lime)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 20, weight: .semibold, design: .rounded))
                Text(detail).font(.caption).foregroundStyle(LunchStyle.muted)
            }
        }
    }
}

public struct MealLabel: View {
    let option: LunchOption
    public init(option: LunchOption) { self.option = option }
    public var body: some View {
        HStack(spacing: 10) {
            Image(systemName: option.symbol).font(.system(size: 16))
                .foregroundStyle(LunchStyle.lime).frame(width: 26)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(option.name).font(.system(size: 13, weight: .semibold))
                Text(option.detail).font(.system(size: 10)).foregroundStyle(LunchStyle.muted)
            }
            Spacer(minLength: 4)
            Text(LunchStyle.money(option.priceCents)).font(.system(size: 13, weight: .semibold)).monospacedDigit()
        }.foregroundStyle(.white).frame(maxWidth: .infinity, alignment: .leading)
    }
}

public struct MealButtonStyle: ButtonStyle {
    public init() {}
    public func makeBody(configuration: Configuration) -> some View {
        configuration.label.padding(.horizontal, 10).padding(.vertical, 9)
            .background(Color.white.opacity(configuration.isPressed ? 0.18 : 0.07))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}

public struct ConfirmLabel: View {
    public init() {}
    public var body: some View {
        Text("Confirm lunch").font(.system(size: 13, weight: .semibold))
            .foregroundStyle(LunchStyle.ink).frame(maxWidth: .infinity).padding(.vertical, 11)
            .background(LunchStyle.lime).clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

public struct LocalLunchCard: View {
    let session: LunchSession
    let embedded: Bool
    let send: (LunchEvent) -> Void
    public init(session: LunchSession, embedded: Bool = false, send: @escaping (LunchEvent) -> Void) {
        self.session = session
        self.embedded = embedded
        self.send = send
    }
    public var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            LunchCard(session: session, expired: session.isExpired(at: context.date), embedded: embedded) {
                if session.phase == .choosing {
                    VStack(spacing: 5) {
                        ForEach(session.options) { option in
                            Button { send(.select(option.id)) } label: { MealLabel(option: option) }
                                .buttonStyle(MealButtonStyle())
                        }
                    }
                } else if session.phase == .reviewing {
                    HStack(spacing: 12) {
                        Button("Change") { send(.changeSelection) }
                            .font(.caption.weight(.semibold)).buttonStyle(.plain)
                        Button { send(.confirm) } label: { ConfirmLabel() }.buttonStyle(.plain)
                    }
                }
            }
        }
    }
}
