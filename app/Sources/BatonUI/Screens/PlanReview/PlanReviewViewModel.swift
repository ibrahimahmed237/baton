import Foundation
import Combine
import BatonKit

/// A plan-returning command that the review screen can preview and then confirm.
public enum PlanRequest: Equatable, Sendable {
    case link(from: String, to: String, mode: String)
    case copy(from: String, to: String, andLink: Bool)
    case unlink(link: Int)
    case sync(link: Int, to: String?)
    case continueIn(link: Int, tool: String)
    case relaunch(tool: String, whenIdle: Bool, thenSync: Int?)
    case brief(link: Int, to: String, writer: String?)

    /// Runs the command as a preview or as the confirmation of a previewed plan.
    func run(_ engine: any EngineClient, _ mutation: MutationOptions) async throws -> ReviewedPlan {
        switch self {
        case .link(let from, let to, let mode):
            let r = try await engine.link(from: from, to: to, mode: mode, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage))
        case .copy(let from, let to, let andLink):
            let r = try await engine.copy(from: from, to: to, andLink: andLink, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage))
        case .unlink(let link):
            let r = try await engine.unlink(link: link, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID ?? link, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage))
        case .sync(let link, let to):
            let r = try await engine.sync(link: link, to: to, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID ?? link, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage))
        case .continueIn(let link, let tool):
            let r = try await engine.continueIn(link: link, inTool: tool, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID ?? link, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage), opened: r.opened)
        case .relaunch(let tool, let whenIdle, let thenSync):
            let r = try await engine.relaunch(tool: tool, whenIdle: whenIdle, thenSync: thenSync, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID ?? thenSync, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage), replying: r.replying)
        case .brief(let link, let to, let writer):
            let r = try await engine.brief(link: link, to: to, writer: writer, mutation: mutation)
            return ReviewedPlan(Plan(planID: r.planID, applied: r.applied, linkID: r.linkID ?? link, steps: r.steps, decisionNeeded: r.decisionNeeded, notes: r.notes, confirmation: r.confirmation, stage: r.stage), brief: r.brief)
        }
    }
}

/// A plan with the extra fields some commands return beside it.
public struct ReviewedPlan: Equatable, Sendable {
    public var plan: Plan
    public var replying: [Chat]
    public var brief: BriefDetails?
    public var opened: Bool?
    /// Refuses incomplete artifacts, dishonest cost bounds and paid stages for an Offline choice.
    func validatesBrief(to destination: String, writer policy: String?) -> Bool {
        guard let brief, !plan.planID.isEmpty, plan.steps.allSatisfy({ $0.tool == destination }) else { return false }
        if policy == "offline", brief.writer != "offline" || plan.stage != "create" { return false }
        if let policy, policy != "offline", brief.writer != policy {
            guard plan.stage == "create", brief.writer == "offline",
                  plan.notes.contains(where: { $0.id == "brief.used_offline" }) else { return false }
        }
        guard plan.steps.contains(where: { $0.action == "create" && $0.tool == destination }) else { return false }
        switch plan.stage {
        case "generate":
            guard !plan.applied, brief.writer != "offline", let total = brief.estimatedTokens, total > 0,
                  let candidates = brief.candidateEstimates, candidates.first?.writer == brief.writer else { return false }
            var sum = 0
            var writers: Set<String> = []
            for candidate in candidates {
                guard !candidate.writer.isEmpty, candidate.writer != "offline", candidate.tokens >= 0,
                      writers.insert(candidate.writer).inserted else { return false }
                let addition = sum.addingReportingOverflow(candidate.tokens)
                guard !addition.overflow else { return false }; sum = addition.partialValue
                guard plan.notes.contains(where: { note in
                    note.id == "brief.cost" && note.values["writer_id"] == .string(candidate.writer) &&
                        !note.text.isEmpty && matchesTokens(note, candidate.tokens)
                }) else { return false }
            }
            return sum == total && plan.notes.contains { $0.id == "brief.total_cost" && !$0.text.isEmpty && matchesTokens($0, total) }
        case "create":
            return !(brief.artifactID ?? "").isEmpty && !(brief.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
                plan.steps.contains { $0.action == "create" && $0.tool == destination }
        default: return false
        }
    }
    private func matchesTokens(_ note: Note, _ expected: Int) -> Bool {
        switch note.values["tokens"] {
        case .number(let tokens): return tokens == Double(expected)
        case .string(let tokens): return Int(tokens.replacingOccurrences(of: ",", with: "")) == expected
        default: return false
        }
    }
    init(_ plan: Plan, replying: [Chat] = [], brief: BriefDetails? = nil, opened: Bool? = nil) {
        self.plan = plan; self.replying = replying; self.brief = brief; self.opened = opened
    }
}

/// How a review ended; selecting an alternative alone is never success.
public enum PlanOutcome: Equatable, Sendable {
    case applied
    case cancelled
    // Retained for source compatibility; a selection alone never produces this outcome.
    case attachedInstead
}

/// Exact identity of the notes mounted for one preview revision.
public struct PlanDisplayReceipt: Equatable, Sendable {
    public let planID: String
    public let revision: Int
    public let notes: [Note]
    public var identity: String {
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        let wording = (try? encoder.encode(notes))?.base64EncodedString() ?? ""
        return "\(revision):\(planID):\(wording)"
    }
}

/// A button retains its origin even when another side offers an identical button.
public struct PlanAction: Identifiable, Equatable, Sendable {
    public let id: String
    public let button: NoteButton
    public let noteID: String
    public let offeringTool: String?
    fileprivate let route: Route
    fileprivate enum Route: Equatable, Sendable {
        case cancel, confirm, preview(PlanRequest), unavailable, chooseCounterpart, ignored
    }
}

/// An unfinished alternative keeps the operation the user originally selected.
public enum PlanAlternative: Equatable, Sendable {
    case unavailable
    case chooseCounterpart
}

/// Shows engine plans and dispatches only recognized, request-specific choices.
@MainActor
public final class PlanReviewViewModel: ObservableObject {
    @Published public private(set) var request: PlanRequest?
    @Published public private(set) var originalRequest: PlanRequest?
    @Published public private(set) var reviewed: ReviewedPlan?
    @Published public private(set) var labels: [Note] = []
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    @Published public private(set) var outcome: PlanOutcome?
    @Published public private(set) var alternative: PlanAlternative?
    private let engine: any EngineClient
    private var gate = ConfirmationGate()
    private var generation = 0
    private var attemptedPlanIDs: Set<String> = []
    private var isConfirming = false

    public init(engine: any EngineClient) { self.engine = engine }
    public var plan: Plan? { reviewed?.plan }
    public var replying: [Chat] { reviewed?.replying ?? [] }
    public func label(_ id: String) -> Note? { labels.first { $0.id == id } }
    public var alternativeNote: Note? {
        switch alternative {
        case .unavailable: return label("plan.unavailable")
        case .chooseCounterpart: return label("plan.choose_counterpart")
        case nil: return nil
        }
    }
    /// All required explanation and confirmation wording; deduplication affects prose only.
    public var planNotes: [Note] {
        guard let plan else { return [] }
        return displayedPlanNotes(plan)
    }
    public var displayReceipt: PlanDisplayReceipt? {
        plan.map { PlanDisplayReceipt(planID: $0.planID, revision: generation, notes: planNotes) }
    }
    /// Source-compatible button list; indexed actions are used by the actual view.
    public var offers: [NoteButton] { actions.map(\.button) }
    public var actions: [PlanAction] {
        guard let plan, let request, let receipt = displayReceipt else { return [] }
        var result: [PlanAction] = []
        func append(_ note: Note, path: String, tool: String?, isConfirmation: Bool = false) {
            for (index, button) in note.buttons.enumerated() {
                let route = route(button, note: note, tool: tool, request: request, isConfirmation: isConfirmation)
                result.append(PlanAction(id: "\(receipt.identity):\(path):\(index)", button: button,
                                         noteID: note.id, offeringTool: tool, route: route))
            }
        }
        for (index, note) in plan.notes.enumerated() {
            append(note, path: "note:\(index)", tool: offeringTool(note, fallback: request.targetTool))
        }
        for (stepIndex, step) in plan.steps.enumerated() {
            for (noteIndex, note) in step.notes.enumerated() {
                let tool: String?
                if case .string(let explicit) = note.values["tool_id"], explicit != step.tool { tool = nil }
                else { tool = step.tool }
                append(note, path: "step:\(stepIndex):\(noteIndex)", tool: tool)
            }
        }
        if let note = plan.confirmation { append(note, path: "confirmation", tool: request.targetTool, isConfirmation: true) }
        // Cancel has no side effect or side provenance; one engine-provided Cancel suffices.
        var sawCancel = false
        result = result.filter { action in
            if action.route != .cancel { return true }
            defer { sawCancel = true }; return !sawCancel
        }
        if !sawCancel, let button = label("dialog.actions")?.buttons.first(where: { $0.id == "cancel" }) {
            result.append(PlanAction(id: "\(receipt.identity):cancel", button: button, noteID: "dialog.actions",
                                     offeringTool: nil, route: .cancel))
        }
        return alternative == nil ? result : result.filter { $0.route == .cancel }
    }
    public var canConfirm: Bool {
        // Relaunch execution belongs to C5; CP2 only presents its future contract.
        if case .relaunch = request { return false }
        guard let plan, let receipt = displayReceipt, alternative == nil, outcome == nil, !busy,
              !plan.applied, !plan.decisionNeeded,
              !attemptedPlanIDs.contains(plan.planID),
              !planNotes.contains(where: { ["plan.unavailable", "plan.choose_counterpart"].contains($0.id) }) else { return false }
        return gate.permits(receipt.notes, identity: receipt.identity) && actions.contains { $0.route == .confirm }
    }
    /// Rejects callbacks from earlier previews, even if their notes are identical.
    public func didDisplay(_ receipt: PlanDisplayReceipt) {
        guard receipt == displayReceipt else { return }
        objectWillChange.send()
        gate.markDisplayed(receipt.notes, identity: receipt.identity)
    }
    /// Keeps unknown/stale controls visibly disabled as well as refusing their dispatch.
    public func canChoose(_ action: PlanAction) -> Bool {
        guard !busy, outcome == nil, actions.contains(action) else { return false }
        if action.route == .cancel { return true }
        guard alternative == nil, let receipt = displayReceipt,
              gate.permits(receipt.notes, identity: receipt.identity) else { return false }
        if action.route == .confirm { return canConfirm }
        return action.route != .ignored
    }
    public func load(_ request: PlanRequest) async { await preview(request, preserveOriginal: false, loadLabels: true) }
    public func preview(_ request: PlanRequest) async { await preview(request, preserveOriginal: false, loadLabels: false) }
    private func preview(_ request: PlanRequest, preserveOriginal: Bool, loadLabels: Bool) async {
        guard !isConfirming else { return }
        generation += 1; let current = generation
        self.request = request
        if !preserveOriginal { originalRequest = request }
        reviewed = nil; gate = ConfirmationGate(); errorNote = nil; outcome = nil; alternative = nil; busy = true
        if loadLabels, labels.isEmpty, let setup = try? await engine.setup() {
            guard current == generation else { return }; labels = setup.notes ?? []
        }
        guard current == generation else { return }
        do {
            let result = try await request.run(engine, .preview)
            guard current == generation else { return }
            if let expected = request.linkID, result.plan.linkID != expected { busy = false; return }
            if case .brief(_, let destination, let policy) = request,
               !result.validatesBrief(to: destination, writer: policy) {
                errorNote = label("plan.unavailable"); busy = false; return
            }
            reviewed = result; busy = false
        } catch {
            guard current == generation else { return }
            errorNote = (error as? EngineCommandError)?.note; busy = false
        }
    }
    /// Indexed actions bind dispatch to the exact visible preview and offering side.
    public func choose(_ action: PlanAction) async {
        guard canChoose(action) else { return }
        if action.route == .cancel { cancel(); return }
        guard alternative == nil, let receipt = displayReceipt,
              gate.permits(receipt.notes, identity: receipt.identity) else { return }
        switch action.route {
        case .confirm: await confirm()
        case .preview(let request): await preview(request, preserveOriginal: true, loadLabels: false)
        case .unavailable: alternative = .unavailable
        case .chooseCounterpart: alternative = .chooseCounterpart
        case .cancel, .ignored: break
        }
    }
    /// Legacy callers may dispatch only a unique, exactly matching offered button.
    public func choose(_ button: NoteButton) async {
        let matches = actions.filter { $0.button == button }
        guard matches.count == 1, let action = matches.first else { return }
        await choose(action)
    }
    /// A host's explicit counterpart selection repreviews attached history without losing creation intent.
    public func selectCounterpart(_ destination: String) async {
        guard alternative == .chooseCounterpart, !busy,
              case .link(let from, let target, _) = originalRequest,
              let separator = destination.firstIndex(of: ":"),
              String(destination[..<separator]) == target,
              !destination[destination.index(after: separator)...].isEmpty else { return }
        await preview(.link(from: from, to: destination, mode: "attached_history"), preserveOriginal: true, loadLabels: false)
    }
    public func cancel() { guard !isConfirming else { return }; generation += 1; busy = false; outcome = .cancelled }
    public func confirm() async {
        guard canConfirm, let request, let plan else { return }
        attemptedPlanIDs.insert(plan.planID)
        generation += 1; let current = generation; busy = true; isConfirming = true
        defer { isConfirming = false }
        do {
            let result = try await request.run(engine, .confirm(plan.planID))
            guard current == generation else { return }
            if case .brief(let link, let destination, let policy) = request {
                guard result.plan.linkID == link, result.validatesBrief(to: destination, writer: policy),
                      result.plan.stage == "create", plan.stage != "generate" || !result.plan.applied else {
                    reviewed = nil; errorNote = label("plan.unavailable"); busy = false; gate = ConfirmationGate(); return
                }
            }
            reviewed = result; busy = false; gate = ConfirmationGate()
            if result.plan.applied { outcome = .applied }
        } catch {
            guard current == generation else { return }
            errorNote = (error as? EngineCommandError)?.note; busy = false; gate = ConfirmationGate()
        }
    }
    private func offeringTool(_ note: Note, fallback: String?) -> String? {
        if case .string(let tool) = note.values["tool_id"] { return tool }
        return fallback // An explicit request destination; never the first step or a display label.
    }
    private func route(_ button: NoteButton, note: Note, tool: String?, request: PlanRequest,
                       isConfirmation: Bool) -> PlanAction.Route {
        if button.id == "cancel" { return .cancel }
        if isConfirmation {
            return button.id == "confirm" && note.id == request.confirmationID(stage: plan?.stage) ? .confirm : .ignored
        }
        switch (button.id, note.id, request) {
        case ("copy_and_link", "link.copy", .copy(let from, let to, false)) where tool == to:
            return .preview(.copy(from: from, to: to, andLink: true))
        case ("copy", "link.copy", .copy(_, let to, false)) where tool == to:
            return .confirm
        case ("when_idle", "relaunch.replying", .relaunch(let requestedTool, false, let link)) where tool == requestedTool:
            return .preview(.relaunch(tool: requestedTool, whenIdle: true, thenSync: link))
        case ("close_anyway", "relaunch.replying", .relaunch(let requestedTool, false, _)) where tool == requestedTool:
            return .unavailable
        case ("when_idle", "write.when_idle", _): return .unavailable
        case ("attach", "write.app_must_close", .link(let from, let to, "full_copy")) where tool == request.targetTool:
            return to.contains(":") ? .preview(.link(from: from, to: to, mode: "attached_history")) : .chooseCounterpart
        case ("attach", "write.app_must_close", _) where tool == request.targetTool && tool != nil: return .unavailable
        case ("sync_relaunch_later", "new_chat.relaunch", .link), ("sync_relaunch_later", "new_chat.relaunch", .copy):
            guard let tool, tool == request.targetTool else { return .ignored }
            return plan?.steps.contains(where: { $0.needs.contains("app_closed") || $0.action == "close" }) == false ? .confirm : .unavailable
        case ("add_now", "write.chat_open_release", .sync),
             ("add_now", "write.release", .sync):
            guard tool != nil else { return .ignored }
            // Ordinary sync can plan attachment; explicit release needs a C3 contract.
            return .unavailable
        case ("close_sync_reopen", "new_chat.relaunch", _), ("close_sync_reopen", "write.app_must_close", .link),
             ("close_sync_reopen", "write.app_must_close", .copy), ("close_sync_reopen", "write.app_must_close", .brief):
            return .unavailable
        case ("close_sync_reopen", "write.chat_open", _), ("close_sync_reopen", "write.chat_open_release", _),
             ("close_sync_reopen", "write.app_must_close", _), ("relaunch", "relaunch_to_see", _),
             ("relaunch", "write.release", _):
            guard tool != nil else { return .ignored }
            return .unavailable
        default: return .ignored
        }
    }
}

private extension PlanRequest {
    var linkID: Int? {
        switch self {
        case .unlink(let link), .sync(let link, _), .continueIn(let link, _), .brief(let link, _, _): return link
        case .relaunch(_, _, let link): return link
        case .link, .copy: return nil
        }
    }
    var targetTool: String? {
        switch self {
        case .link(_, let to, _): return String(to.split(separator: ":", maxSplits: 1)[0])
        case .copy(_, let to, _), .continueIn(_, let to), .brief(_, let to, _): return to
        case .sync(_, let to): return to
        case .relaunch(let tool, _, _): return tool
        case .unlink: return nil
        }
    }
    func confirmationID(stage: String?) -> String {
        switch self {
        case .link: return "plan.confirm_link"
        case .copy: return "plan.confirm_copy"
        case .unlink: return "plan.confirm_unlink"
        case .sync: return "plan.confirm_sync"
        case .continueIn: return "plan.confirm_continue"
        case .relaunch: return "plan.confirm_relaunch"
        case .brief: return stage == "generate" ? "plan.confirm_brief_generation" : stage == "create" ? "plan.confirm_brief_creation" : ""
        }
    }
}
