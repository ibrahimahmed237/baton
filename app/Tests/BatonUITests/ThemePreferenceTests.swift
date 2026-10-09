import AppKit
import SwiftUI
import Testing
import BatonKit
@testable import BatonUI

@Suite(.serialized)
struct ThemePreferenceTests {
    @MainActor @Test
    func savesExplicitAppearanceAndOnlySystemFollowsMacOS() {
        var saved: String?
        let preference = ThemePreference(systemTheme: .graphite, save: { saved = $0 })
        #expect(preference.mode == .system); #expect(preference.theme == .graphite)
        preference.choose(.light)
        #expect(saved == "light"); #expect(preference.theme == .light)
        preference.updateSystemTheme(.graphite)
        #expect(preference.theme == .light)
        let reopened = ThemePreference(storedValue: saved, systemTheme: .graphite)
        #expect(reopened.mode == .light); #expect(reopened.theme == .light)
        preference.choose(.graphite); preference.updateSystemTheme(.light)
        #expect(saved == "graphite"); #expect(preference.theme == .graphite)
        preference.choose(.system)
        #expect(saved == "system"); #expect(preference.theme == .light)
        preference.updateSystemTheme(.graphite)
        #expect(preference.theme == .graphite)
        let invalid = ThemePreference(storedValue: "unrecognized", systemTheme: .graphite)
        #expect(invalid.mode == .system); #expect(invalid.theme == .graphite)
    }

    @MainActor @Test
    func switchingAppearanceKeepsWindowModelAndSelection() async throws {
        let model = WindowViewModel(engine: FixtureEngine(directory: ComponentTests.root.appendingPathComponent("Fixtures"), state: "d3_filled"))
        await model.refresh(); model.select(.link(3))
        let preference = ThemePreference(systemTheme: .light)
        let controller = BatonMainWindowController(model: model, appearance: preference)
        let window = try #require(controller.window)
        let content = window.contentView
        window.setFrameOrigin(NSPoint(x: -10000, y: -10000))
        window.orderBack(nil)
        defer { window.close() }
        window.contentView?.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(200))
        let frame = window.frame
        let flags = window.styleMask
        for choice in AppearanceMode.allCases {
            preference.choose(choice)
            window.contentView?.layoutSubtreeIfNeeded()
            try await Task.sleep(for: .milliseconds(100))
            #expect(window.appearance?.name == (preference.theme == .graphite ? .darkAqua : .aqua))
            #expect(window.backgroundColor == NSColor(preference.theme.background))
            #expect(controller.window === window)
            #expect(controller.model === model)
            #expect(window.contentView === content)
            #expect(model.selection == .link(3))
            #expect(window.frame == frame)
            #expect(window.styleMask == flags)
        }
        preference.choose(.system)
        preference.updateSystemTheme(.graphite)
        window.contentView?.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(100))
        #expect(window.appearance?.name == .darkAqua)
        #expect(window.backgroundColor == NSColor(Theme.graphite.background))
        #expect(window.contentView === content && model.selection == .link(3))
        let directory = ComponentTests.root.appendingPathComponent("Snapshots")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        for choice in AppearanceMode.allCases {
            preference.choose(choice)
            let renderer = ImageRenderer(content: ThemeSelector(preference: preference, notes: model.notes)
                .frame(width: 205).padding(12).background(preference.theme.background).batonTheme(preference.theme))
            renderer.scale = 2
            let image = try #require(renderer.nsImage)
            let tiff = try #require(image.tiffRepresentation)
            let bitmap = try #require(NSBitmapImageRep(data: tiff))
            let png = try #require(bitmap.representation(using: .png, properties: [:]))
            #expect(!png.isEmpty)
            try png.write(to: directory.appendingPathComponent("UI7-selector-\(choice.rawValue).png"))
        }
    }
}
