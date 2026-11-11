import Foundation
import Testing

@testable import ScrobblerCore

// The `stopped` record a play's close sends, so a page goes idle at once rather than after
// the stale window. Every track value is invented; times count from `base`.

/// Every now-playing record the effects carry.
private func nowPlayingRecords(_ effects: [EngineEffect]) -> [NowPlayingRecord] {
  effects.compactMap {
    guard case .nowPlaying(let record) = $0 else { return nil }
    return record
  }
}

/// The only item's info of `record`.
private func info(_ record: NowPlayingRecord) -> AdditionalInfo {
  record.payload[0].trackMetadata.additionalInfo
}

@Test func quittingMusicSendsAStoppedRecordBeforeTheClose() throws {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 3))
  let effects = engine.handle(.musicQuit(at: base + 105))
  #expect(
    labels(effects) == [
      "now stopped 5000", "enqueue \(trackOne) heard 4 piece 1", "stop polling", "save nothing",
    ])
  let stopped = try #require(nowPlayingRecords(effects).first)
  #expect(info(stopped).lsState == .stopped)
  #expect(info(stopped).lsPersistentID == trackOne)
  #expect(info(stopped).lsPlayID == playID(1))
  #expect(info(stopped).lsMeasuredAt == base + 105)
  #expect(stopped.payload[0].trackMetadata.trackName == "Paper Comet")
  #expect(stopped.payload[0].trackMetadata.artistName == "Velvet Marsh")
}

@Test func aStoppedNoticeSendsAStoppedRecordAtTheLastPosition() {
  var engine = pausedEngine()
  let effects = engine.handle(.notice(notice(.stopped, nil), at: base + 200))
  #expect(
    labels(effects) == ["now stopped 5000", "enqueue \(trackOne) heard 5 piece 1", "save nothing"])
}

@Test func aStoppedReadSendsAStoppedRecord() {
  var engine = engineWithOpenPlay()
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 6))
  let effects = engine.handle(.position(position(.stopped, 0, nil), at: base + 112))
  #expect(nowPlayingRecords(effects).map { info($0).lsState } == [.stopped])
  #expect(labels(effects).first == "now stopped 12000")
}

@Test func noStoppedRecordIsSentWhenNoPlayWasOpen() {
  var engine = makeEngine()
  #expect(engine.handle(.musicQuit(at: base + 100)).isEmpty)
  #expect(engine.handle(.notice(notice(.stopped, nil), at: base + 101)).isEmpty)
  #expect(engine.handle(.position(position(.stopped, 0, nil), at: base + 102)).isEmpty)
}

@Test func aPlayThatCannotBeRecordedSendsNoStoppedRecord() {
  var engine = makeEngine()
  _ = engine.handle(.notice(notice(.playing, artist: nil), at: base + 100))
  _ = run(&engine, steadyReads(from: 100, firstMs: 0, count: 6))
  let effects = engine.handle(.musicQuit(at: base + 111))
  #expect(nowPlayingRecords(effects).isEmpty)
}
