import Foundation
import Testing
@testable import BatonKit

private actor ImmediateRecordingTransport: EngineTransport {
    var calls: [(String, [String])] = []
    func response<Result: Decodable & Sendable>(command: String, arguments: [String], as type: Result.Type) async throws -> Result {
        calls.append((command, arguments))
        return try await FixtureEngine(directory: FixtureDecodingTests.fixtures).response(command: command, arguments: arguments, as: type)
    }
}

struct ImmediateCommandTests {
    @Test
    func pauseAndResumeNeverCarryPlanFlagsEvenForLegacyMutationArguments() async throws {
        let transport = ImmediateRecordingTransport()
        _ = try await transport.pause(link: 7)
        _ = try await transport.resume(link: 7)
        _ = try await transport.pause(link: 7, mutation: .confirm("unused"))
        _ = try await transport.resume(link: 7, mutation: .confirm("unused"))
        let calls = await transport.calls
        #expect(calls.map(\.0) == ["pause", "resume", "pause", "resume"])
        #expect(calls.allSatisfy { $0.1 == ["--link", "7"] })
    }
}

struct LinkFixtureRoutingTests {
    @Test
    func selectedLinksGetDistinctHandMadeStatusesWhileOtherCommandsKeepTheirDefault() async throws {
        let engine = FixtureEngine(directory: FixtureDecodingTests.fixtures, state: "d3_filled")
        let merge = try await engine.status(link: 3)
        let relaunch = try await engine.status(link: 4)
        let synced = try await engine.status(link: 5)
        #expect(merge.linkID == 3 && merge.decisionNeeded)
        #expect(relaunch.linkID == 4 && relaunch.sides["claude"]?.added == 2)
        #expect(relaunch.sides["claude"]?.notes.contains { $0.id == "relaunch_to_see" } == true)
        #expect(synced.linkID == 5 && synced.inSync)
        #expect(try await engine.links().links.count == 3)
    }
}
