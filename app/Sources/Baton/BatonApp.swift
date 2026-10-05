import AppKit
import SwiftUI
import BatonKit
import BatonUI

/// The D0 list shared by the menu-bar extra and the main window.
struct LinkList: View {
    @ObservedObject var state: PopoverViewModel

    var body: some View {
        List {
            if let note = state.errorNote {
                Text(note.text)
            }
            ForEach(state.links, id: \.linkID) { link in
                VStack(alignment: .leading) {
                    ForEach(link.sides.keys.sorted(), id: \.self) { tool in
                        if let chat = link.sides[tool] {
                            Text(chat.name)
                        }
                    }
                    Text(link.headline.text)
                }
            }
        }
        .task { await state.refresh() }
    }
}

/// A fixture-backed menu-bar app and window, built directly by Swift Package Manager.
@main
struct BatonApp: App {
    @StateObject private var state: PopoverViewModel
    @Environment(\.openWindow) private var openWindow

    init() {
        NSApplication.shared.setActivationPolicy(.accessory)
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        _state = StateObject(wrappedValue: PopoverViewModel(engine: FixtureEngine(directory: fixtures, states: ["links": "d2_in_sync", "suggestions": "d2_in_sync", "continue": "d2_in_sync"])))
    }

    var body: some Scene {
        MenuBarExtra {
            PopoverView(model: state, linkRecent: { openWindow(id: "links") }).task { await state.refresh() }
        } label: {
            BatonMenuIcon(needsDecision: state.needsDecision)
        }
        .menuBarExtraStyle(.window)
        Window("Baton", id: "links") {
            LinkList(state: state)
        }
    }
}
