import Foundation
import Combine
import BatonKit

/// What gets sent across in a hand-off (DESIGN 6).
public enum HandOffMode: Equatable, Sendable { case full, brief }

/// A writer policy; automatic lets the engine choose eligible candidates.
public enum HandOffWriter: Equatable, Sendable { case automatic, offline }

/// Shows engine notes and retains the precise conversation intended by a limit offer.
@MainActor
public final class HandOffViewModel: ObservableObject {
    @Published public private(set) var labels: [Note] = []
    @Published public private(set) var status: StatusResult?
    @Published public private(set) var chat: Chat?
    @Published public private(set) var offer: Note?
    @Published public private(set) var offerDismissed = false
    @Published public private(set) var target: String?
    @Published public private(set) var brief: ReviewedPlan?
    @Published public private(set) var mode: HandOffMode = .full
    @Published public private(set) var writer: HandOffWriter = .automatic
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var loading = false
    @Published public private(set) var failed = false
    @Published public private(set) var pendingReview: PlanRequest?
    @Published public private(set) var linkRequested: Chat?
    /// The dialog receives the offer's original destination, regardless of later UI selections.
    @Published public private(set) var linkDestinationTool: String?
    private let engine: any EngineClient
    private var generation = 0
    private var dismissedOfferKeys: Set<String> = []

    /// Creates the screen with its only engine boundary.
    public init(engine: any EngineClient) { self.engine = engine }
    /// Finds engine-owned presentation wording.
    public func label(_ id: String) -> Note? { labels.first { $0.id == id } }
    public var linkID: Int? { status?.linkID }
    public var isLinked: Bool { status != nil }
    public var tools: [String] { status?.sides.keys.sorted() ?? [] }
    /// Finds one side by its stable tool identity.
    public func side(_ tool: String) -> Side? { status?.sides[tool] }
    public var limitedTool: String? { tools.first { side($0)?.usage.limit != nil } }
    public var bannerVisible: Bool { offer != nil && !offerDismissed }
    public var hasUnwordedError: Bool { failed && errorNote == nil }
    public var canAct: Bool { !loading && !failed && (status != nil || chat != nil) }
    public var sourceTool: String? { isLinked ? tools.first { $0 != target } : chat?.tool }
    /// Returns context and delivery explanations for one side.
    public func notes(for tool: String) -> [Note] { side(tool)?.notes ?? [] }
    /// Uses only a percentage supplied for a known context size.
    public func percent(for tool: String) -> Double? {
        guard let usage = side(tool)?.usage, usage.size != nil else { return nil }
        return usage.percent
    }
    /// Selects the actual known-size or token-only usage note.
    public func contextNote(for tool: String) -> Note? {
        notes(for: tool).first { ["context.in_use", "context.in_use_no_size"].contains($0.id) }
    }
    public var statusNotes: [Note] { status?.notes ?? [] }
    public var writerNotes: [Note] {
        brief?.plan.notes.filter { ["brief.written_by", "brief.skipped_limit", "brief.skipped_failed", "brief.skipped_no_runner", "brief.used_offline", "brief.cost", "brief.total_cost", "brief.pinned_size"].contains($0.id) } ?? []
    }
    public var briefPreviewNotes: [Note] { brief?.plan.notes.filter { !writerNotes.contains($0) } ?? [] }
    public var briefWriter: String? { brief?.brief?.writer }
    public var request: PlanRequest? {
        guard canAct, let linkID, let target, side(target) != nil else { return nil }
        switch mode {
        case .full: return .continueIn(link: linkID, tool: target)
        case .brief: return .brief(link: linkID, to: target, writer: writer == .offline ? "offline" : nil)
        }
    }

    /// Erases the previous conversation before the next asynchronous load starts.
    private func reset() -> Int {
        generation += 1
        labels = []; status = nil; chat = nil; offer = nil; target = nil; brief = nil
        offerDismissed = false; mode = .full; writer = .automatic; failed = false
        pendingReview = nil; linkRequested = nil; linkDestinationTool = nil; errorNote = nil; loading = true
        return generation
    }

    /// Full mode loads only context and offers; generating a brief is always an explicit choice.
    public func load(link: Int, offers: [Note] = [], to: String? = nil) async {
        let current = reset()
        defer { if current == generation { loading = false } }
        do {
            let setup = try await engine.setup()
            guard current == generation else { return }
            labels = setup.notes ?? []
            let result = try await engine.status(link: link, messages: false)
            guard current == generation else { return }
            guard result.linkID == link, result.sides.count == 2,
                  result.sides.allSatisfy({ $0.key == $0.value.tool && $0.key == $0.value.chat.tool }),
                  to == nil || result.sides[to!] != nil else { fail(nil); return }
            status = result
            offer = offers.first { validOffer($0, status: result) && !wasDismissed($0) }
            target = to ?? offer.flatMap { string($0, "destination_tool_id") } ?? result.sides.keys.sorted().last
        } catch { guard current == generation else { return }; fail(error) }
    }

    /// An unlinked offer still retains its named destination for the future link dialog.
    public func load(unlinked chat: Chat, offers: [Note]) async {
        let current = reset()
        defer { if current == generation { loading = false } }
        do {
            let setup = try await engine.setup()
            guard current == generation else { return }
            labels = setup.notes ?? []
            self.chat = chat
            offer = offers.first { note in
                !wasDismissed(note) && note.id.hasPrefix("limit.offer_") && string(note, "source_tool_id") == chat.tool &&
                string(note, "source_chat_id") == chat.id && string(note, "offer_key") != nil &&
                string(note, "destination_tool_id").map { destination in
                    destination != chat.tool && setup.tools.contains { $0.tool == destination }
                } == true && note.values["link_id"] == .null
            }
            target = offer.flatMap { string($0, "destination_tool_id") }
        } catch { guard current == generation else { return }; fail(error) }
    }

    /// Invalidates the previous plan when delivery mode changes.
    public func selectMode(_ value: HandOffMode) {
        guard canAct, mode != value else { return }
        invalidatePreview(); mode = value
    }
    /// Invalidates the previous plan when brief policy changes.
    public func selectWriter(_ value: HandOffWriter) {
        guard canAct, writer != value else { return }
        invalidatePreview(); writer = value
    }
    /// Selects a validated linked destination and clears stale intent.
    public func selectTarget(_ tool: String) {
        guard canAct, side(tool) != nil, target != tool else { return }
        invalidatePreview(); target = tool
    }
    private func invalidatePreview() { generation += 1; brief = nil; pendingReview = nil; errorNote = nil }

    /// Loads the chosen brief's cost or offline artifact without confirming any operation.
    public func previewChoice() async {
        guard canAct, mode == .brief, let request, let destination = target else { return }
        generation += 1; let current = generation
        brief = nil; pendingReview = nil; loading = true; errorNote = nil
        defer { if current == generation { loading = false } }
        do {
            let result = try await request.run(engine, .preview)
            guard current == generation else { return }
            guard result.plan.linkID == linkID, !result.plan.applied,
                  result.validatesBrief(to: destination, writer: writer == .offline ? "offline" : nil) else { fail(nil); return }
            brief = result
        } catch { guard current == generation else { return }; fail(error) }
    }
    /// Remembers this event locally while E9 owns durable suppression.
    public func dismissOffer() {
        guard canAct else { return }
        if let offer, let key = string(offer, "offer_key") { dismissedOfferKeys.insert(key) }
        offerDismissed = true
    }
    private func wasDismissed(_ note: Note) -> Bool {
        string(note, "offer_key").map { dismissedOfferKeys.contains($0) } ?? false
    }

    /// Never derives an offered destination from the current selection or a sorted side list.
    public func choose(_ button: NoteButton) {
        guard canAct, bannerVisible, let offer, offer.buttons.contains(button) else { return }
        switch button.id {
        case "continue":
            guard let status, validOffer(offer, status: status), let destination = string(offer, "destination_tool_id") else { return }
            pendingReview = .continueIn(link: status.linkID, tool: destination)
        case "link_and_continue":
            guard !isLinked, let chat, let destination = string(offer, "destination_tool_id") else { return }
            linkRequested = chat; linkDestinationTool = destination
        case "not_now": dismissOffer()
        default: break
        }
    }
    /// Routes the engine's existing large-chat choice without starting generation.
    public func chooseRecommendation(_ button: NoteButton) async {
        guard canAct, statusNotes.contains(where: { $0.id == "brief.large_chat" && $0.buttons.contains(button) }) else { return }
        switch button.id {
        case "write_brief": selectMode(.brief); await previewChoice()
        case "send_in_full": selectMode(.full)
        default: break
        }
    }
    /// Sends the current immutable request to the separately gated review.
    public func beginReview() { pendingReview = request }
    private func fail(_ error: Error?) {
        status = nil; chat = nil; offer = nil; target = nil; brief = nil; pendingReview = nil
        linkRequested = nil; linkDestinationTool = nil; failed = true
        errorNote = (error as? EngineCommandError)?.note ?? label("plan.unavailable")
    }
    private func string(_ note: Note, _ key: String) -> String? {
        guard case .string(let value) = note.values[key], !value.isEmpty else { return nil }; return value
    }
    private func validOffer(_ note: Note, status: StatusResult) -> Bool {
        guard note.id.hasPrefix("limit.offer_"), string(note, "offer_key") != nil,
              note.values["link_id"] == .number(Double(status.linkID)),
              let source = string(note, "source_tool_id"), let destination = string(note, "destination_tool_id"),
              source != destination, let sourceSide = status.sides[source], let destinationSide = status.sides[destination] else { return false }
        return string(note, "source_chat_id") == sourceSide.chat.id && string(note, "destination_chat_id") == destinationSide.chat.id
    }
}
