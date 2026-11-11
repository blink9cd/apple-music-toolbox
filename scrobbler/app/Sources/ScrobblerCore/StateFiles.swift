import Foundation

/// The heartbeat `status.json` holds: format 1, every time in Unix seconds as a JSON
/// number, and `null` for anything not yet known. The Python status reads it; it never
/// carries the token.
public struct StatusSnapshot: Codable, Equatable, Sendable {
  /// The file format this type writes.
  public static let currentFormat = 1

  /// The file format.
  public var format: Int
  /// The scrobbler's version.
  public var version: String
  /// The running app's process ID.
  public var pid: Int
  /// When the app started.
  public var startedAt: Double
  /// When this snapshot was written.
  public var heartbeatAt: Double
  /// Whether Music is running.
  public var musicRunning = false
  /// Whether Music is playing.
  public var playing = false
  /// How many listens wait in the queue.
  public var queueBacklog = 0
  /// When the oldest queued listen started.
  public var oldestQueuedAt: Double?
  /// How many listens the store refused.
  public var refusedCount = 0
  /// When a listen was last queued.
  public var lastQueuedAt: Double?
  /// When a listen was last accepted by the store.
  public var lastSentAt: Double?
  /// The last send failure, in the drainer's fixed wording.
  public var lastSendError: String?
  /// Plays skipped because the track named no artist or no title.
  public var unrecordableCount = 0
  /// Whether macOS refused the app's request to read Music.
  public var automationDenied = false
  /// What is playing now, when anything is.
  public var nowPlaying: NowPlayingRecord?

  enum CodingKeys: String, CodingKey {
    case format, version, pid
    case startedAt = "started_at"
    case heartbeatAt = "heartbeat_at"
    case musicRunning = "music_running"
    case playing
    case queueBacklog = "queue_backlog"
    case oldestQueuedAt = "oldest_queued_at"
    case refusedCount = "refused_count"
    case lastQueuedAt = "last_queued_at"
    case lastSentAt = "last_sent_at"
    case lastSendError = "last_send_error"
    case unrecordableCount = "unrecordable_count"
    case automationDenied = "automation_denied"
    case nowPlaying = "now_playing"
  }

  /// A snapshot of the app `pid`, started at `startedAt`, written at `heartbeatAt`, with
  /// nothing else known yet; the caller sets the rest.
  public init(pid: Int, startedAt: Double, heartbeatAt: Double) {
    format = Self.currentFormat
    version = Layout.version
    self.pid = pid
    self.startedAt = startedAt
    self.heartbeatAt = heartbeatAt
  }

  /// Encode every key, writing `null` for an unknown value rather than leaving it out, so
  /// a reader can tell "unknown" from "a key this version does not write".
  public func encode(to encoder: any Encoder) throws {
    var container = encoder.container(keyedBy: CodingKeys.self)
    try container.encode(format, forKey: .format)
    try container.encode(version, forKey: .version)
    try container.encode(pid, forKey: .pid)
    try container.encode(startedAt, forKey: .startedAt)
    try container.encode(heartbeatAt, forKey: .heartbeatAt)
    try container.encode(musicRunning, forKey: .musicRunning)
    try container.encode(playing, forKey: .playing)
    try container.encode(queueBacklog, forKey: .queueBacklog)
    try container.encode(oldestQueuedAt, forKey: .oldestQueuedAt)
    try container.encode(refusedCount, forKey: .refusedCount)
    try container.encode(lastQueuedAt, forKey: .lastQueuedAt)
    try container.encode(lastSentAt, forKey: .lastSentAt)
    try container.encode(lastSendError, forKey: .lastSendError)
    try container.encode(unrecordableCount, forKey: .unrecordableCount)
    try container.encode(automationDenied, forKey: .automationDenied)
    try container.encode(nowPlaying, forKey: .nowPlaying)
  }
}

/// The status file and the open-play file, each replaced atomically.
public struct StateFiles: Sendable {
  /// The heartbeat file.
  public let statusFile: URL
  /// The play still being listened to, saved so a restart can continue it.
  public let openPlayFile: URL

  /// The state files in `stateDir`, which need not exist yet.
  public init(stateDir: URL) {
    statusFile = stateDir.appendingPathComponent("status.json")
    openPlayFile = stateDir.appendingPathComponent("open_play.json")
  }

  /// Replace `status.json` with `status`.
  public func writeStatus(_ status: StatusSnapshot) throws {
    try FileIO.writeAtomically(try RecordCoding.encode(status), to: statusFile)
  }

  /// The largest open-play file read. A saved play is one track's fields and a few
  /// counters, a few KiB at most, so 64 KiB is far past any real one.
  public static let maxOpenPlayBytes = 64 * 1024

  /// Replace the open play with `play`; nil deletes it, and deleting an absent one is fine.
  public func writeOpenPlay<T: Encodable>(_ play: T?) throws {
    guard let play else { return try FileIO.unlinkIfPresent(openPlayFile) }
    try FileIO.writeAtomically(try RecordCoding.encode(play), to: openPlayFile)
  }

  /// The saved open play, or nil when there is none, it is not a regular file within
  /// `maxOpenPlayBytes`, or it cannot be read as `type`: a play that cannot be continued
  /// is simply not continued.
  public func readOpenPlay<T: Decodable>(_ type: T.Type) -> T? {
    guard let data = try? FileIO.readRegularFile(openPlayFile, limit: Self.maxOpenPlayBytes)
    else { return nil }
    return try? RecordCoding.decode(type, from: data)
  }
}
