import Foundation

/// What the executable was asked to do.
public enum Command: Equatable, Sendable {
  /// Run as the scrobbler: the word `run` alone, which is what the launch agent passes.
  case run
  /// Replay the trace at `trace`, writing its listens into the folder `out`.
  case replay(trace: URL, out: URL)
  /// Print the version.
  case version
}

/// A command line that names no command; `message` says what was wrong with it.
public struct UsageError: Error, Equatable, Sendable {
  /// What was wrong, in one line.
  public let message: String

  /// A usage error saying `message`.
  public init(message: String) {
    self.message = message
  }
}

/// Reads the executable's arguments. Every value is a named option, never a position.
public enum CommandLineParser {
  /// The run command's word.
  static let runWord = "run"
  /// The replay command's word.
  static let replayWord = "replay"
  /// The version option.
  static let versionOption = "--version"
  /// The replay command's options, each taking one value.
  static let traceOption = "--trace"
  static let outOption = "--out"

  /// The command `arguments` name, the program's own name left out.
  public static func parse(_ arguments: [String]) -> Result<Command, UsageError> {
    // One way to start, the one the launch agent uses: an empty command line runs nothing.
    guard let first = arguments.first else {
      return .failure(UsageError(message: "no command given"))
    }
    let rest = Array(arguments.dropFirst())
    switch first {
    case runWord:
      return alone(rest, .run)
    case versionOption:
      return alone(rest, .version)
    case replayWord:
      return Result { () throws(UsageError) -> Command in try replay(rest) }
    default:
      return .failure(unknown(first))
    }
  }

  /// The usage text, naming the program as `program`, which the caller takes from argv.
  public static func usage(program: String) -> String {
    """
    usage: \(program) \(runWord)
           \(program) \(replayWord) \(traceOption) <trace.jsonl> \(outOption) <folder>
           \(program) \(versionOption)

    \(runWord) runs as the scrobbler. \(replayWord) feeds a recorded trace of
    Music's notices and reads to the play engine and writes the listens it would queue
    into <folder>; it reads no Music, no config and no network.
    """
  }

  /// `command` when nothing follows its word.
  private static func alone(_ rest: [String], _ command: Command) -> Result<Command, UsageError> {
    rest.first.map { .failure(unexpected($0)) } ?? .success(command)
  }

  /// The replay command from its options.
  private static func replay(_ arguments: [String]) throws(UsageError) -> Command {
    let values = try options(arguments, allowed: [traceOption, outOption])
    guard let trace = values[traceOption] else { throw needs(traceOption) }
    guard let out = values[outOption] else { throw needs(outOption) }
    return .replay(trace: URL(fileURLWithPath: trace), out: URL(fileURLWithPath: out))
  }

  /// Each `--name value` pair in `arguments`, every name one of `allowed`, none twice.
  private static func options(_ arguments: [String], allowed: Set<String>)
    throws(UsageError) -> [String: String]
  {
    var values: [String: String] = [:]
    var index = 0
    while index < arguments.count {
      let name = arguments[index]
      guard allowed.contains(name) else { throw unknown(name) }
      guard values[name] == nil else { throw UsageError(message: "\(name) given twice") }
      let valueIndex = index + 1
      guard valueIndex < arguments.count, !arguments[valueIndex].hasPrefix("-") else {
        throw UsageError(message: "\(name) needs a value")
      }
      values[name] = arguments[valueIndex]
      index = valueIndex + 1
    }
    return values
  }

  /// An argument that is not one of the expected words or options.
  private static func unknown(_ argument: String) -> UsageError {
    argument.hasPrefix("-")
      ? UsageError(message: "unknown option: \(argument)") : unexpected(argument)
  }

  /// An argument where none belongs.
  private static func unexpected(_ argument: String) -> UsageError {
    UsageError(message: "unexpected argument: \(argument)")
  }

  /// A replay missing its `option`.
  private static func needs(_ option: String) -> UsageError {
    UsageError(message: "\(replayWord) needs \(option)")
  }
}
