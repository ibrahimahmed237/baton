import SwiftUI
import BatonKit

/// A fixture-ready menu-bar popover; every label comes from engine data.
public struct PopoverView: View {
    @Environment(\.batonTheme) private var theme
    @ObservedObject private var model: PopoverViewModel
    private let linkRecent: () -> Void

    /// Shows an injected model and delegates opening the suggestion screen.
    public init(model: PopoverViewModel, linkRecent: @escaping () -> Void = {}) {
        self.model = model; self.linkRecent = linkRecent
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let note = model.errorNote { NoteView(note: note) }
            if model.links.isEmpty, let empty = model.notes.first(where: { $0.id == "screen.empty" }) {
                NoteView(note: empty)
            }
            ForEach(model.links, id: \.linkID) { link in
                Button { model.select(linkID: link.linkID) } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Circle().fill(theme.colour(for: rowMeaning(link)))
                            .frame(width: 7, height: 7).padding(.top, 5).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                ForEach(link.sides.keys.sorted(), id: \.self) { tool in ToolDot(tool: tool) }
                            }.font(.caption)
                            ForEach(Array(Set(link.sides.values.map(\.name))).sorted(), id: \.self) { name in
                                Text(name).font(.headline)
                            }
                            Text(link.headline.statusLine ?? link.headline.text)
                                .font(.callout).foregroundStyle(theme.secondaryText)
                        }
                        Spacer(minLength: 0)
                        if link.decisionNeeded {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(theme.colour(for: .danger))
                                .accessibilityLabel(link.headline.text)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(10)
                        .background(theme.colour(for: .action).opacity(model.selectedLinkID == link.linkID ? 0.1 : 0),
                                    in: RoundedRectangle(cornerRadius: 9))
                }.buttonStyle(.plain)
            }
            if let selected = model.selectedLink {
                HStack {
                    ForEach(selected.sides.keys.sorted(), id: \.self) { tool in
                        if let note = model.notes.first(where: { $0.id == "screen.continue" && $0.values["tool"] == .string(tool) }) {
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
        }.padding(16).frame(width: 380).background(theme.background)
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
    /// Receives the badge state without calculating sync behaviour.
    public init(needsDecision: Bool) { self.needsDecision = needsDecision }
    public var body: some View {
        Image(systemName: "link")
            .overlay(alignment: .topTrailing) {
                if needsDecision { Circle().fill(theme.colour(for: .danger)).frame(width: 5, height: 5) }
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
