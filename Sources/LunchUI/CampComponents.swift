import SwiftUI
#if os(macOS)
import AppKit
#endif
#if SWIFT_PACKAGE
import LunchCore
#endif

enum CampPalette {
    static let background = Color(red: 0.96, green: 0.97, blue: 0.94)
    static let ink = Color(red: 0.12, green: 0.17, blue: 0.13)
    static let muted = Color(red: 0.43, green: 0.48, blue: 0.43)
    static let border = Color(red: 0.87, green: 0.89, blue: 0.85)
    static let lime = LunchStyle.lime
    static let green = Color(red: 0.24, green: 0.37, blue: 0.17)
}

struct CampBadge: View {
    let text: String
    var active = false
    var body: some View {
        Text(text).font(.system(size: 10, weight: .semibold))
            .foregroundStyle(active ? CampPalette.green : CampPalette.muted)
            .padding(.horizontal, 9).padding(.vertical, 5)
            .background(active ? CampPalette.lime.opacity(0.5) : CampPalette.background)
            .clipShape(Capsule())
    }
}

struct CampCard<Content: View>: View {
    let title: String
    let subtitle: String?
    let content: Content
    init(_ title: String, subtitle: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title; self.subtitle = subtitle; self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.system(size: 17, weight: .semibold, design: .rounded))
                if let subtitle { Text(subtitle).font(.system(size: 12)).foregroundStyle(CampPalette.muted).fixedSize(horizontal: false, vertical: true) }
            }
            content
        }.frame(maxWidth: .infinity, alignment: .leading).padding(22)
            .background(RoundedRectangle(cornerRadius: 20).fill(.white))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(CampPalette.border, lineWidth: 1))
    }
}

struct CampActionStyle: ButtonStyle {
    var primary = true
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 13, weight: .semibold))
            .foregroundStyle(primary ? CampPalette.ink : CampPalette.green)
            .padding(.horizontal, 17).padding(.vertical, 12)
            .contentShape(Rectangle())
            .background(primary ? CampPalette.lime : CampPalette.background)
            .clipShape(RoundedRectangle(cornerRadius: 11))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct CampField<Content: View>: View {
    let label: String
    let content: Content
    init(_ label: String, @ViewBuilder content: () -> Content) { self.label = label; self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(label).font(.system(size: 12, weight: .medium)).foregroundStyle(CampPalette.muted)
            content.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct CampTextField: View {
    let title: String
    @Binding var text: String
    var body: some View {
        TextField(title, text: $text).textFieldStyle(.plain)
            .font(.system(size: 14)).padding(11).background(CampPalette.background)
            .clipShape(RoundedRectangle(cornerRadius: 9))
            .accessibilityLabel(title)
    }
}

struct CampToggle: View {
    let title: String
    let detail: String
    @Binding var value: Bool
    var body: some View {
        Toggle(isOn: $value) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 13, weight: .medium))
                Text(detail).font(.system(size: 11)).foregroundStyle(CampPalette.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }.toggleStyle(.switch).tint(CampPalette.green)
    }
}

struct CampTimePicker: View {
    let label: String
    @Binding var minutes: Int
    var body: some View {
        #if os(macOS)
        CampNativeTimePicker(label: label, minutes: $minutes)
            .frame(height: 24)
        #else
        Picker(label, selection: $minutes) {
            ForEach(Self.options, id: \.self) { value in
                Text(Self.label(value)).tag(value)
            }
        }.labelsHidden().accessibilityLabel(label)
        #endif
    }
    private static let options = Array(stride(from: 360, through: 1260, by: 5))
    static func label(_ minutes: Int) -> String {
        let hour = minutes / 60
        return "\(hour % 12 == 0 ? 12 : hour % 12):\(String(format: "%02d", minutes % 60)) \(hour >= 12 ? "PM" : "AM")"
    }
}

struct CampNumberStepper: View {
    let label: String
    @Binding var value: Int
    var range: ClosedRange<Int>
    var step = 1
    var suffix = ""
    var money = false
    var body: some View {
        HStack {
            Text(money ? LunchStyle.money(value) : "\(value)\(suffix)")
                .font(.system(size: 15, weight: .semibold, design: .rounded)).monospacedDigit()
            Spacer()
            Stepper(label, value: $value, in: range, step: step).labelsHidden().fixedSize()
                .accessibilityLabel(label)
        }.padding(10).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 9))
    }
}

struct CampPair<Content: View>: View {
    let compact: Bool
    let content: Content
    init(compact: Bool, @ViewBuilder content: () -> Content) { self.compact = compact; self.content = content() }
    var body: some View {
        if compact { VStack(alignment: .leading, spacing: 17) { content } }
        else { HStack(alignment: .top, spacing: 22) { content } }
    }
}

#if os(macOS)
/// Build the menu once per native control, rather than 181 SwiftUI labels per layout.
private struct CampNativeTimePicker: NSViewRepresentable {
    let label: String
    @Binding var minutes: Int
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSPopUpButton {
        let button = NSPopUpButton(frame: .zero, pullsDown: false)
        for value in stride(from: 360, through: 1260, by: 5) {
            button.addItem(withTitle: CampTimePicker.label(value))
            button.lastItem?.tag = value
        }
        button.target = context.coordinator
        button.action = #selector(Coordinator.selectTime(_:))
        button.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return button
    }
    @Environment(\.isEnabled) private var isEnabled
    func updateNSView(_ button: NSPopUpButton, context: Context) {
        context.coordinator.parent = self
        button.setAccessibilityLabel(label)
        button.isEnabled = isEnabled
        if button.selectedItem?.tag != minutes { button.selectItem(withTag: minutes) }
    }
    final class Coordinator: NSObject {
        var parent: CampNativeTimePicker
        init(_ parent: CampNativeTimePicker) { self.parent = parent }
        @objc func selectTime(_ sender: NSPopUpButton) {
            if let item = sender.selectedItem { parent.minutes = item.tag }
        }
    }
}
#endif
