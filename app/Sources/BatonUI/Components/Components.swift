import SwiftUI
import BatonKit

/// A tool's dot and engine-provided name.
public struct ToolDot: View {
    @Environment(\.batonTheme) private var theme
    public let tool: String
    /// Creates a dot for the supplied tool identity.
    public init(tool: String) { self.tool = tool }
    public var body: some View {
        HStack(spacing: 6) {
            Circle().fill(theme.colour(for: ToolColour(tool: tool))).frame(width: 8, height: 8)
                .accessibilityHidden(true)
            Text(tool)
        }.accessibilityElement(children: .combine)
    }
}

/// A state label whose colour reinforces its text.
public struct StateChip: View {
    @Environment(\.batonTheme) private var theme
    public let state: String
    public let label: String
    /// Creates a chip from a state and its optional supplied label.
    public init(state: String, label: String? = nil) { self.state = state; self.label = label ?? state }
    public var body: some View {
        Text(label).font(.caption.weight(.semibold)).padding(.horizontal, 8).padding(.vertical, 4)
            .foregroundStyle(theme.colour(for: StateColour.state(state)))
            .background(theme.colour(for: StateColour.state(state)).opacity(0.12), in: Capsule())
    }
}

/// Displays the engine's note and button labels without creating text.
public struct NoteView: View {
    @Environment(\.batonTheme) private var theme
    public let note: Note
    private let action: (NoteButton) -> Void
    /// Presents a note and forwards its button choices.
    public init(note: Note, action: @escaping (NoteButton) -> Void = { _ in }) {
        self.note = note; self.action = action
    }
    public var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2).fill(theme.colour(for: StateColour.tone(note.tone)))
                .frame(width: 3)
            VStack(alignment: .leading, spacing: 8) {
                Text(note.text).fixedSize(horizontal: false, vertical: true)
                if let line = note.statusLine { Text(line).font(.caption).foregroundStyle(theme.secondaryText) }
                HStack {
                    ForEach(note.buttons, id: \.id) { button in
                        Button(button.label) { action(button) }
                            .buttonStyle(BatonButtonStyle(meaning: StateColour.tone(note.tone)))
                    }
                }
            }
        }.fixedSize(horizontal: false, vertical: true)
    }
}

/// One turn's summary and state per tool.
public struct TurnRow: View {
    public let turn: Turn
    /// Presents one contract turn.
    public init(turn: Turn) { self.turn = turn }
    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack { Text(turn.seq, format: .number).monospacedDigit(); ToolDot(tool: turn.origin) }
            Text(turn.firstLine).fixedSize(horizontal: false, vertical: true)
            HStack {
                ForEach(turn.states.keys.sorted(), id: \.self) { tool in
                    VStack(alignment: .leading, spacing: 4) {
                        ToolDot(tool: tool).font(.caption)
                        StateChip(state: turn.states[tool]!)
                    }
                }
            }
        }
    }
}

/// A message's supplied content and kind in a readable surface.
public struct MessageBubble: View {
    @Environment(\.batonTheme) private var theme
    public let message: TurnMessage
    /// Presents one contract message.
    public init(message: TurnMessage) { self.message = message }
    public var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(message.kind).font(.caption).foregroundStyle(theme.secondaryText)
                    if let tool = message.tool { ToolDot(tool: tool).font(.caption) }
                }
                Text(message.text).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// Numbered plan steps with their engine notes and semantic action colour.
public struct PlanSteps: View {
    @Environment(\.batonTheme) private var theme
    public let steps: [Step]
    /// Presents steps in the order returned by the engine.
    public init(steps: [Step]) { self.steps = steps }
    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .top, spacing: 12) {
                    Text(index + 1, format: .number).font(.headline).monospacedDigit()
                        .foregroundStyle(theme.colour(for: StateColour.step(step.action)))
                    VStack(alignment: .leading, spacing: 8) {
                        HStack { ToolDot(tool: step.tool); Text(step.action).font(.caption) }
                        ForEach(Array(step.notes.enumerated()), id: \.offset) { _, note in NoteView(note: note) }
                    }
                }
            }
        }
    }
}

/// Tracks whether the exact current notes have appeared before an action is enabled.
public struct ConfirmationGate: Equatable {
    private var displayed: [Note]?
    /// Starts with no notes acknowledged as displayed.
    public init() {}
    /// Acknowledges the exact notes that appeared on screen.
    public mutating func markDisplayed(_ notes: [Note]) { displayed = notes }
    /// Allows confirmation only for non-empty unchanged notes.
    public func permits(_ notes: [Note]) -> Bool { !notes.isEmpty && displayed == notes }
}

/// Displays all required notes before enabling their confirmation buttons.
public struct ConfirmBar: View {
    @Environment(\.batonTheme) private var theme
    @State private var gate = ConfirmationGate()
    public let notes: [Note]
    public let buttons: [NoteButton]
    private let action: (NoteButton) -> Void
    /// Presents notes with confirmation buttons gated on their appearance.
    public init(notes: [Note], buttons: [NoteButton], action: @escaping (NoteButton) -> Void = { _ in }) {
        self.notes = notes; self.buttons = buttons; self.action = action
    }
    private var displayIdentity: Data? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        return try? encoder.encode(notes)
    }
    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(notes.enumerated()), id: \.offset) { _, note in
                    NoteView(note: Note(id: note.id, tone: note.tone, values: note.values,
                                        text: note.text, buttons: [], statusLine: note.statusLine))
                }
            }
            .id(displayIdentity)
            .onAppear { gate.markDisplayed(notes) }
            HStack {
                ForEach(buttons, id: \.id) { button in
                    Button(button.label) { if gate.permits(notes) { action(button) } }
                        .disabled(!gate.permits(notes))
                        .buttonStyle(BatonButtonStyle(meaning: button.primary == true ? .action : .neutral))
                }
            }
        }
    }
}

/// SwiftUI-drawn buttons remain visible in ImageRenderer and preserve native actions.
private struct BatonButtonStyle: ButtonStyle {
    @Environment(\.batonTheme) private var theme
    @Environment(\.isEnabled) private var enabled
    let meaning: StateColour
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.callout.weight(.semibold))
            .padding(.horizontal, 10).padding(.vertical, 6)
            .foregroundStyle(theme.colour(for: meaning))
            .background(theme.colour(for: meaning).opacity(configuration.isPressed ? 0.22 : 0.1),
                        in: RoundedRectangle(cornerRadius: 7))
            .opacity(enabled ? 1 : 0.5)
    }
}

/// A context meter with supplied accessibility text; unknown capacity stays indeterminate.
public struct MeterBar: View {
    @Environment(\.batonTheme) private var theme
    public let percent: Double?
    public let label: String
    /// Presents a known or unknown percentage with supplied text.
    public init(percent: Double?, label: String) { self.percent = percent; self.label = label }
    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.caption)
            if let percent {
                GeometryReader { geometry in
                    Capsule().fill(theme.hairline)
                        .overlay(alignment: .leading) {
                            Capsule().fill(theme.colour(for: percent >= 90 ? .danger : .action))
                                .frame(width: geometry.size.width * min(100, max(0, percent)) / 100)
                        }
                }.frame(height: 7)
                .accessibilityValue(Text(percent / 100, format: .percent.precision(.fractionLength(0))))
            } else {
                Capsule().stroke(theme.secondaryText, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    .frame(height: 7)
            }
        }.accessibilityElement(children: .combine).accessibilityLabel(label)
    }
}
