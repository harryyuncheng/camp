import SwiftUI

struct CampCalendarView: View {
    @ObservedObject var store: CampSettingsStore
    var body: some View {
        #if os(macOS)
        CampCard("Make time for lunch", subtitle: "Use the calendars already connected to your Mac.") {
            VStack(alignment: .leading, spacing: 10) {
                Label(store.lunchCalendar.summary, systemImage: "calendar").font(.headline)
                Text(store.lunchCalendar.detail).font(.caption).foregroundStyle(CampPalette.muted)
                if let busy = store.lunchCalendar.busyNow {
                    CampBadge(text: busy ? "Busy now (including buffer)" : "Free now", active: !busy)
                }
                ForEach(Array(store.lunchCalendar.freeWindows.enumerated()), id: \.offset) { _, interval in
                    HStack {
                        Image(systemName: "clock").foregroundStyle(CampPalette.green)
                        Text(store.lunchCalendar.label(interval)).font(.callout.weight(.medium))
                        Spacer()
                        Text("\(Int(interval.duration / 60)) min free").font(.caption).foregroundStyle(CampPalette.muted)
                    }.padding(12).background(CampPalette.background).clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
            HStack {
                if !store.lunchCalendar.enabled || !store.lunchCalendar.canRead {
                    Button(store.lunchCalendar.requesting ? "Waiting for permission…" : "Connect calendars") { store.lunchCalendar.connect() }
                        .buttonStyle(CampActionStyle()).disabled(store.lunchCalendar.requesting)
                } else {
                    Button("Refresh") { store.lunchCalendar.refresh() }.buttonStyle(CampActionStyle(primary: false))
                    Button("Pause") { store.lunchCalendar.pause() }.buttonStyle(.plain)
                }
                Button("Calendar settings") { store.lunchCalendar.openSettings() }.buttonStyle(.plain).font(.caption)
            }
            if store.lunchCalendar.enabled && store.lunchCalendar.canRead {
                Divider()
                Text("Calendars that block lunch").font(.callout.weight(.semibold))
                if store.lunchCalendar.calendars.isEmpty {
                    Text("No calendars found. Add an account in the Mac Calendar app, then refresh.").font(.caption)
                }
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(store.lunchCalendar.calendars) { calendar in
                        Toggle(isOn: Binding(get: { store.lunchCalendar.selected.contains(calendar.id) },
                                             set: { store.lunchCalendar.select(calendar.id, enabled: $0) })) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(calendar.name).font(.callout)
                                Text(calendar.account).font(.caption).foregroundStyle(CampPalette.muted)
                            }
                        }.toggleStyle(.checkbox)
                    }
                    ForEach(Array(store.lunchCalendar.missingSelections).sorted(), id: \.self) { id in
                        Button("Remove unavailable calendar selection") { store.lunchCalendar.select(id, enabled: false) }.font(.caption)
                    }
                }
                Toggle("All-day events block lunch", isOn: Binding(get: { store.lunchCalendar.blockAllDay }, set: { store.lunchCalendar.setBlockAllDay($0) }))
                    .toggleStyle(.switch).font(.callout)
            }
            Text("Uses your saved lunch window and meeting buffer in You. Calendar selections save automatically. Tentative events count as busy; free, cancelled and declined events do not. camp never edits your calendars.")
                .font(.caption).foregroundStyle(CampPalette.muted)
        }
        #else
        CampCard("Calendars") { Text("Connect your calendars in the Mac app. iPhone calendar access is not connected yet.").font(.callout) }
        #endif
    }
}
