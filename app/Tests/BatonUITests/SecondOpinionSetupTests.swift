import AppKit
import Foundation
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

private actor OpinionTestEngine: EngineTransport {
    let state: String
    var calls: [(String, [String])] = []
    init(_ state: String = "before") { self.state = state }
    func response<R: Decodable & Sendable>(command: String, arguments: [String], as type: R.Type) async throws -> R {
        calls.append((command, arguments))
        let route: String
        if command == "ask-add" {
            #expect(arguments.first == "add")
            route = arguments.contains("--confirm") ? "d10_applied" : "d10_review" }
        else if arguments.contains("--status") { route = "d10_answer" }
        else if arguments.contains("--cancel") { route = "d10_cancelled" }
        else if arguments.contains("--confirm") { route = "d10_pending" }
        else { route = "d10_" + state }
        return try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: route)
            .response(command: command, arguments: [], as: type)
    }
}

@Suite(.serialized) struct SecondOpinionSetupTests {
    @MainActor @Test func generationAnswerAndAdditionHaveIndependentExactDisplayGates() async throws {
        let engine = OpinionTestEngine()
        let model = SecondOpinionViewModel(engine: engine)
        await model.preview(from: "claude:sample-a", tool: "codex", question: "Review this")
        #expect(!model.canConfirm)
        let stale = model.displayReceipt
        await model.confirm()
        #expect(await engine.calls.count == 1)
        model.didDisplay(stale)
        #expect(model.canConfirm)
        #expect(model.notes.filter { $0.id == "ask.preview" }.count == 1)
        await model.confirm()
        #expect(model.response?.state == "pending" && model.answer == nil && !model.canConfirm)
        #expect(model.buttons.map(\.id) == ["cancel"])
        let calls = await engine.calls
        #expect(calls[0].1 == ["--chat", "claude:sample-a", "--tool", "codex", "--question", "Review this", "--dry-run", "--background"])
        #expect(calls[1].1.first == "--confirm")
        await model.poll()
        #expect(model.answer?.answerID != nil && !model.canReviewAddition)
        await model.reviewAddition()
        #expect(await engine.calls.count == 3)
        model.didDisplayAnswer(try #require(model.answerDisplayReceipt))
        await model.reviewAddition()
        let additionCalls = await engine.calls
        #expect(additionCalls.last?.1 == ["add", "--answer", model.answer?.answerID ?? "", "--dry-run"])
        #expect(model.response?.stage == "add" && !model.canConfirm)
        model.didDisplay(stale)
        #expect(!model.canConfirm)
        model.didDisplay(model.displayReceipt)
        #expect(!model.canConfirm)
        model.didDisplayAnswer(try #require(model.answerDisplayReceipt))
        #expect(model.canConfirm)
        await model.confirm()
        #expect(model.response?.plan?.applied == true && !model.canConfirm)
        let end = await engine.calls
        #expect(end.last?.0 == "ask-add" && end.last?.1.first == "add" && end.last?.1.dropFirst().first == "--confirm")
    }
    @MainActor @Test func newQuestionRejectsOldReceiptAndCancellationNeverAdds() async throws {
        let backend = OpinionTestEngine()
        let model = SecondOpinionViewModel(engine: backend)
        await model.preview(from: "claude:sample-a", tool: "codex", question: "First")
        let receipt = model.displayReceipt
        await model.askAgain(question: "Second")
        model.didDisplay(receipt)
        #expect(!model.canConfirm)
        model.didDisplay(model.displayReceipt); await model.confirm(); await model.cancelRun()
        #expect(model.response?.state == "cancelled" && model.answer == nil)
        await model.poll(); await model.reviewAddition(); await model.confirm()
        #expect(await backend.calls.count == 4)
    }
    @MainActor @Test func refusalStatesKeepEngineSentencesAndCannotConfirm() async throws {
        for state in ["limit", "command_missing", "signed_out"] {
            let model = SecondOpinionViewModel(engine: OpinionTestEngine(state))
            await model.preview(from: "claude:sample-a", tool: "codex", question: "Review")
            #expect(model.errorNote != nil && !model.canConfirm && model.answer == nil)
        }
    }
    @MainActor @Test func setupFindingsKeepTheirHumanFixAndTypedCapabilities() async throws {
        let expectations = ["codex_trust": "setup.trust_once", "opencode_damaged": "setup.runner_reinstall",
                            "cursor_signed_out": "setup.runner", "not_installed": "setup.not_installed", "unknown_format": "format.unknown_version"]
        for (state, expected) in expectations {
            let model = SetupViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d11_" + state))
            await model.load()
            #expect(model.tools.count == 4)
            #expect(model.tools.flatMap(\.findings).contains { $0.note.id == expected && !$0.ok })
            #expect(model.tools.first?.capabilities?.checkedVersions?.isEmpty == false)
            let button = NoteButton(id: "install_hooks", label: "", primary: true)
            #expect(!model.canInstall(tool: "codex", button: button))
            model.didDisplay(model.displayReceipt)
            #expect(!model.canInstall(tool: "codex", button: button))
        }
    }
    @MainActor @Test func everyNewGeneratedStateRendersInBothThemes() async throws {
        for state in ["before", "pending", "answer", "cancelled", "deadline", "limit", "command_missing", "signed_out"] {
            let model = SecondOpinionViewModel(engine: OpinionTestEngine(state))
            await model.preview(from: "claude:sample-a", tool: "codex", question: "Review this and point out problems")
            for theme in Theme.allCases { try render(SecondOpinionView(model: model), name: "D10-" + state, theme: theme) }
        }
        for state in ["review", "applied", "attached", "unavailable"] {
            let model = SecondOpinionViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), states: ["ask": "d10_answer", "ask-add": "d10_" + state]))
            await model.preview(from: "claude:sample-a", tool: "codex", question: "Review this and point out problems")
            model.didDisplayAnswer(try #require(model.answerDisplayReceipt)); await model.reviewAddition()
            for theme in Theme.allCases { try render(SecondOpinionView(model: model), name: "D10-add-" + state, theme: theme) }
        }
        for state in ["ready", "codex_trust", "opencode_damaged", "cursor_signed_out", "not_installed", "unknown_format", "missing_hooks", "empty", "error"] {
            let model = SetupViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d11_" + state))
            await model.load()
            for theme in Theme.allCases { try render(SetupView(model: model), name: "D11-setup-" + state, theme: theme) }
        }
    }
    @MainActor private func render<V: View>(_ view: V, name: String, theme: Theme) throws {
        let renderer = ImageRenderer(content: view.frame(width: 760).background(theme.background).batonTheme(theme).environment(\.batonSnapshotPresentation, true))
        renderer.scale = 1
        let image = try #require(renderer.nsImage)
        #expect(image.size.width == 760 && image.size.height > 60)
        let tiff = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: tiff))
        let data = try #require(bitmap.representation(using: .png, properties: [:]))
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        try data.write(to: output.appendingPathComponent(name + "-" + theme.rawValue + ".png"))
    }
}

private actor TamperedOpinionEngine: EngineTransport {
    let base = OpinionTestEngine()
    let tamper: String
    init(_ tamper: String) { self.tamper = tamper }
    func response<R: Decodable & Sendable>(command: String, arguments: [String], as type: R.Type) async throws -> R {
        let value = try await base.response(command: command, arguments: arguments, as: JSONValue.self)
        var object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as? [String: Any])
        if command == "ask-add" {
            switch tamper {
            case "answer": object["answer"] = "Changed answer"
            case "identity": object["answer_id"] = "different-answer"
            case "step": object["steps"] = []
            case "tool":
                var steps = object["steps"] as? [[String: Any]] ?? []
                steps[0]["tool"] = "cursor"; object["steps"] = steps
            default: break
            }
        }
        return try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
    }
}

extension SecondOpinionSetupTests {
    @MainActor @Test func changedAnswerIdentityAndUnexpectedAddRoutingCannotConfirm() async throws {
        for tamper in ["answer", "identity", "step", "tool"] {
            let model = SecondOpinionViewModel(engine: TamperedOpinionEngine(tamper))
            await model.preview(from: "claude:sample-a", tool: "codex", question: "Review")
            model.didDisplay(model.displayReceipt); await model.confirm(); await model.poll()
            model.didDisplayAnswer(try #require(model.answerDisplayReceipt)); await model.reviewAddition()
            model.didDisplay(model.displayReceipt); model.didDisplayAnswer(try #require(model.answerDisplayReceipt))
            #expect(!model.canConfirm)
        }
    }
}

private struct UnstructuredScreenFailure: EngineTransport {
    func response<R: Decodable & Sendable>(command: String, arguments: [String], as type: R.Type) async throws -> R {
        throw SettingsValueError.invalidValue
    }
}

extension SecondOpinionSetupTests {
    @MainActor @Test func emptyAndTransportFailureStatesUseGeneratedEngineSentences() async throws {
        let opinion = SecondOpinionViewModel(engine: UnstructuredScreenFailure())
        #expect(opinion.emptyNote?.id == "empty.select_chat.title")
        for theme in Theme.allCases { try render(SecondOpinionView(model: opinion), name: "D10-empty", theme: theme) }
        await opinion.preview(from: "claude:sample-a", tool: "codex", question: "Review")
        #expect(opinion.errorNote?.id == "error.unexpected" && !opinion.canConfirm)
        for theme in Theme.allCases { try render(SecondOpinionView(model: opinion), name: "D10-error", theme: theme) }
        let setup = SetupViewModel(engine: UnstructuredScreenFailure())
        #expect(setup.emptyNote?.id == "screen.list_empty")
        await setup.load()
        #expect(setup.errorNote?.id == "error.unexpected")
    }
}

extension SecondOpinionSetupTests {
    @MainActor @Test func turnQuestionAndEditingArePartOfTheCurrentReview() async throws {
        let turn = try #require((try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d4_s1").status(link: 3)).turns.first)
        let engine = OpinionTestEngine()
        let model = SecondOpinionViewModel(engine: engine)
        await model.preview(from: "claude:sample-a", turn: turn, tool: "codex", question: "Review this turn")
        #expect(model.turn == turn)
        let arguments = await engine.calls.first?.1
        #expect(arguments?.suffix(2) == ["--turn", String(turn.id)])
        for theme in Theme.allCases { try render(SecondOpinionView(model: model), name: "D10-before-turn", theme: theme) }
        model.didDisplay(model.displayReceipt)
        #expect(model.canConfirm)
        model.updateQuestion("Review the tests instead")
        #expect(model.response == nil && !model.canConfirm && model.question == "Review the tests instead")
        await model.confirm()
        #expect(await engine.calls.count == 1)
    }
}
