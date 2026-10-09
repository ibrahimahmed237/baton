import AppKit
import SwiftUI
import BatonKit
import BatonUI

/// A fixture-backed menu-bar app and window, built directly by Swift Package Manager.
@main
struct BatonApp: App {
    @NSApplicationDelegateAdaptor(BatonAppDelegate.self) private var appDelegate
    @StateObject private var state: PopoverViewModel
    @StateObject private var windowState: WindowViewModel
    @State private var menuBarInserted = true
    @Environment(\.openWindow) private var openWindow
    @Environment(\.colorScheme) private var colorScheme

    init() {
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        _state = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: fixtures, states: ["links": "d2_in_sync", "suggestions": "d2_in_sync", "continue": "d2_in_sync"])))
        _windowState = StateObject(wrappedValue: WindowViewModel(engine: FixtureEngine(directory: fixtures, state: "d3_filled")))
    }

    var body: some Scene {
        MenuBarExtra(isInserted: $menuBarInserted) {
            PopoverView(model: state, linkRecent: { windowState.navigate(to: .suggestions); openWindow(id: "links") }).task { await state.refresh() }
        } label: {
            if CommandLine.arguments.contains("--review-label") {
                Text(Image(systemName: "link")) + Text(" Baton")
            } else if let image = BatonMenuIcon.nativeImage(needsDecision: state.needsDecision,
                                                    theme: colorScheme == .dark ? .graphite : .light) {
                Image(nsImage: image)
            } else {
                Image(systemName: "link")
            }
        }
        .menuBarExtraStyle(.window)
        Window("Baton", id: "links") {
            WindowView(model: windowState).task { await windowState.refresh() }
        }.defaultSize(width: 1000, height: 600).windowResizability(.contentMinSize).windowStyle(.hiddenTitleBar)
    }
}

/// Configures the launched application and opens a fixture window when requested for review.
@MainActor
private final class BatonAppDelegate: NSObject, NSApplicationDelegate {
    private var reviewWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.accessory)
        guard CommandLine.arguments.contains("--review-window") else { return }
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        let model = WindowViewModel(engine: FixtureEngine(directory: fixtures, state: "d3_filled"))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 600),
                              styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        BatonWindowConfiguration.apply(to: window)
        window.title = "Baton"
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: WindowView(model: model).task { await model.refresh() })
        reviewWindow = window
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
}
