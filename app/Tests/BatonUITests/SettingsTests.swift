import AppKit
import Foundation
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

@Suite(.serialized)
struct SettingsTests {
    private func engine(save: @escaping @Sendable (BatonKit.Settings) throws -> Void = { _ in }) -> SettingsFixtureEngine {
        SettingsFixtureEngine(base: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures")), save: save)
    }
    @MainActor @Test func allContractChoicesSaveRestoreAndUpdateSharedAppearance() async throws {
        let backend = engine()
        let preference = ThemePreference(systemTheme: .light)
        let model = SettingsViewModel(engine: backend, appearance: preference)
        await model.load()
        #expect(model.settings != nil)
        #expect(SettingsChoice.all.count == 10)
        let changes: [String: String] = ["theme": "graphite", "glass": "80", "notice_on_attach": "false",
            "offer_relaunch": "false", "add_to_idle_claude": "automatic", "offer_switch_at_limit": "false",
            "merge": "by_time", "brief_threshold_tokens": "200000", "hide_script_chats": "false", "title_tag": "false"]
        for choice in SettingsChoice.all {
            #expect(model.note("settings." + choice.key) != nil)
            #expect(model.defaultNote(choice.key) != nil)
            let changed = try #require(changes[choice.key])
            await model.set(choice.key, value: changed)
            #expect(model.errorNote == nil && model.saved)
            #expect(model.value(choice.key) == changed || (choice.key == "glass" && model.value(choice.key) == "80.0"))
        }
        #expect(preference.theme == .graphite && preference.glass == 80)
        let second = SettingsViewModel(engine: backend, appearance: preference)
        await second.load()
        #expect(second.settings == model.settings)
        preference.choose(.light)
        #expect(second.value("theme") == "light")
        await model.restoreDefaults()
        #expect(model.settings == (try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures")).settingsGet()).settings)
        #expect(preference.mode == .system && preference.theme == .light && preference.glass == 62)
    }
    @MainActor @Test func invalidInputsAndFailedSavePreserveSettingsAndAppearance() async throws {
        let preference = ThemePreference(systemTheme: .light)
        let model = SettingsViewModel(engine: engine(), appearance: preference)
        await model.load()
        let before = model.settings
        for (key, value) in [("glass", "39"), ("glass", "96"), ("glass", "nan"),
            ("theme", "orange"), ("merge", "automatic"), ("notice_on_attach", "yes"),
            ("brief_threshold_tokens", "0"), ("brief_threshold_tokens", "2.5"), ("brief_threshold_tokens", "-1")] {
            await model.set(key, value: value)
            #expect(model.settings == before && model.errorNote != nil && !model.saved)
            #expect(preference.mode == .system && preference.glass == 62)
        }
        let failing = SettingsViewModel(engine: engine(save: { _ in throw SettingsValueError.invalidValue }), appearance: preference)
        await failing.load()
        await failing.set("theme", value: "graphite")
        #expect(failing.settings == before && failing.errorNote?.id == "settings.error")
        #expect(preference.mode == .system)
        await failing.restoreDefaults()
        #expect(failing.errorNote != nil && !failing.saved && !failing.saving)
    }
    @MainActor @Test func resetStopsOnFailureEvenWhenPresentationNotesAreMissing() async {
        let engine = NoNotesSettingsEngine()
        let model = SettingsViewModel(engine: engine, appearance: ThemePreference())
        await model.load()
        #expect(model.notes.isEmpty)
        await model.restoreDefaults()
        let writes = await engine.writes
        #expect(writes == ["theme", "glass"])
        #expect(!model.saved && model.saveFailed && model.errorNote == nil)
    }
    @MainActor @Test func quitWordingIsAvailableBeforeLoadAndAfterEngineFailure() async throws {
        let window = WindowViewModel(engine: FailingWindowEngine())
        let notes = BatonQuitConfirmation.loadNotes(from: ComponentTests.root.appendingPathComponent("Fixtures"))
        let title = try #require(notes.first { $0.id == "quit.title" })
        let message = try #require(notes.first { $0.id == "quit.confirm" })
        let actions = try #require(notes.first { $0.id == "quit.actions" })
        let gate = BatonQuitConfirmation()
        let popover = PopoverViewModel(engine: FailingWindowEngine())
        for id in ["screen.quit", "screen.open_window"] {
            #expect(popover.applicationNote(id, fallback: notes) != nil)
        }
        await popover.refresh()
        #expect(popover.loadFailed)
        for id in ["screen.quit", "screen.open_window"] {
            #expect(popover.applicationNote(id, fallback: notes) != nil)
        }
        #expect(window.notes.isEmpty)
        let before = gate.request(title: title, message: message, actions: actions) { _, _, _ in "quit" }
        #expect(before)
        await window.refresh()
        #expect(window.notes.isEmpty && window.loadFailed)
        let after = gate.request(title: title, message: message, actions: actions) { _, _, _ in "quit" }
        #expect(after)
    }
    @MainActor @Test func previewSettingsPersistWithoutChangingPackagedFixtures() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let saved = directory.appendingPathComponent("settings.json")
        let fixture = ComponentTests.root.appendingPathComponent("Fixtures/settings-get.sample.json")
        let unchanged = try Data(contentsOf: fixture)
        let backend = engine(save: { value in try JSONEncoder().encode(value).write(to: saved, options: .atomic) })
        _ = try await backend.settingsSet(key: "merge", value: "by_time")
        let persisted = try JSONDecoder().decode(BatonKit.Settings.self, from: Data(contentsOf: saved))
        let reopened = SettingsFixtureEngine(base: FixtureEngine(directory: fixture.deletingLastPathComponent()), savedSettings: persisted)
        let response = try await reopened.settingsGet()
        #expect(response.settings.merge == "by_time")
        #expect(try Data(contentsOf: fixture) == unchanged)
    }
    @MainActor @Test func settingsSnapshotsIncludeEveryControlInBothThemes() async throws {
        let output = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for theme in Theme.allCases {
            let preference = ThemePreference(storedValue: theme.rawValue, systemTheme: theme)
            let model = SettingsViewModel(engine: engine(), appearance: preference)
            await model.load()
            let renderer = ImageRenderer(content: SettingsView(model: model, appearance: preference)
                .environment(\.batonSnapshotPresentation, true).padding(24).frame(width: 800).background(theme.background).batonTheme(theme))
            renderer.scale = 1
            let image = try #require(renderer.nsImage)
            #expect(image.size.height > 650)
            let tiff = try #require(image.tiffRepresentation)
            let pixels = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(pixels.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty)
            try png.write(to: output.appendingPathComponent("UI8-settings-\(theme.rawValue).png"))
        }
    }
    @MainActor @Test func quitRequiresAnExplicitConfirmationAndRejectsReentry() async throws {
        let links = try await FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures")).links()
        let title = try #require(links.notes.first { $0.id == "quit.title" })
        let message = try #require(links.notes.first { $0.id == "quit.confirm" })
        let actions = try #require(links.notes.first { $0.id == "quit.actions" })
        let gate = BatonQuitConfirmation()
        let cancelled = gate.request(title: title, message: message, actions: actions) { _, _, buttons in
            #expect(buttons.map(\.id) == ["cancel", "quit"])
            let reentrant = gate.request(title: title, message: message, actions: actions) { _, _, _ in "quit" }
            #expect(!reentrant)
            return "cancel"
        }
        #expect(!cancelled)
        #expect(!gate.request(title: title, message: message, actions: actions) { _, _, _ in nil })
        #expect(gate.request(title: title, message: message, actions: actions) { _, _, _ in "quit" })
    }
}


private struct FailingWindowEngine: EngineTransport {
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result { throw SettingsValueError.invalidValue }
}

private actor NoNotesSettingsEngine: EngineTransport {
    let base = SettingsFixtureEngine(base: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures")))
    var writes: [String] = []
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        if command == "settings-set" {
            writes.append(arguments[1])
            if arguments[1] == "glass" { throw SettingsValueError.invalidValue }
        }
        var result: SettingsGetResult = try await base.response(command: command, arguments: arguments, as: SettingsGetResult.self)
        result.notes = nil
        return try JSONDecoder().decode(type, from: JSONEncoder().encode(result))
    }
}
