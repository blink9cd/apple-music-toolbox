import Foundation
import Testing

@testable import ScrobblerCore

/// A saved play of track one, heard 40 s, last read at 50 s into the track.
func savedPlay(pausedAt: Double? = nil, piece: Int = 1) -> OpenPlay {
  OpenPlay(
    playID: "0f0e0d0c-0b0a-4908-8706-050403020100", piece: piece, persistentID: trackOne,
    startedAt: base + 10, heardSeconds: 40, lastPositionMs: 50_000, durationMs: noticeLength,
    snapshot: snapshot(), noticeName: "Paper Comet", noticeArtist: "Velvet Marsh",
    noticeAlbum: "Tin Harbor", pausedAt: pausedAt)
}

@Test func aRestoredPlayStartsPollingToLearnWhatIsPlaying() {
  var engine = makeEngine()
  let effects = engine.handle(.restored(savedPlay(), at: base + 5_000))
  #expect(labels(effects) == ["start polling"])
  #expect(engine.openPlay == savedPlay())
}

@Test func aRestoredPlayOfTheSameTrackContinuesWithoutCreditingTheGap() {
  var engine = makeEngine()
  _ = engine.handle(.restored(savedPlay(), at: base + 5_000))
  let first = engine.handle(.position(position(.playing, 120_000), at: base + 5_002))
  #expect(labels(first) == ["now playing 120000", "save"])
  #expect(engine.openPlay?.heardSeconds == 40)
  _ = engine.handle(.position(position(.playing, 122_000), at: base + 5_004))
  #expect(engine.openPlay?.heardSeconds == 42)
  #expect(engine.openPlay?.playID == savedPlay().playID)
}

@Test func aRestoredPlayOfAnotherTrackClosesWithItsSavedSeconds() throws {
  var engine = makeEngine()
  _ = engine.handle(.restored(savedPlay(), at: base + 5_000))
  let effects = engine.handle(.position(position(.playing, 3_000, trackTwo), at: base + 5_002))
  #expect(
    labels(effects) == [
      "enqueue \(trackOne) heard 40 piece 1", "read \(trackTwo)", "save",
    ])
  let record = try #require(enqueued(effects).first)
  #expect(info(record).lsPlayID == savedPlay().playID)
  #expect(record.payload[0].listenedAt == Int(base) + 10)
}

@Test func aRestoredPausedPlayFoundStillPausedStopsPolling() {
  var engine = makeEngine()
  _ = engine.handle(.restored(savedPlay(pausedAt: base + 20), at: base + 100))
  let effects = engine.handle(.position(position(.paused, 50_000), at: base + 102))
  #expect(labels(effects) == ["stop polling", "now paused 50000", "save"])
  #expect(engine.openPlay?.pausedAt == base + 20)
}

@Test func aRestoredPausedPlayResumedLongAfterSplits() {
  var engine = makeEngine()
  _ = engine.handle(.restored(savedPlay(pausedAt: base + 20), at: base + 5_000))
  let effects = engine.handle(.position(position(.playing, 50_000), at: base + 5_002))
  #expect(
    labels(effects) == ["enqueue \(trackOne) heard 40 piece 1", "now playing 50000", "save"])
  #expect(engine.openPlay?.piece == 2)
}

@Test func aRestoredPlayWithNoSavedPositionStartsFromTheFirstRead() {
  var play = savedPlay()
  play.lastPositionMs = nil
  var engine = makeEngine()
  _ = engine.handle(.restored(play, at: base + 5_000))
  // Before any read, what is playing is sent from the start of the track.
  #expect(labels(engine.handle(.heartbeat(at: base + 5_001))) == ["now playing 0"])
  _ = engine.handle(.position(position(.playing, 1_000), at: base + 5_002))
  #expect(engine.openPlay?.heardSeconds == 40)
  #expect(engine.openPlay?.playID == play.playID)
}

@Test func restoringOverAnOpenPlayClosesItFirst() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 6))
  let effects = engine.handle(.restored(savedPlay(), at: base + 112))
  // Polling is already on, so only the close remains.
  #expect(labels(effects) == ["enqueue \(trackOne) heard 10 piece 1"])
  #expect(engine.openPlay == savedPlay())
}

@Test func anOpenPlayRoundTripsThroughJSON() throws {
  let play = savedPlay(pausedAt: base + 20)
  let data = try JSONEncoder().encode(play)
  #expect(try JSONDecoder().decode(OpenPlay.self, from: data) == play)
}

@Test func aSnapshotRoundTripsThroughJSON() throws {
  var snap = snapshot()
  snap.year = 2021
  snap.compilation = false
  snap.rating = 80
  snap.dateAdded = 1_700_000_000
  let data = try JSONEncoder().encode(snap)
  #expect(try JSONDecoder().decode(TrackSnapshot.self, from: data) == snap)
}

@Test func aRestoredPlayWithoutASnapshotReadsItAgain() {
  var play = savedPlay()
  play.snapshot = nil
  var engine = makeEngine()
  _ = engine.handle(.restored(play, at: base + 5_000))
  let first = engine.handle(.position(position(.playing, 120_000), at: base + 5_002))
  #expect(labels(first) == ["read \(trackOne)", "now playing 120000", "save"])
  // Asked once: the next read only saves.
  let second = engine.handle(.position(position(.playing, 122_000), at: base + 5_004))
  #expect(labels(second) == ["save"])
}

@Test func aRestoredPlayWithoutASnapshotOfAnotherTrackReadsOnlyTheNewTrack() {
  var play = savedPlay()
  play.snapshot = nil
  var engine = makeEngine()
  _ = engine.handle(.restored(play, at: base + 5_000))
  let opened = engine.handle(.position(position(.playing, 3_000, trackTwo), at: base + 5_002))
  #expect(labels(opened).filter { $0.hasPrefix("read") } == ["read \(trackTwo)"])
  let next = engine.handle(.position(position(.playing, 5_000, trackTwo), at: base + 5_004))
  #expect(labels(next) == ["save"])
}

@Test func aFailedSnapshotReadIsNotRetriedEveryPoll() {
  for error in [SnapshotReadError.malformed("invented"), .noCurrentTrack] {
    var engine = engineWithOpenPlay()
    _ = engine.handle(.snapshotFailed(persistentID: trackOne, error, at: base + 100.5))
    let effects = run(&engine, steadyReads(from: 101, firstMs: 1_000, count: 5))
    #expect(!labels(effects).contains { $0.hasPrefix("read") })
  }
}
