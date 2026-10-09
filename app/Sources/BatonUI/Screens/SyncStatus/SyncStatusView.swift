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
                HStack(alignment: .top, spacing: 14) {
                    ForEach(model.tools, id: \.self) { tool in
                        if let side = status.sides[tool] { sideCard(side).frame(maxWidth: .infinity) }
                    }
                }
                ForEach(Array(status.notes.filter { !$0.id.hasPrefix("empty.") && !$0.id.hasPrefix("screen.") && !$0.id.hasPrefix("filter.") && !$0.id.hasPrefix("turn.") && !$0.id.hasPrefix("message.") && !["status.reached", "status.tool_activity", "status.checked"].contains($0.id) }.enumerated()), id: \.offset) { _, note in
                    NoteView(note: note, enabled: { button in model.tools.first.map { model.supportsSideAction(button, tool: $0) } ?? false }) { button in
                        if let tool = model.tools.first { Task { await model.sideAction(button, tool: tool) } }
                    }
                }
                strip(status)
                GlassCard {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack {
                            if let note = model.note("screen.conversation") { Text(note.text).font(.caption.weight(.semibold)) }
                            Spacer(minLength: 0)
                            filters
                        }
                        conversation
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                if let history = model.history {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(history, id: \.id) { entry in Text(entry.text); Text(DisplayTime.string(entry.at)).font(.caption) }
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
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 8) {
                if let note = model.note("screen.sync_status") { Text(note.text).font(.caption).foregroundStyle(theme.secondaryText) }
                HStack(spacing: 12) {
                    ForEach(model.tools, id: \.self) { tool in
                        if tool != model.tools.first { linkBridge }
                        if let side = status.sides[tool] {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(side.chat.name).font(.system(size: 17, weight: .semibold))
                                ToolDot(tool: tool, label: side.displayLabel).font(.caption)
                            }
                        }
                    }
                }
                if let note = model.note("status.checked") { Text(DisplayTime.noteText(note.text, values: note.values)).font(.caption2).foregroundStyle(theme.secondaryText) }
            }
            Spacer(minLength: 0)
            HStack(spacing: 10) {
                labelButton(status.paused ? "screen.resume" : "screen.pause") { Task { await model.togglePause() } }
                labelButton("screen.history") { Task { await model.showHistory() } }
                labelButton("screen.remove", meaning: .danger) { Task { await model.previewRemoval() } }
                labelButton("screen.refresh") { Task { await model.load(link: status.linkID) } }
            }.font(.caption).buttonStyle(.plain)
        }
    }

    private var linkBridge: some View {
        HStack(spacing: 0) {
            Capsule().fill(theme.hairline).frame(width: 10, height: 1)
            Image(systemName: "arrow.left.arrow.right")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(theme.colour(for: .action))
                .padding(8)
                .background(theme.sidebar.opacity(0.72), in: Circle())
                .overlay(Circle().strokeBorder(theme.hairline, lineWidth: 1))
            Capsule().fill(theme.hairline).frame(width: 10, height: 1)
        }
        .accessibilityHidden(true)
    }

    private func sideCard(_ side: Side) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                ToolDot(tool: side.tool, label: side.displayLabel)
                ForEach(Array(model.displayedNotes(for: side).enumerated()), id: \.offset) { _, note in
                    if note.id == "status.context" { MeterBar(percent: side.usage.percent, label: DisplayTime.noteText(note.text, values: note.values)) }
                    else if !["screen.open", "status.synced_up_to"].contains(note.id) {
                        Text(DisplayTime.noteText(note.text, values: note.values)).font(note.id == "status.summary" ? .system(size: 16, weight: .semibold) : .system(size: 12))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                if let reached = side.syncedUpTo {
                    VStack(alignment: .leading, spacing: 4) {
                        if let line = side.notes.first(where: { $0.id == "status.synced_up_to" }) { Text(DisplayTime.noteText(line.text, values: line.values)).font(.caption) }
                        HStack { ToolDot(tool: reached.origin, label: model.toolLabel(reached.origin)); Text(DisplayTime.string(reached.startedAt)) }.font(.caption2)
                    }.foregroundStyle(theme.secondaryText)
                }
                HStack(spacing: 8) {
                    ForEach(model.sideButtons(side), id: \.id) { button in
                        Button(button.label) { Task { await model.sideAction(button, tool: side.tool) } }
                            .disabled(!model.supportsSideAction(button, tool: side.tool))
                            .buttonStyle(BatonButtonStyle(meaning: ["relaunch", "close_sync_reopen"].contains(button.id) ? .danger : button.id == "add_now" ? .added : .action, compact: true))
                    }
                    if let note = side.notes.first(where: { $0.id == "screen.open" }) {
                        Button(note.text) { Task { await model.open(tool: side.tool) } }.disabled(!side.condition.exists)
                            .buttonStyle(BatonButtonStyle(meaning: .action, compact: true))
                    }
                    if model.sideButtons(side).isEmpty, let copy = model.note("screen.copy"), let target = model.tools.first(where: { $0 != side.tool }) {
                        Button(copy.text) { Task { await model.previewCopy(from: side.tool, to: target) } }.disabled(!side.condition.exists)
                            .buttonStyle(BatonButtonStyle(meaning: .action, compact: true))
                    }
                }.font(.system(size: 10, weight: .semibold)).buttonStyle(.plain)
                if !model.sideButtons(side).isEmpty, let copy = model.note("screen.copy"), let target = model.tools.first(where: { $0 != side.tool }) {
                    Button(copy.text) { Task { await model.previewCopy(from: side.tool, to: target) } }
                        .font(.caption2).buttonStyle(BatonButtonStyle(meaning: .action, compact: true)).disabled(!side.condition.exists)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }.frame(maxWidth: .infinity, alignment: .topLeading)
    }
    private func strip(_ status: StatusResult) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
            if let note = model.note("screen.turn_by_turn") { Text(note.text).font(.caption.weight(.semibold)) }
            ForEach(model.tools, id: \.self) { tool in
                HStack(alignment: .top, spacing: 8) {
                    ToolDot(tool: tool, label: model.toolLabel(tool)).frame(width: 95, alignment: .leading)
                    Group {
                        if snapshot { stripBlocks(status, tool: tool) }
                        else { WindowScrollArea(.horizontal) { stripBlocks(status, tool: tool) } }
                    }.frame(height: snapshot ? 27 : 40)
                }
            }
            }.frame(maxWidth: .infinity, alignment: .leading)
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
                        .buttonStyle(BatonButtonStyle(meaning: model.filter == filter ? .action : .neutral, compact: true))
                }
            }
        }.buttonStyle(.plain)
    }
    @ViewBuilder private var conversation: some View {
        if snapshot { conversationContent }
        else {
            ScrollViewReader { proxy in
                WindowScrollArea { conversationContent }.frame(minHeight: 300, maxHeight: 450).onChange(of: model.focusRequest) { _, _ in
                    if let turn = model.focusedTurn { proxy.scrollTo(turn, anchor: .top) }
                }.onAppear { if let turn = model.focusedTurn { proxy.scrollTo(turn, anchor: .top) } }
                    .onChange(of: model.displayedTurns.map(\.id)) { _, _ in
                        if let turn = model.focusedTurn { proxy.scrollTo(turn, anchor: .top) }
                    }
            }
        }
    }
    private var conversationContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let content = model.emptyConversationContent {
                EmptyStateView(content: content,
                               actionLabel: model.canShowAllTurns ? model.note("screen.show_all_turns") : nil,
                               action: model.canShowAllTurns ? { model.setFilter(.all) } : nil)
            }
            if model.foldedCount > 0, let folded = model.note("screen.earlier_turns") {
                Button(folded.text) { model.unfold() }.buttonStyle(.plain)
            }
            ForEach(model.displayedTurns, id: \.id) { turn in
                VStack(alignment: .leading, spacing: 0) {
                    if turn.id == model.displayedTurns.first?.id, !hiddenTurnNotes.isEmpty {
                        reachedBoundaryGroup(hiddenTurnNotes).padding(.leading, 12)
                        Capsule().fill(theme.colour(for: .added).opacity(0.65))
                            .frame(width: 2, height: 16).padding(.leading, 12)
                            .accessibilityHidden(true)
                    }
                    turnView(turn)
                }.id(turn.id)
            }
        }
    }
    private var hiddenTurnNotes: [Note] {
        model.tools.compactMap { tool in
            guard let reached = model.status?.sides[tool]?.syncedUpTo,
                  !model.displayedTurns.contains(where: { $0.id == reached.id }) else { return nil }
            return model.status?.notes.first(where: {
                $0.id == "status.reached" && $0.values["tool"] == .string(model.toolLabel(tool))
            })
        }
    }
    private func turnView(_ turn: Turn) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 8) {
                Text("Turn \(turn.seq)")
                    .font(.caption.weight(.semibold).monospacedDigit())
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(theme.sidebar, in: Capsule())
                ToolDot(tool: turn.origin, label: model.toolLabel(turn.origin)).font(.caption.weight(.medium))
                Text(DisplayTime.string(turn.startedAt)).font(.caption).foregroundStyle(theme.secondaryText)
                Spacer(minLength: 8)
            }
            HStack(alignment: .center, spacing: 8) {
                ForEach(model.tools, id: \.self) { tool in
                    if let state = turn.states[tool], let label = model.stateLabel(state) {
                        HStack(spacing: 6) {
                            ToolDot(tool: tool, label: model.toolLabel(tool)).font(.caption)
                            StateChip(state: state, label: label)
                        }
                    }
                }
            }
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
            let reachedNotes = model.tools.compactMap { tool -> Note? in
                guard model.status?.sides[tool]?.syncedUpTo?.id == turn.id else { return nil }
                return model.status?.notes.first(where: {
                    $0.id == "status.reached" && $0.values["tool"] == .string(model.toolLabel(tool))
                })
            }
            if !reachedNotes.isEmpty {
                reachedBoundaryGroup(reachedNotes).padding(.top, 2)
            }
        }.padding(12).background(theme.sidebar.opacity(0.55), in: RoundedRectangle(cornerRadius: 10))
    }
    private func reachedBoundaryGroup(_ notes: [Note]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(notes.enumerated()), id: \.offset) { _, note in
                reachedBoundary(note)
            }
        }
        .padding(.leading, 10)
        .overlay(alignment: .leading) {
            Capsule().fill(theme.colour(for: .added).opacity(0.65)).frame(width: 2)
        }
        .accessibilityElement(children: .contain)
    }
    private func reachedBoundary(_ note: Note) -> some View {
        HStack(alignment: .center, spacing: 7) {
            Image(systemName: "arrow.turn.down.right")
                .font(.caption2.weight(.semibold))
                .accessibilityHidden(true)
            Text(note.text).font(.caption.weight(.semibold))
        }
        .foregroundStyle(theme.colour(for: .added))
        .accessibilityElement(children: .combine)
    }
    private func messageView(_ message: TurnMessage, expanded: Bool) -> some View {
        HStack {
            if message.kind == "prompt" { Spacer(minLength: 50) }
            VStack(alignment: .leading, spacing: 5) {
                if let label = model.note("message." + message.kind) { Text(label.text).font(.caption.weight(.semibold)).foregroundStyle(theme.secondaryText) }
                Text(message.text).font(.system(size: 13)).lineLimit(!expanded && model.messageNeedsExpansion(message) ? 4 : nil).textSelection(.enabled)
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                .background(message.kind == "prompt" ? theme.colour(for: .action).opacity(0.1) : theme.sidebar.opacity(0.45), in: RoundedRectangle(cornerRadius: 12))
            if message.kind != "prompt" { Spacer(minLength: 50) }
        }
    }
    @ViewBuilder private func labelButton(_ id: String, meaning: StateColour = .action, action: @escaping () -> Void) -> some View {
        if let note = model.note(id) { Button(note.text, action: action).buttonStyle(BatonButtonStyle(meaning: meaning, compact: true)) }
    }
}
