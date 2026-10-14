import SwiftUI
import BatonKit

public struct SetupView: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @ObservedObject private var model: SetupViewModel
    public init(model: SetupViewModel) { self.model = model }
    public var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let label = model.label("setup.check_again") { Button(label.text) { Task { await model.load() } }.disabled(model.busy) }
            if model.busy { ProgressView() }
            if let error = model.errorNote { NoteView(note: error, enabled: { _ in false }) }
            else if model.tools.isEmpty, let note = model.emptyNote { NoteView(note: note) }
            let receipt = model.displayReceipt
            VStack(alignment: .leading, spacing: 16) {
                ForEach(model.tools, id: \.tool) { tool in
                    GlassCard {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack {
                                ToolDot(tool: tool.tool, label: tool.displayLabel).font(.title3.weight(.semibold))
                                Spacer()
                                if let version = tool.version { Text(version).font(.caption.monospaced()) }
                                Image(systemName: tool.ready ? "checkmark.circle" : "exclamationmark.circle")
                                    .foregroundStyle(theme.colour(for: tool.ready ? .added : .danger))
                            }
                            // Per-card deduplication retains the tool beside its findings.
                            ForEach(Array(model.findings(for: tool).enumerated()), id: \.offset) { _, finding in
                                HStack(alignment: .top) {
                                    Image(systemName: finding.ok ? "checkmark" : "exclamationmark.triangle")
                                        .foregroundStyle(theme.colour(for: finding.ok ? .added : .danger))
                                    VStack(alignment: .leading) {
                                        if let label = model.label("setup.category." + finding.id) { Text(label.text).font(.headline) }
                                        NoteView(note: Note(id: finding.note.id, tone: finding.note.tone, values: finding.note.values, text: finding.note.text, buttons: [], statusLine: finding.note.statusLine))
                                        ForEach(finding.note.buttons, id: \.id) { button in
                                            if button.id == "install_hooks" {
                                                Button(button.label) { Task { await model.install(tool: tool.tool, button: button) } }
                                                    .disabled(!model.canInstall(tool: tool.tool, button: button))
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }.id(receipt.identity).onAppear { model.didDisplay(receipt) }
        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
            .task { if !snapshot { await model.load() } }
    }
}
