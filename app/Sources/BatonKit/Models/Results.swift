import Foundation

/// Result of the Setup command.
public struct SetupResult: Codable, Equatable, Sendable {
    public var tools: [SetupTool]

    /// Creates a contract value without requiring JSON.
    public init(tools: [SetupTool]) {
        self.tools = tools
    }

    private enum CodingKeys: String, CodingKey {
        case tools
    }
}

/// Result of the SetupInstall command.
public struct SetupInstallResult: Codable, Equatable, Sendable {
    public var tools: [SetupTool]

    /// Creates a contract value without requiring JSON.
    public init(tools: [SetupTool]) {
        self.tools = tools
    }

    private enum CodingKeys: String, CodingKey {
        case tools
    }
}

/// Result of the Chats command.
public struct ChatsResult: Codable, Equatable, Sendable {
    public var chats: [Chat]

    /// Creates a contract value without requiring JSON.
    public init(chats: [Chat]) {
        self.chats = chats
    }

    private enum CodingKeys: String, CodingKey {
        case chats
    }
}

/// Result of the Suggestions command.
public struct SuggestionsResult: Codable, Equatable, Sendable {
    public var suggestions: [Suggestion]

    /// Creates a contract value without requiring JSON.
    public init(suggestions: [Suggestion]) {
        self.suggestions = suggestions
    }

    private enum CodingKeys: String, CodingKey {
        case suggestions
    }
}

/// Result of the Links command.
public struct LinksResult: Codable, Equatable, Sendable {
    public var links: [LinkSummary]
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(links: [LinkSummary], notes: [Note] = []) {
        self.links = links
        self.notes = notes
    }

    /// Older engines may omit the additive presentation notes.
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        links = try values.decode([LinkSummary].self, forKey: .links)
        notes = try values.decodeIfPresent([Note].self, forKey: .notes) ?? []
    }

    private enum CodingKeys: String, CodingKey {
        case links
        case notes
    }
}

/// Result of the Status command.
public struct StatusResult: Codable, Equatable, Sendable {
    public var linkID: Int
    public var mode: String
    public var paused: Bool
    public var inSync: Bool
    public var decisionNeeded: Bool
    public var sides: [String: Side]
    public var turns: [Turn]
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(linkID: Int, mode: String, paused: Bool, inSync: Bool, decisionNeeded: Bool, sides: [String: Side], turns: [Turn], notes: [Note]) {
        self.linkID = linkID
        self.mode = mode
        self.paused = paused
        self.inSync = inSync
        self.decisionNeeded = decisionNeeded
        self.sides = sides
        self.turns = turns
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case linkID = "link_id"
        case mode
        case paused
        case inSync = "in_sync"
        case decisionNeeded = "decision_needed"
        case sides
        case turns
        case notes
    }
}

/// Result of the Link command.
public struct LinkResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Copy command.
public struct CopyResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Relink command.
public struct RelinkResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Unlink command.
public struct UnlinkResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Sync command.
public struct SyncResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Merge command.
public struct MergeResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Restore command.
public struct RestoreResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the AskAdd command.
public struct AskAddResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Rename command.
public struct RenameResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
    }
}

/// Result of the Pause command.
public struct PauseResult: Codable, Equatable, Sendable {
    public var linkID: Int
    public var paused: Bool

    /// Creates a contract value without requiring JSON.
    public init(linkID: Int, paused: Bool) {
        self.linkID = linkID
        self.paused = paused
    }

    private enum CodingKeys: String, CodingKey {
        case linkID = "link_id"
        case paused
    }
}

/// Result of the Resume command.
public struct ResumeResult: Codable, Equatable, Sendable {
    public var linkID: Int
    public var paused: Bool

    /// Creates a contract value without requiring JSON.
    public init(linkID: Int, paused: Bool) {
        self.linkID = linkID
        self.paused = paused
    }

    private enum CodingKeys: String, CodingKey {
        case linkID = "link_id"
        case paused
    }
}

/// Result of the Continue command.
public struct ContinueResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]
    public var opened: Bool

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note], opened: Bool) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
        self.opened = opened
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
        case opened
    }
}

/// Result of the MergeShow command.
public struct MergeShowResult: Codable, Equatable, Sendable {
    public var lastShared: Turn?
    public var unsynced: [Turn]
    public var order: [Int]
    public var presets: [JSONValue]
    public var outcome: [String: String]
    public var overlaps: [[Int]]
    public var sameFiles: [SameFile]
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(lastShared: Turn? = nil, unsynced: [Turn], order: [Int], presets: [JSONValue], outcome: [String: String], overlaps: [[Int]], sameFiles: [SameFile], notes: [Note]) {
        self.lastShared = lastShared
        self.unsynced = unsynced
        self.order = order
        self.presets = presets
        self.outcome = outcome
        self.overlaps = overlaps
        self.sameFiles = sameFiles
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case lastShared = "last_shared"
        case unsynced
        case order
        case presets
        case outcome
        case overlaps
        case sameFiles = "same_files"
        case notes
    }
}

/// Result of the History command.
public struct HistoryResult: Codable, Equatable, Sendable {
    public var events: [HistoryEvent]

    /// Creates a contract value without requiring JSON.
    public init(events: [HistoryEvent]) {
        self.events = events
    }

    private enum CodingKeys: String, CodingKey {
        case events
    }
}

/// Result of the Undo command.
public struct UndoResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]
    public var removes: [RemovedTurn]
    public var endsAt: Turn?

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note], removes: [RemovedTurn], endsAt: Turn? = nil) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
        self.removes = removes
        self.endsAt = endsAt
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
        case removes
        case endsAt = "ends_at"
    }
}

/// Result of the Keep command.
public struct KeepResult: Codable, Equatable, Sendable {
    public var turn: Turn

    /// Creates a contract value without requiring JSON.
    public init(turn: Turn) {
        self.turn = turn
    }

    private enum CodingKeys: String, CodingKey {
        case turn
    }
}

/// Result of the Send command.
public struct SendResult: Codable, Equatable, Sendable {
    public var turn: Turn

    /// Creates a contract value without requiring JSON.
    public init(turn: Turn) {
        self.turn = turn
    }

    private enum CodingKeys: String, CodingKey {
        case turn
    }
}

/// Result of the Pin command.
public struct PinResult: Codable, Equatable, Sendable {
    public var turn: Turn

    /// Creates a contract value without requiring JSON.
    public init(turn: Turn) {
        self.turn = turn
    }

    private enum CodingKeys: String, CodingKey {
        case turn
    }
}

/// Result of the Unpin command.
public struct UnpinResult: Codable, Equatable, Sendable {
    public var turn: Turn

    /// Creates a contract value without requiring JSON.
    public init(turn: Turn) {
        self.turn = turn
    }

    private enum CodingKeys: String, CodingKey {
        case turn
    }
}

/// Result of the Brief command.
public struct BriefResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]
    public var brief: BriefDetails

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note], brief: BriefDetails) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
        self.brief = brief
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
        case brief
    }
}

/// Result of the Ask command.
public struct AskResult: Codable, Equatable, Sendable {
    public var answer: String
    public var tokens: Int
    public var seconds: Double
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(answer: String, tokens: Int, seconds: Double, notes: [Note]) {
        self.answer = answer
        self.tokens = tokens
        self.seconds = seconds
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case answer
        case tokens
        case seconds
        case notes
    }
}

/// Result of the Relaunch command.
public struct RelaunchResult: Codable, Equatable, Sendable {
    public var planID: String
    public var applied: Bool
    public var linkID: Int?
    public var steps: [Step]
    public var decisionNeeded: Bool
    public var notes: [Note]
    public var replying: [Chat]

    /// Creates a contract value without requiring JSON.
    public init(planID: String, applied: Bool, linkID: Int? = nil, steps: [Step], decisionNeeded: Bool, notes: [Note], replying: [Chat]) {
        self.planID = planID
        self.applied = applied
        self.linkID = linkID
        self.steps = steps
        self.decisionNeeded = decisionNeeded
        self.notes = notes
        self.replying = replying
    }

    private enum CodingKeys: String, CodingKey {
        case planID = "plan_id"
        case applied
        case linkID = "link_id"
        case steps
        case decisionNeeded = "decision_needed"
        case notes
        case replying
    }
}

/// Result of the Open command.
public struct OpenResult: Codable, Equatable, Sendable {
    public var opened: String
    public var note: Note

    /// Creates a contract value without requiring JSON.
    public init(opened: String, note: Note) {
        self.opened = opened
        self.note = note
    }

    private enum CodingKeys: String, CodingKey {
        case opened
        case note
    }
}

/// Result of the SettingsGet command.
public struct SettingsGetResult: Codable, Equatable, Sendable {
    public var settings: Settings

    /// Creates a contract value without requiring JSON.
    public init(settings: Settings) {
        self.settings = settings
    }

    private enum CodingKeys: String, CodingKey {
        case settings
    }
}

/// Result of the SettingsSet command.
public struct SettingsSetResult: Codable, Equatable, Sendable {
    public var settings: Settings

    /// Creates a contract value without requiring JSON.
    public init(settings: Settings) {
        self.settings = settings
    }

    private enum CodingKeys: String, CodingKey {
        case settings
    }
}

/// Result of the Notify command.
public struct NotifyResult: Codable, Equatable, Sendable {
    public var synced: [Int]
    public var queued: [Int]
    public var offers: [Note]

    /// Creates a contract value without requiring JSON.
    public init(synced: [Int], queued: [Int], offers: [Note]) {
        self.synced = synced
        self.queued = queued
        self.offers = offers
    }

    private enum CodingKeys: String, CodingKey {
        case synced
        case queued
        case offers
    }
}

/// Result of the CatchUp command.
public struct CatchUpResult: Codable, Equatable, Sendable {
    public var output: String

    /// Creates a contract value without requiring JSON.
    public init(output: String) {
        self.output = output
    }

    private enum CodingKeys: String, CodingKey {
        case output
    }
}
