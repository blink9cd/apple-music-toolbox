import Foundation
import Testing

@testable import ScrobblerCore

@Test func runRunsTheApp() {
  #expect(CommandLineParser.parse(["run"]) == .success(.run))
}

@Test func versionPrintsTheVersion() {
  #expect(CommandLineParser.parse(["--version"]) == .success(.version))
}

@Test func replayTakesItsTwoOptionsInEitherOrder() {
  let expected = Command.replay(
    trace: URL(fileURLWithPath: "trace.jsonl"), out: URL(fileURLWithPath: "out"))
  #expect(
    CommandLineParser.parse(["replay", "--trace", "trace.jsonl", "--out", "out"])
      == .success(expected))
  #expect(
    CommandLineParser.parse(["replay", "--out", "out", "--trace", "trace.jsonl"])
      == .success(expected))
}

@Test(arguments: [
  ([], "no command given"),
  (["run", "x"], "unexpected argument: x"),
  (["trace.jsonl"], "unexpected argument: trace.jsonl"),
  (["replay", "trace.jsonl"], "unexpected argument: trace.jsonl"),
  (["--version", "now"], "unexpected argument: now"),
  (["--verbose"], "unknown option: --verbose"),
  (["replay", "--trace", "t", "--out", "o", "--fast"], "unknown option: --fast"),
  (["replay", "--trace"], "--trace needs a value"),
  (["replay", "--trace", "--out", "o"], "--trace needs a value"),
  (["replay", "--out", "o"], "replay needs --trace"),
  (["replay", "--trace", "t"], "replay needs --out"),
  (["replay", "--trace", "a", "--trace", "b", "--out", "o"], "--trace given twice"),
])
func aBadCommandLineIsAUsageError(arguments: [String], message: String) {
  #expect(CommandLineParser.parse(arguments) == .failure(UsageError(message: message)))
}

@Test func theUsageNamesTheProgramItIsGiven() {
  let usage = CommandLineParser.usage(program: "renamed")
  #expect(usage.contains("renamed replay --trace"))
  #expect(usage.contains("renamed --version"))
  #expect(usage.contains("renamed run\n"))
  #expect(!usage.contains(Layout.executable + " "))
}

/// The start word the Python wrapper's launch agent passes, kept in `launch_argument/` beside
/// the package so the wrapper's own test reads the same file.
private let startWordFile = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
  .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
  .appendingPathComponent("launch_argument").appendingPathComponent("start-word.txt")

@Test func theWrappersStartWordRunsTheApp() throws {
  let word = try String(contentsOf: startWordFile, encoding: .utf8)
    .trimmingCharacters(in: .newlines)
  #expect(CommandLineParser.parse([word]) == .success(.run))
}
