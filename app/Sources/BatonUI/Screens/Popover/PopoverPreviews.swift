import SwiftUI
import BatonKit

private struct FixturePopover: View {
    @StateObject private var model: PopoverViewModel
    @MainActor init(state: String) {
        let directory = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Fixtures")
        _model = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: directory, state: state)))
    }
    var body: some View { PopoverView(model: model).task { await model.refresh() } }
}

/// Both-theme previews of the eight popover fixture states.
@MainActor
struct PopoverPreviews: PreviewProvider {
    static var previews: some View {
        ForEach(["no_links", "in_sync", "one_side_ahead", "waiting", "relaunch_needed", "decision_needed", "paused", "setup_incomplete"], id: \.self) { state in
            ForEach(Theme.allCases, id: \.rawValue) { theme in
                FixturePopover(state: "d2_" + state).batonTheme(theme)
                    .previewDisplayName("\(state) · \(theme.rawValue)")
            }
        }
    }
}
