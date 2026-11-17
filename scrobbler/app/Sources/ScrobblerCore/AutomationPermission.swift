/// The system's answer to whether this app may send Apple events to Music.
///
/// The live bridge asks with `AEDeterminePermissionToAutomateTarget`, which prompts the
/// user when they have not yet answered and waits as long as they take; this is what its
/// status means.
public enum AutomationPermission: Sendable, Equatable {
  /// The user allowed it.
  case granted
  /// The user refused it, or turned it off in System Settings.
  case denied
  /// Music is not running, so there was nothing to ask about.
  case musicNotRunning
  /// Any other status the system gave, by its number.
  case other(Int)

  /// `noErr`: the events may be sent.
  static let statusGranted = 0

  /// The answer an `OSStatus` of `status` stands for.
  public init(status: Int) {
    switch status {
    case Self.statusGranted: self = .granted
    case AppleEventError.notPermitted, AppleEventError.wouldRequireConsent: self = .denied
    case AppleEventError.appNotRunning, AppleEventError.connectionInvalid:
      self = .musicNotRunning
    default: self = .other(status)
    }
  }
}

/// The Apple event error numbers the scrobbler tells apart, shared by the permission
/// answer and the reads' AppleScript errors.
enum AppleEventError {
  /// errAEEventNotPermitted: the system refused to let this app send Apple events to Music.
  static let notPermitted = -1743
  /// errAEEventWouldRequireUserConsent: sending would need a consent the user never gave.
  static let wouldRequireConsent = -1744
  /// errAETimeout: no reply came in time, as when a consent prompt was left unanswered.
  static let timedOut = -1712
  /// errAENoSuchObject: the current track went away during the read.
  static let noSuchObject = -1728
  /// procNotFound: Music is not running, or quit before the event reached it.
  static let appNotRunning = -600
  /// connectionInvalid: Music quit while the read, or the permission request, was under way.
  static let connectionInvalid = -609
}
