import AppKit
import Foundation
import BatonKit

/// Confirms all user quit routes, with cancellation as the default.
@MainActor public final class BatonQuitConfirmation {
    private var presenting = false
    public init() {}
    /// Loads catalogue wording from packaged fixtures before any engine request can fail.
    public static func loadNotes(from directory: URL) -> [Note] {
        guard let data = try? Data(contentsOf: directory.appendingPathComponent("links.sample.json")),
              let links = try? JSONDecoder().decode(LinksResult.self, from: data) else { return [] }
        return links.notes.filter { $0.id.hasPrefix("quit.") || ["screen.quit", "screen.open_window"].contains($0.id) }
    }
    /// Presents the engine's wording and refuses missing, cancelled or reentrant confirmations.
    public func request(title: Note, message: Note, actions: Note,
                        present: ((Note, Note, [NoteButton]) -> String?)? = nil) -> Bool {
        guard !presenting, let cancel = actions.buttons.first(where: { $0.id == "cancel" }),
              let quit = actions.buttons.first(where: { $0.id == "quit" }) else { return false }
        presenting = true
        defer { presenting = false }
        let buttons = [cancel, quit]
        if let present { return present(title, message, buttons) == "quit" }
        let alert = NSAlert()
        alert.messageText = title.text; alert.informativeText = message.text
        alert.alertStyle = .warning
        for button in buttons { alert.addButton(withTitle: button.label) }
        alert.buttons[0].keyEquivalent = "\r"
        alert.buttons[1].keyEquivalent = ""
        NSApplication.shared.activate(ignoringOtherApps: true)
        return alert.runModal() == .alertSecondButtonReturn
    }
}
