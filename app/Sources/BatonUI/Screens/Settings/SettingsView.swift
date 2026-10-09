import SwiftUI
import BatonKit

/// Groups settings with their choices, defaults and preview boundary clearly visible.
public struct SettingsView: View {
    @Environment(\.batonSnapshotPresentation) private var snapshot
    @Environment(\.batonTheme) private var theme
    @ObservedObject private var model: SettingsViewModel
    @ObservedObject private var appearance: ThemePreference
    private let fallbackNotes: [Note]
    @State private var tokenDraft = ""
    @State private var opacityDraft = 62.0
    public init(model: SettingsViewModel, appearance: ThemePreference, fallbackNotes: [Note] = []) {
        self.model = model; self.appearance = appearance; self.fallbackNotes = fallbackNotes
        _tokenDraft = State(initialValue: model.value("brief_threshold_tokens"))
        _opacityDraft = State(initialValue: appearance.glass)
    }
    private func note(_ id: String) -> Note? { model.note(id) ?? fallbackNotes.first { $0.id == id } }
    public var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 12) {
                Image(systemName: "slider.horizontal.3").font(.title2).foregroundStyle(theme.secondaryText)
                if let title = note("screen.settings") { Text(title.text).font(.largeTitle.weight(.semibold)) }
                Spacer()
                if let label = note("settings.reset") {
                    Button(label.text) { Task { await model.restoreDefaults(); resetDrafts() } }
                        .disabled(model.settings == nil || model.loading || model.saving)
                }
            }
            if let preview = note("settings.preview") { NoteView(note: preview) }
            if model.loading { ProgressView() }
            if let error = model.errorNote ?? ((model.saveFailed || model.loadFailed) && !model.loading ? note("settings.error") : nil) {
                NoteView(note: error)
                if model.settings == nil, let label = note("screen.refresh") { Button(label.text) { Task { await model.load(); resetDrafts() } } }
            }
            if model.saved, let saved = note("settings.saved") { Label(saved.text, systemImage: "checkmark.circle").font(.caption).foregroundStyle(theme.colour(for: .added)) }
            if model.settings != nil {
                group("settings.appearance", keys: ["theme", "glass"])
                group("settings.sync", keys: ["notice_on_attach", "offer_relaunch", "add_to_idle_claude", "offer_switch_at_limit", "merge"])
                group("settings.chats", keys: ["brief_threshold_tokens", "hide_script_chats", "title_tag"])
            }
        }.frame(maxWidth: 760, alignment: .leading).frame(maxWidth: .infinity, alignment: .leading)
            .task { if model.settings == nil, !snapshot { await model.load(); resetDrafts() } }
            .onChange(of: appearance.glass) { _, value in opacityDraft = value }
    }
    private func resetDrafts() { tokenDraft = model.value("brief_threshold_tokens"); opacityDraft = appearance.glass }
    private func group(_ id: String, keys: [String]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title = note(id) { Text(title.text).font(.headline) }
            GlassCard {
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(keys, id: \.self) { key in
                        if let choice = SettingsChoice.all.first(where: { $0.key == key }), let label = note("settings." + key) {
                            row(choice, label: label)
                            if key != keys.last { Divider() }
                        }
                    }
                }
            }
        }.disabled(model.loading || model.saving)
    }
    private func row(_ choice: SettingsChoice, label: Note) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .center, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(label.text).font(.callout.weight(.medium))
                    if let value = model.defaultNote(choice.key) { Text(value.text).font(.caption).foregroundStyle(theme.secondaryText) }
                }.frame(maxWidth: .infinity, alignment: .leading)
                control(choice, label: label)
            }
            if choice.key == "glass", let help = note("settings.glass_help") { Text(help.text).font(.caption).foregroundStyle(theme.secondaryText) }
        }
    }
    @ViewBuilder private func control(_ choice: SettingsChoice, label: Note) -> some View {
        switch choice.kind {
        case .toggle:
            Toggle(label.text, isOn: Binding(get: { model.value(choice.key) == "true" }, set: { value in
                Task { await model.set(choice.key, value: String(value)) }
            })).labelsHidden().toggleStyle(SettingsSwitchStyle(on: note("settings.on")?.text ?? "", off: note("settings.off")?.text ?? "")).accessibilityLabel(label.text)
        case .options(let values):
            Picker(label.text, selection: Binding(get: { model.value(choice.key) }, set: { value in
                Task { await model.set(choice.key, value: value) }
            })) {
                ForEach(values, id: \.self) { value in
                    if let option = note(choice.key == "theme" ? "screen.theme." + value : "settings." + value) { Text(option.text).tag(value) }
                }
            }.labelsHidden().frame(width: 200).accessibilityLabel(label.text)
        case .tokens:
            HStack(spacing: 8) {
                if snapshot {
                    Text(tokenDraft).font(.body.monospacedDigit()).frame(width: 95, alignment: .leading).padding(5)
                        .background(theme.sidebar, in: RoundedRectangle(cornerRadius: 5))
                } else {
                    TextField(label.text, text: $tokenDraft).textFieldStyle(.roundedBorder).frame(width: 105).accessibilityLabel(label.text)
                        .onSubmit { Task { await model.set(choice.key, value: tokenDraft) } }
                }
                if let apply = note("settings.apply") { Button(apply.text) { Task { await model.set(choice.key, value: tokenDraft) } } }
            }
        case .opacity:
            HStack(spacing: 8) {
                Slider(value: $opacityDraft, in: 40...95, onEditingChanged: { editing in
                    if !editing { Task { await model.set(choice.key, value: String(opacityDraft)); opacityDraft = appearance.glass } }
                }).frame(width: 155).accessibilityLabel(label.text)
                Text(opacityDraft / 100, format: .percent.precision(.fractionLength(0))).font(.caption.monospacedDigit()).frame(width: 34)
            }
        }
    }
}


private struct SettingsSwitchStyle: ToggleStyle {
    let on: String
    let off: String
    @Environment(\.batonTheme) private var theme
    func makeBody(configuration: Configuration) -> some View {
        Button { configuration.isOn.toggle() } label: {
            Capsule().fill(configuration.isOn ? theme.colour(for: .action) : theme.secondaryText.opacity(0.25))
                .frame(width: 38, height: 22)
                .overlay(alignment: configuration.isOn ? .trailing : .leading) {
                    Circle().fill(Color.white).frame(width: 16, height: 16).padding(3)
                }
        }.buttonStyle(.plain).accessibilityValue(configuration.isOn ? on : off)

            .accessibilityAddTraits(configuration.isOn ? .isSelected : [])
    }
}
