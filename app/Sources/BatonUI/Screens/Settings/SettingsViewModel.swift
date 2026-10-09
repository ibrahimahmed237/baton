import Foundation
import Combine
import BatonKit

/// Displays and saves the contract's choices; configuration never writes a chat.
@MainActor public final class SettingsViewModel: ObservableObject {
    @Published public private(set) var settings: Settings?
    @Published public private(set) var notes: [Note] = []
    @Published public private(set) var loading = false
    @Published public private(set) var saving = false
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var saved = false
    @Published public private(set) var loadFailed = false
    @Published public private(set) var saveFailed = false
    private let engine: any EngineClient
    private let appearance: ThemePreference
    public init(engine: any EngineClient, appearance: ThemePreference) {
        self.engine = engine; self.appearance = appearance
    }
    public func note(_ id: String) -> Note? { notes.first { $0.id == id } }
    public func defaultNote(_ key: String) -> Note? {
        notes.first { $0.id == "settings.default" && $0.values["key"] == .string(key) }
    }
    /// Reads the actual shared appearance choice as well as backend settings.
    public func value(_ key: String) -> String {
        if key == "theme" { return appearance.mode.rawValue }
        if key == "glass" { return String(appearance.glass) }
        return settings?.value(for: key) ?? ""
    }
    public func load() async {
        guard !loading, !saving else { return }
        loading = true; saved = false; loadFailed = false
        defer { loading = false }
        do {
            let result = try await engine.settingsGet()
            settings = result.settings; notes = result.notes ?? []; errorNote = nil
        } catch let error as EngineCommandError { errorNote = error.note; loadFailed = true }
        catch { errorNote = note("settings.error"); loadFailed = true }
    }
    /// Keeps the previous value and app appearance if validation or saving fails.
    public func set(_ key: String, value: String) async {
        guard let current = settings, !saving, !loading else { return }
        do { _ = try current.changing(key: key, to: value) }
        catch { errorNote = note(key == "brief_threshold_tokens" ? "settings.invalid" : "settings.error"); saved = false; saveFailed = true; return }
        saving = true; saved = false; saveFailed = false; errorNote = nil
        defer { saving = false }
        _ = await write(key, value: value)
    }
    private func write(_ key: String, value: String) async -> Bool {
        do {
            // The compatibility argument is ignored by the immediate settings transport.
            let result = try await engine.settingsSet(key: key, value: value, mutation: .preview)
            settings = result.settings
            if let next = result.notes { notes = next }
            if key == "theme", let mode = AppearanceMode(rawValue: result.settings.theme) { appearance.choose(mode) }
            if key == "glass" { appearance.chooseGlass(result.settings.glass) }
            saved = true; return true
        } catch let error as EngineCommandError { errorNote = error.note; saved = false; saveFailed = true }
        catch { errorNote = note("settings.error"); saved = false; saveFailed = true }
        return false
    }
    /// Restores each contract default; stops on a failed write and preserves accepted values.
    public func restoreDefaults() async {
        guard settings != nil, !saving, !loading else { return }
        saving = true; saved = false; saveFailed = false; errorNote = nil
        defer { saving = false }
        for choice in SettingsChoice.all {
            guard await write(choice.key, value: choice.defaultValue) else { return }
        }
    }
}
