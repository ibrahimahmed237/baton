import Foundation
import Testing
@testable import BatonKit

struct FixtureDecodingTests {
    static let fixtures = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Fixtures", isDirectory: true)

    private func decoder<T: Codable & Equatable>(for type: T.Type) -> (Data) throws -> Void {
        { data in
            let value = try JSONDecoder().decode(type, from: data)
            let roundTrip = try JSONDecoder().decode(type, from: JSONEncoder().encode(value))
            #expect(value == roundTrip)
            var object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
            object["future_contract_field"] = ["nested": true]
            let extended = try JSONSerialization.data(withJSONObject: object)
            let expected = try JSONDecoder().decode(type, from: extended)
            #expect(value == expected)
        }
    }

    @Test
    func testEveryFixtureDecodesAndIgnoresUnknownFields() throws {
        let decoders: [String: (Data) throws -> Void] = [
            "ask": decoder(for: AskResult.self),
            "ask-add": decoder(for: AskAddResult.self),
            "brief": decoder(for: BriefResult.self),
            "brief-details": decoder(for: BriefDetails.self),
            "catch-up": decoder(for: CatchUpResult.self),
            "chat": decoder(for: Chat.self),
            "chats": decoder(for: ChatsResult.self),
            "continue": decoder(for: ContinueResult.self),
            "copy": decoder(for: CopyResult.self),
            "history": decoder(for: HistoryResult.self),
            "history-event": decoder(for: HistoryEvent.self),
            "keep": decoder(for: KeepResult.self),
            "link": decoder(for: LinkResult.self),
            "link-summary": decoder(for: LinkSummary.self),
            "links": decoder(for: LinksResult.self),
            "merge": decoder(for: MergeResult.self),
            "merge-show": decoder(for: MergeShowResult.self),
            "next-message": decoder(for: NextMessage.self),
            "note": decoder(for: Note.self),
            "note-button": decoder(for: NoteButton.self),
            "notify": decoder(for: NotifyResult.self),
            "open": decoder(for: OpenResult.self),
            "pause": decoder(for: PauseResult.self),
            "pin": decoder(for: PinResult.self),
            "plan": decoder(for: Plan.self),
            "relaunch": decoder(for: RelaunchResult.self),
            "relink": decoder(for: RelinkResult.self),
            "removed-turn": decoder(for: RemovedTurn.self),
            "rename": decoder(for: RenameResult.self),
            "restore": decoder(for: RestoreResult.self),
            "resume": decoder(for: ResumeResult.self),
            "same-file": decoder(for: SameFile.self),
            "send": decoder(for: SendResult.self),
            "settings": decoder(for: Settings.self),
            "settings-get": decoder(for: SettingsGetResult.self),
            "settings-set": decoder(for: SettingsSetResult.self),
            "setup": decoder(for: SetupResult.self),
            "setup-finding": decoder(for: SetupFinding.self),
            "setup-install": decoder(for: SetupInstallResult.self),
            "setup-tool": decoder(for: SetupTool.self),
            "side": decoder(for: Side.self),
            "side-condition": decoder(for: SideCondition.self),
            "since-you-left": decoder(for: SinceYouLeft.self),
            "status": decoder(for: StatusResult.self),
            "step": decoder(for: Step.self),
            "suggestion": decoder(for: Suggestion.self),
            "suggestions": decoder(for: SuggestionsResult.self),
            "sync": decoder(for: SyncResult.self),
            "turn": decoder(for: Turn.self),
            "turn-message": decoder(for: TurnMessage.self),
            "undo": decoder(for: UndoResult.self),
            "unlink": decoder(for: UnlinkResult.self),
            "unpin": decoder(for: UnpinResult.self),
            "usage": decoder(for: Usage.self),
            "usage-limit": decoder(for: UsageLimit.self)
        ]
        let files = try FileManager.default.contentsOfDirectory(
            at: Self.fixtures, includingPropertiesForKeys: nil
        ).filter { $0.pathExtension == "json" }
        #expect(!(files.isEmpty))
        var covered: Set<String> = []
        for file in files {
            let command = String(file.lastPathComponent.split(separator: ".")[0])
            let decode = try #require(decoders[command], "Unregistered fixture: \(file.lastPathComponent)")
            do { try decode(Data(contentsOf: file)) }
            catch { Issue.record("\(file.lastPathComponent): \(error)") }
            covered.insert(command)
        }
        #expect(covered == Set(decoders.keys) , "Every model and command needs a fixture")
    }

    @Test
    func testSnakeCaseEncodingAndOptionalButtonPrimary() throws {
        let data = try Data(contentsOf: Self.fixtures.appendingPathComponent("note.sample.json"))
        let note = try JSONDecoder().decode(Note.self, from: data)
        #expect(note.buttons[1].primary == nil)
        let encoded = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(note)) as? [String: Any])
        #expect(encoded["status_line"] as? String == "Sample ready")
        #expect(encoded["statusLine"] == nil)
    }
}
