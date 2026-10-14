import Foundation

/// Mode eligibility and wording belong to the engine, not the picker.
public struct LinkModeOption: Codable, Equatable, Sendable {
    public var mode: String
    public var available: Bool
    public var label: Note
    public var tag: Note?
    public var reason: Note?
    /// Creates an engine-backed presentation value.
    public init(mode: String, available: Bool, label: Note, tag: Note? = nil, reason: Note? = nil) {
        self.mode = mode; self.available = available; self.label = label; self.tag = tag; self.reason = reason
    }
}
