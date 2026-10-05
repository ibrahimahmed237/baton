import Foundation
import Combine
import BatonKit

/// Sidebar destinations, including only tools reported as installed.
public enum WindowSection: Hashable, Sendable {
    case linked, attention, suggestions, chats(String), activity
}

/// Stable selections within the window's lists.
public enum WindowSelection: Hashable, Sendable {
    case link(Int), suggestion(String, String, String, String), chat(String, String), event(Int, Int)
}

/// Associates a history event with the link whose pair it describes.
public struct ActivityEntry: Identifiable, Sendable {
    public let link: LinkSummary
    public let event: HistoryEvent
    public var id: String { "\(link.linkID):\(event.id)" }
}

/// Loads window lists through the engine, without reading chat files or deriving sync rules.
@MainActor
public final class WindowViewModel: ObservableObject {
    @Published public private(set) var section: WindowSection = .linked
    @Published public private(set) var selection: WindowSelection?
    @Published public private(set) var links: [LinkSummary] = []
    @Published public private(set) var notes: [Note] = []
    @Published public private(set) var suggestions: [Suggestion] = []
    @Published public private(set) var installedTools: [String] = []
    @Published public private(set) var chats: [String: [Chat]] = [:]
    @Published public private(set) var activity: [ActivityEntry] = []
    @Published public private(set) var errorNote: Note?
    private let engine: any EngineClient
    private var refreshNumber = 0

    /// Takes the sole source of data and displayed wording.
    public init(engine: any EngineClient) { self.engine = engine }

    public func makeStatusModel() -> SyncStatusViewModel { SyncStatusViewModel(engine: engine) }

    public var sections: [WindowSection] { [.linked, .attention, .suggestions] + installedTools.map(WindowSection.chats) + [.activity] }
    public var attentionLinks: [LinkSummary] { links.filter { $0.needsAttention ?? $0.decisionNeeded } }
    public var listedLinks: [LinkSummary] { section == .attention ? attentionLinks : links }
    public var selectedLink: LinkSummary? {
        guard case .link(let id) = selection else { return nil }
        return links.first { $0.linkID == id }
    }

    public var selectedSuggestion: Suggestion? { suggestions.first { suggestionSelection($0) == selection } }

    /// Identifies a suggestion by both chats, preserving identity when the list reorders.
    public func suggestionSelection(_ suggestion: Suggestion) -> WindowSelection {
        .suggestion(suggestion.a.tool, suggestion.a.id, suggestion.b.tool, suggestion.b.id)
    }

    /// Gets sidebar wording from the engine's optional presentation notes.
    public func label(for destination: WindowSection) -> Note? {
        let id: String
        switch destination {
        case .linked: id = "screen.linked"
        case .attention: id = "screen.attention"
        case .suggestions: id = "screen.suggestions"
        case .chats(let tool):
            return notes.first { $0.id == "screen.all_chats" && $0.values["tool"] == .string(tool) }
        case .activity: id = "screen.activity"
        }
        return notes.first { $0.id == id }
    }

    /// Refreshes all list data and preserves only selections that remain valid.
    public func refresh() async {
        refreshNumber += 1
        let refresh = refreshNumber
        do {
            let response = try await engine.links()
            let setup = try await engine.setup()
            let suggested = try await engine.suggestions()
            let installed = setup.tools.filter(\.installed).map(\.tool).sorted()
            var allChats: [String: [Chat]] = [:]
            for tool in installed {
                allChats[tool] = try await engine.chats(tool: tool, folder: nil).chats.filter { $0.tool == tool }
            }
            var events: [ActivityEntry] = []
            for link in response.links {
                events += try await engine.history(link: link.linkID).events.map { ActivityEntry(link: link, event: $0) }
            }
            guard refreshNumber == refresh else { return }
            links = response.links; notes = response.notes; suggestions = suggested.suggestions
            installedTools = installed; chats = allChats
            let datedEvents: [(index: Int, entry: ActivityEntry, date: Date)] = events.enumerated().map { index, entry in
                (index: index, entry: entry, date: eventDate(entry.event.at))
            }
            let sortedEvents = datedEvents.sorted { first, second in
                if first.date == second.date { return first.index < second.index }
                return first.date > second.date
            }
            activity = sortedEvents.map { $0.entry }
            if !sections.contains(section) { section = .linked; selection = nil }
            if let selection, !selections.contains(selection) { self.selection = nil }
            errorNote = nil
        } catch let error as EngineCommandError {
            guard refreshNumber == refresh else { return }; errorNote = error.note
        } catch {
            guard refreshNumber == refresh else { return }; errorNote = nil
        }
    }

    /// Navigates only to a destination still supported by the current setup.
    public func navigate(to destination: WindowSection) {
        guard sections.contains(destination) else { return }
        section = destination; selection = nil
    }

    /// Selects only an item that belongs to the current list.
    public func select(_ item: WindowSelection) {
        guard selections.contains(item) else { return }
        selection = item
    }

    private var selections: [WindowSelection] {
        switch section {
        case .linked, .attention: return listedLinks.map { .link($0.linkID) }
        case .suggestions: return suggestions.map(suggestionSelection)
        case .chats(let tool): return (chats[tool] ?? []).map { .chat(tool, $0.id) }
        case .activity: return activity.map { .event($0.link.linkID, $0.event.id) }
        }
    }

    private func eventDate(_ time: String) -> Date {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = parser.date(from: time) { return date }
        parser.formatOptions = [.withInternetDateTime]
        return parser.date(from: time) ?? .distantPast
    }
}
