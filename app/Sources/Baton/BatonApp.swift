import AppKit
import SwiftUI
import BatonKit
import BatonUI

/// A fixture-backed menu-bar app and window, built directly by Swift Package Manager.
@main
struct BatonApp: App {
    @NSApplicationDelegateAdaptor(BatonAppDelegate.self) private var appDelegate
    @StateObject private var state: PopoverViewModel
    @State private var menuBarInserted = true
    @Environment(\.colorScheme) private var colorScheme

    init() {
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        _state = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: fixtures, states: ["links": "d2_in_sync", "suggestions": "d2_in_sync", "continue": "d2_in_sync"])))
    }

    var body: some Scene {
        MenuBarExtra(isInserted: $menuBarInserted) {
            PopoverView(model: state, linkRecent: { appDelegate.showMainWindow(section: .suggestions) }).task { await state.refresh() }
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
    }
}

/// Opens the same main window for launch, Dock reopen and menu-bar actions.
@MainActor
private final class BatonAppDelegate: NSObject, NSApplicationDelegate {
    private lazy var mainWindow: BatonMainWindowController = {
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        return BatonMainWindowController(model: WindowViewModel(engine: FixtureEngine(directory: fixtures, state: "d3_filled")))
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let icon = BatonBrand.nativeIcon() { NSApplication.shared.applicationIconImage = icon }
        NSApplication.shared.setActivationPolicy(.regular)
        showMainWindow()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func showMainWindow(section: WindowSection? = nil) {
        if let section { mainWindow.model.navigate(to: section) }
        mainWindow.showWindow(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
}
