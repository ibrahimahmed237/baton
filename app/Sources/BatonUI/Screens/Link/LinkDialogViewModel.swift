import Foundation
import Combine
import BatonKit

/// The operation selected by the user.
public enum LinkDialogAction: Equatable, Sendable { case link, copy, change, fullCopy }

/// Presents engine-supplied choices and previews; never derives tool capabilities.
@MainActor
public final class LinkDialogViewModel: ObservableObject {
    @Published public private(set) var source: Chat?
    @Published public private(set) var tools: [SetupTool] = []
    @Published public private(set) var labels: [Note] = []
    @Published public private(set) var target: String?
    @Published public private(set) var targetChats: [Chat] = []
    @Published public private(set) var targetChat: String?
    @Published public private(set) var mode: String?
    @Published public private(set) var currentLink: LinkSummary?
    @Published public private(set) var retainedTool: String?
    @Published public private(set) var action: LinkDialogAction = .link
    @Published public private(set) var plan: Plan?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    @Published public private(set) var isApplying = false
    @Published public private(set) var finished = false
    private let engine: any EngineClient
    private var generation = 0
    private var gate = ConfirmationGate()
    /// Creates an engine-backed presentation value.
    public init(engine: any EngineClient) { self.engine = engine }
    /// Updates the engine-backed dialog presentation.
    public func label(_ id: String) -> Note? { labels.first { $0.id == id } }
    public var targetTools: [SetupTool] { tools.filter { action == .fullCopy || $0.tool != (action == .change ? retainedTool : source?.tool) } }
    public var selectedTool: SetupTool? { tools.first { $0.tool == target } }
    public var modes: [LinkModeOption] { selectedTool?.linkModes ?? [] }
    public var canConfirm: Bool { !busy && !finished && plan?.applied == false && plan?.decisionNeeded == false && gate.permits(planNotes) }
    public var planNotes: [Note] { (plan?.notes ?? []) + (plan?.steps.flatMap(\.notes) ?? []) }
    public var buttons: [NoteButton] { label("dialog.actions")?.buttons ?? [] }
    /// Updates the engine-backed dialog presentation.
    public func markNotesDisplayed() { gate.markDisplayed(planNotes) }

    /// Updates the engine-backed dialog presentation.
    public func load(source: Chat, link: LinkSummary? = nil, replacing: String? = nil) async {
        guard !isApplying else { return }
        generation += 1; let request = generation
        targetChat = nil; targetChats = []; tools = []; errorNote = nil; labels = []
        self.source = source; currentLink = link; retainedTool = source.tool
        action = replacing == nil ? .link : .fullCopy; plan = nil; finished = false; busy = true
        do {
            let setup = try await engine.setup()
            let links = try await engine.links()
            guard request == generation else { return }
            currentLink = link ?? links.links.first { $0.sides[source.tool]?.id == source.id }
            tools = setup.tools.filter(\.installed)
            labels = setup.notes ?? []
            target = replacing ?? tools.first(where: { $0.tool != source.tool })?.tool
            mode = action == .fullCopy ? "full_copy" : modes.first(where: \.available)?.mode
            if let replacing, currentLink?.sides[replacing] == nil { target = nil; busy = false; return }
            busy = false
            await preview()
        } catch { finishError(error, request: request) }
    }
    /// Updates the engine-backed dialog presentation.
    public func selectTarget(_ tool: String) async {
        guard !isApplying else { return }
        guard targetTools.contains(where: { $0.tool == tool }), action != .fullCopy else { return }
        target = tool; targetChat = nil; targetChats = []; mode = action == .copy ? "full_copy" : modes.first(where: \.available)?.mode
        await preview()
    }
    /// Updates the engine-backed dialog presentation.
    public func selectMode(_ value: String) async {
        guard !isApplying else { return }
        guard modes.contains(where: { $0.mode == value && $0.available }), action != .copy, action != .fullCopy else { return }
        guard targetChat == nil || value != "brief" else { return }
        mode = value; await preview()
    }
    /// Updates the engine-backed dialog presentation.
    public func selectChat(_ id: String?) async {
        guard !isApplying else { return }
        guard id == nil || targetChats.contains(where: { $0.tool == target && $0.id == id }) else { return }
        targetChat = id
        if id != nil && mode == "brief" { mode = modes.first(where: { $0.available && $0.mode != "brief" })?.mode }
        await preview()
    }
    /// Updates the engine-backed dialog presentation.
    public func selectRetainedSide(_ tool: String) async {
        guard !isApplying else { return }
        guard currentLink?.sides[tool] != nil else { return }
        retainedTool = tool
        if target == tool { target = tools.first(where: { $0.tool != tool })?.tool; targetChat = nil; targetChats = []; mode = modes.first(where: \.available)?.mode }
        await preview()
    }
    /// Updates the engine-backed dialog presentation.
    public func choose(_ value: LinkDialogAction) async {
        guard !isApplying else { return }
        guard value != .fullCopy, action != .fullCopy else { return }
        guard value != .change || currentLink != nil else { return }
        action = value
        if value == .copy { mode = "full_copy"; targetChat = nil }
        else if !modes.contains(where: { $0.mode == mode && $0.available }) { mode = modes.first(where: \.available)?.mode }
        await preview()
    }
    /// Updates the engine-backed dialog presentation.
    public func cancel() { guard !isApplying else { return }; generation += 1; plan = nil; busy = false; finished = true }

    /// Updates the engine-backed dialog presentation.
    public func preview() async {
        guard !isApplying else { return }
        generation += 1; let request = generation
        plan = nil; gate = ConfirmationGate(); errorNote = nil; busy = true
        guard let target, let mode, modes.contains(where: { $0.mode == mode && $0.available }), source != nil else { busy = false; return }
        do {
            let chats = try await engine.chats(tool: target, folder: nil)
            guard request == generation else { return }
            targetChats = chats.chats.filter { $0.tool == target }
            if let id = targetChat, !targetChats.contains(where: { $0.id == id }) { targetChat = nil }
            let response = try await execute(.preview)
            guard request == generation else { return }
            plan = response; busy = false
        } catch { finishError(error, request: request) }
    }
    /// Updates the engine-backed dialog presentation.
    public func confirm() async {
        guard canConfirm, let plan else { return }
        generation += 1; let request = generation; busy = true; isApplying = true
        defer { isApplying = false }
        do {
            let response = try await execute(.confirm(plan.planID))
            guard request == generation else { return }
            self.plan = response; finished = response.applied; busy = false
            gate = ConfirmationGate()
        } catch { finishError(error, request: request) }
    }
    private func execute(_ mutation: MutationOptions) async throws -> Plan {
        guard let source, let target, let mode else { throw CancellationError() }
        let destination = targetChat.map { target + ":" + $0 } ?? target
        switch action {
        case .link:
            let r = try await engine.link(from: source.tool + ":" + source.id, to: destination, mode: mode, mutation: mutation)
            return Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes)
        case .copy:
            let r = try await engine.copy(from: source.tool + ":" + source.id, to: target, andLink: false, mutation: mutation)
            return Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes)
        case .change:
            guard let link = currentLink, let retainedTool else { throw CancellationError() }
            let r = try await engine.relink(link: link.linkID, to: destination, keep: retainedTool, mode: mode, mutation: mutation)
            return Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes)
        case .fullCopy:
            guard let link = currentLink else { throw CancellationError() }
            let r = try await engine.fullCopy(link: link.linkID, replace: target, mutation: mutation)
            return Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes)
        }
    }
    private func finishError(_ error: Error, request: Int) {
        guard request == generation else { return }
        errorNote = (error as? EngineCommandError)?.note; plan = nil; busy = false
    }
}
