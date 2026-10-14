import Foundation
import BatonKit

/// The engine binds each alternative to a stored plan; never reconstruct its request.
struct BoundPlanOffer: Equatable, Sendable {
    let command: String
    let planID: String
    static func offered(by note: Note, button: NoteButton) -> BoundPlanOffer? {
        let key: String
        let command: String
        switch button.id {
        case "confirm" where note.id == "relaunch.order":
            key = "relaunch_plan_id"; command = "relaunch"
        case "close_sync_reopen": key = "relaunch_plan_id"; command = "relaunch"
        case "attach":
            key = "attach_plan_id"
            guard case .string(let value) = note.values["attach_command"] else { return nil }; command = value
        case "sync_relaunch_later":
            key = "sync_relaunch_later_plan_id"
            guard case .string(let value) = note.values["sync_relaunch_later_command"] else { return nil }; command = value
        default: return nil
        }
        guard note.buttons.contains(button), case .string(let id) = note.values[key], !id.isEmpty,
              ["relaunch", "link", "copy", "relink", "sync", "undo", "brief"].contains(command) else { return nil }
        return BoundPlanOffer(command: command, planID: id)
    }
    func run(_ engine: any EngineClient) async throws -> Plan {
        guard let transport = engine as? any EngineTransport else { throw CancellationError() }
        return try await transport.response(command: command, arguments: ["--confirm", planID], as: Plan.self)
    }
}
