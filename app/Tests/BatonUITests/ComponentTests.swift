import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

@Suite(.serialized)
struct ComponentTests {
    static let root = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()

    private func fixture<T: Decodable>(_ name: String, as: T.Type) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(contentsOf: Self.root
            .appendingPathComponent("Fixtures").appendingPathComponent(name)))
    }

    @MainActor @Test
    func nativeMenuBarImagesIncludeTheDecisionBadgeInBothThemes() throws {
        try FileManager.default.createDirectory(at: Self.root.appendingPathComponent("Snapshots"),
                                                withIntermediateDirectories: true)
        for theme in Theme.allCases {
            let plain = try #require(BatonMenuIcon.nativeImage(needsDecision: false, theme: theme))
            let badged = try #require(BatonMenuIcon.nativeImage(needsDecision: true, theme: theme))
            #expect(!plain.isTemplate)
            #expect(!badged.isTemplate)
            #expect(plain.size == NSSize(width: 26, height: 22))
            #expect(badged.size == plain.size)
            let plainData = try #require(plain.tiffRepresentation)
            let badgeData = try #require(badged.tiffRepresentation)
            #expect(plainData != badgeData)
            for (name, data) in [("plain", plainData), ("badge", badgeData)] {
                let bitmap = try #require(NSBitmapImageRep(data: data))
                let png = try #require(bitmap.representation(using: .png, properties: [:]))
                #expect(!png.isEmpty)
                try png.write(to: Self.root.appendingPathComponent("Snapshots/D4b-menu-\(name)-\(theme.rawValue).png"))
            }
        }
    }

    @Test
    func confirmationRequiresExactDisplayedNotes() throws {
        let note = try fixture("note.sample.json", as: Note.self)
        var gate = ConfirmationGate()
        #expect(!gate.permits([note]))
        gate.markDisplayed([note])
        #expect(gate.permits([note]))
        var changed = note
        changed.text += "!"
        #expect(!gate.permits([changed]))
        changed = note
        changed.buttons[0].label += "!"
        #expect(!gate.permits([changed]))
        gate.markDisplayed([changed])
        #expect(gate.permits([changed]))
        #expect(!gate.permits([note]))
        #expect(!gate.permits([]))
    }

    @Test
    func semanticMappingsCoverStatesAndPlanActions() {
        #expect(StateColour.state("added") == .added)
        #expect(StateColour.state("attached") == .waiting)
        #expect(StateColour.state("waiting") == .waiting)
        #expect(StateColour.state("merged_copy") == .merged)
        #expect(StateColour.state("relinked") == .action)
        #expect(StateColour.state("conflict") == .danger)
        #expect(StateColour.step("close") == .danger)
        #expect(StateColour.step("write") == .added)
        #expect(StateColour.step("reopen") == .action)
        #expect(StateColour.tone("danger") == .danger)
        #expect(StateColour.state("future_state") == .neutral)
        #expect(ToolColour(tool: "future_tool") == .unknown)
    }

    @MainActor @Test
    func snapshotsEachComponentInBothThemes() throws {
        let note = try fixture("note.sample.json", as: Note.self)
        let turn = try fixture("turn.sample.json", as: Turn.self)
        let message = try fixture("turn-message.sample.json", as: TurnMessage.self)
        let plan = try fixture("plan.sample.json", as: Plan.self)
        let setup = try fixture("setup.sample.json", as: SetupResult.self)
        let labels = Dictionary(uniqueKeysWithValues: setup.tools.map { ($0.tool, $0.displayLabel) })
        let components: [(String, AnyView)] = [
            ("ToolDot", AnyView(ToolDot(tool: turn.origin, label: labels[turn.origin]))),
            ("StateChip", AnyView(StateChip(state: "added"))),
            ("NoteView", AnyView(NoteView(note: note))),
            ("TurnRow", AnyView(TurnRow(turn: turn, toolLabels: labels))),
            ("MessageBubble", AnyView(MessageBubble(message: message, toolLabels: labels))),
            ("PlanSteps", AnyView(PlanSteps(steps: plan.steps))),
            ("ConfirmBar", AnyView(ConfirmBar(notes: plan.notes, buttons: note.buttons))),
            ("MeterBar", AnyView(MeterBar(percent: 82, label: note.statusLine ?? note.text)))
        ]
        let output = Self.root.appendingPathComponent("Snapshots", isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for theme in Theme.allCases {
            for (name, component) in components {
                let content = component.padding(20).frame(width: 420)
                    .background(theme.background).batonTheme(theme)
                let renderer = ImageRenderer(content: content)
                renderer.scale = 2
                let image = try #require(renderer.nsImage)
                #expect(image.size.width > 0 && image.size.height > 0)
                let tiff = try #require(image.tiffRepresentation)
                let bitmap = try #require(NSBitmapImageRep(data: tiff))
                let png = try #require(bitmap.representation(using: .png, properties: [:]))
                #expect(!png.isEmpty)
                try png.write(to: output.appendingPathComponent("D1-\(name)-\(theme.rawValue).png"))
            }
        }
    }
}
