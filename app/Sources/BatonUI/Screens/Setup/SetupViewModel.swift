import Foundation
import Combine
import BatonKit

/// Installation is offered only by current engine findings; human fixes remain instructions.
@MainActor public final class SetupViewModel: ObservableObject {
    @Published public private(set) var result: SetupResult?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    private let engine: any EngineClient
    private var revision = 0
    private var gate = ConfirmationGate()
    public init(engine: any EngineClient) { self.engine = engine }
    public var emptyNote: Note? { SetupPresentation.empty }
    public func label(_ id: String) -> Note? { result?.notes?.first { $0.id == id } }
    public func findings(for tool: SetupTool) -> [SetupFinding] { tool.findings }
    public var tools: [SetupTool] { result?.tools ?? [] }
    public var notes: [Note] {
        displayedPlanNotes(Plan(planID: "setup", applied: false, steps: [], decisionNeeded: false,
                               notes: (result?.notes ?? []).filter { $0.id == "setup.check_again" || $0.id.hasPrefix("setup.category.") } + tools.flatMap { $0.findings.map(\.note) }))
    }
    public var displayReceipt: PlanDisplayReceipt { PlanDisplayReceipt(planID: "setup", revision: revision, notes: notes) }
    public func didDisplay(_ receipt: PlanDisplayReceipt) {
        guard receipt == displayReceipt else { return }
        objectWillChange.send(); gate.markDisplayed(notes, identity: receipt.identity)
    }
    public func canInstall(tool: String, button: NoteButton) -> Bool {
        guard !busy, button.id == "install_hooks", let target = tools.first(where: { $0.tool == tool }), target.installed,
              target.findings.contains(where: { !$0.ok && $0.id == "hooks" && $0.note.id == "setup.hooks" && $0.note.buttons.contains(button) }),
              gate.permits(notes, identity: displayReceipt.identity) else { return false }
        return true
    }
    public func load() async {
        guard !busy else { return }
        busy = true; revision += 1; gate = ConfirmationGate(); errorNote = nil
        defer { busy = false }
        do { result = try await engine.setup() }
        catch let error as EngineCommandError { result = nil; errorNote = error.note ?? SetupPresentation.failure }
        catch { errorNote = SetupPresentation.failure }
    }
    public func install(tool: String, button: NoteButton) async {
        guard canInstall(tool: tool, button: button), let transport = engine as? any EngineTransport else { return }
        busy = true; defer { busy = false }
        do {
            // Immediate install commands take neither dry-run nor confirm.
            result = try await transport.response(command: "setup-install", arguments: ["install", "--tool", tool], as: SetupResult.self)
        } catch let error as EngineCommandError { errorNote = error.note ?? SetupPresentation.failure }
        catch { errorNote = SetupPresentation.failure }
        revision += 1; gate = ConfirmationGate()
    }
}
