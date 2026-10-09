import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

private actor StatusRecordingEngine: EngineTransport {
    var calls: [(String, [String])] = []
    var paused = false
    var delayed = false
    var fail = false
    var removed = false
    func setDelayed() { delayed = true }
    func setFail() { fail = true }
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        calls.append((command, arguments))
        if delayed && ["unlink", "history", "pause"].contains(command) { try await Task.sleep(for: .milliseconds(60)) }
        let fixture = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), states: ["status": "d4_s1", "unlink": "d4_actions", "copy": "d4_actions", "sync": "d4_actions", "relaunch": "d4_actions"])
        if command == "status" {
            if fail { throw EngineCommandError(kind: "chat_changed", note: Note(id: "fixture.failure", tone: "warning", values: [:], text: "Fixture failure", buttons: [])) }
            var result: StatusResult = try await fixture.status(link: 3, messages: true)
            result.paused = paused
            result.linkID = Int(arguments[arguments.firstIndex(of: "--link")! + 1])!
            return try JSONDecoder().decode(type, from: JSONEncoder().encode(result))
        }
        if command == "links" {
            var result: LinksResult = try await fixture.links()
            if removed { result.links.removeAll { $0.linkID == 3 } }
            return try JSONDecoder().decode(type, from: JSONEncoder().encode(result))
        }
        if command == "unlink", arguments.contains("--confirm") {
            var result: UnlinkResult = try await fixture.response(command: command, arguments: arguments, as: UnlinkResult.self)
            result.applied = true; removed = true
            return try JSONDecoder().decode(type, from: JSONEncoder().encode(result))
        }
        if command == "pause" { paused = true }
        if command == "resume" { paused = false }
        return try await fixture.response(command: command, arguments: arguments, as: type)
    }
}

@Suite(.serialized)
struct SyncStatusTests {
    static let scenarios = (1...12).map { "s\($0)" } + ["s4b", "paused", "missing", "hooks", "unknown"]
    @MainActor private func model(_ scenario: String) async -> SyncStatusViewModel {
        let model = SyncStatusViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d4_" + scenario))
        await model.load(link: 3)
        return model
    }
    @MainActor @Test
    func eachAcceptanceScenarioKeepsTheExpectedEnginePositionAndWording() async throws {
        let expectations: [(String, String, Int, Int, Int, String?)] = [
            ("s1", "claude", 2, 2, 2, "write.chat_open_release"), ("s2", "claude", 4, 2, 0, "status.attached"),
            ("s3", "claude", 4, 4, 0, nil), ("s4", "codex", 4, 4, 0, nil),
            ("s4b", "codex", 3, 3, 1, "status.chat_held"), ("s5", "codex", 0, 0, 12, "status.first_message"),
            ("s6", "codex", 12, 0, 0, "status.attached"), ("s7", "claude", 3, 3, 1, "merge.decision_needed"),
            ("s8", "codex", 3, 3, 1, "setup.trust_once"), ("s9", "claude", 3, 3, 1, "write.chat_open_release"),
            ("s10", "claude", 4, 0, 0, "status.new_chat_relaunch"), ("s11", "codex", 4, 4, 0, nil),
            ("s12", "claude", 4, 4, 0, nil), ("paused", "claude", 2, 2, 2, "link.paused"),
            ("missing", "claude", 2, 2, 2, "side.missing"), ("hooks", "claude", 2, 2, 2, "setup.trust_once"),
            ("unknown", "claude", 2, 2, 2, "format.unknown_version")
        ]
        for (scenario, tool, agent, shown, waiting, noteID) in expectations {
            let model = await model(scenario)
            let side = try #require(model.status?.sides[tool])
            #expect(side.agentHas == agent); #expect(side.chatShows == shown); #expect(side.waiting == waiting)
            if let noteID { #expect(side.notes.contains { $0.id == noteID && !$0.text.isEmpty }) }
            #expect(side.notes.contains { $0.id == "status.summary" })
            #expect(side.notes.contains { $0.id == "status.context" })
            #expect(side.notes.contains { $0.id == "status.since_you_left" } == (side.agentHas < side.total || side.waiting > 0))
            #expect(model.turns.count == side.total)
        }
        let s2 = await model("s2")
        #expect(s2.status?.sides["claude"]?.attached == 2)
        #expect(!s2.status!.sides["claude"]!.notes.contains { $0.id == "write.chat_open" })
        let s5 = await model("s5")
        #expect(!s5.status!.sides["codex"]!.notes.contains { $0.id.contains("relaunch") })
        let s9 = await model("s9")
        #expect(s9.turns.last?.states["claude"] == "waiting")
        let s10 = await model("s10")
        #expect(s10.turns.allSatisfy { $0.states["claude"] == "added" })
        #expect(s10.status?.sides["claude"]?.notes.first { $0.id == "status.new_chat_relaunch" }?.text == "Relaunch Claude to see this chat.")
        #expect(!s10.status!.sides["claude"]!.notes.contains { $0.id == "new_chat.relaunch" })
        let s11 = await model("s11")
        #expect(s11.status?.sides["codex"]?.chat.name == "Renamed orchard tests")
        #expect(s11.status?.sides["claude"]?.chat.name == "Imaginary orchard")
    }
    @MainActor @Test
    func suppliedToolLabelsAndIdleOffersRemainEngineData() async throws {
        let model = await model("s1")
        #expect(model.toolLabel("claude") == "Claude")
        #expect(model.toolLabel("codex") == "Codex")
        let reached = model.status?.notes.first { $0.id == "status.reached" && $0.values["tool"] == .string(model.toolLabel("claude")) }
        #expect(reached != nil)
        let engine = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d2_in_sync")
        let popover = PopoverViewModel(engine: engine); await popover.refresh()
        #expect(popover.continueNote(for: "claude") != nil)
        #expect(popover.continueNote(for: "codex") != nil)
        let window = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await window.refresh()
        #expect(window.label(for: .chats("claude"))?.values["tool"] == .string("Claude"))
        var side = try #require(model.status?.sides["claude"])
        side.toolLabel = "Fixture supplied name"
        #expect(side.displayLabel == "Fixture supplied name")
        #expect(model.sideButtons(side).map(\.id).contains("add_now"))
        #expect(model.sideButtons(side).map(\.id).contains("close_sync_reopen"))
        let sideData = try JSONEncoder().encode(side)
        let object = try #require(JSONSerialization.jsonObject(with: sideData) as? [String: Any])
        #expect(object["tool_label"] as? String == "Fixture supplied name")
    }
    @MainActor @Test
    func anUpToDateSideCannotShowASinceYouLeftDigest() async throws {
        let model = await model("s1")
        var side = try #require(model.status?.sides["codex"])
        #expect(side.agentHas == side.total)
        #expect(side.sinceYouLeft == nil)
        #expect(!model.displayedNotes(for: side).contains { $0.id == "status.since_you_left" })
        side.notes.append(Note(id: "status.since_you_left", tone: "info", values: [:], text: "A stale digest", buttons: []))
        #expect(!model.displayedNotes(for: side).contains { $0.id == "status.since_you_left" })
        side.agentHas -= 1
        #expect(model.displayedNotes(for: side).contains { $0.id == "status.since_you_left" })
    }
    @Test
    func timestampPresentationUsesLocalCalendarDayAndSystemStyles() throws {
        let parser = ISO8601DateFormatter()
        let now = try #require(parser.date(from: "2026-10-05T01:00:00Z"))
        let locale = Locale(identifier: "en_US")
        let zone = try #require(TimeZone(secondsFromGMT: -7 * 3600))
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = zone
        let formatter = DateFormatter(); formatter.locale = locale; formatter.calendar = calendar; formatter.timeZone = zone
        formatter.dateStyle = .none; formatter.timeStyle = .short
        let sameLocalDay = try #require(parser.date(from: "2026-10-04T23:30:00Z"))
        #expect(DisplayTime.string("2026-10-04T23:30:00Z", now: now, locale: locale, calendar: calendar, timeZone: zone) == formatter.string(from: sameLocalDay))
        formatter.dateStyle = .short
        let previous = try #require(parser.date(from: "2026-10-04T01:00:00Z"))
        #expect(DisplayTime.string("2026-10-04T01:00:00Z", now: now, locale: locale, calendar: calendar, timeZone: zone) == formatter.string(from: previous))
        #expect(DisplayTime.string("invalid timestamp") == "invalid timestamp")
        let raw = "2026-10-04T01:00:00Z"
        #expect(!DisplayTime.noteText("Last checked " + raw, values: ["at": .string(raw)]).contains(raw))
    }
    @MainActor @Test
    func filtersStripJumpAndFoldPreserveRealTurnIdentity() async throws {
        let model = await model("s1")
        #expect(model.foldedCount == 2)
        #expect(model.displayedTurns.map(\.id) == [43, 44])
        #expect(model.focusedTurn == 43)
        #expect(model.note("screen.earlier_turns")?.values["n"] == .number(2))
        model.setFilter(.waiting); #expect(model.displayedTurns.map(\.id) == [43, 44])
        model.setFilter(.attached); #expect(model.displayedTurns.isEmpty)
        model.setFilter(.pinned); #expect(model.displayedTurns.map(\.id) == [42])
        model.setFilter(.kept); #expect(model.displayedTurns.isEmpty)
        model.jump(to: 41)
        #expect(model.filter == .all); #expect(model.focusedTurn == 41); #expect(model.unfolded)
        #expect(model.displayedTurns.count == 4)
        model.jump(to: 999); #expect(model.focusedTurn == 41)
        let synced = await self.model("s3")
        #expect(synced.displayedTurns.map(\.id) == [44]); #expect(synced.foldedCount == 3)
        #expect(synced.note("screen.earlier_turns")?.values["n"] == .number(3))
    }
    @MainActor @Test
    func longReplyAndToolActivityExpandWithoutHookText() async throws {
        let model = await model("s12")
        let turn = try #require(model.turns.last)
        #expect(model.messages(for: turn).count == 2)
        #expect(model.messages(for: turn).last!.text.count > 240)
        #expect(model.toolMessages(for: turn).count == 4)
        #expect(!model.messages(for: turn).contains { $0.kind == "system" })
        #expect(model.note("screen.tool_calls", turn: turn.id)?.values["n"] == .number(2))
        model.toggleReply(turn.id); model.toggleTools(turn.id)
        #expect(model.expandedReplies.contains(turn.id)); #expect(model.expandedTools.contains(turn.id))
        model.toggleReply(turn.id); model.toggleTools(turn.id)
        #expect(model.expandedReplies.isEmpty); #expect(model.expandedTools.isEmpty)
        #expect(model.hasCollapsedMessage(in: turn))
        var multiline = turn
        multiline.messages = [TurnMessage(kind: "reply", text: "one\ntwo\nthree\nfour\nfive")]
        #expect(model.hasCollapsedMessage(in: multiline))
        multiline.messages = [TurnMessage(kind: "reply", text: "A short reply.")]
        #expect(!model.hasCollapsedMessage(in: multiline))
        var flattened = turn
        flattened.messages = [TurnMessage(kind: "tool_text", text: "Non-replayable activity")]
        #expect(model.messages(for: flattened).isEmpty)
        #expect(model.toolMessages(for: flattened).count == 1)
    }
    @MainActor @Test
    func buttonsUseImmediateCommandsAndPreviewWritingActions() async throws {
        let engine = StatusRecordingEngine(); let model = SyncStatusViewModel(engine: engine)
        await model.load(link: 3)
        await model.togglePause(); #expect(model.status?.paused == true)
        await model.togglePause(); #expect(model.status?.paused == false)
        await model.open(tool: "codex")
        await model.showHistory(); #expect(model.history?.count == 1)
        await model.previewRemoval(); #expect(model.plan?.applied == false)
        model.cancelPlan()
        await model.previewCopy(from: "claude", to: "codex")
        let calls = await engine.calls
        #expect(calls.first?.1 == ["--link", "3", "--messages"])
        #expect(calls.filter { ["pause", "resume"].contains($0.0) }.allSatisfy { $0.1 == ["--link", "3"] })
        #expect(calls.contains { $0.0 == "open" && $0.1 == ["--tool", "codex", "--chat", "sample-b"] })
        #expect(calls.contains { $0.0 == "unlink" && $0.1 == ["--link", "3", "--dry-run"] })
        #expect(calls.contains { $0.0 == "copy" && $0.1 == ["--from", "claude:sample-a", "--to", "codex", "--dry-run"] })
        #expect(!calls.contains { $0.1.contains("--confirm") })
    }
    @MainActor @Test
    func unavailableNavigationActionsAreDisabledAndNeverDispatched() async {
        let engine = StatusRecordingEngine(); let model = SyncStatusViewModel(engine: engine)
        await model.load(link: 3)
        for id in ["relaunch", "close_sync_reopen", "add_now", "open"] {
            #expect(model.supportsSideAction(NoteButton(id: id, label: id), tool: "claude"))
        }
        for id in ["merge_show", "setup_fix", "setup_check", "when_idle", "attach", "resume"] {
            let button = NoteButton(id: id, label: id)
            #expect(!model.supportsSideAction(button, tool: "claude"))
            await model.sideAction(button, tool: "claude")
        }
        #expect(await engine.calls.count == 1)
        let missing = await self.model("missing")
        #expect(!missing.supportsSideAction(NoteButton(id: "open", label: "open"), tool: "claude"))
        let paused = await self.model("paused")
        #expect(paused.supportsSideAction(NoteButton(id: "resume", label: "resume"), tool: "claude"))
    }
    @MainActor @Test
    func exactPreviewIDIsUsedForConfirmationAndOnlyItsActionButtonsAreEnabled() async throws {
        let engine = StatusRecordingEngine(); let model = SyncStatusViewModel(engine: engine)
        await model.load(link: 3)
        await model.previewRemoval()
        #expect(model.plan?.planID == "p_d4_unlink")
        #expect(model.confirmationButtons.map(\.id) == ["unlink", "cancel"])
        await model.confirmPlan()
        let calls = await engine.calls
        #expect(calls.last?.0 == "unlink")
        #expect(calls.last?.1 == ["--link", "3", "--confirm", "p_d4_unlink"])
        #expect(model.removedLinkID == 3)
        #expect(model.status == nil)
        model.cancelPlan()
        await model.confirmPlan()
        #expect(await engine.calls.count == calls.count)
        await model.load(link: 3)
        await model.previewCopy(from: "claude", to: "codex")
        #expect(model.confirmationButtons.map(\.id) == ["copy", "cancel"])
        #expect(!model.confirmationButtons.contains { $0.id == "copy_and_link" })
    }
    @MainActor @Test
    func concurrentConfirmationRunsOnceAndRemovalRefreshClearsWindowSelection() async throws {
        let engine = StatusRecordingEngine(); await engine.setDelayed()
        let model = SyncStatusViewModel(engine: engine)
        let window = WindowViewModel(engine: engine)
        await window.refresh(); window.select(.link(3))
        #expect(window.selectedLink?.linkID == 3)
        await model.load(link: 3); await model.previewRemoval()
        let first = Task { await model.confirmPlan() }
        try await Task.sleep(for: .milliseconds(10))
        #expect(model.isConfirming)
        await model.confirmPlan()
        await first.value
        #expect(!model.isConfirming)
        #expect(model.removedLinkID == 3)
        #expect(model.status == nil)
        let calls = await engine.calls
        #expect(calls.filter { $0.0 == "unlink" && $0.1.contains("--confirm") }.count == 1)
        await window.refresh()
        #expect(window.selectedLink == nil); #expect(window.selection == nil)
        #expect(!window.links.contains { $0.linkID == 3 })
    }
    @MainActor @Test
    func narrowWindowHostsReadableStatusAndPreservesBothNames() async throws {
        let window = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await window.refresh(); window.select(.link(3))
        let status = await model("s7")
        #expect(window.selectedLink?.linkID == status.status?.linkID)
        for theme in Theme.allCases {
            let renderer = ImageRenderer(content: WindowView(model: window, statusModel: status)
                .batonTheme(theme).environment(\.batonSnapshotPresentation, true))
            let image = try #require(renderer.nsImage)
            #expect(image.size.width == 1000); #expect(image.size.height == 600)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            try png.write(to: ComponentTests.root.appendingPathComponent("Snapshots/D4-window-\(theme.rawValue).png"))
        }
    }
    @MainActor @Test
    func delayedActionsCannotReplaceANewLinksPlanHistoryOrStatus() async throws {
        let engine = StatusRecordingEngine(); await engine.setDelayed()
        let model = SyncStatusViewModel(engine: engine); await model.load(link: 3)
        let preview = Task { await model.previewRemoval() }
        let history = Task { await model.showHistory() }
        let pause = Task { await model.togglePause() }
        try await Task.sleep(for: .milliseconds(10))
        await model.load(link: 8)
        await preview.value; await history.value; await pause.value
        #expect(model.status?.linkID == 8); #expect(model.plan == nil); #expect(model.history == nil)
        let calls = await engine.calls
        #expect(calls.filter { $0.0 == "status" }.count == 2)
    }
    @MainActor @Test
    func selectedLinkFixturesMatchIDsAndNamesAndMismatchedResponsesAreRejected() async {
        let engine = FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled")
        let model = SyncStatusViewModel(engine: engine)
        for link in [3, 4, 5] {
            await model.load(link: link)
            #expect(model.status?.linkID == link)
            #expect(model.status?.sides["claude"]?.chat.id == "d3-\(link)-claude")
            #expect(model.status?.sides["codex"]?.chat.id == "d3-\(link)-codex")
        }
        await model.load(link: 8)
        #expect(model.status == nil); #expect(model.plan == nil)
    }
    @MainActor @Test
    func refreshingTheSameLinkInvalidatesVisibleAndPendingPreviews() async {
        let engine = StatusRecordingEngine()
        let model = SyncStatusViewModel(engine: engine)
        await model.load(link: 3)
        await model.previewRemoval()
        #expect(model.plan != nil)
        await model.load(link: 3)
        #expect(model.plan == nil)
        await engine.setDelayed()
        let preview = Task { await model.previewRemoval() }
        try? await Task.sleep(for: .milliseconds(10))
        await model.load(link: 3)
        await preview.value
        #expect(model.status?.linkID == 3)
        #expect(model.plan == nil)
        #expect(model.confirmationButtons.isEmpty)
    }
    @MainActor @Test
    func changedLinkAndEngineFailureNeverShowThePreviousChat() async {
        let engine = StatusRecordingEngine(); let model = SyncStatusViewModel(engine: engine)
        await model.load(link: 3); await engine.setFail(); await model.load(link: 8)
        #expect(model.status == nil); #expect(model.errorNote?.id == "fixture.failure")
    }
    @MainActor @Test
    func snapshotsEverySpecifiedStateAndExpandedReply() async throws {
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        for scenario in Self.scenarios {
            let model = await model(scenario)
            for theme in Theme.allCases {
                try render(model, name: scenario, theme: theme, output: output)
                if scenario == "s12", let turn = model.turns.last {
                    model.toggleReply(turn.id); model.toggleTools(turn.id)
                    try render(model, name: scenario + "_expanded", theme: theme, output: output)
                    model.toggleReply(turn.id); model.toggleTools(turn.id)
                }
            }
        }
    }
    @MainActor private func render(_ model: SyncStatusViewModel, name: String, theme: Theme, output: URL) throws {
        let renderer = ImageRenderer(content: SyncStatusView(model: model).padding(20).frame(width: 1000)
            .background(theme.background).batonTheme(theme).environment(\.batonSnapshotPresentation, true))
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        #expect(image.size.width == 1000); #expect(image.size.height > 100)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        #expect(!png.isEmpty)
        try png.write(to: output.appendingPathComponent("D4-\(name)-\(theme.rawValue).png"))
    }
}
