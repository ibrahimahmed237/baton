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
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    init() {
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        _state = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: fixtures, states: ["links": "d2_in_sync", "suggestions": "d2_in_sync", "continue": "d2_in_sync"])))
    }

    var body: some Scene {
        MenuBarExtra(isInserted: $menuBarInserted) {
            PopoverView(model: state, linkRecent: { appDelegate.showMainWindow(section: .suggestions) })
                .batonTheme(colorScheme == .dark ? .graphite : .light)
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
        return BatonMainWindowController(model: WindowViewModel(engine: FixtureEngine(directory: fixtures, state: "d3_filled")))
    }()

    private var appearanceObservation: NSKeyValueObservation?
    private var displayOptionsObserver: NSObjectProtocol?

    func applicationDidFinishLaunching(_ notification: Notification) {
        updateAppearance(NSApplication.shared.effectiveAppearance)
        appearanceObservation = NSApplication.shared.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, change in
            let theme: Theme = change.newValue?.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? .graphite : .light
            Task { @MainActor [weak self] in self?.applyTheme(theme) }
        }
        displayOptionsObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
            object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor [weak self] in
                    self?.updateApplicationIcon(NSApplication.shared.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? .graphite : .light)
                }
            }
        NSApplication.shared.setActivationPolicy(.regular)
        showMainWindow()
    }

    private func updateAppearance(_ appearance: NSAppearance) {
        applyTheme(appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? .graphite : .light)
    }

    private func applyTheme(_ theme: Theme) {
        updateApplicationIcon(theme)
        mainWindow.setTheme(theme)
    }

    private func updateApplicationIcon(_ theme: Theme) {
        if let icon = BatonBrand.applicationIcon(theme: theme) { NSApplication.shared.applicationIconImage = icon }
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
