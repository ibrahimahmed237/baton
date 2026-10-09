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
        }
        model.setFilter(.pinned)
        let hidden = model.hiddenReachedTools
        #expect(!hidden.isEmpty)
        for tool in hidden {
            let reached = try #require(status.sides[tool]?.syncedUpTo)
            let note = try #require(model.receiptNotes(for: [tool], hidden: true).first)
            #expect(note.id == "screen.received_hidden_tool")
            #expect(note.values["seq"] == .number(Double(reached.seq)))
        }
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        for link in [3, 5] {
            await model.load(link: link)
            for theme in Theme.allCases {
                let renderer = ImageRenderer(content: SyncStatusView(model: model).padding(20).frame(width: 780)
                    .environment(\.batonSnapshotPresentation, true).background(theme.background).batonTheme(theme))
                renderer.scale = 1
                let image = try #require(renderer.nsImage)
                let tiff = try #require(image.tiffRepresentation)
            let pixels = try #require(NSBitmapImageRep(data: tiff))
                try #require(pixels.representation(using: .png, properties: [:])).write(to: output.appendingPathComponent("UI8-receipt-\(link)-\(theme.rawValue).png"))
            }
        }
    }
}
