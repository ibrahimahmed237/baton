import SwiftUI
import BatonKit

/// A glass dialog showing the engine's tool choices, eligibility and exact plan.
public struct LinkDialogView: View {
    @ObservedObject private var model: LinkDialogViewModel
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @State private var choosingChat = false
    public init(model: LinkDialogViewModel) { self.model = model }
    public var body: some View {
        WindowScrollArea(snapshotClips: false) {
        VStack(alignment: .leading, spacing: 16) {
            if let title = model.label("dialog.link") { Text(title.text).font(.title2.weight(.semibold)) }
            if let source = model.source {
                HStack { ToolDot(tool: source.tool, label: source.displayLabel); Text(source.name).font(.headline) }
            }
            if let note = model.label("dialog.target") { Text(note.text).font(.caption).foregroundStyle(theme.secondaryText) }
            HStack(spacing: 8) {
                ForEach(model.targetTools, id: \.tool) { tool in
                    Button { Task { await model.selectTarget(tool.tool) } } label: {
                        ToolDot(tool: tool.tool, label: tool.displayLabel).padding(10)
                            .background(theme.colour(for: .action).opacity(model.target == tool.tool ? 0.15 : 0.03), in: RoundedRectangle(cornerRadius: 10))
                    }.buttonStyle(.plain)
                }
            }
            if let tool = model.selectedTool {
                ForEach(tool.findings.filter { !$0.ok }, id: \.id) { finding in NoteView(note: finding.note) }
            }
            if model.action == .change, let link = model.currentLink {
                if let note = model.label("dialog.retained_side") { Text(note.text).font(.caption) }
                HStack {
                    ForEach(link.sides.keys.sorted(), id: \.self) { tool in
                        if let chat = link.sides[tool] {
                            Button { Task { await model.selectRetainedSide(tool) } } label: {
                                HStack { ToolDot(tool: tool, label: chat.displayLabel); Text(chat.name) }
                            }.buttonStyle(BatonButtonStyle(meaning: model.retainedTool == tool ? .action : .neutral))
                        }
                    }
                }
            }
            if model.action != .copy && model.action != .fullCopy {
                if let note = model.label("dialog.ways") { Text(note.text).font(.caption) }
                ForEach(model.modes, id: \.mode) { option in
                    VStack(alignment: .leading, spacing: 4) {
                        Button { Task { await model.selectMode(option.mode) } } label: {
                            HStack { Text(option.label.text); Spacer(); if let tag = option.tag { Text(tag.text).font(.caption) } }
                                .padding(10).contentShape(Rectangle()).background(theme.colour(for: .action).opacity(model.mode == option.mode ? 0.12 : 0.03), in: RoundedRectangle(cornerRadius: 8))
                        }.buttonStyle(.plain).disabled(!option.available || (model.targetChat != nil && option.mode == "brief"))
                        if let reason = option.reason { NoteView(note: reason) }
                        if model.targetChat != nil && option.mode == "brief", let reason = model.label("mode.brief_new_chat") { NoteView(note: reason) }
                    }
                }
                if let label = model.label("dialog.target_chat") { Text(label.text).font(.caption) }
                if let newChat = model.label("dialog.new_chat") {
                    Button { choosingChat.toggle() } label: {
                        HStack {
                            Text(model.targetChats.first(where: { $0.id == model.targetChat })?.name ?? newChat.text)
                            Spacer()
                            Image(systemName: "chevron.down")
                        }.padding(10).contentShape(Rectangle()).background(theme.colour(for: .action).opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                    }.buttonStyle(.plain)
                    if choosingChat {
                        WindowScrollArea {
                            VStack(alignment: .leading, spacing: 8) {
                                Button(newChat.text) { choosingChat = false; Task { await model.selectChat(nil) } }
                                ForEach(model.targetChats, id: \.id) { chat in
                                    Button(chat.name) { choosingChat = false; Task { await model.selectChat(chat.id) } }
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }.frame(height: 140)
                    }
                }
            }
            if model.action == .copy || model.action == .fullCopy,
               let option = model.modes.first(where: { $0.mode == "full_copy" && !$0.available }),
               let reason = option.reason { NoteView(note: reason) }
            if let note = model.label("dialog.what_will_happen") { Text(note.text).font(.headline) }
            if let error = model.errorNote { NoteView(note: error) }
            if let plan = model.plan {
                PlanSteps(steps: plan.steps, excludingNotes: model.planNotes)
                ConfirmBar(notes: model.planNotes, buttons: confirmationButtons) { _ in
                    model.markNotesDisplayed(); Task { await model.confirm() }
                }
            }
            HStack {
                ForEach(model.buttons.filter { $0.id != confirmationID && (model.action != .fullCopy || $0.id == "cancel") && $0.id != "full_copy" && ($0.id != "copy_and_link" || model.action == .copy) }, id: \.id) { button in
                    Button(button.label) {
                        if button.id == "cancel" { model.cancel() }
                        else if button.id == "copy_without_linking" { Task { await model.choose(.copy) } }
                        else if button.id == "change_link" { Task { await model.choose(.change) } }
                        else if button.id == "copy_and_link" { Task { await model.choose(.link) } }
                        else if button.id == "create" { Task { await model.choose(.link) } }
                    }.buttonStyle(BatonButtonStyle(meaning: .neutral))
                        .disabled(button.id == "change_link" && model.currentLink == nil)
                }
            }
        }.padding(22)
        }.frame(width: 650, height: snapshot ? nil : 560).background { GlassBackdrop() }
            .environment(\.colorScheme, theme.scheme).disabled(model.isApplying)
    }
    private var confirmationID: String {
        switch model.action { case .link: "create"; case .copy: "copy_without_linking"; case .change: "change_link"; case .fullCopy: "full_copy" }
    }
    private var confirmationButtons: [NoteButton] {
        guard !model.busy, model.plan?.decisionNeeded == false else { return [] }
        return model.buttons.filter { $0.id == confirmationID }
    }
}
