import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

private actor RecordingPopoverEngine: EngineTransport {
    let fixture: FixtureEngine
    var calls: [(String, [String])] = []
    init(state: String) { fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: state) }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        calls.append((command, arguments))
        return try await fixture.response(command: command, arguments: arguments, as: type)
    }
}

private actor DeferredContinueEngine: EngineTransport {
    let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d2_in_sync")
    var blocked: CheckedContinuation<Void, Never>?
    var waiting: CheckedContinuation<Void, Never>?
    func waitUntilBlocked() async {
        if blocked == nil { await withCheckedContinuation { waiting = $0 } }
    }
    func release() { blocked?.resume(); blocked = nil }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        if command == "continue", arguments.contains("codex") {
            await withCheckedContinuation { continuation in
                blocked = continuation
                waiting?.resume(); waiting = nil
            }
        }
        return try await fixture.response(command: command, arguments: arguments, as: type)
    }
}

@Suite(.serialized)
struct PopoverTests {
    static let states = ["no_links", "in_sync", "one_side_ahead", "waiting", "relaunch_needed", "decision_needed", "paused", "setup_incomplete"]

    @MainActor @Test
    func selectionContinueAndDecisionBadgeUseEngineData() async throws {
        let engine = RecordingPopoverEngine(state: "d2_decision_needed")
        let model = PopoverViewModel(engine: engine)
        await model.refresh()
        #expect(model.selectedLinkID == 3)
        #expect(model.needsDecision)
        model.select(linkID: 999)
        #expect(model.selectedLinkID == 3)
        await model.continueIn(tool: "unknown")
        #expect(model.plan == nil)
        await model.continueIn(tool: "codex")
        let calls = await engine.calls
        #expect(calls.map(\.0) == ["links", "suggestions", "continue"])
        #expect(calls.last?.1 == ["--link", "3", "--in", "codex", "--dry-run"])
        #expect(model.plan?.planID == "p_d2_decision_needed")
        #expect(model.plan?.applied == false)
        #expect(model.plan?.notes.first?.id == "merge.decision_needed")
        #expect(model.plan?.steps.first?.action == "hold")
        model.select(linkID: 3)
        #expect(model.plan == nil)
    }

    @Test
    func omittedPresentationNotesRemainCompatible() throws {
        let original = try Data(contentsOf: ComponentTests.root.appendingPathComponent("Fixtures/links.sample.json"))
        #expect(try JSONDecoder().decode(LinksResult.self, from: original).notes.isEmpty)
    }

    @MainActor @Test
    func refreshingInvalidatesAnInFlightPreview() async {
        let engine = DeferredContinueEngine()
        let model = PopoverViewModel(engine: engine)
        await model.refresh()
        let slow = Task { await model.continueIn(tool: "codex") }
        await engine.waitUntilBlocked()
        await model.refresh()
        await engine.release()
        await slow.value
        #expect(model.plan == nil)
    }

    @MainActor @Test
    func continuePreviewRendersInBothThemes() async throws {
        try FileManager.default.createDirectory(at: ComponentTests.root.appendingPathComponent("Snapshots"), withIntermediateDirectories: true)
        let model = PopoverViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d2_waiting"))
        await model.refresh()
        await model.continueIn(tool: "codex")
        #expect(model.plan?.steps.count == 1)
        #expect(model.plan?.notes.first?.id == "write.chat_open")
        let plan = try #require(model.plan)
        let step = try #require(plan.steps.first)
        #expect(PlanSteps(steps: plan.steps, excludingNotes: plan.notes).displayedNotes(for: step).isEmpty)
        var changedStep = step
        changedStep.notes[0].text += "!"
        #expect(PlanSteps(steps: plan.steps, excludingNotes: plan.notes).displayedNotes(for: changedStep) == changedStep.notes)
        for theme in Theme.allCases {
            let renderer = ImageRenderer(content: PopoverView(model: model).batonTheme(theme).environment(\.batonSnapshotPresentation, true))
            renderer.scale = 2
            let image = try #require(renderer.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty)
            try png.write(to: ComponentTests.root.appendingPathComponent("Snapshots/D2-continue_preview-\(theme.rawValue).png"))
        }
    }

    @MainActor @Test
    func snapshotsAllEightStatesInBothThemes() async throws {
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for state in Self.states {
            let model = PopoverViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d2_" + state))
            await model.refresh()
            #expect(model.links.isEmpty == (state == "no_links"))
            #expect(model.needsDecision == (state == "decision_needed"))
            #expect(model.suggestions.count == (state == "no_links" ? 0 : 1))
            #expect(!model.notes.isEmpty)
            await model.continueIn(tool: "codex")
            switch state {
            case "no_links": #expect(model.plan == nil)
            case "in_sync", "one_side_ahead":
                #expect(model.plan?.steps.isEmpty == true)
                #expect(model.plan?.notes.first?.id == "nothing_unusual")
            case "paused", "decision_needed", "setup_incomplete":
                #expect(model.plan?.steps.first?.action == "hold")
            case "waiting": #expect(model.plan?.steps.first?.action == "attach")
            case "relaunch_needed":
                #expect(model.plan?.steps.isEmpty == true)
                #expect(model.plan?.notes.first?.id == "relaunch_to_see")
            default: Issue.record("Unregistered fixture state")
            }
            if let id = model.selectedLinkID { model.select(linkID: id) }
            for theme in Theme.allCases {
                let renderer = ImageRenderer(content: PopoverView(model: model).batonTheme(theme).environment(\.batonSnapshotPresentation, true))
                renderer.scale = 2
                let image = try #require(renderer.nsImage)
                #expect(image.size.width > 0 && image.size.height > 0)
                let tiff = try #require(image.tiffRepresentation)
                let bitmap = try #require(NSBitmapImageRep(data: tiff))
                let png = try #require(bitmap.representation(using: .png, properties: [:]))
                #expect(!png.isEmpty)
                try png.write(to: output.appendingPathComponent("D2-\(state)-\(theme.rawValue).png"))
            }
        }
    }
}
