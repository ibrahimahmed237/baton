import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

private enum EmptyFixtureFailure: Error { case unavailable }

/// Controls response timing/failure while retaining real fixture presentation notes.
private actor EmptyStateEngine: EngineTransport {
    let state: String
    var fail = false
    var emptyTurns = false
    var noAttention = false
    var blockNext = false
    var blocked = false
    var entered: CheckedContinuation<Void, Never>?
    var release: CheckedContinuation<Void, Never>?
    init(state: String) { self.state = state }
    func setFail() { fail = true }
    func removeTurns() { emptyTurns = true }
    func removeAttention() { noAttention = true }
    func pauseNextRead() { blockNext = true }
    func waitUntilBlocked() async {
        if blocked { return }
        await withCheckedContinuation { entered = $0 }
    }
    func resume() { release?.resume(); release = nil; blocked = false }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        if blockNext {
            blockNext = false; blocked = true; entered?.resume(); entered = nil
            await withCheckedContinuation { release = $0 }
        }
        if fail { throw EmptyFixtureFailure.unavailable }
        let directory = ComponentTests.root.appendingPathComponent("Fixtures")
        let target = directory.appendingPathComponent("\(command).\(state).json")
        let data = try Data(contentsOf: FileManager.default.fileExists(atPath: target.path)
                            ? target : directory.appendingPathComponent("\(command).sample.json"))
        var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        if emptyTurns, command == "status" { object["turns"] = [] }
        if noAttention, command == "links", let links = object["links"] as? [[String: Any]] {
            object["links"] = links.map { link in
                var changed = link; changed["needs_attention"] = false; changed["decision_needed"] = false
                return changed
            }
        }
        return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
}

@Suite(.serialized)
struct EmptyStateTests {
    @MainActor @Test
    func emptyListsExplainTheirOwnSectionAndFilledListsAskForSelection() async throws {
        let empty = WindowViewModel(engine: EmptyStateEngine(state: "d3_empty"))
        #expect(empty.emptyListContent == nil); #expect(empty.emptyDetailContent == nil)
        await empty.refresh()
        let sections: [(WindowSection, String, String)] = [
            (.linked, "linked", "link"), (.attention, "attention", "link"),
            (.suggestions, "suggestions", "suggestion"), (.chats("codex"), "chats", "chat"),
            (.activity, "activity", "activity")
        ]
        for (section, list, _) in sections {
            empty.navigate(to: section)
            #expect(empty.emptyListContent?.title.id == "empty.\(list).title")
            #expect(empty.emptyDetailContent == empty.emptyListContent)
        }
        let filled = WindowViewModel(engine: EmptyStateEngine(state: "d3_filled"))
        await filled.refresh()
        for (section, _, selection) in sections {
            filled.navigate(to: section)
            #expect(filled.emptyListContent == nil)
            #expect(filled.emptyDetailContent?.title.id == "empty.select_\(selection).title")
        }
        filled.navigate(to: .linked); filled.select(.link(3))
        #expect(filled.emptyDetailContent == nil)
        let engine = EmptyStateEngine(state: "d3_filled"); await engine.removeAttention()
        let clear = WindowViewModel(engine: engine); await clear.refresh(); clear.navigate(to: .attention)
        #expect(!clear.links.isEmpty)
        #expect(clear.emptyDetailContent?.title.id == "empty.attention.title")
    }

    @MainActor @Test
    func windowDoesNotClaimAnEmptySuccessDuringRefreshOrAfterFailure() async {
        let engine = EmptyStateEngine(state: "d3_empty")
        let model = WindowViewModel(engine: engine); await model.refresh()
        #expect(model.emptyDetailContent != nil)
        await engine.pauseNextRead()
        let refresh = Task { await model.refresh() }
        await engine.waitUntilBlocked()
        #expect(model.loading); #expect(model.emptyListContent == nil); #expect(model.emptyDetailContent == nil)
        await engine.resume(); await refresh.value
        #expect(model.emptyDetailContent != nil)
        await engine.setFail(); await model.refresh()
        #expect(model.loadFailed); #expect(!model.loading)
        #expect(model.emptyListContent == nil); #expect(model.emptyDetailContent == nil)
    }

    @MainActor @Test
    func filteredConversationOffersAllTurnsWhileEmptyHistoryDoesNot() async throws {
        let filtered = SyncStatusViewModel(engine: EmptyStateEngine(state: "d4_s1"))
        #expect(filtered.emptyConversationContent == nil)
        await filtered.load(link: 3)
        filtered.setFilter(.attached)
        #expect(!filtered.turns.isEmpty); #expect(filtered.displayedTurns.isEmpty)
        #expect(filtered.emptyConversationContent?.title.id == "empty.filtered.title")
        #expect(filtered.canShowAllTurns)
        filtered.setFilter(.all)
        #expect(!filtered.displayedTurns.isEmpty); #expect(filtered.emptyConversationContent == nil)
        let engine = EmptyStateEngine(state: "d4_s1"); await engine.removeTurns()
        let empty = SyncStatusViewModel(engine: engine); await empty.load(link: 3)
        #expect(empty.emptyConversationContent?.title.id == "empty.conversation.title")
        empty.setFilter(.attached)
        #expect(empty.emptyConversationContent?.title.id == "empty.conversation.title")
        #expect(!empty.canShowAllTurns)
        await engine.pauseNextRead()
        let load = Task { await empty.load(link: 3) }; await engine.waitUntilBlocked()
        #expect(empty.emptyConversationContent == nil)
        await engine.resume(); await load.value
        await engine.setFail(); await empty.load(link: 3)
        #expect(empty.loadFailed); #expect(empty.emptyConversationContent == nil)
    }

    @MainActor @Test
    func popoverOnlyExplainsNoLinksAfterASuccessfulReadyResponse() async {
        let engine = EmptyStateEngine(state: "d2_no_links")
        let model = PopoverViewModel(engine: engine)
        #expect(model.emptyContent == nil)
        await model.refresh(); #expect(model.emptyContent?.title.id == "empty.popover.title")
        #expect(model.emptyContent?.body.id == "empty.popover.body")
        await engine.pauseNextRead()
        let refresh = Task { await model.refresh() }; await engine.waitUntilBlocked()
        #expect(model.emptyContent == nil)
        await engine.resume(); await refresh.value
        #expect(model.emptyContent != nil)
        await engine.setFail(); await model.refresh()
        #expect(model.loadFailed); #expect(model.emptyContent == nil)
    }

    @MainActor @Test
    func renderEmptyAndSelectionSurfacesWithTheSignedBrandInBothThemes() async throws {
        let brand = try #require(BatonBrand.nativeIcon())
        #expect(brand.size.width > 0 && brand.size.height > 0)
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let empty = WindowViewModel(engine: EmptyStateEngine(state: "d3_empty")); await empty.refresh()
        let filled = WindowViewModel(engine: EmptyStateEngine(state: "d3_filled")); await filled.refresh()
        let popover = PopoverViewModel(engine: EmptyStateEngine(state: "d2_no_links")); await popover.refresh()
        let engine = EmptyStateEngine(state: "d4_s1"); await engine.removeTurns()
        let conversation = SyncStatusViewModel(engine: engine); await conversation.load(link: 3)
        let filtered = SyncStatusViewModel(engine: EmptyStateEngine(state: "d4_s1")); await filtered.load(link: 3)
        filtered.setFilter(.attached)
        for theme in Theme.allCases {
            empty.navigate(to: .linked)
            let title = try #require(empty.emptyDetailContent)
            try render(EmptyStateView(content: title), name: "component", theme: theme, output: output)
            for section in empty.sections {
                empty.navigate(to: section); filled.navigate(to: section)
                let name: String
                switch section {
                case .linked: name = "linked"
                case .attention: name = "attention"
                case .suggestions: name = "suggestions"
                case .chats(let tool): name = "chats_" + tool
                case .activity: name = "activity"
                case .settings: continue
                }
                try render(WindowView(model: empty), name: "empty_" + name, theme: theme, output: output)
                try render(WindowView(model: filled), name: "select_" + name, theme: theme, output: output)
            }
            try render(PopoverView(model: popover), name: "popover", theme: theme, output: output)
            try render(SyncStatusView(model: conversation).frame(width: 1000), name: "conversation", theme: theme, output: output)
            try render(SyncStatusView(model: filtered).frame(width: 1000), name: "filtered", theme: theme, output: output)
        }
    }

    @MainActor private func render<V: View>(_ view: V, name: String, theme: Theme, output: URL) throws {
        let renderer = ImageRenderer(content: view.background(theme.background).batonTheme(theme)
            .environment(\.batonSnapshotPresentation, true))
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        #expect(image.size.width > 0 && image.size.height > 0)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        #expect(!png.isEmpty)
        try png.write(to: output.appendingPathComponent("UI5-\(name)-\(theme.rawValue).png"))
    }
}
