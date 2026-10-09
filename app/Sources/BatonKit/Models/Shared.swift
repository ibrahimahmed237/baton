import Foundation

/// NoteButton data returned by the engine.
public struct NoteButton: Codable, Equatable, Sendable {
    public var id: String
    public var label: String
    public var primary: Bool?

    /// Creates a contract value without requiring JSON.
    public init(id: String, label: String, primary: Bool? = nil) {
        self.id = id
        self.label = label
        self.primary = primary
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case label
        case primary
    }
}

/// Note data returned by the engine.
public struct Note: Codable, Equatable, Sendable {
    public var id: String
    public var tone: String
    public var values: [String: JSONValue]
    public var text: String
    public var buttons: [NoteButton]
    public var statusLine: String?

    /// Creates a contract value without requiring JSON.
    public init(id: String, tone: String, values: [String: JSONValue], text: String, buttons: [NoteButton], statusLine: String? = nil) {
        self.id = id
        self.tone = tone
        self.values = values
        self.text = text
        self.buttons = buttons
        self.statusLine = statusLine
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case tone
        case values
        case text
        case buttons
        case statusLine = "status_line"
    }
}

/// Chat data returned by the engine.
public struct Chat: Codable, Equatable, Sendable {
    public var tool: String
    public var toolLabel: String?
    public var displayLabel: String { toolLabel ?? tool }
    public var id: String
    public var name: String
    public var folder: String
    public var updatedAt: String
    public var linked: Bool
    public var linkID: Int?

    /// Creates a contract value without requiring JSON.
    public init(tool: String, id: String, name: String, folder: String, updatedAt: String, linked: Bool, toolLabel: String? = nil, linkID: Int? = nil) {
        self.tool = tool
        self.toolLabel = toolLabel
        self.id = id
        self.name = name
        self.folder = folder
        self.updatedAt = updatedAt
        self.linked = linked
        self.linkID = linkID
    }

    private enum CodingKeys: String, CodingKey {
        case tool
        case toolLabel = "tool_label"
        case id
        case name
        case folder
        case updatedAt = "updated_at"
        case linked
        case linkID = "link_id"
    }
}

/// SideCondition data returned by the engine.
public struct SideCondition: Codable, Equatable, Sendable {
    public var exists: Bool
    public var open: Bool
    public var replying: Bool
    public var hooksReady: Bool

    /// Creates a contract value without requiring JSON.
    public init(exists: Bool, open: Bool, replying: Bool, hooksReady: Bool) {
        self.exists = exists
        self.open = open
        self.replying = replying
        self.hooksReady = hooksReady
    }

    private enum CodingKeys: String, CodingKey {
        case exists
        case open
        case replying
        case hooksReady = "hooks_ready"
    }
}

/// UsageLimit data returned by the engine.
public struct UsageLimit: Codable, Equatable, Sendable {
    public var resetsAt: String?

    /// Creates a contract value without requiring JSON.
    public init(resetsAt: String? = nil) {
        self.resetsAt = resetsAt
    }

    private enum CodingKeys: String, CodingKey {
        case resetsAt = "resets_at"
    }
}

/// Usage data returned by the engine.
public struct Usage: Codable, Equatable, Sendable {
    public var tokens: Int
    public var size: Int?
    public var percent: Double?
    public var limit: UsageLimit?

    /// Creates a contract value without requiring JSON.
    public init(tokens: Int, size: Int? = nil, percent: Double? = nil, limit: UsageLimit? = nil) {
        self.tokens = tokens
        self.size = size
        self.percent = percent
        self.limit = limit
    }

    private enum CodingKeys: String, CodingKey {
        case tokens
        case size
        case percent
        case limit
    }
}

/// NextMessage data returned by the engine.
public struct NextMessage: Codable, Equatable, Sendable {
    public var turns: Int
    public var tokens: Int

    /// Creates a contract value without requiring JSON.
    public init(turns: Int, tokens: Int) {
        self.turns = turns
        self.tokens = tokens
    }

    private enum CodingKeys: String, CodingKey {
        case turns
        case tokens
    }
}

/// SinceYouLeft data returned by the engine.
public struct SinceYouLeft: Codable, Equatable, Sendable {
    public var turns: Int
    public var files: Int
    public var commands: Int
    public var since: String

    /// Creates a contract value without requiring JSON.
    public init(turns: Int, files: Int, commands: Int, since: String) {
        self.turns = turns
        self.files = files
        self.commands = commands
        self.since = since
    }

    private enum CodingKeys: String, CodingKey {
        case turns
        case files
        case commands
        case since
    }
}

/// TurnMessage data returned by the engine.
public struct TurnMessage: Codable, Equatable, Sendable {
    public var kind: String
    public var text: String
    public var tool: String?

    /// Creates a contract value without requiring JSON.
    public init(kind: String, text: String, tool: String? = nil) {
        self.kind = kind
        self.text = text
        self.tool = tool
    }

    private enum CodingKeys: String, CodingKey {
        case kind
        case text
        case tool
    }
}

/// Turn data returned by the engine.
public struct Turn: Codable, Equatable, Sendable {
    public var id: Int
    public var seq: Int
    public var origin: String
    public var firstLine: String
    public var startedAt: String
    public var endedAt: String?
    public var tokens: Int
    public var pinned: Bool
    public var states: [String: String]
    public var messages: [TurnMessage]?

    /// Creates a contract value without requiring JSON.
    public init(id: Int, seq: Int, origin: String, firstLine: String, startedAt: String, endedAt: String? = nil, tokens: Int, pinned: Bool, states: [String: String], messages: [TurnMessage]? = nil) {
        self.id = id
        self.seq = seq
        self.origin = origin
        self.firstLine = firstLine
        self.startedAt = startedAt
        self.endedAt = endedAt
        self.tokens = tokens
        self.pinned = pinned
        self.states = states
        self.messages = messages
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case seq
        case origin
        case firstLine = "first_line"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case tokens
        case pinned
        case states
        case messages
    }
}

/// Side data returned by the engine.
public struct Side: Codable, Equatable, Sendable {
    public var tool: String
    public var toolLabel: String?
    public var displayLabel: String { toolLabel ?? tool }
    public var chat: Chat
    public var condition: SideCondition
    public var total: Int
    public var agentHas: Int
    public var chatShows: Int
    public var added: Int
    public var attached: Int
    public var waiting: Int
    public var keptElsewhere: Int
    public var skipped: Int
    public var syncedUpTo: Turn?
    public var waitingReason: String?
    public var nextMessage: NextMessage
    public var usage: Usage
    public var sinceYouLeft: SinceYouLeft?
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(tool: String, chat: Chat, condition: SideCondition, total: Int, agentHas: Int, chatShows: Int, added: Int, attached: Int, waiting: Int, keptElsewhere: Int, skipped: Int, syncedUpTo: Turn? = nil, waitingReason: String? = nil, nextMessage: NextMessage, usage: Usage, sinceYouLeft: SinceYouLeft? = nil, notes: [Note], toolLabel: String? = nil) {
        self.tool = tool
        self.toolLabel = toolLabel
        self.chat = chat
        self.condition = condition
        self.total = total
        self.agentHas = agentHas
        self.chatShows = chatShows
        self.added = added
        self.attached = attached
        self.waiting = waiting
        self.keptElsewhere = keptElsewhere
        self.skipped = skipped
        self.syncedUpTo = syncedUpTo
        self.waitingReason = waitingReason
        self.nextMessage = nextMessage
        self.usage = usage
        self.sinceYouLeft = sinceYouLeft
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case tool
        case toolLabel = "tool_label"
        case chat
        case condition
        case total
        case agentHas = "agent_has"
        case chatShows = "chat_shows"
        case added
        case attached
        case waiting
        case keptElsewhere = "kept_elsewhere"
        case skipped
        case syncedUpTo = "synced_up_to"
        case waitingReason = "waiting_reason"
        case nextMessage = "next_message"
        case usage
        case sinceYouLeft = "since_you_left"
        case notes
    }
}

/// Step data returned by the engine.
public struct Step: Codable, Equatable, Sendable {
    public var tool: String
    public var toolLabel: String?
    public var displayLabel: String { toolLabel ?? tool }
    public var action: String
    public var turns: [Int]
    public var reason: String
    public var needs: [String]
    public var notes: [Note]

    /// Creates a contract value without requiring JSON.
    public init(tool: String, action: String, turns: [Int], reason: String, needs: [String], notes: [Note], toolLabel: String? = nil) {
        self.tool = tool
        self.toolLabel = toolLabel
        self.action = action
        self.turns = turns
        self.reason = reason
        self.needs = needs
        self.notes = notes
    }

    private enum CodingKeys: String, CodingKey {
        case tool
        case toolLabel = "tool_label"
        case action
        case turns
        case reason
        case needs
        case notes
    }
}

/// Plan data returned by the engine.
public struct Plan: Codable, Equatable, Sendable {
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

/// SetupFinding data returned by the engine.
public struct SetupFinding: Codable, Equatable, Sendable {
    public var id: String
    public var ok: Bool
    public var note: Note

    /// Creates a contract value without requiring JSON.
    public init(id: String, ok: Bool, note: Note) {
        self.id = id
        self.ok = ok
        self.note = note
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case ok
        case note
    }
}

/// SetupTool data returned by the engine.
public struct SetupTool: Codable, Equatable, Sendable {
    public var tool: String
    public var toolLabel: String?
    public var displayLabel: String { toolLabel ?? tool }
    public var installed: Bool
    public var ready: Bool
    public var version: String?
    public var findings: [SetupFinding]
    public var facts: [String: JSONValue]
    public var linkModes: [LinkModeOption]?

    /// Creates a contract value without requiring JSON.
    public init(tool: String, installed: Bool, ready: Bool, version: String? = nil, findings: [SetupFinding], facts: [String: JSONValue], toolLabel: String? = nil, linkModes: [LinkModeOption]? = nil) {
        self.tool = tool
        self.toolLabel = toolLabel
        self.installed = installed
        self.ready = ready
        self.version = version
        self.findings = findings
        self.facts = facts
        self.linkModes = linkModes
    }

    private enum CodingKeys: String, CodingKey {
        case tool
        case toolLabel = "tool_label"
        case installed
        case ready
        case version
        case findings
        case facts
        case linkModes = "link_modes"
    }
}

/// Suggestion data returned by the engine.
public struct Suggestion: Codable, Equatable, Sendable {
    public var a: Chat
    public var b: Chat
    public var matchedTurns: Int

    /// Creates a contract value without requiring JSON.
    public init(a: Chat, b: Chat, matchedTurns: Int) {
        self.a = a
        self.b = b
        self.matchedTurns = matchedTurns
    }

    private enum CodingKeys: String, CodingKey {
        case a
        case b
        case matchedTurns = "matched_turns"
    }
}

/// LinkSummary data returned by the engine.
public struct LinkSummary: Codable, Equatable, Sendable {
    public var linkID: Int
    public var sides: [String: Chat]
    public var mode: String
    public var paused: Bool
    public var headline: Note
    public var inSync: Bool
    public var decisionNeeded: Bool
    public var needsAttention: Bool?

    /// Creates a contract value without requiring JSON.
    public init(linkID: Int, sides: [String: Chat], mode: String, paused: Bool, headline: Note, inSync: Bool, decisionNeeded: Bool, needsAttention: Bool? = nil) {
        self.linkID = linkID
        self.sides = sides
        self.mode = mode
        self.paused = paused
        self.headline = headline
        self.inSync = inSync
        self.decisionNeeded = decisionNeeded
        self.needsAttention = needsAttention
    }

    private enum CodingKeys: String, CodingKey {
        case linkID = "link_id"
        case sides
        case mode
        case paused
        case headline
        case inSync = "in_sync"
        case decisionNeeded = "decision_needed"
        case needsAttention = "needs_attention"
    }
}

/// SameFile data returned by the engine.
public struct SameFile: Codable, Equatable, Sendable {
    public var file: String
    public var turns: [Int]

    /// Creates a contract value without requiring JSON.
    public init(file: String, turns: [Int]) {
        self.file = file
        self.turns = turns
    }

    private enum CodingKeys: String, CodingKey {
        case file
        case turns
    }
}

/// HistoryEvent data returned by the engine.
public struct HistoryEvent: Codable, Equatable, Sendable {
    public var id: Int
    public var at: String
    public var kind: String
    public var tool: String?
    public var turns: [Int]
    public var text: String
    public var canUndo: Bool
    public var canRestore: Bool

    /// Creates a contract value without requiring JSON.
    public init(id: Int, at: String, kind: String, tool: String? = nil, turns: [Int], text: String, canUndo: Bool, canRestore: Bool) {
        self.id = id
        self.at = at
        self.kind = kind
        self.tool = tool
        self.turns = turns
        self.text = text
        self.canUndo = canUndo
        self.canRestore = canRestore
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case at
        case kind
        case tool
        case turns
        case text
        case canUndo = "can_undo"
        case canRestore = "can_restore"
    }
}

/// RemovedTurn data returned by the engine.
public struct RemovedTurn: Codable, Equatable, Sendable {
    public var turn: Turn
    public var onlyHere: Bool

    /// Creates a contract value without requiring JSON.
    public init(turn: Turn, onlyHere: Bool) {
        self.turn = turn
        self.onlyHere = onlyHere
    }

    private enum CodingKeys: String, CodingKey {
        case turn
        case onlyHere = "only_here"
    }
}

/// BriefDetails data returned by the engine.
public struct BriefDetails: Codable, Equatable, Sendable {
    public var writer: String
    public var tokens: Int
    public var pinned: [Int]

    /// Creates a contract value without requiring JSON.
    public init(writer: String, tokens: Int, pinned: [Int]) {
        self.writer = writer
        self.tokens = tokens
        self.pinned = pinned
    }

    private enum CodingKeys: String, CodingKey {
        case writer
        case tokens
        case pinned
    }
}

/// Settings data returned by the engine.
public struct Settings: Codable, Equatable, Sendable {
    public var noticeOnAttach: Bool
    public var offerRelaunch: Bool
    public var addToIdleClaude: String
    public var offerSwitchAtLimit: Bool
    public var merge: String
    public var briefThresholdTokens: Double
    public var hideScriptChats: Bool
    public var titleTag: Bool
    public var theme: String
    public var glass: Double

    /// Creates a contract value without requiring JSON.
    public init(noticeOnAttach: Bool, offerRelaunch: Bool, addToIdleClaude: String, offerSwitchAtLimit: Bool, merge: String, briefThresholdTokens: Double, hideScriptChats: Bool, titleTag: Bool, theme: String, glass: Double) {
        self.noticeOnAttach = noticeOnAttach
        self.offerRelaunch = offerRelaunch
        self.addToIdleClaude = addToIdleClaude
        self.offerSwitchAtLimit = offerSwitchAtLimit
        self.merge = merge
        self.briefThresholdTokens = briefThresholdTokens
        self.hideScriptChats = hideScriptChats
        self.titleTag = titleTag
        self.theme = theme
        self.glass = glass
    }

    private enum CodingKeys: String, CodingKey {
        case noticeOnAttach = "notice_on_attach"
        case offerRelaunch = "offer_relaunch"
        case addToIdleClaude = "add_to_idle_claude"
        case offerSwitchAtLimit = "offer_switch_at_limit"
        case merge
        case briefThresholdTokens = "brief_threshold_tokens"
        case hideScriptChats = "hide_script_chats"
        case titleTag = "title_tag"
        case theme
        case glass
    }
}
