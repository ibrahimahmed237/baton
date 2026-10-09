import AppKit
import SwiftUI
import BatonKit

/// A fixture-ready menu-bar popover; every label comes from engine data.
public struct PopoverView: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @ObservedObject private var model: PopoverViewModel
    private let linkRecent: () -> Void

    /// Shows an injected model and delegates opening the suggestion screen.
    public init(model: PopoverViewModel, linkRecent: @escaping () -> Void = {}) {
        self.model = model; self.linkRecent = linkRecent
    }

    public var body: some View {
        WindowScrollArea(snapshotClips: false) {
        VStack(alignment: .leading, spacing: 14) {
            if let note = model.errorNote { NoteView(note: note) }
            if model.loading, model.links.isEmpty { ProgressView().frame(maxWidth: .infinity).padding() }
            if let content = model.emptyContent { EmptyStateView(content: content, compact: true) }
            ForEach(model.links, id: \.linkID) { link in
                Button { model.select(linkID: link.linkID) } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Circle().fill(theme.colour(for: rowMeaning(link)))
                            .frame(width: 7, height: 7).padding(.top, 5).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                ForEach(link.sides.keys.sorted(), id: \.self) { tool in ToolDot(tool: tool, label: link.sides[tool]?.displayLabel) }
                            }.font(.caption)
                            ForEach(Array(Set(link.sides.values.map(\.name))).sorted(), id: \.self) { name in
                                Text(name).font(.headline)
                            }
                            Text(link.headline.statusLine ?? link.headline.text)
                                .font(.callout).foregroundStyle(theme.colour(for: rowMeaning(link)))
                        }
                        Spacer(minLength: 0)
                        if link.decisionNeeded {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(theme.colour(for: .danger))
                                .accessibilityLabel(link.headline.text)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(10).contentShape(Rectangle())
                        .background(theme.colour(for: .action).opacity(model.selectedLinkID == link.linkID ? 0.1 : 0),
                                    in: RoundedRectangle(cornerRadius: 9))
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
        }.padding(16)
        }.frame(width: 380, height: snapshot ? nil : 460).background { GlassBackdrop() }.environment(\.colorScheme, theme.scheme).preferredColorScheme(theme.scheme)
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
        let renderer = ImageRenderer(content: BatonMenuIcon(needsDecision: needsDecision,
            reduceTransparency: reduceTransparency ?? NSWorkspace.shared.accessibilityDisplayShouldReduceTransparency)
            .font(.system(size: 14)).foregroundStyle(theme.text)
            .frame(width: 26, height: 22).batonTheme(theme))
        renderer.scale = 2
        let image = renderer.nsImage
        image?.isTemplate = false
        return image
    }
    public var body: some View {
        BrandMark(size: 22, reduceTransparency: reduceTransparency)
            .frame(width: 26, height: 22, alignment: .leading)
            .overlay(alignment: .topTrailing) {
                if needsDecision {
                    Circle().fill(theme.colour(for: .danger)).frame(width: 5, height: 5)
                        .overlay(Circle().strokeBorder(theme.background, lineWidth: 0.75))
                }
            }
    }
}

private struct PopoverActionStyle: ButtonStyle {
    @Environment(\.batonTheme) private var theme
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.callout.weight(.semibold))
            .padding(.horizontal, 10).padding(.vertical, 8)
            .foregroundStyle(theme.colour(for: .action))
            .background(theme.colour(for: .action).opacity(configuration.isPressed ? 0.2 : 0.1),
                        in: RoundedRectangle(cornerRadius: 8))
    }
}
