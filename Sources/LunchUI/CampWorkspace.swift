import SwiftUI
#if SWIFT_PACKAGE
import LunchCore
#endif

public struct CampWorkspace: View {
    @ObservedObject var store: CampSettingsStore
    let compact: Bool
    let previewActivity: () -> Void

    public init(store: CampSettingsStore, compact: Bool = false, previewActivity: @escaping () -> Void) {
        self.store = store; self.compact = compact; self.previewActivity = previewActivity
    }

    public var body: some View {
        workspace.overlay {
            if store.showOnboarding {
                CampOnboardingFlow(store: store, compact: compact).transition(.opacity)
            }
        }.animation(.easeInOut(duration: 0.2), value: store.showOnboarding)
    }

    private var workspace: some View {
        HStack(spacing: 0) {
            if !compact { sidebar }
            VStack(spacing: 0) {
                if compact { phoneHeader }
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        pageHeader
                        switch store.section {
                        case .today: CampTodayPage(store: store, compact: compact, previewActivity: previewActivity)
                        case .you: CampPersonalPage(store: store, compact: compact)
                        case .office: CampOfficePage(store: store, compact: compact)
                        case .spending: CampSpendingPage(store: store, compact: compact)
                        case .connections: CampConnectionsPage(store: store, compact: compact)
                        case .demo: CampDemoPage(store: store, compact: compact)
                        }
                        if let error = store.saveError {
                            Text(error).font(.callout).foregroundStyle(.red)
                                .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.red.opacity(0.06)).clipShape(RoundedRectangle(cornerRadius: 12))
                        }
                    }.padding(compact ? 18 : 32).frame(maxWidth: 900)
                        .frame(maxWidth: .infinity)
                }
                if store.hasChanges { saveBar }
                if compact { phoneTabs }
            }
        }
        .foregroundStyle(CampPalette.ink).background(CampPalette.background)
        .preferredColorScheme(.light).tint(CampPalette.green)
    }

    private var pageHeader: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: compact ? 29 : 34, weight: .semibold, design: .rounded)).tracking(-0.8)
            if !store.hasChanges, let status = store.statusMessage {
                Label(status, systemImage: "checkmark.circle.fill").font(.caption).foregroundStyle(CampPalette.green)
            }
        }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 28) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                CampLogo().fill(CampPalette.green).frame(width: 32, height: 18)
                    .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                    .accessibilityHidden(true)
                Text("camp").font(.system(size: 32, weight: .bold, design: .rounded)).tracking(-1.5)
            }.padding(.leading, 6).padding(.top, 8)
            VStack(spacing: 7) {
                ForEach(CampSection.main) { section in sidebarTab(section) }
            }
            Spacer()
            sidebarTab(.demo)
            VStack(alignment: .leading, spacing: 12) {
                Label(store.draft.office.name, systemImage: "building.2").font(.system(size: 12, weight: .medium))
                Divider()
                Toggle("Demo admin", isOn: $store.isDemoAdmin).font(.system(size: 11)).toggleStyle(.switch).controlSize(.small)
            }
        }.frame(width: 190).padding(22).background(.white)
            .overlay(alignment: .trailing) { CampPalette.border.frame(width: 1) }
    }

    private func sidebarTab(_ section: CampSection) -> some View {
        Button { store.section = section } label: {
            HStack(spacing: 11) {
                Image(systemName: section.symbol).frame(width: 20)
                Text(section.rawValue).font(.system(size: 13, weight: store.section == section ? .semibold : .regular)).lineLimit(1)
                Spacer()
            }.frame(maxWidth: .infinity, minHeight: 20, alignment: .leading).padding(13).contentShape(Rectangle()).background(store.section == section ? CampPalette.lime.opacity(0.5) : .clear)
                .clipShape(RoundedRectangle(cornerRadius: 11))
        }.buttonStyle(.plain)
    }

    private var phoneHeader: some View {
        HStack {
            HStack(spacing: 8) { CampLogo().fill(CampPalette.green).frame(width: 30, height: 18).accessibilityHidden(true); Text("camp").font(.system(size: 24, weight: .bold, design: .rounded)) }
            Spacer()
            Menu {
                Toggle("Demo admin", isOn: $store.isDemoAdmin)
                Button("Preview activity", action: previewActivity)
            } label: {
                CampBadge(text: store.isDemoAdmin ? "Demo admin" : "Member", active: store.isDemoAdmin)
            }
        }.padding(.horizontal, 20).padding(.vertical, 12).background(.white)
    }

    private var phoneTabs: some View {
        HStack(spacing: 0) {
            ForEach(CampSection.allCases) { section in
                Button { store.section = section } label: {
                    VStack(spacing: 5) {
                        Image(systemName: section.symbol).font(.system(size: 18))
                        Text(section.rawValue).font(.system(size: 10, weight: .medium))
                    }.frame(maxWidth: .infinity).padding(.vertical, 12).contentShape(Rectangle())
                        .foregroundStyle(store.section == section ? CampPalette.green : CampPalette.muted)
                }.buttonStyle(.plain).accessibilityLabel(section.rawValue)
            }
        }.background(.white).overlay(alignment: .top) { CampPalette.border.frame(height: 1) }
    }

    private var saveBar: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let error = store.validationErrors.first { Text(error).font(.caption).foregroundStyle(.red) }
            HStack {
                Text("Unsaved changes").font(.system(size: 12)).foregroundStyle(CampPalette.muted)
                Spacer()
                Button("Discard") { store.discard() }.buttonStyle(.plain).font(.system(size: 12))
                Button("Save") { store.save() }.buttonStyle(CampActionStyle())
                    .disabled(!store.validationErrors.isEmpty)
            }
        }.padding(.horizontal, compact ? 18 : 32).padding(.vertical, 12).background(.white)
            .overlay(alignment: .top) { CampPalette.border.frame(height: 1) }
    }

    private var title: String {
        switch store.section {
        case .today: return "Orders, handled."
        case .you: return "Your preferences"
        case .office: return "Office"
        case .spending: return "Spending"
        case .connections: return "Connections"
        case .demo: return "Demo"
        }
    }
}
