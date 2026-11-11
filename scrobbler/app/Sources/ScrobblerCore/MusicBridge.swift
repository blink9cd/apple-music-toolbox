/// The coordinator's view of Music.app: its notices, whether it runs, and the two reads.
///
/// The live layer implements it over the distributed notification center and the two
/// AppleScript reads; tests implement it with scripted answers, so no test reaches Music.
public protocol MusicBridge: AnyObject {
  /// Start listening: `onNotice` gets each playerInfo notice and `onQuit` Music quitting,
  /// both called on the main actor.
  @MainActor func start(
    onNotice: @escaping @MainActor (PlayerNotice) -> Void, onQuit: @escaping @MainActor () -> Void)
  /// Whether Music is running; asking never launches it.
  @MainActor func isMusicRunning() -> Bool
  /// The position script's result, parsed.
  @MainActor func readPosition() -> Result<PositionRead, SnapshotReadError>
  /// The snapshot script's result, parsed.
  @MainActor func readSnapshot() -> Result<TrackSnapshot, SnapshotReadError>
}

/// Where what is playing now goes.
public protocol NowPlayingSink: AnyObject {
  /// Take `record`, the newest word on what is playing.
  @MainActor func publish(_ record: NowPlayingRecord)
}

/// A sink that sends nothing anywhere: it keeps the newest record published, and nothing
/// older.
@MainActor public final class StatusNowPlayingSink: NowPlayingSink {
  /// The newest record published; nil until the first.
  public private(set) var latest: NowPlayingRecord?

  /// A sink holding nothing yet.
  public init() {}

  /// Keep `record` as the newest.
  public func publish(_ record: NowPlayingRecord) {
    latest = record
  }
}

/// A sink handing each record to several others, in the order given: the status sink and
/// the relay's sink run side by side behind the coordinator's one.
@MainActor public final class FanOutNowPlayingSink: NowPlayingSink {
  /// The sinks each record goes to.
  private let sinks: [any NowPlayingSink]

  /// A sink publishing to each of `sinks` in turn.
  public init(_ sinks: [any NowPlayingSink]) {
    self.sinks = sinks
  }

  /// Hand `record` to every sink.
  public func publish(_ record: NowPlayingRecord) {
    for sink in sinks { sink.publish(record) }
  }
}
