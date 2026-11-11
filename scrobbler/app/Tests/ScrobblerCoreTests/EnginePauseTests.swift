import Foundation
import Testing

@testable import ScrobblerCore

/// An engine whose play of track one was heard 4 s by its last read at `base + 104`, then
/// paused by a notice at `base + 105`, which carries it 1 s further, to 5000 ms.
func pausedEngine() -> Engine {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  _ = engine.handle(.notice(notice(.paused), at: base + 105))
  return engine
}

@Test func aPauseNoticeCarriesThePositionToThePause() throws {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let paused = engine.handle(.notice(notice(.paused), at: base + 105.8))
  #expect(labels(paused) == ["stop polling", "now paused 5800", "save"])
  _ = engine.handle(.notice(notice(.playing), at: base + 705))
  // The first read after the resume continues from where the pause left the track, so it
  // is heard rather than taken for a scrub.
  let read = engine.handle(.position(position(.playing, 7_800), at: base + 707))
  #expect(labels(read) == ["save"])
  let heard = try #require(engine.openPlay?.heardSeconds)
  // Times near `base` keep about seven decimal digits, so "7.8" holds to a microsecond.
  #expect(abs(heard - 7.8) < 1e-6)
}

@Test func aPauseNoticeBeforeAnyReadAfterARestoreCreditsNothing() {
  var engine = makeEngine()
  _ = engine.handle(.restored(savedPlay(), at: base + 5_000))
  let effects = engine.handle(.notice(notice(.paused), at: base + 5_001))
  #expect(labels(effects) == ["stop polling", "now paused 50000", "save"])
  #expect(engine.openPlay?.heardSeconds == 40)
}

@Test func aPauseStopsPollingAndSavesWhenItBegan() throws {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let effects = engine.handle(.notice(notice(.paused), at: base + 105))
  #expect(labels(effects) == ["stop polling", "now paused 5000", "save"])
  let play = try #require(engine.openPlay)
  #expect(play.pausedAt == base + 105)
  #expect(effects.last == .saveOpenPlay(play))
}

@Test func aPausedReadPausesThePlayAfterCreditingWhatItMoved() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let effects = engine.handle(.position(position(.paused, 5_000), at: base + 106))
  #expect(labels(effects) == ["stop polling", "now paused 5000", "save"])
  #expect(engine.openPlay?.heardSeconds == 5)
}

@Test func aShortPauseResumesTheSamePieceOfTheSamePlay() throws {
  var engine = pausedEngine()
  let effects = engine.handle(.notice(notice(.playing), at: base + 705))
  #expect(labels(effects) == ["start polling", "now playing 5000", "save"])
  let play = try #require(engine.openPlay)
  #expect(play.playID == playID(1))
  #expect(play.piece == 1)
  #expect(play.pausedAt == nil)
  // Heard time counts again from the resume, never across the pause.
  _ = engine.handle(.position(position(.playing, 7_000), at: base + 707))
  #expect(engine.openPlay?.heardSeconds == 7)
}

@Test func aPauseJustUnderTheSplitDoesNotSplit() {
  var engine = pausedEngine()
  let effects = engine.handle(.notice(notice(.playing), at: base + 105 + 1_799.9))
  #expect(enqueued(effects).isEmpty)
  #expect(engine.openPlay?.piece == 1)
}

@Test func aLongPauseClosesThePieceAndOpensTheNextOfTheSamePlay() throws {
  var engine = pausedEngine()
  let effects = engine.handle(.notice(notice(.playing), at: base + 1_905))
  #expect(
    labels(effects) == [
      "enqueue \(trackOne) heard 5 piece 1", "start polling", "now playing 5000", "save",
    ])
  let play = try #require(engine.openPlay)
  #expect(play.playID == playID(1))
  #expect(play.piece == 2)
  #expect(play.startedAt == base + 1_905)
  #expect(play.heardSeconds == 0)
  _ = run(&engine, steadyReads(from: 1_907, firstMs: 7_000, count: 3))
  let record = try #require(enqueued(engine.handle(.musicQuit(at: base + 1_912))).first)
  #expect(info(record).lsPiece == 2)
  #expect(info(record).durationPlayed == 6)
  #expect(info(record).lsPlayID == playID(1))
  #expect(record.payload[0].listenedAt == Int(base) + 1_905)
}

@Test func aLongSilenceIsAPauseFromTheLastObservation() throws {
  var engine = makeEngine()
  _ = engine.handle(.notice(notice(.playing), at: base + 90))
  _ = engine.handle(.position(position(.playing, 10_000), at: base + 100))
  let effects = engine.handle(.position(position(.playing, 12_000), at: base + 7_300))
  #expect(
    labels(effects) == ["enqueue \(trackOne) heard 10 piece 1", "now playing 12000", "save"])
  let play = try #require(engine.openPlay)
  #expect(play.piece == 2)
  #expect(play.startedAt == base + 7_300)
}

@Test func aHeartbeatAfterALongSilenceWaitsForTheNextRead() throws {
  var engine = makeEngine()
  _ = engine.handle(.notice(notice(.playing), at: base + 90))
  _ = engine.handle(.position(position(.playing, 10_000), at: base + 100))
  #expect(engine.handle(.heartbeat(at: base + 7_300)).isEmpty)
  #expect(engine.openPlay?.pausedAt == base + 100)
  // Polling is still on, so the next read tells the engine what the player is doing.
  let effects = engine.handle(.position(position(.paused, 12_000), at: base + 7_302))
  #expect(labels(effects) == ["stop polling", "now paused 12000", "save"])
  #expect(engine.openPlay?.pausedAt == base + 100)
  let resumed = engine.handle(.notice(notice(.playing), at: base + 7_400))
  #expect(
    labels(resumed) == [
      "enqueue \(trackOne) heard 10 piece 1", "start polling", "now playing 12000", "save",
    ])
}

@Test func aLongSilenceWhilePausedKeepsWhenThePauseBegan() {
  var engine = pausedEngine()
  _ = engine.handle(.heartbeat(at: base + 9_000))
  #expect(engine.openPlay?.pausedAt == base + 105)
}

@Test func aLongSilenceWithNoOpenPlayChangesNothing() {
  var engine = makeEngine()
  _ = engine.handle(.heartbeat(at: base + 100))
  #expect(engine.handle(.heartbeat(at: base + 9_000)).isEmpty)
  #expect(engine.openPlay == nil)
}

@Test func quittingMusicClosesThePlay() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let effects = engine.handle(.musicQuit(at: base + 105))
  #expect(
    labels(effects) == [
      "now stopped 5000", "enqueue \(trackOne) heard 4 piece 1", "stop polling", "save nothing",
    ])
  #expect(engine.openPlay == nil)
  var idle = makeEngine()
  #expect(idle.handle(.musicQuit(at: base + 105)).isEmpty)
}

@Test func quittingWhilePausedClosesThePlayWithoutStoppingPollingAgain() {
  var engine = pausedEngine()
  let effects = engine.handle(.musicQuit(at: base + 200))
  #expect(
    labels(effects) == ["now stopped 5000", "enqueue \(trackOne) heard 5 piece 1", "save nothing"])
}

@Test func aStoppedNoticeClosesThePlayAsQuittingDoes() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let effects = engine.handle(.notice(notice(.stopped, nil), at: base + 105))
  #expect(
    labels(effects) == [
      "now stopped 5000", "enqueue \(trackOne) heard 4 piece 1", "stop polling", "save nothing",
    ])
}

@Test func aPausedNoticeWithNoOpenPlayOpensAPausedPlay() throws {
  var engine = makeEngine()
  let effects = engine.handle(.notice(notice(.paused), at: base + 100))
  #expect(labels(effects) == ["read \(trackOne)", "now paused 0", "save"])
  #expect(engine.openPlay?.pausedAt == base + 100)
  #expect(labels(engine.handle(.snapshot(snapshot(), at: base + 101))) == ["now paused 0", "save"])
  let resumed = engine.handle(.notice(notice(.playing), at: base + 110))
  #expect(labels(resumed) == ["start polling", "now playing 0", "save"])
}

@Test func aPausedNoticeForAnotherTrackClosesThePlayAndOpensItPaused() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let effects = engine.handle(.notice(notice(.paused, trackTwo), at: base + 105))
  #expect(
    labels(effects) == [
      "enqueue \(trackOne) heard 4 piece 1", "read \(trackTwo)", "stop polling", "now paused 0",
      "save",
    ])
}

@Test func noticesAloneCreditNothing() {
  // Playing and paused notices half a second apart, with no position read between them:
  // only a read sets the time a pause may carry from, so nothing is heard and nothing queued.
  var engine = makeEngine()
  var effects: [EngineEffect] = []
  for step in 0..<5 {
    effects += engine.handle(.notice(notice(.playing), at: base + Double(step)))
    effects += engine.handle(.notice(notice(.paused), at: base + Double(step) + 0.5))
  }
  #expect(engine.openPlay?.heardSeconds == 0)
  effects += engine.handle(.notice(notice(.stopped), at: base + 5))
  #expect(enqueued(effects).isEmpty)
}

@Test func aPauseAfterAResumeWithoutAReadCreditsNothing() throws {
  var engine = pausedEngine()
  _ = engine.handle(.notice(notice(.playing), at: base + 705))
  _ = engine.handle(.notice(notice(.paused), at: base + 706))
  #expect(engine.openPlay?.heardSeconds == 5)
}
