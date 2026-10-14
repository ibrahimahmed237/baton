import SwiftUI
import BatonKit

public struct ActionReviewView: View {
    @ObservedObject private var model: ActionReviewViewModel
    @Environment(\.batonTheme) private var theme
    public init(model: ActionReviewViewModel) { self.model = model }
    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if model.busy { ProgressView() }
            if let error = model.errorNote { NoteView(note: error) }
            if let plan = model.plan {
                PlanSteps(steps: plan.steps, excludingNotes: model.notes)
                ForEach(Array(model.removalGroups.enumerated()), id: \.offset) { _, group in
                    Text(group.heading.text).font(.headline)
                    ForEach(group.removes, id: \.turn.id) { removed in removedTurn(removed) }
                }
                if let end = model.endsAt { GlassCard { VStack(alignment: .leading, spacing: 6) { Text(end.firstLine); Text(DisplayTime.string(end.startedAt)).font(.caption) }.frame(maxWidth: .infinity, alignment: .leading) } }
                if let receipt = model.displayReceipt {
                    ConfirmBar(notes: receipt.notes, buttons: model.buttons, revision: receipt.identity,
                               enabled: { _, button in button.id == "cancel" || (button.id == "open" && plan.applied) || model.canConfirm }) { _, button in
                        Task { await model.choose(button) }
                    }.id(receipt.identity).onAppear { model.didDisplay(receipt) }.disabled(model.busy)
                }
            }
        }.frame(maxWidth: .infinity, alignment: .leading).foregroundStyle(theme.text)
    }
    private func removedTurn(_ removed: RemovedTurn) -> some View {
        GlassCard {
          VStack(alignment: .leading, spacing: 6) {
            HStack { ToolDot(tool: removed.turn.origin, label: model.plan?.steps.first(where: { $0.tool == removed.turn.origin })?.displayLabel ?? removed.turn.origin); Text(removed.turn.firstLine)
                if removed.onlyHere { Image(systemName: "exclamationmark.triangle").foregroundStyle(theme.colour(for: .danger)) }
            }
            Text(DisplayTime.string(removed.turn.startedAt)).font(.caption)
          }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
