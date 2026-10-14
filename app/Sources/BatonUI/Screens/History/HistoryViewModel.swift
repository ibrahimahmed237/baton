import Foundation
import Combine
import BatonKit

public struct HistoryPresentation: Decodable, Equatable, Sendable {
    public let id: Int
    public let label: Note
    public let undoLabel: Note
    public let restoreLabel: Note
    enum CodingKeys: String, CodingKey { case id, label; case undoLabel = "undo_label", restoreLabel = "restore_label" }
}
private struct HistoryProjection: Decodable, Sendable {
    let events: [HistoryEvent]
    let presentation: [HistoryPresentation]
    let notes: [Note]
    enum CodingKeys: String, CodingKey { case events, notes }
    init(from decoder: any Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        events = try fields.decode([HistoryEvent].self, forKey: .events)
        presentation = try fields.decode([HistoryPresentation].self, forKey: .events)
        notes = try fields.decodeIfPresent([Note].self, forKey: .notes) ?? []
    }
}

@MainActor public final class HistoryViewModel: ObservableObject {
    @Published public private(set) var events: [HistoryEvent] = []
    @Published public private(set) var presentation: [HistoryPresentation] = []
    @Published public private(set) var notes: [Note] = []
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    public let review: ActionReviewViewModel
    private let engine: any EngineClient
    private var link: Int?
    private var revision = 0
    public init(engine: any EngineClient) {
        self.engine = engine; review = ActionReviewViewModel(engine: engine)
        review.onApplied = { [weak self] in
            guard let self, let link = self.link else { return }
            await self.refresh(link: link, clearReview: false)
        }
    }
    public var legend: [HistoryEvent] {
        var kinds: Set<String> = []; return events.filter { kinds.insert($0.kind).inserted }
    }
    public func label(_ event: HistoryEvent) -> Note? { presentation.first { $0.id == event.id }?.label }
    public func undoLabel(_ event: HistoryEvent) -> Note? { presentation.first { $0.id == event.id }?.undoLabel }
    public func restoreLabel(_ event: HistoryEvent) -> Note? { presentation.first { $0.id == event.id }?.restoreLabel }
    public static func colour(_ kind: String) -> StateColour {
        switch kind {
        case "add", "added", "delivered", "synced", "place", "create", "created", "twin_created", "restore": return .added
        case "attached", "attach_pending": return .waiting
        case "merge": return .merged
        case "linked", "moved", "link_moved": return .action
        case "undo", "unlinked", "removed", "link_removed", "not_confirmed": return .danger
        default: return .neutral
        }
    }
    public static func instant(_ value: String) -> Date {
        let fractional = ISO8601DateFormatter(); fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value) ?? ISO8601DateFormatter().date(from: value) ?? .distantPast
    }
    public func load(link: Int) async { await refresh(link: link, clearReview: true) }
    private func refresh(link: Int, clearReview: Bool) async {
        revision += 1; let current = revision; self.link = link; events = []; presentation = []; notes = []; errorNote = nil; busy = true
        if clearReview { review.invalidate() }
        do {
            if let transport = engine as? any EngineTransport {
                let result = try await transport.response(command: "history", arguments: ["--link", String(link)], as: HistoryProjection.self)
                guard current == revision else { return }
                events = result.events; presentation = result.presentation; notes = result.notes
            } else {
                let result = try await engine.history(link: link)
                guard current == revision else { return }
                events = result.events
            }
            events.sort { Self.instant($0.at) == Self.instant($1.at) ? $0.id > $1.id : Self.instant($0.at) > Self.instant($1.at) }
            busy = false
        } catch { guard current == revision else { return }; errorNote = (error as? EngineCommandError)?.note; busy = false }
    }
    public func undo(_ event: HistoryEvent) async {
        guard !busy, let link, events.contains(event), event.canUndo else { return }
        await review.load(.undo(link: link, event: event.id))
    }
    public func restore(_ event: HistoryEvent) async {
        guard !busy, let link, events.contains(event), event.canRestore else { return }
        await review.load(.restore(link: link, event: event.id))
    }
}
