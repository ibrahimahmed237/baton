import SwiftUI
import BatonKit

/// Hand-off: limit banner, both sides' fullness, full sync or brief, who writes the brief, and a preview.
public struct HandOffView: View {
    @ObservedObject private var model: HandOffViewModel
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    private let cancel: () -> Void

    public init(model: HandOffViewModel, cancel: @escaping () -> Void = {}) { self.model = model; self.cancel = cancel }

    public var body: some View {
        WindowScrollArea(snapshotClips: false) {
            VStack(alignment: .leading, spacing: 16) {
                if let title = model.label("handoff.title") { Text(title.text).font(.title2.weight(.semibold)) }
                if let error = model.errorNote { NoteView(note: error) }
                if model.loading {
                    // A native progress control is not rendered by ImageRenderer.
                    Circle().trim(from: 0, to: 0.7)
                        .stroke(theme.secondaryText, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                        .frame(width: 24, height: 24).frame(maxWidth: .infinity).padding(12)
                }
                if model.hasUnwordedError {
                    GlassCard {
                        HStack(spacing: 16) {
                            BrandMark(size: 58)
                            Image(systemName: "exclamationmark.triangle").font(.title2).foregroundStyle(theme.secondaryText)
                            Spacer()
                            Button(action: cancel) { Image(systemName: "xmark.circle.fill").font(.title2) }.buttonStyle(.plain)
                        }.padding(16)
                    }
                }
                if let offer = model.offer, model.bannerVisible {
                    NoteView(note: offer, enabled: { _ in model.canAct }, action: { button in model.choose(button) })
                        .padding(12).background(theme.colour(for: StateColour.tone(offer.tone)).opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }
                if let chat = model.chat, !model.isLinked {
                    HStack(spacing: 8) { ToolDot(tool: chat.tool, label: chat.displayLabel); Text(chat.name).font(.headline) }
                }
                if model.isLinked {
                    heading("handoff.sides")
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(model.tools, id: \.self) { tool in sideCard(tool) }
                    }
                    ForEach(Array(model.statusNotes.enumerated()), id: \.offset) { _, note in
                        NoteView(note: note, enabled: { _ in model.canAct }) { button in
                            Task { await model.chooseRecommendation(button) }
                        }
                    }
                    heading("handoff.mode")
                    HStack(alignment: .top, spacing: 12) {
                        modeCard(.full, title: "handoff.full", help: "handoff.full_help", notes: model.target.flatMap { model.notes(for: $0).filter { $0.id == "status.if_send" } } ?? [])
                        modeCard(.brief, title: "handoff.brief", help: "handoff.brief_help", notes: model.briefPreviewNotes)
                    }
                    if model.mode == .brief { writerBlock; if model.brief != nil { previewBlock } }
                    actions
                }
            }.padding(22)
        }
        .frame(width: 720, height: snapshot ? nil : 640).background { GlassBackdrop() }
        .environment(\.colorScheme, theme.scheme)
    }

    @ViewBuilder private func heading(_ id: String) -> some View {
        if let note = model.label(id) { Text(note.text).font(.headline) }
    }

    private func sideCard(_ tool: String) -> some View {
        let side = model.side(tool)
        let context = model.contextNote(for: tool)
        return GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Button { model.selectTarget(tool); Task { await model.previewChoice() } } label: {
                    HStack {
                        ToolDot(tool: tool, label: side?.displayLabel).font(.headline)
                        if model.target == tool { Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.colour(for: .action)) }
                    }
                }.buttonStyle(.plain).disabled(!model.canAct)
                if let name = side?.chat.name { Text(name).font(.subheadline).foregroundStyle(theme.secondaryText) }
                if let context { MeterBar(percent: model.percent(for: tool), label: DisplayTime.noteText(context.text, values: context.values)) }
                ForEach(Array(model.notes(for: tool).filter { $0 != context && $0.id != "status.if_send" }.enumerated()), id: \.offset) { _, note in sideNote(note) }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder private func sideNote(_ note: Note) -> some View {
        if note.statusLine?.trimmingCharacters(in: CharacterSet(charactersIn: ". ")) == note.text.trimmingCharacters(in: CharacterSet(charactersIn: ". ")), note.buttons.isEmpty {
            Text(DisplayTime.noteText(note.text, values: note.values))
                .fixedSize(horizontal: false, vertical: true).padding(.leading, 13)
                .overlay(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2).fill(theme.colour(for: StateColour.tone(note.tone))).frame(width: 3)
                }
        } else { NoteView(note: note) }
    }

    private func modeCard(_ mode: HandOffMode, title: String, help: String, notes: [Note]) -> some View {
        Button { model.selectMode(mode); Task { await model.previewChoice() } } label: {
            VStack(alignment: .leading, spacing: 8) {
                if let note = model.label(title) { Text(note.text).font(.headline) }
                if let note = model.label(help) { Text(note.text).font(.caption).foregroundStyle(theme.secondaryText).fixedSize(horizontal: false, vertical: true) }
                ForEach(Array(notes.enumerated()), id: \.offset) { _, note in Text(note.text).font(.callout).fixedSize(horizontal: false, vertical: true) }
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(14).contentShape(Rectangle())
            .background(theme.colour(for: .action).opacity(model.mode == mode ? 0.14 : 0.04), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(model.mode == mode ? theme.colour(for: .action) : theme.hairline))
        }.buttonStyle(.plain).disabled(!model.canAct).accessibilityAddTraits(model.mode == mode ? .isSelected : [])
    }

    private var writerBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            heading("handoff.writer")
            HStack {
                ForEach(model.label("handoff.writer_choices")?.buttons ?? [], id: \.id) { button in
                    Button(button.label) {
                        guard ["automatic", "offline"].contains(button.id) else { return }
                        model.selectWriter(button.id == "offline" ? .offline : .automatic)
                        Task { await model.previewChoice() }
                    }.buttonStyle(BatonButtonStyle(meaning: (button.id == "offline") == (model.writer == .offline) ? .action : .neutral))
                        .disabled(!model.canAct)
                }
            }
            if let writer = model.briefWriter, let side = model.side(writer) { ToolDot(tool: writer, label: side.displayLabel).font(.callout.weight(.semibold)) }
            ForEach(Array(model.writerNotes.enumerated()), id: \.offset) { _, note in NoteView(note: note) }
        }
    }

    private var previewBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            heading("handoff.preview")
            if let plan = model.brief?.plan {
                PlanSteps(steps: plan.steps, excludingNotes: plan.notes)
                if plan.stage == "create", let text = model.brief?.brief?.text, !text.isEmpty {
                    GlassCard { Text(text).font(.body).textSelection(.enabled).fixedSize(horizontal: false, vertical: true) }
                }
            }
        }
    }

    private var actions: some View {
        HStack {
            ForEach(model.label("handoff.actions")?.buttons ?? [], id: \.id) { button in
                Button(button.label) { if button.id == "review" { model.beginReview() } else { cancel() } }
                    .buttonStyle(BatonButtonStyle(meaning: button.primary == true ? .action : .neutral))
                    .disabled(button.id == "review" && model.request == nil)
            }
        }
    }
}
