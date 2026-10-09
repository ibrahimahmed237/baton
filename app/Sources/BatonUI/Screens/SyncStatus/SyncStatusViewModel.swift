import Foundation
import Combine
import BatonKit

/// Conversation filters affect presentation only, never delivery.
public enum ConversationFilter: String, CaseIterable, Sendable { case all, waiting, attached, kept, pinned }

/// Engine-backed status, previewed actions and conversation presentation.
@MainActor
public final class SyncStatusViewModel: ObservableObject {
    @Published public private(set) var status: StatusResult?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var filter: ConversationFilter = .all
    @Published public private(set) var focusedTurn: Int?
    @Published public private(set) var focusRequest = 0
    @Published public private(set) var expandedReplies: Set<Int> = []
    @Published public private(set) var expandedTools: Set<Int> = []
    @Published public private(set) var unfolded = false
    @Published public private(set) var history: [HistoryEvent]?
    @Published public private(set) var plan: Plan?
    @Published public private(set) var isConfirming = false
    @Published public private(set) var removedLinkID: Int?
    @Published public private(set) var loading = false
    @Published public private(set) var loadFailed = false
    private let engine: any EngineClient
    private var request = 0
    private var actionRequest = 0
    private var pending: PendingAction?
    private enum PendingAction { case unlink, copy(String, String), sync(String), relaunch(String) }

    public init(engine: any EngineClient) { self.engine = engine }
    public var tools: [String] { status?.sides.keys.sorted() ?? [] }
    public func toolLabel(_ tool: String) -> String { status?.sides[tool]?.displayLabel ?? tool }
    public func displayedNotes(for side: Side) -> [Note] {
        side.notes.filter { $0.id != "status.since_you_left" || side.agentHas < side.total || side.waiting > 0 }
    }
    public func sideButtons(_ side: Side) -> [NoteButton] {
        var seen: Set<String> = []
        return displayedNotes(for: side).flatMap(\.buttons).filter { seen.insert($0.id).inserted }
    }
    public var turns: [Turn] { status?.turns ?? [] }
    public var filteredTurns: [Turn] {
        turns.filter { turn in
            switch filter {
            case .all: return true
            case .pinned: return turn.pinned
            case .kept: return turn.states.values.contains("kept_back")
            case .waiting, .attached: return turn.states.values.contains(filter.rawValue)
            }
        }
    }
    public var earlierTurns: [Turn] {
        guard tools.count == 2 else { return [] }
        return Array(turns.prefix { turn in tools.allSatisfy { ["written_here", "shown"].contains(turn.states[$0] ?? "") } })
    }
    public var displayedTurns: [Turn] {
        guard filter == .all, !unfolded else { return filteredTurns }
        let hidden = Set(earlierTurns.dropLast(earlierTurns.count == turns.count ? 1 : 0).map(\.id))
        return filteredTurns.filter { !hidden.contains($0.id) }
    }
    public var emptyConversationContent: EmptyStateContent? {
        guard status != nil, !loading, !loadFailed, displayedTurns.isEmpty else { return nil }
        return EmptyStateContent.find(turns.isEmpty ? "empty.conversation" : "empty.filtered",
                                      in: status?.notes ?? [])
    }
    public var canShowAllTurns: Bool { emptyConversationContent != nil && !turns.isEmpty && filter != .all }
    public var foldedCount: Int { filteredTurns.count - displayedTurns.count }
    public func note(_ id: String, turn: Int? = nil) -> Note? {
        status?.notes.first { note in note.id == id && (turn == nil || note.values["turn_id"] == .number(Double(turn!))) }
    }
    /// Groups only tools whose engine-reported receipt ends at this exact turn.
    public func reachedTools(at turn: Int) -> [String] {
        tools.filter { status?.sides[$0]?.syncedUpTo?.id == turn }
    }
    /// Keeps filtered or folded receipts explicit about their original turn.
    public var hiddenReachedTools: [String] {
        guard !displayedTurns.isEmpty else { return [] }
        let visible = Set(displayedTurns.map(\.id))
        return tools.filter { tool in
            guard let turn = status?.sides[tool]?.syncedUpTo?.id else { return false }
            return !visible.contains(turn)
        }
    }
    /// Uses engine wording for a shared receipt, with a legacy per-tool fallback.
    public func receiptNotes(for tools: [String], hidden: Bool = false) -> [Note] {
        guard !tools.isEmpty else { return [] }
        if !hidden, tools.count == self.tools.count, tools.count == 2,
           let shared = note("screen.received_both") { return [shared] }
        return tools.compactMap { tool in
            let id = hidden ? "screen.received_hidden_tool" : "screen.received_one"
            return status?.notes.first { $0.id == id && $0.values["tool"] == .string(toolLabel(tool)) }
                ?? status?.notes.first { $0.id == "status.reached" && $0.values["tool"] == .string(toolLabel(tool)) }
        }
    }
    public func stateLabel(_ state: String) -> String? { note("turn." + state)?.text }
    public func setFilter(_ value: ConversationFilter) { filter = value }
    public func jump(to turn: Int) {
        guard turns.contains(where: { $0.id == turn }) else { return }
        filter = .all; unfolded = true; focusedTurn = turn; focusRequest += 1
    }
    public func unfold() { unfolded = true }
    public func toggleReply(_ turn: Int) { if !expandedReplies.insert(turn).inserted { expandedReplies.remove(turn) } }
    public func toggleTools(_ turn: Int) { if !expandedTools.insert(turn).inserted { expandedTools.remove(turn) } }
    public func messages(for turn: Turn) -> [TurnMessage] {
        (turn.messages ?? []).filter { ["prompt", "reply"].contains($0.kind) }
    }
    public func messageNeedsExpansion(_ message: TurnMessage) -> Bool {
        message.text.count > 240 || message.text.split(separator: "\n", omittingEmptySubsequences: false).count > 4
    }
    public func hasCollapsedMessage(in turn: Turn) -> Bool {
        messages(for: turn).contains { messageNeedsExpansion($0) }
    }
    public func toolMessages(for turn: Turn) -> [TurnMessage] {
        (turn.messages ?? []).filter { ["tool_call", "tool_result", "tool_text"].contains($0.kind) }
    }

    /// Loads full messages and keeps stale async responses out of the selected link.
    public func load(link: Int) async {
        request += 1; let current = request
        loading = true
        defer { if current == request { loading = false } }
        actionRequest += 1; plan = nil; pending = nil
        if status?.linkID != link { status = nil; history = nil }
        do {
            let response = try await engine.status(link: link, messages: true)
            guard current == request else { return }
            guard response.linkID == link else { status = nil; plan = nil; pending = nil; history = nil; loadFailed = true; return }
            let changedLink = status?.linkID != response.linkID
            status = response; errorNote = nil; loadFailed = false
            if changedLink {
                filter = .all; unfolded = false; expandedReplies = []; expandedTools = []
                history = nil; plan = nil; pending = nil
                focusedTurn = displayedTurns.first?.id ?? turns.last?.id
            } else if let focusedTurn, !turns.contains(where: { $0.id == focusedTurn }) { self.focusedTurn = nil }
        } catch let error as EngineCommandError {
            guard current == request else { return }; errorNote = error.note; loadFailed = true
        } catch { guard current == request else { return }; errorNote = nil; loadFailed = true }
    }

    /// Pause and resume do not write chats and act immediately.
    public func togglePause() async {
        guard let status else { return }
        let generation = actionRequest
        do {
            if status.paused { _ = try await engine.resume(link: status.linkID, mutation: .preview) }
            else { _ = try await engine.pause(link: status.linkID, mutation: .preview) }
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }
            await load(link: status.linkID)
        } catch let error as EngineCommandError {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = error.note
        }
        catch {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = nil
        }
    }
    public func showHistory() async {
        guard let status else { return }
        let generation = actionRequest
        do {
            let events = try await engine.history(link: status.linkID).events
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }
            history = events
        }
        catch let error as EngineCommandError {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = error.note
        }
        catch {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = nil
        }
    }
    public func open(tool: String) async {
        guard let status, let side = status.sides[tool], side.condition.exists else { return }
        let generation = actionRequest
        do { _ = try await engine.open(tool: tool, chat: side.chat.id) }
        catch let error as EngineCommandError {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = error.note
        }
        catch {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = nil
        }
    }
    public func previewRemoval() async { await preview(.unlink) }
    public func previewCopy(from tool: String, to target: String) async {
        guard let side = status?.sides[tool], side.condition.exists, tools.contains(target), target != tool else { return }
        let chat = side.chat
        await preview(.copy("\(chat.tool):\(chat.id)", target))
    }
    public func supportsSideAction(_ button: NoteButton, tool: String) -> Bool {
        guard let side = status?.sides[tool] else { return false }
        switch button.id {
        case "resume": return status?.paused == true
        case "open", "relaunch", "close_sync_reopen", "add_now": return side.condition.exists
        default: return false
        }
    }
    public func sideAction(_ button: NoteButton, tool: String) async {
        guard supportsSideAction(button, tool: tool) else { return }
        switch button.id {
        case "resume": if status?.paused == true { await togglePause() }
        case "relaunch", "close_sync_reopen": await preview(.relaunch(tool))
        case "add_now": await preview(.sync(tool))
        case "open": await open(tool: tool)
        default: break
        }
    }
    public func cancelPlan() { actionRequest += 1; plan = nil; pending = nil }
    public var confirmationButtons: [NoteButton] {
        guard let plan, let pending else { return [] }
        let permitted: Set<String>
        switch pending {
        case .unlink: permitted = ["unlink", "cancel"]
        case .copy: permitted = ["copy", "cancel"]
        case .sync: permitted = ["add_now", "cancel"]
        case .relaunch: permitted = ["close_sync_reopen", "relaunch", "cancel"]
        }
        var seen: Set<String> = []
        return plan.notes.flatMap(\.buttons).filter { permitted.contains($0.id) && seen.insert($0.id).inserted }
    }
    public func confirmPlan() async {
        guard !isConfirming, let plan, let pending else { return }
        isConfirming = true
        defer { isConfirming = false }
        await execute(pending, mutation: .confirm(plan.planID))
    }
    private func preview(_ action: PendingAction) async { actionRequest += 1; plan = nil; pending = action; await execute(action, mutation: .preview) }
    private func execute(_ action: PendingAction, mutation: MutationOptions) async {
        guard let status else { return }
        let generation = actionRequest
        var returned: Plan
        do {
            switch action {
            case .unlink:
                let result = try await engine.unlink(link: status.linkID, mutation: mutation)
                returned = Plan(planID: result.planID, applied: result.applied, linkID: status.linkID, steps: result.steps, decisionNeeded: result.decisionNeeded, notes: result.notes)
            case .copy(let source, let target):
                let result = try await engine.copy(from: source, to: target, andLink: false, mutation: mutation)
                returned = Plan(planID: result.planID, applied: result.applied, linkID: status.linkID, steps: result.steps, decisionNeeded: result.decisionNeeded, notes: result.notes)
            case .sync(let tool):
                let result = try await engine.sync(link: status.linkID, to: tool, mutation: mutation)
                returned = Plan(planID: result.planID, applied: result.applied, linkID: status.linkID, steps: result.steps, decisionNeeded: result.decisionNeeded, notes: result.notes)
            case .relaunch(let tool):
                let result = try await engine.relaunch(tool: tool, whenIdle: false, thenSync: status.linkID, mutation: mutation)
                returned = Plan(planID: result.planID, applied: result.applied, linkID: status.linkID, steps: result.steps, decisionNeeded: result.decisionNeeded, notes: result.notes)
            }
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }
            plan = returned
            if plan?.applied == true {
                cancelPlan()
                if case .unlink = action { self.status = nil; removedLinkID = status.linkID }
                else { await load(link: status.linkID) }
            }
        } catch let error as EngineCommandError {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = error.note
        }
        catch {
            guard generation == actionRequest, self.status?.linkID == status.linkID else { return }; errorNote = nil
        }
    }
}
