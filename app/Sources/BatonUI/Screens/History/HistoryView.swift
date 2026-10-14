import SwiftUI
import BatonKit

public struct HistoryView: View {
    @ObservedObject private var model: HistoryViewModel
    @Environment(\.batonTheme) private var theme
    public init(model: HistoryViewModel) { self.model = model }
    public var body: some View {
        WindowScrollArea(snapshotClips: false) {
            VStack(alignment: .leading, spacing: 14) {
                if model.busy { ProgressView() }
                if let error = model.errorNote { NoteView(note: error) }
                ForEach(Array(model.notes.enumerated()), id: \.offset) { _, note in NoteView(note: note) }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), alignment: .leading)], alignment: .leading, spacing: 8) {
                  ForEach(model.legend, id: \.id) { event in
                    HStack { Circle().fill(theme.colour(for: HistoryViewModel.colour(event.kind))).frame(width: 7, height: 7); Text(model.label(event)?.text ?? event.text).font(.caption) }
                }
                }
                ForEach(model.events, id: \.id) { event in
                    GlassCard {
                        HStack(alignment: .top) {
                            RoundedRectangle(cornerRadius: 2).fill(theme.colour(for: HistoryViewModel.colour(event.kind))).frame(width: 4)
                            VStack(alignment: .leading, spacing: 6) {
                                Text(model.label(event)?.text ?? event.text).font(.caption.weight(.semibold))
                                Text(event.text).font(.headline).foregroundStyle(theme.colour(for: HistoryViewModel.colour(event.kind)))
                                HStack {
                                    if let tool = event.tool { ToolDot(tool: tool, label: tool) }
                                    Text(DisplayTime.string(event.at)).font(.caption)
                                    ForEach(event.turns, id: \.self) { Text($0, format: .number).font(.caption.monospacedDigit()) }
                                }
                            }
                            Spacer(minLength: 10)
                            if event.canUndo {
                                Button { Task { await model.undo(event) } } label: { Image(systemName: "arrow.uturn.backward") }
                                    .accessibilityLabel(model.undoLabel(event)?.text ?? event.text).tint(theme.colour(for: .danger))
                            }
                            if event.canRestore {
                                Button { Task { await model.restore(event) } } label: { Image(systemName: "arrow.clockwise") }
                                    .accessibilityLabel(model.restoreLabel(event)?.text ?? event.text).tint(theme.colour(for: .added))
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }.buttonStyle(.bordered)
                }
                ActionReviewView(model: model.review)
            }.padding(20)
        }.foregroundStyle(theme.text).background(theme.background)
    }
}
