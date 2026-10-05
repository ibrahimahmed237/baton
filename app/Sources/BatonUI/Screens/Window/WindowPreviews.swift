import SwiftUI
import BatonKit

private struct FixtureWindow: View {
    @StateObject private var model: WindowViewModel
    let destination: WindowSection
    @MainActor init(state: String, destination: WindowSection) {
        self.destination = destination
        let directory = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Fixtures")
        _model = StateObject(wrappedValue: WindowViewModel(engine: FixtureEngine(directory: directory, state: state)))
    }
    var body: some View {
        WindowView(model: model).task { await model.refresh(); model.navigate(to: destination) }
    }
}

/// Empty and filled previews for all sidebar lists in both palettes.
@MainActor
struct WindowPreviews: PreviewProvider {
    static var previews: some View {
        ForEach(["empty", "filled"], id: \.self) { state in
            ForEach([WindowSection.linked, .attention, .suggestions, .chats("claude"), .chats("codex"), .chats("opencode"), .chats("cursor"), .activity], id: \.self) { section in
                ForEach(Theme.allCases, id: \.rawValue) { theme in
                    FixtureWindow(state: "d3_" + state, destination: section).batonTheme(theme)
                        .previewDisplayName("\(state) · \(section) · \(theme.rawValue)")
                }
            }
        }
    }
}
