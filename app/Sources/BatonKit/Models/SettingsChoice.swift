import Foundation

/// Describes the existing settings contract as data, without presentation wording.
public struct SettingsChoice: Sendable {
    public enum Kind: Sendable { case toggle, options([String]), tokens, opacity }
    public let key: String
    public let kind: Kind
    public let defaultValue: String
    public static let all: [SettingsChoice] = [
        .init(key: "theme", kind: .options(["system", "light", "graphite"]), defaultValue: "system"),
        .init(key: "glass", kind: .opacity, defaultValue: "62"),
        .init(key: "notice_on_attach", kind: .toggle, defaultValue: "true"),
        .init(key: "offer_relaunch", kind: .toggle, defaultValue: "true"),
        .init(key: "add_to_idle_claude", kind: .options(["on_button", "automatic"]), defaultValue: "on_button"),
        .init(key: "offer_switch_at_limit", kind: .toggle, defaultValue: "true"),
        .init(key: "merge", kind: .options(["ask", "by_time"]), defaultValue: "ask"),
        .init(key: "brief_threshold_tokens", kind: .tokens, defaultValue: "150000"),
        .init(key: "hide_script_chats", kind: .toggle, defaultValue: "true"),
        .init(key: "title_tag", kind: .toggle, defaultValue: "true")
    ]
}

/// Rejects invalid configuration without mutating the previous settings.
public enum SettingsValueError: Error { case invalidValue }

public extension Settings {
    /// Reads a setting as a command argument rather than a displayed sentence.
    func value(for key: String) -> String? {
        switch key {
        case "notice_on_attach": return String(noticeOnAttach)
        case "offer_relaunch": return String(offerRelaunch)
        case "add_to_idle_claude": return addToIdleClaude
        case "offer_switch_at_limit": return String(offerSwitchAtLimit)
        case "merge": return merge
        case "brief_threshold_tokens": return String(format: "%.0f", briefThresholdTokens)
        case "hide_script_chats": return String(hideScriptChats)
        case "title_tag": return String(titleTag)
        case "theme": return theme
        case "glass": return String(glass)
        default: return nil
        }
    }
    /// Returns a validated copy, leaving the current value intact on refusal.
    func changing(key: String, to value: String) throws -> Settings {
        guard let choice = SettingsChoice.all.first(where: { $0.key == key }) else { throw SettingsValueError.invalidValue }
        switch choice.kind {
        case .toggle: guard value == "true" || value == "false" else { throw SettingsValueError.invalidValue }
        case .options(let values): guard values.contains(value) else { throw SettingsValueError.invalidValue }
        case .tokens:
            guard let number = Int(value), number > 0 else { throw SettingsValueError.invalidValue }
        case .opacity:
            guard let number = Double(value), number.isFinite, (40...95).contains(number) else { throw SettingsValueError.invalidValue }
        }
        var copy = self
        switch key {
        case "notice_on_attach": copy.noticeOnAttach = value == "true"
        case "offer_relaunch": copy.offerRelaunch = value == "true"
        case "add_to_idle_claude": copy.addToIdleClaude = value
        case "offer_switch_at_limit": copy.offerSwitchAtLimit = value == "true"
        case "merge": copy.merge = value
        case "brief_threshold_tokens": copy.briefThresholdTokens = Double(value)!
        case "hide_script_chats": copy.hideScriptChats = value == "true"
        case "title_tag": copy.titleTag = value == "true"
        case "theme": copy.theme = value
        case "glass": copy.glass = Double(value)!
        default: throw SettingsValueError.invalidValue
        }
        return copy
    }
}
