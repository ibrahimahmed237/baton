import Foundation

/// Runs the Baton CLI without a shell and decodes its stdout contract.
public struct ProcessEngine: EngineTransport {
    public let executable: URL
    public let prefixArguments: [String]
    public let environment: [String: String]?

    /// Defaults to PATH lookup; an explicit executable supports tests and installed engines.
    public init(
        executable: URL = URL(fileURLWithPath: "/usr/bin/env"),
        prefixArguments: [String] = ["baton"],
        environment: [String: String]? = nil
    ) {
        self.executable = executable
        self.prefixArguments = prefixArguments
        self.environment = environment
    }

    /// Runs a command, checks its error envelope, then decodes its typed result.
    public func response<Result: Decodable & Sendable>(
        command: String, arguments: [String], as type: Result.Type
    ) async throws -> Result {
        let subcommands = [
            "setup-install": "setup", "merge-show": "merge", "ask-add": "ask",
            "settings-get": "settings", "settings-set": "settings"
        ]
        let jsonArguments = command == "catch-up" ? [] : ["--json"]
        let output = try await run(
            arguments: prefixArguments + [subcommands[command] ?? command] + arguments + jsonArguments
        )
        try checkEngineError(output.stdout)
        guard output.status == 0 else {
            throw EngineProcessError(status: output.status, stderr: String(decoding: output.stderr, as: UTF8.self))
        }
        if command == "catch-up" {
            let result = CatchUpResult(output: String(decoding: output.stdout, as: UTF8.self))
            return try JSONDecoder().decode(type, from: JSONEncoder().encode(result))
        }
        return try decodeResponse(type, from: output.stdout)
    }

    private struct Output: Sendable {
        let stdout: Data
        let stderr: Data
        let status: Int32
    }

    private func run(arguments: [String]) async throws -> Output {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global().async {
                do {
                    let process = Process()
                    let stdout = Pipe()
                    let stderr = Pipe()
                    process.executableURL = executable
                    process.arguments = arguments
                    process.environment = environment
                    process.standardOutput = stdout
                    process.standardError = stderr
                    try process.run()
                    let diagnostic = PipeData()
                    let readers = DispatchGroup()
                    // Blocking I/O belongs on GCD, which can add workers as needed.
                    DispatchQueue.global().async(group: readers) {
                        diagnostic.store(stderr.fileHandleForReading.readDataToEndOfFile())
                    }
                    let output = stdout.fileHandleForReading.readDataToEndOfFile()
                    process.waitUntilExit()
                    readers.wait()
                    continuation.resume(returning: Output(
                        stdout: output, stderr: diagnostic.value, status: process.terminationStatus
                    ))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}

// The stderr reader and process worker exchange data across GCD queues.
private final class PipeData: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    func store(_ value: Data) {
        lock.withLock { data = value }
    }

    var value: Data { lock.withLock { data } }
}
