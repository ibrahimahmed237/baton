import AppKit
import Foundation
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

@Suite(.serialized)
struct ReceiptTests {
    @MainActor @Test func sharedReceiptsUseOneSentenceAndEmptyFiltersSuppressThem() async throws {
        let model = SyncStatusViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.load(link: 5)
        let shared = try #require(model.turns.last)
        #expect(model.reachedTools(at: shared.id) == ["claude", "codex"])
        let notes = model.receiptNotes(for: model.reachedTools(at: shared.id))
        #expect(notes.map(\.id) == ["screen.received_both"])
        #expect(notes.first?.text == "Both agents reached this turn.")
        #expect(model.note("screen.conversation_guide")?.text == "An agent may have a turn even when its chat does not show it.")
        #expect(model.hiddenReachedTools.isEmpty)
        for filter in [ConversationFilter.attached, .waiting, .kept] {
            model.setFilter(filter)
            #expect(model.displayedTurns.isEmpty)
            #expect(model.hiddenReachedTools.isEmpty)
        }
    }
    @MainActor @Test func differentReceiptTurnsStaySeparateAndHiddenNotesNameTheirTurn() async throws {
        let model = SyncStatusViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.load(link: 3)
        let status = try #require(model.status)
        for tool in model.tools {
            let reached = try #require(status.sides[tool]?.syncedUpTo)
            #expect(model.reachedTools(at: reached.id) == [tool])
            #expect(model.receiptNotes(for: [tool]).first?.id == "screen.received_one")
            #expect(model.receiptNotes(for: [tool]).first?.text == "\(model.toolLabel(tool)) reached this turn.")
        }
        model.setFilter(.pinned)
        let hidden = model.hiddenReachedTools
        #expect(!hidden.isEmpty)
        #expect(model.note("screen.received_hidden")?.text == "Position outside this view")
        for tool in hidden {
            let reached = try #require(status.sides[tool]?.syncedUpTo)
            let note = try #require(model.receiptNotes(for: [tool], hidden: true).first)
            #expect(note.id == "screen.received_hidden_tool")
            #expect(note.values["seq"] == .number(Double(reached.seq)))
        }
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        for (link, filter, state) in [(3, ConversationFilter.all, "separate"),
                                      (3, .pinned, "hidden"),
                                      (5, .all, "shared")] {
            await model.load(link: link)
            model.setFilter(filter)
            if state == "separate" {
                model.unfold()
                #expect(model.tools.allSatisfy { tool in
                    model.displayedTurns.contains { model.reachedTools(at: $0.id).contains(tool) }
                })
            }
            for theme in Theme.allCases {
                let renderer = ImageRenderer(content: SyncStatusView(model: model).padding(20).frame(width: 780)
                    .environment(\.batonSnapshotPresentation, true).background(theme.background).batonTheme(theme))
                renderer.scale = 1
                let image = try #require(renderer.nsImage)
                let tiff = try #require(image.tiffRepresentation)
            let pixels = try #require(NSBitmapImageRep(data: tiff))
                try #require(pixels.representation(using: .png, properties: [:])).write(to: output.appendingPathComponent("UI13-receipt-\(state)-\(theme.rawValue).png"))
            }
        }
    }
}
