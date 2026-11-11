// The live Music.app bridge.
//
// This target is excluded from coverage as a real-host seam: every decision it could make
// lives in ScrobblerCore, where tests reach it (the tripwire, the script text, the error
// mapping, the parsers and the notice reader). What is left here only calls the system;
// the live smoke test is what proves it.
import AppKit
import Foundation
import ScrobblerCore
import os

/// `MusicBridge` over the real Music.app: two compiled AppleScript reads, the playerInfo
/// notice, and the workspace's word that Music quit.
///
/// It never controls playback and never launches Music: each read first asks whether Music
/// runs, and the scripts ask again before addressing it.
@MainActor public final class LiveMusicBridge: MusicBridge {
  private let log = Logger(subsystem: Layout.bundleID, category: "music")
  // Compiled on first use, after a read's running check, never at creation: the app makes
  // the bridge at every start, and compiling against Music must never be what opens it.
  private lazy var positionScript = Self.compiled(MusicScripts.positionSource)
  private lazy var snapshotScript = Self.compiled(MusicScripts.snapshotSource())
  /// Each observer with the center it was added to, so a second `start` can remove it.
  private var observers: [(center: NotificationCenter, token: any NSObjectProtocol)] = []

  /// The bridge, its scripts not yet compiled. Stops the process inside a test runner
  /// unless the live smoke test was asked for: the tripwire.
  public init() {
    let process = ProcessInfo.processInfo
    let path = Bundle.main.executablePath ?? process.arguments.first ?? ""
    guard LiveGuard.liveBridgeAllowed(environment: process.environment, processPath: path)
    else {
      fatalError("tripwire: the live Music bridge was created inside a test runner")
    }
  }

  /// `source` as a script, compiled once. The texts are fixed, so a compile failure is logged and left
  /// for each run to report: an uncompiled script compiles again when run, and its error
  /// comes back through the run's own mapping.
  private static func compiled(_ source: String) -> NSAppleScript {
    // `NSAppleScript(source:)` is nil only for a nil source, which a `String` never is.
    let script = NSAppleScript(source: source)!
    var error: NSDictionary?
    if !script.compileAndReturnError(&error) {
      Logger(subsystem: Layout.bundleID, category: "music").error(
        "a Music script did not compile: \(Self.label(Self.errorNumber(error)), privacy: .public)")
    }
    return script
  }

  /// Observe Music's playerInfo notice and Music quitting, both delivered on the main queue.
  /// A second call replaces the first one's observers, so no notice arrives twice. Only live
  /// notifications can show that, so it is proven by reading, not by a test.
  public func start(
    onNotice: @escaping @MainActor (PlayerNotice) -> Void, onQuit: @escaping @MainActor () -> Void
  ) {
    for observer in observers { observer.center.removeObserver(observer.token) }
    let distributed = DistributedNotificationCenter.default()
    let workspace = NSWorkspace.shared.notificationCenter
    let notices = distributed.addObserver(
      forName: Notification.Name(MusicApp.playerInfoNotice), object: nil, queue: .main
    ) { note in
      let notice = PlayerNotice.parse(note.userInfo ?? [:])
      MainActor.assumeIsolated { notice.map(onNotice) }
    }
    let quits = workspace.addObserver(
      forName: NSWorkspace.didTerminateApplicationNotification, object: nil, queue: .main
    ) { note in
      let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
      let quitting = MusicApp.isMusic(bundleIdentifier: app?.bundleIdentifier)
      MainActor.assumeIsolated { if quitting { onQuit() } }
    }
    observers = [(distributed, notices), (workspace, quits)]
  }

  /// Whether Music is running, asked of the workspace, which never launches it.
  public func isMusicRunning() -> Bool {
    !NSRunningApplication.runningApplications(withBundleIdentifier: MusicApp.bundleID).isEmpty
  }

  /// The position script's result, parsed; Music not running is checked first.
  public func readPosition() -> Result<PositionRead, SnapshotReadError> {
    guard isMusicRunning() else { return .failure(.musicNotRunning) }
    return run(positionScript).parsed(by: PositionParser.parse)
  }

  /// The snapshot script's result, parsed in this machine's time zone; Music not running is
  /// checked first.
  public func readSnapshot() -> Result<TrackSnapshot, SnapshotReadError> {
    guard isMusicRunning() else { return .failure(.musicNotRunning) }
    return run(snapshotScript).parsed { SnapshotParser.parse($0) }
  }

  /// Run `script` and keep what it gave: its text exactly as Music wrote it, or its error's
  /// number. Only the number leaves the error dictionary; its message is never logged.
  private func run(_ script: NSAppleScript) -> ScriptAnswer {
    var error: NSDictionary?
    let result = script.executeAndReturnError(&error)
    if let error {
      let number = Self.errorNumber(error)
      log.error("a Music script failed: \(Self.label(number), privacy: .public)")
      return .raised(number: number)
    }
    return .returned(result.stringValue)
  }

  /// An error number as logged: public, since it names no track and no message.
  private static func label(_ number: Int?) -> String {
    number.map { "error \($0)" } ?? "an error without a number"
  }

  /// The `NSAppleScriptErrorNumber` in an error dictionary, when there is one.
  private static func errorNumber(_ error: NSDictionary?) -> Int? {
    error?[NSAppleScript.errorNumber] as? Int
  }
}
