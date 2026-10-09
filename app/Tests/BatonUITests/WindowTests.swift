import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

private actor RecordingWindowEngine: EngineTransport {
    let fixture: FixtureEngine
    var calls: [(String, [String])] = []
    var fail = false
    func setFail() { fail = true }
    init(state: String) { fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: state) }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        calls.append((command, arguments))
        if fail { throw EngineCommandError(kind: "fixture_failure", note: Note(id: "fixture.failure", tone: "warning", values: [:], text: "Fixture refresh failed", buttons: [])) }
        return try await fixture.response(command: command, arguments: arguments, as: type)
    }
}

private actor ChangingWindowEngine: EngineTransport {
    var suggestionOrder = 0
    func reorderSuggestions() { suggestionOrder = 1 }
    func removeFirstSuggestion() { suggestionOrder = 2 }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        let data = try Data(contentsOf: ComponentTests.root.appendingPathComponent("Fixtures/\(command).d3_filled.json"))
        var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        if command == "suggestions" {
            let originals = try #require(object["suggestions"] as? [[String: Any]])
            let first = try #require(originals.first)
            var second = first
            for side in ["a", "b"] {
                var chat = try #require(second[side] as? [String: Any])
                chat["id"] = (chat["id"] as? String ?? "") + "_other"
                second[side] = chat
            }
            object["suggestions"] = suggestionOrder == 0 ? [first, second] : suggestionOrder == 1 ? [second, first] : [second]
        }
        if command == "history" {
            let originals = try #require(object["events"] as? [[String: Any]])
            var first = try #require(originals.first)
            first["at"] = "2026-10-05T10:00:00Z"
            var later = first; later["id"] = 2; later["at"] = "2026-10-05T10:00:00.9Z"
            object["events"] = [first, later]
        }
        return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
}

@Suite(.serialized)
struct WindowTests {
    @MainActor @Test
    func refreshErrorsChangeTheSharedDetailSurfaceForLinkedAndAttention() async throws {
        try FileManager.default.createDirectory(at: ComponentTests.root.appendingPathComponent("Snapshots"),
                                                withIntermediateDirectories: true)
        for section in [WindowSection.linked, .attention] {
            let engine = RecordingWindowEngine(state: "d3_filled")
            let model = WindowViewModel(engine: engine); await model.refresh(); model.navigate(to: section)
            let previousLinks = model.links
            let before = try errorSurfacePixels(model)
            await engine.setFail(); await model.refresh()
            #expect(model.links == previousLinks)
            #expect(model.selection == nil)
            #expect(model.errorNote?.id == "fixture.failure")
            let after = try errorSurfacePixels(model)
            #expect(before != after)
            for theme in Theme.allCases {
                let renderer = ImageRenderer(content: WindowView(model: model).batonTheme(theme)
                    .environment(\.batonSnapshotPresentation, true))
                let image = try #require(renderer.nsImage)
                let tiff = try #require(image.tiffRepresentation)
                let bitmap = try #require(NSBitmapImageRep(data: tiff))
                let png = try #require(bitmap.representation(using: .png, properties: [:]))
                let name = section == .linked ? "linked" : "attention"
                try png.write(to: ComponentTests.root.appendingPathComponent("Snapshots/D4b-error-\(name)-\(theme.rawValue).png"))
            }
        }
    }
    @MainActor private func errorSurfacePixels(_ model: WindowViewModel) throws -> Data {
        let renderer = ImageRenderer(content: WindowView(model: model).batonTheme(.light)
            .environment(\.batonSnapshotPresentation, true))
        let image = try #require(renderer.cgImage)
        let region = try #require(image.cropping(to: CGRect(x: 225, y: 20, width: 400, height: 100)))
        return try #require(region.dataProvider?.data) as Data
    }
    @MainActor @Test
    func navigationSelectionAndAttentionUseEngineFlags() async {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh()
        #expect(model.sections.count == 8)
        #expect(model.attentionLinks.map(\.linkID) == [3, 4])
        model.select(.link(3))
        #expect(model.selectedLink?.linkID == 3)
        await model.refresh()
        #expect(model.selectedLink?.linkID == 3)
        model.navigate(to: .attention)
        #expect(model.selection == nil)
        model.select(.link(5))
        #expect(model.selection == nil)
        model.select(.link(4))
        #expect(model.selectedLink?.headline.id == "relaunch_to_see")
        model.navigate(to: .suggestions)
        let selectedSuggestion = model.suggestionSelection(model.suggestions[0])
        model.select(selectedSuggestion)
        #expect(model.selection == selectedSuggestion)
        model.navigate(to: .chats("codex"))
        model.select(.chat("codex", "d3-unlinked-codex"))
        #expect(model.selection == .chat("codex", "d3-unlinked-codex"))
        model.navigate(to: .activity)
        #expect(Set(model.activity.map(\.id)).count == 3)
        model.select(.event(3, 1))
        #expect(model.selection == .event(3, 1))
    }

    @MainActor @Test
    func uninstalledToolIsNeverOfferedOrQueried() async {
        let engine = RecordingWindowEngine(state: "d3_tool_missing")
        let model = WindowViewModel(engine: engine)
        await model.refresh()
        #expect(!model.installedTools.contains("cursor"))
        #expect(!model.sections.contains(.chats("cursor")))
        model.navigate(to: .chats("cursor"))
        #expect(model.section == .linked)
        let calls = await engine.calls
        #expect(!calls.contains { $0.0 == "chats" && $0.1.contains("cursor") })
    }

    @Test
    func legacyAttentionFlagIsOptional() throws {
        let value = try JSONDecoder().decode(LinksResult.self, from: Data(contentsOf: ComponentTests.root.appendingPathComponent("Fixtures/links.sample.json")))
        #expect(value.links.first?.needsAttention == nil)
    }

    @MainActor @Test
    func suggestionIdentitySurvivesReorderingAndClearsOnRemoval() async {
        let engine = ChangingWindowEngine()
        let model = WindowViewModel(engine: engine)
        await model.refresh()
        model.navigate(to: .suggestions)
        let original = model.suggestionSelection(model.suggestions[0])
        model.select(original)
        await engine.reorderSuggestions()
        await model.refresh()
        #expect(model.selection == original)
        #expect(model.selectedSuggestion?.a.id == "d3-suggestion-claude")
        await engine.removeFirstSuggestion()
        await model.refresh()
        #expect(model.selection == nil)
        #expect(model.selectedSuggestion == nil)
    }

    @MainActor @Test
    func fractionalHistoryTimesSortAfterWholeSeconds() async {
        let model = WindowViewModel(engine: ChangingWindowEngine())
        await model.refresh()
        #expect(model.activity.map(\.event.id) == [2, 2, 2, 1, 1, 1])
        #expect(model.activity.prefix(3).map(\.link.linkID) == [3, 4, 5])
    }

    @MainActor @Test
    func snapshotsEveryListEmptyFilledAndMissingTool() async throws {
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for fixture in ["empty", "filled", "tool_missing"] {
            let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_" + fixture))
            await model.refresh()
            let destinations = fixture == "tool_missing" ? [WindowSection.linked] : model.sections
            #expect(destinations.count == (fixture == "tool_missing" ? 1 : 8))
            for section in destinations {
                model.navigate(to: section)
                let name: String
                switch section {
                case .linked: name = "linked"; if fixture == "filled" { model.select(.link(3)) }
                case .attention: name = "attention"; if fixture == "filled" { model.select(.link(4)) }
                case .suggestions: name = "suggestions"; if fixture == "filled" { model.select(model.suggestionSelection(model.suggestions[0])) }
                case .chats(let tool): name = "chats_" + tool; if fixture == "filled" { model.select(.chat(tool, "d3-unlinked-" + tool)) }
                case .activity: name = "activity"; if fixture == "filled" { model.select(.event(3, 1)) }
                }
                for theme in Theme.allCases {
                    let renderer = ImageRenderer(content: WindowView(model: model).batonTheme(theme).environment(\.batonSnapshotPresentation, true))
                    renderer.scale = 1
                    let image = try #require(renderer.nsImage)
                    #expect(image.size.width > 0 && image.size.height > 0)
                    let tiff = try #require(image.tiffRepresentation)
                    let bitmap = try #require(NSBitmapImageRep(data: tiff))
                    let png = try #require(bitmap.representation(using: .png, properties: [:]))
                    #expect(!png.isEmpty)
                    try png.write(to: output.appendingPathComponent("D3-\(name)-\(fixture)-\(theme.rawValue).png"))
                }
            }
        }
    }
}
