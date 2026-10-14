import Foundation
import Combine
import BatonKit

public struct MergePreset: Identifiable, Equatable {
    public let id: String
    public let label: String
    public let order: [Int]
    init?(_ value: JSONValue) {
        guard case .object(let fields) = value, case .string(let id) = fields["id"],
              case .string(let label) = fields["label"], case .array(let values) = fields["order"] else { return nil }
        var ids: [Int] = []
        for value in values { guard case .number(let n) = value, let id = Int(exactly: n) else { return nil }; ids.append(id) }
        self.id = id; self.label = label; order = ids
    }
}

private struct MergeProjection: Decodable, Sendable {
    let result: MergeShowResult
    let preset: String?
    enum CodingKeys: String, CodingKey { case preset = "selected_preset" }
    init(from decoder: any Decoder) throws {
        result = try MergeShowResult(from: decoder)
        preset = try decoder.container(keyedBy: CodingKeys.self).decodeIfPresent(String.self, forKey: .preset)
    }
}

@MainActor public final class MergeViewModel: ObservableObject {
    @Published public private(set) var result: MergeShowResult?
    @Published public private(set) var errorNote: Note?
    @Published public private(set) var busy = false
    @Published public private(set) var selectedChoice: MergeChoice?
    @Published public private(set) var briefDestination: String?
    public let review: ActionReviewViewModel
    public var onBriefRequested: ((Int, String, [Int]) -> Void)?
    private let engine: any EngineTransport
    private var link: Int?
    private var revision = 0
    public init(engine: any EngineTransport) { self.engine = engine; review = ActionReviewViewModel(engine: engine) }
    public var presets: [MergePreset] { result?.presets.compactMap(MergePreset.init) ?? [] }
    public var turns: [Turn] { result?.order.compactMap { id in result?.unsynced.first { $0.id == id } } ?? [] }
    public var presentationNotes: [Note] { result?.notes.filter { $0.id != "merge.always" } ?? [] }
    public var choices: [Note] { result?.notes.filter { ["merge.keep_choice", "merge.split_choice", "merge.brief_choice"].contains($0.id) } ?? [] }
    public func load(link: Int) async { self.link = link; await refresh(order: nil, preset: nil) }
    private func refresh(order: [Int]?, preset: String?) async {
        let expectedPreset = preset.flatMap { id in presets.first { $0.id == id } }
        revision += 1; let current = revision; review.invalidate(); result = nil; selectedChoice = nil; errorNote = nil; busy = true
        guard let link else { busy = false; return }
        do {
            var arguments = ["--link", String(link), "--show"]
            if let order { arguments += ["--order", order.map(String.init).joined(separator: ",")] }
            if let preset { arguments += ["--preset", preset] }
            let projection = try await engine.response(command: "merge-show", arguments: arguments, as: MergeProjection.self)
            let response = projection.result
            guard current == revision else { return }
            guard Set(response.order) == Set(response.unsynced.map(\.id)), response.order.count == response.unsynced.count,
                  order == nil || response.order == order,
                  preset == nil || (projection.preset == preset && response.order == expectedPreset?.order) else { busy = false; return }
            result = response; busy = false
            selectedChoice = preset.map(MergeChoice.preset) ?? .order(response.order)
            await preview()
        } catch { guard current == revision else { return }; errorNote = (error as? EngineCommandError)?.note; busy = false }
    }
    public func select(_ preset: MergePreset) async {
        guard !busy, presets.contains(preset) else { return }
        await refresh(order: nil, preset: preset.id)
    }
    public func choose(_ note: Note) async {
        guard !busy, choices.contains(note), let link else { return }
        switch note.id {
        case "merge.keep_choice":
            guard case .string(let tool) = note.values["tool_id"] else { return }
            selectedChoice = .keep(tool); await preview()
        case "merge.split_choice": selectedChoice = .split; await preview()
        case "merge.brief_choice":
            guard let result, let tool = result.outcome.keys.sorted().first(where: { result.outcome[$0] == "merged_copy" }) else { return }
            review.invalidate(); briefDestination = tool; onBriefRequested?(link, tool, result.order)
        default: break
        }
    }
    public func move(_ id: Int, to index: Int) async {
        guard !busy, var order = result?.order, let old = order.firstIndex(of: id), order.indices.contains(index), old != index else { return }
        order.remove(at: old); order.insert(id, at: index)
        await refresh(order: order, preset: nil)
    }
    public func preview() async {
        guard !busy, let link, let selectedChoice else { return }
        await review.load(.merge(link: link, choice: selectedChoice))
    }
}
