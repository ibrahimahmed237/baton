import Foundation

/// The complete command interface used by app views and view models.
public protocol EngineClient: Sendable {
    /// Runs the setup command.
    func setup() async throws -> SetupResult
    /// Runs the setup-install command.
    func setupInstall(tool: String, mutation: MutationOptions) async throws -> SetupInstallResult
    /// Runs the chats command.
    func chats(tool: String, folder: String?) async throws -> ChatsResult
    /// Runs the suggestions command.
    func suggestions() async throws -> SuggestionsResult
    /// Runs the links command.
    func links() async throws -> LinksResult
    /// Runs the status command.
    func status(link: Int, messages: Bool) async throws -> StatusResult
    /// Runs the link command.
    func link(from: String, to: String, mode: String, mutation: MutationOptions) async throws -> LinkResult
    /// Runs the copy command.
    func copy(from: String, to: String, andLink: Bool, mutation: MutationOptions) async throws -> CopyResult
    /// Runs the relink command.
    func relink(link: Int, to: String, mutation: MutationOptions) async throws -> RelinkResult
    /// Replaces an existing side with a full-history copy (R9).
    func fullCopy(link: Int, replace: String, mutation: MutationOptions) async throws -> LinkResult
    /// Changes the partner while retaining the named side (R9).
    func relink(link: Int, to: String, keep: String, mutation: MutationOptions) async throws -> RelinkResult
    func relink(link: Int, to: String, keep: String, mode: String, mutation: MutationOptions) async throws -> RelinkResult
    /// Runs the unlink command.
    func unlink(link: Int, mutation: MutationOptions) async throws -> UnlinkResult
    /// Runs the pause command.
    func pause(link: Int, mutation: MutationOptions) async throws -> PauseResult
    /// Runs the resume command.
    func resume(link: Int, mutation: MutationOptions) async throws -> ResumeResult
    /// Runs the sync command.
    func sync(link: Int, to: String?, mutation: MutationOptions) async throws -> SyncResult
    /// Runs the continue command.
    func continueIn(link: Int, inTool: String, mutation: MutationOptions) async throws -> ContinueResult
    /// Runs the merge-show command.
    func mergeShow(link: Int) async throws -> MergeShowResult
    /// Runs the merge command.
    func merge(link: Int, choice: MergeChoice, mutation: MutationOptions) async throws -> MergeResult
    /// Runs the history command.
    func history(link: Int) async throws -> HistoryResult
    /// Runs the undo command.
    func undo(link: Int, event: Int, mutation: MutationOptions) async throws -> UndoResult
    /// Runs the restore command.
    func restore(event: Int, mutation: MutationOptions) async throws -> RestoreResult
    /// Runs the keep command.
    func keep(turn: Int, mutation: MutationOptions) async throws -> KeepResult
    /// Runs the send command.
    func send(turn: Int, mutation: MutationOptions) async throws -> SendResult
    /// Runs the pin command.
    func pin(turn: Int, mutation: MutationOptions) async throws -> PinResult
    /// Runs the unpin command.
    func unpin(turn: Int, mutation: MutationOptions) async throws -> UnpinResult
    /// Runs the brief command.
    func brief(link: Int, to: String, writer: String?, mutation: MutationOptions) async throws -> BriefResult
    /// Runs the ask command.
    func ask(from: String, turn: Int, tool: String, question: String) async throws -> AskResult
    /// Runs the ask-add command.
    func askAdd(answer: String, mutation: MutationOptions) async throws -> AskAddResult
    /// Runs the rename command.
    func rename(link: Int, name: String, tools: [String], mutation: MutationOptions) async throws -> RenameResult
    /// Runs the relaunch command.
    func relaunch(tool: String, whenIdle: Bool, thenSync: Int?, mutation: MutationOptions) async throws -> RelaunchResult
    /// Runs the open command.
    func open(tool: String, chat: String) async throws -> OpenResult
    /// Runs the settings-get command.
    func settingsGet() async throws -> SettingsGetResult
    /// Runs the settings-set command.
    func settingsSet(key: String, value: String, mutation: MutationOptions) async throws -> SettingsSetResult
    /// Runs the notify command.
    func notify(tool: String, chat: String) async throws -> NotifyResult
    /// Runs the catch-up command.
    func catchUp(tool: String, chat: String) async throws -> CatchUpResult
}

/// Shared typed command dispatch for process and fixture transports.
public protocol EngineTransport: EngineClient {
    /// Obtains a command response and decodes its contract result.
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result
}

public extension EngineTransport {
    func relink(link: Int, to: String, keep: String, mode: String, mutation: MutationOptions = .preview) async throws -> RelinkResult {
        try await response(command: "relink", arguments: ["--link", String(link), "--to", to, "--keep", keep, "--mode", mode] + mutation.arguments, as: RelinkResult.self)
    }

    func fullCopy(link: Int, replace: String, mutation: MutationOptions = .preview) async throws -> LinkResult {
        try await response(command: "link", arguments: ["--link", String(link), "--replace", replace, "--mode", "full_copy"] + mutation.arguments, as: LinkResult.self)
    }
    func relink(link: Int, to: String, keep: String, mutation: MutationOptions = .preview) async throws -> RelinkResult {
        try await response(command: "relink", arguments: ["--link", String(link), "--to", to, "--keep", keep] + mutation.arguments, as: RelinkResult.self)
    }

    /// Runs the setup command.
    func setup() async throws -> SetupResult {
        try await response(command: "setup", arguments: [], as: SetupResult.self)
    }

    /// Runs the setup-install command.
    func setupInstall(tool: String, mutation: MutationOptions = .preview) async throws -> SetupInstallResult {
        try await response(command: "setup-install", arguments: ["install", "--tool", tool] + mutation.arguments, as: SetupInstallResult.self)
    }

    /// Runs the chats command.
    func chats(tool: String, folder: String? = nil) async throws -> ChatsResult {
        try await response(command: "chats", arguments: ["--tool", tool] + option("--folder", folder), as: ChatsResult.self)
    }

    /// Runs the suggestions command.
    func suggestions() async throws -> SuggestionsResult {
        try await response(command: "suggestions", arguments: [], as: SuggestionsResult.self)
    }

    /// Runs the links command.
    func links() async throws -> LinksResult {
        try await response(command: "links", arguments: [], as: LinksResult.self)
    }

    /// Runs the status command.
    func status(link: Int, messages: Bool = false) async throws -> StatusResult {
        try await response(command: "status", arguments: ["--link", String(link)] + flag("--messages", messages), as: StatusResult.self)
    }

    /// Runs the link command.
    func link(from: String, to: String, mode: String, mutation: MutationOptions = .preview) async throws -> LinkResult {
        try await response(command: "link", arguments: ["--from", from, "--to", to, "--mode", mode] + mutation.arguments, as: LinkResult.self)
    }

    /// Runs the copy command.
    func copy(from: String, to: String, andLink: Bool = false, mutation: MutationOptions = .preview) async throws -> CopyResult {
        try await response(command: "copy", arguments: ["--from", from, "--to", to] + flag("--and-link", andLink) + mutation.arguments, as: CopyResult.self)
    }

    /// Runs the relink command.
    func relink(link: Int, to: String, mutation: MutationOptions = .preview) async throws -> RelinkResult {
        try await response(command: "relink", arguments: ["--link", String(link), "--to", to] + mutation.arguments, as: RelinkResult.self)
    }

    /// Runs the unlink command.
    func unlink(link: Int, mutation: MutationOptions = .preview) async throws -> UnlinkResult {
        try await response(command: "unlink", arguments: ["--link", String(link)] + mutation.arguments, as: UnlinkResult.self)
    }

    /// Runs the pause command.
    func pause(link: Int, mutation: MutationOptions = .preview) async throws -> PauseResult {
        try await response(command: "pause", arguments: ["--link", String(link)], as: PauseResult.self)
    }

    /// Runs the resume command.
    func resume(link: Int, mutation: MutationOptions = .preview) async throws -> ResumeResult {
        try await response(command: "resume", arguments: ["--link", String(link)], as: ResumeResult.self)
    }

    /// Runs the sync command.
    func sync(link: Int, to: String? = nil, mutation: MutationOptions = .preview) async throws -> SyncResult {
        try await response(command: "sync", arguments: ["--link", String(link)] + option("--to", to) + mutation.arguments, as: SyncResult.self)
    }

    /// Runs the continue command.
    func continueIn(link: Int, inTool: String, mutation: MutationOptions = .preview) async throws -> ContinueResult {
        try await response(command: "continue", arguments: ["--link", String(link)] + ["--in", inTool] + mutation.arguments, as: ContinueResult.self)
    }

    /// Runs the merge-show command.
    func mergeShow(link: Int) async throws -> MergeShowResult {
        try await response(command: "merge-show", arguments: ["--link", String(link), "--show"], as: MergeShowResult.self)
    }

    /// Runs the merge command.
    func merge(link: Int, choice: MergeChoice, mutation: MutationOptions = .preview) async throws -> MergeResult {
        try await response(command: "merge", arguments: ["--link", String(link)] + choice.arguments + mutation.arguments, as: MergeResult.self)
    }

    /// Runs the history command.
    func history(link: Int) async throws -> HistoryResult {
        try await response(command: "history", arguments: ["--link", String(link)], as: HistoryResult.self)
    }

    /// Runs the undo command.
    func undo(link: Int, event: Int, mutation: MutationOptions = .preview) async throws -> UndoResult {
        try await response(command: "undo", arguments: ["--link", String(link), "--to", String(event)] + mutation.arguments, as: UndoResult.self)
    }

    /// Runs the restore command.
    func restore(event: Int, mutation: MutationOptions = .preview) async throws -> RestoreResult {
        try await response(command: "restore", arguments: ["--event", String(event)] + mutation.arguments, as: RestoreResult.self)
    }

    /// Runs the keep command.
    func keep(turn: Int, mutation: MutationOptions = .preview) async throws -> KeepResult {
        try await response(command: "keep", arguments: ["--turn", String(turn)] + mutation.arguments, as: KeepResult.self)
    }

    /// Runs the send command.
    func send(turn: Int, mutation: MutationOptions = .preview) async throws -> SendResult {
        try await response(command: "send", arguments: ["--turn", String(turn)] + mutation.arguments, as: SendResult.self)
    }

    /// Runs the pin command.
    func pin(turn: Int, mutation: MutationOptions = .preview) async throws -> PinResult {
        try await response(command: "pin", arguments: ["--turn", String(turn)] + mutation.arguments, as: PinResult.self)
    }

    /// Runs the unpin command.
    func unpin(turn: Int, mutation: MutationOptions = .preview) async throws -> UnpinResult {
        try await response(command: "unpin", arguments: ["--turn", String(turn)] + mutation.arguments, as: UnpinResult.self)
    }

    /// Runs the brief command.
    func brief(link: Int, to: String, writer: String? = nil, mutation: MutationOptions = .preview) async throws -> BriefResult {
        try await response(command: "brief", arguments: ["--link", String(link), "--to", to] + option("--writer", writer) + mutation.arguments, as: BriefResult.self)
    }

    /// Runs the ask command.
    func ask(from: String, turn: Int, tool: String, question: String) async throws -> AskResult {
        try await response(command: "ask", arguments: ["--from", from, "--turn", String(turn), "--tool", tool, "--question", question], as: AskResult.self)
    }

    /// Runs the ask-add command.
    func askAdd(answer: String, mutation: MutationOptions = .preview) async throws -> AskAddResult {
        try await response(command: "ask-add", arguments: ["add", "--answer", answer] + mutation.arguments, as: AskAddResult.self)
    }

    /// Runs the rename command.
    func rename(link: Int, name: String, tools: [String] = [], mutation: MutationOptions = .preview) async throws -> RenameResult {
        try await response(command: "rename", arguments: ["--link", String(link), "--name", name] + (tools.isEmpty ? [] : ["--tools", tools.joined(separator: ",")]) + mutation.arguments, as: RenameResult.self)
    }

    /// Runs the relaunch command.
    func relaunch(tool: String, whenIdle: Bool = false, thenSync: Int? = nil, mutation: MutationOptions = .preview) async throws -> RelaunchResult {
        try await response(command: "relaunch", arguments: ["--tool", tool] + flag("--when-idle", whenIdle) + option("--then-sync", thenSync.map(String.init)) + mutation.arguments, as: RelaunchResult.self)
    }

    /// Runs the open command.
    func open(tool: String, chat: String) async throws -> OpenResult {
        try await response(command: "open", arguments: ["--tool", tool, "--chat", chat], as: OpenResult.self)
    }

    /// Runs the settings-get command.
    func settingsGet() async throws -> SettingsGetResult {
        try await response(command: "settings-get", arguments: ["get"], as: SettingsGetResult.self)
    }

    /// Sets configuration immediately; the retained mutation argument does not add plan flags.
    func settingsSet(key: String, value: String, mutation: MutationOptions = .preview) async throws -> SettingsSetResult {
        try await response(command: "settings-set", arguments: ["set", key, value], as: SettingsSetResult.self)
    }

    /// Runs the notify command.
    func notify(tool: String, chat: String) async throws -> NotifyResult {
        try await response(command: "notify", arguments: ["--tool", tool, "--chat", chat], as: NotifyResult.self)
    }

    /// Runs the catch-up command.
    func catchUp(tool: String, chat: String) async throws -> CatchUpResult {
        try await response(command: "catch-up", arguments: ["--tool", tool, "--chat", chat], as: CatchUpResult.self)
    }

}

private func option(_ name: String, _ value: String?) -> [String] { value.map { [name, $0] } ?? [] }
private func flag(_ name: String, _ enabled: Bool) -> [String] { enabled ? [name] : [] }
