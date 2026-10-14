import SwiftUI
import AppKit
import BatonKit

public struct SecondOpinionView: View {
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @Environment(\.batonTheme) private var theme
    @ObservedObject private var model: SecondOpinionViewModel
    public init(model: SecondOpinionViewModel) { self.model = model }
    public var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let turn = model.turn {
                GlassCard {
                    VStack(alignment: .leading, spacing: 10) {
                        if let messages = turn.messages, !messages.isEmpty {
                            ForEach(Array(messages.enumerated()), id: \.offset) { _, message in Text(message.text).textSelection(.enabled) }
                        } else { Text(turn.firstLine).font(.headline) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            if let plan = model.response?.plan, model.response?.stage == "add" { PlanSteps(steps: plan.steps, excludingNotes: model.notes) }
            if snapshot { Text(model.question).font(.title3).textSelection(.enabled) }
            else {
                TextField(model.label("ask.question")?.text ?? "", text: Binding(get: { model.question }, set: { model.updateQuestion($0) }))
                    .accessibilityLabel(model.label("ask.question")?.text ?? "")
                    .font(.title3).textFieldStyle(.roundedBorder).disabled(model.busy || model.running)
                    .onSubmit { Task { await model.askAgain(question: model.question) } }
            }
            if model.busy { ProgressView() }
            if let error = model.errorNote { NoteView(note: error, enabled: { _ in false }) }
            else if model.response == nil, let note = model.emptyNote { NoteView(note: note) }
            if let answer = model.answer, let receipt = model.answerDisplayReceipt {
                GlassCard { Text(answer.answer).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                    .id(receipt.identity).onAppear {
                        model.didDisplayAnswer(receipt)
                        if !snapshot, model.response?.state == "completed" { Task { await model.reviewAdditionAutomatically() } }
                    }
            }
            let receipt = model.displayReceipt
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(model.notes.enumerated()), id: \.offset) { _, note in NoteView(note: Note(id: note.id, tone: note.tone, values: note.values, text: note.text, buttons: [], statusLine: note.statusLine)) }
            }.id(receipt.identity).onAppear { model.didDisplay(receipt) }
            HStack {
                if model.answer != nil {
                    ForEach(model.answerActions, id: \.id) { button in
                        Button(button.label) {
                            Task {
                                await model.chooseAnswerAction(button) { answer in
                                    NSPasteboard.general.clearContents(); NSPasteboard.general.setString(answer, forType: .string)
                                }
                            }
                        }.disabled(model.busy || model.running)
                    }
                }
                ForEach(model.buttons, id: \.id) { button in
                    Button(button.label) {
                        if button.id == "confirm" { Task { await model.confirm() } }
                        else if button.id == "cancel" {
                            if model.running { Task { await model.cancelRun() } }
                            else { model.discard() }
                        }
                    }.disabled(button.id == "confirm" ? !model.canConfirm : model.busy)
                }
            }
        }.task(id: model.response?.requestID) {
            guard !snapshot else { return }
            while !Task.isCancelled, ["pending", "running"].contains(model.response?.state ?? "") {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                await model.poll()
            }
        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
    }
}
