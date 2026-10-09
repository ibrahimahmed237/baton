import AppKit
import SwiftUI
import BatonKit
import BatonUI

/// A fixture-backed menu-bar app and window, built directly by Swift Package Manager.
@main
struct BatonApp: App {
    @NSApplicationDelegateAdaptor(BatonAppDelegate.self) private var appDelegate
    private let applicationNotes: [Note]
    @StateObject private var state: PopoverViewModel
    @StateObject private var appearance = ThemePreference.shared
    @State private var menuBarInserted = true
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    init() {
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        applicationNotes = BatonQuitConfirmation.loadNotes(from: fixtures)
        _state = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: fixtures, states: ["links": "d2_in_sync", "suggestions": "d2_in_sync", "continue": "d2_in_sync"])))
    }

    var body: some Scene {
        MenuBarExtra(isInserted: $menuBarInserted) {
            PopoverView(model: state, linkRecent: { appDelegate.showMainWindow(section: .suggestions) },
                        openWindow: { appDelegate.showMainWindow() }, quit: { NSApplication.shared.terminate(nil) }, applicationNotes: applicationNotes)
                .batonTheme(appearance.theme, glass: appearance.glass)
                .task { await state.refresh() }
        } label: {
            if CommandLine.arguments.contains("--review-label") {
                Text("Baton")
            } else if let image = BatonMenuIcon.nativeImage(needsDecision: state.needsDecision,
                                                    theme: colorScheme == .dark ? .graphite : .light,
                                                    reduceTransparency: reduceTransparency) {
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
        let saved = UserDefaults.standard.data(forKey: "baton.fixture.settings").flatMap { try? JSONDecoder().decode(BatonKit.Settings.self, from: $0) }
        let engine = SettingsFixtureEngine(base: FixtureEngine(directory: fixtures, state: "d3_filled",
            states: ["settings-get": "sample", "settings-set": "sample"]), savedSettings: saved,
            save: { value in UserDefaults.standard.set(try JSONEncoder().encode(value), forKey: "baton.fixture.settings") })
        return BatonMainWindowController(model: WindowViewModel(engine: engine))
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let icon = BatonBrand.applicationIcon(theme: .light) { NSApplication.shared.applicationIconImage = icon }
        NSApplication.shared.setActivationPolicy(.regular)
        showMainWindow()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return false
    }

    private lazy var quitNotes = BatonQuitConfirmation.loadNotes(from:
        Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true))
    private let quitConfirmation = BatonQuitConfirmation()
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let notes = quitNotes
        guard let title = notes.first(where: { $0.id == "quit.title" }),
              let message = notes.first(where: { $0.id == "quit.confirm" }),
              let actions = notes.first(where: { $0.id == "quit.actions" }) else { return .terminateCancel }
        return quitConfirmation.request(title: title, message: message, actions: actions) ? .terminateNow : .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func showMainWindow(section: WindowSection? = nil) {
        if let section { mainWindow.model.navigate(to: section) }
        mainWindow.showWindow(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
}
