import Foundation
import Testing
@testable import BatonKit

struct ProcessEngineTests {
    private func withScript(
        _ body: String, operation: (ProcessEngine, URL) async throws -> Void
    ) async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let executable = directory.appendingPathComponent("fake-baton")
        try ("#!/bin/sh\n" + body).write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        let engine = ProcessEngine(executable: executable, prefixArguments: [])
        try await operation(engine, directory)
    }

    @Test
    func testRefusalAndCrashBothCarryTheEngineNote() async throws {
        let noteData = try Data(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("note.sample.json"))
        let note = try JSONDecoder().decode(Note.self, from: noteData)
        for status in [0, 9] {
            let failure = EngineCommandError(kind: status == 0 ? "chat_changed" : "internal", note: note)
            let json = String(decoding: try JSONEncoder().encode(["error": failure]), as: UTF8.self)
            try await withScript("cat <<'JSON'\n\(json)\nJSON\nexit \(status)\n") { engine, _ in
                do {
                    _ = try await engine.links()
                    Issue.record("Error envelope must throw even when the process exits zero")
                } catch let error as EngineCommandError {
                    #expect(error.kind == failure.kind)
                    #expect(error.note == note)
                }
            }
        }
    }

    @Test
    func testUnstructuredNonzeroExitPreservesStatusAndStderr() async throws {
        try await withScript("printf 'sample diagnostic' >&2\nexit 7\n") { engine, _ in
            do {
                _ = try await engine.links()
                Issue.record("Nonzero exit must throw")
            } catch let error as EngineProcessError {
                #expect(error.status == 7)
                #expect(error.stderr == "sample diagnostic")
            }
        }
    }

    @Test
    func testSuccessAddsJSONFlagAndIgnoresUnknownFields() async throws {
        let script = """
        [ "$#" -eq 2 ] && [ "$1" = links ] && [ "$2" = --json ] || exit 88
        printf '%s' '{"links": [], "future": true}'
        """
        try await withScript(script) { engine, _ in
            let result = try await engine.links()
            #expect(result.links.isEmpty)
        }
    }

    @Test
    func testMalformedSuccessRemainsADecodingError() async throws {
        try await withScript("printf '%s' '{\"wrong_shape\": []}'") { engine, _ in
            do {
                _ = try await engine.links()
                Issue.record("Invalid success must throw")
            } catch {
                #expect(error is DecodingError)
            }
        }
    }

    @Test
    func testArgumentsArePassedLiterallyAndConfirmationIsExclusive() async throws {
        let name = "Fictional name; $(exit 99) ' \"\nsecond line"
        let json = try String(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("rename.sample.json"), encoding: .utf8)
        let script = """
        printf '%s\\0' "$@" > "$(dirname "$0")/arguments"
        cat <<'JSON'
        \(json)
        JSON
        """
        try await withScript(script) { engine, directory in
            _ = try await engine.rename(link: 3, name: name, tools: ["claude", "codex"], mutation: .confirm("p_sample"))
            let data = try Data(contentsOf: directory.appendingPathComponent("arguments"))
            let arguments = String(decoding: data, as: UTF8.self).split(separator: "\0").map(String.init)
            #expect(arguments == ["rename", "--link", "3", "--name", name, "--tools", "claude,codex", "--confirm", "p_sample", "--json"])
            #expect(!(arguments.contains("--dry-run")))
        }
    }

    @Test
    func testSubcommandDispatchAndPreview() async throws {
        let json = try String(contentsOf: FixtureDecodingTests.fixtures.appendingPathComponent("setup-install.sample.json"), encoding: .utf8)
        let script = """
        [ "$#" -eq 6 ] && [ "$1" = setup ] && [ "$2" = install ] && [ "$3" = --tool ] && [ "$4" = claude ] && [ "$5" = --dry-run ] && [ "$6" = --json ] || exit 88
        cat <<'JSON'
        \(json)
        JSON
        """
        try await withScript(script) { engine, _ in
            let result = try await engine.setupInstall(tool: "claude")
            #expect(result.tools.first?.tool == "claude")
        }
    }

    @Test
    func testCatchUpPreservesRawOutputAndOmitsJSONFlag() async throws {
        let script = """
        [ "$#" -eq 5 ] && [ "$1" = catch-up ] && [ "$2" = --tool ] && [ "$3" = claude ] && [ "$4" = --chat ] && [ "$5" = sample-a ] || exit 88
        printf 'fictional hook output\\n'
        """
        try await withScript(script) { engine, _ in
            let result = try await engine.catchUp(tool: "claude", chat: "sample-a")
            #expect(result.output == "fictional hook output\n")
        }
    }

    @Test
    func testBothOutputPipesAreDrained() async throws {
        let script = """
        /usr/bin/head -c 262144 /dev/zero >&2
        printf '%s' '{"links": []}'
        """
        try await withScript(script) { engine, _ in
            let result = try await engine.links()
            #expect(result.links.isEmpty)
        }
    }

    @Test
    func testConcurrentProcessesDrainBothPipes() async throws {
        let script = """
        /usr/bin/head -c 262144 /dev/zero >&2
        printf '%s' '{"links": []}'
        """
        try await withScript(script) { engine, _ in
            try await withThrowingTaskGroup(of: LinksResult.self) { group in
                for _ in 0..<16 {
                    group.addTask { try await engine.links() }
                }
                var completed = 0
                for try await result in group {
                    #expect(result.links.isEmpty)
                    completed += 1
                }
                #expect(completed == 16)
            }
        }
    }
}
