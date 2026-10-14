import Foundation
import BatonKit

/// Packaged, generated engine wording remains available when transport itself fails.
enum SetupPresentation {
    private static var directories: [URL] {
        var local = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { local.deleteLastPathComponent() }
        return [Bundle.main.resourceURL?.appendingPathComponent("Fixtures"),
                Bundle.main.resourceURL?.appendingPathComponent("Baton_Baton.bundle/Contents/Resources/Fixtures"),
                Bundle.main.executableURL?.deletingLastPathComponent().appendingPathComponent("Baton_Baton.bundle/Contents/Resources/Fixtures"),
                local.appendingPathComponent("Fixtures")].compactMap { $0 }
    }
    private static func data(_ name: String) -> Data? {
        directories.lazy.compactMap { try? Data(contentsOf: $0.appendingPathComponent(name)) }.first
    }
    private struct Failure: Decodable { let error: EngineCommandError }
    static let failure: Note? = data("setup.d11_error.json").flatMap { try? JSONDecoder().decode(Failure.self, from: $0).error.note }
    private static let labels: [Note] = data("links.sample.json").flatMap { try? JSONDecoder().decode(LinksResult.self, from: $0).notes } ?? []
    static let empty: Note? = labels.first { $0.id == "screen.list_empty" }
    static let opinionLabels: [Note] = data("ask.d10_before.json").flatMap {
        try? JSONDecoder().decode(OpinionResponse.self, from: $0).notes
    } ?? []
    static let chooseChat: Note? = labels.first { $0.id == "empty.select_chat.title" }
}
