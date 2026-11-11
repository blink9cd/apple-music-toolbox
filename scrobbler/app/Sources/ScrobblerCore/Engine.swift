import Foundation

/// The play engine: turns what Music reports into what the scrobbler does.
///
/// It is pure. Every input carries its own time, it reads no clock and touches no file, and
/// it answers each input with the effects the live layer carries out. The rules it keeps:
///
/// - Heard time is measured between consecutive position reads; an interval whose position
///   moved more than `scrubTolerance` away from the time that passed is a scrub and credits
///   nothing, so heard time is undercounted by at most one poll per scrub, never overcounted.
/// - A play heard no more than `minimumHeard` seconds is not queued.
/// - A read back inside the first `repeatWindow` seconds, from a position past it, is the
///   track playing again: the play closes and a new one opens. A jump back that never left
///   the window is a scrub.
/// - A pause of `pauseSplit` seconds or more closes the play's piece, and the resume opens the
///   next piece of the same play. Any input arriving more than `pauseSplit` seconds after the
///   last one, while the play was playing, is a sleep: the play is treated as paused from the
///   last input, so the same split applies on wake.
/// - A restored play continues when the first read finds the same track, crediting nothing
///   for the time the app was not running; any other track closes it with its saved seconds.
public struct Engine: Sendable {
  /// Seconds between position reads while playing.
  public static let pollInterval = 2.0
  /// How far, in seconds, a read may stray from the time that passed and still be heard.
  public static let scrubTolerance = 1.5
  /// The start of the track, in seconds, that a read back into counts as a repeat.
  public static let repeatWindow = 3.0
  /// The pause, in seconds, that splits a play into pieces.
  public static let pauseSplit = 1800.0
  /// Seconds a play must exceed to be queued.
  public static let minimumHeard = 2.0
  /// Seconds between heartbeats.
  public static let heartbeatInterval = 30.0
  /// Milliseconds in a second.
  static let millisecondsPerSecond = 1_000.0
  /// The last piece a play may have; past it the play closes and a new play ID opens.
  static let lastPiece = IntegerBound.lsPiece.range.upperBound

  /// Makes a new play ID.
  private let newPlayID: @Sendable () -> String
  /// The play being listened to.
  public private(set) var openPlay: OpenPlay?
  /// Whether the live layer has been told to poll.
  private var polling = false
  /// When the last input arrived.
  private var lastEventAt: Double?
  /// When `openPlay.lastPositionMs` was read; nil until the first read after a restore.
  private var lastReadAt: Double?
  /// Whether `lastReadAt` came from a position read, or a pause carried from one. A notice
  /// sets the time too but not this, so a pause carries heard time only from a read: any
  /// process can post a notice, and notices alone must never add up to a listen.
  private var baseIsFromRead = false
  /// Whether the last snapshot read was refused by the system.
  private var denied = false
  /// Whether a restored play came back without its snapshot, so the first report of its
  /// track asks for it once more. A read that failed in this run is not retried: it would
  /// fail again on every poll.
  private var snapshotOwed = false

  /// An engine with no open play; `newPlayID` makes each new play's UUID.
  public init(newPlayID: @escaping @Sendable () -> String) {
    self.newPlayID = newPlayID
  }

  /// The effects of `input`, in the order the live layer should carry them out.
  public mutating func handle(_ input: EngineInput) -> [EngineEffect] {
    switch input {
    case .notice(let notice, let time):
      observe(time)
      return applyNotice(notice, at: time)
    case .position(let read, let time):
      observe(time)
      return applyPosition(read, at: time)
    case .snapshot(let snapshot, let time):
      observe(time)
      return applySnapshot(snapshot, at: time)
    case .snapshotFailed(_, let error, let time):
      observe(time)
      return applyReadFailure(error)
    case .musicQuit(let time):
      observe(time)
      return closeAll(at: time)
    case .heartbeat(let time):
      observe(time)
      return heartbeat(at: time)
    case .restored(let play, let time):
      return restore(play, at: time)
    }
  }

  /// Applies the sleep rule, then records `at` as the latest input.
  private mutating func observe(_ time: Double) {
    if let last = lastEventAt, time - last > Self.pauseSplit, var play = openPlay,
      play.pausedAt == nil
    {
      play.pausedAt = last
      openPlay = play
    }
    lastEventAt = time
  }

  /// A notice: a stopped player closes the play, and any other names the current track.
  private mutating func applyNotice(_ notice: PlayerNotice, at time: Double) -> [EngineEffect] {
    guard notice.state != .stopped else { return closeAll(at: time) }
    guard let id = notice.persistentID else { return [] }
    let seen = TrackSeen(
      persistentID: id, state: notice.state, positionMs: nil, durationMs: notice.totalTimeMs,
      name: notice.name, artist: notice.artist, album: notice.album)
    return applyTrack(seen, at: time)
  }

  /// A position read, which a stopped player answers without a track.
  private mutating func applyPosition(_ read: PositionRead, at time: Double) -> [EngineEffect] {
    guard read.state != .stopped else { return closeAll(at: time) }
    guard let id = read.persistentID else { return [] }
    let seen = TrackSeen(
      persistentID: id, state: read.state, positionMs: read.positionMs,
      durationMs: read.durationMs)
    return applyTrack(seen, at: time)
  }

  /// A track reported playing or paused: a new play when it is another track or a repeat,
  /// else the open play carried forward.
  private mutating func applyTrack(_ seen: TrackSeen, at time: Double) -> [EngineEffect] {
    guard let play = openPlay, play.persistentID == seen.persistentID,
      !seen.isRepeat(of: play)
    else {
      let carried =
        openPlay?.persistentID == seen.persistentID ? seen.filling(from: openPlay) : seen
      return closePlay() + beginPlay(carried, at: time)
    }
    var owed: [EngineEffect] = []
    if snapshotOwed {
      snapshotOwed = false
      owed = [.readSnapshot(persistentID: play.persistentID)]
    }
    return owed + applyOpenTrack(seen, play, at: time)
  }

  /// A report of the open play's track, carried forward: a resume, a pause, or a read.
  private mutating func applyOpenTrack(_ seen: TrackSeen, _ play: OpenPlay, at time: Double)
    -> [EngineEffect]
  {
    var play = play
    if let length = seen.durationMs { play.durationMs = length }
    if let pausedAt = play.pausedAt {
      return applyWhilePaused(seen, play, pausedAt: pausedAt, at: time)
    }
    guard let positionMs = seen.positionMs else {
      // A notice for the playing track: a pause, or a duplicate that changes nothing.
      guard seen.state == .paused else {
        openPlay = play
        return []
      }
      carryToPause(&play, at: time)
      openPlay = play
      return applyPause(play, at: time)
    }
    let jumped = creditRead(positionMs, to: &play, at: time)
    openPlay = play
    if seen.state == .paused { return applyPause(play, at: time) }
    return (jumped ? nowPlayingEffect(play, .playing, at: time) : []) + [.saveOpenPlay(play)]
  }

  /// Credits the time since the last read when the position moved with it, and records the
  /// read; returns whether the read jumped, which also holds for the first read after a
  /// restore, since it has nothing to be measured against.
  private mutating func creditRead(_ positionMs: Int, to play: inout OpenPlay, at time: Double)
    -> Bool
  {
    var jumped = true
    if let readAt = lastReadAt, let last = play.lastPositionMs {
      let elapsed = time - readAt
      // In Double, so a corrupt saved position cannot overflow the subtraction.
      let moved = (Double(positionMs) - Double(last)) / Self.millisecondsPerSecond
      jumped = abs(moved - elapsed) > Self.scrubTolerance
      if !jumped { play.heardSeconds += max(0, min(moved, elapsed)) }
    }
    play.lastPositionMs = positionMs
    lastReadAt = time
    baseIsFromRead = true
    return jumped
  }

  /// Carries a playing `play` from its last read to a pause notice at `time`, which says
  /// nothing of the position: the time since the read is credited, at most one poll, and
  /// the position moves with it, so the read after the resume is measured from where the
  /// track paused. The overcount is at most the debounce window by which the notice lags.
  /// With no read since the play began or resumed, nothing is credited.
  private mutating func carryToPause(_ play: inout OpenPlay, at time: Double) {
    guard let readAt = lastReadAt, baseIsFromRead else { return }
    play.heardSeconds += max(0, min(time - readAt, Self.pollInterval))
    play.lastPositionMs = position(of: play, at: time)
    lastReadAt = time
  }

  /// A report on a paused play: a resume, with a split after a long pause, or the pause
  /// carried on.
  private mutating func applyWhilePaused(
    _ seen: TrackSeen, _ play: OpenPlay, pausedAt: Double, at time: Double
  ) -> [EngineEffect] {
    var play = play
    // The position does not move while paused, so this moment becomes the read to measure
    // the next one against.
    if let positionMs = seen.positionMs { play.lastPositionMs = positionMs }
    lastReadAt = time
    baseIsFromRead = seen.positionMs != nil
    guard seen.state == .playing else {
      openPlay = play
      return applyPause(play, at: time)
    }
    var effects: [EngineEffect] = []
    if time - pausedAt >= Self.pauseSplit {
      effects = closeRecord(play)
      play = splitPiece(play, at: time)
    }
    play.pausedAt = nil
    openPlay = play
    return effects + announce(play, .playing, at: time)
  }

  /// Pauses `play` from `at`, or tells the live layer of a pause it has not heard about: one
  /// the sleep rule inferred, or a restored one. A pause already announced changes nothing.
  private mutating func applyPause(_ play: OpenPlay, at time: Double) -> [EngineEffect] {
    guard play.pausedAt == nil || polling else { return [] }
    var play = play
    if play.pausedAt == nil { play.pausedAt = time }
    openPlay = play
    return announce(play, .paused, at: time)
  }

  /// Opens a play of `seen`'s track at `at`, crediting nothing before it.
  private mutating func beginPlay(_ seen: TrackSeen, at time: Double) -> [EngineEffect] {
    let paused = seen.state == .paused
    let play = OpenPlay(
      playID: newID(), piece: 1, persistentID: seen.persistentID, startedAt: time,
      heardSeconds: 0, lastPositionMs: seen.positionMs ?? 0, durationMs: seen.durationMs,
      snapshot: nil, noticeName: seen.name, noticeArtist: seen.artist, noticeAlbum: seen.album,
      pausedAt: paused ? time : nil)
    openPlay = play
    lastReadAt = time
    baseIsFromRead = seen.positionMs != nil
    snapshotOwed = false
    return [.readSnapshot(persistentID: seen.persistentID)]
      + announce(play, paused ? .paused : .playing, at: time)
  }

  /// Closes the open play, queueing its current piece.
  private mutating func closePlay() -> [EngineEffect] {
    guard let play = openPlay else { return [] }
    openPlay = nil
    lastReadAt = nil
    return closeRecord(play)
  }

  /// Music stopped or quit at `time`: a `stopped` record of the play at its last position,
  /// so the pages go idle at once, then the play closes and polling stops.
  private mutating func closeAll(at time: Double) -> [EngineEffect] {
    guard let play = openPlay else { return [] }
    // Built before the close, which forgets the read the position is carried from.
    var effects = nowPlayingEffect(play, .stopped, at: time) + closePlay()
    if polling {
      polling = false
      effects.append(.stopPolling)
    }
    return effects + [.saveOpenPlay(nil)]
  }

  /// A snapshot: fills the open play when it is of the same track.
  private mutating func applySnapshot(_ snap: TrackSnapshot, at time: Double) -> [EngineEffect] {
    // Any snapshot that arrived proves the system lets the scrobbler script Music again.
    var effects: [EngineEffect] = []
    if denied {
      denied = false
      effects.append(.automationDenied(false))
    }
    guard var play = openPlay, snap.persistentID == play.persistentID else { return effects }
    play.snapshot = snap
    if let length = snap.durationMs { play.durationMs = length }
    openPlay = play
    let state: LsState = play.pausedAt == nil ? .playing : .paused
    return effects + nowPlayingEffect(play, state, at: time) + [.saveOpenPlay(play)]
  }

  /// A failed snapshot read: a refusal is reported once; the record falls back to the notice.
  private mutating func applyReadFailure(_ error: SnapshotReadError) -> [EngineEffect] {
    guard error == .automationDenied, !denied else { return [] }
    denied = true
    return [.automationDenied(true)]
  }

  /// Takes up a play saved before the app last stopped, and polls to learn what is playing.
  private mutating func restore(_ play: OpenPlay, at time: Double) -> [EngineEffect] {
    var effects = closePlay()
    openPlay = play
    lastReadAt = nil
    lastEventAt = time
    snapshotOwed = play.snapshot == nil
    if !polling {
      polling = true
      effects.append(.startPolling)
    }
    return effects
  }

  /// Tells the live layer `play` is now in `state`: polling to match, what is playing, and
  /// the play saved.
  private mutating func announce(_ play: OpenPlay, _ state: LsState, at time: Double)
    -> [EngineEffect]
  {
    var effects: [EngineEffect] = []
    let wanted = state == .playing
    if polling != wanted {
      polling = wanted
      effects.append(wanted ? .startPolling : .stopPolling)
    }
    return effects + nowPlayingEffect(play, state, at: time) + [.saveOpenPlay(play)]
  }
}

// The engine's non-mutating helpers, kept apart from the state transitions above.
extension Engine {
  /// The next piece of `play`, starting at `time`; past the last piece, a new play.
  private func splitPiece(_ play: OpenPlay, at time: Double) -> OpenPlay {
    var next = play
    if play.piece >= Self.lastPiece {
      // The new play keeps the snapshot and does not read Music's counts again: a play
      // reaching its last piece is rare, and the snapshot is still this track's.
      next.playID = newID()
      next.piece = 1
    } else {
      next.piece += 1
    }
    next.startedAt = time
    next.heardSeconds = 0
    return next
  }

  /// The listen of `play`'s current piece: queued past the floor, counted when it cannot be
  /// recorded, and nothing at or under the floor.
  private func closeRecord(_ play: OpenPlay) -> [EngineEffect] {
    guard play.heardSeconds > Self.minimumHeard else { return [] }
    guard let record = RecordBuilder.listen(play) else { return [.unrecordable] }
    return [.enqueue(record)]
  }

  /// The heartbeat: what is playing, sent again while it plays.
  private func heartbeat(at time: Double) -> [EngineEffect] {
    guard let play = openPlay, play.pausedAt == nil else { return [] }
    return nowPlayingEffect(play, .playing, at: time)
  }

  /// The now-playing record of `play` in `state` at `at`, when it can be recorded.
  private func nowPlayingEffect(_ play: OpenPlay, _ state: LsState, at time: Double)
    -> [EngineEffect]
  {
    let positionMs = position(of: play, at: time)
    guard
      let record = RecordBuilder.nowPlaying(play, state: state, positionMs: positionMs, at: time)
    else {
      return []
    }
    return [.nowPlaying(record)]
  }

  /// Where `play` is at `time`: the last read, carried forward while playing and held at the
  /// track's end.
  private func position(of play: OpenPlay, at time: Double) -> Int {
    let last = play.lastPositionMs ?? 0
    guard play.pausedAt == nil, let readAt = lastReadAt else { return last }
    // Never carried past the sleep rule's window, so the step is small enough to convert;
    // rounded, since two Unix times this large differ by a fraction just off the true one.
    let elapsed = min(max(0, time - readAt), Self.pauseSplit)
    let (sum, overflow) = last.addingReportingOverflow(
      Int((elapsed * Self.millisecondsPerSecond).rounded()))
    let carried = overflow ? Int.max : sum
    return play.durationMs.map { min(carried, $0) } ?? carried
  }

  /// A new play ID, lowercased: the contract takes only the lowercase form.
  private func newID() -> String {
    newPlayID().lowercased()
  }
}
