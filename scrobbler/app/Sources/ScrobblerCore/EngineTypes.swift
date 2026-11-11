import Foundation

/// The play being listened to: everything a listen record is built from, and everything a
/// restart needs to carry on with it, so it is what `state/open_play.json` holds.
public struct OpenPlay: Codable, Equatable, Sendable {
  /// The play's ID, a lowercase UUID shared by every piece of the play.
  public var playID: String
  /// Which piece of the play this is, counting from 1; a long pause starts the next.
  public var piece: Int
  /// The track's persistent ID, normalized.
  public var persistentID: String
  /// When this piece started, in Unix seconds.
  public var startedAt: Double
  /// Seconds of this piece heard so far.
  public var heardSeconds: Double
  /// The position the last read found, in milliseconds.
  public var lastPositionMs: Int?
  /// The newest track length read, in milliseconds.
  public var durationMs: Int?
  /// The track as the snapshot read found it; nil until the read arrives, or if it failed.
  public var snapshot: TrackSnapshot?
  /// The notice's track name, the fallback when there is no snapshot.
  public var noticeName: String?
  /// The notice's artist, the fallback when there is no snapshot.
  public var noticeArtist: String?
  /// The notice's album, the fallback when there is no snapshot.
  public var noticeAlbum: String?
  /// When the play was paused, in Unix seconds; nil while it plays.
  public var pausedAt: Double?

  /// A play with every field given.
  public init(
    playID: String, piece: Int, persistentID: String, startedAt: Double, heardSeconds: Double,
    lastPositionMs: Int?, durationMs: Int?, snapshot: TrackSnapshot?, noticeName: String?,
    noticeArtist: String?, noticeAlbum: String?, pausedAt: Double?
  ) {
    self.playID = playID
    self.piece = piece
    self.persistentID = persistentID
    self.startedAt = startedAt
    self.heardSeconds = heardSeconds
    self.lastPositionMs = lastPositionMs
    self.durationMs = durationMs
    self.snapshot = snapshot
    self.noticeName = noticeName
    self.noticeArtist = noticeArtist
    self.noticeAlbum = noticeAlbum
    self.pausedAt = pausedAt
  }
}

/// One thing the engine is told; every case carries the time it happened, in Unix seconds,
/// so the engine itself never reads a clock.
public enum EngineInput: Sendable, Equatable {
  /// A debounced playerInfo notice.
  case notice(PlayerNotice, at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
  /// A position read's result.
  case position(PositionRead, at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
  /// A snapshot read's result.
  case snapshot(TrackSnapshot, at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
  /// A snapshot read of `persistentID` that failed.
  case snapshotFailed(persistentID: String, SnapshotReadError, at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
  /// Music quit.
  case musicQuit(at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
  /// The app's periodic timer.
  case heartbeat(at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
  /// The play saved before the app last stopped, read once at start.
  case restored(OpenPlay, at: Double)
  // swiftlint:disable:previous identifier_name - a case label, not a variable; callers write `at:`
}

/// One thing the engine asks the live layer to do.
public enum EngineEffect: Sendable, Equatable {
  /// Read the snapshot of `persistentID`.
  case readSnapshot(persistentID: String)
  /// Start the position reads.
  case startPolling
  /// Stop the position reads.
  case stopPolling
  /// Queue a finished listen.
  case enqueue(ListenRecord)
  /// Send what is playing now.
  case nowPlaying(NowPlayingRecord)
  /// Save the open play, or remove the saved one when nil.
  case saveOpenPlay(OpenPlay?)
  /// A play passed the floor but could not be built within the contract; counted in
  /// `status.json`.
  case unrecordable
  /// Whether the system now refuses to let the scrobbler script Music.
  case automationDenied(Bool)
}
