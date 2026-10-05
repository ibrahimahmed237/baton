import SwiftUI

/// The two palettes used by Baton's surfaces and semantic accents.
public enum Theme: String, CaseIterable, Sendable {
    case light, graphite

    public var background: Color { self == .light ? colour(0xf4f5f8) : colour(0x3e4148) }
    public var sidebar: Color { self == .light ? colour(0xffffff) : colour(0x484b52) }
    public var text: Color { self == .light ? colour(0x20242d) : colour(0xffffff) }
    public var secondaryText: Color { self == .light ? colour(0x535967) : colour(0xd5d8e0) }
    public var hairline: Color { text.opacity(0.1) }
    public var scheme: ColorScheme { self == .light ? .light : .dark }

    /// Returns a colour for a meaning, rather than for a particular screen.
    public func colour(for meaning: StateColour) -> Color {
        let light: [StateColour: UInt32] = [.added: 0x187148, .waiting: 0x875c00, .merged: 0x7541bb,
                                          .action: 0x1763b5, .danger: 0xb33343, .neutral: 0x535967]
        let dark: [StateColour: UInt32] = [.added: 0x70e3ac, .waiting: 0xffd278, .merged: 0xd3b2ff,
                                         .action: 0x9ccaff, .danger: 0xffa5b1, .neutral: 0xd5d8e0]
        return colour((self == .light ? light : dark)[meaning]!)
    }

    /// Returns the identity colour for a tool, with a neutral unknown-tool fallback.
    public func colour(for tool: ToolColour) -> Color {
        let light: [ToolColour: UInt32] = [.claude: 0xb74b38, .codex: 0x007b75,
                                         .opencode: 0x896700, .cursor: 0x2878ae, .unknown: 0x535967]
        let dark: [ToolColour: UInt32] = [.claude: 0xffad98, .codex: 0x79dacf,
                                        .opencode: 0xffda77, .cursor: 0x9ed6ff, .unknown: 0xd5d8e0]
        return colour((self == .light ? light : dark)[tool]!)
    }

    private func colour(_ hex: UInt32) -> Color {
        Color(red: Double((hex >> 16) & 255) / 255, green: Double((hex >> 8) & 255) / 255,
              blue: Double(hex & 255) / 255)
    }
}

/// Semantic colours shared by states, tones and plan steps.
public enum StateColour: Sendable {
    case added, waiting, merged, action, danger, neutral

    /// Maps delivery states to their presentation meaning.
    public static func state(_ value: String) -> Self {
        switch value {
        case "added", "shown", "written_here", "in_sync": return .added
        case "attached", "waiting": return .waiting
        case "merged", "merged_copy": return .merged
        case "linked", "relinked": return .action
        case "undo", "conflict", "decision_needed", "removed": return .danger
        default: return .neutral
        }
    }

    /// Maps note severity to its presentation meaning.
    public static func tone(_ value: String) -> Self {
        switch value {
        case "ok": return .added
        case "warning": return .waiting
        case "danger": return .danger
        default: return .action
        }
    }

    /// Maps plan actions to their presentation meaning.
    public static func step(_ value: String) -> Self {
        switch value {
        case "close", "release", "cut", "create_shorter": return .danger
        case "add", "add_after_release", "create", "place", "write": return .added
        case "reopen", "open": return .action
        case "attach", "hold": return .waiting
        default: return .neutral
        }
    }
}

/// A tool's identity, used only for presentation.
public enum ToolColour: String, Sendable {
    case claude, codex, opencode, cursor, unknown
    /// Preserves unknown tools as neutral identities.
    public init(tool: String) { self = Self(rawValue: tool) ?? .unknown }
}

private struct ThemeKey: EnvironmentKey { static let defaultValue = Theme.light }
private struct GlassKey: EnvironmentKey { static let defaultValue = 62.0 }
public extension EnvironmentValues {
    var batonTheme: Theme { get { self[ThemeKey.self] } set { self[ThemeKey.self] = newValue } }
    var batonGlass: Double { get { self[GlassKey.self] } set { self[GlassKey.self] = newValue } }
}

public extension View {
    /// Applies the palette and the user's surface opacity setting.
    func batonTheme(_ theme: Theme, glass: Double = 62) -> some View {
        environment(\.batonTheme, theme).environment(\.batonGlass, min(95, max(40, glass)))
            .preferredColorScheme(theme.scheme).foregroundStyle(theme.text)
    }
}

/// A material surface with readable content and reduced-transparency support.
public struct GlassCard<Content: View>: View {
    @Environment(\.batonTheme) private var theme
    @Environment(\.batonGlass) private var glass
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    private let content: Content
    /// Wraps content in a readable material surface.
    public init(@ViewBuilder content: () -> Content) { self.content = content() }
    public var body: some View {
        content.padding(12)
            .background {
                RoundedRectangle(cornerRadius: 12).fill(.regularMaterial)
                    .overlay(RoundedRectangle(cornerRadius: 12)
                        .fill(theme.background.opacity(reduceTransparency ? 1 : max(0.85, glass / 100))))
            }
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(theme.hairline))
    }
}
