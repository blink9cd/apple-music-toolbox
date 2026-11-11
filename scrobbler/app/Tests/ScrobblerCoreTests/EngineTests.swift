import Foundation
import Testing
import os

@testable import ScrobblerCore

// Every track value in these tests is invented. Times are seconds after `base`, a moment
// inside the contract's listened_at range, so a closed play builds a record.

/// The moment every engine test counts from.
let base = 1_795_000_000.0
/// The first invented track's persistent ID.
let trackOne = "00000000000000A1"
/// The second invented track's persistent ID.
let trackTwo = "00000000000000B2"
/// The invented track length the notices carry.
let noticeLength = 214_000

/// A play ID generator counting from 1, in the lowercase UUID form the contract takes.
func countingIDs() -> @Sendable () -> String {
  let counter = OSAllocatedUnfairLock(initialState: 0)
  return {
    let next = counter.withLock { value -> Int in
      value += 1
      return value
    }
    return String(format: "00000000-0000-4000-8000-%012d", next)
  }
}

/// The play ID `countingIDs` hands out `number`th.
func playID(_ number: Int) -> String {
  String(format: "00000000-0000-4000-8000-%012d", number)
}

/// A fresh engine with counting play IDs.
func makeEngine() -> Engine {
  Engine(newPlayID: countingIDs())
}

/// A notice for `id`, carrying the invented fallback name, artist and album.
func notice(
  _ state: PlayerState, _ id: String? = trackOne, artist: String? = "Velvet Marsh",
  total: Int? = noticeLength
) -> PlayerNotice {
  PlayerNotice(
    state: state, persistentID: id, name: "Paper Comet", artist: artist, album: "Tin Harbor",
    totalTimeMs: total)
}

/// A position read of `id` at `positionMs`.
func position(
  _ state: PlayerState, _ positionMs: Int, _ id: String? = trackOne, duration: Int? = nil
) -> PositionRead {
  PositionRead(state: state, positionMs: positionMs, durationMs: duration, persistentID: id)
}

/// An invented snapshot of `id`.
func snapshot(of id: String = trackOne) -> TrackSnapshot {
  var snap = TrackSnapshot()
  snap.persistentID = id
  snap.trackClass = "file track"
  snap.location = "/Volumes/Invented/Velvet Marsh/Paper Comet.m4a"
  snap.name = "Paper Comet (Album Version)"
  snap.artist = "Velvet Marsh"
  snap.album = "Tin Harbor"
  snap.mediaKind = "song"
  snap.durationMs = 214_500
  snap.musicVersion = "9.9.1"
  return snap
}

/// The engine's effects for each input, concatenated.
func run(_ engine: inout Engine, _ inputs: [EngineInput]) -> [EngineEffect] {
  inputs.flatMap { engine.handle($0) }
}

/// Position reads of `id` every two seconds from `start`, from `firstMs` on.
func steadyReads(from start: Double, firstMs: Int, count: Int, id: String = trackOne)
  -> [EngineInput]
{
  (0..<count).map { step in
    .position(position(.playing, firstMs + step * 2_000, id), at: base + start + Double(step * 2))
  }
}

/// A listen record's only item's info.
func info(_ record: ListenRecord) -> AdditionalInfo {
  record.payload[0].trackMetadata.additionalInfo
}

/// Each effect as a short line, so a sequence reads as the table does.
func labels(_ effects: [EngineEffect]) -> [String] {
  effects.map(label)
}

/// One effect as a short line.
func label(_ effect: EngineEffect) -> String {
  switch effect {
  case .readSnapshot(let id): return "read \(id)"
  case .startPolling: return "start polling"
  case .stopPolling: return "stop polling"
  case .enqueue(let record):
    let item = info(record)
    return "enqueue \(item.lsPersistentID ?? "-") heard \(item.durationPlayed ?? -1) "
      + "piece \(item.lsPiece ?? -1)"
  case .nowPlaying(let record):
    let item = record.payload[0].trackMetadata.additionalInfo
    let millis = Int(((item.lsPositionSeconds ?? -1) * 1_000).rounded())
    return "now \(item.lsState?.rawValue ?? "-") \(millis)"
  case .saveOpenPlay(let play): return play == nil ? "save nothing" : "save"
  case .unrecordable: return "unrecordable"
  case .automationDenied(let denied): return "denied \(denied)"
  }
}

/// Every listen the effects queue.
func enqueued(_ effects: [EngineEffect]) -> [ListenRecord] {
  effects.compactMap {
    guard case .enqueue(let record) = $0 else { return nil }
    return record
  }
}

/// An engine with a play of track one opened by a notice at `base + 100`.
func engineWithOpenPlay() -> Engine {
  var engine = makeEngine()
  _ = engine.handle(.notice(notice(.playing), at: base + 100))
  return engine
}

@Test func aPlayingNoticeOpensAPlay() throws {
  var engine = makeEngine()
  let effects = engine.handle(.notice(notice(.playing), at: base + 100))
  #expect(labels(effects) == ["read \(trackOne)", "start polling", "now playing 0", "save"])
  let play = try #require(engine.openPlay)
  #expect(play.playID == playID(1))
  #expect(play.piece == 1)
  #expect(play.startedAt == base + 100)
  #expect(play.durationMs == noticeLength)
  #expect(play.noticeName == "Paper Comet")
  #expect(play.noticeArtist == "Velvet Marsh")
  #expect(play.noticeAlbum == "Tin Harbor")
  #expect(effects.last == .saveOpenPlay(play))
}

@Test func aPlayingReadWithNoOpenPlayOpensOneCreditingNothingBeforeIt() throws {
  var engine = makeEngine()
  let effects = engine.handle(.position(position(.playing, 95_000), at: base + 100))
  // A read carries no names, so what is playing is sent once the snapshot brings them.
  #expect(labels(effects) == ["read \(trackOne)", "start polling", "save"])
  let play = try #require(engine.openPlay)
  #expect(play.heardSeconds == 0)
  #expect(play.lastPositionMs == 95_000)
  #expect(play.noticeName == nil)
  let filled = engine.handle(.snapshot(snapshot(), at: base + 101))
  #expect(labels(filled) == ["now playing 96000", "save"])
  _ = engine.handle(.position(position(.playing, 97_000), at: base + 102))
  #expect(engine.openPlay?.heardSeconds == 2)
}

@Test func aStoppedReadClosesThePlayAsAStoppedNoticeDoes() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 6))
  let effects = engine.handle(.position(position(.stopped, 0, nil), at: base + 112))
  #expect(
    labels(effects) == [
      "now stopped 12000", "enqueue \(trackOne) heard 10 piece 1", "stop polling",
      "save nothing",
    ])
  #expect(engine.openPlay == nil)
}

@Test func steadyReadsCreditTheTimeBetweenThem() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  #expect(engine.openPlay?.heardSeconds == 4)
}

@Test func aReadThatJumpedCreditsNothingAndSendsTheNewPosition() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, 10_000), at: base + 110))
  #expect(engine.openPlay?.heardSeconds == 10)
  let effects = engine.handle(.position(position(.playing, 60_000), at: base + 112))
  #expect(labels(effects) == ["now playing 60000", "save"])
  #expect(engine.openPlay?.heardSeconds == 10)
}

@Test func aReadThatLagsCreditsOnlyThePositionItMoved() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, 1_000), at: base + 102))
  #expect(engine.openPlay?.heardSeconds == 1)
}

@Test func eachReadRefreshesTheLengthTheRecordCarries() throws {
  var engine = engineWithOpenPlay()
  #expect(engine.openPlay?.durationMs == 214_000)
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 5))
  _ = engine.handle(.position(position(.playing, 10_000, duration: 215_000), at: base + 110))
  let closed = enqueued(engine.handle(.musicQuit(at: base + 111)))
  #expect(info(try #require(closed.first)).durationMs == 215_000)
}

@Test func aPlayHeardTwoSecondsOrLessIsNotQueued() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, 1_900), at: base + 101.9))
  let effects = engine.handle(.notice(notice(.playing, trackTwo), at: base + 102))
  #expect(labels(effects) == ["read \(trackTwo)", "now playing 0", "save"])

  var exact = engineWithOpenPlay()
  _ = exact.handle(.position(position(.playing, 2_000), at: base + 102))
  #expect(enqueued(exact.handle(.musicQuit(at: base + 103))).isEmpty)
}

@Test func aPlayHeardJustOverTwoSecondsIsQueued() throws {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, 2_500), at: base + 102.5))
  let closed = enqueued(engine.handle(.musicQuit(at: base + 103)))
  #expect(info(try #require(closed.first)).durationPlayed == 2)
}

@Test func aNewTrackClosesTheOpenPlayAndOpensAnother() throws {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 102, firstMs: 2_000, count: 15))
  let effects = engine.handle(.notice(notice(.playing, trackTwo), at: base + 131))
  #expect(
    labels(effects) == [
      "enqueue \(trackOne) heard 30 piece 1", "read \(trackTwo)", "now playing 0", "save",
    ])
  let record = try #require(enqueued(effects).first)
  #expect(record.payload[0].listenedAt == Int(base) + 100)
  #expect(engine.openPlay?.persistentID == trackTwo)
  #expect(engine.openPlay?.playID == playID(2))
}

@Test func aReadBackToTheStartAfterTheRepeatWindowStartsANewPlay() throws {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, 200_000), at: base + 300))
  let effects = engine.handle(.position(position(.playing, 1_000), at: base + 302))
  #expect(
    labels(effects) == [
      "enqueue \(trackOne) heard 200 piece 1", "read \(trackOne)", "now playing 1000", "save",
    ])
  let play = try #require(engine.openPlay)
  #expect(play.playID == playID(2))
  #expect(play.persistentID == trackOne)
  #expect(play.heardSeconds == 0)
  // The repeat keeps the notice's fallbacks, since it is the same track.
  #expect(play.noticeArtist == "Velvet Marsh")
}

@Test func aBackwardJumpNearTheStartIsAScrubNotARepeat() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, 2_500), at: base + 102.5))
  let effects = engine.handle(.position(position(.playing, 1_000), at: base + 104.5))
  #expect(labels(effects) == ["now playing 1000", "save"])
  #expect(engine.openPlay?.playID == playID(1))
}

@Test func aSnapshotForTheOpenTrackFillsThePlay() throws {
  var engine = engineWithOpenPlay()
  let effects = engine.handle(.snapshot(snapshot(), at: base + 100.5))
  // The position is carried forward from the notice's start to the snapshot's arrival.
  #expect(labels(effects) == ["now playing 500", "save"])
  let play = try #require(engine.openPlay)
  #expect(play.snapshot == snapshot())
  #expect(play.durationMs == 214_500)
  guard case .nowPlaying(let record) = effects[0] else {
    Issue.record("expected a now-playing record")
    return
  }
  #expect(record.payload[0].trackMetadata.trackName == "Paper Comet (Album Version)")
}

@Test func aSnapshotForAnotherTrackIsIgnored() {
  var engine = engineWithOpenPlay()
  let before = engine.openPlay
  #expect(engine.handle(.snapshot(snapshot(of: trackTwo), at: base + 101)).isEmpty)
  #expect(engine.openPlay == before)
  var empty = makeEngine()
  #expect(empty.handle(.snapshot(snapshot(), at: base + 101)).isEmpty)
}

@Test func aSnapshotWithoutALengthKeepsTheNoticeLength() {
  var engine = engineWithOpenPlay()
  var snap = snapshot()
  snap.durationMs = nil
  _ = engine.handle(.snapshot(snap, at: base + 101))
  #expect(engine.openPlay?.durationMs == noticeLength)
}

@Test func aDeniedReadIsReportedOnceAndTheRecordFallsBackToTheNotice() throws {
  var engine = engineWithOpenPlay()
  let denied = EngineInput.snapshotFailed(
    persistentID: trackOne, .automationDenied, at: base + 100.5)
  #expect(labels(engine.handle(denied)) == ["denied true"])
  #expect(engine.handle(denied).isEmpty)
  _ = run(&engine, steadyReads(from: 101, firstMs: 1_000, count: 5))
  let record = try #require(enqueued(engine.handle(.musicQuit(at: base + 110))).first)
  let metadata = record.payload[0].trackMetadata
  #expect(metadata.trackName == "Paper Comet")
  #expect(metadata.artistName == "Velvet Marsh")
  #expect(metadata.releaseName == "Tin Harbor")
}

@Test func aSnapshotAfterADenialReportsAccessRestored() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.snapshotFailed(persistentID: trackOne, .automationDenied, at: base + 101))
  let effects = engine.handle(.snapshot(snapshot(of: trackTwo), at: base + 102))
  #expect(labels(effects) == ["denied false"])
}

@Test func anyOtherReadFailureChangesNothing() {
  var engine = engineWithOpenPlay()
  let failure = EngineInput.snapshotFailed(
    persistentID: trackOne, .malformed("invented"), at: base + 101)
  #expect(engine.handle(failure).isEmpty)
}

@Test func aPlayWithNoArtistAnywhereIsCountedNotQueued() {
  var engine = makeEngine()
  let opened = engine.handle(.notice(notice(.playing, artist: nil), at: base + 100))
  #expect(labels(opened) == ["read \(trackOne)", "start polling", "save"])
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 6))
  let effects = engine.handle(.musicQuit(at: base + 111))
  #expect(labels(effects) == ["unrecordable", "stop polling", "save nothing"])
}

@Test func theHeartbeatSendsTheExtrapolatedPositionWhilePlaying() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  #expect(labels(engine.handle(.heartbeat(at: base + 110))) == ["now playing 10000"])
  // Never past the track's end.
  #expect(labels(engine.handle(.heartbeat(at: base + 1_000))) == ["now playing 214000"])
}

@Test func theHeartbeatSendsNothingWhilePausedOrIdle() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.notice(notice(.paused), at: base + 104))
  #expect(engine.handle(.heartbeat(at: base + 110)).isEmpty)
  var idle = makeEngine()
  #expect(idle.handle(.heartbeat(at: base + 110)).isEmpty)
}

@Test func theHeartbeatHoldsAtTheLargestPositionRatherThanOverflowing() {
  var engine = engineWithOpenPlay()
  _ = engine.handle(.position(position(.playing, Int.max, duration: nil), at: base + 102))
  #expect(engine.openPlay?.durationMs == noticeLength)
  #expect(labels(engine.handle(.heartbeat(at: base + 104))) == ["now playing 214000"])
  var unknownLength = makeEngine()
  _ = unknownLength.handle(.notice(notice(.playing, total: nil), at: base + 100))
  _ = unknownLength.handle(.position(position(.playing, Int.max), at: base + 102))
  let effects = unknownLength.handle(.heartbeat(at: base + 104))
  #expect(labels(effects) == ["now playing 2073600000"])
}

@Test func theSameNoticeTwiceYieldsNothingTheSecondTime() {
  for state in [PlayerState.playing, .paused, .stopped] {
    var engine = engineWithOpenPlay()
    _ = engine.handle(.notice(notice(state), at: base + 101))
    #expect(engine.handle(.notice(notice(state), at: base + 101.2)).isEmpty)
  }
}

@Test func everyReadWhilePlayingEndsBySavingThePlay() {
  var engine = engineWithOpenPlay()
  for input in steadyReads(from: 100, firstMs: 0, count: 4) {
    let effects = engine.handle(input)
    #expect(effects.last == .saveOpenPlay(engine.openPlay))
  }
}

@Test func aReadOrNoticeWithoutATrackIDIsIgnored() {
  var engine = engineWithOpenPlay()
  let before = engine.openPlay
  #expect(engine.handle(.position(position(.playing, 4_000, nil), at: base + 102)).isEmpty)
  #expect(engine.handle(.notice(notice(.playing, nil), at: base + 103)).isEmpty)
  #expect(engine.openPlay == before)
}

@Test func playIDsAreLowercasedWhateverTheGeneratorWrites() {
  var engine = Engine(newPlayID: { "ABCDEF00-0000-4000-8000-00000000000A" })
  _ = engine.handle(.notice(notice(.playing), at: base + 100))
  #expect(engine.openPlay?.playID == "abcdef00-0000-4000-8000-00000000000a")
}

@Test func theEngineConstantsHoldTheirDocumentedValues() {
  #expect(Engine.pollInterval == 2.0)
  #expect(Engine.scrubTolerance == 1.5)
  #expect(Engine.repeatWindow == 3.0)
  #expect(Engine.pauseSplit == 1800.0)
  #expect(Engine.minimumHeard == 2.0)
  #expect(Engine.heartbeatInterval == 30.0)
}
