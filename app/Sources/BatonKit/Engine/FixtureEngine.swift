import Foundation

/// Loads hand-made responses from a caller-selected fixture directory.
public struct FixtureEngine: EngineTransport {
    public let directory: URL
    public let state: String
    public let states: [String: String]

    /// Selects a default state and optional per-command fixture states.
    public init(directory: URL, state: String = "sample", states: [String: String] = [:]) {
        self.directory = directory
        self.state = state
        self.states = states
    }

    /// Loads `<command>.<state>.json` and decodes its contract response.
    public func response<Result: Decodable & Sendable>(
        command: String, arguments: [String], as type: Result.Type
    ) async throws -> Result {
        let selectedState = states[command] ?? state
        let url = directory.appendingPathComponent("\(command).\(selectedState).json")
        let data = try Data(contentsOf: url)
        return try decodeResponse(type, from: data)
    }
}
