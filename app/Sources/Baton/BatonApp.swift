import AppKit
import SwiftUI
import BatonKit
import BatonUI

/// A fixture-backed menu-bar app and window, built directly by Swift Package Manager.
@main
struct BatonApp: App {
    @StateObject private var state: PopoverViewModel
    @StateObject private var windowState: WindowViewModel
    @Environment(\.openWindow) private var openWindow

    init() {
        NSApplication.shared.setActivationPolicy(.accessory)
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        _state = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: fixtures, states: ["links": "d2_in_sync", "suggestions": "d2_in_sync", "continue": "d2_in_sync"])))
        _windowState = StateObject(wrappedValue: WindowViewModel(engine: FixtureEngine(directory: fixtures, state: "d3_filled")))
    }

    var body: some Scene {
        MenuBarExtra {
            PopoverView(model: state, linkRecent: { windowState.navigate(to: .suggestions); openWindow(id: "links") }).task { await state.refresh() }
        } label: {
            BatonMenuIcon(needsDecision: state.needsDecision)
        }
        .menuBarExtraStyle(.window)
        Window("Baton", id: "links") {
            WindowView(model: windowState).task { await windowState.refresh() }
        }
    }
}
