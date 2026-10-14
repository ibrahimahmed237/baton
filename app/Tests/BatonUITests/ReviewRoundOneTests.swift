import Foundation
import SwiftUI
import AppKit
import Testing
import BatonKit
@testable import BatonUI

private actor ReviewEngine: EngineTransport {
    let scenario: String
    let omitting: String?
    var calls: [(String, [String])] = []
    init(_ scenario: String, omitting: String? = nil) { self.scenario = scenario; self.omitting = omitting }
    func response<R: Decodable & Sendable>(command: String, arguments: [String], as type: R.Type) async throws -> R {
        calls.append((command, arguments))
        let directory = ComponentTests.root.appendingPathComponent("Fixtures")
        if ["opinion-failure", "opinion-actions"].contains(scenario), command == "ask-add" { throw SettingsValueError.invalidValue }
        var state: String
        switch scenario {
        case "settings": state = command == "settings-set" ? "d11_saved" : "d11_loaded"
        case "setup": state = "d11_ready"
        case "opinion-failure", "opinion-actions": state = "d10_answer"
        default: state = scenario
        }
        if scenario.hasPrefix("dfix_"), command == "relaunch", arguments.contains("--confirm") {
            let target = scenario.split(separator: "_")[1]
            let originalCommand = calls.first { ["link", "sync"].contains($0.0) }?.0 ?? "link"
            state = "dfix_" + target + "_" + originalCommand + "_applied"
        }
        if scenario.hasPrefix("dfix_"), ["setup", "links", "chats"].contains(command) { state = "sample" }
        if scenario.hasPrefix("dfix_"), command == "status" { state = "d4_s1" }
        let value = try await FixtureEngine(directory: directory, state: state).response(command: command, arguments: [], as: JSONValue.self)
        var object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as? [String: Any])
        if scenario == "settings", command == "settings-set" {
            let original = try await FixtureEngine(directory: directory, state: "d11_loaded").settingsGet()
            var label = try #require(original.notes?.first { $0.id == "settings.theme" })
            label.text = "Replacement label"
            var defaultLabel = try #require(original.notes?.first { $0.id == "settings.default" && $0.values["key"] == .string("theme") })
            defaultLabel.text = "Replacement default"
            object["notes"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode([label, defaultLabel]))
        }
        if scenario == "opinion-actions" {
            let notes = [Note(id: "ask.actions", tone: "info", values: [:], text: "Fixture answer actions", buttons: [
                NoteButton(id: "copy", label: "Copy"), NoteButton(id: "ask_again", label: "Ask again"),
                NoteButton(id: "discard", label: "Discard"), NoteButton(id: "retry", label: "Retry")]),
                Note(id: "ask.question", tone: "info", values: [:], text: "Question", buttons: [])]
            var rendered = notes
            if let omitting { rendered[0].buttons.removeAll { $0.id == omitting } }
            object["notes"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(rendered))
        }
        if scenario == "setup" {
            var tools = try #require(object["tools"] as? [[String: Any]])
            var findings = try #require(tools[0]["findings"] as? [[String: Any]])
            var note = Note(id: "setup.hooks", tone: "warning", values: [:], text: "Fixture hook remedy", buttons: [NoteButton(id: "install_hooks", label: "Fixture install", primary: true)])
            if omitting == "install_hooks" { note.buttons = [] }
            findings[1] = ["id": "hooks", "ok": false, "note": try JSONSerialization.jsonObject(with: JSONEncoder().encode(note))]
            if omitting == "runner-row" { findings.removeAll { $0["id"] as? String == "runner" } }
            tools[0]["findings"] = findings; object["tools"] = tools
            let labels = [("setup.category.hooks", "Hooks"), ("setup.category.runner", "Background"),
                          ("setup.category.format", "Format"), ("setup.check_again", "Check again")].map {
                Note(id: $0.0, tone: "info", values: [:], text: $0.1, buttons: [])
            }
            object["notes"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(labels.filter { $0.id != omitting }))
        }
        return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
}

@Suite(.serialized) struct ReviewRoundOneTests {
    @MainActor @Test func replacementLabelsAndDefaultsAreTheOnlyRenderedReceiptWording() async throws {
        let appearance = ThemePreference(systemTheme: .light)
        let model = SettingsViewModel(engine: ReviewEngine("settings"), appearance: appearance)
        let view = SettingsView(model: model, appearance: appearance)
        await model.load()
        let old = model.displayReceipt
        let delayedAppearance = view.appearanceCallback(for: old)
        delayedAppearance()
        await model.set("theme", value: "graphite")
        #expect(model.note("settings.theme")?.text == "Replacement label")
        #expect(model.defaultNote("theme")?.text == "Replacement default")
        #expect(model.notes.filter { $0.id == "settings.theme" }.count == 1)
        #expect(model.notes.filter { $0.id == "settings.default" && $0.values["key"] == .string("theme") }.count == 1)
        #expect(model.displayReceipt.notes.contains { $0.text == "Replacement label" })
        #expect(!model.displayReceipt.notes.contains { $0.id == "settings.theme" && $0.text != "Replacement label" })
        delayedAppearance()
        #expect(!model.canSet)
        view.appearanceCallback(for: model.displayReceipt)()
        #expect(model.canSet)
    }
    @MainActor @Test func automaticAdditionFailureAttemptsOnceAndExplicitRetryRetainsAnswer() async throws {
        let engine = ReviewEngine("opinion-failure")
        let model = SecondOpinionViewModel(engine: engine)
        await model.preview(from: "claude:sample-a", tool: "codex", question: "Review")
        let answer = try #require(model.answer)
        model.didDisplayAnswer(try #require(model.answerDisplayReceipt))
        await model.reviewAdditionAutomatically()
        #expect(model.errorNote != nil && model.answer == answer)
        for _ in 0..<3 {
            model.didDisplayAnswer(try #require(model.answerDisplayReceipt))
            await model.reviewAdditionAutomatically()
        }
        #expect(await engine.calls.filter { $0.0 == "ask-add" }.count == 1)
        model.updateQuestion("Another question")
        #expect(model.answer == answer)
        await model.reviewAddition()
        #expect(await engine.calls.filter { $0.0 == "ask-add" }.count == 2)
        model.discard()
        #expect(model.answer == nil && model.response == nil)
    }
    @MainActor @Test func offeredInstallUsesImmediateExactArgumentsAndRefreshRejectsStaleReceipt() async throws {
        let engine = ReviewEngine("setup")
        let model = SetupViewModel(engine: engine)
        await model.load()
        let target = try #require(model.tools.first)
        #expect(model.findings(for: target).map(\.id) == ["format", "hooks", "runner"])
        let button = try #require(target.findings.first { $0.id == "hooks" }?.note.buttons.first)
        await model.install(tool: target.tool, button: button)
        #expect(await engine.calls.count == 1)
        let old = model.displayReceipt
        model.didDisplay(old)
        #expect(model.canInstall(tool: target.tool, button: button))
        await model.install(tool: target.tool, button: button)
        #expect(await engine.calls.last?.0 == "setup-install")
        #expect(await engine.calls.last?.1 == ["install", "--tool", target.tool])
        model.didDisplay(old)
        #expect(!model.canInstall(tool: target.tool, button: button))
        await model.load()
        #expect(await engine.calls.count == 3)
        #expect(model.findings(for: try #require(model.tools.first)).count == 3)
        model.didDisplay(old)
        #expect(!model.canInstall(tool: target.tool, button: button))
        model.didDisplay(model.displayReceipt)
        #expect(model.canInstall(tool: target.tool, button: button))
    }
    @MainActor @Test func offeredAnswerControlsCopyAskAgainRetryAndDiscard() async throws {
        let engine = ReviewEngine("opinion-actions")
        let model = SecondOpinionViewModel(engine: engine)
        await model.preview(from: "claude:sample-a", tool: "codex", question: "Review")
        #expect(model.label("ask.question")?.text == "Question")
        #expect(model.answerActions.map(\.id) == ["copy", "ask_again", "discard", "retry"])
        var copied = ""
        await model.chooseAnswerAction(try #require(model.answerActions.first { $0.id == "copy" })) { copied = $0 }
        #expect(copied == model.answer?.answer && !copied.isEmpty)
        model.updateQuestion("Changed question")
        #expect(model.answer != nil)
        await model.chooseAnswerAction(try #require(model.answerActions.first { $0.id == "ask_again" }))
        #expect(await engine.calls.last?.1.contains("Changed question") == true)
        model.didDisplayAnswer(try #require(model.answerDisplayReceipt))
        await model.chooseAnswerAction(try #require(model.answerActions.first { $0.id == "retry" }))
        #expect(await engine.calls.last?.0 == "ask-add")
        await model.chooseAnswerAction(try #require(model.answerActions.first { $0.id == "discard" }))
        #expect(model.answer == nil)
    }
    @MainActor @Test func rendersChangeWhenEachRequiredControlCategoryOrHealthyRowIsRemoved() async throws {
        let opinion = SecondOpinionViewModel(engine: ReviewEngine("opinion-actions"))
        await opinion.preview(from: "claude:sample-a", tool: "codex", question: "Review")
        let fullAnswer = try renderedPixels(SecondOpinionView(model: opinion))
        for action in ["copy", "ask_again", "discard", "retry"] {
            let missing = SecondOpinionViewModel(engine: ReviewEngine("opinion-actions", omitting: action))
            await missing.preview(from: "claude:sample-a", tool: "codex", question: "Review")
            #expect(try renderedPixels(SecondOpinionView(model: missing)) != fullAnswer, "Missing control: \(action)")
        }
        let setup = SetupViewModel(engine: ReviewEngine("setup"))
        await setup.load()
        let fullSetup = try renderedPixels(SetupView(model: setup))
        for item in ["setup.category.hooks", "setup.category.runner", "setup.category.format", "setup.check_again", "runner-row", "install_hooks"] {
            let missing = SetupViewModel(engine: ReviewEngine("setup", omitting: item))
            await missing.load()
            #expect(try renderedPixels(SetupView(model: missing)) != fullSetup, "Missing setup presentation: \(item)")
        }
    }
    @MainActor private func renderedPixels<V: View>(_ view: V) throws -> Data {
        let renderer = ImageRenderer(content: view.frame(width: 760).background(Theme.light.background)
            .batonTheme(.light).environment(\.batonSnapshotPresentation, true))
        renderer.scale = 1
        let native = try #require(renderer.nsImage)
        let data = try #require(native.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: data))
        return try #require(bitmap.representation(using: .png, properties: [:]))
    }
    @MainActor @Test func productionCreationAndSyncOffersUseTheirBoundRelaunchIDsAfterExactDisplay() async throws {
        for tool in ["claude", "cursor", "codex"] {
            for command in ["link", "sync"] {
                let engine = ReviewEngine("dfix_" + tool + "_idle")
                let model = PlanReviewViewModel(engine: engine)
                let request: PlanRequest = command == "link" ? .link(from: "source:id", to: tool, mode: "full_copy") : .sync(link: 3, to: tool)
                await model.preview(request)
                let receipt = try #require(model.displayReceipt)
                #expect(model.plan?.steps.map(\.action) == ["close", "wait_until_still", command == "link" ? "create" : "add", "reopen"])
                let action = try #require(model.actions.first { $0.button.id == "close_sync_reopen" })
                #expect(!model.canChoose(action))
                await model.choose(action)
                #expect(await engine.calls.count == 1)
                await model.preview(request)
                model.didDisplay(receipt)
                let current = try #require(model.actions.first { $0.button.id == "close_sync_reopen" })
                #expect(!model.canChoose(current))
                model.didDisplay(try #require(model.displayReceipt))
                #expect(model.canChoose(current))
                let note = try #require(model.planNotes.first { $0.buttons.contains(current.button) && $0.values["relaunch_plan_id"] != nil })
                guard case .string(let id) = note.values["relaunch_plan_id"] else { Issue.record("Missing bound ID"); return }
                await model.choose(current)
                #expect(await engine.calls.last?.0 == "relaunch")
                #expect(await engine.calls.last?.1 == ["--confirm", id])
                #expect(model.outcome == .applied && model.plan?.applied == true)
            }
        }
    }
    @MainActor @Test func statusAndLinkScreensExecuteTheOfferedRelaunchThroughTheirDisplayGates() async throws {
        let backend = ReviewEngine("dfix_claude_idle")
        let status = SyncStatusViewModel(engine: backend)
        await status.load(link: 3)
        await status.sideAction(NoteButton(id: "add_now", label: "Fixture add"), tool: "claude")
        let button = try #require(status.confirmationButtons.first { $0.id == "close_sync_reopen" })
        #expect(!status.canConfirmPlan)
        let before = await backend.calls.count
        await status.confirmPlan(button)
        #expect(await backend.calls.count == before)
        status.didDisplay(try #require(status.displayReceipt))
        #expect(status.canConfirmPlan)
        await status.confirmPlan(button)
        #expect(await backend.calls.contains { $0.0 == "relaunch" && $0.1.first == "--confirm" })
        #expect(status.plan == nil)

        let linkBackend = ReviewEngine("dfix_cursor_idle")
        let dialog = LinkDialogViewModel(engine: linkBackend)
        let source = try #require((try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures")).chats(tool: "claude", folder: nil)).chats.first)
        await dialog.load(source: source)
        await dialog.selectTarget("cursor")
        let offer = try #require(dialog.boundButtons.first { $0.id == "close_sync_reopen" })
        #expect(!dialog.canConfirm)
        dialog.didDisplay(try #require(dialog.displayReceipt))
        await dialog.chooseBound(offer)
        #expect(dialog.finished && dialog.plan?.applied == true)
        #expect(await linkBackend.calls.last?.0 == "relaunch")
    }
    @MainActor @Test func replyingAndUnknownProductionPreviewsCannotCloseOrWrite() async throws {
        for tool in ["claude", "cursor", "codex"] {
            for command in ["link", "sync"] {
                for state in ["replying", "unknown"] {
                    let engine = ReviewEngine("dfix_" + tool + "_" + state)
                    let model = PlanReviewViewModel(engine: engine)
                    await model.preview(command == "link" ? .link(from: "source:id", to: tool, mode: "full_copy") : .sync(link: 3, to: tool))
                    model.didDisplay(try #require(model.displayReceipt))
                    #expect(model.plan?.decisionNeeded == true)
                    #expect(model.planNotes.contains { $0.id == (state == "unknown" ? "relaunch.replying_unknown" : "relaunch.replying_safe") })
                    #expect(!model.canConfirm)
                    for action in model.actions where action.button.id != "cancel" { #expect(!model.canChoose(action)) }
                    await model.confirm()
                    #expect(await engine.calls.count == 1)
                }
            }
        }
    }
}
