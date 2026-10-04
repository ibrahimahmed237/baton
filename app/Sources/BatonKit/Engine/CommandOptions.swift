/// Specifies whether a mutating command previews or confirms a previously returned plan.
public enum MutationOptions: Equatable, Sendable {
    case preview
    case confirm(String)

    var arguments: [String] {
        switch self {
        case .preview: return ["--dry-run"]
        case .confirm(let planID): return ["--confirm", planID]
        }
    }
}

/// Encodes the mutually exclusive ways to resolve a merge decision.
public enum MergeChoice: Equatable, Sendable {
    case order([Int])
    case preset(String)
    case keep(String)
    case split

    var arguments: [String] {
        switch self {
        case .order(let ids): return ["--order", ids.map(String.init).joined(separator: ",")]
        case .preset(let name): return ["--preset", name]
        case .keep(let tool): return ["--keep", tool]
        case .split: return ["--split"]
        }
    }
}
