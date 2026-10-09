import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

/// A contract provider: tokens bind the complete request and revision, and modeled effects are explicit.
private actor D6Engine: EngineTransport {
    struct Issued { let command: String; let arguments: [String]; let object: [String: Any]; let revision: Int }
    enum Failure: Error { case staleOrWrongRequest }
    enum ConfirmationBehavior { case apply, refuse, ambiguous, nextStage }
    private(set) var calls: [(command: String, arguments: [String])] = []
    private var plans: [String: Issued] = [:]
    private var revision = 0
    private var serial = 0
    private var confirmationStarted = false
    private(set) var created: [(source: String, target: String, linked: Bool)] = []
    private(set) var deliveries: [String] = []
    let state: String
    let custom: Data?
    let confirmationDelay: Bool
    let confirmationBehavior: ConfirmationBehavior
    init(state: String, custom: Data? = nil, confirmationDelay: Bool = false, confirmationBehavior: ConfirmationBehavior = .apply) {
        self.state = state; self.custom = custom; self.confirmationDelay = confirmationDelay
        self.confirmationBehavior = confirmationBehavior
    }
    func writes() -> [(command: String, arguments: [String])] { calls.filter { $0.arguments.contains("--confirm") } }
    func previews() -> [(command: String, arguments: [String])] { calls.filter { $0.arguments.contains("--dry-run") } }
    func effects() -> (copies: Int, links: Int, sources: [String], targets: [String], deliveries: [String]) {
        (created.count, created.filter(\.linked).count, created.map(\.source), created.map(\.target), deliveries)
    }
    func invalidate() { revision += 1 }
    func startedConfirming() -> Bool { confirmationStarted }
    func response<R: Decodable & Sendable>(command: String, arguments: [String], as type: R.Type) async throws -> R {
        calls.append((command, arguments))
        if command == "setup" {
            return try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d6_labels")
                .response(command: command, arguments: arguments, as: type)
        }
        let confirmIndex = arguments.firstIndex(of: "--confirm")
        let plain = confirmIndex.map { Array(arguments[..<$0]) } ?? arguments.filter { $0 != "--dry-run" }
        var object: [String: Any]
        if let index = confirmIndex {
            confirmationStarted = true
            if confirmationDelay { try await Task.sleep(for: .milliseconds(70)) }
            let token = arguments[index + 1]
            guard let issued = plans.removeValue(forKey: token), issued.command == command,
                  issued.arguments == plain, issued.revision == revision else { throw Failure.staleOrWrongRequest }
            object = issued.object
            if confirmationBehavior == .ambiguous { throw Failure.staleOrWrongRequest }
            if confirmationBehavior == .refuse { return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object)) }
            if confirmationBehavior == .nextStage {
                object["plan_id"] = token + "_create"; object["stage"] = "create"
                var confirmation = object["confirmation"] as! [String: Any]
                confirmation["id"] = "plan.confirm_brief_creation"; object["confirmation"] = confirmation
                plans[token + "_create"] = Issued(command: command, arguments: plain, object: object, revision: revision)
                return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
            }
            object["applied"] = true
            if command == "link" || command == "copy" {
                created.append((Self.value("--from", in: plain)!, Self.value("--to", in: plain)!, command == "link" || plain.contains("--and-link")))
            }
            if command == "sync", let target = Self.value("--to", in: plain) { deliveries.append(target) }
        } else {
            object = try payload(command: command, arguments: plain)
            serial += 1
            let token = "p_d6_\(serial)"
            object["plan_id"] = token
            object["applied"] = false
            plans[token] = Issued(command: command, arguments: plain, object: object, revision: revision)
        }
        return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
    private func payload(command: String, arguments: [String]) throws -> [String: Any] {
        if let custom { return try #require(JSONSerialization.jsonObject(with: custom) as? [String: Any]) }
        var selected = state
        if command == "relaunch" { selected = arguments.contains("--when-idle") ? "d6_when_idle" : state == "d6_replying" ? state : "d6_idle" }
        if command == "sync", !state.hasPrefix("d6_claude") && state != "d6_cursor_running" && state != "d6_codex_holding" && state != "d6_opencode_any_time" {
            selected = "d6_claude_open_idle"
        }
        let url = ComponentTests.root.appendingPathComponent("Fixtures/\(command).\(selected).json")
        return try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }
    private static func value(_ flag: String, in arguments: [String]) -> String? {
        arguments.firstIndex(of: flag).map { arguments[$0 + 1] }
    }
}

@Suite(.serialized)
struct PlanReviewTests {
    struct Case { let name: String; let request: PlanRequest }
    static let cases = [
        Case(name: "d6_new_chat_claude", request: .link(from: "codex:c1", to: "claude", mode: "full_copy")),
        Case(name: "d6_new_chat_cursor", request: .link(from: "codex:c1", to: "cursor", mode: "full_copy")),
        Case(name: "d6_new_chat_codex", request: .link(from: "claude:c1", to: "codex", mode: "full_copy")),
        Case(name: "d6_cursor_running", request: .sync(link: 3, to: "cursor")),
        Case(name: "d6_codex_holding", request: .sync(link: 3, to: "codex")),
        Case(name: "d6_claude_open_idle", request: .sync(link: 3, to: "claude")),
        Case(name: "d6_claude_replying", request: .sync(link: 3, to: "claude")),
        Case(name: "d6_opencode_any_time", request: .sync(link: 3, to: "opencode")),
        Case(name: "d6_idle", request: .relaunch(tool: "claude", whenIdle: false, thenSync: 3)),
        Case(name: "d6_replying", request: .relaunch(tool: "claude", whenIdle: false, thenSync: 3)),
    ]
    @MainActor private func model(_ test: Case) async -> (PlanReviewViewModel, D6Engine) {
        let engine = D6Engine(state: test.name)
        let model = PlanReviewViewModel(engine: engine)
        await model.load(test.request)
        return (model, engine)
    }
    @MainActor private func display(_ model: PlanReviewViewModel) throws { model.didDisplay(try #require(model.displayReceipt)) }
    @MainActor private func action(_ id: String, in model: PlanReviewViewModel, tool: String? = nil) throws -> PlanAction {
        try #require(model.actions.first { $0.button.id == id && (tool == nil || $0.offeringTool == tool) })
    }
    private func note(_ id: String, buttons: [(String, String)] = []) -> Note {
        Note(id: id, tone: "info", values: [:], text: id, buttons: buttons.map { NoteButton(id: $0.0, label: $0.1) })
    }
    private func data(notes: [Note], confirmation: Note? = nil, steps: [Step] = [], stage: String? = nil) throws -> Data {
        try JSONEncoder().encode(Plan(planID: "unused", applied: false, linkID: 3, steps: steps,
                                    decisionNeeded: false, notes: notes, confirmation: confirmation, stage: stage))
    }
    @MainActor private func customModel(_ data: Data, request: PlanRequest, delay: Bool = false, behavior: D6Engine.ConfirmationBehavior = .apply) async -> (PlanReviewViewModel, D6Engine) {
        let engine = D6Engine(state: "custom", custom: data, confirmationDelay: delay, confirmationBehavior: behavior)
        let model = PlanReviewViewModel(engine: engine); await model.load(request)
        return (model, engine)
    }

    @MainActor @Test func everyStateRequiresItsExactDisplayBeforeAnyMutation() async throws {
        for test in Self.cases {
            let (model, engine) = await model(test)
            #expect(model.plan != nil); #expect(!model.planNotes.isEmpty); #expect(!model.canConfirm)
            for action in model.actions where action.button.id != "cancel" { await model.choose(action) }
            await model.confirm()
            #expect(await engine.writes().isEmpty)
            #expect(model.outcome == nil)
        }
    }
    @MainActor @Test func staleEmptyPartialAndIdenticalNotesOnNewRevisionNeverUnlock() async throws {
        let (model, engine) = await model(Self.cases[2])
        let receipt = try #require(model.displayReceipt)
        model.didDisplay(PlanDisplayReceipt(planID: receipt.planID, revision: receipt.revision, notes: []))
        #expect(!model.canConfirm)
        model.didDisplay(PlanDisplayReceipt(planID: receipt.planID, revision: receipt.revision, notes: Array(receipt.notes.dropLast())))
        #expect(!model.canConfirm)
        try display(model); #expect(model.canConfirm)
        let oldAction = try action("confirm", in: model)
        await model.preview(Self.cases[2].request)
        let next = try #require(model.displayReceipt)
        #expect(next.notes == receipt.notes); #expect(next.planID != receipt.planID)
        model.didDisplay(receipt); #expect(!model.canConfirm)
        model.didDisplay(PlanDisplayReceipt(planID: next.planID, revision: receipt.revision, notes: next.notes)); #expect(!model.canConfirm)
        await model.choose(oldAction); #expect(await engine.writes().isEmpty)
        try display(model); #expect(model.canConfirm)
        // Even matching plan/text cannot acknowledge a different revision.
        model.didDisplay(PlanDisplayReceipt(planID: next.planID, revision: receipt.revision, notes: next.notes))
        #expect(model.canConfirm) // rejected callback cannot replace the valid current receipt
    }
    @MainActor @Test func confirmingUsesTheIssuedTokenAndCreatesExactlyOneLinkedCounterpart() async throws {
        let (model, engine) = await model(Self.cases[2]); try display(model)
        let id = try #require(model.plan?.planID)
        await model.choose(try action("confirm", in: model))
        #expect(await engine.writes().first?.arguments.suffix(2) == ["--confirm", id])
        let effects = await engine.effects()
        #expect(effects.copies == 1 && effects.links == 1)
        #expect(effects.sources == ["claude:c1"] && effects.targets == ["codex"])
        #expect(model.outcome == .applied)
        await model.confirm(); #expect(await engine.writes().count == 1)
    }
    @MainActor @Test func unknownAndWrongRequestConfirmationNotesNeverMutate() async throws {
        let unknown = note("unexpected", buttons: [("unknown", "Unknown"), ("confirm", "Confirm")])
        let (model, engine) = await customModel(try data(notes: [unknown]), request: .sync(link: 3, to: "codex"))
        try display(model)
        for action in model.actions where action.button.id != "cancel" { await model.choose(action) }
        await model.confirm(); #expect(await engine.writes().isEmpty)
        #expect(!model.canConfirm)
        let (wrong, wrongEngine) = await customModel(try data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_copy", buttons: [("confirm", "Copy")])), request: .sync(link: 3, to: "codex"))
        try display(wrong); await wrong.confirm()
        #expect(await wrongEngine.writes().isEmpty)
    }
    @MainActor @Test func copyAndLinkRepreviewsTheFullRequestAndItsEffectActuallyLinks() async throws {
        let payload = try data(notes: [note("link.copy", buttons: [("copy", "Copy"), ("copy_and_link", "Copy and link")])], confirmation: note("plan.confirm_copy", buttons: [("confirm", "Copy")]))
        let original = PlanRequest.copy(from: "claude:source", to: "codex", andLink: false)
        let (model, engine) = await customModel(payload, request: original); try display(model)
        await model.choose(try action("copy_and_link", in: model))
        #expect(model.request == .copy(from: "claude:source", to: "codex", andLink: true))
        #expect(model.originalRequest == original && !model.canConfirm)
        #expect(await engine.writes().isEmpty)
        try display(model); await model.choose(try action("confirm", in: model))
        let effects = await engine.effects(); #expect(effects.copies == 1 && effects.links == 1)
        #expect(effects.sources == ["claude:source"] && effects.targets == ["codex"])
        let (copy, copyEngine) = await customModel(payload, request: original); try display(copy)
        await copy.choose(try action("copy", in: copy)); #expect(await copyEngine.effects().links == 0)
    }
    @MainActor @Test func duplicateButtonIDsRetainTheOfferingSideRegardlessOfOrder() async throws {
        for order in [["claude", "codex"], ["codex", "claude"]] {
            let steps = order.map { Step(tool: $0, action: "hold", turns: [41], reason: "", needs: [], notes: [note("write.chat_open_release", buttons: [("add_now", "Add them now")])]) }
            let (model, engine) = await customModel(try data(notes: [note("nothing_unusual")], steps: steps), request: .sync(link: 3, to: nil))
            #expect(model.actions.filter { $0.button.id == "add_now" }.count == 2)
            #expect(Set(model.actions.map(\.id)).count == model.actions.count)
            try display(model)
            await model.choose(NoteButton(id: "add_now", label: "Add them now"))
            #expect(await engine.previews().count == 1, "ambiguous legacy button must not choose a side")
            await model.choose(try action("add_now", in: model, tool: "codex"))
            #expect(model.request == .sync(link: 3, to: nil) && model.originalRequest == model.request)
            #expect(model.alternative == .unavailable && !model.canConfirm)
            #expect(await engine.previews().count == 1)
            #expect(await engine.writes().isEmpty)
        }
    }
    @MainActor @Test func addNowNeverConfirmsTheOrdinaryAttachPlan() async throws {
        for noteID in ["write.chat_open_release", "write.release"] {
            let original = PlanRequest.sync(link: 3, to: "codex")
            let steps = [Step(tool: "codex", action: "attach", turns: [41], reason: "chat open", needs: [],
                              notes: [note(noteID, buttons: [("add_now", "Add them now")])])]
            let payload = try data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_sync", buttons: [("confirm", "Sync")]), steps: steps)
            let (model, engine) = await customModel(payload, request: original); try display(model)
            await model.choose(try action("add_now", in: model, tool: "codex"))
            #expect(model.request == original && model.originalRequest == original)
            #expect(model.alternative == .unavailable && !model.canConfirm && model.outcome == nil)
            await model.confirm(); #expect(await engine.writes().isEmpty)
            #expect(await engine.previews().count == 1)
            #expect(await engine.effects().deliveries.isEmpty)
        }
    }
    @MainActor @Test func everyRelaunchConversionIsUnavailableWithoutReplacingTheOriginalRequest() async throws {
        let requests: [PlanRequest] = [.sync(link: 3, to: "codex"), .continueIn(link: 3, tool: "codex"),
                                      .brief(link: 3, to: "codex", writer: "offline"),
                                      .link(from: "claude:source", to: "codex", mode: "full_copy"),
                                      .copy(from: "claude:source", to: "codex", andLink: false)]
        let offers = [("close_sync_reopen", "write.chat_open"), ("close_sync_reopen", "write.chat_open_release"),
                      ("close_sync_reopen", "write.app_must_close"), ("close_sync_reopen", "new_chat.relaunch"),
                      ("relaunch", "relaunch_to_see"), ("relaunch", "write.release")]
        for original in requests {
            for (buttonID, noteID) in offers {
                var object = try #require(JSONSerialization.jsonObject(with: data(notes: [note(noteID, buttons: [(buttonID, "Relaunch")])])) as? [String: Any])
                if case .continueIn = original { object["opened"] = false }
                if case .brief = original { object["brief"] = ["writer": "offline", "tokens": 12, "pinned": []] }
                let (model, engine) = await customModel(try JSONSerialization.data(withJSONObject: object), request: original); try display(model)
                await model.choose(try action(buttonID, in: model))
                #expect(model.request == original && model.originalRequest == original)
                #expect(model.alternative == .unavailable && !model.canConfirm && model.outcome == nil)
                await model.confirm(); #expect(await engine.writes().isEmpty)
                #expect(await engine.previews().count == 1)
                #expect(await engine.effects().copies == 0)
                #expect(await engine.effects().deliveries.isEmpty)
            }
        }
    }
    @MainActor @Test func conflictingAttachProvenanceNeverChangesDestinationOrMode() async throws {
        for destination in ["cursor", "cursor:selected"] {
            let original = PlanRequest.link(from: "claude:source", to: destination, mode: "full_copy")
            var topLevel = note("write.app_must_close", buttons: [("attach", "Attach instead")])
            topLevel.values["tool_id"] = .string("codex")
            let opposite = Step(tool: "codex", action: "hold", turns: [41], reason: "", needs: [], notes: [note("write.app_must_close", buttons: [("attach", "Attach instead")])])
            let conflicting = Step(tool: "cursor", action: "hold", turns: [41], reason: "", needs: [], notes: [topLevel])
            for payload in [try data(notes: [topLevel]), try data(notes: [note("nothing_unusual")], steps: [opposite]),
                            try data(notes: [note("nothing_unusual")], steps: [conflicting])] {
                let (model, engine) = await customModel(payload, request: original); try display(model)
                let attach = try action("attach", in: model)
                #expect(!model.canChoose(attach))
                await model.choose(attach)
                #expect(model.request == original && model.originalRequest == original && model.alternative == nil)
                #expect(await engine.previews().count == 1)
                #expect(await engine.writes().isEmpty)
            }
        }
    }
    @MainActor @Test func topLevelAmbiguousToolNeverFallsBackToFirstStep() async throws {
        let (model, engine) = await customModel(try data(notes: [note("write.chat_open_release", buttons: [("add_now", "Add them now")])], steps: [Step(tool: "claude", action: "hold", turns: [], reason: "", needs: [], notes: [])]), request: .sync(link: 3, to: nil))
        try display(model); await model.choose(try action("add_now", in: model))
        #expect(await engine.previews().count == 1); #expect(await engine.writes().isEmpty)
    }
    @MainActor @Test func newChatCloseAndAttachKeepOriginalIntentWithoutSuccess() async throws {
        for index in [0, 1] {
            let (model, engine) = await model(Self.cases[index]); try display(model)
            await model.choose(try action("close_sync_reopen", in: model))
            #expect(model.originalRequest == Self.cases[index].request && model.request == Self.cases[index].request)
            #expect(model.alternative == .unavailable && model.alternativeNote?.id == "plan.unavailable")
            #expect(!model.canConfirm && model.outcome == nil)
            #expect(model.actions.map(\.button.id) == ["cancel"])
            await model.confirm(); #expect(await engine.writes().isEmpty); #expect(await engine.previews().count == 1)
        }
        let (selection, selectionEngine) = await model(Self.cases[1]); try display(selection)
        await selection.choose(try action("attach", in: selection))
        #expect(selection.alternative == .chooseCounterpart && selection.originalRequest == Self.cases[1].request)
        #expect(selection.outcome == nil && !selection.canConfirm)
        #expect(await selectionEngine.writes().isEmpty)
        let payload = try data(notes: [note("write.app_must_close", buttons: [("attach", "Attach instead")])])
        let copyRequest = PlanRequest.copy(from: "claude:c1", to: "cursor", andLink: false)
        let (copy, copyEngine) = await customModel(payload, request: copyRequest); try display(copy)
        await copy.choose(try action("attach", in: copy))
        #expect(copy.alternative == .unavailable && copy.originalRequest == copyRequest && copy.outcome == nil)
        #expect(await copyEngine.writes().isEmpty)
    }
    @MainActor @Test func counterpartSelectionRepreviewsTheExplicitDestinationAndRetainsOriginal() async throws {
        let original = PlanRequest.link(from: "claude:source", to: "cursor", mode: "full_copy")
        let payload = try data(notes: [note("write.app_must_close", buttons: [("attach", "Attach instead")])], confirmation: note("plan.confirm_link", buttons: [("confirm", "Link")]))
        let (model, engine) = await customModel(payload, request: original); try display(model)
        await model.choose(try action("attach", in: model))
        await model.selectCounterpart("codex:wrong")
        #expect(model.request == original && !model.canConfirm)
        await model.selectCounterpart("cursor:selected")
        #expect(model.request == .link(from: "claude:source", to: "cursor:selected", mode: "attached_history"))
        #expect(model.originalRequest == original && model.outcome == nil && !model.canConfirm)
        #expect(await engine.writes().isEmpty)
        #expect(await engine.previews().last?.arguments == ["--from", "claude:source", "--to", "cursor:selected", "--mode", "attached_history", "--dry-run"])
    }
    @MainActor @Test func syncNowRelaunchLaterCreatesTheOriginalLinkedChat() async throws {
        let (model, engine) = await model(Self.cases[0]); try display(model)
        await model.choose(try action("sync_relaunch_later", in: model))
        #expect(await engine.writes().first?.command == "link")
        #expect(await engine.effects().links == 1)
    }
    @MainActor @Test func syncNowRelaunchLaterRejectsEveryConflictingOfferingSide() async throws {
        let requests: [PlanRequest] = [.link(from: "claude:source", to: "codex", mode: "full_copy"),
                                      .copy(from: "claude:source", to: "codex", andLink: false)]
        var conflict = note("new_chat.relaunch", buttons: [("sync_relaunch_later", "Sync now, I relaunch later")])
        conflict.values["tool_id"] = .string("cursor")
        let plain = note("new_chat.relaunch", buttons: [("sync_relaunch_later", "Sync now, I relaunch later")])
        let wrongStep = Step(tool: "claude", action: "create", turns: [], reason: "", needs: [], notes: [plain])
        let conflictingStep = Step(tool: "codex", action: "create", turns: [], reason: "", needs: [], notes: [conflict])
        for original in requests {
            for payload in [try data(notes: [conflict]),
                            try data(notes: [note("nothing_unusual")], steps: [wrongStep]),
                            try data(notes: [note("nothing_unusual")], steps: [conflictingStep])] {
                let (model, engine) = await customModel(payload, request: original); try display(model)
                let chosen = try action("sync_relaunch_later", in: model)
                #expect(!model.canConfirm && !model.canChoose(chosen))
                await model.choose(chosen); await model.confirm()
                #expect(model.request == original && model.originalRequest == original && model.outcome == nil)
                let previews = await engine.previews(), writes = await engine.writes()
                let effects = await engine.effects()
                #expect(previews.count == 1 && writes.isEmpty)
                #expect(effects.copies == 0 && effects.deliveries.isEmpty)
            }
        }
    }
    @MainActor @Test func ordinaryWhenIdleNeverBecomesRelaunch() async throws {
        let (model, engine) = await model(Self.cases[6]); try display(model)
        await model.choose(try action("when_idle", in: model))
        #expect(model.request == Self.cases[6].request && model.alternative == .unavailable)
        #expect(await engine.previews().count == 1); #expect(await engine.writes().isEmpty)
    }
    @MainActor @Test func relaunchWhenIdleRepreviewsOnlyThatRelaunchAndRemainsUnavailable() async throws {
        let (model, engine) = await model(Self.cases[9]); try display(model)
        #expect(model.replying.map(\.name) == ["Imaginary orchard", "Orchard tests"])
        await model.choose(try action("when_idle", in: model))
        #expect(model.request == .relaunch(tool: "claude", whenIdle: true, thenSync: 3))
        #expect(model.originalRequest == Self.cases[9].request && !model.canConfirm)
        try display(model); await model.confirm()
        #expect(!model.canConfirm); #expect(await engine.writes().isEmpty)
    }
    @MainActor @Test func futureRelaunchFixturesCannotConfirmOrCloseAnyway() async throws {
        for test in [Self.cases[8], Self.cases[9]] {
            let (model, engine) = await model(test); try display(model)
            #expect(model.planNotes.contains { $0.id == "plan.unavailable" })
            #expect(!model.canConfirm)
            if test.name == "d6_replying" { await model.choose(try action("close_anyway", in: model)) }
            await model.confirm()
            #expect(model.request == test.request && model.originalRequest == test.request && model.outcome == nil)
            #expect(await engine.writes().isEmpty)
            #expect(await engine.previews().count == 1)
            #expect(await engine.effects().copies == 0)
            #expect(await engine.effects().deliveries.isEmpty)
        }
        // Even a mislabeled future provider cannot enable runtime relaunch at CP2.
        let payload = try data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_relaunch", buttons: [("confirm", "Relaunch")]))
        var object = try #require(JSONSerialization.jsonObject(with: payload) as? [String: Any]); object["replying"] = []
        let (model, engine) = await customModel(try JSONSerialization.data(withJSONObject: object), request: .relaunch(tool: "codex", whenIdle: false, thenSync: 3)); try display(model)
        await model.confirm(); #expect(!model.canConfirm); #expect(await engine.writes().isEmpty)
    }
    @MainActor @Test func doubleClickAndStaleConfirmationAreNotFalseSuccess() async throws {
        let payload = try data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_sync", buttons: [("confirm", "Sync")]))
        let (model, engine) = await customModel(payload, request: .sync(link: 3, to: "codex"), delay: true); try display(model)
        let chosen = try action("confirm", in: model)
        async let first: Void = model.choose(chosen)
        while !(await engine.startedConfirming()) { await Task.yield() }
        await model.choose(chosen); await model.confirm(); model.cancel()
        await model.preview(.sync(link: 3, to: "claude"))
        #expect(model.request == .sync(link: 3, to: "codex"))
        await first
        #expect(await engine.writes().count == 1); #expect(await engine.effects().deliveries == ["codex"])
        #expect(model.outcome == .applied)
        let (stale, staleEngine) = await customModel(payload, request: .sync(link: 3, to: "codex")); try display(stale)
        await staleEngine.invalidate(); await stale.confirm()
        #expect(stale.outcome == nil && !stale.canConfirm); #expect(await staleEngine.effects().deliveries.isEmpty)
        try display(stale); await stale.confirm()
        #expect(!stale.canConfirm); #expect(await staleEngine.writes().count == 1)
    }
    @MainActor @Test func ambiguousAndRefusedResultsNeedANewPreviewEvenAfterRedisplay() async throws {
        let payload = try data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_sync", buttons: [("confirm", "Sync")]))
        for behavior in [D6Engine.ConfirmationBehavior.ambiguous, .refuse] {
            let (model, engine) = await customModel(payload, request: .sync(link: 3, to: "codex"), behavior: behavior)
            try display(model); await model.confirm(); try display(model); await model.confirm()
            #expect(model.outcome == nil && !model.canConfirm); #expect(await engine.writes().count == 1)
            await model.preview(.sync(link: 3, to: "codex")); try display(model)
            #expect(model.canConfirm)
        }
    }
    @MainActor @Test func distinctCreationTokenNeedsItsOwnDisplayedRevision() async throws {
        var object = try #require(JSONSerialization.jsonObject(with: data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_brief_generation", buttons: [("confirm", "Generate")]), stage: "generate")) as? [String: Any])
        object["brief"] = ["writer": "offline", "tokens": 12, "pinned": []]
        let (model, engine) = await customModel(try JSONSerialization.data(withJSONObject: object), request: .brief(link: 3, to: "codex", writer: "offline"), behavior: .nextStage)
        try display(model); let old = try #require(model.displayReceipt); await model.confirm()
        #expect(model.plan?.stage == "create" && model.plan?.planID != old.planID && !model.canConfirm)
        model.didDisplay(old); #expect(!model.canConfirm)
        try display(model); #expect(model.canConfirm); #expect(await engine.writes().count == 1)
    }
    @MainActor @Test func semanticPlanBookRejectsWrongRequestAndReusedTokens() async throws {
        let payload = try data(notes: [note("nothing_unusual")], confirmation: note("plan.confirm_copy", buttons: [("confirm", "Copy")]))
        let engine = D6Engine(state: "custom", custom: payload)
        let shown = try await engine.copy(from: "claude:c1", to: "codex", andLink: false, mutation: .preview)
        do {
            _ = try await engine.copy(from: "claude:c1", to: "codex", andLink: true, mutation: .confirm(shown.planID))
            Issue.record("wrong request accepted")
        } catch { #expect(error is D6Engine.Failure) }
        #expect(await engine.effects().copies == 0)
        let shownAgain = try await engine.copy(from: "claude:c1", to: "codex", andLink: false, mutation: .preview)
        _ = try await engine.copy(from: "claude:c1", to: "codex", andLink: false, mutation: .confirm(shownAgain.planID))
        do {
            _ = try await engine.copy(from: "claude:c1", to: "codex", andLink: false, mutation: .confirm(shownAgain.planID))
            Issue.record("reused token accepted")
        } catch { #expect(error is D6Engine.Failure) }
        #expect(await engine.effects().copies == 1); #expect(await engine.effects().links == 0)
    }
    @MainActor @Test func ordinaryAndBriefControlsNeedCorrectStageAndCancelNeverWrites() async throws {
        let (ordinary, _) = await model(Self.cases[7]); try display(ordinary); #expect(ordinary.canConfirm)
        for stage in ["generate", "create"] {
            let id = "plan.confirm_brief_\(stage == "generate" ? "generation" : "creation")"
            var object = try #require(JSONSerialization.jsonObject(with: data(notes: [note("nothing_unusual")], confirmation: note(id, buttons: [("confirm", "Continue")]), stage: stage)) as? [String: Any])
            object["brief"] = ["writer": "offline", "tokens": 12, "pinned": []]
            let (brief, _) = await customModel(try JSONSerialization.data(withJSONObject: object), request: .brief(link: 3, to: "codex", writer: "offline")); try display(brief)
            #expect(brief.canConfirm)
        }
        let (cancelled, engine) = await model(Self.cases[2])
        await cancelled.choose(try action("cancel", in: cancelled))
        #expect(cancelled.outcome == .cancelled); #expect(await engine.writes().isEmpty)
    }
    @MainActor @Test func everyFixtureAndUnavailableSelectionRendersInBothThemes() async throws {
        let directory = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var models: [(String, PlanReviewViewModel)] = []
        for test in Self.cases { models.append((test.name, await model(test).0)) }
        let (unavailable, _) = await model(Self.cases[0]); try display(unavailable)
        await unavailable.choose(try action("close_sync_reopen", in: unavailable)); models.append(("unavailable", unavailable))
        let (selection, _) = await model(Self.cases[1]); try display(selection)
        await selection.choose(try action("attach", in: selection)); models.append(("selection", selection))
        for (name, model) in models {
            for theme in Theme.allCases {
                let renderer = ImageRenderer(content: PlanReviewView(model: model).environment(\.batonTheme, theme).environment(\.batonSnapshotPresentation, true))
                let tiff = try #require(renderer.nsImage?.tiffRepresentation)
                let bitmap = try #require(NSBitmapImageRep(data: tiff))
                let png = try #require(bitmap.representation(using: .png, properties: [:])); #expect(!png.isEmpty)
                try png.write(to: directory.appendingPathComponent("D6-\(name)-\(theme.rawValue).png"))
            }
        }
    }
}
