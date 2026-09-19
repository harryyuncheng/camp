import SwiftUI

struct CampCalendarView: View {
    @ObservedObject var store: CampSettingsStore
    @State private var choosingCalendars = false
    var body: some View {
        #if os(macOS)
        CampCard("Today’s calendar", subtitle: "See your blockers and a suggested time for lunch.") {
            if store.lunchCalendar.enabled && store.lunchCalendar.canRead {
                Button { choosingCalendars.toggle() } label: {
                    HStack {
                        Image(systemName: "calendar")
                        Text(store.lunchCalendar.selected.isEmpty ? "Select calendars" : "\(store.lunchCalendar.selected.count) calendars selected")
                        Spacer()
                        Image(systemName: "chevron.down")
                    }.font(.callout).padding(12).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 10))
                }.buttonStyle(.plain).popover(isPresented: $choosingCalendars, arrowEdge: .bottom) { calendarPicker }
            }
            if let day = store.lunchCalendar.timelineDay, store.lunchCalendar.checkedAt != nil {
                CampDayTimeline(calendar: store.lunchCalendar, day: day)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(store.lunchCalendar.summary).font(.headline)
                    Text(store.lunchCalendar.detail).font(.caption).foregroundStyle(CampPalette.muted)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(20).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 12))
            }
            HStack {
                if !store.lunchCalendar.enabled || !store.lunchCalendar.canRead {
                    Button(store.lunchCalendar.requesting ? "Waiting for permission…" : "Connect calendars") { store.lunchCalendar.connect() }
                        .buttonStyle(CampActionStyle()).disabled(store.lunchCalendar.requesting)
                } else {
                    Button("Refresh") { store.lunchCalendar.refresh() }.buttonStyle(CampActionStyle(primary: false))
                }
                Spacer()
                Menu {
                    Button("Calendar settings") { store.lunchCalendar.openSettings() }
                    if store.lunchCalendar.enabled { Button("Pause calendar access") { store.lunchCalendar.pause() } }
                    Toggle("All-day events block lunch", isOn: Binding(get: { store.lunchCalendar.blockAllDay }, set: { store.lunchCalendar.setBlockAllDay($0) }))
                } label: { Image(systemName: "ellipsis.circle").font(.title3) }.menuStyle(.borderlessButton).fixedSize()
            }
            Text("Lunch is a suggestion, not a calendar event. Busy blocks include your meeting buffer. Adjust lunch timing in You.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }
        #else
        CampCard("Calendars") { Text("Connect your calendars in the Mac app. iPhone calendar access is not connected yet.").font(.callout) }
        #endif
    }
    #if os(macOS)
    private var calendarPicker: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack { Text("Show calendars").font(.headline); Spacer(); Button("Done") { choosingCalendars = false } }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(store.lunchCalendar.calendars) { calendar in
                        Toggle(isOn: Binding(get: { store.lunchCalendar.selected.contains(calendar.id) }, set: { store.lunchCalendar.select(calendar.id, enabled: $0) })) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(calendar.name).font(.callout)
                                Text(calendar.account).font(.caption).foregroundStyle(CampPalette.muted)
                            }
                        }.toggleStyle(.checkbox)
                    }
                    ForEach(Array(store.lunchCalendar.missingSelections).sorted(), id: \.self) { id in
                        Button("Remove unavailable calendar") { store.lunchCalendar.select(id, enabled: false) }.font(.caption)
                    }
                    if store.lunchCalendar.calendars.isEmpty { Text("Add an account in the Mac Calendar app, then refresh.").font(.caption) }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 280)
        }.padding(18).frame(width: 300)
    }
    #endif
}

#if os(macOS)
private struct CampDayTimeline: View {
    @ObservedObject var calendar: MacLunchCalendar
    let day: DateInterval
    private let hourHeight: CGFloat = 64
    private var hours: Int { Int(day.duration / 3600) }
    private var height: CGFloat { CGFloat(day.duration / 3600) * hourHeight }
    private var lunch: DateInterval? { calendar.suggestedLunch }
    private var title: String {
        let formatter = DateFormatter(); formatter.timeZone = TimeZone(identifier: calendar.timezone)
        formatter.dateFormat = "EEEE, MMM d"
        return formatter.string(from: day.start)
    }
    private func time(_ date: Date) -> String {
        let formatter = DateFormatter(); formatter.timeZone = TimeZone(identifier: calendar.timezone)
        formatter.dateFormat = "h a"
        return formatter.string(from: date)
    }
    private func y(_ date: Date) -> CGFloat { CGFloat(date.timeIntervalSince(day.start) / 3600) * hourHeight }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.headline)
                Spacer()
                Text(calendar.timezone).font(.caption).foregroundStyle(CampPalette.muted)
            }
            HStack(spacing: 14) {
                Label("Busy + buffer", systemImage: "square.fill").foregroundStyle(Color(red: 0.45, green: 0.52, blue: 0.65))
                Label("Suggested lunch", systemImage: "square.fill").foregroundStyle(CampPalette.green)
            }.font(.caption)
            ScrollViewReader { proxy in
                ScrollView(.vertical) {
                    ZStack(alignment: .topLeading) {
                        VStack(spacing: 0) {
                        ForEach(0..<hours, id: \.self) { hour in
                            HStack(alignment: .top, spacing: 8) {
                                Text(time(day.start.addingTimeInterval(Double(hour) * 3600))).font(.system(size: 10)).foregroundStyle(CampPalette.muted).frame(width: 44, alignment: .trailing)
                                Rectangle().fill(CampPalette.border).frame(height: 1)
                            }.frame(height: hourHeight, alignment: .top).id("hour-\(hour)")
                        }
                        }
                        GeometryReader { geometry in
                            ForEach(Array(calendar.busyBlocks.enumerated()), id: \.offset) { _, block in
                                blockView("Busy", interval: block, isLunch: false)
                                    .frame(width: max(0, geometry.size.width - 66), height: max(12, y(block.end) - y(block.start)), alignment: .topLeading)
                                    .offset(x: 56, y: y(block.start))
                            }
                            if let lunch {
                                blockView("Lunch · suggested", interval: lunch, isLunch: true)
                                    .frame(width: max(0, geometry.size.width - 66), height: max(12, y(lunch.end) - y(lunch.start)), alignment: .topLeading)
                                    .offset(x: 56, y: y(lunch.start))
                            }
                            if let now = calendar.checkedAt, now >= day.start && now < day.end {
                                Rectangle().fill(Color.red.opacity(0.65)).frame(height: 1).offset(y: y(now))
                            }
                        }
                    }.frame(height: height).padding(.vertical, 8)
                }.frame(height: 440).background(.white).clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(CampPalette.border))
                    .onAppear { scroll(proxy) }
                    .onChange(of: day.start) { _ in scroll(proxy) }
            }
            if let lunch {
                Text("Suggested lunch: \(calendar.label(lunch))").font(.callout.weight(.medium)).foregroundStyle(CampPalette.green)
            } else { Text(calendar.summary).font(.callout).foregroundStyle(CampPalette.muted) }
        }
    }
    private func blockView(_ title: String, interval: DateInterval, isLunch: Bool) -> some View {
        HStack(spacing: 0) {
            Rectangle().fill(isLunch ? CampPalette.green : Color(red: 0.45, green: 0.52, blue: 0.65)).frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 11, weight: .semibold)).lineLimit(1)
                if interval.duration >= 2700 { Text(calendar.label(interval)).font(.system(size: 10)).lineLimit(1) }
            }.padding(.horizontal, 8)
            Spacer(minLength: 0)
        }.frame(maxHeight: .infinity).background(isLunch ? Color(red: 0.84, green: 0.94, blue: 0.76) : Color(red: 0.90, green: 0.93, blue: 0.97))
            .clipShape(RoundedRectangle(cornerRadius: 5)).clipped()
            .help("\(title): \(calendar.label(interval))")
            .accessibilityLabel("\(title), \(calendar.label(interval))")
    }
    private func scroll(_ proxy: ScrollViewProxy) {
        let hour = max(0, min(hours - 1, Int((lunch?.start ?? day.start.addingTimeInterval(10 * 3600)).timeIntervalSince(day.start) / 3600) - 1))
        proxy.scrollTo("hour-\(hour)", anchor: .top)
    }
}
#endif
