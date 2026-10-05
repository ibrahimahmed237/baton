import SwiftUI
import BatonKit

/// Both sides' confirmed position and the shared conversation.
public struct SyncStatusView: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @ObservedObject private var model: SyncStatusViewModel
    public init(model: SyncStatusViewModel) { self.model = model }
    public var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let status = model.status {
                header(status)
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 14) {
                        ForEach(model.tools, id: \.self) { tool in
                            if let side = status.sides[tool] { sideCard(side).frame(minWidth: 280) }
                        }
                    }
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(model.tools, id: \.self) { tool in
                            if let side = status.sides[tool] { sideCard(side) }
                        }
                    }
                }
                ForEach(Array(status.notes.filter { !$0.id.hasPrefix("screen.") && !$0.id.hasPrefix("filter.") && !$0.id.hasPrefix("turn.") && !$0.id.hasPrefix("message.") && !["status.reached", "status.tool_activity"].contains($0.id) }.enumerated()), id: \.offset) { _, note in
                    NoteView(note: note, enabled: { button in model.tools.first.map { model.supportsSideAction(button, tool: $0) } ?? false }) { button in
                        if let tool = model.tools.first { Task { await model.sideAction(button, tool: tool) } }
                    }
                }
                strip(status)
                filters
                conversation
                if let history = model.history {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(history, id: \.id) { entry in Text(entry.text); Text(entry.at).font(.caption) }
                    }
                }
                if let plan = model.plan {
                    PlanSteps(steps: plan.steps, excludingNotes: plan.notes)
                    ConfirmBar(notes: plan.notes, buttons: model.confirmationButtons) { button in
                        if button.id == "cancel" { model.cancelPlan() }
                        else { Task { await model.confirmPlan() } }
                    }.disabled(model.isConfirming)
                }
            }
            if let error = model.errorNote { NoteView(note: error) }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    private func header(_ status: StatusResult) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let note = model.note("screen.sync_status") { Text(note.text).font(.title2.bold()) }
            HStack {
                labelButton(status.paused ? "screen.resume" : "screen.pause") { Task { await model.togglePause() } }
                labelButton("screen.history") { Task { await model.showHistory() } }
                labelButton("screen.remove") { Task { await model.previewRemoval() } }
                labelButton("screen.refresh") { Task { await model.load(link: status.linkID) } }
            }.buttonStyle(.plain)
        }
    }
    private func sideCard(_ side: Side) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                ToolDot(tool: side.tool)
                Text(side.chat.name).font(.headline)
                Text(side.chat.folder).font(.caption).foregroundStyle(theme.secondaryText)
                ForEach(Array(side.notes.enumerated()), id: \.offset) { _, note in
                    if note.id == "status.context" { MeterBar(percent: side.usage.percent, label: note.text) }
                    else if note.id != "screen.open" { NoteView(note: note, enabled: { model.supportsSideAction($0, tool: side.tool) }) { button in Task { await model.sideAction(button, tool: side.tool) } } }
                }
                if let reached = side.syncedUpTo {
                    Text(reached.firstLine).font(.callout)
                    HStack { ToolDot(tool: reached.origin); Text(reached.startedAt).font(.caption) }
                }
                HStack {
                    if let note = side.notes.first(where: { $0.id == "screen.open" }) {
                        Button(note.text) { Task { await model.open(tool: side.tool) } }.disabled(!side.condition.exists)
                    }
                    if let copy = model.note("screen.copy"), let target = model.tools.first(where: { $0 != side.tool }) {
                        Button(copy.text) { Task { await model.previewCopy(from: side.tool, to: target) } }.disabled(!side.condition.exists)
                    }
                }.buttonStyle(.plain)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }.frame(maxWidth: .infinity, alignment: .topLeading)
    }
    private func strip(_ status: StatusResult) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(model.tools, id: \.self) { tool in
                HStack(alignment: .top, spacing: 8) {
                    ToolDot(tool: tool).frame(width: 95, alignment: .leading)
                    Group {
                        if snapshot { stripBlocks(status, tool: tool) }
                        else { ScrollView(.horizontal) { stripBlocks(status, tool: tool) } }
                    }.frame(height: 27)
                }
            }
        }
    }
    private func stripBlocks(_ status: StatusResult, tool: String) -> some View {
        HStack(spacing: 4) { ForEach(status.turns, id: \.id) { turn in stripBlock(turn, tool: tool) } }
    }
    private func stripBlock(_ turn: Turn, tool: String) -> some View {
        let state = turn.states[tool] ?? ""
        return Button { model.jump(to: turn.id) } label: {
            Text(turn.seq, format: .number).font(.caption).monospacedDigit()
                .frame(width: 27, height: 24)
                .background(theme.colour(for: StateColour.state(state)).opacity(0.3), in: RoundedRectangle(cornerRadius: 4))
        }.buttonStyle(.plain).accessibilityLabel(model.stateLabel(state) ?? state)
    }
    private var filters: some View {
        HStack {
            ForEach(ConversationFilter.allCases, id: \.self) { filter in
                if let note = model.note("filter." + filter.rawValue) {
                    Button(note.text) { model.setFilter(filter) }
                        .fontWeight(model.filter == filter ? .bold : .regular)
                }
            }
        }.buttonStyle(.plain)
    }
    @ViewBuilder private var conversation: some View {
        if snapshot { conversationContent }
        else {
            ScrollViewReader { proxy in
                ScrollView { conversationContent }.frame(minHeight: 300, maxHeight: 450).onChange(of: model.focusedTurn) { _, turn in
                    if let turn { proxy.scrollTo(turn, anchor: .top) }
                }.onAppear { if let turn = model.focusedTurn { proxy.scrollTo(turn, anchor: .top) } }
            }
        }
    }
    private var conversationContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.foldedCount > 0, let folded = model.note("screen.earlier_turns") {
                Button(folded.text) { model.unfold() }.buttonStyle(.plain)
                ForEach(model.tools, id: \.self) { tool in
                    if let reached = model.status?.sides[tool]?.syncedUpTo,
                       !model.displayedTurns.contains(where: { $0.id == reached.id }),
                       let note = model.status?.notes.first(where: { $0.id == "status.reached" && $0.values["tool"] == .string(tool) }) {
                        Text(note.text).font(.caption.weight(.semibold)).foregroundStyle(theme.colour(for: .added))
                    }
                }
            }
            ForEach(model.displayedTurns, id: \.id) { turn in
                turnView(turn).id(turn.id)
                ForEach(model.tools, id: \.self) { tool in
                    if model.status?.sides[tool]?.syncedUpTo?.id == turn.id,
                       let reached = model.status?.notes.first(where: { $0.id == "status.reached" && $0.values["tool"] == .string(tool) }) {
                        Text(reached.text).font(.caption.weight(.semibold)).foregroundStyle(theme.colour(for: .added))
                    }
                }
            }
        }
    }
    private func turnView(_ turn: Turn) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack { ToolDot(tool: turn.origin); Text(turn.startedAt).font(.caption).foregroundStyle(theme.secondaryText) }
            HStack { ForEach(model.tools, id: \.self) { tool in
                if let state = turn.states[tool], let label = model.stateLabel(state) {
                    VStack(alignment: .leading, spacing: 4) { ToolDot(tool: tool).font(.caption); StateChip(state: state, label: label) }
                }
            } }
            ForEach(Array(model.messages(for: turn).enumerated()), id: \.offset) { _, message in
                messageView(message, expanded: model.expandedReplies.contains(turn.id))
            }
            if model.hasCollapsedMessage(in: turn), let note = model.note(model.expandedReplies.contains(turn.id) ? "screen.hide_reply" : "screen.show_reply") {
                Button(note.text) { model.toggleReply(turn.id) }.buttonStyle(.plain)
            }
            if !model.toolMessages(for: turn).isEmpty {
                if let summary = model.note("status.tool_activity", turn: turn.id) ?? model.note("screen.tool_calls", turn: turn.id) { Text(summary.text).font(.caption) }
                if let label = model.note(model.expandedTools.contains(turn.id) ? "screen.hide_tools" : "screen.show_tools") {
                    Button(label.text) { model.toggleTools(turn.id) }.buttonStyle(.plain)
                }
                if model.expandedTools.contains(turn.id) {
                    ForEach(Array(model.toolMessages(for: turn).enumerated()), id: \.offset) { _, message in messageView(message, expanded: true) }
                }
            }
        }.padding(12).background(theme.sidebar.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }
    private func messageView(_ message: TurnMessage, expanded: Bool) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            if let label = model.note("message." + message.kind) { Text(label.text).font(.caption.weight(.semibold)) }
            Text(message.text).lineLimit(!expanded && model.messageNeedsExpansion(message) ? 4 : nil).textSelection(.enabled)
        }
    }
    @ViewBuilder private func labelButton(_ id: String, action: @escaping () -> Void) -> some View {
        if let note = model.note(id) { Button(note.text, action: action) }
    }
}
