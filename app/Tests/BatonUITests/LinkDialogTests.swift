import AppKit
import SwiftUI
// Renders are checked by a person, not by the test; these checks only prove image production.
import Testing
import BatonKit
@testable import BatonUI

private enum DialogReceiptError: Error { case staleOrChangedRequest }

/// Request-bound transport simulator; Python contract tests prove the actual service effects.
private actor DialogRecordingEngine: EngineTransport {
    var calls: [(String, [String])] = []
    private var previews: [String: (command: String, arguments: [String])] = [:]
    private var receiptCount = 0
    func receipts() -> Int { receiptCount }
    var fullUnavailable = false
    func disableFullCopy() { fullUnavailable = true }
    var delayChats = false
    func setChatsDelay() { delayChats = true }
    var delay = false
    var confirmDelay = false
    func setConfirmDelay() { confirmDelay = true }
    func setDelay() { delay = true }
    func recorded() -> [(String, [String])] { calls }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        calls.append((command, arguments))
        if confirmDelay && arguments.contains("--confirm") { try await Task.sleep(for: .milliseconds(60)) }
        if delay && command == "link" && arguments.contains("codex") { try await Task.sleep(for: .milliseconds(70)) }
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode")
        var data: Data
        if command == "chats", delayChats {
            let tool = arguments[arguments.firstIndex(of: "--tool")! + 1]
            if tool == "cursor" { try await Task.sleep(for: .milliseconds(60)) }
            var chats = try await fixture.chats(tool: tool)
            for i in chats.chats.indices { chats.chats[i].tool = tool; chats.chats[i].id = tool + "-only" }
            return try JSONDecoder().decode(type, from: JSONEncoder().encode(chats))
        }
        if command == "setup", fullUnavailable {
            var setup = try await fixture.setup()
            for i in setup.tools.indices {
                for j in (setup.tools[i].linkModes ?? []).indices {
                    if setup.tools[i].linkModes?[j].mode == "full_copy" { setup.tools[i].linkModes?[j].available = false }
                }
            }
            return try JSONDecoder().decode(type, from: JSONEncoder().encode(setup))
        }
        if command == "link" {
            var plan: LinkResult = try await fixture.response(command: command, arguments: arguments, as: LinkResult.self)
            if let index = arguments.firstIndex(of: "--confirm") {
                guard arguments.indices.contains(index + 1),
                      let preview = previews.removeValue(forKey: arguments[index + 1]),
                      preview.command == command, preview.arguments == Array(arguments.prefix(index)),
                      plan.planID == arguments[index + 1] else { throw DialogReceiptError.staleOrChangedRequest }
                receiptCount += 1
                plan.applied = true
            } else {
                previews[plan.planID] = (command, arguments.filter { $0 != "--dry-run" })
            }
            data = try JSONEncoder().encode(plan)
        } else if command == "relink" {
            let plan: RelinkResult = try await fixture.response(command: command, arguments: arguments, as: RelinkResult.self)
            data = try JSONEncoder().encode(plan)
        } else { return try await fixture.response(command: command, arguments: arguments, as: type) }
        return try JSONDecoder().decode(type, from: data)
    }
}

@Suite(.serialized)
struct LinkDialogTests {
    static let states = ["claude", "codex", "opencode", "cursor", "already", "unavailable", "large"]
    @MainActor private func loaded(_ state: String) async throws -> LinkDialogViewModel {
        let engine = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_"+state)
        let source: Chat = try await engine.response(command: "chat", arguments: [], as: Chat.self)
        let model = LinkDialogViewModel(engine: engine); await model.load(source: source); return model
    }
    @Test func receiptSimulatorRefusesUnknownChangedAndConsumedPlans() async throws {
        let engine = DialogRecordingEngine()
        let request = ["--from", "opencode:source", "--to", "claude", "--mode", "full_copy"]
        let preview: LinkResult = try await engine.response(command: "link", arguments: request + ["--dry-run"], as: LinkResult.self)
        do {
            let _: LinkResult = try await engine.response(command: "link", arguments: request + ["--confirm", "unknown"], as: LinkResult.self)
            Issue.record("Unknown confirmation token was accepted")
        } catch DialogReceiptError.staleOrChangedRequest {}
        var changed = request; changed[1] = "opencode:other"
        do {
            let _: LinkResult = try await engine.response(command: "link", arguments: changed + ["--confirm", preview.planID], as: LinkResult.self)
            Issue.record("Changed request was accepted")
        } catch DialogReceiptError.staleOrChangedRequest {}
        #expect(await engine.receipts() == 0)
        let fresh: LinkResult = try await engine.response(command: "link", arguments: request + ["--dry-run"], as: LinkResult.self)
        let receipt: LinkResult = try await engine.response(command: "link", arguments: request + ["--confirm", fresh.planID], as: LinkResult.self)
        #expect(receipt.applied)
        do {
            let _: LinkResult = try await engine.response(command: "link", arguments: request + ["--confirm", fresh.planID], as: LinkResult.self)
            Issue.record("Consumed token was accepted twice")
        } catch DialogReceiptError.staleOrChangedRequest {}
        #expect(await engine.receipts() == 1)
    }

    @MainActor @Test func staleOrIncompleteDisplayCannotApproveChangedNotes() async throws {
        let engine = DialogRecordingEngine(); let model = LinkDialogViewModel(engine: engine)
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        await model.load(source: source)
        let old = try #require(model.displayReceipt)
        model.didDisplay(PlanDisplayReceipt(planID: old.planID, revision: old.revision, notes: []))
        await model.confirm()
        #expect(!(await engine.recorded()).contains { $0.1.contains("--confirm") })
        model.didDisplay(old); #expect(model.canConfirm)
        await model.selectTarget("cursor")
        let next = try #require(model.displayReceipt)
        #expect(next.notes != old.notes)
        model.didDisplay(old); await model.confirm()
        #expect(!model.canConfirm)
        #expect(!(await engine.recorded()).contains { $0.1.contains("--confirm") })
        model.didDisplay(next); #expect(model.canConfirm)
    }
    @MainActor @Test func d5DuplicateSentencesAppearOnceInBothReviews() async throws {
        for state in Self.states {
            let model = try await loaded(state)
            let plan = try #require(model.plan)
            let review = PlanReviewViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_" + state))
            await review.preview(.link(from: model.source!.tool + ":" + model.source!.id, to: model.target!, mode: model.mode!))
            #expect(model.planNotes == displayedPlanNotes(plan))
            for notes in [model.planNotes, review.planNotes] {
                for (index, note) in notes.enumerated() {
                    #expect(!notes.prefix(index).contains { sameSentence($0, note) })
                }
            }
        }
        var plan = try #require(try await loaded("opencode").plan)
        let note = try #require(plan.notes.first)
        var metadata = note; metadata.buttons = []
        plan.steps[0].notes.append(metadata)
        #expect(displayedPlanNotes(plan).filter { sameSentence($0, note) }.count == 1)
        var changed = metadata; changed.values["different"] = .string("value")
        plan.steps[0].notes.append(changed)
        #expect(!sameSentence(changed, note))
        #expect(displayedPlanNotes(plan).filter { filledSentence($0) == filledSentence(note) }.count == 1)
        // The first occurrence owns provenance; repeating it on two sides adds no prose.
        let neutral = Note(id: "fixture.side", tone: "info", values: [:], text: "Side fixture", buttons: [])
        var other = plan.steps[0]; other.tool = "other"; other.notes = [neutral]
        plan.notes = [neutral]; plan.steps[0].notes = [neutral]; plan.steps.append(other)
        #expect(displayedPlanNotes(plan).filter { $0.id == neutral.id }.count == 1)
    }
    @MainActor @Test func eachTargetShowsItsOwnEngineNotesAndEligibility() async throws {
        for state in Self.states {
            let model = try await loaded(state)
            #expect(!model.planNotes.isEmpty)
            #expect(model.targetTools.allSatisfy { $0.installed })
            #expect(model.targetTools.allSatisfy { $0.tool != model.source?.tool })
            #expect(model.modes.count == 3)
            #expect(!model.canConfirm)
            if state == "already" { #expect(model.currentLink?.linkID == 3); #expect(model.planNotes.contains { $0.id == "link.already_linked" }); #expect(!model.canConfirm) }
            if state == "unavailable" {
                await model.selectTarget("opencode")
                let unavailable = try #require(model.modes.first { !$0.available })
                #expect(unavailable.reason != nil)
                let before = model.mode; await model.selectMode(unavailable.mode); #expect(model.mode == before)
            }
            if state == "large" { #expect(model.planNotes.contains { $0.id == "link.large_copy" }) }
        }
    }
    @MainActor @Test func switchingTargetInvalidatesDisplayedNotesAndIgnoresStalePreview() async throws {
        let engine = DialogRecordingEngine(); let model = LinkDialogViewModel(engine: engine)
        let source: Chat = try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode").response(command: "chat", arguments: [], as: Chat.self)
        await model.load(source: source); model.didDisplay(try #require(model.displayReceipt)); #expect(model.canConfirm)
        await engine.setDelay()
        let old = Task { await model.selectTarget("codex") }
        try await Task.sleep(for: .milliseconds(10))
        await model.selectTarget("cursor"); await old.value
        #expect(model.target == "cursor"); #expect(model.plan?.steps.first?.tool == "cursor")
        #expect(!model.canConfirm)
        #expect(model.planNotes.first?.values["tool"] == .string("Cursor"))
    }
    @MainActor @Test func confirmationUsesOnlyTheDisplayedPreviewAndCopyNeverLinks() async throws {
        let engine = DialogRecordingEngine(); let model = LinkDialogViewModel(engine: engine)
        let source: Chat = try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode").response(command: "chat", arguments: [], as: Chat.self)
        await model.load(source: source); await model.confirm()
        var calls = await engine.recorded(); #expect(!calls.contains { $0.1.contains("--confirm") })
        let id = try #require(model.plan?.planID); model.didDisplay(try #require(model.displayReceipt)); await model.confirm()
        calls = await engine.recorded(); #expect(calls.contains { $0.0 == "link" && $0.1.suffix(2) == ["--confirm", id] })
        #expect(model.finished)
        await model.load(source: source); await model.choose(.copy)
        calls = await engine.recorded(); let copy = try #require(calls.last { $0.0 == "copy" })
        #expect(!copy.1.contains("--and-link")); #expect(model.planNotes.contains { $0.id == "link.copy" })
    }
    @MainActor @Test func replacementRoutesNameRetainedSideAndSelectedMode() async throws {
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_already")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        let link = try #require(try await fixture.links().links.first)
        let engine = DialogRecordingEngine(); let model = LinkDialogViewModel(engine: engine)
        await model.load(source: source, link: link); await model.choose(.change); await model.selectMode("attached_history")
        var calls = await engine.recorded(); let relink = try #require(calls.last { $0.0 == "relink" })
        #expect(relink.1.contains("--keep")); #expect(relink.1.contains(source.tool)); #expect(relink.1.contains("attached_history"))
        await model.load(source: source, link: link, replacing: "codex")
        calls = await engine.recorded(); let full = try #require(calls.last { $0.0 == "link" })
        #expect(full.1.prefix(6) == ["--link", "3", "--replace", "codex", "--mode", "full_copy"])
    }
    @MainActor @Test func applyingLocksTheSelectionUntilTheResultIsVisible() async throws {
        let engine = DialogRecordingEngine(); let model = LinkDialogViewModel(engine: engine)
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        await model.load(source: source); model.didDisplay(try #require(model.displayReceipt)); await engine.setConfirmDelay()
        let applying = Task { await model.confirm() }; try await Task.sleep(for: .milliseconds(10))
        #expect(model.isApplying); let target = model.target
        await model.selectTarget("cursor"); await model.choose(.copy); model.cancel()
        #expect(model.target == target); #expect(model.action == .link)
        await applying.value; #expect(model.finished); #expect(!model.isApplying)
        #expect(model.plan?.applied == true)
    }
    @MainActor @Test func attachedHistoryModeGetsItsOwnNotesAndFreshLoadClearsChatSelection() async throws {
        let model = try await loaded("opencode")
        let oldID = model.plan?.planID
        await model.selectMode("attached_history")
        #expect(model.plan?.planID != oldID)
        #expect(model.planNotes.contains { $0.id == "link.attached_history" })
        #expect(!model.canConfirm)
        let destination = try #require(model.targetChats.first?.id)
        await model.selectChat(destination); await model.selectMode("brief")
        #expect(model.targetChat == destination); #expect(model.mode == "attached_history")
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        await model.load(source: source); #expect(model.targetChat == nil); #expect(model.mode == "full_copy")
    }
    @MainActor @Test func copyAndFullCopyNeverBypassUnavailableFullHistory() async throws {
        let engine = DialogRecordingEngine(); await engine.disableFullCopy()
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_already")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        let links = try await fixture.links(); let link = try #require(links.links.first)
        let model = LinkDialogViewModel(engine: engine); await model.load(source: source, link: link)
        await model.choose(.copy); #expect(model.plan == nil); #expect(!model.canConfirm)
        await model.load(source: source, link: link, replacing: "codex")
        #expect(model.mode == "full_copy"); #expect(model.plan == nil)
        let calls = await engine.recorded()
        #expect(!calls.contains { $0.0 == "copy" || $0.1.contains("--replace") })
    }
    @MainActor @Test func oldToolChatsCannotBeSelectedWhileNewToolChatsLoad() async throws {
        let engine = DialogRecordingEngine(); await engine.setChatsDelay()
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_opencode")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        let model = LinkDialogViewModel(engine: engine); await model.load(source: source)
        let oldID = try #require(model.targetChats.first?.id)
        let switching = Task { await model.selectTarget("cursor") }
        try await Task.sleep(for: .milliseconds(10))
        #expect(model.targetChats.isEmpty)
        await model.selectChat(oldID)
        await switching.value
        #expect(model.targetChat == nil)
        let calls = await engine.recorded()
        #expect(!calls.contains { $0.1.contains("cursor:" + oldID) })
    }
    @MainActor @Test func replacementPreviewNamesExistingLinkAndPreservesEarlierChat() async throws {
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d5_already")
        let source: Chat = try await fixture.response(command: "chat", arguments: [], as: Chat.self)
        let link = try #require(try await fixture.links().links.first)
        let model = LinkDialogViewModel(engine: fixture)
        await model.load(source: source, link: link, replacing: "codex")
        #expect(model.plan?.linkID == 3)
        #expect(model.planNotes.contains { $0.id == "link.full_copy" })
        #expect(model.planNotes.contains { $0.text.contains("current chat stays exactly as it is") })
    }
    @MainActor @Test func unavailableFormatOffersOnlyItsMeasuredReasonAndCopyOffersLink() async throws {
        let model = try await loaded("unavailable")
        for tool in model.tools {
            if tool.tool == "opencode" {
                #expect(tool.linkModes?.first { !$0.available }?.reason?.id == "format.unknown_version")
                #expect(tool.linkModes?.first { $0.mode == "attached_history" }?.available == true)
            } else {
                #expect(tool.linkModes?.allSatisfy(\.available) == true)
            }
        }
        await model.choose(.copy)
        #expect(model.buttons.contains { $0.id == "copy_and_link" && $0.label == "Copy and link" })
    }
    @MainActor @Test func eachFixtureRendersInBothThemes() async throws {
        let directory = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        for state in Self.states {
            let model = try await loaded(state)
            for theme in Theme.allCases {
                let renderer = ImageRenderer(content: LinkDialogView(model: model).environment(\.batonTheme, theme).environment(\.batonSnapshotPresentation, true))
                let image = try #require(renderer.nsImage)
                let tiff = try #require(image.tiffRepresentation)
                let bitmap = try #require(NSBitmapImageRep(data: tiff))
                let png = try #require(bitmap.representation(using: .png, properties: [:])); #expect(!png.isEmpty)
                try png.write(to: directory.appendingPathComponent("D5-\(state)-\(theme.rawValue).png"))
            }
        }
    }
}
