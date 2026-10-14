import Foundation

/// Saves preview configuration only, while all chat responses remain hand-made fixtures.
public actor SettingsFixtureEngine: EngineTransport {
    private let base: FixtureEngine
    private var settings: Settings?
    private let save: @Sendable (Settings) throws -> Void
    public init(base: FixtureEngine, savedSettings: Settings? = nil, save: @escaping @Sendable (Settings) throws -> Void = { _ in }) {
        self.base = base; self.settings = savedSettings; self.save = save
    }
    /// Handles immediate settings get/set without touching chat files or other app configuration.
    public func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        guard command == "settings-get" || command == "settings-set" else {
            return try await base.response(command: command, arguments: arguments, as: type)
        }
        let seed = try await base.settingsGet()
        let current = settings ?? seed.settings
        if command == "settings-set" {
            guard arguments.count == 3, arguments[0] == "set" else { throw SettingsValueError.invalidValue }
            let updated = try current.changing(key: arguments[1], to: arguments[2])
            try save(updated)
            settings = updated
        } else if settings == nil { settings = current }
        let data = try JSONEncoder().encode(SettingsGetResult(settings: settings ?? current, notes: seed.notes))
        return try decodeResponse(type, from: data)
    }
}
