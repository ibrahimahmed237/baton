import SwiftUI
import BatonKit

/// Fixture-backed previews for every D1 component in both palettes.
struct ComponentPreviews: PreviewProvider {
    private static let directory = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Fixtures")

    private static func fixture<T: Decodable>(_ name: String, as: T.Type) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(contentsOf: directory.appendingPathComponent(name)))
    }

    static var previews: some View {
        ForEach(Theme.allCases, id: \.rawValue) { theme in
            if let note = try? fixture("note.sample.json", as: Note.self),
               let turn = try? fixture("turn.sample.json", as: Turn.self),
               let message = try? fixture("turn-message.sample.json", as: TurnMessage.self),
               let plan = try? fixture("plan.sample.json", as: Plan.self) {
                let setup = try? fixture("setup.sample.json", as: SetupResult.self)
                let labels = Dictionary(uniqueKeysWithValues: (setup?.tools ?? []).map { ($0.tool, $0.displayLabel) })
                let components: [(String, AnyView)] = [
                    ("ToolDot", AnyView(ToolDot(tool: turn.origin, label: labels[turn.origin]))),
                    ("StateChip", AnyView(StateChip(state: turn.states.values.sorted().first ?? ""))),
                    ("NoteView", AnyView(NoteView(note: note))),
                    ("TurnRow", AnyView(TurnRow(turn: turn, toolLabels: labels))),
                    ("MessageBubble", AnyView(MessageBubble(message: message, toolLabels: labels))),
                    ("PlanSteps", AnyView(PlanSteps(steps: plan.steps))),
                    ("ConfirmBar", AnyView(ConfirmBar(notes: plan.notes, buttons: note.buttons))),
                    ("MeterBar", AnyView(MeterBar(percent: 82, label: note.statusLine ?? note.text)))
                ]
                ForEach(components, id: \.0) { name, component in
                    component.padding(20).frame(width: 420).background(theme.background)
                        .batonTheme(theme).previewDisplayName("\(name) · \(theme.rawValue)")
                }
            }
        }
    }
}
