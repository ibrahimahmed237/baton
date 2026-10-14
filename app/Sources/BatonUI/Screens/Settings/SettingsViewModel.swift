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
    private var revision = 0
    private var gate = ConfirmationGate()
    private var pendingDefaults: [SettingsChoice] = []
    public var restoringDefaults: Bool { !pendingDefaults.isEmpty }
    public var displayReceipt: PlanDisplayReceipt { PlanDisplayReceipt(planID: "settings", revision: revision, notes: displayedNotes) }
    public var displayedNotes: [Note] {
        var visible: [Note] = []
        for id in ["screen.settings", "screen.setup", "settings.reset", "settings.preview"] {
            if let n = note(id) { visible.append(n) }
        }
        if settings != nil {
            visible += disclosureNotes
            for id in ["settings.appearance", "settings.sync", "settings.chats", "settings.glass_help", "settings.apply", "settings.on_button", "settings.automatic", "settings.ask", "settings.by_time", "screen.theme.system", "screen.theme.light", "screen.theme.graphite"] {
                if let n = note(id) { visible.append(n) }
            }
            for choice in SettingsChoice.all {
                guard let label = note("settings." + choice.key) else { continue }
                visible.append(label)
                if let n = defaultNote(choice.key) { visible.append(n) }
                if case .toggle = choice.kind, let n = note(value(choice.key) == "true" ? "settings.on" : "settings.off") { visible.append(n) }
            }
        }
        if saved, let n = note("settings.saved") { visible.append(n) }
        if let n = errorNote ?? ((saveFailed || loadFailed) && !loading ? note("settings.error") : nil) { visible.append(n) }
        if settings == nil {
            if errorNote == nil, let n = emptyNote { visible.append(n) }
            if loadFailed, let n = note("screen.refresh") { visible.append(n) }
        }
        return visible
    }

    public var disclosureNotes: [Note] {
        let known = Set(SettingsChoice.all.map { "settings." + $0.key } + ["settings.default", "settings.appearance", "settings.sync", "settings.chats", "settings.reset", "settings.glass_help", "settings.apply", "settings.on", "settings.off", "settings.on_button", "settings.automatic", "settings.ask", "settings.by_time", "screen.theme.system", "screen.theme.light", "screen.theme.graphite", "settings.saved", "settings.error", "settings.invalid", "settings.loading", "settings.preview", "screen.settings", "screen.setup", "screen.refresh"])
        return notes.filter { !known.contains($0.id) }
    }
    public var canSet: Bool { settings != nil && !loading && !saving && gate.permits(displayedNotes, identity: displayReceipt.identity) }
    public func didDisplay(_ receipt: PlanDisplayReceipt) {
        guard receipt == displayReceipt else { return }
        objectWillChange.send(); gate.markDisplayed(displayedNotes, identity: receipt.identity)
    }
    public var engineTheme: Theme { AppearanceMode(rawValue: settings?.theme ?? "system")?.resolve(system: appearance.systemTheme) ?? appearance.systemTheme }
    public var engineGlass: Double { settings?.glass ?? 62 }

    public init(engine: any EngineClient, appearance: ThemePreference) {
        self.engine = engine; self.appearance = appearance
    }
    public var emptyNote: Note? { SetupPresentation.empty }
    public func makeSetupModel() -> SetupViewModel { SetupViewModel(engine: engine) }
    public func note(_ id: String) -> Note? { notes.first { $0.id == id } }
    public func defaultNote(_ key: String) -> Note? {
        notes.first { $0.id == "settings.default" && $0.values["key"] == .string(key) }
    }
    /// Reads the actual shared appearance choice as well as backend settings.
    public func value(_ key: String) -> String {
        return settings?.value(for: key) ?? ""
    }
    public func load() async {
        guard !loading, !saving else { return }
        revision += 1; gate = ConfirmationGate(); pendingDefaults = []
        loading = true; saved = false; loadFailed = false
        defer { loading = false }
        do {
            let result = try await engine.settingsGet()
            settings = result.settings; notes = result.notes ?? []; errorNote = nil
        } catch let error as EngineCommandError { errorNote = error.note ?? SetupPresentation.failure; loadFailed = true }
        catch { errorNote = SetupPresentation.failure; loadFailed = true }
    }
    /// Keeps the previous value and app appearance if validation or saving fails.
    public func set(_ key: String, value: String) async {
        guard let current = settings, canSet, !restoringDefaults else { return }
        do { _ = try current.changing(key: key, to: value) }
        catch { errorNote = note(key == "brief_threshold_tokens" ? "settings.invalid" : "settings.error"); saved = false; saveFailed = true; return }
        saving = true; saved = false; saveFailed = false; errorNote = nil
        defer { saving = false }
        _ = await write(key, value: value)
        revision += 1; gate = ConfirmationGate()
    }
    private func write(_ key: String, value: String) async -> Bool {
        do {
            // The compatibility argument is ignored by the immediate settings transport.
            let result = try await engine.settingsSet(key: key, value: value, mutation: .preview)
            settings = result.settings
            // Set receipts may contain only the saved note; retain current engine labels.
            if let next = result.notes {
                for note in next {
                    notes.removeAll { $0.id == note.id && $0.values["key"] == note.values["key"] }
                    notes.append(note)
                }
            }
            saved = true; return true
        } catch let error as EngineCommandError { errorNote = error.note ?? SetupPresentation.failure; saved = false; saveFailed = true }
        catch { errorNote = note("settings.error"); saved = false; saveFailed = true }
        return false
    }
    /// Each default write waits for the new current display receipt before proceeding.
    public func restoreDefaults() async {
        guard canSet, !restoringDefaults else { return }
        pendingDefaults = SettingsChoice.all
        await continueRestoringDefaults()
    }
    public func continueRestoringDefaults() async {
        guard canSet, let choice = pendingDefaults.first else { return }
        saving = true; saved = false; saveFailed = false; errorNote = nil
        defer { saving = false }
        pendingDefaults.removeFirst()
        if !(await write(choice.key, value: choice.defaultValue)) { pendingDefaults = [] }
        revision += 1; gate = ConfirmationGate()
    }
}
