/// What one run of a Music script gave the live bridge.
public enum ScriptAnswer: Sendable, Equatable {
  /// The script ran; its result's text, or nil when the result was not text.
  case returned(String?)
  /// The script raised an error; its `NSAppleScriptErrorNumber`, when it had one.
  case raised(number: Int?)

  /// This answer as a read's result: returned text goes to `parse` exactly as Music wrote
  /// it, untrimmed, and an error is mapped without parsing anything.
  public func parsed<T>(by parse: (String) -> Result<T, SnapshotReadError>)
    -> Result<T, SnapshotReadError>
  {
    switch self {
    case .returned(let text?): parse(text)
    case .returned(nil): .failure(.malformed("the script's result is not text"))
    case .raised(let number): .failure(.fromAppleScriptError(number: number))
    }
  }
}

extension SnapshotReadError {
  /// The read error an AppleScript error numbered `number` stands for; a number that is
  /// missing or not one of these is a malformed read, named by its number.
  public static func fromAppleScriptError(number: Int?) -> SnapshotReadError {
    switch number {
    case AppleEventError.notPermitted, AppleEventError.wouldRequireConsent: .automationDenied
    case AppleEventError.timedOut: .timedOut
    case AppleEventError.noSuchObject: .noCurrentTrack
    case AppleEventError.appNotRunning, AppleEventError.connectionInvalid: .musicNotRunning
    case let number?: .malformed("AppleScript error \(number)")
    case nil: .malformed("AppleScript error without a number")
    }
  }
}
