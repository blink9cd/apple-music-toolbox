// The runner's command line, `--python <abs> --script <abs> -- [script args...]`, parsed
// with no side effects so every refusal is a unit test.
import Foundation

/// Why the runner refuses or fails, each with the exit code it ends the runner with.
public enum RunnerError: Error, Equatable, Sendable {
  /// The command line is malformed; the text says how.
  case usage(String)
  /// The named interpreter or script is not in the bundle's allowlist.
  case notAllowed(String)
  /// The runner's own bundle signature does not verify.
  case selfCheckFailed
  /// The bundle's Info.plist holds no well-formed allowlist.
  case allowlistUnreadable
  /// `posix_spawn` returned this error number.
  case spawnFailed(Int32)

  /// 1 when the spawn itself failed, 2 for every refusal.
  public var exitCode: Int32 {
    if case .spawnFailed = self { return 1 }
    return 2
  }

  /// The one line reported after `ERROR: `.
  public var message: String {
    switch self {
    case .usage(let text): text
    case .notAllowed(let path): "not in the runner's allowlist: \(path)"
    case .selfCheckFailed: "the runner's own signature does not verify"
    case .allowlistUnreadable: "the runner's allowlist is missing or malformed"
    case .spawnFailed(let number):
      "could not start the child: \(String(cString: strerror(number))) (errno \(number))"
    }
  }
}

/// A parsed command line: the interpreter, the script it runs, and the script's own
/// arguments, which are everything after the `--` separator, passed through untouched.
public struct Arguments: Equatable, Sendable {
  /// The two options the runner takes, each exactly once.
  static let pythonFlag = "--python"
  static let scriptFlag = "--script"
  /// Ends the runner's own options; it is required so a script argument can never be
  /// mistaken for one of them.
  static let separator = "--"

  public let python: String
  public let script: String
  public let rest: [String]

  public init(python: String, script: String, rest: [String]) {
    self.python = python
    self.script = script
    self.rest = rest
  }

  /// Parse `argv`, the arguments after the program name.
  public static func parse(_ argv: [String]) throws(RunnerError) -> Arguments {
    let end = argv.firstIndex(of: separator)
    let options = try readOptions(Array(argv[..<(end ?? argv.count)]))
    let python = try required(options[pythonFlag], flag: pythonFlag)
    let script = try required(options[scriptFlag], flag: scriptFlag)
    // Checked last, so a malformed or missing option is the complaint a user sees first.
    guard let end else { throw .usage("-- must end the runner's own options") }
    return Arguments(python: python, script: script, rest: Array(argv[(end + 1)...]))
  }

  /// The `--python` and `--script` values in `options`, which holds no separator.
  static func readOptions(_ options: [String]) throws(RunnerError) -> [String: String] {
    var found: [String: String] = [:]
    var index = 0
    while index < options.count {
      let flag = options[index]
      guard flag == pythonFlag || flag == scriptFlag else {
        throw .usage("unknown option: \(flag)")
      }
      guard index + 1 < options.count else { throw .usage("\(flag) needs a value") }
      guard found[flag] == nil else { throw .usage("\(flag) given twice") }
      found[flag] = options[index + 1]
      index += 2
    }
    return found
  }

  /// `value` when it was given as an absolute path.
  static func required(_ value: String?, flag: String) throws(RunnerError) -> String {
    guard let value else { throw .usage("\(flag) is required") }
    guard value.hasPrefix("/") else { throw .usage("\(flag) must be an absolute path") }
    return value
  }
}
