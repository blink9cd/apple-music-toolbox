import AppKit
import Foundation
import ScrobblerCore
import Testing

@testable import ScrobblerLive

/// Whether the live switch is on. Every test here reads the real Music.app, so each one is
/// disabled unless `SCROBBLER_LIVE` is "1", and no gate run ever reaches the real host.
let liveSwitchOn = ProcessInfo.processInfo.environment["SCROBBLER_LIVE"] == "1"

/// Whether Music is running, asked of the workspace before any bridge exists.
func musicRunning() -> Bool {
  !NSRunningApplication.runningApplications(withBundleIdentifier: MusicApp.bundleID).isEmpty
}

/// The live smoke test. It reads Music and listens to it, and never controls playback.
/// It prints no track value: every assertion compares values without showing them.
@MainActor @Suite(.serialized) struct LiveSmokeTests {
  /// How long to wait for Music to post a notice of its own.
  static let noticeWait: Duration = .seconds(10)

  @Test(.enabled(if: liveSwitchOn))
  func readsTheCurrentTrackWithoutControllingPlayback() async throws {
    // Run once with Music quit: neither making the bridge nor reading may launch it.
    let wasRunning = musicRunning()
    let bridge = LiveMusicBridge()
    #expect(wasRunning || !bridge.isMusicRunning(), "making the bridge launched Music")
    let position = bridge.readPosition()
    #expect(wasRunning || !bridge.isMusicRunning(), "the position read launched Music")
    let snapshot = bridge.readSnapshot()
    #expect(wasRunning || !bridge.isMusicRunning(), "the snapshot read launched Music")
    #expect(Self.succeededOrNotRunning(position))
    #expect(Self.succeededOrNotRunning(snapshot))
    guard case .success(let read) = position, case .success(let track) = snapshot else { return }
    // Each comparison is made first and only its answer asserted, so a failure shows no ID.
    let sameTrack = read.persistentID == track.persistentID
    #expect(sameTrack, "the two reads named different tracks")
    // Skipped when nothing plays: a stopped player posts no notice to wait for.
    guard read.state == .playing else { return }
    guard let notice = await Self.firstNotice(from: bridge) else {
      print("no notice arrived within 10 s; skip a track to exercise it")
      return
    }
    let noticeMatches = notice.persistentID == track.persistentID
    #expect(noticeMatches, "the notice named another track than the snapshot")
  }

  /// Run with a track current in Music, best a local file playing: the snapshot must parse.
  /// That proves, against the real app, the date handler's joined parts, the location
  /// handler's inner tell block, and the length handler's ceiling comparison. Skipped while
  /// Music is quit; a running Music with no current track fails, since a track must be
  /// current for this test to prove anything.
  @Test(.enabled(if: liveSwitchOn), .enabled("Music is running") { musicRunning() })
  func aCurrentTracksSnapshotParses() throws {
    let bridge = LiveMusicBridge()
    let read = try #require(
      try? bridge.readPosition().get(), "start a track in Music, then run this test again")
    try #require(read.state != .stopped, "start a track in Music, then run this test again")
    let snapshot = bridge.readSnapshot()
    // Compared as a bare success, so a failing run names the error and never a track value.
    #expect((try? snapshot.get()) != nil, "the snapshot did not parse: \(Self.failure(snapshot))")
  }

  /// Whether `result` succeeded, found Music not running, or found its player stopped, the
  /// one state with no current track to read.
  static func succeededOrNotRunning<T>(_ result: Result<T, SnapshotReadError>) -> Bool {
    switch result {
    case .success, .failure(.musicNotRunning), .failure(.noCurrentTrack): true
    case .failure: false
    }
  }

  /// The error `result` failed with, or `none`; a malformed error names a field, never a value.
  static func failure<T>(_ result: Result<T, SnapshotReadError>) -> String {
    guard case .failure(let error) = result else { return "none" }
    return String(describing: error)
  }

  /// The first notice Music posts within `noticeWait`, or nil.
  static func firstNotice(from bridge: LiveMusicBridge) async -> PlayerNotice? {
    var received: PlayerNotice?
    bridge.start(onNotice: { received = received ?? $0 }, onQuit: {})
    let deadline = ContinuousClock.now + noticeWait
    while received == nil, ContinuousClock.now < deadline {
      try? await Task.sleep(for: .milliseconds(100))
    }
    return received
  }
}
