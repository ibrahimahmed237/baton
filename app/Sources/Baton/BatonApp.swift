import AppKit
import SwiftUI
import BatonKit

/// Holds only the engine's list response and any engine-supplied error note.
@MainActor
final class AppState: ObservableObject {
    @Published private(set) var links: [LinkSummary] = []
    @Published private(set) var errorNote: Note?
    private let engine: any EngineClient

    /// Injects the same client into the menu and window.
    init(engine: any EngineClient) {
        self.engine = engine
    }

    /// Refreshes the list using engine data without synthesizing display sentences.
    func refresh() async {
        do {
            links = try await engine.links().links
            errorNote = nil
        } catch let error as EngineCommandError {
            errorNote = error.note
        } catch {
            // Transport errors have no catalogue sentence; D13 adds their presentation.
            errorNote = nil
        }
    }
}

/// The D0 list shared by the menu-bar extra and the main window.
struct LinkList: View {
    @ObservedObject var state: AppState

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
    @StateObject private var state: AppState

    init() {
        NSApplication.shared.setActivationPolicy(.accessory)
        let fixtures = Bundle.module.resourceURL!.appendingPathComponent("Fixtures", isDirectory: true)
        _state = StateObject(wrappedValue: AppState(engine: FixtureEngine(directory: fixtures)))
    }

    var body: some Scene {
        MenuBarExtra("Baton", systemImage: "link") {
            LinkList(state: state)
        }
        .menuBarExtraStyle(.window)
        Window("Baton", id: "links") {
            LinkList(state: state)
        }
    }
}
