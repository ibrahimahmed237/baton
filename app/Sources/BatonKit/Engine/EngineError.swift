import Foundation

/// An engine refusal or failure, preserving the catalogue note for display.
public struct EngineCommandError: Error, Codable, Equatable, Sendable {
    public var kind: String?
    public var note: Note?

    /// Creates a failure with the note supplied by the engine.
    public init(kind: String? = nil, note: Note? = nil) {
        self.kind = kind
        self.note = note
    }
}

/// A failed process without a structured engine error on stdout.
public struct EngineProcessError: Error, Equatable, Sendable {
    public let status: Int32
    public let stderr: String
}

private struct ErrorEnvelope: Decodable {
    let error: EngineCommandError
}

func checkEngineError(_ data: Data) throws {
    // Inspect the envelope first: malformed success data must remain a decoding error.
    if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
       object["error"] != nil {
        throw try JSONDecoder().decode(ErrorEnvelope.self, from: data).error
    }
}

func decodeResponse<Result: Decodable>(_ type: Result.Type, from data: Data) throws -> Result {
    try checkEngineError(data)
    return try JSONDecoder().decode(type, from: data)
}
