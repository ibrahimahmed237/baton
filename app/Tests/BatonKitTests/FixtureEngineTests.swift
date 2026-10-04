import Foundation
import Testing
@testable import BatonKit

struct FixtureEngineTests {
    @Test
    func testEveryCommandThroughEngineClient() async throws {
        let engine: any EngineClient = FixtureEngine(directory: FixtureDecodingTests.fixtures)
        do {
            let actual = try await engine.setup()
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("setup.sample.json"))
            let expected = try JSONDecoder().decode(SetupResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.setupInstall(tool: "claude", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("setup-install.sample.json"))
            let expected = try JSONDecoder().decode(SetupInstallResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.chats(tool: "claude", folder: nil)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("chats.sample.json"))
            let expected = try JSONDecoder().decode(ChatsResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.suggestions()
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("suggestions.sample.json"))
            let expected = try JSONDecoder().decode(SuggestionsResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.links()
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("links.sample.json"))
            let expected = try JSONDecoder().decode(LinksResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.status(link: 3, messages: true)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("status.sample.json"))
            let expected = try JSONDecoder().decode(StatusResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.link(from: "claude:sample-a", to: "codex:sample-b", mode: "full_copy", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("link.sample.json"))
            let expected = try JSONDecoder().decode(LinkResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.copy(from: "claude:sample-a", to: "codex:sample-b", andLink: true, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("copy.sample.json"))
            let expected = try JSONDecoder().decode(CopyResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.relink(link: 3, to: "codex:sample-b", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("relink.sample.json"))
            let expected = try JSONDecoder().decode(RelinkResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.unlink(link: 3, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("unlink.sample.json"))
            let expected = try JSONDecoder().decode(UnlinkResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.pause(link: 3, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("pause.sample.json"))
            let expected = try JSONDecoder().decode(PauseResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.resume(link: 3, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("resume.sample.json"))
            let expected = try JSONDecoder().decode(ResumeResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.sync(link: 3, to: "codex:sample-b", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("sync.sample.json"))
            let expected = try JSONDecoder().decode(SyncResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.continueIn(link: 3, inTool: "codex", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("continue.sample.json"))
            let expected = try JSONDecoder().decode(ContinueResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.mergeShow(link: 3)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("merge-show.sample.json"))
            let expected = try JSONDecoder().decode(MergeShowResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.merge(link: 3, choice: .order([41]), mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("merge.sample.json"))
            let expected = try JSONDecoder().decode(MergeResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.history(link: 3)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("history.sample.json"))
            let expected = try JSONDecoder().decode(HistoryResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.undo(link: 3, event: 1, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("undo.sample.json"))
            let expected = try JSONDecoder().decode(UndoResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.restore(event: 1, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("restore.sample.json"))
            let expected = try JSONDecoder().decode(RestoreResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.keep(turn: 41, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("keep.sample.json"))
            let expected = try JSONDecoder().decode(KeepResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.send(turn: 41, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("send.sample.json"))
            let expected = try JSONDecoder().decode(SendResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.pin(turn: 41, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("pin.sample.json"))
            let expected = try JSONDecoder().decode(PinResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.unpin(turn: 41, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("unpin.sample.json"))
            let expected = try JSONDecoder().decode(UnpinResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.brief(link: 3, to: "codex:sample-b", writer: "offline", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("brief.sample.json"))
            let expected = try JSONDecoder().decode(BriefResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.ask(from: "claude:sample-a", turn: 41, tool: "claude", question: "Invent another fruit.")
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("ask.sample.json"))
            let expected = try JSONDecoder().decode(AskResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.askAdd(answer: "Amber apples.", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("ask-add.sample.json"))
            let expected = try JSONDecoder().decode(AskAddResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.rename(link: 3, name: "Imaginary orchard", tools: ["claude", "codex"], mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("rename.sample.json"))
            let expected = try JSONDecoder().decode(RenameResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.relaunch(tool: "claude", whenIdle: true, thenSync: 3, mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("relaunch.sample.json"))
            let expected = try JSONDecoder().decode(RelaunchResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.open(tool: "claude", chat: "sample-a")
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("open.sample.json"))
            let expected = try JSONDecoder().decode(OpenResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.settingsGet()
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("settings-get.sample.json"))
            let expected = try JSONDecoder().decode(SettingsGetResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.settingsSet(key: "glass", value: "62", mutation: .preview)
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("settings-set.sample.json"))
            let expected = try JSONDecoder().decode(SettingsSetResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.notify(tool: "claude", chat: "sample-a")
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("notify.sample.json"))
            let expected = try JSONDecoder().decode(NotifyResult.self, from: data)
            #expect(actual == expected)
        }
        do {
            let actual = try await engine.catchUp(tool: "claude", chat: "sample-a")
            let data = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("catch-up.sample.json"))
            let expected = try JSONDecoder().decode(CatchUpResult.self, from: data)
            #expect(actual == expected)
        }
    }

    @Test
    func testStateSelection() async throws {
        let engine = FixtureEngine(directory: FixtureDecodingTests.fixtures, states: ["links": "empty"])
        let links = try await engine.links()
        #expect(links.links.isEmpty)
        let chats = try await engine.chats(tool: "claude")
        #expect(chats.chats.count == 2)
        let empty = FixtureEngine(directory: FixtureDecodingTests.fixtures, state: "empty")
        let emptyLinks = try await empty.links()
        #expect(emptyLinks == links)
    }

    @Test
    func testMissingFixtureThrows() async {
        let engine = FixtureEngine(directory: FixtureDecodingTests.fixtures, state: "missing")
        do {
            _ = try await engine.links()
            Issue.record("Missing fixture must throw")
        } catch {
            #expect(error is CocoaError)
        }
    }

    @Test
    func testFixtureErrorPreservesNote() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let note = try JSONDecoder().decode(Note.self, from: Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("note.sample.json")))
        let failure = EngineCommandError(kind: "chat_changed", note: note)
        let data = try JSONEncoder().encode(["error": failure])
        try data.write(to: directory.appendingPathComponent("links.sample.json"))
        do {
            _ = try await FixtureEngine(directory: directory).links()
            Issue.record("Error envelope must throw")
        } catch let error as EngineCommandError {
            #expect(error == failure)
        }
    }
}
