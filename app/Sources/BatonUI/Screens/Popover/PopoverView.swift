import AppKit
import SwiftUI
import BatonKit

/// A fixture-ready menu-bar popover; every label comes from engine data.
public struct PopoverView: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @ObservedObject private var model: PopoverViewModel
    private let linkRecent: () -> Void
    private let openWindow: () -> Void
    private let quit: () -> Void
    private let applicationNotes: [Note]

    /// Shows an injected model and delegates opening the suggestion screen.
    public init(model: PopoverViewModel, linkRecent: @escaping () -> Void = {},
                openWindow: @escaping () -> Void = {}, quit: @escaping () -> Void = {}, applicationNotes: [Note] = []) {
        self.model = model; self.linkRecent = linkRecent; self.openWindow = openWindow; self.quit = quit; self.applicationNotes = applicationNotes
    }

    public var body: some View {
        VStack(spacing: 0) {
        WindowScrollArea(snapshotClips: false) {
        VStack(alignment: .leading, spacing: 10) {
            if let note = model.errorNote { NoteView(note: note) }
            if model.loading, model.links.isEmpty { ProgressView().frame(maxWidth: .infinity).padding() }
            if let content = model.emptyContent { EmptyStateView(content: content, compact: true) }
            ForEach(model.links, id: \.linkID) { link in
                Button { model.select(linkID: link.linkID) } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Circle().fill(theme.colour(for: rowMeaning(link)))
                            .frame(width: 7, height: 7).padding(.top, 5).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 7) {
                            HStack {
                                ForEach(link.sides.keys.sorted(), id: \.self) { tool in ToolDot(tool: tool, label: link.sides[tool]?.displayLabel) }
                            }.font(.caption.weight(.medium))
                            ForEach(Array(Set(link.sides.values.map(\.name))).sorted(), id: \.self) { name in
                                Text(name).font(.headline.weight(.semibold)).lineLimit(1)
                            }
                            Text(link.headline.statusLine ?? link.headline.text)
                                .font(.subheadline).foregroundStyle(theme.colour(for: rowMeaning(link)))
                        }
                        Spacer(minLength: 0)
                        if link.decisionNeeded {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(theme.colour(for: .danger))
                                .accessibilityLabel(link.headline.text)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(12).contentShape(Rectangle())
                        .background {
                            RoundedRectangle(cornerRadius: 13).fill(.regularMaterial)
                                .overlay(RoundedRectangle(cornerRadius: 13).fill(theme.sidebar.opacity(0.24)))
                                .overlay(RoundedRectangle(cornerRadius: 13)
                                    .fill(theme.colour(for: .action).opacity(model.selectedLinkID == link.linkID ? 0.085 : 0)))
                                .overlay(RoundedRectangle(cornerRadius: 13)
                                    .stroke(model.selectedLinkID == link.linkID ? theme.colour(for: .action).opacity(0.34) : theme.hairline,
                                            lineWidth: model.selectedLinkID == link.linkID ? 1 : 0.7))
                        }
                }.buttonStyle(.plain)
            }
            if let selected = model.selectedLink {
                HStack {
                    ForEach(selected.sides.keys.sorted(), id: \.self) { tool in
                        if let note = model.continueNote(for: tool) {
                            Button(note.text) { Task { await model.continueIn(tool: tool) } }
                                .buttonStyle(PopoverActionStyle())
                        }
                    }
                }
            }
            if let note = model.notes.first(where: { $0.id == "screen.link_recent" }) {
                Button(action: linkRecent) {
                    HStack { Text(note.text); Spacer(); Text(model.suggestions.count, format: .number) }
                }.buttonStyle(PopoverActionStyle())
            }
            if let plan = model.plan {
                ForEach(Array(plan.notes.enumerated()), id: \.offset) { _, note in NoteView(note: note) }
                PlanSteps(steps: plan.steps, excludingNotes: plan.notes)
            }
        }.padding(13)
        }
        Divider()
        HStack {
            if let note = model.applicationNote("screen.open_window", fallback: applicationNotes) {
                Button(note.text, action: openWindow).buttonStyle(PopoverFooterStyle())
            }
            Spacer()
            if let note = model.applicationNote("screen.quit", fallback: applicationNotes) {
                Button(note.text, action: quit).buttonStyle(PopoverFooterStyle(quiet: true))
            }
        }.font(.caption.weight(.medium)).padding(.horizontal, 13).padding(.vertical, 10)
        }.frame(width: 340, height: snapshot ? nil : 340).background { GlassBackdrop() }.environment(\.colorScheme, theme.scheme).preferredColorScheme(theme.scheme)
    }

    private func rowMeaning(_ link: LinkSummary) -> StateColour {
        if link.decisionNeeded { return .danger }
        if link.paused { return .waiting }
        if link.inSync { return .added }
        switch link.headline.id {
        case "turn.waiting", "write.chat_open", "relaunch_to_see", "reopen_chat_to_see": return .waiting
        default: return StateColour.tone(link.headline.tone)
        }
    }
}

/// The menu-bar icon carries an engine-derived decision badge.
public struct BatonMenuIcon: View {
    @Environment(\.batonTheme) private var theme
    public let needsDecision: Bool
    private let reduceTransparency: Bool?
    /// Receives the badge state without calculating sync behaviour.
    public init(needsDecision: Bool, reduceTransparency: Bool? = nil) {
        self.needsDecision = needsDecision; self.reduceTransparency = reduceTransparency
    }
    /// Flattens the icon and its badge into the image accepted by the system menu bar.
    @MainActor public static func nativeImage(needsDecision: Bool, theme: Theme, reduceTransparency: Bool? = nil) -> NSImage? {
        guard BatonBrand.nativeIcon() != nil else { return nil }
        let renderer = ImageRenderer(content: BatonMenuIcon(needsDecision: needsDecision,
            reduceTransparency: reduceTransparency ?? NSWorkspace.shared.accessibilityDisplayShouldReduceTransparency)
            .frame(width: 26, height: 22).batonTheme(theme))
        renderer.scale = 3
        let image = renderer.nsImage
        image?.isTemplate = false
        return image
    }
    public var body: some View {
        BrandMark(size: 19, placement: .menu)
            .frame(width: 26, height: 22, alignment: .leading)
            .overlay(alignment: .topTrailing) {
                if needsDecision {
                    Circle().fill(theme.menuOutline).frame(width: 5, height: 5)
                        .overlay(Circle().strokeBorder(theme.menuBadgeOutline, lineWidth: 0.75))
                }
            }
    }
}

private struct PopoverActionStyle: ButtonStyle {
    @Environment(\.batonTheme) private var theme
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.callout.weight(.semibold))
            .padding(.horizontal, 12).padding(.vertical, 9)
            .foregroundStyle(theme.colour(for: .action))
            .background(theme.colour(for: .action).opacity(configuration.isPressed ? 0.20 : 0.11),
                        in: Capsule())
            .overlay(Capsule().stroke(theme.colour(for: .action).opacity(0.22), lineWidth: 0.7))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

private struct PopoverFooterStyle: ButtonStyle {
    @Environment(\.batonTheme) private var theme
    var quiet = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.caption.weight(.semibold))
            .foregroundStyle(quiet ? theme.secondaryText : theme.text)
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(theme.sidebar.opacity(configuration.isPressed ? 0.58 : 0.38), in: Capsule())
            .overlay(Capsule().stroke(theme.hairline, lineWidth: 0.65))
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
