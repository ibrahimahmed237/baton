import SwiftUI
import BatonKit

public struct MergeView: View {
    @ObservedObject private var model: MergeViewModel
    @Environment(\.batonTheme) private var theme
    public init(model: MergeViewModel) { self.model = model }
    public var body: some View {
        WindowScrollArea(snapshotClips: false) {
            VStack(alignment: .leading, spacing: 16) {
                if model.busy { ProgressView() }
                if let error = model.errorNote { NoteView(note: error) }
                if let result = model.result {
                    ForEach(Array(model.presentationNotes.filter { !model.choices.contains($0) }.enumerated()), id: \.offset) { _, note in
                        NoteView(note: Note(id: note.id, tone: note.tone, values: note.values, text: note.text, buttons: [], statusLine: note.statusLine))
                    }
                    if let shared = result.lastShared { GlassCard { VStack(alignment: .leading, spacing: 6) { Text(shared.firstLine); Text(DisplayTime.string(shared.startedAt)).font(.caption) }.frame(maxWidth: .infinity, alignment: .leading) } }
                    HStack { ForEach(model.presets) { preset in Button(preset.label) { Task { await model.select(preset) } } } }.buttonStyle(.bordered).tint(theme.colour(for: .danger))
                    HStack { ForEach(Array(model.choices.enumerated()), id: \.offset) { _, note in
                        Button(note.text) { Task { await model.choose(note) } }
                            .tint(theme.colour(for: note.id == "merge.brief_choice" ? .action : .danger))
                    } }.buttonStyle(.bordered)
                    ForEach(Array(model.turns.enumerated()), id: \.element.id) { index, turn in
                        GlassCard {
                          VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                ToolDot(tool: turn.origin, label: turn.origin)
                                Text(DisplayTime.string(turn.startedAt)).font(.caption)
                                Spacer()
                                Button { Task { await model.move(turn.id, to: index - 1) } } label: { Image(systemName: "arrow.up") }.disabled(index == 0)
                                Button { Task { await model.move(turn.id, to: index + 1) } } label: { Image(systemName: "arrow.down") }.disabled(index + 1 == model.turns.count)
                            }
                            ForEach(Array((turn.messages ?? []).enumerated()), id: \.offset) { _, message in Text(message.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                          }
                        }
                        .draggable(String(turn.id))
                        .dropDestination(for: String.self) { ids, _ in
                            guard let id = ids.first.flatMap(Int.init), model.turns.contains(where: { $0.id == id }) else { return false }
                            Task { await model.move(id, to: index) }; return true
                        }
                    }
                    ForEach(result.sameFiles, id: \.file) { file in
                        HStack { Image(systemName: "exclamationmark.triangle"); Text(file.file); ForEach(file.turns, id: \.self) { Text($0, format: .number) } }.foregroundStyle(theme.colour(for: .danger))
                    }
                    ForEach(Array(result.overlaps.enumerated()), id: \.offset) { _, ids in
                        HStack { Image(systemName: "clock.badge.exclamationmark"); ForEach(ids, id: \.self) { Text($0, format: .number) } }.foregroundStyle(theme.colour(for: .waiting))
                    }

                }
                ActionReviewView(model: model.review)
            }.padding(20)
        }.foregroundStyle(theme.text).background(theme.background)
    }
}
