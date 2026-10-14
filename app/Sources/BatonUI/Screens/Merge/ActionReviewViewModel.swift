import Foundation
import Combine
import BatonKit

public struct RemovalGroup: Decodable, Equatable, Sendable {
    public let tool: String
    public let category: String
    public let heading: Note
    public let removes: [RemovedTurn]
}
private struct UndoProjection: Decodable, Sendable {
    let result: UndoResult
    let groups: [RemovalGroup]
    enum CodingKeys: String, CodingKey { case groups = "removal_groups" }
    init(from decoder: any Decoder) throws {
        result = try UndoResult(from: decoder)
        groups = try decoder.container(keyedBy: CodingKeys.self).decodeIfPresent([RemovalGroup].self, forKey: .groups) ?? []
    }
}

private struct MergeActionProjection: Decodable, Sendable {
    let result: MergeResult
    let order: [Int]
    let preset: String
    let keep: String
    let split: Bool
    let mismatchNote: Note?
    enum CodingKeys: String, CodingKey { case order, preset, keep, split; case mismatchNote = "mismatch_note" }
    init(from decoder: any Decoder) throws {
        result = try MergeResult(from: decoder)
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        order = try fields.decodeIfPresent([Int].self, forKey: .order) ?? []
        preset = try fields.decodeIfPresent(String.self, forKey: .preset) ?? ""
        keep = try fields.decodeIfPresent(String.self, forKey: .keep) ?? ""
        split = try fields.decodeIfPresent(Bool.self, forKey: .split) ?? false
        mismatchNote = try fields.decodeIfPresent(Note.self, forKey: .mismatchNote)
    }
    func matches(_ choice: MergeChoice) -> Bool {
        switch choice {
        case .order(let ids): return order == ids && keep.isEmpty && !split
        case .preset(let id): return preset == id && keep.isEmpty && !split
        case .keep(let tool): return keep == tool && !split
        case .split: return split
        }
    }
}

public enum ScreenAction: Equatable, Sendable {
    case merge(link: Int, choice: MergeChoice)
    case undo(link: Int, event: Int)
    case restore(link: Int, event: Int)
    var link: Int { switch self { case .merge(let link, _), .undo(let link, _), .restore(let link, _): return link } }
    func run(_ engine: any EngineClient, mutation: MutationOptions) async throws -> (Plan, [RemovedTurn], Turn?, [RemovalGroup]) {
        switch self {
        case .merge(let link, let choice):
            let r: MergeResult
            if let transport = engine as? any EngineTransport {
                var arguments = ["--link", String(link)]
                switch choice {
                case .order(let ids): arguments += ["--order", ids.map(String.init).joined(separator: ",")]
                case .preset(let id): arguments += ["--preset", id]
                case .keep(let tool): arguments += ["--keep", tool]
                case .split: arguments += ["--split"]
                }
                switch mutation { case .preview: arguments += ["--dry-run"]; case .confirm(let id): arguments += ["--confirm", id] }
                let projection = try await transport.response(command: "merge", arguments: arguments, as: MergeActionProjection.self)
                guard projection.matches(choice) else { throw EngineCommandError(kind: "chat_changed", note: projection.mismatchNote) }
                r = projection.result
            } else { r = try await engine.merge(link: link, choice: choice, mutation: mutation) }
            return (Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation), [], nil, [])
        case .undo(let link, let event):
            var groups: [RemovalGroup] = []
            let r: UndoResult
            if let transport = engine as? any EngineTransport {
                let arguments = ["--link", String(link), "--to", String(event)] + (mutation == .preview ? ["--dry-run"] : { if case .confirm(let id) = mutation { return ["--confirm", id] }; return [] }())
                let projection = try await transport.response(command: "undo", arguments: arguments, as: UndoProjection.self)
                r = projection.result; groups = projection.groups
            } else { r = try await engine.undo(link: link, event: event, mutation: mutation) }
            return (Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation), r.removes, r.endsAt, groups)
        case .restore(_, let event):
            let r = try await engine.restore(event: event, mutation: mutation)
            return (Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation), [], nil, [])
        }
    }
}

/// Shared by these two screens; consent belongs to one immutable preview revision.
@MainActor public final class ActionReviewViewModel: ObservableObject {
    @Published public private(set) var plan: Plan?
    @Published public private(set) var removalGroups: [RemovalGroup] = []
    public var onApplied: (() async -> Void)?
    @Published public private(set) var removes: [RemovedTurn] = []
    @Published public private(set) var endsAt: Turn?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    private let engine: any EngineClient
    private var action: ScreenAction?
    private var revision = 0
    private var gate = ConfirmationGate()
    private var attempted: Set<String> = []
    private var confirming = false
    public init(engine: any EngineClient) { self.engine = engine }
    public var addedTurns: [RemovedTurn] {
        guard let steps = plan?.steps, steps.count == 1, let tool = steps.first?.tool else { return removes }
        return removes.filter { $0.turn.origin != tool }
    }
    public var writtenAfterwards: [RemovedTurn] {
        guard let steps = plan?.steps, steps.count == 1, let tool = steps.first?.tool else { return [] }
        return removes.filter { $0.turn.origin == tool }
    }
    public var notes: [Note] { plan.map(displayedPlanNotes) ?? [] }
    public var displayReceipt: PlanDisplayReceipt? { plan.map { PlanDisplayReceipt(planID: $0.planID, revision: revision, notes: notes) } }
    public var buttons: [NoteButton] {
        var result: [NoteButton] = []
        for note in notes { for button in note.buttons where offered(button, by: note) {
            if !result.contains(button) { result.append(button) }
        } }
        return result
    }
    private func offered(_ button: NoteButton, by note: Note) -> Bool {
        if BoundPlanOffer.offered(by: note, button: button) != nil { return true }
        if button.id == "cancel" { return true }
        switch action {
        case .undo: return (button.id == "undo" && ["plan.confirm_undo", "undo.cut", "undo.cut_reopen", "undo.shorter", "undo.shorter_closed"].contains(note.id)) || (button.id == "when_idle" && note.id == "undo.replying")
        case .restore: return button.id == "restore" && ["undo.restore", "undo.earlier_chat"].contains(note.id)
        case .merge: return (button.id == "confirm" && note == plan?.confirmation && ["plan.confirm_merge", "plan.confirm_keep", "plan.confirm_split"].contains(note.id)) || (button.id == "open" && note.id == "merge.open" && plan?.applied == true)
        case nil: return false
        }
    }
    public var canConfirm: Bool {
        guard let plan, let receipt = displayReceipt, !busy, !plan.applied, !plan.decisionNeeded,
              plan.linkID == action?.link, !plan.planID.isEmpty, !attempted.contains(plan.planID),
              !notes.contains(where: { ["undo.replying", "plan.unavailable"].contains($0.id) }),
              buttons.contains(where: { $0.id != "cancel" }) else { return false }
        return gate.permits(receipt.notes, identity: receipt.identity)
    }
    public func didDisplay(_ receipt: PlanDisplayReceipt) {
        guard receipt == displayReceipt else { return }
        objectWillChange.send(); gate.markDisplayed(receipt.notes, identity: receipt.identity)
    }
    public func invalidate() {
        guard !confirming else { return }
        revision += 1; plan = nil; removes = []; removalGroups = []; endsAt = nil; action = nil; gate = ConfirmationGate(); busy = false; errorNote = nil
    }
    public func load(_ action: ScreenAction) async {
        guard !confirming else { return }
        invalidate(); self.action = action; busy = true; let current = revision
        do {
            let result = try await action.run(engine, mutation: .preview)
            guard current == revision else { return }
            guard result.0.linkID == action.link, !result.0.applied else { busy = false; return }
            plan = result.0; removes = result.1; endsAt = result.2; removalGroups = result.3; busy = false
        } catch { guard current == revision else { return }; errorNote = (error as? EngineCommandError)?.note; busy = false }
    }
    public func choose(_ button: NoteButton) async {
        guard buttons.contains(button), !busy else { return }
        if button.id == "cancel" { invalidate(); return }
        if button.id == "open", plan?.applied == true,
           let note = notes.first(where: { $0.id == "merge.open" && $0.buttons.contains(button) }),
           case .string(let tool) = note.values["tool_id"], case .string(let chat) = note.values["chat_id"] {
            do { _ = try await engine.open(tool: tool, chat: chat) }
            catch { errorNote = (error as? EngineCommandError)?.note }
            return
        }
        guard canConfirm, let plan, let action else { return }
        attempted.insert(plan.planID); busy = true; confirming = true; gate = ConfirmationGate()
        defer { busy = false; confirming = false }
        do {
            let result: (Plan, [RemovedTurn], Turn?, [RemovalGroup])
            if let note = notes.first(where: { BoundPlanOffer.offered(by: $0, button: button) != nil }),
               let offer = BoundPlanOffer.offered(by: note, button: button) {
                result = (try await offer.run(engine), removes, endsAt, removalGroups)
            } else { result = try await action.run(engine, mutation: .confirm(plan.planID)) }
            guard result.0.linkID == action.link else { self.plan = nil; removes = []; removalGroups = []; endsAt = nil; return }
            revision += 1; self.plan = result.0; removes = result.1; endsAt = result.2; removalGroups = result.3
            if result.0.applied { await onApplied?() }
        } catch { errorNote = (error as? EngineCommandError)?.note }
    }
}
