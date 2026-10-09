import Foundation
import Combine
import BatonKit

/// Holds the popover's engine responses, selection and Continue preview.
@MainActor
public final class PopoverViewModel: ObservableObject {
    @Published public private(set) var links: [LinkSummary] = []
    @Published public private(set) var notes: [Note] = []
    @Published public private(set) var suggestions: [Suggestion] = []
    @Published public private(set) var selectedLinkID: Int?
    @Published public private(set) var plan: ContinueResult?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var loading = false
    private let engine: any EngineClient
    private var requestNumber = 0
    private var refreshNumber = 0

    /// Receives the only source of data and user-facing wording.
    public init(engine: any EngineClient) { self.engine = engine }

    public func continueNote(for tool: String) -> Note? {
        guard let label = selectedLink?.sides[tool]?.displayLabel else { return nil }
        return notes.first { $0.id == "screen.continue" && $0.values["tool"] == .string(label) }
    }
    public var selectedLink: LinkSummary? { links.first { $0.linkID == selectedLinkID } }
    public var needsDecision: Bool { links.contains { $0.decisionNeeded } }

    /// Refreshes links and suggestions while retaining a valid selection.
    public func refresh() async {
        loading = true
        requestNumber += 1
        refreshNumber += 1
        let refresh = refreshNumber
        plan = nil
        defer { if refreshNumber == refresh { loading = false } }
        do {
            let response = try await engine.links()
            let suggested = try await engine.suggestions()
            guard refreshNumber == refresh else { return }
            links = response.links
            notes = response.notes
            suggestions = suggested.suggestions
            if !links.contains(where: { $0.linkID == selectedLinkID }) {
                selectedLinkID = links.first?.linkID
                plan = nil
            }
            errorNote = nil
        } catch let error as EngineCommandError {
            guard refreshNumber == refresh else { return }
            errorNote = error.note
        } catch {
            guard refreshNumber == refresh else { return }
            errorNote = nil
        }
    }

    /// Selects an existing link and clears the preceding preview.
    public func select(linkID: Int) {
        guard links.contains(where: { $0.linkID == linkID }) else { return }
        selectedLinkID = linkID
        plan = nil
        requestNumber += 1
    }

    /// Asks for exactly the selected link and target without performing a write.
    public func continueIn(tool: String) async {
        guard !loading, let link = selectedLink, link.sides[tool] != nil else { return }
        let selectedID = link.linkID
        requestNumber += 1
        let request = requestNumber
        plan = nil
        do {
            let result = try await engine.continueIn(link: selectedID, inTool: tool, mutation: .preview)
            guard selectedLinkID == selectedID, requestNumber == request,
                  selectedLink?.sides[tool] != nil else { return }
            plan = result
            errorNote = nil
        } catch let error as EngineCommandError {
            guard requestNumber == request else { return }
            errorNote = error.note
        } catch {
            guard requestNumber == request else { return }
            errorNote = nil
        }
    }
}
