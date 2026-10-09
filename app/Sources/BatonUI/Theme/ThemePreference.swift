import AppKit
import Combine
import Foundation
import SwiftUI
import BatonKit

/// The saved appearance choice, using the engine contract's values.
public enum AppearanceMode: String, CaseIterable, Sendable {
    case light, graphite, system
    /// Resolves System against macOS while explicit choices stay fixed.
    public func resolve(system: Theme) -> Theme {
        switch self { case .light: return .light; case .graphite: return .graphite; case .system: return system }
    }
}

/// Shares the local app preference across the window and popover without changing macOS.
@MainActor public final class ThemePreference: ObservableObject {
    public static let shared: ThemePreference = {
        let preference = ThemePreference(storedValue: UserDefaults.standard.string(forKey: "baton.ui.theme"),
            systemTheme: NSApplication.shared.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? .graphite : .light,
            save: { UserDefaults.standard.set($0, forKey: "baton.ui.theme") },
            storedGlass: UserDefaults.standard.object(forKey: "baton.ui.glass") as? Double,
            saveGlass: { UserDefaults.standard.set($0, forKey: "baton.ui.glass") })
        preference.observeSystemAppearance()
        return preference
    }()
    @Published public private(set) var mode: AppearanceMode
    @Published public private(set) var theme: Theme
    @Published public private(set) var systemTheme: Theme
    @Published public private(set) var glass: Double
    private let saveGlass: (Double) -> Void
    private let save: (String) -> Void
    private var appearanceObservation: NSKeyValueObservation?

    /// Uses injectable persistence so fixture tests never touch real preferences.
    public init(storedValue: String? = nil, systemTheme: Theme = .light, save: @escaping (String) -> Void = { _ in },
                storedGlass: Double? = nil, saveGlass: @escaping (Double) -> Void = { _ in }) {
        let choice = AppearanceMode(rawValue: storedValue ?? "") ?? .system
        glass = storedGlass.map { $0.isFinite ? min(95, max(40, $0)) : 62 } ?? 62
        self.saveGlass = saveGlass
        mode = choice; self.systemTheme = systemTheme; theme = choice.resolve(system: systemTheme); self.save = save
    }

    /// Saves the chosen app appearance and updates all observing surfaces.
    public func choose(_ choice: AppearanceMode) {
        guard mode != choice else { return }
        mode = choice; save(choice.rawValue); resolve()
    }

    /// Changes local surface opacity without altering macOS transparency preferences.
    public func chooseGlass(_ value: Double) {
        guard value.isFinite else { return }
        let clamped = min(95, max(40, value))
        guard glass != clamped else { return }
        glass = clamped; saveGlass(clamped)
    }

    /// Follows macOS only when the saved choice is System.
    public func updateSystemTheme(_ value: Theme) {
        systemTheme = value; resolve()
    }
    private func resolve() {
        let resolved = mode.resolve(system: systemTheme)
        if theme != resolved { theme = resolved }
    }
    private func observeSystemAppearance() {
        appearanceObservation = NSApplication.shared.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, change in
            let value: Theme = change.newValue?.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? .graphite : .light
            Task { @MainActor [weak self] in self?.updateSystemTheme(value) }
        }
    }
}

/// A visible appearance choice with wording supplied by the catalogue.
public struct ThemeSelector: View {
    @Environment(\.batonTheme) private var theme
    @ObservedObject private var preference: ThemePreference
    private let notes: [Note]
    /// Receives the shared preference and the engine's presentation labels.
    public init(preference: ThemePreference, notes: [Note]) { self.preference = preference; self.notes = notes }
    public var body: some View {
        if let heading = notes.first(where: { $0.id == "screen.theme" }) {
            VStack(alignment: .leading, spacing: 8) {
                Label(heading.text, systemImage: "circle.lefthalf.filled")
                    .font(.caption).foregroundStyle(theme.secondaryText)
                HStack(spacing: 3) {
                    ForEach(AppearanceMode.allCases, id: \.rawValue) { mode in
                        if let label = notes.first(where: { $0.id == "screen.theme." + mode.rawValue }) {
                            Button { preference.choose(mode) } label: {
                                Text(label.text).font(.system(size: 11, weight: preference.mode == mode ? .semibold : .regular))
                                    .frame(maxWidth: .infinity).padding(.vertical, 7)
                                    .background(preference.mode == mode ? theme.colour(for: .action).opacity(0.16) : .clear,
                                                in: RoundedRectangle(cornerRadius: 7))
                                    .contentShape(Rectangle())
                            }.buttonStyle(.plain)
                                .accessibilityAddTraits(preference.mode == mode ? .isSelected : [])
                        }
                    }
                }.padding(3).background(theme.sidebar.opacity(0.3), in: RoundedRectangle(cornerRadius: 10))
            }
        }
    }
}

/// Keeps window identity and selection stable as the shared palette changes.
struct AppearanceWindowContent: View {
    @ObservedObject var preference: ThemePreference
    let model: WindowViewModel
    var body: some View {
        WindowView(model: model, appearance: preference).batonTheme(preference.theme, glass: preference.glass)
            .task { await model.refresh() }
    }
}
