import SwiftUI
import BatonKit

/// What will happen, per tool, with the engine's notes and its offered choices.
/// Choices stay disabled, and the model refuses them, until these notes have appeared.
public struct PlanReviewView: View {
    @ObservedObject private var model: PlanReviewViewModel
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    /// Called with the way the review ended; the host dismisses the sheet.
    private let finish: (PlanOutcome) -> Void
    private let chooseCounterpart: ((PlanRequest) -> Void)?

    public init(model: PlanReviewViewModel, finish: @escaping (PlanOutcome) -> Void = { _ in }, chooseCounterpart: ((PlanRequest) -> Void)? = nil) {
        self.model = model; self.finish = finish; self.chooseCounterpart = chooseCounterpart
    }

    public var body: some View {
        WindowScrollArea(snapshotClips: false) {
            VStack(alignment: .leading, spacing: 16) {
                if let title = model.label("dialog.what_will_happen") { Text(title.text).font(.title2.weight(.semibold)) }
                if let error = model.errorNote { NoteView(note: error) }
                if model.busy, model.plan == nil { ProgressView().frame(maxWidth: .infinity).padding() }
                if let plan = model.plan {
                    if !model.replying.isEmpty { replyingChats }
                    PlanSteps(steps: plan.steps, excludingNotes: model.planNotes)
                    if let note = model.alternativeNote {
                        NoteView(note: Note(id: note.id, tone: note.tone, values: note.values, text: note.text,
                                            buttons: note.buttons.filter { $0.id == "choose_chat" }, statusLine: note.statusLine),
                                 enabled: { _ in chooseCounterpart != nil && !model.busy }) { _ in
                            if let original = model.originalRequest { chooseCounterpart?(original) }
                        }
                    }
                    if model.outcome == nil, let receipt = model.displayReceipt {
                        let actions = model.actions
                        ConfirmBar(notes: receipt.notes, buttons: actions.map(\.button), revision: receipt.identity,
                                   enabled: { index, _ in model.canChoose(actions[index]) }) { index, _ in
                            Task { await model.choose(actions[index]) }
                        }
                        .id(receipt.identity)
                        .onAppear { model.didDisplay(receipt) }
                        .disabled(model.busy)
                    } else {
                        ForEach(Array(model.planNotes.enumerated()), id: \.offset) { _, note in
                            NoteView(note: Note(id: note.id, tone: note.tone, values: note.values, text: note.text, buttons: [], statusLine: note.statusLine))
                        }
                    }
                }
            }.padding(22)
        }
        .frame(width: 650, height: snapshot ? nil : 560).background { GlassBackdrop() }
        .environment(\.colorScheme, theme.scheme)
        .onChange(of: model.outcome) { _, outcome in if let outcome { finish(outcome) } }
    }

    /// The chats the engine says are replying right now; names are data, the warning is the notes.
    private var replyingChats: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(model.replying, id: \.id) { chat in
                HStack(spacing: 8) { ToolDot(tool: chat.tool, label: chat.displayLabel); Text(chat.name).font(.headline) }
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(theme.colour(for: .waiting).opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(theme.colour(for: .waiting).opacity(0.35)))
    }
}
