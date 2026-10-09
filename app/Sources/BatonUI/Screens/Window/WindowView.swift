import SwiftUI
import BatonKit

/// Sidebar, lists and a detail host for the later screens.
public struct WindowView: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonGlass) private var glass
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var linkDialog: LinkDialogViewModel?
    @StateObject private var settingsModel: SettingsViewModel
    @StateObject private var statusModel: SyncStatusViewModel
    @ObservedObject private var appearance: ThemePreference
    @ObservedObject private var model: WindowViewModel
    /// Shows the engine-backed window model.
    public init(model: WindowViewModel, statusModel: SyncStatusViewModel? = nil, appearance: ThemePreference? = nil) {
        let preference = appearance ?? .shared
        self.appearance = preference
        _settingsModel = StateObject(wrappedValue: model.makeSettingsModel(appearance: preference))
        self.model = model
        _statusModel = StateObject(wrappedValue: statusModel ?? model.makeStatusModel())
    }
    public var body: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(model.sections, id: \.self) { destination in
                    if let note = model.label(for: destination) {
                        Button { model.navigate(to: destination) } label: {
                            HStack { Text(note.text); Spacer(minLength: 0) }
                                .font(.callout.weight(model.section == destination ? .semibold : .regular))
                                .padding(10).contentShape(Rectangle()).background(theme.colour(for: .action)
                                    .opacity(model.section == destination ? 0.12 : 0), in: RoundedRectangle(cornerRadius: 8))
                        }.buttonStyle(.plain)
                    }
                }
                if model.section == .linked || model.section == .attention {
                    Rectangle().fill(theme.hairline).frame(height: 1).padding(.vertical, 8)
                    WindowScrollArea { listContent }
                }
                Spacer(minLength: 12)
                ThemeSelector(preference: appearance, notes: model.notes)
            }.padding(12).frame(width: 205).frame(maxHeight: .infinity, alignment: .top)
                .background { Rectangle().fill(.regularMaterial).overlay(theme.sidebar.opacity(reduceTransparency ? 1 : glass / 200)) }
            if model.section != .linked && model.section != .attention && model.section != .settings {
                VStack(alignment: .leading, spacing: 14) {
                    if let label = model.label(for: model.section) { Text(label.text).font(.title2.weight(.semibold)) }
                    WindowScrollArea { listContent }
                }.padding(20).frame(width: 260).frame(maxHeight: .infinity, alignment: .top)
            }
            Rectangle().fill(theme.hairline).frame(width: 1)
            WindowScrollArea {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = model.errorNote { NoteView(note: error) }
                    if model.section == .settings { SettingsView(model: settingsModel, appearance: appearance, fallbackNotes: model.notes) }
                    else { detail }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
        }.frame(minWidth: 1000, idealWidth: 1000, maxWidth: .infinity, minHeight: 600, idealHeight: 600, maxHeight: .infinity).background { GlassBackdrop().ignoresSafeArea(.container, edges: .top) }
            .background(WindowGlassChrome(theme: theme)).environment(\.colorScheme, theme.scheme).preferredColorScheme(theme.scheme)
            .task(id: model.selectedLink?.linkID) { if let link = model.selectedLink { await statusModel.load(link: link.linkID) } }
            .sheet(item: Binding(get: { linkDialog.map(DialogItem.init) }, set: { if $0 == nil { linkDialog = nil } })) { item in
                LinkDialogView(model: item.model)
                    .onChange(of: item.model.finished) { _, finished in if finished { linkDialog = nil; Task { await model.refresh() } } }
            }
            .onChange(of: statusModel.removedLinkID) { _, removed in
                if removed != nil { Task { await model.refresh() } }
            }
    }

    @ViewBuilder private var listContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch model.section {
            case .linked, .attention:
                if model.listedLinks.isEmpty { empty }
                ForEach(model.listedLinks, id: \.linkID) { link in
                    row(.link(link.linkID)) { linkSummary(link) }
                }
            case .suggestions:
                if model.suggestions.isEmpty { empty }
                ForEach(model.suggestions.map { IdentifiedSuggestion(selection: model.suggestionSelection($0), suggestion: $0) }) { item in
                    let suggestion = item.suggestion
                    row(model.suggestionSelection(suggestion)) { suggestionSummary(suggestion) }
                }
            case .chats(let tool):
                if (model.chats[tool] ?? []).isEmpty { empty }
                ForEach(model.chats[tool] ?? [], id: \.id) { chat in
                    row(.chat(tool, chat.id)) { chatSummary(chat) }
                }
            case .settings: EmptyView()
            case .activity:
                if model.activity.isEmpty { empty }
                ForEach(model.activity) { entry in
                    row(.event(entry.link.linkID, entry.event.id)) {
                        VStack(alignment: .leading, spacing: 8) {
                            linkSummary(entry.link)
                            Text(entry.event.text).font(.callout)
                            Text(DisplayTime.string(entry.event.at)).font(.caption).foregroundStyle(theme.secondaryText)
                        }
                    }
                }
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private var detail: some View {
        switch model.selection {
        case .link:
            if let link = model.selectedLink {
                if statusModel.status?.linkID == link.linkID {
                    VStack(alignment: .leading, spacing: 12) {
                        SyncStatusView(model: statusModel)
                        if let note = model.notes.first(where: { $0.id == "dialog.actions" }) {
                            ForEach(link.sides.keys.sorted(), id: \.self) { tool in
                                if let chat = link.sides[tool] {
                                    HStack {
                                        ToolDot(tool: tool, label: chat.displayLabel)
                                        ForEach(note.buttons.filter { ["change_link", "full_copy"].contains($0.id) }, id: \.id) { button in
                                            Button(button.label) { presentDialog(chat, link: link, action: button.id == "full_copy" ? .fullCopy : .change) }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                else { linkSummary(link) }
            }
        case .suggestion:
            if let suggestion = model.selectedSuggestion { suggestionSummary(suggestion) }
        case .chat(let tool, let id):
            if let chat = model.chats[tool]?.first(where: { $0.id == id }) {
                VStack(alignment: .leading, spacing: 12) {
                    chatSummary(chat)
                    if let note = model.notes.first(where: { $0.id == "dialog.actions" }) {
                        ForEach(note.buttons.filter { ["create", "copy_without_linking"].contains($0.id) }, id: \.id) { button in
                            Button(button.label) { presentDialog(chat, action: button.id == "create" ? .link : .copy) }
                        }
                    }
                }
            }
        case .event(let link, let id):
            if let entry = model.activity.first(where: { $0.link.linkID == link && $0.event.id == id }) {
                VStack(alignment: .leading, spacing: 12) { linkSummary(entry.link); Text(entry.event.text) }
            }
        case nil:
            if model.loading { ProgressView().frame(maxWidth: .infinity, minHeight: 320) }
            else if let content = model.emptyDetailContent { EmptyStateView(content: content) }
        }
    }

    private func presentDialog(_ chat: Chat, link: LinkSummary? = nil, action: LinkDialogAction) {
        let dialog = model.makeLinkDialogModel(); linkDialog = dialog
        Task {
            await dialog.load(source: chat, link: link, replacing: action == .fullCopy ? chat.tool : nil)
            if action == .copy || action == .change { await dialog.choose(action) }
        }
    }

    @ViewBuilder private var empty: some View {
        if model.loading { ProgressView().frame(maxWidth: .infinity).padding() }
        else if let content = model.emptyListContent { EmptyStateView(content: content, compact: true) }
    }

    private func row<Content: View>(_ selection: WindowSelection, @ViewBuilder content: () -> Content) -> some View {
        Button { model.select(selection) } label: {
            content().frame(maxWidth: .infinity, alignment: .leading).padding(10).contentShape(Rectangle())
                .background(theme.colour(for: .action).opacity(model.selection == selection ? 0.1 : 0),
                            in: RoundedRectangle(cornerRadius: 9))
        }.buttonStyle(.plain)
    }

    private func linkSummary(_ link: LinkSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(link.sides.keys.sorted(), id: \.self) { tool in
                if let chat = link.sides[tool] { chatSummary(chat) }
            }
            Text(link.headline.statusLine ?? link.headline.text).font(.callout).foregroundStyle(theme.secondaryText)
        }
    }

    private func chatSummary(_ chat: Chat) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            ToolDot(tool: chat.tool, label: chat.displayLabel).font(.caption)
            Text(chat.name).font(.headline)
            FolderPathLabel(path: chat.folder)
        }
    }

    private func suggestionSummary(_ suggestion: Suggestion) -> some View {
        VStack(alignment: .leading, spacing: 10) { chatSummary(suggestion.a); chatSummary(suggestion.b) }
    }
}

private struct IdentifiedSuggestion: Identifiable {
    let selection: WindowSelection
    let suggestion: Suggestion
    var id: WindowSelection { selection }
}

private struct DialogItem: Identifiable {
    let model: LinkDialogViewModel
    var id: ObjectIdentifier { ObjectIdentifier(model) }
}

private struct FolderPathLabel: View {
    @Environment(\.batonTheme) private var theme
    let path: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "folder")
                .font(.system(size: 10, weight: .medium))
                .accessibilityHidden(true)
            Text(path)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .foregroundStyle(theme.secondaryText)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(theme.sidebar.opacity(0.72), in: RoundedRectangle(cornerRadius: 7))
        .overlay {
            RoundedRectangle(cornerRadius: 7)
                .stroke(theme.hairline.opacity(0.75), lineWidth: 0.7)
        }
        .help(path)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(path)
    }
}
