import Foundation

/// Both stages of a second opinion and its retained asynchronous run.
public struct OpinionResponse: Decodable, Sendable {
    public let plan: Plan?
    public let requestID: String?
    public let state: String?
    public let answer: AskResult?
    public let answerID: String?
    public let answerText: String?
    public let notes: [Note]
    public let error: EngineCommandError?
    public let estimatedTokens: Int?
    public let readOnly: Bool?
    public let stage: String?
    public let deadlineAt: String?
    public let expiresAt: String?
    enum CodingKeys: String, CodingKey {
        case planID = "plan_id", requestID = "request_id", state, result, answer, notes, error, stage
        case estimatedTokens = "estimated_tokens", readOnly = "read_only", answerID = "answer_id"
        case deadlineAt = "deadline_at", expiresAt = "expires_at"
    }
    private struct Result: Decodable { let answer: String?; let error: EngineCommandError? }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        plan = c.contains(.planID) ? try Plan(from: decoder) : nil
        requestID = try c.decodeIfPresent(String.self, forKey: .requestID)
        state = try c.decodeIfPresent(String.self, forKey: .state)
        notes = try c.decodeIfPresent([Note].self, forKey: .notes) ?? []
        stage = try c.decodeIfPresent(String.self, forKey: .stage)
        estimatedTokens = try c.decodeIfPresent(Int.self, forKey: .estimatedTokens)
        readOnly = try c.decodeIfPresent(Bool.self, forKey: .readOnly)
        answerID = try c.decodeIfPresent(String.self, forKey: .answerID)
        answerText = try c.decodeIfPresent(String.self, forKey: .answer)
        deadlineAt = try c.decodeIfPresent(String.self, forKey: .deadlineAt)
        expiresAt = try c.decodeIfPresent(String.self, forKey: .expiresAt)
        let nested = try c.decodeIfPresent(Result.self, forKey: .result)
        error = try nested?.error ?? c.decodeIfPresent(EngineCommandError.self, forKey: .error)
        answer = nested?.answer != nil ? try c.decode(AskResult.self, forKey: .result) : nil
    }
}

/// A typed projection of capability fields; unknown fields stay in the original map.
public struct Capabilities: Codable, Equatable, Sendable {
    public let writeWindow: String?
    public let newChatVisible: String?
    public let addedTurnVisible: String?
    public let canCut: Bool?
    public let canPlace: Bool?
    public let canReleaseChat: Bool?
    public let opensAtChat: Bool?
    public let limitHasResetTime: Bool?
    public let contextSizeKnown: Bool?
    public let hooksNeed: String?
    public let checkedVersions: [String]?
    public let replaysToolCalls: Bool?
    enum CodingKeys: String, CodingKey {
        case writeWindow = "write_window", newChatVisible = "new_chat_visible", addedTurnVisible = "added_turn_visible"
        case canCut = "can_cut", canPlace = "can_place", canReleaseChat = "can_release_chat", opensAtChat = "opens_at_chat"
        case limitHasResetTime = "limit_has_reset_time", contextSizeKnown = "context_size_known", hooksNeed = "hooks_need"
        case checkedVersions = "checked_versions", replaysToolCalls = "replays_tool_calls"
    }
}
public extension SetupTool {
    var capabilities: Capabilities? {
        guard let data = try? JSONEncoder().encode(facts) else { return nil }
        return try? JSONDecoder().decode(Capabilities.self, from: data)
    }
}
